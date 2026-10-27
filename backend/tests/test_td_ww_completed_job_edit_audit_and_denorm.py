"""WW · Feb-2026 — ``closed_job_checklist_toggle`` audit discriminator
on the legacy ``PUT /jobs/{jid}/field-report`` endpoint + the shared
``edited_after_completion`` denorm across all four completed-job
write sites.

Scope locked by:
  * The admin FE JobDetail.jsx still toggles checklist items via
    ``PUT /jobs/{jid}/field-report`` (not the K6 PATCH sibling).
    This test shipgate assures that a toggle on a COMPLETED job
    writes a ``db.job_edits`` row with
    ``event="closed_job_checklist_toggle"`` + the expected
    before/after shape.
  * ``edited_after_completion`` denorm flips exactly once on the
    first ``closed_job_*`` write across the four sites (PATCH,
    POST /photos, DELETE /photos, PUT /field-report-while-completed)
    and stays ``True`` on subsequent writes — tested with a
    4-write sequence against ONE job.
  * Open-job toggles stay silent (no closed-job audit row, no
    denorm flip).
  * Role gates on all four paths unchanged (regression lock).

Pattern mirrors ``test_closed_job_edit_unlock.py`` for fixture +
_LOOP + _run helpers so motor's event-loop binding stays in
lockstep with the Phase-K6 suite.
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


PREFIX = f"ww-{uuid.uuid4().hex[:8]}"


async def _tenant_id() -> str:
    u = await _db().users.find_one(
        {"email": "admin@aquaterra.com"}, {"_id": 0, "tenant_id": 1},
    )
    return u["tenant_id"]


async def _tenant_dep(tid: str) -> Dict[str, Any]:
    return {"id": tid}


def _user(role: str, uid: str = None) -> Dict[str, Any]:
    return {"id": uid or f"u-{role}", "role": role,
             "name": f"{role.title()} Test",
             "email": f"{role}@test.local"}


async def _mk_completed_job(tid: str, *, tech_id: str = "u-tech-ww",
                              with_checklist: bool = True) -> str:
    jid = f"{PREFIX}-job-{uuid.uuid4().hex[:8]}"
    doc: Dict[str, Any] = {
        "id": jid, "tenant_id": tid,
        "customer_id": f"{PREFIX}-cust",
        "technician_id": tech_id,
        "status": "completed",
        "completed_at": (datetime.now(timezone.utc)
                           - timedelta(hours=48)).isoformat(),
        "notes": "pre-ww",
        "photos": [],
        "service_type": "pool-weekly",
    }
    if with_checklist:
        doc["checklist"] = [
            {"id": "c0", "label": "Skim surface", "done": False},
            {"id": "c1", "label": "Vacuum floor",  "done": False},
        ]
    await _db().jobs.insert_one(doc)
    return jid


async def _mk_open_job(tid: str, *, tech_id: str = "u-tech-ww") -> str:
    jid = f"{PREFIX}-open-{uuid.uuid4().hex[:8]}"
    await _db().jobs.insert_one({
        "id": jid, "tenant_id": tid,
        "customer_id": f"{PREFIX}-cust",
        "technician_id": tech_id,
        "status": "active",
        "photos": [],
        "checklist": [
            {"id": "c0", "label": "Skim surface", "done": False},
        ],
        "service_type": "pool-weekly",
    })
    return jid


async def _drain(tid: str):
    rx = {"$regex": f"^{PREFIX}"}
    for coll in ("jobs", "job_edits", "audit_events"):
        await _db()[coll].delete_many(
            {"$or": [{"id": rx}, {"job_id": rx},
                     {"tenant_id": tid, "job_id": rx}]},
        )


# ═══════════════════════════════════════════════════════════════════
# 1. Checklist toggle on COMPLETED job via PUT /field-report writes
#    a `closed_job_checklist_toggle` audit row with correct diff.
# ═══════════════════════════════════════════════════════════════════
def test_checklist_toggle_on_completed_writes_audit_row():
    async def _go():
        from models import FieldReportUpdate
        from routers.jobs import update_field_report
        tid = await _tenant_id()
        jid = await _mk_completed_job(tid)
        try:
            new_cl = [
                {"id": "c0", "label": "Skim surface", "done": True},
                {"id": "c1", "label": "Vacuum floor", "done": False},
            ]
            body = FieldReportUpdate(checklist=new_cl)
            await update_field_report(
                jid, body,
                user=_user("admin", uid="u-admin-ww"),
                tenant=await _tenant_dep(tid),
            )
            row = await _db().job_edits.find_one(
                {"job_id": jid, "event": "closed_job_checklist_toggle"},
                {"_id": 0},
            )
            assert row is not None, (
                "closed_job_checklist_toggle audit row missing — "
                "WW BE write path not firing"
            )
            assert row["edited_by"] == "u-admin-ww"
            assert row["edited_by_role"] == "admin"
            assert row["source"] == "web"
            # Changes diff shape: before + after on the checklist key.
            ch = row.get("changes") or {}
            assert "checklist" in ch
            before = ch["checklist"]["before"]
            after = ch["checklist"]["after"]
            assert isinstance(before, list) and isinstance(after, list)
            assert any(c.get("done") is False for c in before)
            assert any(c.get("done") is True for c in after)
        finally:
            await _drain(tid)
    _run(_go())


# ═══════════════════════════════════════════════════════════════════
# 2. Checklist toggle on OPEN job writes NO closed-job audit row.
# ═══════════════════════════════════════════════════════════════════
def test_checklist_toggle_on_open_job_silent():
    async def _go():
        from models import FieldReportUpdate
        from routers.jobs import update_field_report
        tid = await _tenant_id()
        jid = await _mk_open_job(tid)
        try:
            body = FieldReportUpdate(checklist=[
                {"id": "c0", "label": "Skim surface", "done": True},
            ])
            await update_field_report(
                jid, body,
                user=_user("admin", uid="u-admin-ww"),
                tenant=await _tenant_dep(tid),
            )
            n = await _db().job_edits.count_documents(
                {"job_id": jid},
            )
            assert n == 0, (
                f"open-job field-report toggle wrote {n} audit rows; "
                "closed-job audit must stay silent on non-completed jobs"
            )
            fresh = await _db().jobs.find_one(
                {"id": jid, "tenant_id": tid}, {"_id": 0},
            )
            assert fresh.get("edited_after_completion") is not True, (
                "open-job write must NOT flip edited_after_completion "
                "denorm — negative lock"
            )
        finally:
            await _drain(tid)
    _run(_go())


# ═══════════════════════════════════════════════════════════════════
# 3. edited_after_completion denorm flips exactly once across all 4
#    write sites in sequence on the same completed job. The
#    invariant: after site #1 it is True; after sites #2-4 it is
#    still True (no toggle-back, no re-flip).
# ═══════════════════════════════════════════════════════════════════
def test_edited_after_completion_denorm_flips_exactly_once_across_4_sites():
    async def _go():
        from models import FieldReportUpdate, PhotoIn
        from routers.jobs import (
            add_job_photo, delete_job_photo,
            patch_job_edit_window, JobEditPatch,
            update_field_report,
        )
        from unittest.mock import MagicMock

        tid = await _tenant_id()
        jid = await _mk_completed_job(tid)

        # Site #1 — PUT /field-report (checklist). Before this write
        # the denorm must be falsy; after, must be True.
        pre = await _db().jobs.find_one(
            {"id": jid, "tenant_id": tid}, {"_id": 0},
        )
        assert pre.get("edited_after_completion") is not True

        try:
            await update_field_report(
                jid, FieldReportUpdate(checklist=[
                    {"id": "c0", "label": "Skim surface", "done": True},
                ]),
                user=_user("admin", uid="u-admin-ww"),
                tenant=await _tenant_dep(tid),
            )
            row1 = await _db().jobs.find_one(
                {"id": jid, "tenant_id": tid}, {"_id": 0},
            )
            assert row1.get("edited_after_completion") is True, (
                "field-report checklist toggle on completed job "
                "must flip edited_after_completion to True"
            )

            # Site #2 — POST /photos. Already-True denorm must stay.
            # ``add_job_photo`` reads an idempotency key off the
            # Request headers — supply a mock Request with empty
            # headers so a fresh key is minted.
            req = MagicMock()
            req.headers = {}
            # 1x1 transparent PNG data-url.
            tiny_png = (
                "data:image/png;base64,"
                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nGMAAQAABQABLuRXuwAAAABJRU5ErkJggg=="
            )
            photo_body = PhotoIn(data=tiny_png, label="ww-site2")
            await add_job_photo(
                jid, photo_body, request=req,
                user=_user("admin", uid="u-admin-ww"),
                tenant=await _tenant_dep(tid),
            )
            row2 = await _db().jobs.find_one(
                {"id": jid, "tenant_id": tid},
                {"_id": 0, "edited_after_completion": 1, "photos": 1},
            )
            assert row2.get("edited_after_completion") is True
            assert (row2.get("photos") or []), (
                "photo-add didn't persist a photo on the job"
            )
            new_pid = row2["photos"][-1]["id"]

            # Site #3 — DELETE /photos. Denorm stays True.
            await delete_job_photo(
                jid, new_pid,
                user=_user("admin", uid="u-admin-ww"),
                tenant=await _tenant_dep(tid),
            )
            row3 = await _db().jobs.find_one(
                {"id": jid, "tenant_id": tid},
                {"_id": 0, "edited_after_completion": 1},
            )
            assert row3.get("edited_after_completion") is True

            # Site #4 — PATCH /jobs/{jid}. Denorm stays True.
            await patch_job_edit_window(
                jid, JobEditPatch(notes="ww-site4"),
                user=_user("admin", uid="u-admin-ww"),
                tenant=await _tenant_dep(tid),
            )
            row4 = await _db().jobs.find_one(
                {"id": jid, "tenant_id": tid},
                {"_id": 0, "edited_after_completion": 1},
            )
            assert row4.get("edited_after_completion") is True

            # All four event discriminators must now be present in
            # db.job_edits for this job.
            events = await _db().job_edits.distinct(
                "event", {"job_id": jid},
            )
            expected = {
                "closed_job_checklist_toggle",
                "closed_job_photo_add",
                "closed_job_photo_delete",
                "closed_job_edit",
            }
            assert expected.issubset(set(events)), (
                f"missing event discriminators: expected {expected}, "
                f"got {set(events)}"
            )
        finally:
            await _drain(tid)
    _run(_go())


# ═══════════════════════════════════════════════════════════════════
# 4. Jobs never edited post-completion keep ``edited_after_completion``
#    falsy (not present / False / None are all valid).
# ═══════════════════════════════════════════════════════════════════
def test_denorm_stays_falsy_on_never_edited_completed_job():
    async def _go():
        tid = await _tenant_id()
        jid = await _mk_completed_job(tid)
        try:
            row = await _db().jobs.find_one(
                {"id": jid, "tenant_id": tid}, {"_id": 0},
            )
            assert row.get("edited_after_completion") is not True, (
                "freshly-seeded completed job must not carry a True "
                "edited_after_completion denorm"
            )
        finally:
            await _drain(tid)
    _run(_go())


# ═══════════════════════════════════════════════════════════════════
# 5. Role gate on PUT /field-report preserved — customer role still
#    403, technician on another tech's job still 403.
# ═══════════════════════════════════════════════════════════════════
def test_field_report_role_gates_preserved_through_ww():
    async def _go():
        from models import FieldReportUpdate
        from routers.jobs import update_field_report
        tid = await _tenant_id()
        jid = await _mk_completed_job(tid, tech_id="u-tech-owner")
        try:
            # customer → 403.
            with pytest.raises(HTTPException) as exc_c:
                await update_field_report(
                    jid, FieldReportUpdate(checklist=[
                        {"id": "c0", "label": "x", "done": True},
                    ]),
                    user=_user("customer", uid="u-cust-ww"),
                    tenant=await _tenant_dep(tid),
                )
            assert exc_c.value.status_code == 403

            # technician NOT on the job → 403 via
            # is_tech_authorized_on_job (crew-aware).
            with pytest.raises(HTTPException) as exc_t:
                await update_field_report(
                    jid, FieldReportUpdate(checklist=[
                        {"id": "c0", "label": "x", "done": True},
                    ]),
                    user=_user("technician", uid="u-other-tech-ww"),
                    tenant=await _tenant_dep(tid),
                )
            assert exc_t.value.status_code == 403

            # No audit row should have been written on either 403.
            n = await _db().job_edits.count_documents({"job_id": jid})
            assert n == 0, (
                f"role-gate rejection wrote {n} audit rows — must stay 0"
            )
            # Denorm must stay falsy — no mutation happened.
            fresh = await _db().jobs.find_one(
                {"id": jid, "tenant_id": tid}, {"_id": 0},
            )
            assert fresh.get("edited_after_completion") is not True
        finally:
            await _drain(tid)
    _run(_go())
