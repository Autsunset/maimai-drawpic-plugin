"""提交被取消时仍等待原子持久化结束，避免留下未受跟踪的线程写入。"""

from typing import Any
from functools import wraps
import asyncio

from ...domain.task_errors import task_error
from ...infrastructure.storage.tasks import DrawTaskRecord, DrawTaskStore


def tracked_submission(method):
    @wraps(method)
    async def run(self, *args: Any, **kwargs: Any):
        with self.submission_scope():
            return await method(self, *args, **kwargs)
    return run


async def wait_for_admission(pending: asyncio.Task[Any]) -> Any:
    """Finish an owned IO operation even if the caller is cancelled repeatedly."""
    while not pending.done():
        try:
            await asyncio.shield(pending)
        except asyncio.CancelledError:
            continue
    return pending.result()


async def update_task_owned(store: DrawTaskStore, task_id: str, **changes: Any) -> DrawTaskRecord | None:
    """Wait for an in-flight status write before letting cancellation set a terminal state."""
    pending = asyncio.create_task(asyncio.to_thread(store.update_task, task_id, **changes))
    try:
        return await asyncio.shield(pending)
    except asyncio.CancelledError:
        await wait_for_admission(pending)
        raise


async def persist_submission(store: DrawTaskStore, **kwargs: Any) -> DrawTaskRecord:
    pending = asyncio.create_task(asyncio.to_thread(store.create_task, **kwargs))
    try:
        return await asyncio.shield(pending)
    except asyncio.CancelledError:
        record = await wait_for_admission(pending)
        cleanup = asyncio.create_task(asyncio.to_thread(
            store.update_task,
            record.task_id,
            status="failed",
            message="提交等待已取消，尚未启动绘图",
            error=task_error("SUBMISSION_INTERRUPTED", "任务已落盘但执行尚未启动", retry_submit=True),
        ))
        await wait_for_admission(cleanup)
        raise
