"""旧配置中断恢复和持久状态完整性；所有数据都在临时目录。"""

from concurrent.futures import ThreadPoolExecutor
from importlib import import_module
from threading import Event
import asyncio
import json
import logging
import pytest
import tomlkit

from test_workspace import _PACKAGE, make_plugin as make_plugin, storage

preferences = import_module(f"{_PACKAGE}.src.maimai_drawpic.infrastructure.storage.preferences")
quotas = import_module(f"{_PACKAGE}.src.maimai_drawpic.infrastructure.storage.quotas")


LEGACY = '''[plugin]
config_version = "2.20.0"
[general]
default_model = "fixture-image"
fallback_model = "fixture-backup"
quota_enabled = false
quota_period = "weekly"
default_quota = 13
[openai]
api_key = "fixture-openai-key"
models = ["fixture-image", "fixture-backup"]
[volcengine]
api_key = "fixture-volcengine-key"
unified_models = ["fixture-unified-image"]
t2i_models = ["fixture-t2i-image"]
i2i_models = ["fixture-i2i-image"]
[prompt_review]
enabled = true
review_prompt = "fixture-original-review"
'''


def normalized_legacy():
    values = storage.migrate_legacy_review_config(tomlkit.parse(LEGACY))
    return storage.DrawpicConfig.model_validate(values).model_dump(mode="json")


def test_old_platform_fields_resume_after_toml_write_failure(tmp_path, monkeypatch):
    path = tmp_path / "config.toml"
    original = LEGACY.replace("\n", "\r\n").encode("utf-8")
    path.write_bytes(original)
    store = storage.WorkspaceConfigStore(tmp_path / "data", path)

    def fail(*args):
        raise OSError("fixture interrupted TOML write")

    with monkeypatch.context() as patch:
        patch.setattr(storage, "write_text_atomically", fail)
        with pytest.raises(OSError):
            store.initialize(normalized_legacy())
    assert path.read_bytes() == original
    restarted = storage.WorkspaceConfigStore(store.path.parent, path)
    restarted.initialize(normalized_legacy())
    volcengine = next(record for record in restarted.providers if record["kind"] == "volcengine")
    assert volcengine["config"]["models"] == ["fixture-unified-image", "fixture-t2i-image", "fixture-i2i-image"]
    general = restarted.settings.values["general"]
    assert general["fallback_models"] == ["OpenAI_Compatible/fixture-backup"]
    assert general["group_quota_enabled"] is False
    assert general["private_quota_period"] == "weekly"
    assert general["group_default_quota"] == 13
    assert general["prompt_review_prompt"] == "fixture-original-review"
    assert set(tomlkit.parse(path.read_text(encoding="utf-8"))) == {"plugin"}
    assert any(p.read_bytes() == original for p in (store.path.parent / "migration_backups").glob("*.toml"))


def test_external_toml_change_is_not_removed_during_migration(tmp_path, monkeypatch):
    path = tmp_path / "config.toml"
    path.write_text(LEGACY, encoding="utf-8")
    store = storage.WorkspaceConfigStore(tmp_path / "data", path)
    original_save = store._save
    changed = LEGACY.replace("fixture-openai-key", "fixture-externally-edited-key").encode("utf-8")

    def save(*args, **kwargs):
        original_save(*args, **kwargs)
        path.write_bytes(changed)

    monkeypatch.setattr(store, "_save", save)
    with pytest.raises(ValueError, match="外部修改"):
        store.initialize(normalized_legacy())
    assert path.read_bytes() == changed


class UnavailableRouter:
    def get_model_provider(self, model):
        return "openai" if model == "new-image" else ""

    def resolve_model_name(self, model, allow_unknown_model=False):
        if model != "new-image":
            raise ValueError("fixture model unavailable")
        return model


def test_unavailable_session_model_is_preserved_and_can_be_replaced(tmp_path):
    path = tmp_path / "preferences.json"
    path.write_text(json.dumps({"qq:group:1": {"model": "old-image"}}), encoding="utf-8")
    store = preferences.SessionPreferenceStore(path, UnavailableRouter(), logging.getLogger("upgrade-test"))
    store.load()
    assert store.preferences["qq:group:1"]["model"] == "old-image"
    store.save()
    assert json.loads(path.read_text(encoding="utf-8"))["qq:group:1"]["model"] == "old-image"
    assert store.set_preference("stream", group_id="1", model="new-image")["model"] == "new-image"


def test_preference_write_failure_keeps_memory_and_file_unchanged(tmp_path, monkeypatch):
    path = tmp_path / "session_preferences.json"
    store = preferences.SessionPreferenceStore(path, UnavailableRouter(), logging.getLogger("upgrade-test"))
    store.set_preference("stream", group_id="1", model="new-image")
    before, original = json.loads(json.dumps(store.preferences)), path.read_bytes()

    def fail(*args):
        raise OSError("fixture disk write failure")

    monkeypatch.setattr(preferences, "write_json_atomically", fail)
    with pytest.raises(OSError):
        store.set_preference("stream", group_id="1", novelai_artist_tags="unsaved tags")
    assert store.preferences == before
    assert path.read_bytes() == original


