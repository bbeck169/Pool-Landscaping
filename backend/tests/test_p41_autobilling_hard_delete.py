"""Phase P41 · Feb-2026 — Autobilling Runs · Hard Delete.

Physical removal of the audit document from ``db.autobilling_runs``.
Endpoints:
  * ``DELETE /api/autobilling-runs/{run_id}`` → single hard delete.
  * ``POST /api/autobilling-runs/hard-delete-bulk`` → bulk hard delete.

Security invariants under test:
  1. Tenant scoping is mandatory on every query. Cross-tenant delete
     returns **404** (existence-hiding), never 403.
  2. Admin / super_admin / owner only. Technician → 403.
  3. In-progress runs (``status in {running, in_progress}``) delete
     but WARN — no hard-block per user spec.
  4. Bulk endpoint always returns 200 with counts + ``not_found``.

Uses the same event-loop-bound Motor client pattern as the P40 tests
so we can drive the router helpers directly against real Mongo
without spinning up the FastAPI TestClient. This keeps the test
runtime tight and avoids pulling in the whole app boot lifespan.
"""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from pathlib import Path

import pytest
from dotenv import load_dotenv
from fastapi import HTTPException
from motor.motor_asyncio import AsyncIOMotorClient


load_dotenv(Path(__file__).resolve().parents[1] / ".env")

_LOOP = asyncio.new_event_loop()
_MOTOR = AsyncIOMotorClient(os.environ["MONGO_URL"], io_loop=_LOOP)
_DB = _MOTOR[os.environ["DB_NAME"]]


def _run(coro):
    return _LOOP.run_until_complete(coro)


# ─────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────
@pytest.fixture
def p41_db(monkeypatch):
    """Rebind the router's module-level ``db`` symbol to our loop-
    bound client so ``delete_one`` / ``delete_many`` awaits resolve
    on the test loop."""
    import config as _config_mod
    monkeypatch.setattr(_config_mod, "db", _DB)
    from routers import finances as _f
    monkeypatch.setattr(_f, "db", _DB)
    yield _DB


@pytest.fixture
def tenant_a(p41_db):
    tid = f"test_p41_a_{uuid.uuid4().hex[:8]}"
    yield {"id": tid}
    _run(_DB.autobilling_runs.delete_many({"tenant_id": tid}))
    _run(_DB.audits.delete_many({"tenant_id": tid}))


@pytest.fixture
def tenant_b(p41_db):
    tid = f"test_p41_b_{uuid.uuid4().hex[:8]}"
    yield {"id": tid}
    _run(_DB.autobilling_runs.delete_many({"tenant_id": tid}))
    _run(_DB.audits.delete_many({"tenant_id": tid}))


def _admin(uid: str = "u-admin"):
    return {"id": uid, "email": "admin@test", "role": "admin"}


def _tech(uid: str = "u-tech"):
    return {"id": uid, "email": "tech@test", "role": "technician"}


def _seed_run(tenant_id: str, *, status: str = "fired",
              rid: str | None = None) -> str:
    rid = rid or f"run_{uuid.uuid4().hex[:12]}"
    _run(_DB.autobilling_runs.insert_one({
        "id": rid, "tenant_id": tenant_id, "status": status,
        "ts": "2026-02-15T10:00:00Z",
        "plan_id": "plan-x", "plan_name": "Plan X",
        "message": "seeded for P41 test",
    }))
    return rid


# ─────────────────────────────────────────────────────────────────────
# Tests — single hard delete
# ─────────────────────────────────────────────────────────────────────
def test_hard_delete_single_run_removes_document(tenant_a):
    from routers.finances import hard_delete_autobilling_run
    rid = _seed_run(tenant_a["id"])
    res = _run(hard_delete_autobilling_run(
        run_id=rid, user=_admin(), tenant=tenant_a))
    assert res == {"deleted": True, "id": rid}
    # Physical delete — Mongo returns None.
    got = _run(_DB.autobilling_runs.find_one({"id": rid}))
    assert got is None


def test_hard_delete_returns_404_for_unknown_id(tenant_a):
    from routers.finances import hard_delete_autobilling_run
    with pytest.raises(HTTPException) as exc:
        _run(hard_delete_autobilling_run(
            run_id="does-not-exist", user=_admin(), tenant=tenant_a))
    assert exc.value.status_code == 404


def test_hard_delete_returns_404_for_other_tenant_run(tenant_a, tenant_b):
    """Cross-tenant delete MUST 404 (existence-hiding), never 403."""
    from routers.finances import hard_delete_autobilling_run
    rid = _seed_run(tenant_b["id"])  # owned by tenant B
    with pytest.raises(HTTPException) as exc:
        _run(hard_delete_autobilling_run(
            run_id=rid, user=_admin(), tenant=tenant_a))
    assert exc.value.status_code == 404
    # And the row MUST still exist for tenant B.
    still = _run(_DB.autobilling_runs.find_one({"id": rid}))
    assert still is not None


def test_hard_delete_requires_admin_role():
    """The endpoint depends on ``require_admin``. A technician user
    passed through that dependency must be rejected with 403 before
    the handler runs. We assert against the dependency directly
    since we're calling the handler without going through the app."""
    from utils import require_admin
    # ``require_admin`` is a FastAPI dependency that resolves the
    # current user and raises 403 for non-admin roles.
    with pytest.raises(HTTPException) as exc:
        _run(require_admin(_tech()))
    assert exc.value.status_code in (401, 403)


