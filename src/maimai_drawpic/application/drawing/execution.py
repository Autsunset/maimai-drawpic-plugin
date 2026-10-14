from typing import Awaitable, Callable
import asyncio
import inspect

from ..chat import ImageDeliveryError
from ...infrastructure.storage.retention import CacheCapacityError


class ImageExecutionMixin:
    """ImageExecutionMixin 的独立绘图职责。"""

    async def _background_image_request(
        self,
        *,
        task_id: str,
        prompt: str,
        stream_id: str,
        resolved_model: str,
        openai_compatibility_mode: str = "",
        novelai_mode: str = "",
        novelai_artist_tags: str = "",
        request_negative_prompt: str = "",
        source_image_bytes_list: list[bytes] | None = None,
        source_image_urls: list[str] | None = None,
        matched_message_id: str = "",
        user_id: str = "",
        group_id: str = "",
        platform_name: str = "qq",
        prompt_reviewed: bool = True,
        on_task_unsuccessful: Callable[[str, str, str], Awaitable[None] | None] | None = None,
        on_task_successful: Callable[[str, str, str], Awaitable[None] | None] | None = None,
    ) -> None:
        """后台执行绘图任务，源图为空时文生图，存在源图时图生图。"""

        async def _notify_task_unsuccessful(status: str, reason: str) -> None:
            if on_task_unsuccessful is None:
                return
            try:
                result = on_task_unsuccessful(task_id, status, reason)
                if inspect.isawaitable(result):
                    await result
            except Exception as exc:
                self.ctx.logger.error(
                    "绘图任务失败回调执行异常: task_id=%s status=%s reason=%s error=%s",
                    task_id,
                    status,
                    reason,
                    exc,
                    exc_info=True,
                )

        async def _notify_task_successful(status: str, reason: str) -> None:
            if on_task_successful is None:
                return
            try:
                result = on_task_successful(task_id, status, reason)
                if inspect.isawaitable(result):
                    await result
            except Exception as exc:
                self.ctx.logger.error(
                    "绘图任务成功回调执行异常: task_id=%s status=%s reason=%s error=%s",
                    task_id,
                    status,
                    reason,
                    exc,
                    exc_info=True,
                )

        normalized_source_images = source_image_bytes_list or []
        normalized_source_urls = source_image_urls or [""] * len(normalized_source_images)
        is_image_edit = bool(normalized_source_images)
        task_type = "edit_image" if is_image_edit else "draw"
        running_message = "图片正在编辑中" if is_image_edit else "图片正在生成中"
        timeout_message = "图片编辑超时" if is_image_edit else "图片生成超时"
        try:
            if not prompt_reviewed:
                await self.review_prompt_or_raise(prompt)
            running_record = await asyncio.to_thread(
                self.task_store.update_task,
                task_id,
                status="running",
                message=running_message,
            )
            if running_record is None:
                # 任务记录已失效时结束执行，并通知调用方释放预留资源。
                self.ctx.logger.warning("绘图任务记录已失效，终止后台执行: task_id=%s task_type=%s", task_id, task_type)
                await _notify_task_unsuccessful("failed", "任务记录已失效")
                return
            primary_attempt = self._build_image_request_attempt(
                model=resolved_model,
                task_type=task_type,
                openai_compatibility_mode=openai_compatibility_mode,
                novelai_mode=novelai_mode,
                novelai_artist_tags=novelai_artist_tags,
            )
            await asyncio.to_thread(
                self.task_store.update_task,
                task_id,
                status="running",
                message=running_message,
                model=primary_attempt.model,
                provider=primary_attempt.provider_name,
            )

            image_bytes_list, successful_attempt, attempt_errors = await self._execute_request_plan(
                primary_attempt=primary_attempt,
                primary_model=resolved_model,
                prompt=prompt,
                task_id=task_id,
                task_type=task_type,
                openai_compatibility_mode=openai_compatibility_mode,
                novelai_mode=novelai_mode,
                novelai_artist_tags=novelai_artist_tags,
                source_image_bytes_list=normalized_source_images,
                source_image_urls=normalized_source_urls,
                matched_message_id=matched_message_id,
                request_negative_prompt=request_negative_prompt,
            )

            if successful_attempt is None:
                failure_message = "；".join(attempt_errors) if attempt_errors else "图片平台没有返回任何图片结果"
                await asyncio.to_thread(
                    self.task_store.update_task,
                    task_id,
                    status="failed",
                    message=failure_message,
                )
                await _notify_task_unsuccessful("failed", failure_message)
                self.ctx.logger.error(
                    "绘图任务失败: task_id=%s task_type=%s primary_provider=%s primary_model=%s configured_fallback_model=%s errors=%s",
                    task_id,
                    task_type,
                    primary_attempt.provider_name,
                    primary_attempt.model,
                    self.router.config.general.fallback_models,
                    failure_message,
                )
                return

            reviewed_images, rejected_reasons = await self.filter_reviewed_images(prompt, image_bytes_list)
            if not reviewed_images:
                review_reason_text = "；".join(rejected_reasons) if rejected_reasons else "审核未通过"
                if successful_attempt.is_fallback and attempt_errors:
                    review_reason_text = f"首选模型失败后使用备选模型生成，但图片审核未通过：{review_reason_text}"
                await asyncio.to_thread(
                    self.task_store.update_task,
                    task_id,
                    status="rejected",
                    message=review_reason_text,
                    model=successful_attempt.model,
                    provider=successful_attempt.provider_name,
                )
                await _notify_task_unsuccessful("rejected", review_reason_text)
                self.ctx.logger.error(
                    "绘图任务审核未通过: task_id=%s task_type=%s provider=%s model=%s is_fallback=%s error=%s",
                    task_id,
                    task_type,
                    successful_attempt.provider_name,
                    successful_attempt.model,
                    successful_attempt.is_fallback,
                    review_reason_text,
                )
                return

            result_count = 0
            cache_message = ""
            if self.result_store is not None:
                try:
                    result_count = await asyncio.to_thread(self.result_store.save, task_id, reviewed_images)
                except CacheCapacityError as exc:
                    cache_message = f"；图片未缓存：{exc}，可在 MaiBot 插件配置页调整缓存上限"
                    self.ctx.logger.warning("绘图结果未缓存: task_id=%s reason=%s", task_id, exc)
                await asyncio.to_thread(
                    self.task_store.update_task,
                    task_id,
                    status="running",
                    message="图片已生成",
                    result_count=result_count,
                )
            sent_count = 0
            if stream_id:
                sent_count = await self.stream_service.send_generated_images_with_fallback(
                    stream_id=stream_id,
                    image_bytes_list=reviewed_images,
                    user_id=user_id,
                    group_id=group_id,
                    platform=platform_name,
                    task_id=task_id,
                    provider=successful_attempt.provider_name,
                    model=successful_attempt.model,
                )
            success_message = (
                f"图片已发送，数量={sent_count}" if stream_id else f"图片已生成，数量={len(reviewed_images)}"
            )
            if successful_attempt.is_fallback:
                action = "发送" if stream_id else "生成"
                success_message = f"首选模型失败，已使用生图备选模型{action}图片，数量={sent_count if stream_id else len(reviewed_images)}"
            success_message += cache_message
            await asyncio.to_thread(
                self.task_store.update_task,
                task_id,
                status="completed",
                message=success_message,
                sent_count=sent_count,
                model=successful_attempt.model,
                provider=successful_attempt.provider_name,
            )
            await _notify_task_successful("completed", success_message)
            self.ctx.logger.info(
                "绘图任务完成: task_id=%s task_type=%s provider=%s model=%s is_fallback=%s sent_count=%s previous_errors=%s",
                task_id,
                task_type,
                successful_attempt.provider_name,
                successful_attempt.model,
                successful_attempt.is_fallback,
                sent_count,
                "；".join(attempt_errors),
            )
        except asyncio.CancelledError:
            await asyncio.to_thread(
                self.task_store.update_task,
                task_id,
                status="failed",
                message="任务已取消",
            )
            await _notify_task_unsuccessful("failed", "任务已取消")
            self.ctx.logger.warning(
                "绘图任务已取消: task_id=%s task_type=%s model=%s", task_id, task_type, resolved_model
            )
            raise
        except ImageDeliveryError as exc:
            if exc.sent_count <= 0:
                await asyncio.to_thread(
                    self.task_store.update_task,
                    task_id,
                    status="failed",
                    message=str(exc),
                )
                await _notify_task_unsuccessful("failed", str(exc))
                self.ctx.logger.error(
                    "绘图任务投递失败: task_id=%s task_type=%s model=%s error=%s",
                    task_id,
                    task_type,
                    resolved_model,
                    exc,
                )
                return

            partial_message = f"部分图片已发送，数量={exc.sent_count}；其余图片投递失败：{exc}"
            await asyncio.to_thread(
                self.task_store.update_task,
                task_id,
                status="completed",
                message=partial_message,
                sent_count=exc.sent_count,
            )
            await _notify_task_successful("completed", partial_message)
            self.ctx.logger.warning(
                "绘图任务部分投递完成: task_id=%s task_type=%s model=%s sent_count=%s error=%s",
                task_id,
                task_type,
                resolved_model,
                exc.sent_count,
                exc,
            )
        except TimeoutError:
            timeout_seconds = self.resolve_request_timeout_seconds()
            await asyncio.to_thread(
                self.task_store.update_task,
                task_id,
                status="failed",
                message=f"{timeout_message}，超过 {timeout_seconds} 秒",
            )
            await _notify_task_unsuccessful("failed", f"{timeout_message}，超过 {timeout_seconds} 秒")
            self.ctx.logger.error(
                "绘图任务失败: task_id=%s task_type=%s model=%s error=%s",
                task_id,
                task_type,
                resolved_model,
                f"{timeout_message}，超过 {timeout_seconds} 秒",
            )
        except Exception as exc:
            await asyncio.to_thread(
                self.task_store.update_task,
                task_id,
                status="failed",
                message=str(exc),
            )
            await _notify_task_unsuccessful("failed", str(exc))
            self.ctx.logger.error(
                "绘图任务失败: task_id=%s task_type=%s model=%s error=%s",
                task_id,
                task_type,
                resolved_model,
                exc,
                exc_info=True,
            )
