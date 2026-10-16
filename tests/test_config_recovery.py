"""已知误生成模板的恢复，以及用户配置、损坏文件和事务的保护。"""

from copy import deepcopy
from importlib import import_module
from pathlib import Path
import json
import pytest
import tomlkit

from test_config_transactions import assert_renamed, new_store, pending_transaction, snapshot_bytes
from test_workspace import _PACKAGE, storage

recovery = import_module(f"{_PACKAGE}.src.maimai_drawpic.infrastructure.storage.config_recovery")


def write_reseeded(store, version="2.38.0"):
    fixture = Path(__file__).parent / "fixtures" / f"reseeded-defaults-{version}.toml"
    document = tomlkit.parse(fixture.read_text(encoding="utf-8"))
    document["plugin"]["image_cache_max_mb"] = 321
    document["proxy"].update(enabled=True, username="fixture-proxy-user", password="fixture-proxy-password")
    original = tomlkit.dumps(document).replace("\n", "\r\n").encode("utf-8")
    store.config_path.write_bytes(original)
    return original


def saved_workspace(tmp_path):
    store = new_store(tmp_path)
    store.save_provider(
        {"kind": "openai", "name": "Saved", "config": {"api_key": "fixture-saved-key", "models": ["image-a"]}},
        store.revision,
    )
    values = deepcopy(store.settings.values)
    values["general"].update(default_model="Saved/image-a", request_retry_count=2)
    values["style"]["default_style"] = "fixture-saved-style"
    store.save_common(values, values, store.revision)
    return store


@pytest.mark.parametrize("version", ["2.37.0", "2.38.0"])
def test_known_generated_defaults_recover_without_changing_json(tmp_path, version):
    store = saved_workspace(tmp_path)
    original = write_reseeded(store, version)
    before = snapshot_bytes(store)
    restarted = storage.WorkspaceConfigStore(store.path.parent, store.config_path)
    backup = restarted.initialize(tomlkit.parse(original.decode("utf-8")))
    assert backup is not None and backup.read_bytes() == original
    assert snapshot_bytes(store) == before
    document = tomlkit.parse(store.config_path.read_text(encoding="utf-8"))
    assert set(document) == {"plugin", "proxy"}
    assert document["plugin"]["image_cache_max_mb"] == 321
    assert document["proxy"]["password"] == "fixture-proxy-password"
    assert restarted.settings.values == store.settings.values
    assert restarted.providers == store.providers
    assert restarted.revision == store.revision
    backups = set(backup.parent.iterdir())
    assert restarted.initialize(document) is None
    assert set(backup.parent.iterdir()) == backups


@pytest.mark.parametrize("change", ["general", "style", "key", "unknown", "partial", "version", "type"])
def test_actual_edits_and_unknown_templates_remain_conflicts(tmp_path, change):
    store = saved_workspace(tmp_path)
    document = tomlkit.parse(write_reseeded(store).decode("utf-8"))
    if change == "general":
        document["general"]["request_retry_count"] = 3
    elif change == "style":
        document["style"]["default_style"] = "fixture-toml-style"
    elif change == "key":
        document["openai"]["api_key"] = "fixture-user-edited-key"
    elif change == "unknown":
        document["general"]["unrecognized"] = "fixture-user-data"
    elif change == "partial":
        del document["agnes"]
    elif change == "version":
        document["plugin"]["config_version"] = "2.39.0"
    else:
        document["general"]["request_retry_count"] = True
    original = tomlkit.dumps(document).encode("utf-8")
    store.config_path.write_bytes(original)
    before = snapshot_bytes(store)
    with pytest.raises(ValueError, match="冲突"):
        storage.WorkspaceConfigStore(store.path.parent, store.config_path).initialize(document)
    assert store.config_path.read_bytes() == original
    assert snapshot_bytes(store) == before
    assert not (store.path.parent / "migration_backups").exists()


@pytest.mark.parametrize("target", ["platforms", "settings"])
def test_invalid_json_prevents_any_template_cleanup(tmp_path, target):
    store = saved_workspace(tmp_path)
    original = write_reseeded(store)
    damaged = store.path if target == "platforms" else store.settings.path
    damaged.write_bytes(b'{"unrecognized":"fixture-preserve-me"}')
    before = snapshot_bytes(store)
    with pytest.raises(ValueError):
        storage.WorkspaceConfigStore(store.path.parent, store.config_path).initialize({})
    assert store.config_path.read_bytes() == original
    assert snapshot_bytes(store) == before
    assert not (store.path.parent / "migration_backups").exists()


def test_missing_platform_file_does_not_override_existing_settings(tmp_path):
    store = saved_workspace(tmp_path)
    original = write_reseeded(store)
    store.path.unlink()
    before = snapshot_bytes(store)
    with pytest.raises(ValueError, match="冲突"):
        storage.WorkspaceConfigStore(store.path.parent, store.config_path).initialize({})
    assert store.config_path.read_bytes() == original
    assert snapshot_bytes(store) == before
    assert not (store.path.parent / "migration_backups").exists()


@pytest.mark.parametrize("stage", ["backup", "replace"])
def test_failed_recovery_keeps_original_and_can_be_retried(tmp_path, monkeypatch, stage):
    store = saved_workspace(tmp_path)
    original = write_reseeded(store)
    before = snapshot_bytes(store)

    def fail(*args, **kwargs):
        raise OSError("fixture recovery IO failure")

    with monkeypatch.context() as patch:
        if stage == "backup":
            patch.setattr(recovery.shutil, "copy2", fail)
        else:
            patch.setattr(recovery, "write_text_atomically", fail)
        with pytest.raises(OSError):
            storage.WorkspaceConfigStore(store.path.parent, store.config_path).initialize({})
    assert store.config_path.read_bytes() == original
    assert snapshot_bytes(store) == before
    backup = storage.WorkspaceConfigStore(store.path.parent, store.config_path).initialize({})
    assert backup is not None and backup.read_bytes() == original


def test_valid_committed_transaction_recovers_before_template_cleanup(tmp_path, monkeypatch):
    store = pending_transaction(tmp_path, monkeypatch)
    original = write_reseeded(store)
    restarted = storage.WorkspaceConfigStore(store.path.parent, store.config_path)
    backup = restarted.initialize({})
    assert backup is not None and backup.read_bytes() == original
    assert_renamed(restarted, store.revision)
    assert not store.transaction_path.exists()


@pytest.mark.parametrize("damage", ["journal", "external_change"])
def test_bad_transaction_or_external_change_blocks_cleanup(tmp_path, monkeypatch, damage):
    store = pending_transaction(tmp_path, monkeypatch)
    original = write_reseeded(store)
    if damage == "journal":
        store.transaction_path.write_bytes(b"{")
    else:
        payload = json.loads(store.settings.path.read_text(encoding="utf-8"))
        payload["settings"]["general"]["request_retry_count"] = 4
        store.settings.path.write_text(json.dumps(payload), encoding="utf-8")
    before = snapshot_bytes(store)
    with pytest.raises(ValueError):
        storage.WorkspaceConfigStore(store.path.parent, store.config_path).initialize({})
    assert store.config_path.read_bytes() == original
    assert snapshot_bytes(store) == before
    assert not (store.path.parent / "migration_backups").exists()
