"""commands/preferences.py 的插件组件。"""


class PreferenceMixin:
    """commands/preferences.py 对应的插件行为。"""

    def _get_session_preference(
        self,
        stream_id: str,
        user_id: str = "",
        group_id: str = "",
        platform: str = "qq",
    ) -> dict[str, str]:
        """获取当前会话的模型配置。"""

        return self._require_session_store().get_preference(stream_id, user_id, group_id, platform)

    def _set_session_preference(
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
        """更新当前会话的模型配置。"""

        return self._require_session_store().set_preference(
            stream_id,
            user_id,
            group_id,
            platform,
            model=model,
            openai_compatibility_mode=openai_compatibility_mode,
            novelai_mode=novelai_mode,
            novelai_artist_tags=novelai_artist_tags,
        )

    def _is_admin(self, user_id: str) -> bool:
        """判断用户是否为插件管理员。"""

        normalized_user_id = user_id.strip()
        if not normalized_user_id:
            return False
        admin_ids = {str(admin_id).strip() for admin_id in self.config.general.admin_user_ids}
        return normalized_user_id in admin_ids

    def _can_manage_session(self, user_id: str) -> bool:
        """判断用户是否可管理模型、兼容模式与次数。"""

        if not self.config.general.permission_enabled:
            return True
        return self._is_admin(user_id)
