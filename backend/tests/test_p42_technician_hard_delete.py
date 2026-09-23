"""Phase P42 · Feb-2026 — Team Member HARD DELETE (technicians surface).

Physical removal of a technician + their linked user login + any
pending invitations. Future scheduled/pending jobs are unassigned
(``technician_id=null``) — job rows are NEVER deleted.

Endpoints:
  * ``DELETE /api/technicians/{tech_id}/hard-delete``
  * ``POST /api/technicians/hard-delete-bulk``

Security invariants under test (mirror ``hard_delete_technician``
docstring):
  1. Tenant scoping mandatory. Cross-tenant id → 404 (existence-hiding).
  2. Admin / super_admin only. Technician → 403.
  3. Self-delete → 400 ``cannot_delete_self``.
  4. Last-admin orphan → 400 ``would_orphan_tenant_no_admin_remaining``.
  5. In-progress-job protection: proceed + ERROR log, no hard-block.
  6. Job records preserved; only ``technician_id`` unassigned on
     future scheduled/pending jobs.
  7. Bulk cap: 500 ids/call, dedupes repeated ids.
"""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
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


def _iso(dt: datetime) -> str:
    return dt.isoformat()


# ─────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────
@pytest.fixture
def p42_db(monkeypatch):
    import config as _config_mod
    monkeypatch.setattr(_config_mod, "db", _DB)
    from routers import technicians as _t
    monkeypatch.setattr(_t, "db", _DB)
    yield _DB


@pytest.fixture
def tenant_a(p42_db):
    tid = f"test_p42_a_{uuid.uuid4().hex[:8]}"
    yield {"id": tid}
    _run(_DB.technicians.delete_many({"tenant_id": tid}))
    _run(_DB.users.delete_many({"tenant_id": tid}))
    _run(_DB.jobs.delete_many({"tenant_id": tid}))
    _run(_DB.audits.delete_many({"tenant_id": tid}))
    _run(_DB.deletion_audit.delete_many({"tenant_id": tid}))


@pytest.fixture
def tenant_b(p42_db):
    tid = f"test_p42_b_{uuid.uuid4().hex[:8]}"
    yield {"id": tid}
    _run(_DB.technicians.delete_many({"tenant_id": tid}))
    _run(_DB.users.delete_many({"tenant_id": tid}))
    _run(_DB.jobs.delete_many({"tenant_id": tid}))


def _admin_actor(tid: str = "actor-admin"):
    return {"id": tid, "email": "admin@test", "role": "admin"}


def _seed_admin_user(tenant_id: str, *, uid: str | None = None):
    uid = uid or f"admin_{uuid.uuid4().hex[:8]}"
    _run(_DB.users.insert_one({
        "id": uid, "tenant_id": tenant_id, "role": "admin",
        "email": f"{uid}@test", "name": f"Admin {uid}",
    }))
    return uid


def _seed_tech_with_user(tenant_id: str, *, tech_role: str = "technician",
                         user_role: str = "technician",
                         name: str = "Test Tech"):
    uid = f"u_{uuid.uuid4().hex[:8]}"
    tid = f"t_{uuid.uuid4().hex[:8]}"
    _run(_DB.users.insert_one({
        "id": uid, "tenant_id": tenant_id, "role": user_role,
        "email": f"{uid}@test", "name": name,
        "technician_id": tid,
    }))
    _run(_DB.technicians.insert_one({
        "id": tid, "tenant_id": tenant_id, "name": name,
        "email": f"{uid}@test", "user_id": uid, "active": True,
    }))
    return tid, uid


def _seed_tech_no_user(tenant_id: str, name: str = "Orphan Tech"):
    tid = f"t_{uuid.uuid4().hex[:8]}"
    _run(_DB.technicians.insert_one({
        "id": tid, "tenant_id": tenant_id, "name": name, "active": True,
    }))
    return tid


def _seed_job(tenant_id: str, technician_id: str, *, status: str,
              scheduled_start: datetime | None = None):
    jid = f"j_{uuid.uuid4().hex[:8]}"
    _run(_DB.jobs.insert_one({
        "id": jid, "tenant_id": tenant_id,
        "technician_id": technician_id,
        "technician_name": "Test Tech",
        "status": status,
        "scheduled_start": _iso(scheduled_start) if scheduled_start else None,
    }))
    return jid


