"""FLEET-A · Retention / TTL-index bootstrap tests.

Confirms ``services.fleet.indexes.ensure_fleet_indexes`` registers
the expected indexes (particularly the TTL indexes) on the four
FLEET-A collections. Uses a tiny in-memory collection stub that
records ``create_indexes`` invocations verbatim.
"""
from __future__ import annotations

import asyncio
import os

import pytest

from services.fleet import indexes


class _RecordingColl:
    def __init__(self):
        self.calls = []
    async def create_indexes(self, models):
        self.calls.append(list(models))


class _RecordingDB:
    def __init__(self):
        self._colls = {}
    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return self._colls.setdefault(name, _RecordingColl())


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _all_index_names(coll):
    names = []
    for call in coll.calls:
        for model in call:
            names.append(model.document["name"])
    return names


def _index_expire_seconds(coll, name):
    for call in coll.calls:
        for model in call:
            if model.document["name"] == name:
                return model.document.get("expireAfterSeconds")
    return None


# ─── Registration ──────────────────────────────────────────────────

def test_tech_locations_ttl_index_registered():
    db = _RecordingDB()
    _run(indexes.ensure_fleet_indexes(db))
    names = _all_index_names(db.tech_locations)
    assert "tech_locations_ttl" in names
    assert "tech_locations_tenant_tech_time_bg" in names
    assert "tech_locations_tenant_time_bg" in names


def test_tech_locations_ttl_defaults_to_30_days(monkeypatch):
    monkeypatch.delenv("FLEET_BREADCRUMB_RETENTION_DAYS", raising=False)
    db = _RecordingDB()
    _run(indexes.ensure_fleet_indexes(db))
    expire = _index_expire_seconds(db.tech_locations,
                                     "tech_locations_ttl")
    assert expire == 30 * 24 * 60 * 60


def test_tech_locations_ttl_respects_env_override(monkeypatch):
    monkeypatch.setenv("FLEET_BREADCRUMB_RETENTION_DAYS", "7")
    db = _RecordingDB()
    _run(indexes.ensure_fleet_indexes(db))
    expire = _index_expire_seconds(db.tech_locations,
                                     "tech_locations_ttl")
    assert expire == 7 * 24 * 60 * 60


def test_tech_locations_ttl_env_invalid_falls_back_to_30(monkeypatch):
    monkeypatch.setenv("FLEET_BREADCRUMB_RETENTION_DAYS", "banana")
    db = _RecordingDB()
    _run(indexes.ensure_fleet_indexes(db))
    expire = _index_expire_seconds(db.tech_locations,
                                     "tech_locations_ttl")
    assert expire == 30 * 24 * 60 * 60


def test_membership_unique_index_registered():
    db = _RecordingDB()
    _run(indexes.ensure_fleet_indexes(db))
    names = _all_index_names(db.fleet_membership)
    assert "fleet_membership_unique" in names
    # Confirm the model was declared unique=True.
    for call in db.fleet_membership.calls:
        for model in call:
            if model.document["name"] == "fleet_membership_unique":
                assert model.document.get("unique") is True


def test_eta_snapshots_indexes_registered_with_ttl():
    db = _RecordingDB()
    _run(indexes.ensure_fleet_indexes(db))
    names = _all_index_names(db.fleet_eta_snapshots)
    assert "fleet_eta_snapshots_ttl" in names
    assert _index_expire_seconds(db.fleet_eta_snapshots,
                                    "fleet_eta_snapshots_ttl") == 24 * 60 * 60


def test_notification_dedup_indexes_registered_with_ttl():
    db = _RecordingDB()
    _run(indexes.ensure_fleet_indexes(db))
    names = _all_index_names(db.fleet_notification_dedup)
    assert "fleet_notif_dedup_lookup_bg" in names
    assert "fleet_notif_dedup_ttl" in names
    # TTL must be > 4 h dedup window; 24 h is the module default.
    ttl = _index_expire_seconds(db.fleet_notification_dedup,
                                  "fleet_notif_dedup_ttl")
    assert ttl == 24 * 60 * 60


def test_ensure_fleet_indexes_is_idempotent():
    """Calling ``ensure_fleet_indexes`` twice must not double-register
    or raise. PyMongo's create_indexes is itself idempotent — but we
    still ensure the helper doesn't blow up on repeated invocations."""
    db = _RecordingDB()
    _run(indexes.ensure_fleet_indexes(db))
    _run(indexes.ensure_fleet_indexes(db))
    names = _all_index_names(db.tech_locations)
    # Each call adds another batch — module doesn't dedup itself; the
    # driver does. We only need to prove the second call ran cleanly.
    assert names.count("tech_locations_ttl") == 2


def test_retention_days_reader_returns_int():
    """``_retention_days`` should always coerce to an int and never
    raise on missing env."""
    assert isinstance(indexes._retention_days(), int)
