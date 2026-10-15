"""额度写入回滚与周期绑定结算；仅使用临时文件和本地 mock。"""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from importlib import import_module
from types import SimpleNamespace
from unittest.mock import Mock
import json

import pytest

from test_workspace import _PACKAGE


quota_storage = import_module(f"{_PACKAGE}.src.maimai_drawpic.infrastructure.storage.quotas")
QuotaMixin = import_module(f"{_PACKAGE}.src.maimai_drawpic.application.quotas").QuotaMixin
UserQuotaStore = quota_storage.UserQuotaStore


def make_store(tmp_path):
    return UserQuotaStore(tmp_path / "quotas.json")


def reserve(store, *, key="user", period="daily", quota=5):
    token, _ = store.reserve(key, period=period, default_quota=quota)
    assert token is not None
    return token


def snapshot(store):
    return {key: asdict(record) for key, record in store.records.items()}


def fail_save():
    raise OSError("simulated quota storage failure")


@pytest.mark.parametrize(
    "operation",
    ["consume", "refund", "reserve", "add", "remove", "set", "refund_reservation", "commit_reservation"],
)
def test_quota_mutation_write_failure_preserves_memory_and_disk(tmp_path, monkeypatch, operation):
    store = make_store(tmp_path)
    token = reserve(store)
    assert store.consume("user", period="daily", default_quota=5) == (True, 3)
    previous_records = store.records
    previous_record = store.records["user"]
    before = snapshot(store)
    original_bytes = store.path.read_bytes()

    def mutate():
        if operation in {"add", "remove", "set"}:
            return store.adjust_remaining("user", action=operation, count=2, period="daily", default_quota=5)
        if operation in {"refund_reservation", "commit_reservation"}:
            return getattr(store, operation)(token)
        return getattr(store, operation)("user", period="daily", default_quota=5)

    with monkeypatch.context() as broken:
        broken.setattr(store, "save", fail_save)
        with pytest.raises(OSError, match="simulated quota storage failure"):
            mutate()

    assert store.records is previous_records
    assert store.records["user"] is previous_record
    assert snapshot(store) == before
    assert store.path.read_bytes() == original_bytes
    assert token.reservation_id in store.records["user"].reservation_ids

    mutate()
    assert asdict(previous_record) == before["user"]
    reloaded = make_store(tmp_path)
    reloaded.load()
    assert snapshot(reloaded) == snapshot(store)


@pytest.mark.parametrize("operation", ["consume", "refund", "reserve", "adjust_remaining"])
def test_first_quota_write_failure_does_not_create_phantom_record(tmp_path, monkeypatch, operation):
    store = make_store(tmp_path)
    monkeypatch.setattr(store, "save", fail_save)
    kwargs = {"action": "add", "count": 1} if operation == "adjust_remaining" else {}
    with pytest.raises(OSError):
        getattr(store, operation)("user", period="daily", default_quota=5, **kwargs)
    assert store.records == {}
    assert not store.path.exists()


def test_period_rollover_write_failure_preserves_previous_period(tmp_path, monkeypatch):
    store = make_store(tmp_path)
    period = ["2026-10-15"]
    monkeypatch.setattr(store, "_period_key", lambda _: period[0])
    old_token = reserve(store)
    before = snapshot(store)
    original_bytes = store.path.read_bytes()
    period[0] = "2026-10-16"
    with monkeypatch.context() as broken:
        broken.setattr(store, "save", fail_save)
        with pytest.raises(OSError):
            reserve(store)
    assert snapshot(store) == before
    assert store.path.read_bytes() == original_bytes
    assert old_token.reservation_id in store.records["user"].reservation_ids


