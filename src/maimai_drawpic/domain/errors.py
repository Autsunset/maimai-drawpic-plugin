"""提供商失败的执行语义，避免把未知结果当作可重复提交的请求。"""


class ProviderError(RuntimeError):
    """默认不重新生成；只有明确未受理的临时错误才允许重试。"""

    retryable = False
    allow_fallback = False
    rejected = False
    outcome_unknown = False


class ProviderRequestError(ProviderError):
    """收到明确拒绝响应，保留协议状态与审核分类。"""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status, self.code = status, code
        normalized = code.casefold().replace("-", "_")
        self.rejected = any(
            marker in normalized
            for marker in (
                "content_policy",
                "content_filter",
                "safety",
                "moderation",
                "sensitive",
                "inappropriate",
                "responsibleai",
                "datainspection",
                "riskcontrol",
                "prohibited",
            )
        )
        quota = any(marker in normalized for marker in ("quota", "balance", "billing", "credit"))
        self.retryable = (
            not self.rejected
            and not quota
            and (
                status == 429
                or normalized in {"server_busy", "service_unavailable", "model_overloaded", "rate_limit_exceeded"}
            )
        )
        self.allow_fallback = not self.rejected and (400 <= status < 500 or self.retryable)
        self.outcome_unknown = not self.rejected and status >= 500 and not self.retryable


class ProviderResultError(ProviderError):
    """已收到生成响应，解析或结果下载失败只能恢复结果，不能重新生图。"""


class ProviderOutcomeUnknown(ProviderError):
    """连接中断或超时，无法确认上游是否已经受理、生成或计费。"""

    outcome_unknown = True


class ProviderConnectionError(ProviderError):
    """连接尚未建立，生成请求没有发出，可按配置重试或切换。"""

    retryable = True
    allow_fallback = True
