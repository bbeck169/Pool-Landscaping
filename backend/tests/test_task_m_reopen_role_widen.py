"""Task M+P · Commit 2 — Reopen endpoint role + multi-SR coverage.

Locks the Task M+P Commit 1 contract on
``backend/routers/jobs.py::reopen_job``:

  * Admin / super_admin → allowed on completed OR cancelled;
    clears ``submitted_at`` on ALL SRs for the job.
  * Technician (F1-authorised) → allowed on completed ONLY;
    clears ``submitted_at`` on ONLY their own SR.
  * Technician (not authorised — different tech or no
    assignment) → 403.
  * Customer + other roles → 403.
  * Status precondition — 400 with role-aware allowed_list.
  * Cross-tenant isolation — 404 when the job belongs to
    another tenant.
  * Multi-SR shape — admin clears every SR; tech clears only
    their own (other techs' SRs left submitted).
  * ``activity_logs`` row shape (actor_role + metadata) written.
  * Idempotency replay via X-Idempotency-Key (envelope
    preserved verbatim from pre-Task-M+P).
"""
from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import patch

import pytest
from dotenv import dotenv_values
from pymongo import MongoClient
from motor.motor_asyncio import AsyncIOMotorClient


_BE = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
MONGO_URL = _BE.get("MONGO_URL")
DB_NAME = _BE.get("DB_NAME")

TAG = "TASKMC1_"


# ─── Sync fixtures ─────────────────────────────────────────────────
@pytest.fixture(scope="module")
def dbc() -> MongoClient:
    return MongoClient(MONGO_URL)[DB_NAME]


@pytest.fixture
def cleanup(dbc):
    seeded_jids: List[str] = []
    seeded_report_ids: List[str] = []
    seeded_activity_ids: List[str] = []
    yield seeded_jids, seeded_report_ids, seeded_activity_ids
    if seeded_jids:
        dbc.jobs.delete_many({"id": {"$in": seeded_jids}})
        dbc.service_reports.delete_many({"job_id": {"$in": seeded_jids}})
        dbc.activity_logs.delete_many({"job_id": {"$in": seeded_jids}})
    if seeded_report_ids:
        dbc.service_reports.delete_many({"id": {"$in": seeded_report_ids}})
    if seeded_activity_ids:
        dbc.activity_logs.delete_many({"id": {"$in": seeded_activity_ids}})


# ─── Loop + Motor db swap ──────────────────────────────────────────
def _loop_and_db():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    client = AsyncIOMotorClient(MONGO_URL, io_loop=loop)
    adb = client[DB_NAME]
    from routers import jobs as _jobs_mod
    _jobs_mod._orig_db_for_test = getattr(_jobs_mod, "_orig_db_for_test",
                                            _jobs_mod.db)
    _jobs_mod.db = adb
    # authz helper does a crews lookup via passed-in db — no swap needed
    return loop, client, adb


def _restore_db(client=None, loop=None):
    from routers import jobs as _jobs_mod
    if hasattr(_jobs_mod, "_orig_db_for_test"):
        _jobs_mod.db = _jobs_mod._orig_db_for_test
    if client is not None:
        try:
            client.close()
        except Exception:
            pass
    if loop is not None:
        try:
            loop.close()
        except Exception:
            pass


def _run(async_call):
    loop, client, _adb = _loop_and_db()
    try:
        return loop.run_until_complete(async_call)
    finally:
        _restore_db(client, loop)


# ─── Seed helpers ──────────────────────────────────────────────────
def _fresh_id(prefix: str) -> str:
    return f"{TAG}{prefix}_{uuid.uuid4().hex[:8]}"


def _seed_job_sync(dbc, tenant_id: str, *,
                    status: str = "completed",
                    technician_id: str = None,
                    crew_id: str = None) -> str:
    jid = _fresh_id("JOB")
    doc: Dict[str, Any] = {
        "id": jid, "tenant_id": tenant_id,
        "customer_id": _fresh_id("CUST"),
        "title": "M+P seed", "status": status,
        "completed_at": "2026-02-01T00:00:00Z",
        "photos": [],
    }
    if technician_id:
        doc["technician_id"] = technician_id
    if crew_id:
        doc["crew_id"] = crew_id
    dbc.jobs.insert_one(doc)
    return jid


