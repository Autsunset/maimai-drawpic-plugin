"""绘图通用设置与预设的独立配置文件及旧 TOML 迁移。"""

from copy import deepcopy
from pathlib import Path
from typing import Any, Dict
from uuid import uuid4
import json
import shutil
import tomlkit

from ...domain.configuration.models import DrawpicConfig, migrate_legacy_review_config
from .atomic import write_json_atomically, write_text_atomically

WORKSPACE_SECTIONS = ("general", "style")
LEGACY_REVIEW_SECTIONS = ("prompt_review", "image_review")


def workspace_config(config: Dict[str, Any]) -> Dict[str, Any]:
    result = {key: deepcopy(config[key]) for key in WORKSPACE_SECTIONS if key in config}
    general = result.get("general", {})
    legacy = general.pop("fallback_model", "")
    if legacy and not general.get("fallback_models"):
        general["fallback_models"] = [legacy]
    return result


def read_json_file(path: Path) -> Dict[str, Any]:
    def object_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("配置文件包含重复字段，已保留原文件")
            result[key] = value
        return result

    def invalid_constant(_):
        raise ValueError("配置文件包含非有限数值，已保留原文件")

    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=object_pairs, parse_constant=invalid_constant)


class WorkspaceSettingsStore:
    def __init__(self, data_dir: Path, config_path: Path) -> None:
        self.path = data_dir / "workspace_settings.json"
        self.config_path = config_path
        self.values: Dict[str, Any] = {}
        self.revision = 0

    @staticmethod
    def validate_payload(payload: Any) -> Dict[str, Any]:
        if not isinstance(payload, dict) or type(payload.get("schema_version")) is not int:
            raise ValueError("workspace_settings.json 格式或版本不正确")
        version = payload["schema_version"]
        fields = {"schema_version", "settings"} | ({"revision"} if version == 2 else set())
        if version not in (1, 2) or set(payload) != fields:
            raise ValueError("workspace_settings.json 格式或版本不正确")
        if version == 2 and (type(payload["revision"]) is not int or payload["revision"] < 0):
            raise ValueError("workspace_settings.json 修订号无效")
        values = payload["settings"]
        if not isinstance(values, dict) or set(values) != set(WORKSPACE_SECTIONS):
            raise ValueError("workspace_settings.json 缺少配置分类或包含未知分类")
        # 延迟导入以复用同一严格字段校验，防止升级时静默丢弃未知数据。
        from .platforms import _validate_fields

        for section, fields in values.items():
            _validate_fields(DrawpicConfig.model_fields[section].annotation, fields)
        return payload

    def read_payload(self) -> Dict[str, Any]:
        return self.validate_payload(read_json_file(self.path))

    def check_legacy_conflicts(self, document: Dict[str, Any]) -> None:
        if not self.path.exists():
            return
        payload = self.read_payload()
        sections = set(document) & set(WORKSPACE_SECTIONS)
        if set(document) & set(LEGACY_REVIEW_SECTIONS):
            sections.add("general")
        saved = workspace_config(DrawpicConfig.model_validate(payload["settings"]).model_dump(mode="json"))
        restored = workspace_config(
            DrawpicConfig.model_validate(migrate_legacy_review_config(document)).model_dump(mode="json")
        )
        if any(saved[section] != restored[section] for section in sections):
            raise ValueError(
                "旧 config.toml 与 workspace_settings.json 存在冲突，已保留原文件。请先备份，确认保留哪份绘图设置，再移走另一份后重新加载插件。"
            )

    def initialize(self, legacy: Dict[str, Any]) -> None:
        original = self.config_path.read_bytes() if self.config_path.exists() else b""
        document = tomlkit.parse(original.decode("utf-8"))
        if self.config_path.exists():
            self.check_legacy_conflicts(document)
        payload = self.read_payload() if self.path.exists() else None
        # 平台阶段可能已移除平台节；通用与审核设置仍以本阶段实际读取的
        # TOML 为准，不能用较早的 Runner 快照盖掉两个阶段之间的外部修改。
        source = document if set(document) & {*WORKSPACE_SECTIONS, *LEGACY_REVIEW_SECTIONS} else legacy
        if payload is not None:
            source = payload["settings"]
        self.values = workspace_config(
            DrawpicConfig.model_validate(migrate_legacy_review_config(source)).model_dump(mode="json")
        )
        self.revision = payload.get("revision", 0) if payload is not None else 0
        if payload is None or payload["schema_version"] == 1:
            if payload is not None:
                backup = self.path.parent / "migration_backups" / f"workspace-settings-{uuid4().hex}.json"
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(self.path, backup)
                if backup.read_bytes() != self.path.read_bytes():
                    raise RuntimeError("通用配置备份校验失败，保留原文件")
            self._save()
        current = self.config_path.read_bytes() if self.config_path.exists() else b""
        if current != original:
            raise ValueError("config.toml 已在外部修改，已保留原文件，请重新加载插件")
        if self.config_path.exists():
            if any(key in document for key in (*WORKSPACE_SECTIONS, *LEGACY_REVIEW_SECTIONS)):
                backup = self.path.parent / "migration_backups" / f"workspace-config-{uuid4().hex}.toml"
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(self.config_path, backup)
                if backup.read_bytes() != self.config_path.read_bytes():
                    raise RuntimeError("通用配置备份校验失败，保留原文件")
                if self.config_path.read_bytes() != original:
                    raise ValueError("config.toml 已在外部修改，已保留原文件，请重新加载插件")
                for key in (*WORKSPACE_SECTIONS, *LEGACY_REVIEW_SECTIONS):
                    document.pop(key, None)
                write_text_atomically(self.config_path, tomlkit.dumps(document))

    def payload(self, values: Dict[str, Any] | None = None, revision: int | None = None) -> Dict[str, Any]:
        return {
            "schema_version": 2,
            "revision": self.revision if revision is None else revision,
            "settings": self.values if values is None else values,
        }

    def _save(self, values: Dict[str, Any] | None = None, revision: int | None = None) -> None:
        write_json_atomically(self.path, self.payload(values, revision))

    def save(self, values: Dict[str, Any], revision: int) -> None:
        candidate = deepcopy(values)
        self._save(candidate, revision)
        self.values, self.revision = candidate, revision
