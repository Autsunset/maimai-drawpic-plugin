"""runtime/requests.py 的插件组件。"""

from typing import Any, Dict, Optional
import asyncio


class RequestMixin:
    """runtime/requests.py 对应的插件行为。"""

    async def _start_background_image_request(
        self,
        *,
        prompt: str,
        stream_id: str,
        requested_model: str = "",
        requested_openai_compatibility_mode: str = "",
        request_negative_prompt: str = "",
        requested_novelai_mode: str = "",
        source_image_bytes_list: list[bytes] | None = None,
        source_image_urls: list[str] | None = None,
        matched_message_id: str = "",
        user_id: str = "",
        group_id: str = "",
        platform_name: str = "qq",
        notify_start: bool = True,
        defer_prompt_review: bool = False,
        submission: Optional[Dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """按当前会话设置启动后台绘图，源图为空时文生图，存在源图时图生图。"""

        draw_service = self._require_draw_service()
        live_context = await self._require_stream_service().resolve_live_stream_context(
            stream_id=stream_id,
            user_id=user_id,
            group_id=group_id,
            platform=platform_name,
        )
        runtime_context = self._merge_resolved_runtime_context(
            live_context,
            user_id=user_id,
            group_id=group_id,
            platform=platform_name,
        )
        resolved_stream_id = runtime_context["stream_id"]
        if not resolved_stream_id:
            raise RuntimeError("当前聊天流不可用，无法回传图片")
        resolved_user_id = runtime_context["user_id"]
        resolved_group_id = runtime_context["group_id"]
        resolved_platform = runtime_context["platform"]
        normalized_source_images = source_image_bytes_list or []
        normalized_source_urls = source_image_urls or [""] * len(normalized_source_images)
        if len(normalized_source_urls) != len(normalized_source_images):
            raise ValueError("源图 URL 数量必须与源图数量一致")
        session_preference = self._get_session_preference(
            resolved_stream_id,
            resolved_user_id,
            resolved_group_id,
            resolved_platform,
        )
        resolved_model = draw_service.resolve_model_name(
            requested_model or session_preference["model"],
            allow_unknown_model=False,
        )
        resolved_openai_mode = self._require_router().resolve_openai_compatibility_mode(
            requested_openai_compatibility_mode or session_preference["openai_compatibility_mode"],
            resolved_model,
        )
        resolved_novelai_mode = self._require_router().resolve_novelai_mode_for_model(
            resolved_model, requested_novelai_mode or session_preference.get("novelai_mode", "")
        )
        resolved_novelai_artist_tags = self._require_router().resolve_novelai_artist_tags_for_model(
            resolved_model, session_preference.get("novelai_artist_tags", "")
        )
        provider_name = self._require_router().get_model_provider(resolved_model)
        if not provider_name:
            raise ValueError(f"指定模型不可用：{resolved_model}")
        task_type = "edit_image" if normalized_source_images else "draw"
        # 火山引擎使用统一模型列表，按模型名能力标记和全局黑名单提前校验。
        check_model = resolved_model
        if provider_name == "volcengine":
            try:
                check_model = self._require_router().resolve_volcengine_model_for_task(
                    resolved_model,
                    task_type,
                )
            except ValueError:
                check_model = resolved_model
        capability = self._require_router().evaluate_model_task_capability(
            check_model,
            task_type,
        )
        if not capability.allowed:
            self.ctx.logger.warning(
                "拒绝提交模型不支持的绘图任务: model=%s provider=%s task_type=%s "
                "capability_source=%s source_image_count=%s reason=%s",
                check_model,
                provider_name,
                task_type,
                capability.source,
                len(normalized_source_images),
                capability.reason,
            )
            task_hint = "图生图" if task_type == "draw" else "文生图"
            raise ValueError(f"{capability.reason}。请改用 /绘图 {task_hint} <prompt>，或切换到支持当前任务的模型")

        self._require_router().validate_source_image_count(check_model, len(normalized_source_images))
        if not defer_prompt_review:
            await draw_service.review_prompt_or_raise(prompt)
        quota_allowed, quota_message, quota_key = await asyncio.to_thread(
            self._reserve_draw_quota,
            resolved_user_id,
            resolved_group_id,
            resolved_stream_id,
        )
        if not quota_allowed:
            raise PermissionError(quota_message)
        _, reserved_quota_period, reserved_default_quota = self._resolve_quota_config(resolved_group_id)

        async def _handle_task_unsuccessful(task_id: str, status: str, reason: str) -> None:
            await asyncio.to_thread(
                self._refund_draw_quota,
                quota_key,
                resolved_group_id,
                resolved_stream_id,
                task_id,
                quota_period=reserved_quota_period,
                default_quota=reserved_default_quota,
            )
            await self._send_draw_failure_notice(
                reason=reason,
                stream_id=resolved_stream_id,
                user_id=resolved_user_id,
                group_id=resolved_group_id,
                platform=resolved_platform,
                task_id=task_id,
                status=status,
            )

        try:
            return await draw_service.start_background_image_request(
                prompt=prompt,
                stream_id=resolved_stream_id,
                resolved_model=resolved_model,
                resolved_openai_mode=resolved_openai_mode,
                provider_name=provider_name,
                novelai_mode=resolved_novelai_mode,
                novelai_artist_tags=resolved_novelai_artist_tags,
                request_negative_prompt=request_negative_prompt.strip(),
                user_id=resolved_user_id,
                group_id=resolved_group_id,
                platform_name=resolved_platform,
                source_image_bytes_list=normalized_source_images,
                source_image_urls=normalized_source_urls,
                matched_message_id=matched_message_id,
                notify_start=notify_start,
                prompt_reviewed=not defer_prompt_review,
                on_task_unsuccessful=_handle_task_unsuccessful,
                submission=submission,
            )
        except (Exception, asyncio.CancelledError):
            await asyncio.to_thread(
                self._refund_draw_quota,
                quota_key,
                resolved_group_id,
                resolved_stream_id,
                quota_period=reserved_quota_period,
                default_quota=reserved_default_quota,
            )
            raise
