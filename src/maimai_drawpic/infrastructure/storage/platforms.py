"""按需添加的平台配置、密钥保护和旧 TOML 迁移。"""

from copy import deepcopy
from datetime import datetime
from maibot_sdk.config import generate_plugin_config_schema
from pathlib import Path
from pydantic import BaseModel, ValidationError
from typing import Any, Dict, List, Mapping
from uuid import uuid4
import json
import re
import shutil
import tomlkit

from ...domain.configuration.models import DrawpicConfig, OpenAICompatibleInstanceConfig
from ...application.routing import ProviderRouter
from .atomic import write_json_atomically, write_text_atomically
from .settings import WorkspaceSettingsStore, workspace_config


PLATFORM_NAMES = {
    "openai": "OpenAI / 兼容服务",
    "google": "Google Gemini",
    "zhipu": "智谱",
    "aliyun": "阿里百炼",
    "volcengine": "火山引擎",
    "siliconflow": "硅基流动",
    "novelai": "NovelAI / NovelAPI",
    "comfyui": "ComfyUI",
}
COMMON_SECTIONS = ("plugin", "general", "style", "proxy")
HOST_SECTIONS = ("plugin", "proxy")
SECRET_FIELDS = {"api_key", "password"}


def common_config(config: Mapping[str, Any]) -> Dict[str, Any]:
    """只保留宿主管理的非平台配置。"""
    result = {key: deepcopy(config[key]) for key in COMMON_SECTIONS if key in config}
    general = result.get("general", {})
    legacy_fallback = general.pop("fallback_model", "")
    if legacy_fallback and not general.get("fallback_models"):
        general["fallback_models"] = [legacy_fallback]
    return result


def host_config(config: Mapping[str, Any]) -> Dict[str, Any]:
    return {key: deepcopy(config[key]) for key in HOST_SECTIONS if key in config}


def parse_json_object(value: str) -> Dict[str, Any]:
    if len(value.encode("utf-8")) > 60 * 1024:
        raise ValueError("配置超过 60 KiB，请分次保存")
    result = json.loads(value, parse_constant=lambda _: _invalid_number())
    if not isinstance(result, dict):
        raise ValueError("配置必须是对象")
    pending = [(result, 0)]
    count = 0
    while pending:
        item, depth = pending.pop()
        count += 1
        if depth > 16 or count > 5000:
            raise ValueError("配置嵌套或元素数量超过限制")
        if isinstance(item, dict):
            pending.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            pending.extend((child, depth + 1) for child in item)
    return result


def _invalid_number() -> None:
    raise ValueError("配置不能包含非有限数字")