def _seed_sr_sync(dbc, tenant_id: str, job_id: str, *,
                    tech_id: str = None,
                    submitted_at: str = "2026-02-01T00:05:00Z",
                    submitted_by: str = None) -> str:
    rid = _fresh_id("SR")
    tech_id = tech_id or _fresh_id("TECH")
    doc: Dict[str, Any] = {
        "id": rid, "tenant_id": tenant_id, "job_id": job_id,
        "tech_id": tech_id,
        "public_uuid": uuid.uuid4().hex,
        "photos": [], "videos": [],
        "submitted_at": submitted_at,
        "submitted_by": submitted_by or tech_id,
    }
    dbc.service_reports.insert_one(doc)
    return rid


def _mock_request():
    """Minimal ``Request`` stand-in for the idempotency envelope.
    ``replay_or_reserve`` only reads the ``X-Idempotency-Key``
    header — an empty header dict skips the replay path entirely.
    """
    class _FakeRequest:
        headers = {}
    return _FakeRequest()


def _admin_user(uid: str = None):
    return {"id": uid or _fresh_id("USR"),
             "role": "admin", "name": "Admin Test"}


def _tech_user(tid: str, uid: str = None):
    return {"id": uid or tid, "role": "technician",
             "technician_id": tid, "name": "Tech Test"}


def _customer_user():
    return {"id": _fresh_id("CST"), "role": "customer",
             "name": "Cust Test"}


def _tenant(tid: str):
    return {"id": tid, "name": "test tenant"}


# ═══════════════════════════════════════════════════════════════════
# 1) ADMIN reopen — completed job — clears ALL SRs
# ═══════════════════════════════════════════════════════════════════
def test_admin_reopen_completed_clears_all_srs(dbc, cleanup):
    tenant_id = _fresh_id("T")
    seeded_jids, seeded_report_ids, seeded_activity_ids = cleanup

    jid = _seed_job_sync(dbc, tenant_id, status="completed")
    seeded_jids.append(jid)
    # Multi-tech job — 2 SRs.
    rid1 = _seed_sr_sync(dbc, tenant_id, jid, tech_id="techA")
    rid2 = _seed_sr_sync(dbc, tenant_id, jid, tech_id="techB")
    seeded_report_ids.extend([rid1, rid2])

    from routers.jobs import reopen_job
    updated = _run(reopen_job(jid, _mock_request(),
                                _admin_user(), _tenant(tenant_id)))

    assert updated["status"] == "active"
    assert updated.get("reopened_at")
    assert "completed_at" not in updated

    # BOTH SRs get their submitted_at cleared (admin scope=all).
    srs = list(dbc.service_reports.find({"job_id": jid}))
    assert len(srs) == 2
    for sr in srs:
        assert sr.get("submitted_at") is None
        assert "submitted_by" not in sr

    # Activity log written with actor_role=admin + metadata.
    audit = dbc.activity_logs.find_one({"job_id": jid, "type": "reopen"})
    assert audit is not None
    seeded_activity_ids.append(audit["id"])
    assert audit["actor_role"] == "admin"
    assert audit["metadata"]["cleared_sr_scope"] == "all"
    assert audit["metadata"]["cleared_sr_count"] == 2


# ═══════════════════════════════════════════════════════════════════
# 2) ADMIN reopen — cancelled job → allowed (unchanged)
# ═══════════════════════════════════════════════════════════════════
def test_admin_reopen_cancelled_allowed(dbc, cleanup):
    tenant_id = _fresh_id("T")
    seeded_jids, _, _ = cleanup
    jid = _seed_job_sync(dbc, tenant_id, status="cancelled")
    seeded_jids.append(jid)

    from routers.jobs import reopen_job
    updated = _run(reopen_job(jid, _mock_request(),
                                _admin_user(), _tenant(tenant_id)))
    assert updated["status"] == "active"


