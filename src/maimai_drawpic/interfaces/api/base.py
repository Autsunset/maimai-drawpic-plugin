"""薄接口层共享工作台服务入口。"""

from functools import wraps
from typing import Any, Awaitable, Callable, Dict, Optional

from ...application.workspace.service import WorkspaceService


class WorkspaceAPIBase:
    _workspace_service: Optional[WorkspaceService]

    def _workspace(self) -> WorkspaceService:
        if self._workspace_service is None:
            raise RuntimeError("绘图工作台尚未完成加载")
        return self._workspace_service


def workspace_endpoint(handler: Callable[..., Awaitable[Dict[str, Any]]]) -> Callable:
    """可预期的输入错误回传页面；运行异常继续交由 Runner 完整记录。"""

    @wraps(handler)
    async def invoke(*args: Any, **kwargs: Any) -> Dict[str, Any]:
        try:
            return await handler(*args, **kwargs)
        except (ValueError, PermissionError) as exc:
            return {"__workspace_error__": str(exc)}

    return invoke
