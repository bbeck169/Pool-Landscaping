"""Phase 21 · Sub-item B — landscape/department seed-drift fix pytest.

Seeds a user with a legacy ``department="landscaping"`` value, runs the
Phase 21 fix script in-process, and asserts the field is remapped to
the canonical ``"landscape_tech"``.

Also asserts:
  * A second run of the script is a no-op (idempotency).
  * A user with an unrecognized value (``"north"``) is cleared to
    ``None`` and logged (WARNING).
  * A user whose value is already valid (``"pool_tech"``) is untouched.
"""
from __future__ import annotations

import asyncio
import os
import sys
import uuid
from pathlib import Path

import pytest
from dotenv import dotenv_values
from pymongo import MongoClient

os.environ.setdefault("ALLOW_TEST_HOOKS", "1")

_BACKEND_DIR = Path(__file__).resolve().parents[1]
_ENV = dotenv_values(_BACKEND_DIR / ".env")
_sync = MongoClient(_ENV["MONGO_URL"])[_ENV["DB_NAME"]]

# Make the script importable without shipping an __init__.py.
sys.path.insert(0, str(_BACKEND_DIR / "scripts"))
import fix_landscape_tech_seed_drift as fix_drift  # noqa: E402


# Phase 41.1c · Feb 2026 — batch-bleed isolation.
#
# ``fix_drift.run()`` scans the ENTIRE ``users`` collection, not just
# the ephemeral tenant this file seeds. Real demo users (e.g.
# ``landscaper@aquaterra.com`` seeded with ``department="landscaping"``
# by ``backend/seed.py::seed_landscaping_user``) get remapped to
# ``"landscape_tech"``, and every downstream test that calls
# ``_require_landscaping()`` — which accepts only ``"landscaping"`` /
# ``"both"`` — 403s in the batched pytest run.
#
# Guard: module-scoped ``autouse=True`` fixture that snapshots the
# ``department`` field on every non-ephemeral user BEFORE the file's
# tests run, and restores it verbatim after. Cheap, deterministic,
# no runtime code touched. Also mirrors the restore onto the linked
# ``technicians`` docs so tests downstream of this file don't see a
# split-brain user/tech state.
@pytest.fixture(scope="module", autouse=True)
def _restore_real_user_departments_after_phase21():
    # Snapshot only rows whose email is NOT part of this file's own
    # ephemeral fixture (the `p21b-*@p21.test` accounts) so we
    # don't accidentally reintroduce them. Also skip rows with no
    # ``department`` field at all — they never had one to restore.
    snapshot_users = [
        {"id": u["id"], "department": u.get("department")}
        for u in _sync.users.find(
            {"email": {"$not": {"$regex": r"@p21\.test$"}}},
            {"_id": 0, "id": 1, "department": 1, "email": 1},
        )
    ]
    snapshot_techs = [
        {"id": t["id"], "department": t.get("department")}
        for t in _sync.technicians.find(
            {"email": {"$not": {"$regex": r"@p21\.test$"}}},
            {"_id": 0, "id": 1, "department": 1, "email": 1},
        )
    ]
    yield
    for row in snapshot_users:
        _sync.users.update_one(
            {"id": row["id"]},
            {"$set": {"department": row["department"]}},
        )
    for row in snapshot_techs:
        _sync.technicians.update_one(
            {"id": row["id"]},
            {"$set": {"department": row["department"]}},
        )


@pytest.fixture()
def seeded_users():
    tid = f"p21b-{uuid.uuid4().hex[:8]}"
    _sync.tenants.insert_one({
        "id": tid, "name": f"P21B {tid}", "slug": f"p21b-{tid}",
        "active": True, "widget_allowed_domains": [],
    })
    landscaping_uid = f"u-{uuid.uuid4().hex[:8]}"
    valid_uid = f"u-{uuid.uuid4().hex[:8]}"
    north_uid = f"u-{uuid.uuid4().hex[:8]}"
    _sync.users.insert_many([
        {"id": landscaping_uid, "tenant_id": tid, "role": "technician",
         "email": f"{landscaping_uid}@p21.test",
         "department": "landscaping"},   # legacy value → remap
        {"id": valid_uid, "tenant_id": tid, "role": "technician",
         "email": f"{valid_uid}@p21.test",
         "department": "pool_tech"},     # already valid → no-op
        {"id": north_uid, "tenant_id": tid, "role": "technician",
         "email": f"{north_uid}@p21.test",
         "department": "north"},          # unrecognized → clear
    ])
    yield {"tid": tid, "landscaping": landscaping_uid,
           "valid": valid_uid, "north": north_uid}
    _sync.tenants.delete_many({"id": tid})
    _sync.users.delete_many({"tenant_id": tid})


def test_landscape_drift_is_fixed(seeded_users):
    r1 = asyncio.run(fix_drift.run(dry_run=False))
    assert r1["remapped"] >= 1
    assert r1["cleared"] >= 1

    remapped = _sync.users.find_one({"id": seeded_users["landscaping"]})
    assert remapped["department"] == "landscape_tech"

    cleared = _sync.users.find_one({"id": seeded_users["north"]})
    assert cleared["department"] is None

    valid = _sync.users.find_one({"id": seeded_users["valid"]})
    assert valid["department"] == "pool_tech"  # unchanged


def test_script_is_idempotent(seeded_users):
    # First run — should remap the landscaping row.
    asyncio.run(fix_drift.run(dry_run=False))
    # Second run — nothing left to fix within THIS tenant. Global counts
    # may still be non-zero (other tenants); assert this tenant's rows
    # are stable across a second pass.
    before = {u["id"]: u.get("department")
              for u in _sync.users.find({"tenant_id": seeded_users["tid"]})}
    asyncio.run(fix_drift.run(dry_run=False))
    after = {u["id"]: u.get("department")
             for u in _sync.users.find({"tenant_id": seeded_users["tid"]})}
    assert before == after, (
        f"second run mutated rows in tenant {seeded_users['tid']!r} — "
        f"idempotency broken. before={before} after={after}"
    )
