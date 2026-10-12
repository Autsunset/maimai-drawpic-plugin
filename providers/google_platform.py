from typing import Any, Dict, List

from google import genai
from google.genai import types

from ..core.http_proxy import HttpProxySettings, sanitize_provider_text
from ..core.image_utils import detect_mime_type


class GoogleImage:
    """通过 Gemini generateContent 生成和编辑图片。"""

    def __init__(
        self,
        api_key: str,
        base_url: str = "",
        logger: Any | None = None,
        request_timeout_seconds: int = 20,
        aspect_ratio: str = "",
        image_size: str = "",
        negative_prompt: str = "",
        seed: int = -1,
        extra_parameters: Dict[str, Any] | None = None,
        proxy_settings: HttpProxySettings | None = None,
    ) -> None:
        self.base_url = base_url.strip().rstrip("/") or "https://generativelanguage.googleapis.com"
        self.api_key = api_key
        self.logger = logger
        proxy = proxy_settings or HttpProxySettings.disabled()
        self._client_kwargs = {
            "api_key": api_key,
            "http_options": {
                "timeout": request_timeout_seconds * 1000,
                "base_url": self.base_url,
                "client_args": proxy.google_client_args(),
            },
        }
        self.aspect_ratio = aspect_ratio.strip()
        self.image_size = image_size.strip()
        self.negative_prompt = negative_prompt.strip()
        self.seed = int(seed)
        self.extra_parameters = dict(extra_parameters or {})

    @staticmethod
    def _uses_generate_content_api(model: str) -> bool:
        """Gemini 图片模型使用 generateContent，Imagen 不属于此协议。"""

        return not model.strip().lower().startswith("imagen-")

    @staticmethod
    def supports_negative_prompt(model: str) -> bool:
        """Gemini 没有独立反向提示词字段，调用层应合并到普通提示词。"""

        del model
        return False

    @staticmethod
    def max_reference_images(model: str) -> int:
        """按官方模型系列限制参考图片数量。"""

        return 3 if model.strip().lower().startswith("gemini-2.5-") else 14

    def _build_generate_content_config(self) -> types.GenerateContentConfig:
        """分开构造生成配置与图片配置，不静默丢弃不支持的扩展参数。"""

        kwargs = dict(self.extra_parameters)
        image_kwargs = kwargs.pop("image_config", {})
        if not isinstance(image_kwargs, dict):
            raise ValueError("Google extra_parameters.image_config 必须是 JSON 对象")
        image_kwargs = dict(image_kwargs)
        for key, value in (("aspect_ratio", self.aspect_ratio), ("image_size", self.image_size)):
            if value:
                image_kwargs.setdefault(key, value)
            if key in kwargs:
                image_kwargs[key] = kwargs.pop(key)
        unsupported_image_keys = set(image_kwargs) - {"aspect_ratio", "image_size"}
        if unsupported_image_keys:
            raise ValueError(f"Gemini API 不支持这些图片配置：{', '.join(sorted(unsupported_image_keys))}")
        unknown_keys = set(kwargs) - set(types.GenerateContentConfig.model_fields)
        if unknown_keys:
            raise ValueError(f"Google 生成配置不支持这些参数：{', '.join(sorted(unknown_keys))}")
        if image_kwargs:
            kwargs["image_config"] = types.ImageConfig(**image_kwargs)
        if self.seed >= 0:
            kwargs.setdefault("seed", self.seed)
        kwargs["response_modalities"] = ["TEXT", "IMAGE"]
        return types.GenerateContentConfig(**kwargs)

    @staticmethod
    def _extract_images_from_generate_content_response(response: types.GenerateContentResponse) -> List[bytes]:
        """只提取最终图片，不发送模型内部的思考图片。"""

        images: List[bytes] = []
        for candidate in response.candidates or []:
            if candidate.content is None:
                continue
            for part in candidate.content.parts or []:
                if part.thought or part.inline_data is None:
                    continue
                blob = part.inline_data
                if blob.data and blob.mime_type and blob.mime_type.startswith("image/"):
                    images.append(blob.data)
        if not images:
            feedback = response.prompt_feedback
            reason = str(feedback.block_reason) if feedback and feedback.block_reason else "未返回图片"
            finish_reasons = [str(candidate.finish_reason) for candidate in response.candidates or []]
            raise RuntimeError(f"Google 图片请求未完成：{reason}；finish_reason={','.join(finish_reasons)}")
        return images

    def _generate(self, prompt: str, model: str, images: List[bytes], n: int) -> List[bytes]:
        """由调用层线程池执行同步 SDK 请求，每次请求负责关闭自己的客户端。"""

        if not self._uses_generate_content_api(model):
            raise ValueError("Google Gemini API 已下线 Imagen，请选择 Gemini 图片模型")
        if n != 1:
            raise ValueError("Gemini 图片接口不支持 number_of_images，请分别提交绘图任务")
        limit = self.max_reference_images(model)
        if len(images) > limit:
            raise ValueError(f"当前 Google 模型最多支持 {limit} 张参考图片")
        contents: List[Any] = [types.Part.from_bytes(data=data, mime_type=detect_mime_type(data)) for data in images]
        full_prompt = prompt
        if self.negative_prompt:
            full_prompt += f"\nNegative prompt: {self.negative_prompt}"
        contents.append(full_prompt)
        # 每个后台任务使用独立 SDK 客户端，避免取消或配置重载影响其他任务。
        config = self._build_generate_content_config()
        if model.strip().lower().startswith("gemini-2.5-") and config.image_config and config.image_config.image_size:
            raise ValueError("Gemini 2.5 图片模型不支持分辨率档位，请将 image_size 留空")
        try:
            with genai.Client(**self._client_kwargs) as client:
                response = client.models.generate_content(model=model, contents=contents, config=config)
        except Exception as exc:
            raise RuntimeError(f"Google 图片请求失败：{sanitize_provider_text(exc, self.api_key)}") from None
        return self._extract_images_from_generate_content_response(response)

    def generate_images(self, prompt: str, model: str, n: int = 1) -> List[bytes]:
        """调用 Gemini 文生图接口。"""

        return self._generate(prompt, model, [], n)

    def edit_images(self, prompt: str, model: str, image_bytes_list: List[bytes], n: int = 1) -> List[bytes]:
        """调用 Gemini 图生图接口，保留所有有效参考图。"""

        if not image_bytes_list:
            raise ValueError("没有可用于图生图的源图片")
        return self._generate(prompt, model, image_bytes_list, n)