@pytest.mark.parametrize(
    "period,old_key,new_key",
    [
        ("daily", "2026-10-15", "2026-10-16"),
        ("weekly", "2026-W42", "2026-W43"),
        ("monthly", "2026-10", "2026-11"),
    ],
)
def test_old_reservation_cannot_refund_new_period(tmp_path, monkeypatch, period, old_key, new_key):
    store = make_store(tmp_path)
    clock = [old_key]
    monkeypatch.setattr(store, "_period_key", lambda _: clock[0])
    old_token = reserve(store, period=period, quota=1)
    assert old_token.period_key == old_key
    clock[0] = new_key
    new_token = reserve(store, period=period, quota=1)
    before = snapshot(store)
    original_bytes = store.path.read_bytes()
    with monkeypatch.context() as broken:
        broken.setattr(store, "save", fail_save)
        assert store.refund_reservation(old_token) == 0
        assert store.commit_reservation(old_token) == 0
    assert snapshot(store) == before
    assert store.path.read_bytes() == original_bytes
    assert store.get_remaining("user", period=period, default_quota=1) == 0
    assert store.reserve("user", period=period, default_quota=1) == (None, 0)
    assert store.refund_reservation(new_token) == 1


def test_refund_is_idempotent_after_reload_and_another_consumption(tmp_path):
    store = make_store(tmp_path)
    old_token = reserve(store, quota=2)
    other_token = reserve(store, quota=2)
    store.refund_reservation(old_token)
    store = make_store(tmp_path)
    store.load()
    new_token = reserve(store, quota=2)
    before = snapshot(store)
    assert store.refund_reservation(old_token) == 0
    assert snapshot(store) == before
    assert set(store.records["user"].reservation_ids) == {other_token.reservation_id, new_token.reservation_id}


def test_refund_write_failure_can_retry_same_token_once(tmp_path, monkeypatch):
    store = make_store(tmp_path)
    token = reserve(store, quota=2)
    other_token = reserve(store, quota=2)
    with monkeypatch.context() as broken:
        broken.setattr(store, "save", fail_save)
        with pytest.raises(OSError):
            store.refund_reservation(token)
    assert store.refund_reservation(token) == 1
    assert store.refund_reservation(token) == 1
    assert store.records["user"].reservation_ids == [other_token.reservation_id]


def test_successful_commit_keeps_charge_and_prevents_late_refund(tmp_path):
    store = make_store(tmp_path)
    token = reserve(store, quota=1)
    assert store.commit_reservation(token) == 0
    assert store.records["user"].reservation_ids == []
    store = make_store(tmp_path)
    store.load()
    assert store.commit_reservation(token) == 0
    assert store.refund_reservation(token) == 0
    assert store.get_remaining("user", period="daily", default_quota=1) == 0


def test_reservations_are_atomic_and_duplicate_refunds_are_serialized(tmp_path):
    store = make_store(tmp_path)
    with ThreadPoolExecutor(max_workers=8) as workers:
        attempts = list(workers.map(lambda _: store.reserve("user", period="daily", default_quota=2), range(12)))
    tokens = [token for token, _ in attempts if token is not None]
    assert len(tokens) == 2
    with ThreadPoolExecutor(max_workers=8) as workers:
        remaining = list(workers.map(lambda _: store.refund_reservation(tokens[0]), range(12)))
    assert remaining == [1] * 12
    assert store.records["user"].reservation_ids == [tokens[1].reservation_id]
    assert store.refund_reservation(tokens[1]) == 2


def test_legacy_records_load_and_legacy_refund_cannot_release_live_reservation(tmp_path):
    store = make_store(tmp_path)
    store.path.write_text(json.dumps({"user": {"period_key": "once", "used": 1, "quota_override": 3}}))
    store.load()
    assert store.get_remaining("user", period="once", default_quota=1) == 2
    token = reserve(store, period="once", quota=1)
    assert store.refund("user", period="once", default_quota=1) == 2
    assert store.refund("user", period="once", default_quota=1) == 2
    assert store.records["user"].reservation_ids == [token.reservation_id]
    assert store.refund_reservation(token) == 3


