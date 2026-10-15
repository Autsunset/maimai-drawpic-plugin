"""绘图通用设置与预设的独立配置文件及旧 TOML 迁移。"""

from copy import deepcopy
from pathlib import Path
from typing import Any, Dict
from uuid import uuid4
import json
import shutil
import tomlkit

from ...domain.configuration.models import DrawpicConfig
from .atomic import write_json_atomically, write_text_atomically

WORKSPACE_SECTIONS = ("general", "style")


def workspace_config(config: Dict[str, Any]) -> Dict[str, Any]:
    result = {key: deepcopy(config[key]) for key in WORKSPACE_SECTIONS if key in config}
    general = result.get("general", {})
    legacy = general.pop("fallback_model", "")
    if legacy and not general.get("fallback_models"):
        general["fallback_models"] = [legacy]
    return result


class WorkspaceSettingsStore:
    def __init__(self, data_dir: Path, config_path: Path) -> None:
        self.path = data_dir / "workspace_settings.json"
        self.config_path = config_path
        self.values: Dict[str, Any] = {}

    def check_legacy_conflicts(self, document: Dict[str, Any]) -> None:
        sections = set(document) & set(WORKSPACE_SECTIONS)
        if not self.path.exists() or not sections:
            return
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if (
            not isinstance(payload, dict)
            or payload.get("schema_version") != 1
            or not isinstance(payload.get("settings"), dict)
        ):
            raise ValueError("workspace_settings.json 格式或版本不正确")
        saved = workspace_config(DrawpicConfig.model_validate(payload["settings"]).model_dump(mode="json"))
        restored = workspace_config(DrawpicConfig.model_validate(document).model_dump(mode="json"))
        if any(saved[section] != restored[section] for section in sections):
            raise ValueError(
                "旧 config.toml 与 workspace_settings.json 存在冲突，已保留原文件。请先备份，确认保留哪份绘图设置，再移走另一份后重新加载插件。"
            )

    def initialize(self, legacy: Dict[str, Any]) -> None:
        if self.config_path.exists():
            self.check_legacy_conflicts(tomlkit.parse(self.config_path.read_text(encoding="utf-8")))
        if self.path.exists():
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if (
                not isinstance(payload, dict)
                or payload.get("schema_version") != 1
                or not isinstance(payload.get("settings"), dict)
            ):
                raise ValueError("workspace_settings.json 格式或版本不正确")
            source = payload["settings"]
        else:
            source = legacy
        self.values = workspace_config(DrawpicConfig.model_validate(source).model_dump(mode="json"))
        if not self.path.exists():
            self._save()
        if self.config_path.exists():
            document = tomlkit.parse(self.config_path.read_text(encoding="utf-8"))
            if any(key in document for key in WORKSPACE_SECTIONS):
                backup = self.path.parent / "migration_backups" / f"workspace-config-{uuid4().hex}.toml"
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(self.config_path, backup)
                if backup.read_bytes() != self.config_path.read_bytes():
                    raise RuntimeError("通用配置备份校验失败，保留原文件")
                for key in WORKSPACE_SECTIONS:
                    document.pop(key, None)
                write_text_atomically(self.config_path, tomlkit.dumps(document))

    def _save(self) -> None:
        write_json_atomically(self.path, {"schema_version": 1, "settings": self.values})

    def save(self, values: Dict[str, Any]) -> None:
        previous = self.values
        self.values = deepcopy(values)
        try:
            self._save()
        except OSError:
            self.values = previous
            raise
