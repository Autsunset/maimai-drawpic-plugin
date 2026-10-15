"""提交被取消时仍等待原子持久化结束，避免留下未受跟踪的线程写入。"""

from typing import Any
import asyncio

from ...domain.task_errors import task_error
from ...infrastructure.storage.tasks import DrawTaskRecord, DrawTaskStore


async def persist_submission(store: DrawTaskStore, **kwargs: Any) -> DrawTaskRecord:
    pending = asyncio.create_task(asyncio.to_thread(store.create_task, **kwargs))
    try:
        return await asyncio.shield(pending)
    except asyncio.CancelledError:
        record = await pending
        await asyncio.to_thread(
            store.update_task,
            record.task_id,
            status="failed",
            message="提交等待已取消，尚未启动绘图",
            error=task_error("SUBMISSION_INTERRUPTED", "任务已落盘但执行尚未启动", retry_submit=True),
        )
        raise