def make_quota_plugin(tmp_path, *, enabled=True, admin=False):
    plugin = QuotaMixin()
    plugin._usage_store = make_store(tmp_path)
    plugin.ctx = SimpleNamespace(logger=Mock())
    plugin._is_admin = lambda _: admin
    plugin.config = SimpleNamespace(
        general=SimpleNamespace(
            group_quota_enabled=enabled, group_quota_period="daily", group_default_quota=1,
            private_quota_enabled=enabled, private_quota_period="daily", private_default_quota=1,
        )
    )
    return plugin


@pytest.mark.parametrize("enabled,admin", [(False, False), (True, True)])
def test_disabled_or_admin_quota_has_no_reservation(tmp_path, enabled, admin):
    plugin = make_quota_plugin(tmp_path, enabled=enabled, admin=admin)
    allowed, _, token = plugin._reserve_draw_quota("12345", "10000", "stream", return_reservation=True)
    assert allowed is True
    assert token is None
    plugin._commit_draw_quota(token)
    assert plugin._usage_store.records == {}
    assert not plugin._usage_store.path.exists()


def test_application_refund_uses_captured_quota_config(tmp_path):
    plugin = make_quota_plugin(tmp_path)
    allowed, _, token = plugin._reserve_draw_quota("12345", "10000", "stream", return_reservation=True)
    assert allowed is True
    assert isinstance(token, quota_storage.QuotaReservation)
    assert (token.quota_key, token.period, token.default_quota) == ("qq:group:10000", "daily", 1)
    assert plugin._reserve_draw_quota("12345", "10000", "stream", return_reservation=True)[2] is None
    plugin.config.general.group_quota_period = "monthly"
    plugin.config.general.group_default_quota = 99
    plugin.config.general.group_quota_enabled = False
    plugin._refund_draw_quota(token.quota_key, "10000", "stream", reservation=token)
    plugin._refund_draw_quota(token.quota_key, "10000", "stream", reservation=token)
    assert plugin._usage_store.records[token.quota_key].period_key == token.period_key
    assert plugin._usage_store.records[token.quota_key].used == 0
    assert plugin._usage_store.get_remaining(token.quota_key, period="daily", default_quota=1) == 1


def test_returning_to_previous_period_type_cannot_revive_old_token(tmp_path, monkeypatch):
    store = make_store(tmp_path)
    monkeypatch.setattr(store, "_period_key", lambda period: "2026-10-15" if period == "daily" else "2026-W42")
    old_token = reserve(store, period="daily", quota=1)
    reserve(store, period="weekly", quota=1)
    new_token = reserve(store, period="daily", quota=1)
    assert new_token.period_key == old_token.period_key
    assert new_token.reservation_id != old_token.reservation_id
    assert store.refund_reservation(old_token) == 0
    assert store.records["user"].reservation_ids == [new_token.reservation_id]


def test_application_rejects_reservation_for_different_quota_key(tmp_path):
    plugin = make_quota_plugin(tmp_path)
    _, _, token = plugin._reserve_draw_quota("12345", "10000", "stream", return_reservation=True)
    before = snapshot(plugin._usage_store)
    with pytest.raises(ValueError, match="归属"):
        plugin._refund_draw_quota("qq:group:20000", "20000", "stream", reservation=token)
    assert snapshot(plugin._usage_store) == before
    assert plugin._usage_store.refund_reservation(replace(token, quota_key="qq:group:20000")) == 1
    assert snapshot(plugin._usage_store) == before


def test_application_commit_removes_token_without_refunding(tmp_path):
    plugin = make_quota_plugin(tmp_path)
    _, _, token = plugin._reserve_draw_quota("12345", "10000", "stream", return_reservation=True)
    plugin._commit_draw_quota(token)
    plugin._refund_draw_quota(token.quota_key, "10000", "stream", reservation=token)
    assert plugin._usage_store.records[token.quota_key].used == 1
    assert plugin._usage_store.records[token.quota_key].reservation_ids == []
