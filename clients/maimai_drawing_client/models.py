"""客户端结果类型；不依赖绘图插件内部代码或第三方库。"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


class DrawingTransportError(RuntimeError):
    """RPC 未获得可信业务响应，不代表未受理或绘图失败。"""

    def __init__(self, message: str, *, task_id: Optional[str] = None, request_id: str = "") -> None:
        super().__init__(message)
        self.task_id, self.request_id = task_id, request_id


def validate_error(error: Any, *, task_id: Optional[str] = None, request_id: str = "") -> None:
    if (
        not isinstance(error, dict)
        or not isinstance(error.get("code"), str)
        or not error["code"]
        or not isinstance(error.get("message"), str)
        or any(name in error and type(error[name]) is not bool for name in ("retry_query", "retry_submit"))
    ):
        raise DrawingTransportError("业务错误响应格式无效", task_id=task_id, request_id=request_id)


class DrawingError(RuntimeError):
    def __init__(self, error: Dict[str, Any], *, task_id: Optional[str] = None, request_id: str = "") -> None:
        validate_error(error, task_id=task_id, request_id=request_id)
        super().__init__(error["message"])
        self.code = error["code"]
        self.retry_query = bool(error.get("retry_query", False))
        self.retry_submit = bool(error.get("retry_submit", False))
        self.task_id, self.request_id = task_id, request_id


@dataclass(frozen=True)
class TaskHandle:
    task_id: Optional[str]
    request_id: str
    status: str = "pending"
    reused: bool = False
    error: Optional[DrawingError] = None


@dataclass(frozen=True)
class GeneratedImage:
    data: bytes = field(repr=False)
    reference: Dict[str, Any]


@dataclass
class DrawingResult:
    task_id: Optional[str]
    request_id: str
    status: str
    images: List[GeneratedImage] = field(default_factory=list)
    image_references: List[Dict[str, Any]] = field(default_factory=list)
    error: Optional[DrawingError] = None
    wait_expired: bool = False
    generation_completed: bool = False
    results_readable: bool = False
    delivery: Dict[str, Any] = field(default_factory=dict)
    retry_after_ms: int = 3000
