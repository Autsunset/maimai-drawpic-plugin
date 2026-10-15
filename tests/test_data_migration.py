"""验证持久数据迁移、冲突保护和工作流路径兼容。"""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from threading import get_ident
from types import ModuleType
from typing import Any, List

from maibot_sdk import PluginContext
from maibot_sdk.context import PluginPaths

import asyncio
import os
import pytest
import sys


_SPEC = spec_from_file_location(
    "drawpic_data_migration",
    Path(__file__).parents[1] / "src" / "maimai_drawpic" / "infrastructure" / "storage" / "migration.py",
)
assert _SPEC is not None and _SPEC.loader is not None
_MIGRATION = module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MIGRATION)
migrate_plugin_data = _MIGRATION.migrate_plugin_data
resolve_workflow_path = _MIGRATION.resolve_workflow_path


def test_migration_preserves_bytes_config_and_backup(tmp_path: Path) -> None:
    plugin_dir = tmp_path / "plugins" / "drawpic"
    legacy_dir = plugin_dir / "data"
    workflows = legacy_dir / "workflows"
    workflows.mkdir(parents=True)
    payload = '{"说明": "换行保真"}\r\n'.encode("utf-8")
    (workflows / "t2i.json").write_bytes(payload)
    (legacy_dir / "user_quotas.json").write_bytes(b'{"quota": 3}\n')
    (plugin_dir / "session_preferences.json").write_bytes(b'{"model": "demo"}\n')
    config = b'[plugin]\r\nconfig_version = "2.30.0"\r\n'
    (plugin_dir / "config.toml").write_bytes(config)
    data_dir = tmp_path / "data" / "plugins" / "drawpic"

    backups = migrate_plugin_data(plugin_dir, data_dir)

    assert (data_dir / "workflows" / "t2i.json").read_bytes() == payload
    assert (data_dir / "user_quotas.json").read_bytes() == b'{"quota": 3}\n'
    assert (data_dir / "session_preferences.json").read_bytes() == b'{"model": "demo"}\n'
    assert (plugin_dir / "config.toml").read_bytes() == config
    assert not legacy_dir.exists()
    assert len(backups) == 2
    assert (backups[0] / "workflows" / "t2i.json").read_bytes() == payload
    assert migrate_plugin_data(plugin_dir, data_dir) == []


def test_conflict_is_reported_before_copying(tmp_path: Path) -> None:
    plugin_dir = tmp_path / "plugin"
    legacy_dir = plugin_dir / "data"
    legacy_dir.mkdir(parents=True)
    (legacy_dir / "a.json").write_bytes(b"new-file")
    (legacy_dir / "z.json").write_bytes(b"legacy")
    data_dir = tmp_path / "persistent"
    data_dir.mkdir()
    (data_dir / "z.json").write_bytes(b"existing")

    with pytest.raises(FileExistsError, match="不覆盖"):
        migrate_plugin_data(plugin_dir, data_dir)

    assert legacy_dir.exists()
    assert (data_dir / "z.json").read_bytes() == b"existing"
    assert not (data_dir / "a.json").exists()


def test_older_root_state_conflict_preserves_both_sources(tmp_path: Path) -> None:
    plugin_dir = tmp_path / "plugin"
    legacy_dir = plugin_dir / "data"
    legacy_dir.mkdir(parents=True)
    (legacy_dir / "draw_tasks.json").write_bytes(b"newer")
    (plugin_dir / "draw_tasks.json").write_bytes(b"older")

    with pytest.raises(FileExistsError, match="两处旧数据"):
        migrate_plugin_data(plugin_dir, tmp_path / "persistent")

    assert (legacy_dir / "draw_tasks.json").read_bytes() == b"newer"
    assert (plugin_dir / "draw_tasks.json").read_bytes() == b"older"


def test_interrupted_migration_can_resume(tmp_path: Path, monkeypatch: Any) -> None:
    plugin_dir = tmp_path / "plugin"
    legacy_dir = plugin_dir / "data"
    legacy_dir.mkdir(parents=True)
    (legacy_dir / "a.json").write_bytes(b"first")
    (legacy_dir / "b.json").write_bytes(b"second")
    data_dir = tmp_path / "persistent"
    real_link = os.link

    def interrupt_second_copy(source: Path, target: Path) -> None:
        if target.name == "b.json":
            raise PermissionError("模拟复制中断")
        real_link(source, target)

    with monkeypatch.context() as patch:
        patch.setattr(os, "link", interrupt_second_copy)
        with pytest.raises(PermissionError):
            migrate_plugin_data(plugin_dir, data_dir)

    assert legacy_dir.exists()
    assert (data_dir / "a.json").read_bytes() == b"first"
    assert not list(data_dir.glob(".migration-*"))
    backups = migrate_plugin_data(plugin_dir, data_dir)
    assert len(backups) == 1
    assert (data_dir / "b.json").read_bytes() == b"second"