def test_hard_delete_in_progress_run_still_deletes_with_warn_log(
    tenant_a, caplog,
):
    """status=running → delete anyway + WARN log captured."""
    from routers.finances import hard_delete_autobilling_run
    rid = _seed_run(tenant_a["id"], status="running")
    caplog.set_level(logging.WARNING)
    res = _run(hard_delete_autobilling_run(
        run_id=rid, user=_admin(), tenant=tenant_a))
    assert res["deleted"] is True
    # Row physically removed.
    assert _run(_DB.autobilling_runs.find_one({"id": rid})) is None
    # WARN log surfaced.
    warn_lines = [
        rec.getMessage() for rec in caplog.records
        if rec.levelno >= logging.WARNING and "[p41]" in rec.getMessage()
    ]
    assert warn_lines, f"expected [p41] WARN log, got: {caplog.text!r}"
    assert any("status=running" in m for m in warn_lines)


# ─────────────────────────────────────────────────────────────────────
# Tests — bulk hard delete
# ─────────────────────────────────────────────────────────────────────
def test_bulk_hard_delete_removes_all_matching_and_reports_counts(tenant_a):
    from routers.finances import (hard_delete_autobilling_runs_bulk,
                                   _AutobillingRunsHardDeleteBulkIn)
    r1, r2, r3 = [_seed_run(tenant_a["id"]) for _ in range(3)]
    body = _AutobillingRunsHardDeleteBulkIn(ids=[r1, r2, r3])
    res = _run(hard_delete_autobilling_runs_bulk(
        body=body, user=_admin(), tenant=tenant_a))
    assert res["deleted_count"] == 3
    assert res["requested_count"] == 3
    assert res["not_found"] == []
    # All physically gone.
    for rid in (r1, r2, r3):
        assert _run(_DB.autobilling_runs.find_one({"id": rid})) is None


def test_bulk_hard_delete_partial_success_reports_not_found(tenant_a):
    from routers.finances import (hard_delete_autobilling_runs_bulk,
                                   _AutobillingRunsHardDeleteBulkIn)
    r1 = _seed_run(tenant_a["id"])
    r2 = _seed_run(tenant_a["id"])
    ghost = "run_ghost_" + uuid.uuid4().hex[:6]
    body = _AutobillingRunsHardDeleteBulkIn(ids=[r1, ghost, r2])
    res = _run(hard_delete_autobilling_runs_bulk(
        body=body, user=_admin(), tenant=tenant_a))
    assert res["deleted_count"] == 2
    assert res["requested_count"] == 3
    assert res["not_found"] == [ghost]


def test_bulk_hard_delete_tenant_scoping_ignores_other_tenant_ids(
    tenant_a, tenant_b,
):
    from routers.finances import (hard_delete_autobilling_runs_bulk,
                                   _AutobillingRunsHardDeleteBulkIn)
    b1 = _seed_run(tenant_b["id"])
    b2 = _seed_run(tenant_b["id"])
    # Tenant A admin tries to nuke tenant B's rows.
    body = _AutobillingRunsHardDeleteBulkIn(ids=[b1, b2])
    res = _run(hard_delete_autobilling_runs_bulk(
        body=body, user=_admin(), tenant=tenant_a))
    assert res["deleted_count"] == 0
    assert res["requested_count"] == 2
    # Both ids leaked as ``not_found`` (existence-hiding — same as
    # unknown ids). Order preserved from the input.
    assert set(res["not_found"]) == {b1, b2}
    # Tenant B's rows MUST still exist.
    for rid in (b1, b2):
        assert _run(_DB.autobilling_runs.find_one({"id": rid})) is not None


def test_bulk_hard_delete_admin_only():
    """require_admin gate rejects technicians before the handler
    ever runs — mirrors the single-delete admin-only test."""
    from utils import require_admin
    with pytest.raises(HTTPException) as exc:
        _run(require_admin(_tech()))
    assert exc.value.status_code in (401, 403)


def test_bulk_hard_delete_empty_array_returns_200_zero(tenant_a):
    from routers.finances import (hard_delete_autobilling_runs_bulk,
                                   _AutobillingRunsHardDeleteBulkIn)
    body = _AutobillingRunsHardDeleteBulkIn(ids=[])
    res = _run(hard_delete_autobilling_runs_bulk(
        body=body, user=_admin(), tenant=tenant_a))
    assert res == {"deleted_count": 0, "requested_count": 0,
                    "not_found": []}


def test_bulk_hard_delete_deduplicates_repeated_ids(tenant_a):
    """A caller sending the same id twice counts as a single delete
    with a single audit event, and ``deleted_count`` reflects that."""
    from routers.finances import (hard_delete_autobilling_runs_bulk,
                                   _AutobillingRunsHardDeleteBulkIn)
    rid = _seed_run(tenant_a["id"])
    body = _AutobillingRunsHardDeleteBulkIn(ids=[rid, rid, rid])
    res = _run(hard_delete_autobilling_runs_bulk(
        body=body, user=_admin(), tenant=tenant_a))
    assert res["deleted_count"] == 1
    assert res["requested_count"] == 3  # count of what caller sent
    assert res["not_found"] == []
    assert _run(_DB.autobilling_runs.find_one({"id": rid})) is None
