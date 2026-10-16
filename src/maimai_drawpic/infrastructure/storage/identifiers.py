"""将旧平台名称、模型别名和模型引用迁成统一的 平台/模型 标识。"""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Mapping, Set, Tuple
from uuid import uuid4
import re

from ...application.routing import ProviderRouter
from .preferences import SessionPreferenceStore
from .settings import read_json_file

if TYPE_CHECKING:
    from .platforms import WorkspaceConfigStore


def _name_plan(label: str, default_name: str, original: str) -> Tuple[str, str]:
    """类型说明不作为实例名；只修复已知旧默认名及其自动编号。"""
    if re.search(r"\s|/", label):
        for old_default in (label, re.sub(r"\s", "_", label)):
            match = re.fullmatch(re.escape(old_default) + r"(?:[ _]([1-9][0-9]*))?", original)
            if match is not None:
                return default_name + (f"_{match[1]}" if match[1] else ""), default_name
    normalized = re.sub(r"\s", "_", original)
    return normalized, normalized


def _normalize_records(
    providers: List[Dict[str, Any]], labels: Mapping[str, str], defaults: Mapping[str, str]
) -> List[Dict[str, Any]]:
    result = deepcopy(providers)
    plans = [_name_plan(labels[item["kind"]], defaults[item["kind"]], item["name"]) for item in providers]
    # 先保留已有合法自定义名称，旧默认名不能抢占“OpenAI_Compatible”或“平台_A”等实例。
    reserved = {item["name"].casefold() for item, (name, _) in zip(providers, plans, strict=True)
                if item["name"] == name}
    used: Set[str] = set()
    for record, (base, stem) in zip(result, plans, strict=True):
        original = record["name"]
        name, suffix = base, 2
        while name.casefold() in used or (original != base and name.casefold() in reserved):
            ending = f"_{suffix}"
            name = stem[:80 - len(ending)] + ending
            suffix += 1
        record["name"] = name
        used.add(name.casefold())
        config = record["config"]
        aliases = {}
        for key in ("models", "custom_models"):
            if key not in config:
                continue
            models = []
            for value in config[key]:
                if record["kind"] == "openai" and "=" in value:
                    alias, value = value.split("=", 1)
                    if alias.strip() in aliases and aliases[alias.strip()] != value.strip():
                        raise ValueError("旧模型别名对应多个真实模型，已保留原文件，请先统一模型 ID")
                    aliases[alias.strip()] = value.strip()
                model = value.strip()
                if not model:
                    raise ValueError("旧模型别名缺少真实模型 ID，已保留原文件，请补全后重新加载")
                if model not in models:
                    models.append(model)
            config[key] = models
        for key in ("model_size_overrides", "model_endpoint_overrides"):
            if key not in config:
                continue
            overrides: Dict[str, str] = {}
            for item in config[key]:
                model, separator, value = item.partition("=")
                if not separator:
                    raise ValueError("模型覆盖配置缺少等号，已保留原文件")
                model = aliases.get(model.strip(), model.strip())
                if model in overrides and overrides[model] != value:
                    raise ValueError("旧别名与真实模型的覆盖参数冲突，已保留原文件，请先统一参数")
                overrides[model] = value
            config[key] = [f"{model}={value}" for model, value in overrides.items()]
    return result


def remap_preferences(path: Path, replacements: Dict[str, str]) -> Tuple[Dict[str, Any], str] | None:
    """保留其余偏好原值，只改精确匹配的模型引用并绑定原始文件摘要。"""
    if not path.exists():
        return None
    original = path.read_bytes()
    raw = read_json_file(path)
    SessionPreferenceStore.validate_payload(raw)
    converted = deepcopy(raw)
    for value in converted.values():
        model = value.get("model", "")
        if model in replacements:
            value["model"] = replacements[model]
    if path.read_bytes() != original:
        raise ValueError("会话偏好已在模型标识迁移期间被外部修改，已保留原文件")
    return (converted, sha256(original).hexdigest()) if converted != raw else None


def migrate_model_identifiers(
    store: WorkspaceConfigStore, labels: Mapping[str, str], defaults: Mapping[str, str]
) -> None:
    """备份后将平台、设置与会话引用一次提交，写入中断可由同一事务恢复。"""
    updated = _normalize_records(store.providers, labels, defaults)
    candidates: Dict[str, Set[str]] = {}
    enabled_candidates: Dict[str, Set[str]] = {}
    for previous, record in zip(store.providers, updated, strict=True):
        catalog = deepcopy(previous)
        catalog["config"]["enabled"] = True
        router = ProviderRouter(store.effective_config({}, [catalog]))
        for model in router.get_all_models():
            upstream = router.describe_model(model)["upstream_model"]
            canonical = f"{record['name']}/{upstream}"
            for value in (model, upstream, f"{previous['name']} / {model}", f"{previous['name']}/{model}"):
                candidates.setdefault(value, set()).add(canonical)
            if previous["config"]["enabled"]:
                for value in (model, upstream):
                    enabled_candidates.setdefault(value, set()).add(canonical)
    for key, values in enabled_candidates.items():
        candidates[key] = values
    replacements = {key: next(iter(values)) for key, values in candidates.items() if len(values) == 1}
    settings = deepcopy(store.settings.values)
    general = settings["general"]
    general["default_model"] = replacements.get(general["default_model"], general["default_model"])
    for key in ("fallback_models", "image_edit_unsupported_models", "text_to_image_unsupported_models"):
        general[key] = list(dict.fromkeys(replacements.get(model, model) for model in general[key]))
    preference_path = store.path.parent / "session_preferences.json"
    originals = {store.path: store.path.read_bytes(), store.settings.path: store.settings.path.read_bytes()}
    if preference_path.exists():
        originals[preference_path] = preference_path.read_bytes()
    preferences = remap_preferences(preference_path, replacements)
    if updated == store.providers and settings == store.settings.values and preferences is None:
        return
    backup_dir = store.path.parent / "migration_backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    for path, original in originals.items():
        if path.read_bytes() != original:
            raise ValueError("配置已在模型标识迁移期间被外部修改，已保留原文件")
        backup = backup_dir / f"identifiers-{path.stem}-{uuid4().hex}.json"
        backup.write_bytes(original)
        if backup.read_bytes() != original:
            raise RuntimeError("模型标识迁移备份校验失败，保留原文件")
    store._commit(updated, settings=store._validate_common(settings, settings), preferences=preferences)
    # 启动时会话偏好尚未载入，必须先完成整个事务，不能读取一半旧引用。
    if store.recovery_pending:
        store._recover_transaction()
