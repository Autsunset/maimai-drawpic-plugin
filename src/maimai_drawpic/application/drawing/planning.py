from typing import Any
import asyncio
import inspect

from ...infrastructure.media.collection import validate_result_images
from .admission import wait_for_admission
from .types import ImageRequestAttempt
from .character_prompt import CharacterPromptEnhancer, SearxngClient
from .style_anchor import append_default_style
from .unknown_character import _strip_conflicting_appearance


class RequestPlanningMixin:
    """RequestPlanningMixin 的独立绘图职责。"""

    async def run_provider_call(self, call: Any, *args: Any) -> list[bytes]:
        """执行图片请求，并按插件配置控制后台任务超时。"""

        timeout_seconds = self.resolve_request_timeout_seconds()

        if inspect.iscoroutinefunction(call):
            image_bytes_list = await asyncio.wait_for(call(*args), timeout=timeout_seconds)
        else:
            # Cancelling the asyncio wrapper cannot stop an SDK thread. Keep this
            # drawing task (and its quota/capacity) alive until the worker exits.
            pending = asyncio.create_task(asyncio.to_thread(call, *args))
            try:
                image_bytes_list = await asyncio.wait_for(asyncio.shield(pending), timeout=timeout_seconds)
            except (asyncio.CancelledError, TimeoutError):
                try:
                    await wait_for_admission(pending)
                except Exception:
                    pass  # Retrieve worker failure, but preserve cancellation/timeout.
                raise
        # 解码大图会占用 CPU，必须在线程中校验，避免阻塞其他会话的任务。
        return await asyncio.to_thread(validate_result_images, image_bytes_list)

    def _build_image_request_attempt(
        self,
        *,
        model: str,
        task_type: str,
        openai_compatibility_mode: str,
        novelai_mode: str = "",
        novelai_artist_tags: str = "",
        is_fallback: bool = False,
    ) -> ImageRequestAttempt:
        """构建一次图片请求尝试的最终模型与提供商信息。"""

        provider_name = self.router.get_model_provider(model)
        if not provider_name:
            raise ValueError(f"指定模型不可用：{model}")

        effective_model = model
        if provider_name == "volcengine":
            effective_model = self.router.resolve_volcengine_model_for_task(model, task_type)
        elif provider_name == "novelai":
            novelai_mode = self.router.resolve_novelai_mode_for_model(model, novelai_mode)
            effective_model = self.router.resolve_novelai_model_for_mode(model, novelai_mode)
            provider_name = self.router.get_model_provider(effective_model)
            if provider_name != "novelai":
                raise ValueError(
                    f"NovelAI {novelai_mode} 模式需要模型 "
                    f"{effective_model}，请先在 novelai.models 中启用该模型"
                )
            if effective_model != model:
                self.ctx.logger.info(
                    "NovelAI V3 模型按 mode 自动切换: original_model=%s effective_model=%s mode=%s is_fallback=%s",
                    model,
                    effective_model,
                    novelai_mode,
                    is_fallback,
                )

        capability = self.router.evaluate_model_task_capability(
            effective_model,
            task_type,
        )
        if not capability.allowed:
            self.ctx.logger.warning(
                "拒绝构建不支持的绘图尝试: model=%s provider=%s task_type=%s "
                "capability_source=%s reason=%s is_fallback=%s",
                effective_model,
                provider_name,
                task_type,
                capability.source,
                capability.reason,
                is_fallback,
            )
            task_hint = "图生图" if task_type == "draw" else "文生图"
            raise ValueError(f"{capability.reason}。请改用{task_hint}，或切换到支持当前任务的模型")

        return ImageRequestAttempt(
            model=effective_model,
            provider_name=provider_name,
            openai_compatibility_mode=self.router.resolve_openai_compatibility_mode(
                openai_compatibility_mode,
                effective_model,
            ),
            novelai_mode=(
                self.router.resolve_novelai_mode_for_model(effective_model, novelai_mode)
                if provider_name == "novelai"
                else ""
            ),
            novelai_artist_tags=(
                self.router.resolve_novelai_artist_tags_for_model(effective_model, novelai_artist_tags)
                if provider_name == "novelai"
                else ""
            ),
            is_fallback=is_fallback,
        )

    def _build_fallback_image_request_attempt(
        self,
        *,
        primary_model: str,
        primary_effective_model: str,
        task_type: str,
        openai_compatibility_mode: str,
        novelai_mode: str = "",
        novelai_artist_tags: str = "",
        fallback_model: str = "",
    ) -> ImageRequestAttempt | None:
        """在首选模型失败后构建备选模型请求。"""

        fallback_model = fallback_model or self.router.resolve_fallback_model(primary_model)
        if not fallback_model:
            return None

        try:
            fallback_attempt = self._build_image_request_attempt(
                model=fallback_model,
                task_type=task_type,
                openai_compatibility_mode=openai_compatibility_mode,
                novelai_mode=novelai_mode,
                novelai_artist_tags=novelai_artist_tags,
                is_fallback=True,
            )
        except Exception as exc:
            self.ctx.logger.warning(
                "生图备选模型解析失败，跳过备选尝试: primary_model=%s fallback_model=%s task_type=%s error=%s",
                primary_model,
                fallback_model,
                task_type,
                exc,
            )
            return None

        if fallback_attempt.model == primary_effective_model:
            self.ctx.logger.warning(
                "生图备选模型与首选模型最终解析结果相同，跳过备选尝试: primary_model=%s fallback_model=%s effective_model=%s",
                primary_model,
                fallback_model,
                fallback_attempt.model,
            )
            return None

        return fallback_attempt

    async def _run_image_request_attempt(
        self,
        *,
        attempt: ImageRequestAttempt,
        prompt: str,
        task_id: str,
        task_type: str,
        source_image_bytes_list: list[bytes],
        source_image_urls: list[str],
        matched_message_id: str,
        request_negative_prompt: str = "",
        stream_id: str = "",
    ) -> list[bytes]:
        """执行单次图片请求尝试。"""

        provider_name = attempt.provider_name
        if task_type == "edit_image":
            self.router.validate_source_image_count(attempt.model, len(source_image_bytes_list))
        provider_prompt = prompt
        provider_negative_prompt = request_negative_prompt.strip()
        supports_negative_prompt = self.router.supports_separate_negative_prompt(
            attempt.model,
            task_type,
        )
        if provider_negative_prompt and not supports_negative_prompt:
            provider_prompt = self.router.merge_prompt_parts(
                provider_prompt,
                f"Negative prompt: {provider_negative_prompt}",
            )
            provider_negative_prompt = ""
        # 角色形象补全必须在英文改写之前：模型不认识「星瞳」这类角色名，
        # 改写只会把中文名变成拼音，信息量更少。
        #
        # 整段补全都在 try 里兜底：补全只是锦上添花，任何异常都不能让绘图失败。
        try:
            _enhancer = self._character_enhancer
        except AttributeError:
            _enhancer = self._character_enhancer = CharacterPromptEnhancer(
                searcher=SearxngClient()
            )
        if _enhancer is not None:
            try:
                # 顺序要紧：先认出角色、洗掉冲突的外貌描述，再追加角色库标签。
                # 反过来的话，刚追加的 silver white short hair 会被当成「外貌
                # 短语」一并删掉。
                _profiles = _enhancer.matched_profiles(provider_prompt)
                if _profiles:
                    provider_prompt = _strip_conflicting_appearance(provider_prompt, _profiles)
                    provider_prompt, _matched = _enhancer.enhance(provider_prompt)
                else:
                    # chat LLM 常把「画个星瞳」改写成一大段自编的外貌描述，
                    # 角色名就此丢失，角色库永远补不上。这里从最近消息里的
                    # 用户原话找回角色名，再补一次。
                    provider_prompt, _matched = await self.recover_character_from_recent_messages(
                        provider_prompt,
                        _enhancer,
                        stream_id,
                        task_id,
                    )
                if _matched:
                    self.ctx.logger.info(
                        "角色形象已补全: task_id=%s characters=%s model=%s",
                        task_id,
                        ",".join(_matched),
                        attempt.model,
                    )
                elif self.should_lookup_unknown_character(provider_prompt):
                    # 内置库里没有：联网查一次外观，再让 LLM 翻成英文标签。
                    _unknown = _enhancer.guess_unknown_character(provider_prompt)
                    if _unknown:
                        _looked = await self.lookup_character_appearance(_enhancer, _unknown, task_id)
                        if _looked:
                            provider_prompt = ", ".join([provider_prompt.strip().rstrip(","), _looked])
            except Exception as exc:  # noqa: BLE001
                self.ctx.logger.warning(
                    "角色形象补全失败，按原提示词继续: task_id=%s error=%s", task_id, exc
                )

        # 画风兜底：提示词自己没写画风时才补默认风格，写了就完全让位给提示词。
        provider_prompt, _style_added = append_default_style(
            provider_prompt,
            self.router.config.style.auto_style_prompt,
        )
        if _style_added:
            self.ctx.logger.info(
                "提示词未指定画风，已追加默认画风: task_id=%s", task_id
            )

        provider_prompt = await self.rewrite_prompt_to_english_if_needed(
            provider_prompt,
            provider_name,
            attempt.model,
        )
        if provider_negative_prompt:
            provider_negative_prompt = await self.rewrite_prompt_to_english_if_needed(
                provider_negative_prompt,
                provider_name,
                attempt.model,
            )
        image_platform, provider_name = self.router.require_platform_for_model(
            attempt.model,
            attempt.openai_compatibility_mode,
            request_negative_prompt=provider_negative_prompt,
            novelai_mode=attempt.novelai_mode,
            novelai_artist_tags=attempt.novelai_artist_tags,
        )

        if task_type == "edit_image":
            self.ctx.logger.info(
                "开始绘图任务尝试: task_id=%s task_type=%s provider=%s model=%s is_fallback=%s source_image_count=%s source_image_bytes_lengths=%s matched_message_id=%s prompt=%s",
                task_id,
                task_type,
                provider_name,
                attempt.model,
                attempt.is_fallback,
                len(source_image_bytes_list),
                [len(image_bytes) for image_bytes in source_image_bytes_list],
                matched_message_id,
                provider_prompt[:120],
            )
            if provider_name == "aliyun":
                return await self.run_provider_call(
                    image_platform.edit_images_with_urls,
                    provider_prompt,
                    attempt.model,
                    source_image_bytes_list,
                    source_image_urls,
                    1,
                )
            return await self.run_provider_call(
                image_platform.edit_images,
                provider_prompt,
                attempt.model,
                source_image_bytes_list,
                1,
            )

        self.ctx.logger.info(
            "开始绘图任务尝试: task_id=%s task_type=%s provider=%s model=%s is_fallback=%s source_image_count=0 prompt=%s",
            task_id,
            task_type,
            provider_name,
            attempt.model,
            attempt.is_fallback,
            provider_prompt[:120],
        )
        return await self.run_provider_call(
            image_platform.generate_images,
            provider_prompt,
            attempt.model,
            1,
        )

    @staticmethod
    def _format_attempt_error(attempt: ImageRequestAttempt, error_message: str) -> str:
        """格式化一次模型尝试失败信息。"""

        role_name = "备选模型" if attempt.is_fallback else "首选模型"
        return f"{role_name} {attempt.provider_name}:{attempt.model} 失败：{error_message}"
