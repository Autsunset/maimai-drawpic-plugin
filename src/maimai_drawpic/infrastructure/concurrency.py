"""同步存储对象在事件循环及工作线程之间共享状态时使用的互斥边界。"""

from functools import wraps
from typing import Any, Callable


def synchronized(method: Callable) -> Callable:
    @wraps(method)
    def locked(self: Any, *args: Any, **kwargs: Any) -> Any:
        with self._lock:
            return method(self, *args, **kwargs)

    return locked
