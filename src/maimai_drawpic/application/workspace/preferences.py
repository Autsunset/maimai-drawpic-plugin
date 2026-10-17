"""可信实例内调用方的绘图偏好；不开放平台、密钥或全局配置写入。"""

from typing import Any, Callable, Dict, Optional
import asyncio

from ...domain.models.openai_profiles import OPENAI_COMPATIBILITY_MODES, normalize_openai_mode
from ...infrastructure.storage.preferences import NOVELAI_MODES, SessionPreferenceStore
from ..chat.service import ChatStreamService


def validate_preferences(values: Dict[str, Any]) -> Dict[str, str]:
    limits = {"model": 200, "openai_compatibility_mode": 40, "novelai_mode": 40, "novelai_artist_tags": 16000}
    if values.keys() - limits.keys():
        raise ValueError("绘图偏好包含未知字段")
    if any(not isinstance(value, str) or len(value) > limits[key] for key, value in values.items()):
        raise ValueError("绘图偏好应为长度限制内的文本")
    patch = {key: value.strip() for key, value in values.items()}
    if "openai_compatibility_mode" in patch:
        mode = normalize_openai_mode(patch["openai_compatibility_mode"])
        if mode and mode not in OPENAI_COMPATIBILITY_MODES:
            raise ValueError("OpenAI 兼容模式无效")
        patch["openai_compatibility_mode"] = mode
    if patch.get("novelai_mode", "") not in NOVELAI_MODES | {""}:
        raise ValueError("NovelAI 模式无效")
    return patch


class IntegrationPreferenceService:
    def __init__(self, streams: ChatStreamService, get_store: Callable[[], SessionPreferenceStore]) -> None:
        self.streams, self.get_store = streams, get_store

    async def preferences(self, stream_id: str, values: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if not isinstance(stream_id, str) or not stream_id.strip() or len(stream_id) > 200:
            raise ValueError("必须提供真实聊天流 ID，最长 200 个字符")
        patch = validate_preferences(values) if values is not None else None
        context = await self.streams.existing_stream_context(stream_id.strip())
        if not context.get("stream_id"):
            raise ValueError("当前聊天流不存在或无权访问")
        store = self.get_store()
        if patch is not None and patch.get("model") and patch["model"] not in store.router.get_all_models():
            raise ValueError("模型必须使用已启用的完整 平台名称/模型名称")
        identity = {key: context[key] for key in ("stream_id", "user_id", "group_id", "platform")}
        if patch is None:
            result = await asyncio.to_thread(store.get_preference, **identity)
        else:
            result = await asyncio.to_thread(store.set_preference, **identity, **patch)
        return {"stream_id": context["stream_id"], "preferences": result}