def _mask_secrets(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: "" if key in SECRET_FIELDS else _mask_secrets(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_mask_secrets(item) for item in value]
    return deepcopy(value)


def _validate_fields(model: Any, values: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(values, dict):
        raise ValueError("配置字段必须是对象")
    unknown = values.keys() - model.model_fields.keys()
    if unknown:
        raise ValueError(f"未知配置字段: {', '.join(sorted(unknown))}")
    try:
        validated = model.model_validate(values)
    except ValidationError as exc:
        # 错误只返回字段位置与错误类型，不能把含密钥的输入值带回页面或日志。
        fields = [
            f"{'.'.join(map(str, error['loc']))}: {error['type']}"
            for error in exc.errors(include_input=False, include_context=False)
        ]
        raise ValueError("配置校验失败: " + "; ".join(fields)) from None

    def check_nested(value: Any, raw: Any) -> None:
        if isinstance(value, BaseModel) and isinstance(raw, dict):
            if raw.keys() - type(value).model_fields.keys():
                raise ValueError("嵌套配置包含未知字段")
            for key, child in raw.items():
                check_nested(value.__dict__[key], child)
        elif isinstance(value, list) and isinstance(raw, list):
            for child, original in zip(value, raw, strict=True):
                check_nested(child, original)

    check_nested(validated, values)
    return validated.model_dump(mode="json")


class WorkspaceConfigStore:
    """拥有平台配置；未添加的平台在运行时明确禁用。"""

    def __init__(self, data_dir: Path, config_path: Path) -> None:
        self.path = data_dir / "platforms.json"
        self.config_path = config_path
        self.providers: List[Dict[str, Any]] = []
        self.revision = 0
        self.settings = WorkspaceSettingsStore(data_dir, config_path)

    @staticmethod
    def platform_model(kind: str) -> Any:
        if kind not in PLATFORM_NAMES:
            raise ValueError("未知绘图平台")
        return DrawpicConfig.model_fields[kind].annotation

    def initialize(self, legacy_config: Dict[str, Any]) -> None:
        """平台配置成功持久化并备份之后，才移除 TOML 平台节。"""
        # 在写 JSON、重命名平台或移除任何 TOML 节之前完成全部冲突检查。
        document = tomlkit.parse(self.config_path.read_text(encoding="utf-8")) if self.config_path.exists() else {}
        self.settings.check_legacy_conflicts(document)
        if self.path.exists():
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if (
                not isinstance(payload, dict)
                or payload.get("schema_version") != 1
                or not isinstance(payload.get("providers"), list)
            ):
                raise ValueError("platforms.json 格式或版本不受支持")
            self.providers = [self._validate_record(record) for record in payload["providers"]]
            ids = [item["id"] for item in self.providers]
            if len(ids) != len(set(ids)):
                raise ValueError("platforms.json 存在重复平台 ID")
            if type(payload.get("revision")) is not int or payload["revision"] < 0:
                raise ValueError("platforms.json 修订号无效")
            self.revision = payload["revision"]
            legacy = WorkspaceConfigStore(self.path.parent, self.config_path)
            legacy._import_legacy_platforms(document)

            def comparable(records):
                return sorted((item["kind"], json.dumps(item["config"], sort_keys=True)) for item in records)

            if legacy.providers and comparable(legacy.providers) != comparable(self.providers):
                raise ValueError(
                    "旧 config.toml 与 platforms.json 存在冲突，已保留原文件。请先备份，确认保留哪份平台配置，再移走另一份后重新加载插件。"
                )
            names = set()
            renamed = False
            for record in self.providers:
                base = record["name"].strip()
                name, suffix = base, 2
                while name.casefold() in names:
                    name = f"{base[:70]} {suffix}"
                    suffix += 1
                names.add(name.casefold())
                if name != record["name"]:
                    record["name"] = name
                    renamed = True
            if renamed:
                backup = self.path.parent / "migration_backups" / f"platforms-{uuid4().hex}.json"
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(self.path, backup)
                self.revision += 1
                self._save()
        else:
            self._import_legacy_platforms(legacy_config)
            self.revision = 1
            self._save()

        if self.config_path.exists():
            document = tomlkit.parse(self.config_path.read_text(encoding="utf-8"))
            if any(key in document for key in PLATFORM_NAMES):
                backup_dir = self.path.parent / "migration_backups"
                backup_dir.mkdir(parents=True, exist_ok=True)
                backup = backup_dir / f"config-{datetime.now():%Y%m%d-%H%M%S}-{uuid4().hex[:8]}.toml"
                shutil.copy2(self.config_path, backup)
                if backup.read_bytes() != self.config_path.read_bytes():
                    raise RuntimeError("配置备份校验失败，保留原配置")
                for kind in PLATFORM_NAMES:
                    document.pop(kind, None)
                write_text_atomically(self.config_path, tomlkit.dumps(document))

        self.settings.initialize(legacy_config)

    def _import_legacy_platforms(self, legacy_config: Dict[str, Any]) -> None:
        """只导入有实际配置的平台，用于首次迁移与无副作用冲突检查。"""
        normalized = DrawpicConfig.model_validate(legacy_config).model_dump(mode="json")
        defaults = DrawpicConfig().model_dump(mode="json")
        for kind in PLATFORM_NAMES:
            values = deepcopy(normalized[kind])
            instances = values.pop("instances", []) if kind == "openai" else []
            # 只迁移启用、填过密钥或修改过参数的平台，不展示无用的默认平台。
            meaningful = bool(values.get("api_key", "")) and values.get("api_key") != defaults[kind].get("api_key")
            meaningful = meaningful or (kind == "comfyui" and values.get("enabled", False))
            meaningful = meaningful or any(
                value != defaults[kind].get(key) for key, value in values.items() if key != "enabled"
            )
            if meaningful:
                self.providers.append(self._new_record(kind, PLATFORM_NAMES[kind], values))
            for index, instance in enumerate(instances, 1):
                values = deepcopy(instance)
                name = values.pop("name") or f"兼容服务 {index}"
                model_text = values.pop("models")
                values["models"] = [
                    f"{display}={upstream}" if display != upstream else upstream
                    for display, upstream in ProviderRouter._parse_model_routes(model_text)
                ]
                for field in ("model_size_overrides", "extra_parameters"):
                    values[field] = ProviderRouter._parse_key_value_text(values[field])
                self.providers.append(self._new_record("openai", name, values))

    def _validate_record(self, record: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(record, dict) or set(record) != {"id", "kind", "name", "config"}:
            raise ValueError("平台记录格式错误")
        if not isinstance(record["id"], str) or not re.fullmatch(r"[a-f0-9]{32}", record["id"]):
            raise ValueError("平台 ID 格式错误")
        if (
            not isinstance(record["name"], str)
            or not record["name"].strip()
            or len(record["name"]) > 80
            or any(ord(char) < 32 for char in record["name"])
        ):
            raise ValueError("平台名称应为 1～80 个字符")
        if not isinstance(record["kind"], str) or record["kind"] not in PLATFORM_NAMES:
            raise ValueError("未知绘图平台")
        result = deepcopy(record)
        result["name"] = record["name"].strip()
        result["config"] = _validate_fields(self.platform_model(record["kind"]), record["config"])
        if record["kind"] == "openai":
            result["config"]["instances"] = []
        return result

    def _new_record(self, kind: str, name: str, config: Dict[str, Any]) -> Dict[str, Any]:
        base, suffix = name, 2
        while any(item["name"].strip().casefold() == name.strip().casefold() for item in self.providers):
            name = f"{base[:70]} {suffix}"
            suffix += 1
        return self._validate_record({"id": uuid4().hex, "kind": kind, "name": name, "config": config})

    def _save(self) -> None:
        write_json_atomically(self.path, {"schema_version": 1, "revision": self.revision, "providers": self.providers})

    def public_snapshot(self) -> Dict[str, Any]:
        return {
            "revision": self.revision,
            "providers": [
                {
                    **record,
                    "config": _mask_secrets(record["config"]),
                    "has_api_key": bool(record["config"].get("api_key", "")),
                }
                for record in self.providers
            ],
        }

    def save_provider(self, payload: Dict[str, Any], revision: int) -> Dict[str, Any]:
        if revision != self.revision:
            raise ValueError("配置已被其他页面更新，请刷新后再保存")
        if payload.keys() - {"id", "kind", "name", "config", "clear_api_key"}:
            raise ValueError("平台参数包含未知字段")
        if not {"kind", "name", "config"} <= payload.keys() or not isinstance(payload["name"], str):
            raise ValueError("平台类型、名称与配置为必填项")
        if type(revision) is not int or type(payload.get("clear_api_key", False)) is not bool:
            raise ValueError("平台参数类型无效")
        identifier = payload.get("id", "")
        previous = next((item for item in self.providers if item["id"] == identifier), None)
        if identifier and previous is None:
            raise ValueError("平台不存在，请刷新列表")
        kind = payload["kind"]
        if previous is not None and kind != previous["kind"]:
            raise ValueError("平台类型不能修改，请新建平台")
        if any(
            item["name"].strip().casefold() == payload["name"].strip().casefold() and item["id"] != identifier
            for item in self.providers
        ):
            raise ValueError("平台名称不能重复")
        if previous is None and len(self.providers) >= 40:
            raise ValueError("最多添加 40 个平台实例")
        values = deepcopy(payload["config"])
        if not isinstance(values, dict):
            raise ValueError("平台配置必须是对象")
        if "instances" in values and values["instances"]:
            raise ValueError("请将兼容实例分别添加为平台")
        if previous is not None and not values.get("api_key", "") and not payload.get("clear_api_key", False):
            if "api_key" in previous["config"]:
                values["api_key"] = previous["config"]["api_key"]
        record = self._validate_record(
            {"id": identifier or uuid4().hex, "kind": kind, "name": payload["name"].strip(), "config": values}
        )
        updated = [record if item["id"] == identifier else item for item in self.providers]
        if previous is None:
            updated.append(record)
        self._commit(updated)
        return {"id": record["id"], "revision": self.revision}

    def delete_provider(self, identifier: str, revision: int) -> None:
        if revision != self.revision:
            raise ValueError("配置已更新，请刷新")
        updated = [item for item in self.providers if item["id"] != identifier]
        if len(updated) == len(self.providers):
            raise ValueError("平台不存在")
        self._commit(updated)

    def _commit(self, providers: List[Dict[str, Any]]) -> None:
        if len(json.dumps(providers, ensure_ascii=False).encode("utf-8")) > 160 * 1024:
            raise ValueError("平台配置总大小超过 160 KiB，请精简配置")
        previous, previous_revision = self.providers, self.revision
        self.providers, self.revision = providers, self.revision + 1
        try:
            self._save()
        except OSError:
            self.providers, self.revision = previous, previous_revision
            raise

    def effective_config(self, base: Dict[str, Any], providers: List[Dict[str, Any]] | None = None) -> DrawpicConfig:
        records = self.providers if providers is None else providers
        values = DrawpicConfig.model_validate({**base, **self.settings.values}).model_dump(mode="json")
        for kind in PLATFORM_NAMES:
            values[kind] = self.platform_model(kind)().model_dump(mode="json")
            values[kind]["enabled"] = False
        openai_records = [item for item in records if item["kind"] == "openai"]
        for record in records:
            if record["kind"] != "openai":
                values[record["kind"]] = deepcopy(record["config"])
        if openai_records:
            instance_model = OpenAICompatibleInstanceConfig
            for record in openai_records:
                instance = {key: value for key, value in record["config"].items() if key in instance_model.model_fields}
                instance["name"] = record["name"]
                instance["models"] = ", ".join(record["config"]["models"])
                for field in ("model_size_overrides", "extra_parameters"):
                    instance[field] = "\n".join(record["config"][field])
                values["openai"]["instances"].append(instance)
        return DrawpicConfig.model_validate(values)

    def save_common(self, values: Dict[str, Any], current: Dict[str, Any]) -> Dict[str, Any]:
        if values.keys() - {"general", "style"}:
            raise ValueError("工作台仅维护通用与审核、风格预设")
        for section, fields in values.items():
            _validate_fields(DrawpicConfig.model_fields[section].annotation, fields)
        candidate = {**workspace_config(current), **deepcopy(values)}
        validated = workspace_config(DrawpicConfig.model_validate(candidate).model_dump(mode="json"))
        presets = validated["style"]["presets"]
        names = [item["name"].strip().casefold() for item in presets]
        if len(presets) > 100 or any(not name or len(name) > 80 for name in names) or len(names) != len(set(names)):
            raise ValueError("预设名称应为 1～80 字且不能重复，最多保存 100 个预设")
        if len(json.dumps(validated, ensure_ascii=False).encode("utf-8")) > 48 * 1024:
            raise ValueError("工作台配置总大小超过 48 KiB，请精简提示词模板")
        self.settings.save(validated)
        return validated

    @staticmethod
    def schema() -> Dict[str, Any]:
        return generate_plugin_config_schema(DrawpicConfig)

    def secrets(self) -> List[str]:
        return [item["config"]["api_key"] for item in self.providers if item["config"].get("api_key")]
