"""在后台线程中保存插件脱敏日志。"""

from hashlib import sha256
from logging.handlers import QueueHandler, QueueListener, RotatingFileHandler
from pathlib import Path
from queue import Empty, Full, Queue
from threading import Lock
from typing import Callable, List
import logging
import re

from ..http import normalize_provider_diagnostic, sanitize_provider_text


class _RedactedFormatter(logging.Formatter):
    def __init__(self, secrets: Callable[[], List[str]], fmt: str = "%(asctime)s | %(levelname)s | %(message)s") -> None:
        super().__init__(fmt, datefmt="%Y-%m-%d %H:%M:%S")
        self.secrets = secrets

    def format(self, record: logging.LogRecord) -> str:
        text = normalize_provider_diagnostic(super().format(record))
        for secret in self.secrets():
            if secret:
                text = text.replace(secret, "[REDACTED]")
        return sanitize_provider_text(text)


class _BoundedQueueHandler(QueueHandler):
    """Drop newest records under backpressure; never wait for file I/O."""

    def __init__(self, secrets: Callable[[], List[str]], capacity: int) -> None:
        super().__init__(Queue(maxsize=capacity))
        self.setFormatter(_RedactedFormatter(secrets, "%(message)s"))
        self.dropped_records = 0
        self.accepting = True

    def enqueue(self, record: logging.LogRecord) -> None:
        # Handler.handle holds its RLock, also used when disabling producers.
        if not self.accepting:
            self.dropped_records += 1
            return
        try:
            self.queue.put_nowait(record)
        except Full:
            self.dropped_records += 1


class _BoundedQueueListener(QueueListener):
    def __init__(self, queue_handler: _BoundedQueueHandler, sink: logging.Handler) -> None:
        super().__init__(queue_handler.queue, sink)
        self.queue_handler = queue_handler
        self.reported_drops = 0

    def handle(self, record: logging.LogRecord) -> None:
        handler = self.queue_handler
        handler.acquire()
        try:
            dropped = handler.dropped_records
        finally:
            handler.release()
        if dropped > self.reported_drops:
            # Write directly to the sink, never back into the saturated queue.
            warning = logging.LogRecord(
                "drawpic.logs", logging.WARNING, __file__, 0,
                "日志队列容量不足，已丢弃 %s 条日志（累计 %s 条）",
                (dropped - self.reported_drops, dropped), None,
            )
            super().handle(warning)
            self.reported_drops = dropped
        super().handle(record)

    def enqueue_sentinel(self) -> None:
        handler = self.queue_handler
        handler.acquire()
        try:
            handler.accepting = False
            while True:
                try:
                    self.queue.put_nowait(self._sentinel)
                    return
                except Full:
                    try:
                        self.queue.get_nowait()
                    except Empty:
                        continue
                    self.queue.task_done()
                    handler.dropped_records += 1
        finally:
            handler.release()


class WorkspaceLogStore:
    def __init__(
        self, data_dir: Path, logger: logging.Logger, secrets: Callable[[], List[str]], max_mb: int = 10
    ) -> None:
        self.path = data_dir / "logs" / "drawpic.log"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.logger = logger
        self.file_handler = RotatingFileHandler(self.path, maxBytes=1024 * 1024, backupCount=3, encoding="utf-8")
        self.file_handler.setFormatter(_RedactedFormatter(secrets))
        self.configure_limit(max_mb)
        self._close_lock = Lock()
        self._closed = False
        self.queue_handler = _BoundedQueueHandler(secrets, capacity=256)
        self.listener = _BoundedQueueListener(self.queue_handler, self.file_handler)
        self.logger.addHandler(self.queue_handler)
        self.listener.start()

    def configure_limit(self, max_mb: int) -> None:
        """总配额分给当前文件与三份备份；调低配置后立即清理超额旧日志。"""
        if type(max_mb) is not int or not 1 <= max_mb <= 1024:
            raise ValueError("日志容量应为 1～1024 MB")
        budget = max_mb * 1024 * 1024
        self.file_handler.acquire()
        try:
            self.file_handler.maxBytes = budget // 4
            if self.path.exists() and self.path.stat().st_size >= self.file_handler.maxBytes:
                self.file_handler.doRollover()
            backups = [self.path.with_name(f"{self.path.name}.{index}") for index in (3, 2, 1)]
            total = sum(path.stat().st_size for path in [self.path, *backups] if path.exists())
            for path in backups:
                if total <= budget:
                    break
                if path.exists():
                    total -= path.stat().st_size
                    path.unlink()
        finally:
            self.file_handler.release()

    def close(self) -> None:
        # Called by lifecycle in a worker thread: actual filesystem I/O can
        # still block, but the backlog is bounded and a full queue cannot
        # prevent the stop signal. Repeated/concurrent closes are harmless.
        with self._close_lock:
            if self._closed:
                return
            self.logger.removeHandler(self.queue_handler)
            self.listener.stop()
            self.file_handler.close()
            self._closed = True

    @property
    def dropped_records(self) -> int:
        self.queue_handler.acquire()
        try:
            return self.queue_handler.dropped_records
        finally:
            self.queue_handler.release()

    def query(self, task_id: str = "", level: str = "", limit: int = 120, cursor: str = "") -> dict:
        if type(limit) is not int or not 1 <= limit <= 300:
            raise ValueError("日志条数应为 1～300")
        if not isinstance(task_id, str) or not re.fullmatch(r"[a-f0-9]{0,12}", task_id):
            raise ValueError("日志任务筛选应为最多 12 位十六进制 ID")
        if level and level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError("日志级别无效")
        dropped = self.dropped_records
        # 轮转与读取共享文件锁；未变化时不读文件、不重复传输日志。
        self.file_handler.acquire()
        try:
            if not self.path.exists():
                return {"lines": [], "total": 0, "cursor": "", "unchanged": False, "dropped_records": dropped}
            stat = self.path.stat()
            revision = sha256(
                f"{stat.st_ino}:{stat.st_size}:{stat.st_mtime_ns}:{task_id}:{level}:{limit}:{dropped}".encode()
            ).hexdigest()[:24]
            if cursor == revision:
                return {"lines": [], "cursor": revision, "unchanged": True, "dropped_records": dropped}
            selected, pending = [], b""
            with self.path.open("rb") as handle:
                position = stat.st_size
                while position > 0 and len(selected) < limit:
                    size = min(position, 16384)
                    position -= size
                    handle.seek(position)
                    parts = (handle.read(size) + pending).split(b"\n")
                    pending = parts.pop(0) if position else b""
                    for raw in reversed(parts):
                        line = raw.decode("utf-8", errors="replace").rstrip("\r")
                        if (
                            line
                            and (not task_id or f"task_id={task_id}" in line)
                            and (not level or f"| {level} |" in line)
                        ):
                            selected.append(line)
                            if len(selected) == limit:
                                break
            return {"lines": list(reversed(selected)), "total": len(selected), "cursor": revision, "unchanged": False, "dropped_records": dropped}
        finally:
            self.file_handler.release()