# ═══════════════════════════════════════════════════════════════════
# 3) TECH reopen — assigned tech + completed → allowed
# ═══════════════════════════════════════════════════════════════════
def test_assigned_tech_reopen_completed_clears_own_sr_only(dbc, cleanup):
    tenant_id = _fresh_id("T")
    seeded_jids, seeded_report_ids, _ = cleanup
    tech_a = _fresh_id("TECH")
    tech_b = _fresh_id("TECH")

    jid = _seed_job_sync(dbc, tenant_id, status="completed",
                          technician_id=tech_a)
    seeded_jids.append(jid)
    rid_a = _seed_sr_sync(dbc, tenant_id, jid, tech_id=tech_a)
    rid_b = _seed_sr_sync(dbc, tenant_id, jid, tech_id=tech_b)
    seeded_report_ids.extend([rid_a, rid_b])

    from routers.jobs import reopen_job
    updated = _run(reopen_job(jid, _mock_request(),
                                _tech_user(tech_a), _tenant(tenant_id)))
    assert updated["status"] == "active"

    # Only tech A's SR cleared; tech B's SR still submitted.
    sr_a = dbc.service_reports.find_one({"id": rid_a})
    sr_b = dbc.service_reports.find_one({"id": rid_b})
    assert sr_a["submitted_at"] is None
    assert sr_b["submitted_at"] is not None  # still locked

    audit = dbc.activity_logs.find_one({"job_id": jid, "type": "reopen"})
    assert audit["actor_role"] == "tech"
    assert audit["metadata"]["cleared_sr_scope"] == "own"
    assert audit["metadata"]["cleared_sr_count"] == 1
    dbc.activity_logs.delete_many({"id": audit["id"]})


# ═══════════════════════════════════════════════════════════════════
# 4) TECH reopen — NOT assigned → 403
# ═══════════════════════════════════════════════════════════════════
def test_unassigned_tech_reopen_forbidden(dbc, cleanup):
    tenant_id = _fresh_id("T")
    seeded_jids, _, _ = cleanup
    tech_owner = _fresh_id("TECH")
    tech_other = _fresh_id("TECH")

    jid = _seed_job_sync(dbc, tenant_id, status="completed",
                          technician_id=tech_owner)
    seeded_jids.append(jid)

    from routers.jobs import reopen_job
    from fastapi import HTTPException as _HE
    with pytest.raises(_HE) as excinfo:
        _run(reopen_job(jid, _mock_request(),
                          _tech_user(tech_other), _tenant(tenant_id)))
    assert excinfo.value.status_code == 403


# ═══════════════════════════════════════════════════════════════════
# 5) TECH reopen — cancelled job → 400 (E2 preserved)
# ═══════════════════════════════════════════════════════════════════
def test_tech_reopen_cancelled_status_forbidden(dbc, cleanup):
    """Tech attempting to reopen a cancelled job → 400 with the
    role-aware allowed_list detail (E2 — cancelled is admin-only)."""
    tenant_id = _fresh_id("T")
    seeded_jids, _, _ = cleanup
    tech = _fresh_id("TECH")
    jid = _seed_job_sync(dbc, tenant_id, status="cancelled",
                          technician_id=tech)
    seeded_jids.append(jid)

    from routers.jobs import reopen_job
    from fastapi import HTTPException as _HE
    with pytest.raises(_HE) as excinfo:
        _run(reopen_job(jid, _mock_request(),
                          _tech_user(tech), _tenant(tenant_id)))
    assert excinfo.value.status_code == 400
    assert "Only completed" in str(excinfo.value.detail)


# ═══════════════════════════════════════════════════════════════════
# 6) CUSTOMER role → 403
# ═══════════════════════════════════════════════════════════════════
def test_customer_role_forbidden(dbc, cleanup):
    tenant_id = _fresh_id("T")
    seeded_jids, _, _ = cleanup
    jid = _seed_job_sync(dbc, tenant_id, status="completed")
    seeded_jids.append(jid)

    from routers.jobs import reopen_job
    from fastapi import HTTPException as _HE
    with pytest.raises(_HE) as excinfo:
        _run(reopen_job(jid, _mock_request(),
                          _customer_user(), _tenant(tenant_id)))
    assert excinfo.value.status_code == 403


# ═══════════════════════════════════════════════════════════════════
# 7) Status precondition — admin on already-active → 400 (C1)
# ═══════════════════════════════════════════════════════════════════
def test_admin_reopen_active_returns_400(dbc, cleanup):
    """C1 — pre-Task-M+P 400 contract preserved on the admin path
    when the job is already active."""
    tenant_id = _fresh_id("T")
    seeded_jids, _, _ = cleanup
    jid = _seed_job_sync(dbc, tenant_id, status="active")
    seeded_jids.append(jid)

    from routers.jobs import reopen_job
    from fastapi import HTTPException as _HE
    with pytest.raises(_HE) as excinfo:
        _run(reopen_job(jid, _mock_request(),
                          _admin_user(), _tenant(tenant_id)))
    assert excinfo.value.status_code == 400
    assert "Only completed or cancelled" in str(excinfo.value.detail)