# ─────────────────────────────────────────────────────────────────────
# Tests — single hard delete
# ─────────────────────────────────────────────────────────────────────
def test_hard_delete_single_tech_removes_all_linked_records(tenant_a):
    from routers.technicians import hard_delete_technician
    # Seed a second admin so the orphan guard doesn't block us.
    _seed_admin_user(tenant_a["id"])
    tid, uid = _seed_tech_with_user(tenant_a["id"])
    # A future scheduled job — should be unassigned but not deleted.
    future = datetime.now(timezone.utc) + timedelta(days=3)
    fj = _seed_job(tenant_a["id"], tid, status="scheduled",
                    scheduled_start=future)
    # A past completed job — should stay assigned + not deleted.
    past = datetime.now(timezone.utc) - timedelta(days=10)
    pj = _seed_job(tenant_a["id"], tid, status="completed",
                    scheduled_start=past)

    res = _run(hard_delete_technician(
        tech_id=tid, user=_admin_actor(), tenant=tenant_a))
    assert res["deleted"] is True
    assert res["tech_id"] == tid
    assert res["linked_user_deleted"] is True
    assert res["future_jobs_unassigned"] == 1
    assert res["pending_invitations_deleted"] == 0
    assert res["audit_id"]

    # Tech + user physically gone.
    assert _run(_DB.technicians.find_one({"id": tid})) is None
    assert _run(_DB.users.find_one({"id": uid})) is None

    # Future job preserved but unassigned.
    fj_doc = _run(_DB.jobs.find_one({"id": fj}))
    assert fj_doc is not None
    assert fj_doc.get("technician_id") is None
    assert fj_doc.get("technician_name") is None
    assert fj_doc.get("unassigned_reason") == "technician_hard_deleted"

    # Past completed job untouched.
    pj_doc = _run(_DB.jobs.find_one({"id": pj}))
    assert pj_doc.get("technician_id") == tid
    assert pj_doc.get("status") == "completed"

    # Forensic audit written.
    audit = _run(_DB.audits.find_one({"id": res["audit_id"]}))
    assert audit is not None
    assert audit["kind"] == "technicians_hard_delete"
    assert audit["target_id"] == tid
    assert audit["tech_snapshot"]["id"] == tid
    assert audit["linked_user_snapshot"]["id"] == uid
    assert audit["future_jobs_unassigned"] == 1


def test_hard_delete_returns_404_for_unknown_id(tenant_a):
    from routers.technicians import hard_delete_technician
    _seed_admin_user(tenant_a["id"])  # so orphan guard doesn't fire
    with pytest.raises(HTTPException) as exc:
        _run(hard_delete_technician(
            tech_id="does-not-exist", user=_admin_actor(), tenant=tenant_a))
    assert exc.value.status_code == 404


def test_hard_delete_returns_404_for_cross_tenant_id(tenant_a, tenant_b):
    """Cross-tenant tech id MUST return 404 (existence-hiding),
    never 403."""
    from routers.technicians import hard_delete_technician
    _seed_admin_user(tenant_a["id"])
    _seed_admin_user(tenant_b["id"])
    tid_b, _uid_b = _seed_tech_with_user(tenant_b["id"])
    with pytest.raises(HTTPException) as exc:
        _run(hard_delete_technician(
            tech_id=tid_b, user=_admin_actor(), tenant=tenant_a))
    assert exc.value.status_code == 404
    # Tenant B row MUST still exist.
    assert _run(_DB.technicians.find_one({"id": tid_b})) is not None


def test_hard_delete_requires_admin_role():
    """require_admin gate rejects technician role before handler runs."""
    from utils import require_admin
    with pytest.raises(HTTPException) as exc:
        _run(require_admin({"id": "u-tech", "role": "technician",
                              "email": "tech@t"}))
    assert exc.value.status_code in (401, 403)


def test_hard_delete_self_returns_400_cannot_delete_self(tenant_a):
    """When the caller resolves to the target tech's linked user
    (or has the tech id set on their own user doc), block with 400."""
    from routers.technicians import hard_delete_technician
    _seed_admin_user(tenant_a["id"])
    tid, uid = _seed_tech_with_user(tenant_a["id"])
    # Caller is the linked user for this tech → self-delete.
    caller = {"id": uid, "role": "admin", "email": f"{uid}@test",
              "technician_id": tid}
    with pytest.raises(HTTPException) as exc:
        _run(hard_delete_technician(
            tech_id=tid, user=caller, tenant=tenant_a))
    assert exc.value.status_code == 400
    assert exc.value.detail["code"] == "cannot_delete_self"


def test_hard_delete_would_orphan_no_admin_returns_400(tenant_a):
    """Deleting the LAST admin's linked tech → 400
    ``would_orphan_tenant_no_admin_remaining``."""
    from routers.technicians import hard_delete_technician
    # No other admins seeded — the tech's linked user IS the only admin.
    tid, uid = _seed_tech_with_user(
        tenant_a["id"], user_role="admin")
    caller = _admin_actor("another-actor-id")
    with pytest.raises(HTTPException) as exc:
        _run(hard_delete_technician(
            tech_id=tid, user=caller, tenant=tenant_a))
    assert exc.value.status_code == 400
    assert (exc.value.detail["code"]
            == "would_orphan_tenant_no_admin_remaining")
    # Nothing deleted.
    assert _run(_DB.technicians.find_one({"id": tid})) is not None
    assert _run(_DB.users.find_one({"id": uid})) is not None


