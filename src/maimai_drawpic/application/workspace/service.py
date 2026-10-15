"""绘图工作台的配置、模型、会话和预设业务边界。"""

from typing import Any, Callable, Dict
import asyncio

from ...domain.configuration.models import DrawpicConfig, StylePresetConfig
from ...infrastructure.storage.platforms import (
    PLATFORM_NAMES,
    WorkspaceConfigStore,
    _mask_secrets,
    _validate_fields,
    parse_json_object,
)
from .tasks import WorkspaceTaskService
from ...infrastructure.storage.settings import workspace_config


class WorkspaceService:
    def __init__(
        self,
        *,
        ctx: Any,
        store: WorkspaceConfigStore,
        tasks: WorkspaceTaskService,
        logs: Any,
        get_config: Callable,
        apply_settings: Callable,
        refresh: Callable,
    ) -> None:
        self.ctx, self.store, self.tasks, self.logs = ctx, store, tasks, logs
        self.get_config, self.apply_settings, self.refresh = get_config, apply_settings, refresh
        self.lock = asyncio.Lock()

    def models(self) -> Dict[str, Any]:
        router = self.tasks.get_service().router
        default_model, default_model_error = "", ""
        if router.get_all_models():
            try:
                default_model = router.resolve_default_model()
            except ValueError as exc:
                default_model_error = str(exc)
        return {
            "models": [
                {
                    **router.describe_model(model),
                    "draw": router.evaluate_model_task_capability(model, "draw").allowed,
                    "edit_image": router.evaluate_model_task_capability(model, "edit_image").allowed,
                    "edit_reason": router.evaluate_model_task_capability(model, "edit_image").reason,
                }
                for model in router.get_all_models()
            ],
            "default_model": default_model,
            "default_model_error": default_model_error,
        }

    async def bootstrap(self) -> Dict[str, Any]:
        snapshot = await asyncio.to_thread(self.store.public_snapshot)
        config = snapshot["settings"]
        config.pop("plugin", None)
        defaults = workspace_config(DrawpicConfig().model_dump(mode="json"))
        defaults.pop("plugin", None)
        schema = self.store.schema()
        schema["sections"].pop("plugin", None)
        schema["sections"].pop("proxy", None)
        return {
            **snapshot,
            "settings": _mask_secrets(config),
            "defaults": _mask_secrets(defaults),
            "schema": schema,
            "catalog": [
                {
                    "kind": key,
                    "name": name,
                    "defaults": _mask_secrets(self.store.platform_model(key)().model_dump(mode="json")),
                }
                for key, name in PLATFORM_NAMES.items()
            ],
            **self.models(),
            "presets": config["style"]["presets"],
            "proxy_password_set": bool(self.get_config().proxy.password),
        }

    async def _refresh_committed(self, values: Dict[str, Any] | None = None) -> Dict[str, Any]:
        status = {"saved": True, "revision": self.store.revision, "recovery_pending": self.store.recovery_pending}
        warnings = []
        if self.store.recovery_pending:
            warnings.append("配置已保存，文件同步尚未完成；下次保存或重新加载插件时将先恢复已提交事务")
        try:
            if values is None:
                await self.refresh()
            else:
                await self.apply_settings(values)
        except Exception as exc:
            # 持久化已经成功。不得让运行时刷新故障把成功提交误报为保存失败。
            status["runtime_refresh_pending"] = True
            warnings.append("配置已保存，但运行时刷新未完成，请重新加载插件后检查")
            self.ctx.logger.warning("配置已保存但运行时刷新失败: error_type=%s", type(exc).__name__)
        if warnings:
            status["warning"] = "；".join(warnings)
        return status

    async def save_provider(self, provider_json: str, revision: int) -> Dict[str, Any]:
        payload = parse_json_object(provider_json)
        async with self.lock:
            result = await asyncio.to_thread(self.store.save_provider, payload, revision)
            result.update(await self._refresh_committed())
            self.ctx.logger.info("平台配置已保存: platform_id=%s kind=%s", result["id"], payload["kind"])
            return result

    async def delete_provider(self, provider_id: str, revision: int) -> Dict[str, Any]:
        async with self.lock:
            await asyncio.to_thread(self.store.delete_provider, provider_id, revision)
            status = await self._refresh_committed()
            self.ctx.logger.info("平台配置已移除: platform_id=%s", provider_id)
            return {"deleted": True, **status}

    async def save_settings(self, config_json: str, revision: int) -> Dict[str, Any]:
        values = parse_json_object(config_json)
        # 旧页面可能仍回传宿主字段；明确忽略这些已移出工作台的字段，避免阻止绘图设置保存。
        if values.keys() - {"plugin", "proxy", "general", "style", "clear_proxy_password"}:
            raise ValueError("工作台配置包含未知分类")
        values = workspace_config(values)
        async with self.lock:
            if revision != self.store.revision:
                raise ValueError("配置已更新，请刷新后保存")
            current = self.get_config().model_dump(mode="json")
            updated = await asyncio.to_thread(self.store.save_common, values, current, revision)
            return await self._refresh_committed(updated)

    async def presets(self, operation: str = "list", name: str = "", preset_json: str = "") -> Dict[str, Any]:
        if operation not in {"list", "get", "save", "delete"} or len(name) > 80:
            raise ValueError("预设操作或名称无效")
        async with self.lock:
            snapshot = await asyncio.to_thread(self.store.public_snapshot)
            current = snapshot["settings"]
            presets = current["style"]["presets"]
            target = next((item for item in presets if item["name"].casefold() == name.casefold()), None)
            if operation == "list":
                return {"presets": presets, "default_style": current["style"]["default_style"]}
            if operation == "get":
                if target is None:
                    raise ValueError("预设不存在")
                return {"preset": target}
            if operation == "delete":
                if target is None:
                    raise ValueError("预设不存在")
                presets.remove(target)
                if current["style"]["default_style"].casefold() == name.casefold():
                    current["style"]["default_style"] = ""
            else:
                preset = _validate_fields(StylePresetConfig, parse_json_object(preset_json))
                if not preset["name"].strip() or len(preset["name"]) > 80 or len(presets) >= 100 and target is None:
                    raise ValueError("预设名称必须为 1～80 个字符，最多保存 100 个预设")
                if target is not None:
                    if any(
                        item is not target and item["name"].casefold() == preset["name"].casefold() for item in presets
                    ):
                        raise ValueError("已有同名预设")
                    presets[presets.index(target)] = preset
                else:
                    if any(item["name"].casefold() == preset["name"].casefold() for item in presets):
                        raise ValueError("已有同名预设")
                    presets.append(preset)
            updated = await asyncio.to_thread(self.store.save_common, workspace_config(current), current, snapshot["revision"])
            status = await self._refresh_committed(updated)
            return {"presets": presets, **status}

    async def streams(self, platform: str = "qq") -> Dict[str, Any]:
        if not platform or len(platform) > 80:
            raise ValueError("平台标识无效")
        raw = await self.ctx.chat.get_all_streams(platform=platform)
        # SDK 返回当前宿主序列化的真实聊天流，不构造资源归属 ID。
        from ..chat import ChatStreamService

        streams = ChatStreamService._unwrap_stream_list_result(raw)
        if not isinstance(streams, list):
            raise ValueError("宿主返回的聊天流列表格式不正确")
        items = []
        for stream in streams:
            if not isinstance(stream, dict):
                raise ValueError("宿主返回了不支持的聊天流结构")
            session_id = str(stream.get("session_id") or stream.get("stream_id") or "")
            name = stream.get("group_name") or stream.get("session_name") or stream.get("name")
            if not name:
                name = f"{stream.get('user_cardname') or stream.get('user_nickname') or stream.get('user_id') or '用户'}的私聊"
            if session_id:
                items.append({"id": session_id, "name": name, "platform": platform})
        return {"streams": items}
