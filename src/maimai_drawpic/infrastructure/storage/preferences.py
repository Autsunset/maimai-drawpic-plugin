from copy import deepcopy
from pathlib import Path
from threading import RLock
from typing import Any, Callable, Dict

from ...application.routing import ProviderRouter
from .atomic import write_json_atomically
from .settings import read_json_file
from ..concurrency import synchronized
from ...domain.models.openai_profiles import OPENAI_COMPATIBILITY_MODES, normalize_openai_mode

NOVELAI_MODES = {"anime", "furry", "background"}


class SessionPreferenceStore:
    """管理会话级模型配置。"""

    def __init__(
        self, path: Path, router: ProviderRouter, logger: Any,
        persist: Callable[[Dict[str, Dict[str, str]]], Dict[str, Dict[str, str]]] | None = None,
    ) -> None:
        self.path = path
        self.router = router
        self.logger = logger
        self.preferences: dict[str, dict[str, str]] = {}
        self._load_failed = False
        self._lock = RLock()
        self._persist = persist

    @staticmethod
    def resolve_session_key(
        stream_id: str,
        user_id: str = "",
        group_id: str = "",
        platform: str = "qq",
    ) -> str:
        """生成会话级模型配置键。"""

        normalized_platform = platform.strip() or "qq"
        normalized_group_id = group_id.strip()
        normalized_user_id = user_id.strip()
        normalized_stream_id = stream_id.strip()

        if normalized_group_id:
            return f"{normalized_platform}:group:{normalized_group_id}"
        if normalized_user_id:
            return f"{normalized_platform}:user:{normalized_user_id}"
        return f"{normalized_platform}:stream:{normalized_stream_id}"

    @synchronized
    def load(self) -> None:
        """从本地文件加载会话级模型配置。"""

        self._load_failed = True
        if not self.path.exists():
            self.preferences = {}
            self._load_failed = False
            return

        try:
            raw_data = read_json_file(self.path)
        except (OSError, ValueError) as exc:
            raise ValueError("会话偏好文件无法读取，已保留原件，请从备份恢复") from exc

        self.preferences = self.validate_payload(raw_data)
        self.normalize_all()
        self._load_failed = False

    @staticmethod
    def validate_payload(raw_data: Any) -> Dict[str, Dict[str, str]]:
        """校验持久化偏好，供加载与模型标识迁移事务共同使用。"""
        if not isinstance(raw_data, dict):
            raise ValueError("会话偏好文件格式不正确，已保留原件")

        normalized_preferences: dict[str, dict[str, str]] = {}
        fields = {"model", "openai_compatibility_mode", "novelai_mode", "novelai_artist_tags"}
        for session_key, session_value in raw_data.items():
            if (
                not isinstance(session_key, str) or not session_key.strip()
                or not isinstance(session_value, dict) or session_value.keys() - fields
                or any(not isinstance(value, str) for value in session_value.values())
            ):
                raise ValueError("会话偏好记录格式不正确或包含未知字段，已保留原件")
            mode = session_value.get("openai_compatibility_mode", "").strip()
            novelai_mode = session_value.get("novelai_mode", "").strip()
            if (
                mode and normalize_openai_mode(mode) not in OPENAI_COMPATIBILITY_MODES
                or novelai_mode and novelai_mode not in NOVELAI_MODES
            ):
                raise ValueError("会话偏好包含无法识别的模式，已保留原件")
            normalized_preferences[session_key] = {
                "model": session_value.get("model", "").strip(),
                "openai_compatibility_mode": session_value.get("openai_compatibility_mode", "").strip(),
                "novelai_mode": session_value.get("novelai_mode", "").strip(),
                "novelai_artist_tags": session_value.get("novelai_artist_tags", "").strip(),
            }
        return normalized_preferences

    @synchronized
    def save(self) -> None:
        """保存会话级模型配置到本地文件。"""
        self._save_values(self.preferences)

    def _save_values(self, values: Dict[str, Dict[str, str]]) -> None:
        if self._load_failed:
            raise ValueError("会话偏好文件尚未恢复，拒绝覆盖原件")
        normalized = self._normalized(values)
        if self._persist is None:
            write_json_atomically(self.path, normalized)
        else:
            normalized = self._persist(normalized)
        # 写盘成功后一次发布内存快照，读取不必等待持有写锁的文件 IO。
        self.preferences = normalized

    @synchronized
    def normalize_all(self) -> None:
        """校正所有会话级模型配置。"""
        self.preferences = self._normalized(self.preferences)

    @staticmethod
    def _normalized(values: Dict[str, Dict[str, str]]) -> Dict[str, Dict[str, str]]:
        normalized_preferences: dict[str, dict[str, str]] = {}
        for session_key, session_value in values.items():
            model = str(session_value.get("model") or "").strip()
            openai_compatibility_mode = normalize_openai_mode(str(session_value.get("openai_compatibility_mode") or ""))
            novelai_mode = str(session_value.get("novelai_mode") or "").strip()
            novelai_artist_tags = str(session_value.get("novelai_artist_tags") or "").strip()
            normalized_preferences[session_key] = {
                # 暂时禁用的平台或升级后有歧义的短名仍是用户的显式选择；
                # 保留原值，由使用模型的入口报错，不能在加载/保存时静默清空。
                "model": model,
                "openai_compatibility_mode": (
                    openai_compatibility_mode if openai_compatibility_mode in OPENAI_COMPATIBILITY_MODES else ""
                ),
                "novelai_mode": novelai_mode if novelai_mode in NOVELAI_MODES else "",
                "novelai_artist_tags": novelai_artist_tags,
            }
        return normalized_preferences

    @synchronized
    def rebind_router(
        self, router: ProviderRouter, replacements: Dict[str, str],
        persist: Callable[[Dict[str, Dict[str, str]]], Dict[str, Dict[str, str]]],
    ) -> None:
        """刷新复用同一存储对象，保留工作线程中已持有该对象的会话更新。"""
        self.router = router
        self._persist = persist
        self.preferences = {
            key: {**value, "model": replacements.get(value.get("model", ""), value.get("model", ""))}
            for key, value in self.preferences.items()
        }
        self.normalize_all()

    def get_preference(
        self,
        stream_id: str,
        user_id: str = "",
        group_id: str = "",
        platform: str = "qq",
    ) -> dict[str, str]:
        """获取当前会话的模型配置；未设置模型时不写入默认模型。"""

        session_key = self.resolve_session_key(stream_id, user_id, group_id, platform)
        session_value = self.preferences.get(session_key, {})
        router = self.router
        model = str(session_value.get("model") or "").strip()
        openai_compatibility_mode = normalize_openai_mode(str(session_value.get("openai_compatibility_mode") or ""))
        novelai_mode = str(session_value.get("novelai_mode") or "").strip()
        novelai_artist_tags = str(session_value.get("novelai_artist_tags") or "").strip()
        resolved_preference = {
            "model": (
                router.resolve_model_name(model, allow_unknown_model=False)
                if model and router.get_model_provider(model) else model
            ),
            "openai_compatibility_mode": (
                openai_compatibility_mode if openai_compatibility_mode in OPENAI_COMPATIBILITY_MODES else ""
            ),
            "novelai_mode": novelai_mode if novelai_mode in NOVELAI_MODES else "",
            "novelai_artist_tags": novelai_artist_tags,
        }
        return resolved_preference

    @synchronized
    def set_preference(
        self,
        stream_id: str,
        user_id: str = "",
        group_id: str = "",
        platform: str = "qq",
        *,
        model: str | None = None,
        openai_compatibility_mode: str | None = None,
        novelai_mode: str | None = None,
        novelai_artist_tags: str | None = None,
    ) -> dict[str, str]:
        """更新当前会话的模型配置并持久化。"""

        session_key = self.resolve_session_key(stream_id, user_id, group_id, platform)
        current_value = self.get_preference(stream_id, user_id, group_id, platform)
        next_value = {
            "model": current_value["model"],
            "openai_compatibility_mode": current_value["openai_compatibility_mode"],
            "novelai_mode": current_value["novelai_mode"],
            "novelai_artist_tags": current_value["novelai_artist_tags"],
        }
        if model is not None:
            next_value["model"] = self.router.resolve_model_name(model, allow_unknown_model=False)
        if openai_compatibility_mode is not None:
            normalized_mode = normalize_openai_mode(openai_compatibility_mode)
            next_value["openai_compatibility_mode"] = (
                normalized_mode if normalized_mode in OPENAI_COMPATIBILITY_MODES else ""
            )
        if novelai_mode is not None:
            normalized_novelai_mode = novelai_mode.strip()
            next_value["novelai_mode"] = normalized_novelai_mode if normalized_novelai_mode in NOVELAI_MODES else ""
        if novelai_artist_tags is not None:
            next_value["novelai_artist_tags"] = novelai_artist_tags.strip()
        updated = deepcopy(self.preferences)
        updated[session_key] = next_value
        self._save_values(updated)
        return dict(self.preferences[session_key])