def test_hard_delete_preserves_completed_and_past_jobs(tenant_a):
    """Only future scheduled/pending jobs get unassigned. Completed
    + in_progress + cancelled jobs stay assigned."""
    from routers.technicians import hard_delete_technician
    _seed_admin_user(tenant_a["id"])
    tid, _uid = _seed_tech_with_user(tenant_a["id"])
    now = datetime.now(timezone.utc)
    future = now + timedelta(days=2)
    past = now - timedelta(days=2)
    jf = _seed_job(tenant_a["id"], tid, status="scheduled",
                    scheduled_start=future)  # → unassigned
    jp = _seed_job(tenant_a["id"], tid, status="scheduled",
                    scheduled_start=past)     # past → stays assigned
    jc = _seed_job(tenant_a["id"], tid, status="completed",
                    scheduled_start=past)     # completed → stays
    jip = _seed_job(tenant_a["id"], tid, status="in_progress",
                     scheduled_start=now)      # in_progress → stays

    res = _run(hard_delete_technician(
        tech_id=tid, user=_admin_actor(), tenant=tenant_a))
    assert res["future_jobs_unassigned"] == 1

    # Only the future/scheduled job got unassigned.
    assert _run(_DB.jobs.find_one({"id": jf}))["technician_id"] is None
    assert _run(_DB.jobs.find_one({"id": jp}))["technician_id"] == tid
    assert _run(_DB.jobs.find_one({"id": jc}))["technician_id"] == tid
    assert _run(_DB.jobs.find_one({"id": jip}))["technician_id"] == tid
    # No jobs deleted.
    assert _run(_DB.jobs.count_documents(
        {"tenant_id": tenant_a["id"]})) == 4


def test_hard_delete_unlinked_user_response_marks_linked_user_deleted_false(
    tenant_a,
):
    """Tech with NO linked user (``user_id`` unset AND no reverse
    match) → ``linked_user_deleted: false``."""
    from routers.technicians import hard_delete_technician
    _seed_admin_user(tenant_a["id"])
    tid = _seed_tech_no_user(tenant_a["id"])
    res = _run(hard_delete_technician(
        tech_id=tid, user=_admin_actor(), tenant=tenant_a))
    assert res["deleted"] is True
    assert res["linked_user_deleted"] is False
    assert res["pending_invitations_deleted"] == 0


def test_hard_delete_no_pending_invitations_response_marks_count_zero(
    tenant_a,
):
    """Environment has no ``invitations`` collection today, so the
    count MUST always be 0 (documented no-op)."""
    from routers.technicians import hard_delete_technician
    _seed_admin_user(tenant_a["id"])
    tid, _uid = _seed_tech_with_user(tenant_a["id"])
    res = _run(hard_delete_technician(
        tech_id=tid, user=_admin_actor(), tenant=tenant_a))
    assert res["pending_invitations_deleted"] == 0


def test_hard_delete_in_progress_jobs_logs_error_but_still_deletes(
    tenant_a, caplog,
):
    """status=in_progress → ERROR log surfaced, tech still deleted."""
    from routers.technicians import hard_delete_technician
    _seed_admin_user(tenant_a["id"])
    tid, _uid = _seed_tech_with_user(tenant_a["id"])
    _seed_job(tenant_a["id"], tid, status="in_progress",
               scheduled_start=datetime.now(timezone.utc))
    caplog.set_level(logging.ERROR)
    res = _run(hard_delete_technician(
        tech_id=tid, user=_admin_actor(), tenant=tenant_a))
    assert res["deleted"] is True
    # ERROR log surfaced with the [p42] tag.
    err_lines = [rec.getMessage() for rec in caplog.records
                 if rec.levelno >= logging.ERROR
                 and "[p42]" in rec.getMessage()]
    assert err_lines, f"expected [p42] ERROR log, got: {caplog.text!r}"
    assert any("in_progress jobs count=1" in m for m in err_lines)


