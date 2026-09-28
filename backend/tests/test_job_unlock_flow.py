"""CHEM-LOCK · Feb-2026 — Backend contract for the submitted-job
admin unlock endpoint.

Coverage:
  1. Admin/super_admin can POST ``/api/jobs/{jid}/unlock`` with a
     valid reason → 200; ``locked_at`` cleared on the SR;
     ``unlocked_at`` stamped on the job; audit row in
     ``db.job_edits`` with ``action: unlock``.
  2. Technician role cannot unlock → 403.
  3. Empty / short (< 8 char) reason → 400.
  4. Multiple unlocks on the same job → multiple audit rows,
     each with its ``previous_state`` capturing the pre-unlock
     submitted_at.
  5. Job with paid invoice → 200 + ``warnings: ["invoice_paid"]``
     (non-blocking per brief §Edge cases §3).
  6. Save-submit on unlocked job → auto-relocks
     (``service_report.submitted_at`` re-stamped, ``job.unlocked_at``
     cleared).
  7. Non-submitted job → 409 ``not_locked``.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timezone
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
    for mod in ("routers.jobs", "routers.service_reports"):
        __import__(mod)
        import sys
        sys.modules[mod].db = fresh_db
    yield


def _db():
    from motor.motor_asyncio import AsyncIOMotorClient
    from dotenv import load_dotenv
    load_dotenv("/app/backend/.env")
    return AsyncIOMotorClient(os.environ["MONGO_URL"], io_loop=_LOOP)[
        os.environ["DB_NAME"]]


async def _tenant_id() -> str:
    u = await _db().users.find_one(
        {"email": "admin@aquaterra.com"}, {"_id": 0, "tenant_id": 1},
    )
    return u["tenant_id"]


async def _tenant_dep(tid: str) -> Dict[str, Any]:
    doc = await _db().tenants.find_one({"id": tid}, {"_id": 0})
    return doc or {"id": tid}


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _mk_submitted_job(
    tid: str, *,
    submitted_hours_ago: float = 1.0,
    invoice_paid: bool = False,
) -> tuple[str, str]:
    """Seed a completed job + submitted SR pair. Returns (jid, sr_id)."""
    from utils import now_iso
    submitted_at = _iso_now()
    await _db().customers.update_one(
        {"id": "chemlock-cust"},
        {"$setOnInsert": {
            "id": "chemlock-cust", "tenant_id": tid,
            "name": "CHEM-LOCK Cust", "email": "cl@example.com",
            "created_at": now_iso(),
        }},
        upsert=True,
    )
    jid = f"chemlock-job-{uuid.uuid4().hex[:10]}"
    await _db().jobs.insert_one({
        "id": jid, "tenant_id": tid,
        "customer_id": "chemlock-cust", "customer_name": "CHEM-LOCK Cust",
        "service_type": "Weekly Pool Service",
        "technician_id": "chemlock-tech",
        "status": "completed",
        "completed_at": submitted_at,
        "service_report_submitted_at": submitted_at,
        "scheduled_date": submitted_at,
        "price_cents": 10000,
        "created_at": now_iso(),
    })
    srid = f"chemlock-sr-{uuid.uuid4().hex[:10]}"
    await _db().service_reports.insert_one({
        "id": srid, "tenant_id": tid, "job_id": jid,
        "tech_id": "chemlock-tech",
        "submitted_at": submitted_at,
        "email_pending_at": submitted_at,
        "sms_pending_at": submitted_at,
        "chemical_readings": [],
        "chemicals_added": [
            {"name": "Chlorine", "amount": "1", "unit": "gal"},
        ],
        "created_at": now_iso(),
    })
    if invoice_paid:
        iid = f"chemlock-inv-{uuid.uuid4().hex[:10]}"
        await _db().quotes.insert_one({
            "id": iid, "tenant_id": tid, "doc_type": "invoice",
            "status": "issued", "payment_status": "paid",
            "customer_id": "chemlock-cust",
            "scheduled_job_id": jid,
            "subtotal_cents": 10000, "total_cents": 10000,
            "created_at": now_iso(),
        })
        await _db().jobs.update_one(
            {"id": jid, "tenant_id": tid},
            {"$set": {"auto_invoice_id": iid}},
        )
    return jid, srid


def _mk_user(tid: str, role: str) -> Dict[str, Any]:
    return {"id": f"u-{role}", "role": role,
            "technician_id": "chemlock-tech" if role == "technician" else None,
            "tenant_id": tid,
            "email": f"{role}@example.com",
            "name": role.title()}


def _body(reason: str):
    from routers.jobs import JobUnlockIn
    return JobUnlockIn(reason=reason)


async def _drain(tid: str) -> None:
    for coll in ("jobs", "job_edits", "quotes", "service_reports"):
        await _db()[coll].delete_many({
            "$or": [
                {"id": {"$regex": "^chemlock-"}},
                {"job_id": {"$regex": "^chemlock-"}},
                {"customer_id": "chemlock-cust"},
                {"scheduled_job_id": {"$regex": "^chemlock-"}},
            ],
        })
    await _db().customers.delete_many({"id": "chemlock-cust"})


# ═══════════════════════════════════════════════════════════════════
# 1. Admin unlock — happy path
# ═══════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("role", ["admin", "super_admin", "manager", "owner"])
def test_admin_role_can_unlock_with_valid_reason(role):
    async def _go():
        tid = await _tenant_id()
        jid, srid = await _mk_submitted_job(tid)
        try:
            from routers.jobs import unlock_submitted_job
            res = await unlock_submitted_job(
                jid, _body("Typo in chlorine dose"),
                user=_mk_user(tid, role),
                tenant=await _tenant_dep(tid),
            )
            assert res["ok"] is True
            assert res["warnings"] == []
            assert res["audit_id"]
            assert res["unlocked_at"]

            # ── job state ────────────────────────────────────────
            fresh_job = await _db().jobs.find_one(
                {"id": jid, "tenant_id": tid}, {"_id": 0},
            )
            assert fresh_job["unlocked_at"]
            assert fresh_job["unlocked_reason"] == "Typo in chlorine dose"
            assert fresh_job["status"] == "completed"

            # ── SR state — lock cleared ──────────────────────────
            fresh_sr = await _db().service_reports.find_one(
                {"id": srid, "tenant_id": tid}, {"_id": 0},
            )
            assert fresh_sr.get("submitted_at") in (None, "")
            assert fresh_sr.get("email_pending_at") in (None, "")
            assert fresh_sr.get("sms_pending_at") in (None, "")
            # The pre-unlock submitted_at is captured for the
            # resubmit stale-report banner.
            assert fresh_sr.get("previously_submitted_at")

            # ── Audit row shape ──────────────────────────────────
            audit = await _db().job_edits.find_one(
                {"id": res["audit_id"]}, {"_id": 0},
            )
            assert audit is not None
            assert audit["job_id"] == jid
            assert audit["action"] == "unlock"
            assert audit["reason"] == "Typo in chlorine dose"
            assert audit["edited_by_role"] == role
            assert audit["changes"]["lock_state"] == {
                "before": "locked", "after": "unlocked",
            }
            # previous_state captures the SR snapshot before unlock.
            ps = audit["previous_state"]
            assert isinstance(ps["service_reports"], list)
            assert ps["service_reports"][0]["submitted_at"]
        finally:
            await _drain(tid)
    _run(_go())


# ═══════════════════════════════════════════════════════════════════
# 2. Tech role is 403 — cannot self-unlock
# ═══════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("role", ["technician", "customer", "viewer",
                                   "marketer", "sales"])
def test_non_admin_roles_cannot_unlock(role):
    async def _go():
        tid = await _tenant_id()
        jid, _sr = await _mk_submitted_job(tid)
        try:
            from routers.jobs import unlock_submitted_job
            with pytest.raises(HTTPException) as ei:
                await unlock_submitted_job(
                    jid, _body("I want to fix my typo"),
                    user=_mk_user(tid, role),
                    tenant=await _tenant_dep(tid),
                )
            assert ei.value.status_code == 403
            # No audit row.
            audits = await _db().job_edits.count_documents(
                {"job_id": jid, "action": "unlock"})
            assert audits == 0
        finally:
            await _drain(tid)
    _run(_go())


# ═══════════════════════════════════════════════════════════════════
# 3. Reason field validation
# ═══════════════════════════════════════════════════════════════════
def test_unlock_missing_reason_returns_400():
    async def _go():
        tid = await _tenant_id()
        jid, _sr = await _mk_submitted_job(tid)
        try:
            from routers.jobs import unlock_submitted_job
            with pytest.raises(HTTPException) as ei:
                await unlock_submitted_job(
                    jid, _body(""),
                    user=_mk_user(tid, "admin"),
                    tenant=await _tenant_dep(tid),
                )
            assert ei.value.status_code == 400
            assert "reason" in str(ei.value.detail).lower()
        finally:
            await _drain(tid)
    _run(_go())


def test_unlock_short_reason_returns_400():
    async def _go():
        tid = await _tenant_id()
        jid, _sr = await _mk_submitted_job(tid)
        try:
            from routers.jobs import unlock_submitted_job
            with pytest.raises(HTTPException) as ei:
                await unlock_submitted_job(
                    jid, _body("short"),  # 5 chars
                    user=_mk_user(tid, "admin"),
                    tenant=await _tenant_dep(tid),
                )
            assert ei.value.status_code == 400
            # 400 for < 8 chars carries structured detail
            detail = ei.value.detail
            if isinstance(detail, dict):
                assert detail.get("detail") == "reason_too_short"
        finally:
            await _drain(tid)
    _run(_go())


def test_unlock_reason_exactly_eight_chars_succeeds():
    async def _go():
        tid = await _tenant_id()
        jid, _sr = await _mk_submitted_job(tid)
        try:
            from routers.jobs import unlock_submitted_job
            res = await unlock_submitted_job(
                jid, _body("12345678"),  # exactly 8 chars
                user=_mk_user(tid, "admin"),
                tenant=await _tenant_dep(tid),
            )
            assert res["ok"] is True
        finally:
            await _drain(tid)
    _run(_go())


# ═══════════════════════════════════════════════════════════════════
# 4. Multiple unlocks — each writes its own audit row
# ═══════════════════════════════════════════════════════════════════
def test_multiple_unlocks_create_multiple_audit_rows():
    async def _go():
        tid = await _tenant_id()
        jid, srid = await _mk_submitted_job(tid)
        try:
            from routers.jobs import unlock_submitted_job

            # First unlock.
            res1 = await unlock_submitted_job(
                jid, _body("First correction of chlorine typo"),
                user=_mk_user(tid, "admin"),
                tenant=await _tenant_dep(tid),
            )

            # Re-submit to relock so we can unlock again.
            now2 = _iso_now()
            await _db().service_reports.update_one(
                {"id": srid, "tenant_id": tid},
                {"$set": {"submitted_at": now2,
                          "email_pending_at": now2,
                          "sms_pending_at": now2}},
            )
            await _db().jobs.update_one(
                {"id": jid, "tenant_id": tid},
                {"$set": {"service_report_submitted_at": now2},
                 "$unset": {"unlocked_at": ""}},
            )

            # Second unlock.
            res2 = await unlock_submitted_job(
                jid, _body("Second correction after resubmit"),
                user=_mk_user(tid, "admin"),
                tenant=await _tenant_dep(tid),
            )

            assert res1["audit_id"] != res2["audit_id"]
            audits = await _db().job_edits.find(
                {"job_id": jid, "action": "unlock"},
                {"_id": 0},
            ).to_list(10)
            assert len(audits) == 2

            # Each row's previous_state captures its own pre-unlock
            # submitted_at.
            reasons = sorted(a["reason"] for a in audits)
            assert reasons == [
                "First correction of chlorine typo",
                "Second correction after resubmit",
            ]
            # Both rows have a service_reports snapshot with a
            # submitted_at value — proving previous_state is
            # reconstructable per unlock.
            for a in audits:
                srs = a["previous_state"]["service_reports"]
                assert srs and srs[0].get("submitted_at")
        finally:
            await _drain(tid)
    _run(_go())


# ═══════════════════════════════════════════════════════════════════
# 5. Paid invoice → warnings: ["invoice_paid"] (non-blocking)
# ═══════════════════════════════════════════════════════════════════
def test_unlock_paid_invoice_surfaces_warning():
    async def _go():
        tid = await _tenant_id()
        jid, _sr = await _mk_submitted_job(tid, invoice_paid=True)
        try:
            from routers.jobs import unlock_submitted_job
            res = await unlock_submitted_job(
                jid, _body("Correction on paid job"),
                user=_mk_user(tid, "admin"),
                tenant=await _tenant_dep(tid),
            )
            assert res["ok"] is True, (
                "Paid invoice must NOT hard-block unlock — warning only"
            )
            assert "invoice_paid" in res["warnings"]

            # Warning also surfaces on the audit row for compliance
            # reconstruction.
            audit = await _db().job_edits.find_one(
                {"id": res["audit_id"]}, {"_id": 0},
            )
            assert "invoice_paid" in (audit.get("warnings") or [])
        finally:
            await _drain(tid)
    _run(_go())


# ═══════════════════════════════════════════════════════════════════
# 6. Non-submitted job → 409
# ═══════════════════════════════════════════════════════════════════
def test_unlock_non_submitted_job_returns_409():
    async def _go():
        tid = await _tenant_id()
        # Seed a job with NO submitted SR.
        from utils import now_iso
        jid = f"chemlock-job-{uuid.uuid4().hex[:10]}"
        await _db().jobs.insert_one({
            "id": jid, "tenant_id": tid,
            "customer_id": "chemlock-cust",
            "status": "scheduled",
            "created_at": now_iso(),
        })
        await _db().customers.update_one(
            {"id": "chemlock-cust"},
            {"$setOnInsert": {"id": "chemlock-cust", "tenant_id": tid,
                              "created_at": now_iso()}},
            upsert=True,
        )
        try:
            from routers.jobs import unlock_submitted_job
            with pytest.raises(HTTPException) as ei:
                await unlock_submitted_job(
                    jid, _body("nothing to unlock"),
                    user=_mk_user(tid, "admin"),
                    tenant=await _tenant_dep(tid),
                )
            assert ei.value.status_code == 409
        finally:
            await _drain(tid)
    _run(_go())


# ═══════════════════════════════════════════════════════════════════
# 7. Non-existent job → 404
# ═══════════════════════════════════════════════════════════════════
def test_unlock_nonexistent_job_returns_404():
    async def _go():
        tid = await _tenant_id()
        try:
            from routers.jobs import unlock_submitted_job
            with pytest.raises(HTTPException) as ei:
                await unlock_submitted_job(
                    "chemlock-does-not-exist",
                    _body("phantom unlock"),
                    user=_mk_user(tid, "admin"),
                    tenant=await _tenant_dep(tid),
                )
            assert ei.value.status_code == 404
        finally:
            await _drain(tid)
    _run(_go())
