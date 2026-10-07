"""CLOSED-JOB-EDIT-UNLOCK · Feb-2026 — pytest end-to-end.

Phase B of CLOSED-JOB-EDIT-UNLOCK lifts the 24h post-completion
edit window.  All six K6 staff roles can edit a completed job
regardless of elapsed time; the ``employee`` role is included
forward-compat.  Audit trail (``db.job_edits``) stays authoritative.

Scope locked by:
  * is_within_edit_window → True for ``status=completed``
    (regardless of elapsed time)
  * K6_UNLOCK_ROLES += "employee"
  * ``patch_job_edit_window`` audit row tagged
    ``event="closed_job_edit"``
  * Photo add on completed job → new audit row
    ``event="closed_job_photo_add"``
  * Photo delete on completed job → new audit row
    ``event="closed_job_photo_delete"``
  * Role gate (``_authorize_edit``) + immutable-field guard
    (``IMMUTABLE_FIELDS``) remain untouched.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

import pytest
from fastapi import HTTPException


_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)


def _run(coro):
    return _LOOP.run_until_complete(coro)


@pytest.fixture(scope="module", autouse=True)
def _bind_db():
    from motor.motor_asyncio import AsyncIOMotorClient
    from dotenv import load_dotenv
    load_dotenv("/app/backend/.env")
    fresh = AsyncIOMotorClient(os.environ["MONGO_URL"], io_loop=_LOOP)
    fresh_db = fresh[os.environ["DB_NAME"]]
    import config as _cfg
    _cfg.db = fresh_db
    for mod in ("routers.jobs", "routers.mobile_sync"):
        __import__(mod)
        import sys
        sys.modules[mod].db = fresh_db
    yield


def _db():
    from motor.motor_asyncio import AsyncIOMotorClient
    from dotenv import load_dotenv
    load_dotenv("/app/backend/.env")
    return AsyncIOMotorClient(
        os.environ["MONGO_URL"], io_loop=_LOOP,
    )[os.environ["DB_NAME"]]


PREFIX = f"cjeu-{uuid.uuid4().hex[:8]}"


async def _tenant_id() -> str:
    u = await _db().users.find_one(
        {"email": "admin@aquaterra.com"}, {"_id": 0, "tenant_id": 1},
    )
    return u["tenant_id"]


async def _tenant_dep(tid: str) -> Dict[str, Any]:
    return {"id": tid}


async def _mk_completed_job(tid: str, *, completed_hours_ago: float = 48.0,
                               tech_id: str = "u-tech-k6") -> str:
    jid = f"{PREFIX}-job-{uuid.uuid4().hex[:8]}"
    completed_at = (datetime.now(timezone.utc)
                       - timedelta(hours=completed_hours_ago)).isoformat()
    await _db().jobs.insert_one({
        "id": jid, "tenant_id": tid,
        "customer_id": f"{PREFIX}-cust",
        "technician_id": tech_id,
        "status": "completed",
        "completed_at": completed_at,
        "notes": "pre-fix",
        "photos": [],
        "service_type": "pool-weekly",
    })
    return jid


async def _drain(tid: str):
    rx = {"$regex": f"^{PREFIX}"}
    for coll in ("jobs", "job_edits", "audit_events"):
        await _db()[coll].delete_many(
            {"$or": [{"id": rx}, {"job_id": rx}, {"tenant_id": tid, "job_id": rx}]},
        )


def _user(role: str, uid: str = None) -> Dict[str, Any]:
    return {"id": uid or f"u-{role}", "role": role,
             "name": f"{role.title()} Test",
             "email": f"{role}@test.local"}


def _patch_body(**kw):
    from routers.jobs import JobEditPatch
    return JobEditPatch(**kw)


# ═══════════════════════════════════════════════════════════════════
# 1. is_within_edit_window — now True for completed jobs regardless
#    of elapsed time (CORE semantic change).
# ═══════════════════════════════════════════════════════════════════
def test_is_within_edit_window_true_for_long_completed_jobs():
    """Pure-unit test on the gate helper — no DB touch."""
    from services.edit_window import is_within_edit_window
    far_past = (datetime.now(timezone.utc)
                   - timedelta(days=90)).isoformat()
    assert is_within_edit_window(
        {"status": "completed", "completed_at": far_past},
    ) is True


def test_is_within_edit_window_false_for_non_completed():
    from services.edit_window import is_within_edit_window
    assert is_within_edit_window(
        {"status": "in_progress",
         "completed_at": datetime.now(timezone.utc).isoformat()},
    ) is False


def test_is_within_edit_window_false_on_missing_completed_at():
    from services.edit_window import is_within_edit_window
    assert is_within_edit_window(
        {"status": "completed"},
    ) is False


# ═══════════════════════════════════════════════════════════════════
# 2. All five staff roles that ``_authorize_edit`` already permits
#    (admin / super_admin / manager / technician / owner) can edit
#    a 48h-old completed job.  The role gate stays active — the
#    SEMANTIC change here is "no 24h window", not "widen the role
#    gate".  "employee" is K6-forward-compat (G2=B) and gets its
#    own test below locking the "zero behavioural impact at ship
#    time" contract.
# ═══════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("role", [
    "admin", "super_admin", "manager", "technician", "owner",
])
def test_staff_roles_edit_completed_job_past_window(role):
    async def _go():
        tid = await _tenant_id()
        jid = await _mk_completed_job(tid, tech_id=f"u-{role}")
        try:
            from routers.jobs import patch_job_edit_window
            body = _patch_body(notes=f"edit-by-{role}",
                                   edit_reason=f"test {role} unlock")
            fresh = await patch_job_edit_window(
                jid, body, user=_user(role, uid=f"u-{role}"),
                tenant=await _tenant_dep(tid),
            )
            assert fresh["notes"] == f"edit-by-{role}"
            # Audit row with the new event tag landed.
            row = await _db().job_edits.find_one(
                {"tenant_id": tid, "job_id": jid}, {"_id": 0},
            )
            assert row is not None
            assert row["event"] == "closed_job_edit", (
                f"role={role} missing event tag"
            )
            assert row["edited_by_role"] == role
        finally:
            await _drain(tid)

    _run(_go())


# ═══════════════════════════════════════════════════════════════════
# 2b. "employee" is in K6_UNLOCK_ROLES (forward-compat ) but still
#     blocked by ``_authorize_edit`` — the "zero behavioural impact
#     until seeded" contract from G2=B.  When the staff-role
#     expansion lands and ``_authorize_edit`` adds "employee" to its
#     allowlist, this test flips to expect success.
# ═══════════════════════════════════════════════════════════════════
def test_employee_role_still_403_at_authorize_edit():
    async def _go():
        tid = await _tenant_id()
        jid = await _mk_completed_job(tid)
        try:
            from routers.jobs import patch_job_edit_window
            body = _patch_body(notes="employee-edit")
            with pytest.raises(HTTPException) as ei:
                await patch_job_edit_window(
                    jid, body, user=_user("employee"),
                    tenant=await _tenant_dep(tid),
                )
            # ``_authorize_edit`` fails FIRST — role not in the
            # allowed set yet.  CLOSED-JOB-EDIT-UNLOCK didn't widen
            # ``_authorize_edit``, only ``K6_UNLOCK_ROLES``.
            assert ei.value.status_code == 403
            assert "Not permitted to edit jobs" in str(ei.value.detail)
        finally:
            await _drain(tid)

    _run(_go())


# ═══════════════════════════════════════════════════════════════════
# 3. Customer / portal role still 403 — role gate stays active.
# ═══════════════════════════════════════════════════════════════════
def test_customer_still_403_on_edit():
    async def _go():
        tid = await _tenant_id()
        jid = await _mk_completed_job(tid)
        try:
            from routers.jobs import patch_job_edit_window
            body = _patch_body(notes="not-allowed")
            with pytest.raises(HTTPException) as ei:
                await patch_job_edit_window(
                    jid, body, user=_user("customer"),
                    tenant=await _tenant_dep(tid),
                )
            # 403 OR 404 depending on soft-delete visibility — both
            # fail-closed.  The _authorize_edit layer raises 403.
            assert ei.value.status_code in (403, 404)
        finally:
            await _drain(tid)

    _run(_go())


# ═══════════════════════════════════════════════════════════════════
# 4. IMMUTABLE_FIELDS guard still fires post-fix. Note that the
#    Pydantic ``JobEditPatch`` schema has ``extra='forbid'`` so a
#    hostile ``customer_id`` key wouldn't even reach the handler —
#    FastAPI's dep injection rejects it at parse time.  We exercise
#    the inner helper directly so the OTHER call-sites of the guard
#    (mobile-sync replay path) stay covered too.
# ═══════════════════════════════════════════════════════════════════
def test_immutable_field_guard_still_fires_on_closed_edit():
    from services.edit_window import (
        assert_immutable_fields_untouched, IMMUTABLE_FIELDS,
    )
    # Every immutable field must trip the guard.
    for field in IMMUTABLE_FIELDS:
        with pytest.raises(HTTPException) as ei:
            assert_immutable_fields_untouched({field: "x"})
        assert ei.value.status_code == 400
        assert ei.value.detail["detail"] == "immutable_field"
        assert ei.value.detail["field"] == field
    # Allowed fields pass through unchanged.
    assert_immutable_fields_untouched({"notes": "fine"})
    assert_immutable_fields_untouched({"chemical_readings": {"ph": 7.4}})


# ═══════════════════════════════════════════════════════════════════
# 5. Photo ADD on a completed job writes a ``closed_job_photo_add``
#    audit row with the hard-constraint shape.
# ═══════════════════════════════════════════════════════════════════
def test_photo_add_on_completed_writes_audit_row():
    async def _go():
        from fastapi import Request
        tid = await _tenant_id()
        jid = await _mk_completed_job(tid)
        try:
            from routers.jobs import add_job_photo
            from models import PhotoIn
            # Build a request stub with the headers scope that the
            # idempotency helper reads.
            scope = {"type": "http", "method": "POST", "headers": [],
                      "path": f"/jobs/{jid}/photos", "query_string": b""}
            request = Request(scope)
            body = PhotoIn(
                data="data:image/png;base64,"
                     + "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABAQMAAAAl21bKAAAAA1BMVEX///+nxBvIAAAAC0lEQVR42mNgAAIAAAUAAeImBMAAAAAASUVORK5CYII=",
                label="post-completion-add", client_uuid=None,
            )
            await add_job_photo(
                jid, body, request, user=_user("admin"),
                tenant=await _tenant_dep(tid),
            )
            row = await _db().job_edits.find_one(
                {"tenant_id": tid, "job_id": jid,
                 "event": "closed_job_photo_add"}, {"_id": 0},
            )
            assert row is not None
            # Shape contract (per CLOSED-JOB-EDIT-UNLOCK G4):
            for k in ("id", "tenant_id", "job_id", "event",
                      "edited_by", "edited_by_name", "edited_by_role",
                      "edited_at", "changes", "source"):
                assert k in row, f"audit row missing field {k!r}"
            assert row["edited_by_role"] == "admin"
            assert row["source"] == "web"
            assert "photos" in row["changes"]
            assert row["changes"]["photos"]["before"] is None
        finally:
            await _drain(tid)

    _run(_go())


# ═══════════════════════════════════════════════════════════════════
# 6. Photo ADD on an OPEN job stays silent (no audit row).
# ═══════════════════════════════════════════════════════════════════
def test_photo_add_on_open_job_does_not_write_audit_row():
    async def _go():
        from fastapi import Request
        tid = await _tenant_id()
        jid = f"{PREFIX}-open-{uuid.uuid4().hex[:8]}"
        await _db().jobs.insert_one({
            "id": jid, "tenant_id": tid,
            "customer_id": f"{PREFIX}-cust",
            "technician_id": "u-admin", "status": "in_progress",
            "photos": [],
        })
        try:
            from routers.jobs import add_job_photo
            from models import PhotoIn
            scope = {"type": "http", "method": "POST", "headers": [],
                      "path": f"/jobs/{jid}/photos", "query_string": b""}
            request = Request(scope)
            body = PhotoIn(
                data="data:image/png;base64,"
                     + "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABAQMAAAAl21bKAAAAA1BMVEX///+nxBvIAAAAC0lEQVR42mNgAAIAAAUAAeImBMAAAAAASUVORK5CYII=",
                label="open-add", client_uuid=None,
            )
            await add_job_photo(
                jid, body, request, user=_user("admin"),
                tenant=await _tenant_dep(tid),
            )
            n = await _db().job_edits.count_documents(
                {"tenant_id": tid, "job_id": jid,
                 "event": "closed_job_photo_add"},
            )
            assert n == 0, (
                "open-job photo adds must NOT write an audit row "
                "(prevents double-logging routine work)"
            )
        finally:
            await _drain(tid)

    _run(_go())


# ═══════════════════════════════════════════════════════════════════
# 7. Photo DELETE on a completed job writes a
#    ``closed_job_photo_delete`` audit row.
# ═══════════════════════════════════════════════════════════════════
def test_photo_delete_on_completed_writes_audit_row():
    async def _go():
        tid = await _tenant_id()
        jid = await _mk_completed_job(tid)
        photo_id = f"{PREFIX}-photo-{uuid.uuid4().hex[:6]}"
        # Seed a photo directly to avoid driving the add path again.
        await _db().jobs.update_one(
            {"id": jid, "tenant_id": tid},
            {"$push": {"photos": {"id": photo_id,
                                     "label": "seeded",
                                     "data": "data:image/png;base64,abc",
                                     "created_at": "2026-02-01T00:00:00Z"}}},
        )
        try:
            from routers.jobs import delete_job_photo
            await delete_job_photo(
                jid, photo_id, user=_user("manager"),
                tenant=await _tenant_dep(tid),
            )
            row = await _db().job_edits.find_one(
                {"tenant_id": tid, "job_id": jid,
                 "event": "closed_job_photo_delete"}, {"_id": 0},
            )
            assert row is not None
            for k in ("id", "tenant_id", "job_id", "event",
                      "edited_by", "edited_by_name", "edited_by_role",
                      "edited_at", "changes", "source"):
                assert k in row, f"audit row missing field {k!r}"
            assert row["edited_by_role"] == "manager"
            assert row["source"] == "web"
            assert row["changes"]["photos"]["before"] == {"id": photo_id}
            assert row["changes"]["photos"]["after"] is None
        finally:
            await _drain(tid)

    _run(_go())


# ═══════════════════════════════════════════════════════════════════
# 8. Photo DELETE on an OPEN job stays silent.
# ═══════════════════════════════════════════════════════════════════
def test_photo_delete_on_open_job_does_not_write_audit_row():
    async def _go():
        tid = await _tenant_id()
        jid = f"{PREFIX}-open-del-{uuid.uuid4().hex[:8]}"
        photo_id = f"{PREFIX}-ph-{uuid.uuid4().hex[:6]}"
        await _db().jobs.insert_one({
            "id": jid, "tenant_id": tid,
            "customer_id": f"{PREFIX}-cust", "status": "in_progress",
            "photos": [{"id": photo_id, "label": "x"}],
        })
        try:
            from routers.jobs import delete_job_photo
            await delete_job_photo(
                jid, photo_id, user=_user("admin"),
                tenant=await _tenant_dep(tid),
            )
            n = await _db().job_edits.count_documents(
                {"tenant_id": tid, "job_id": jid,
                 "event": "closed_job_photo_delete"},
            )
            assert n == 0
        finally:
            await _drain(tid)

    _run(_go())


# ═══════════════════════════════════════════════════════════════════
# 9. K6_UNLOCK_ROLES set now contains "employee" (forward-compat).
# ═══════════════════════════════════════════════════════════════════
def test_k6_unlock_roles_contains_employee():
    from services.edit_window import K6_UNLOCK_ROLES, role_bypasses_edit_window
    assert "employee" in K6_UNLOCK_ROLES
    assert role_bypasses_edit_window("employee") is True
    assert role_bypasses_edit_window("EMPLOYEE") is True
    # Non-staff roles still return False.
    assert role_bypasses_edit_window("customer") is False
    assert role_bypasses_edit_window("viewer") is False