# ─────────────────────────────────────────────────────────────────────
# Tests — bulk hard delete
# ─────────────────────────────────────────────────────────────────────
def test_bulk_hard_delete_partial_success_reports_per_tech_shape(tenant_a):
    """Bulk with a mix of (own-valid + self + orphan-blocked) — the
    response reports each outcome so the FE can render a partial-
    success table."""
    from routers.technicians import (hard_delete_technicians_bulk,
                                       _TechniciansHardDeleteBulkIn)
    # Seed one extra admin so the "orphan" case below doesn't
    # accidentally succeed. But we WANT the orphan case, so we
    # keep the admin-tech-user as the last admin standing.
    _seed_admin_user(tenant_a["id"], uid="secondary-admin")
    tid_good, _uid_good = _seed_tech_with_user(tenant_a["id"])
    tid_self, uid_self = _seed_tech_with_user(tenant_a["id"])
    # Orphan case — remove the secondary admin so that tid_admin's
    # linked user (role=admin) is the last remaining admin.
    _run(_DB.users.delete_one({"id": "secondary-admin"}))
    tid_admin, _uid_admin = _seed_tech_with_user(
        tenant_a["id"], user_role="admin")
    # Caller is the self-target's linked user (technician_id set).
    caller = {"id": uid_self, "role": "admin",
              "email": f"{uid_self}@test", "technician_id": tid_self}
    body = _TechniciansHardDeleteBulkIn(
        ids=[tid_good, tid_self, tid_admin])
    res = _run(hard_delete_technicians_bulk(
        body=body, user=caller, tenant=tenant_a))
    assert res["requested_count"] == 3
    assert res["deleted_count"] == 1
    assert len(res["results"]) == 1
    assert res["results"][0]["tech_id"] == tid_good
    codes = {s["code"] for s in res["skipped"]}
    assert "cannot_delete_self" in codes
    assert "would_orphan_tenant_no_admin_remaining" in codes


def test_bulk_hard_delete_tenant_scoping_excludes_other_tenant_ids(
    tenant_a, tenant_b,
):
    from routers.technicians import (hard_delete_technicians_bulk,
                                       _TechniciansHardDeleteBulkIn)
    _seed_admin_user(tenant_a["id"])
    _seed_admin_user(tenant_b["id"])
    tid_b, _uid_b = _seed_tech_with_user(tenant_b["id"])
    body = _TechniciansHardDeleteBulkIn(ids=[tid_b])
    res = _run(hard_delete_technicians_bulk(
        body=body, user=_admin_actor(), tenant=tenant_a))
    assert res["deleted_count"] == 0
    assert res["not_found"] == [tid_b]
    # Tenant B row untouched.
    assert _run(_DB.technicians.find_one({"id": tid_b})) is not None


def test_bulk_hard_delete_dedupes_repeated_ids(tenant_a):
    from routers.technicians import (hard_delete_technicians_bulk,
                                       _TechniciansHardDeleteBulkIn)
    _seed_admin_user(tenant_a["id"])
    tid, _uid = _seed_tech_with_user(tenant_a["id"])
    body = _TechniciansHardDeleteBulkIn(ids=[tid, tid, tid])
    res = _run(hard_delete_technicians_bulk(
        body=body, user=_admin_actor(), tenant=tenant_a))
    # Requested count reflects what the caller sent; deleted_count
    # reflects the deduped work (single physical delete).
    assert res["requested_count"] == 3
    assert res["deleted_count"] == 1


def test_bulk_hard_delete_cap_at_500_returns_400_when_exceeded(tenant_a):
    from routers.technicians import (hard_delete_technicians_bulk,
                                       _TechniciansHardDeleteBulkIn)
    body = _TechniciansHardDeleteBulkIn(ids=[f"id-{i}" for i in range(501)])
    with pytest.raises(HTTPException) as exc:
        _run(hard_delete_technicians_bulk(
            body=body, user=_admin_actor(), tenant=tenant_a))
    assert exc.value.status_code == 400


def test_audit_snapshot_written_with_prior_status_and_linked_ids(tenant_a):
    """The forensic audit MUST include the tech snapshot, linked user
    snapshot, pending_invite_ids list, and unassigned-jobs count."""
    from routers.technicians import hard_delete_technician
    _seed_admin_user(tenant_a["id"])
    tid, uid = _seed_tech_with_user(tenant_a["id"])
    future = datetime.now(timezone.utc) + timedelta(days=1)
    _seed_job(tenant_a["id"], tid, status="pending",
               scheduled_start=future)
    res = _run(hard_delete_technician(
        tech_id=tid, user=_admin_actor(), tenant=tenant_a))
    audit = _run(_DB.audits.find_one({"id": res["audit_id"]}))
    assert audit is not None
    assert audit["kind"] == "technicians_hard_delete"
    assert audit["target_id"] == tid
    assert audit["tech_snapshot"]["id"] == tid
    assert audit["linked_user_snapshot"]["id"] == uid
    assert audit["pending_invite_ids"] == []
    assert audit["in_progress_job_count"] == 0
    assert audit["future_jobs_unassigned"] == 1
    assert audit["actor_user_id"] == "actor-admin"