def test_concurrent_preference_updates_preserve_every_session(tmp_path):
    path = tmp_path / "session_preferences.json"
    store = preferences.SessionPreferenceStore(path, UnavailableRouter(), logging.getLogger("upgrade-test"))
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = [pool.submit(store.set_preference, f"stream-{index}", model="new-image") for index in range(30)]
        for future in futures:
            assert future.result()["model"] == "new-image"
    reloaded = preferences.SessionPreferenceStore(path, UnavailableRouter(), logging.getLogger("upgrade-test"))
    reloaded.load()
    assert len(reloaded.preferences) == 30 and reloaded.preferences == store.preferences


def test_preference_reads_keep_committed_snapshot_during_slow_write(tmp_path, monkeypatch):
    path = tmp_path / "session_preferences.json"
    store = preferences.SessionPreferenceStore(path, UnavailableRouter(), logging.getLogger("upgrade-test"))
    store.set_preference("stream", model="new-image")
    entered, release = Event(), Event()
    original = preferences.write_json_atomically

    def slow_write(*args):
        entered.set()
        assert release.wait(5)
        original(*args)

    monkeypatch.setattr(preferences, "write_json_atomically", slow_write)
    with ThreadPoolExecutor(max_workers=2) as pool:
        pending = pool.submit(store.set_preference, "stream", novelai_artist_tags="new tags")
        try:
            assert entered.wait(5)
            reading = pool.submit(store.get_preference, "stream")
            assert reading.result(timeout=1)["novelai_artist_tags"] == ""
        finally:
            release.set()
        assert pending.result()["novelai_artist_tags"] == "new tags"


@pytest.mark.parametrize("kind", ["preferences", "quotas"])
@pytest.mark.parametrize("content", [b"{", b"[]", b'{"qq:user:1":123}'])
def test_bad_persistent_state_is_not_replaced_with_empty_state(tmp_path, kind, content):
    path = tmp_path / f"{kind}.json"
    path.write_bytes(content)
    store = (
        preferences.SessionPreferenceStore(path, UnavailableRouter(), logging.getLogger("upgrade-test"))
        if kind == "preferences" else quotas.UserQuotaStore(path)
    )
    with pytest.raises(ValueError):
        store.load()
    with pytest.raises(ValueError):
        store.save()
    assert path.read_bytes() == content
    # 修复原文件后，同一个对象可以完整重读，再正常保存。
    path.write_bytes(b"{}")
    store.load()
    store.save()
    assert json.loads(path.read_text(encoding="utf-8")) == {}


@pytest.mark.parametrize("payload", [{"used": 4}, {"period_key": "once", "used": True}])
def test_quota_records_do_not_lose_usage_on_invalid_fields(tmp_path, payload):
    path = tmp_path / "quotas.json"
    original = json.dumps({"qq:user:1": payload}).encode("utf-8")
    path.write_bytes(original)
    store = quotas.UserQuotaStore(path)
    with pytest.raises(ValueError):
        store.load()
    with pytest.raises(ValueError):
        store.consume("qq:user:1", period="once", default_quota=13)
    assert path.read_bytes() == original


def test_failed_startup_cleans_resources_without_saving_unread_state(make_plugin):
    async def run():
        plugin = make_plugin()
        data = plugin.ctx.paths.data_dir
        data.mkdir(exist_ok=True)
        bad = data / "user_quotas.json"
        original = b'{"qq:user:1":'
        bad.write_bytes(original)
        try:
            with pytest.raises(ValueError):
                await plugin.on_load()
            assert plugin._closing
            assert plugin._workspace_cleanup_task is None
            assert plugin._redactor not in plugin.ctx.logger.filters
            assert bad.read_bytes() == original
        finally:
            if plugin._draw_service is not None:
                await import_module(f"{_PACKAGE}.src.maimai_drawpic.application.workspace.lifecycle").close_workspace(plugin)
            plugin.ctx.logger.removeFilter(plugin._redactor)

    asyncio.run(run())


@pytest.mark.parametrize("stage", ["migration", "log_constructor", "task_metadata"])
def test_cancelled_startup_waits_for_owned_io(make_plugin, monkeypatch, stage):
    async def run():
        plugin = make_plugin()
        entered, release = Event(), Event()
        lifecycle = import_module(f"{_PACKAGE}.src.maimai_drawpic.application.workspace.lifecycle")
        owner, name = {
            "migration": (storage.WorkspaceConfigStore, "initialize"),
            "log_constructor": (lifecycle, "WorkspaceLogStore"),
            "task_metadata": (lifecycle.WorkspaceTaskService, "initialize"),
        }[stage]
        original = getattr(owner, name)
        handlers_before = set(plugin.ctx.logger.handlers)

        def blocked(*args, **kwargs):
            entered.set()
            assert release.wait(5)
            return original(*args, **kwargs)

        monkeypatch.setattr(owner, name, blocked)
        loading = asyncio.create_task(plugin.on_load())
        try:
            assert await asyncio.to_thread(entered.wait, 5)
            loading.cancel()
            await asyncio.sleep(0.02)
            assert not loading.done(), "不能在迁移线程仍写入时结束加载并允许回滚"
            loading.cancel()
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await loading
            assert plugin._redactor not in plugin.ctx.logger.filters
            assert set(plugin.ctx.logger.handlers) == handlers_before
        finally:
            release.set()
            await asyncio.gather(loading, return_exceptions=True)

    asyncio.run(run())
