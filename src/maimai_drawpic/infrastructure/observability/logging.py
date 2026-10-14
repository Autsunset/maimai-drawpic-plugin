"""在后台线程中保存插件脱敏日志。"""

from hashlib import sha256
from logging.handlers import QueueHandler, QueueListener, RotatingFileHandler
from pathlib import Path
from queue import SimpleQueue
from typing import Callable, List
import logging
import re

from ..http import sanitize_provider_text


class _RedactedFormatter(logging.Formatter):
    def __init__(self, secrets: Callable[[], List[str]]) -> None:
        super().__init__("%(asctime)s | %(levelname)s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
        self.secrets = secrets

    def format(self, record: logging.LogRecord) -> str:
        text = super().format(record)
        for secret in self.secrets():
            if secret:
                text = text.replace(secret, "[REDACTED]")
        return sanitize_provider_text(text)


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
        self.queue_handler = QueueHandler(SimpleQueue())
        self.listener = QueueListener(self.queue_handler.queue, self.file_handler)
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
        self.logger.removeHandler(self.queue_handler)
        self.listener.stop()
        self.file_handler.close()

    def query(self, task_id: str = "", level: str = "", limit: int = 120, cursor: str = "") -> dict:
        if type(limit) is not int or not 1 <= limit <= 300:
            raise ValueError("日志条数应为 1～300")
        if not isinstance(task_id, str) or not re.fullmatch(r"[a-f0-9]{0,12}", task_id):
            raise ValueError("日志任务筛选应为最多 12 位十六进制 ID")
        if level and level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError("日志级别无效")
        # 轮转与读取共享文件锁；未变化时不读文件、不重复传输日志。
        self.file_handler.acquire()
        try:
            if not self.path.exists():
                return {"lines": [], "total": 0, "cursor": "", "unchanged": False}
            stat = self.path.stat()
            revision = sha256(
                f"{stat.st_ino}:{stat.st_size}:{stat.st_mtime_ns}:{task_id}:{level}:{limit}".encode()
            ).hexdigest()[:24]
            if cursor == revision:
                return {"lines": [], "cursor": revision, "unchanged": True}
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
            return {"lines": list(reversed(selected)), "total": len(selected), "cursor": revision, "unchanged": False}
        finally:
            self.file_handler.release()
