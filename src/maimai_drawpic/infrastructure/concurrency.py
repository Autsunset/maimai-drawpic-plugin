"""同步存储对象在事件循环及工作线程之间共享状态时使用的互斥边界。"""

from functools import wraps
from typing import Any, Callable, TypeVar
import asyncio

T = TypeVar("T")


async def wait_owned(pending: "asyncio.Task[T]") -> T:
    """即使反复取消，也等已归属的操作结束，避免回滚与残留写线程并行。"""
    while not pending.done():
        try:
            await asyncio.shield(pending)
        except asyncio.CancelledError:
            continue
    return pending.result()


async def run_owned_thread(function: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """保留取消语义，但先等同步操作完成，再允许生命周期清理或回滚。"""
    pending = asyncio.create_task(asyncio.to_thread(function, *args, **kwargs))
    try:
        return await asyncio.shield(pending)
    except asyncio.CancelledError:
        await wait_owned(pending)
        raise


def synchronized(method: Callable) -> Callable:
    @wraps(method)
    def locked(self: Any, *args: Any, **kwargs: Any) -> Any:
        with self._lock:
            return method(self, *args, **kwargs)

    return locked
