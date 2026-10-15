"""在宿主日志、任务持久化和公开结果共享同一组实例密钥。"""

from threading import RLock
from typing import Any, Dict, Iterable
import logging

from ..http import sanitize_provider_text


class SecretRedactor(logging.Filter):
    """插件存活期间保留已知密钥，配置轮换不会暴露旧任务的诊断。"""

    def __init__(self) -> None:
        super().__init__()
        self._lock = RLock()
        self._secrets = set()

    def add(self, values: Iterable[str]) -> None:
        with self._lock:
            self._secrets.update(value for value in values if value)

    def add_config(self, values: Dict[str, Any]) -> None:
        pending, secrets = [values], []
        while pending:
            item = pending.pop()
            if isinstance(item, dict):
                secrets.extend(
                    value for key, value in item.items() if key in {"api_key", "password"} and isinstance(value, str)
                )
                pending.extend(item.values())
            elif isinstance(item, list):
                pending.extend(item)
        self.add(secrets)

    def redact(self, value: Any, *, max_chars: int = 2000) -> str:
        text = str(value)
        with self._lock:
            for secret in sorted(self._secrets, key=len, reverse=True):
                text = text.replace(secret, "[REDACTED]")
        return sanitize_provider_text(text, max_chars=max_chars)

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = self.redact(record.getMessage(), max_chars=4000)
        record.args = ()
        if record.exc_info:
            record.exc_text = self.redact(logging.Formatter().formatException(record.exc_info), max_chars=12000)
            record.exc_info = None
        return True
