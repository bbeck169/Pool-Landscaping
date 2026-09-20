"""Phase I1.5.d · Feb-2026 — Migration script contract lock.

Tests the ``scripts.i15d_theme_migration`` module directly against
the live Mongo instance (same dependency posture as
``test_i15a_tenant_theme_endpoint.py`` — imports the shared
``config.db`` and hits real collections).

Contract:
  1. Tenant with no ``theme`` field → migrated to expanded
     default preset + ``theme_preset="default"`` + timestamp.
  2. Tenant with existing ``theme`` (partial or full) → left
     untouched (operator work is authoritative).
  3. Second run is idempotent — zero new migrations.
  4. Audit doc lands in ``migration_runs`` with the expected
     shape.
  5. ``--dry-run`` reports migrations without mutating tenants.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient
from tests._shared_mongo import (
    shared_client as _shared_client,
    shared_db as _shared_db,
)


load_dotenv(Path(__file__).resolve().parents[1] / ".env")

_sync = _shared_db()
# ── Import target under test ─────────────────────────────────────
# Late import so the .env is loaded before ``config.db`` binds.
from scripts.i15d_theme_migration import _run as _migration_run  # noqa: E402
from services.theme.presets import get_preset  # noqa: E402
from services.theme.validate import validate_theme_payload  # noqa: E402


def _drive(coro_factory):
    """Run an async coroutine with a fresh motor client bound to
    this event loop.

    Motor clients cache their event loop at construction time; the
    process-wide ``config.db`` was bound to the FastAPI event loop
    at import time, so calling it from ``asyncio.run`` here trips
    "attached to a different loop". Building a per-loop client
    inside a single ``asyncio.run`` block sidesteps that.
    """
    async def _wrap():
        client = AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = client[os.environ["DB_NAME"]]
        try:
            return await coro_factory(db)
        finally:
            client.close()
    return asyncio.run(_wrap())


# ── Fixtures ─────────────────────────────────────────────────────
@pytest.fixture
def temp_tenants():
    """Seed a couple of throwaway tenants and yield their ids.

    Cleans up itself + any audit rows the migration wrote in the
    finalizer so re-running the suite doesn't accumulate drift.
    """
    unset_id = f"i15d-test-unset-{uuid.uuid4().hex}"
    preset_id = f"i15d-test-preset-{uuid.uuid4().hex}"
    now = datetime.now(timezone.utc).isoformat()
    _sync.tenants.insert_many([
        {"id": unset_id, "name": "I1.5.d unset tenant", "created_at": now},
        {"id": preset_id, "name": "I1.5.d preset tenant",
          "created_at": now,
          "theme": {**get_preset("salon"), "preset": "salon"}},
    ])
    yield {"unset": unset_id, "preset": preset_id}
    _sync.tenants.delete_many({"id": {"$in": [unset_id, preset_id]}})
    _sync.migration_runs.delete_many({
        "script": "i15d_theme_migration",
        "migrated_tenant_ids": {"$in": [unset_id]},
    })


# ── Tests ────────────────────────────────────────────────────────
def test_i15d_migration_migrates_only_unset_tenants(temp_tenants):
    """Unset tenant gets the default preset; preset tenant is
    untouched."""
    report = _drive(lambda db: _migration_run(
        dry_run=False, write_audit=True, db=db))
    assert report["errors"] == [], report["errors"]
    unset = _sync.tenants.find_one({"id": temp_tenants["unset"]})
    preset = _sync.tenants.find_one({"id": temp_tenants["preset"]})

    # ── Unset tenant should now carry the default preset.
    assert unset is not None
    assert isinstance(unset.get("theme"), dict)
    assert unset["theme"]["preset"] == "default"
    assert unset.get("theme_preset") == "default"
    assert isinstance(unset.get("theme_migrated_at"), str)
    assert unset.get("theme_migrated_by") == "i15d_theme_migration"
    # ── The migrated theme must round-trip through the validator.
    validate_theme_payload(unset["theme"])

    # ── Preset tenant unchanged (still salon).
    assert preset["theme"]["preset"] == "salon"
    assert preset.get("theme_migrated_at") is None


def test_i15d_migration_is_idempotent(temp_tenants):
    """Running the migration twice touches zero new tenants on
    the second pass."""
    _ = _drive(lambda db: _migration_run(
        dry_run=False, write_audit=True, db=db))
    r2 = _drive(lambda db: _migration_run(
        dry_run=False, write_audit=True, db=db))
    # Second pass must not report our unset tenant again.
    assert temp_tenants["unset"] not in r2["migrated_tenant_ids"]
    unset = _sync.tenants.find_one({"id": temp_tenants["unset"]})
    assert unset["theme"]["preset"] == "default"


def test_i15d_migration_writes_audit_doc(temp_tenants):
    """A ``migration_runs`` audit doc is appended per run with the
    expected shape."""
    report = _drive(lambda db: _migration_run(
        dry_run=False, write_audit=True, db=db))
    audit = _sync.migration_runs.find_one({"run_id": report["run_id"]})
    assert audit is not None, "audit doc not persisted"
    for key in ("run_id", "script", "started_at", "finished_at",
                 "tenants_scanned", "tenants_migrated",
                 "tenants_skipped_had_theme", "migrated_tenant_ids",
                 "errors", "dry_run"):
        assert key in audit, key
    assert audit["script"] == "i15d_theme_migration"
    assert audit["dry_run"] is False
    assert audit["tenants_scanned"] >= 2  # at least our two fixtures


def test_i15d_migration_dry_run_does_not_mutate(temp_tenants):
    """``dry_run=True`` reports migrations but writes zero mutations
    to the tenants collection."""
    before = _sync.tenants.find_one({"id": temp_tenants["unset"]})
    assert before.get("theme") in (None, {})
    report = _drive(lambda db: _migration_run(
        dry_run=True, write_audit=True, db=db))
    assert report["dry_run"] is True
    assert temp_tenants["unset"] in report["migrated_tenant_ids"]
    after = _sync.tenants.find_one({"id": temp_tenants["unset"]})
    # Tenant document must NOT have been touched.
    assert after.get("theme") in (None, {})
    assert after.get("theme_migrated_at") is None
    # But an audit doc must still be recorded (dry_run=True flag).
    audit = _sync.migration_runs.find_one({"run_id": report["run_id"]})
    assert audit is not None
    assert audit["dry_run"] is True
