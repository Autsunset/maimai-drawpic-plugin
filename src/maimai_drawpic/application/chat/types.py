class ChatStreamUnavailableError(RuntimeError):
    """表示无法解析用于发送消息的真实聊天流。"""


class ImageDeliveryError(RuntimeError):
    """表示调用平台图片发送链路时发生异常。"""

    def __init__(self, message: str, sent_count: int = 0) -> None:
        super().__init__(message)
        self.sent_count = sent_count


class ImageDeliveryUnconfirmedError(ImageDeliveryError):
    """表示平台未确认图片发送成功，实际投递结果未知。"""
