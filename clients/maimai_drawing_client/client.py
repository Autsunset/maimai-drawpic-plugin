"""有界等待的正式客户端，所有路径共用 submit/task/image 幂等任务协议。"""

from pathlib import Path
from typing import Any, Dict, Optional, Union
from uuid import uuid4
import asyncio
import math
import re

from .images import read_image, save_bytes
from .models import DrawingError, DrawingResult, DrawingTransportError, GeneratedImage, TaskHandle
from .transport import APIProxy, DrawingRPC


class DrawingClient:
    def __init__(
        self,
        api: APIProxy,
        *,
        rpc_timeout: float = 8,
        poll_interval: float = 3,
        max_image_bytes: int = 64 * 1024 * 1024,
        max_result_bytes: int = 128 * 1024 * 1024,
    ) -> None:
        if not math.isfinite(rpc_timeout) or not 0 < rpc_timeout <= 30:
            raise ValueError("rpc_timeout 应为 0～30 秒（不含 0）")
        if not math.isfinite(poll_interval) or not 0 < poll_interval <= 60:
            raise ValueError("poll_interval 应为 0～60 秒（不含 0）")
        if (
            type(max_image_bytes) is not int
            or type(max_result_bytes) is not int
            or min(max_image_bytes, max_result_bytes) <= 0
        ):
            raise ValueError("图片与单次结果容量限制必须为正整数")
        self.rpc = DrawingRPC(api, rpc_timeout)
        self.poll_interval, self.max_image_bytes, self.max_result_bytes = (
            poll_interval,
            max_image_bytes,
            max_result_bytes,
        )

    @staticmethod
    def _budget(seconds: float) -> float:
        if not math.isfinite(seconds) or not 0 < seconds <= 3600:
            raise ValueError("等待预算必须为有限的 0～3600 秒（不含 0）")
        return seconds

    async def submit(self, prompt: str, *, request_id: Optional[str] = None, **kwargs: Any) -> TaskHandle:
        """立即返回句柄；响应不确定时保留 request_id，绝不换键重画。"""
        request_id = uuid4().hex if request_id is None else request_id
        if not isinstance(request_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{8,80}", request_id):
            raise ValueError("request_id 应为 8～80 位字母、数字、下划线或横线；省略时自动生成")
        try:
            result = await self.rpc.call("submit", prompt=prompt, request_id=request_id, **kwargs)
            # 回执不完整时无法证明未受理，保留原幂等键供调用方恢复。
            if result.get("accepted") is True:
                if (
                    not isinstance(result.get("task_id"), str)
                    or not result["task_id"]
                    or not isinstance(result.get("status"), str)
                    or type(result.get("reused")) is not bool
                ):
                    raise DrawingTransportError("提交回执缺少任务信息")
            elif result.get("accepted") is not False or not isinstance(result.get("error"), dict):
                raise DrawingTransportError("提交回执缺少受理状态或错误信息")
        except DrawingTransportError as exc:
            error = DrawingError(
                {"code": "SUBMISSION_UNKNOWN", "message": str(exc), "retry_submit": False}, request_id=request_id
            )
            return TaskHandle(None, request_id, "submission_unknown", error=error)
        if result.get("accepted") is not True:
            raise DrawingError(result["error"], request_id=request_id)
        return TaskHandle(result["task_id"], request_id, result["status"], result["reused"])

    async def task(self, task_id: str) -> Dict[str, Any]:
        result = await self.rpc.call("task", task_id=task_id)
        if result.get("task_id") is None:
            raise DrawingError(result["error"], task_id=task_id)
        return result

    async def cancel(self, task_id: str) -> Dict[str, Any]:
        result = await self.rpc.call("cancel", task_id=task_id)
        if result.get("task_id") is None:
            raise DrawingError(result["error"], task_id=task_id)
        return result

    async def read_image(self, task_id: str, index: int = 0) -> bytes:
        return await read_image(self.rpc, task_id, index, self.max_image_bytes)

    async def save_image(
        self, task_id: str, destination: Union[str, Path], index: int = 0, *, overwrite: bool = False
    ) -> Path:
        """保存到调用方明确选择的授予目录；不会使用上游文件名拼接路径。"""
        raw = await self.read_image(task_id, index)
        return await asyncio.to_thread(save_bytes, Path(destination), raw, overwrite)

    async def _wait(self, handle: TaskHandle, result: DrawingResult, read_images: bool) -> DrawingResult:
        while True:
            try:
                snapshot = await self.task(handle.task_id)
            except DrawingTransportError:
                # 只重试只读查询，外层总预算负责结束等待。
                await asyncio.sleep(self.poll_interval)
                continue
            result.status = snapshot["status"]
            result.image_references = snapshot["images"]
            result.generation_completed = snapshot["generation_completed"]
            result.results_readable = snapshot["results_readable"]
            result.delivery = snapshot["delivery"]
            result.retry_after_ms = snapshot["retry_after_ms"]
            result.error = (
                DrawingError(snapshot["error"], task_id=handle.task_id, request_id=handle.request_id)
                if snapshot["error"]
                else None
            )
            if result.status not in {"pending", "running"}:
                if read_images and result.image_references:
                    if sum(item["size"] for item in result.image_references) > self.max_result_bytes:
                        raise ValueError("图片总大小超过客户端单次结果限制")
                    for image in result.image_references:
                        try:
                            raw = await self.read_image(handle.task_id, image["index"])
                        except DrawingError as exc:
                            result.error, result.results_readable = exc, False
                            break
                        except DrawingTransportError:
                            result.error = DrawingError(
                                {
                                    "code": "RESULT_UNAVAILABLE",
                                    "message": "结果读取响应未确认，可继续读取原任务图片",
                                    "retry_query": True,
                                },
                                task_id=handle.task_id,
                                request_id=handle.request_id,
                            )
                            result.results_readable = False
                            break
                        result.images.append(GeneratedImage(raw, image))
                return result
            await asyncio.sleep(max(self.poll_interval, snapshot["retry_after_ms"] / 1000))

    async def wait(
        self, task: Union[TaskHandle, str], *, request_id: str = "", wait_seconds: float = 120, read_images: bool = True
    ) -> DrawingResult:
        """等待结束保留任务状态与句柄，不取消远端，也不标成绘图失败。"""
        budget = self._budget(wait_seconds)
        handle = task if isinstance(task, TaskHandle) else TaskHandle(task, request_id)
        result = DrawingResult(handle.task_id, handle.request_id, handle.status, error=handle.error)
        if handle.task_id is None:
            return result
        try:
            async with asyncio.timeout(budget):
                return await self._wait(handle, result, read_images)
        except TimeoutError:
            result.wait_expired = True
            return result

    async def generate(
        self,
        prompt: str,
        *,
        request_id: Optional[str] = None,
        wait_seconds: float = 120,
        read_images: bool = True,
        **kwargs: Any,
    ) -> DrawingResult:
        """一次 await 完成提交、短查询和读取；总预算包含所有 RPC、sleep 与图片读取。"""
        budget = self._budget(wait_seconds)
        request_id = uuid4().hex if request_id is None else request_id
        result = DrawingResult(None, request_id, "submission_unknown")
        try:
            async with asyncio.timeout(budget):
                handle = await self.submit(prompt, request_id=request_id, **kwargs)
                result.task_id, result.status, result.error = handle.task_id, handle.status, handle.error
                if handle.task_id is None:
                    return result
                return await self._wait(handle, result, read_images)
        except TimeoutError:
            result.wait_expired = True
            if result.task_id is None:
                result.error = DrawingError(
                    {"code": "SUBMISSION_UNKNOWN", "message": "等待结束，提交响应未确认，请保留原 request_id"},
                    request_id=request_id,
                )
            return result
