"""每次 SDK 调用独立限时；不设置宿主能力超时或创建后台任务。"""

from typing import Any, Dict, Protocol
import asyncio

from .models import DrawingTransportError


class APIProxy(Protocol):
    async def call(self, api_name: str, version: str = "1", **kwargs: Any) -> Any: ...


class DrawingRPC:
    def __init__(self, api: APIProxy, timeout: float) -> None:
        self.api, self.timeout = api, timeout

    async def call(self, name: str, /, *, version: str = "2", **kwargs: Any) -> Dict[str, Any]:
        handles = {"task_id": kwargs.get("task_id"), "request_id": kwargs.get("request_id", "")}
        try:
            async with asyncio.timeout(self.timeout):
                response = await self.api.call(
                    f"maimai-drawpic-plugin.drawpic_{name}{'_v2' if version == '2' else ''}", version=version, **kwargs
                )
        except TimeoutError as exc:
            raise DrawingTransportError("RPC 等待结束，远端响应未确认", **handles) from exc
        except Exception as exc:
            raise DrawingTransportError("SDK 调用失败，远端响应未确认", **handles) from exc
        if not isinstance(response, dict) or response.get("success") is not True:
            message = (
                str(response.get("error", "RPC 返回无效包装")) if isinstance(response, dict) else "RPC 返回无效包装"
            )
            raise DrawingTransportError(message, **handles)
        result = response.get("result")
        if not isinstance(result, dict):
            raise DrawingTransportError("RPC result 必须是对象", **handles)
        return result