def test_no_legacy_data_is_valid(tmp_path: Path) -> None:
    data_dir = tmp_path / "persistent"
    assert migrate_plugin_data(tmp_path / "plugin", data_dir) == []
    assert data_dir.is_dir()


def test_workflow_paths_follow_migration_and_preserve_custom_paths(tmp_path: Path) -> None:
    plugin_dir = tmp_path / "plugin"
    data_dir = tmp_path / "persistent"
    expected = data_dir / "workflows" / "t2i.json"
    assert resolve_workflow_path("data/workflows/t2i.json", plugin_dir, data_dir) == expected
    assert resolve_workflow_path(r"data\workflows\t2i.json", plugin_dir, data_dir) == expected
    assert resolve_workflow_path(str(plugin_dir / "data" / "workflows" / "t2i.json"), plugin_dir, data_dir) == expected
    external = tmp_path / "external" / "custom.json"
    assert resolve_workflow_path(str(external), plugin_dir, data_dir) == external
    assert resolve_workflow_path("custom.json", plugin_dir, data_dir) == plugin_dir / "custom.json"


def test_plugin_lifecycle_uses_granted_paths_and_keeps_state_on_reload(tmp_path: Path, monkeypatch: Any) -> None:
    """使用真实 SDK 注入路径，在临时目录验证加载、配置刷新及卸载。"""

    package_name = "drawpic_storage_lifecycle_test"
    plugin_source = Path(__file__).parents[1]
    package = ModuleType(package_name)
    package.__path__ = [str(plugin_source)]
    monkeypatch.setitem(sys.modules, package_name, package)
    spec = spec_from_file_location(f"{package_name}.plugin", plugin_source / "plugin.py")
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    runtime_globals = module.DrawpicPlugin.on_load.__globals__
    original_prepare = runtime_globals["prepare_workspace"]

    async def prepare_in_temporary_directory(plugin, config_path):
        del config_path
        await original_prepare(plugin, tmp_path / "plugin" / "config.toml")

    monkeypatch.setitem(runtime_globals, "prepare_workspace", prepare_in_temporary_directory)

    legacy_plugin = tmp_path / "plugin"
    (legacy_plugin / "data").mkdir(parents=True)
    (legacy_plugin / "data" / "draw_tasks.json").write_text('{"tasks": {}, "latest_task_id_by_session": {}}')
    paths = PluginPaths(data_dir=tmp_path / "persistent", runtime_dir=tmp_path / "runtime")
    loop_thread = get_ident()
    migration_threads: List[int] = []

    def migrate_in_temporary_directory(plugin_dir: Path, data_dir: Path) -> List[Path]:
        del plugin_dir
        migration_threads.append(get_ident())
        return migrate_plugin_data(legacy_plugin, data_dir)

    monkeypatch.setitem(runtime_globals, "migrate_plugin_data", migrate_in_temporary_directory)
    plugin = module.create_plugin()
    plugin._set_context(PluginContext("maimai-drawpic-plugin", paths=paths))
    plugin.set_plugin_config(plugin.get_default_config())

    async def lifecycle() -> None:
        await plugin.on_load()
        assert plugin._task_store.path == paths.data_dir / "draw_tasks.json"
        assert plugin._usage_store.path == paths.data_dir / "user_quotas.json"
        assert plugin._require_session_store().path == paths.data_dir / "session_preferences.json"
        provider = plugin._require_router().create_comfyui_provider()
        assert provider.data_dir == paths.data_dir
        assert resolve_workflow_path(provider.t2i_workflow_path, provider.plugin_dir, provider.data_dir) == (
            paths.data_dir / "workflows" / "t2i.json"
        )
        store = plugin._task_store
        await plugin.on_config_update("self", plugin.get_default_config(), "2.31.0")
        assert plugin._task_store is store
        await plugin.on_unload()

    asyncio.run(lifecycle())
    assert migration_threads and all(thread != loop_thread for thread in migration_threads)
    assert not (legacy_plugin / "data").exists()
    assert (paths.data_dir / "workflows" / "README.txt").exists()
    assert (paths.data_dir / "session_preferences.json").exists()