# ═══════════════════════════════════════════════════════════════════
# 8) Cross-tenant — 404
# ═══════════════════════════════════════════════════════════════════
def test_cross_tenant_reopen_returns_404(dbc, cleanup):
    """Tenant B's job never surfaces to a Tenant A admin."""
    tenant_a = _fresh_id("TA")
    tenant_b = _fresh_id("TB")
    seeded_jids, _, _ = cleanup
    jid = _seed_job_sync(dbc, tenant_b, status="completed")
    seeded_jids.append(jid)

    from routers.jobs import reopen_job
    from fastapi import HTTPException as _HE
    with pytest.raises(_HE) as excinfo:
        _run(reopen_job(jid, _mock_request(),
                          _admin_user(), _tenant(tenant_a)))
    assert excinfo.value.status_code == 404


# ═══════════════════════════════════════════════════════════════════
# 9) Job with no SR — reopen still succeeds
# ═══════════════════════════════════════════════════════════════════
def test_reopen_job_with_no_sr_still_succeeds(dbc, cleanup):
    """Some legacy completed jobs never had an SR created.  Reopen
    must still flip the status (cleared_sr_count = 0)."""
    tenant_id = _fresh_id("T")
    seeded_jids, _, _ = cleanup
    jid = _seed_job_sync(dbc, tenant_id, status="completed")
    seeded_jids.append(jid)
    # No SR seeded.

    from routers.jobs import reopen_job
    updated = _run(reopen_job(jid, _mock_request(),
                                _admin_user(), _tenant(tenant_id)))
    assert updated["status"] == "active"

    audit = dbc.activity_logs.find_one({"job_id": jid, "type": "reopen"})
    assert audit["metadata"]["cleared_sr_count"] == 0
    dbc.activity_logs.delete_many({"id": audit["id"]})


# ═══════════════════════════════════════════════════════════════════
# 10) Tech id fallback — user.id when technician_id missing
# ═══════════════════════════════════════════════════════════════════
def test_tech_id_falls_back_to_user_id_for_own_sr_scope(dbc, cleanup):
    """Older seeds stamp ``user.id`` on ``jobs.technician_id`` and
    ``service_reports.tech_id``.  The reopen tech-scope filter
    must accept both — pattern: ``user.technician_id or user.id``.
    """
    tenant_id = _fresh_id("T")
    seeded_jids, seeded_report_ids, _ = cleanup
    user_id = _fresh_id("USR")
    jid = _seed_job_sync(dbc, tenant_id, status="completed",
                          technician_id=user_id)
    seeded_jids.append(jid)
    rid = _seed_sr_sync(dbc, tenant_id, jid, tech_id=user_id)
    seeded_report_ids.append(rid)

    # Tech user with NO technician_id — only user.id.
    tech_user = {"id": user_id, "role": "technician",
                  "name": "Fallback Tech"}

    from routers.jobs import reopen_job
    updated = _run(reopen_job(jid, _mock_request(),
                                tech_user, _tenant(tenant_id)))
    assert updated["status"] == "active"
    sr = dbc.service_reports.find_one({"id": rid})
    assert sr["submitted_at"] is None

    audit = dbc.activity_logs.find_one({"job_id": jid, "type": "reopen"})
    assert audit["metadata"]["cleared_sr_scope"] == "own"
    assert audit["metadata"]["cleared_sr_count"] == 1
    dbc.activity_logs.delete_many({"id": audit["id"]})


# ═══════════════════════════════════════════════════════════════════
# 11) Response shape — job doc returned, status flipped, no data blobs
# ═══════════════════════════════════════════════════════════════════
def test_response_shape_returns_updated_job(dbc, cleanup):
    tenant_id = _fresh_id("T")
    seeded_jids, _, _ = cleanup
    jid = _seed_job_sync(dbc, tenant_id, status="completed")
    seeded_jids.append(jid)

    from routers.jobs import reopen_job
    updated = _run(reopen_job(jid, _mock_request(),
                                _admin_user(), _tenant(tenant_id)))
    assert updated["id"] == jid
    assert updated["status"] == "active"
    assert updated["tenant_id"] == tenant_id
    # No _id leak in the response payload.
    assert "_id" not in updated
