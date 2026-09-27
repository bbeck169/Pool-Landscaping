"""AIHUB-A · Feb-2026 — migration idempotency + backfill tests.

Locks the ``scripts/migrate_ai_hub_18_employees.run`` contract:

1. Fresh tenant → every registry row inserted, all 18 counted.
2. Second run → 0 inserts, 0 patches (idempotent).
3. Existing tenant customisations (custom ``name`` /
   ``system_prompt`` / ``avatar_url``) preserved verbatim.
4. Missing new fields (``authorized_for_public_use``,
   ``action_limit_monthly``, ``codename``, ``human_name``,
   ``org_department`` …) get patched on rows that pre-date
   AIHUB-A.
5. ``run_if_env_enabled`` no-ops when ``AI_HUB_AUTO_MIGRATE`` is
   unset or any value other than ``"true"``.

Motor is faked via ``MagicMock`` + ``AsyncMock`` — no live DB.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest


class _AsyncCursor:
    def __init__(self, rows):
        self._rows = rows
        self._i = 0
    def __aiter__(self):
        return self
    async def __anext__(self):
        if self._i >= len(self._rows):
            raise StopAsyncIteration
        row = self._rows[self._i]
        self._i += 1
        return row


def _make_fake_db(*, tenants, existing_employees=None):
    """Fake Mongo shape used by the migration.  ``existing_employees``
    is a dict keyed by (tenant_id, employee_key) → row snapshot."""
    existing_employees = existing_employees or {}
    db = MagicMock()
    # Fresh cursor per call — ``run(db)`` may execute more than once
    # in an idempotency test.  Returning a shared cursor exhausts on
    # first iteration and the 2nd call sees zero tenants.
    db.tenants.find = MagicMock(
        side_effect=lambda *a, **kw: _AsyncCursor(list(tenants)),
    )

    async def _find_one(query, projection=None):
        tid = query.get("tenant_id")
        k = query.get("key")
        return existing_employees.get((tid, k))

    async def _insert_one(doc):
        # Persist so a second run sees it.
        existing_employees[(doc["tenant_id"], doc["key"])] = dict(doc)
        return SimpleNamespace(inserted_id="mock-id")

    async def _update_one(query, patch):
        row_id = query.get("id")
        for k, v in list(existing_employees.items()):
            if v.get("id") == row_id:
                new = dict(v)
                new.update(patch.get("$set", {}))
                existing_employees[k] = new
                return SimpleNamespace(matched_count=1)
        return SimpleNamespace(matched_count=0)

    db.ai_employees.find_one = _find_one
    db.ai_employees.insert_one = _insert_one
    db.ai_employees.update_one = _update_one
    return db, existing_employees


# ═══════════════════════════════════════════════════════════════════
# Fresh tenant → 18 inserts
# ═══════════════════════════════════════════════════════════════════
def test_fresh_tenant_gets_all_18_employees_inserted():
    from scripts.migrate_ai_hub_18_employees import run
    db, storage = _make_fake_db(tenants=[{"id": "t-fresh", "name": "Fresh"}])
    res = asyncio.run(run(db))
    assert res["ok"] is True
    assert res["tenants_scanned"] == 1
    assert res["employees_inserted"] == 18
    assert res["employees_patched"] == 0
    assert res["employees_untouched"] == 0
    # All 18 rows persisted with fail-safe defaults.
    assert len(storage) == 18
    for (tid, key), row in storage.items():
        assert tid == "t-fresh"
        assert row["authorized_for_public_use"] is False
        assert row["action_limit_monthly"] == 60000
        assert row["is_legacy"] is False


# ═══════════════════════════════════════════════════════════════════
# Idempotency — 2nd run is a no-op
# ═══════════════════════════════════════════════════════════════════
def test_migration_is_idempotent_second_run_does_nothing():
    from scripts.migrate_ai_hub_18_employees import run
    db, storage = _make_fake_db(tenants=[{"id": "t-idem"}])
    r1 = asyncio.run(run(db))
    r2 = asyncio.run(run(db))
    assert r1["employees_inserted"] == 18
    assert r2["employees_inserted"] == 0
    assert r2["employees_patched"] == 0
    assert r2["employees_untouched"] == 18


# ═══════════════════════════════════════════════════════════════════
# Existing customisations preserved
# ═══════════════════════════════════════════════════════════════════
def test_existing_customisations_are_never_overwritten():
    from scripts.migrate_ai_hub_18_employees import run
    # Pre-existing MARCO row with an admin-customised name + prompt.
    existing = {
        ("t-cust", "marco_executive"): {
            "id": "marco-existing", "tenant_id": "t-cust",
            "key": "marco_executive",
            "name": "Custom Assistant Name",           # DO NOT touch
            "system_prompt": "You are my custom MARCO.",  # DO NOT touch
            "avatar_url": "/custom/marco.png",         # DO NOT touch
            "active": True,
        },
    }
    db, storage = _make_fake_db(
        tenants=[{"id": "t-cust"}], existing_employees=existing,
    )
    asyncio.run(run(db))
    row = storage[("t-cust", "marco_executive")]
    # Preserved verbatim.
    assert row["name"] == "Custom Assistant Name"
    assert row["system_prompt"] == "You are my custom MARCO."
    assert row["avatar_url"] == "/custom/marco.png"
    # New fields patched with defaults.
    assert row["authorized_for_public_use"] is False
    assert row["action_limit_monthly"] == 60000
    assert row["is_legacy"] is False
    assert row["codename"] == "MARCO"
    assert row["human_name"] == "MARCO"
    assert row["org_department"] == "executive"


# ═══════════════════════════════════════════════════════════════════
# Backfill of missing new fields on legacy rows
# ═══════════════════════════════════════════════════════════════════
def test_missing_new_fields_are_patched_on_legacy_row():
    from scripts.migrate_ai_hub_18_employees import run
    # Pre-existing NOVA row (imagine an old admin-created custom
    # persona at that key) — missing every new field.
    existing = {
        ("t-back", "nova"): {
            "id": "nova-legacy", "tenant_id": "t-back", "key": "nova",
            "name": "Sarah", "role": "CMO",
            "active": True,
        },
    }
    db, storage = _make_fake_db(
        tenants=[{"id": "t-back"}], existing_employees=existing,
    )
    res = asyncio.run(run(db))
    assert res["employees_patched"] >= 1
    row = storage[("t-back", "nova")]
    assert row["authorized_for_public_use"] is False
    assert row["action_limit_monthly"] == 60000
    assert row["human_name"] == "Sarah"
    assert row["codename"] == "NOVA"
    assert row["role_title"] == "CMO"
    assert row["org_department"] == "marketing"
    assert row["hierarchy_order"] == 3
    assert row["manager_key"] == "marco_executive"


# ═══════════════════════════════════════════════════════════════════
# Multiple tenants get their own copies
# ═══════════════════════════════════════════════════════════════════
def test_multi_tenant_insertion():
    from scripts.migrate_ai_hub_18_employees import run
    db, storage = _make_fake_db(tenants=[
        {"id": "t-A"}, {"id": "t-B"},
    ])
    res = asyncio.run(run(db))
    assert res["tenants_scanned"] == 2
    assert res["employees_inserted"] == 36  # 18 × 2
    a_keys = {k for (t, k) in storage.keys() if t == "t-A"}
    b_keys = {k for (t, k) in storage.keys() if t == "t-B"}
    assert len(a_keys) == 18 and len(b_keys) == 18
    assert a_keys == b_keys


# ═══════════════════════════════════════════════════════════════════
# Env-gate — boot hook only runs when AI_HUB_AUTO_MIGRATE=true
# ═══════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("val", ["", "0", "false", "no", "True", "TRUE"])
def test_run_if_env_disabled_noops(monkeypatch, val):
    """Any value other than the exact lowercase ``true`` is a skip.
    ``"True"`` / ``"TRUE"`` DO count as ``true`` (case-insensitive)."""
    from scripts.migrate_ai_hub_18_employees import run_if_env_enabled
    monkeypatch.setenv("AI_HUB_AUTO_MIGRATE", val)
    db, _ = _make_fake_db(tenants=[{"id": "t-env"}])
    res = asyncio.run(run_if_env_enabled(db))
    should_run = val.strip().lower() == "true"
    if should_run:
        assert res.get("skipped") is not True
        assert "employees_inserted" in res
    else:
        assert res == {"ok": True, "skipped": True, "reason": "env_disabled"}


def test_run_if_env_unset_noops(monkeypatch):
    from scripts.migrate_ai_hub_18_employees import run_if_env_enabled
    monkeypatch.delenv("AI_HUB_AUTO_MIGRATE", raising=False)
    db, _ = _make_fake_db(tenants=[{"id": "t-none"}])
    res = asyncio.run(run_if_env_enabled(db))
    assert res == {"ok": True, "skipped": True, "reason": "env_disabled"}
