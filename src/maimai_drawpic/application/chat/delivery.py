import base64

from .types import ChatStreamUnavailableError, ImageDeliveryError, ImageDeliveryUnconfirmedError


class ImageDeliveryMixin:
    """ImageDeliveryMixin 的独立绘图职责。"""

    async def send_generated_images(
        self,
        stream_id: str,
        image_bytes_list: list[bytes],
    ) -> int:
        """将生成结果发送回当前会话。"""

        total = len(image_bytes_list)
        sent_count = 0
        for index, image_bytes in enumerate(image_bytes_list, start=1):
            image_base64 = base64.b64encode(image_bytes).decode("utf-8")
            self.ctx.logger.info(
                "正在发送绘图结果图片: stream_id=%s progress=%s/%s",
                stream_id,
                index,
                total,
            )
            try:
                send_result = await self.ctx.send.image(image_base64, stream_id)
            except Exception as exc:
                self.ctx.logger.warning(
                    "调用平台适配器发送图片异常: stream_id=%s progress=%s/%s error_type=%s error=%s",
                    stream_id,
                    index,
                    total,
                    type(exc).__name__,
                    exc,
                )
                raise ImageDeliveryError(
                    f"调用平台适配器发送图片时发生异常: stream_id={stream_id} error={exc}",
                    sent_count=sent_count,
                ) from exc
            if not send_result:
                self.ctx.logger.warning(
                    "平台未确认图片发送成功，投递结果未知: stream_id=%s progress=%s/%s；"
                    "请检查平台适配器日志，避免盲目重试",
                    stream_id,
                    index,
                    total,
                )
                raise ImageDeliveryUnconfirmedError(
                    "图片发送未获得平台成功确认，可能是平台适配器返回失败或响应超时；"
                    "不能据此判定聊天流不可用，图片也可能已经送达: "
                    f"stream_id={stream_id}",
                    sent_count=sent_count,
                )
            sent_count += 1
        return sent_count

    async def send_generated_images_with_fallback(
        self,
        stream_id: str,
        image_bytes_list: list[bytes],
        user_id: str = "",
        group_id: str = "",
        platform: str = "qq",
        task_id: str = "",
        provider: str = "",
        model: str = "",
    ) -> int:
        """发送图片，并在必要时重新解析活跃聊天流后重试。"""

        resolved_stream_id = await self.resolve_live_stream_id(
            stream_id=stream_id,
            user_id=user_id,
            group_id=group_id,
            platform=platform,
        )
        if not resolved_stream_id:
            self.ctx.logger.warning(
                "未能解析到可用聊天流，无法发送绘图结果: original_stream_id=%s user_id=%s group_id=%s platform=%s",
                stream_id,
                user_id,
                group_id,
                platform,
            )
            raise ChatStreamUnavailableError(f"未能解析到可用聊天流，无法发送图片: original_stream_id={stream_id}")
        try:
            sent_count = await self.send_generated_images(resolved_stream_id, image_bytes_list)
            self.ctx.logger.info(
                "发送绘图结果成功: task_id=%s provider=%s model=%s original_stream_id=%s resolved_stream_id=%s platform=%s count=%s",
                task_id,
                provider,
                model,
                stream_id,
                resolved_stream_id,
                platform,
                sent_count,
            )
            return sent_count
        except ImageDeliveryUnconfirmedError:
            raise
        except ImageDeliveryError as first_error:
            self.ctx.logger.warning(
                "首次发送图片未完成确认，尝试重新解析聊天流: original_stream_id=%s resolved_stream_id=%s error=%s",
                stream_id,
                resolved_stream_id,
                first_error,
            )
            fallback_stream_id = await self.resolve_live_stream_id(
                stream_id="",
                user_id=user_id,
                group_id=group_id,
                platform=platform,
            )
            if not fallback_stream_id or fallback_stream_id == resolved_stream_id:
                self.ctx.logger.warning(
                    "重新解析未得到新的可用聊天流，不重复发送图片: original_stream_id=%s "
                    "resolved_stream_id=%s fallback_stream_id=%s error_type=%s",
                    stream_id,
                    resolved_stream_id,
                    fallback_stream_id,
                    type(first_error).__name__,
                )
                raise
            self.ctx.logger.info(
                "使用重新解析的聊天流重试发送图片: original_stream_id=%s fallback_stream_id=%s",
                stream_id,
                fallback_stream_id,
            )
            remaining_images = image_bytes_list[first_error.sent_count :]
            try:
                fallback_sent_count = await self.send_generated_images(fallback_stream_id, remaining_images)
            except ImageDeliveryError as fallback_error:
                fallback_error.sent_count += first_error.sent_count
                raise
            sent_count = first_error.sent_count + fallback_sent_count
            self.ctx.logger.info(
                "发送绘图结果成功: task_id=%s provider=%s model=%s original_stream_id=%s resolved_stream_id=%s platform=%s count=%s",
                task_id,
                provider,
                model,
                stream_id,
                fallback_stream_id,
                platform,
                sent_count,
            )
            return sent_count

    async def send_image_bytes_with_fallback(
        self,
        image_bytes: bytes,
        stream_id: str,
        user_id: str = "",
        group_id: str = "",
        platform: str = "qq",
    ) -> bool:
        """发送单张图片，并在必要时重新解析活跃聊天流后重试。"""

        resolved_stream_id = await self.resolve_live_stream_id(
            stream_id=stream_id,
            user_id=user_id,
            group_id=group_id,
            platform=platform,
        )
        if not resolved_stream_id:
            self.ctx.logger.warning("未能解析到可用聊天流，无法发送图片回复")
            return False

        image_base64 = base64.b64encode(image_bytes).decode("utf-8")
        send_result = await self.ctx.send.image(image_base64, resolved_stream_id)
        if send_result:
            return True

        self.ctx.logger.warning(
            "首次发送图片回复失败，尝试重新解析聊天流: original_stream_id=%s resolved_stream_id=%s",
            stream_id,
            resolved_stream_id,
        )
        fallback_stream_id = await self.resolve_live_stream_id(
            stream_id="",
            user_id=user_id,
            group_id=group_id,
            platform=platform,
        )
        if not fallback_stream_id or fallback_stream_id == resolved_stream_id:
            return False
        return bool(await self.ctx.send.image(image_base64, fallback_stream_id))

    async def send_text_with_fallback(
        self,
        text: str,
        stream_id: str,
        user_id: str = "",
        group_id: str = "",
        platform: str = "qq",
    ) -> bool:
        """发送文本，并在必要时重新解析活跃聊天流后重试。"""

        resolved_stream_id = await self.resolve_live_stream_id(
            stream_id=stream_id,
            user_id=user_id,
            group_id=group_id,
            platform=platform,
        )
        if not resolved_stream_id:
            self.ctx.logger.warning("未能解析到可用聊天流，无法发送文本: %s", text)
            return False

        send_result = await self.ctx.send.text(text=text, stream_id=resolved_stream_id)
        if send_result:
            return True

        self.ctx.logger.warning(
            "首次发送文本失败，尝试重新解析聊天流: original_stream_id=%s resolved_stream_id=%s",
            stream_id,
            resolved_stream_id,
        )
        fallback_stream_id = await self.resolve_live_stream_id(
            stream_id="",
            user_id=user_id,
            group_id=group_id,
            platform=platform,
        )
        if not fallback_stream_id or fallback_stream_id == resolved_stream_id:
            return False
        return await self.ctx.send.text(text, fallback_stream_id)
