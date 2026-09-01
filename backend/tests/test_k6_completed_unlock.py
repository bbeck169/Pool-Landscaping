"""Phase K6 · Feb-2026 — Completed Job Unlock (Web).

Backend contract lock for the loosened post-completion edit path.

Coverage:
  1. K6 roles (super_admin / admin / manager / tech) can PATCH a
     completed job **past** the 24h window; audit trail fires.
  2. K6 roles can PATCH a completed job that's ALSO invoiced (paid
     linked invoice → 409 exact string; draft → 200 + recalc).
  3. Non-K6 roles remain blocked by ``_authorize_edit`` (403).
  4. Communication-timeline audit row shape (fields_changed +
     invoice_recalculated).
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
    for mod in ("routers.jobs", "routers.communication_timeline"):
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


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


async def _mk_completed_job(tid: str, *, hours_ago: float = 48.0,
                                     price_cents: int = 10000) -> str:
    from utils import now_iso
    # Seed the shared customer row once — the communication-timeline
    # router loads it to resolve email/phone aliases and returns 404
    # otherwise.
    await _db().customers.update_one(
        {"id": "cust-k6"},
        {"$setOnInsert": {
            "id": "cust-k6", "tenant_id": tid, "name": "K6 Cust",
            "email": "k6@example.com", "created_at": now_iso(),
        }},
        upsert=True,
    )
    jid = f"k6-job-{uuid.uuid4().hex[:10]}"
    completed_at = _iso(datetime.now(timezone.utc)
                          - timedelta(hours=hours_ago))
    await _db().jobs.insert_one({
        "id": jid, "tenant_id": tid,
        "customer_id": "cust-k6", "customer_name": "K6 Cust",
        "service_type": "Weekly Pool Service",
        "technician_id": "k6-tech",
        "status": "completed",
        "completed_at": completed_at,
        "scheduled_date": completed_at,
        "price_cents": price_cents,
        "created_at": now_iso(),
    })
    return jid


async def _mk_invoice(tid: str, *, job_id: str, status: str,
                             subtotal: float = 100.00,
                             payment_status: str = "unpaid") -> str:
    """Seed an invoice mirror with BOTH the legacy dollar fields
    AND the auto-invoice integer-cents fields so K6c recalc lands
    on the cents columns (matches services/auto_invoice.py schema)."""
    from utils import now_iso
    iid = f"k6-inv-{uuid.uuid4().hex[:10]}"
    subtotal_cents = int(round(subtotal * 100))
    await _db().quotes.insert_one({
        "id": iid, "tenant_id": tid, "doc_type": "invoice",
        "status": status, "payment_status": payment_status,
        "customer_id": "cust-k6",
        "scheduled_job_id": job_id,
        "subtotal_cents": subtotal_cents,
        "total_cents":    subtotal_cents,
        "subtotal": subtotal, "total_amount": subtotal, "total": subtotal,
        "created_at": now_iso(),
    })
    return iid


def _mk_user(tid: str, role: str) -> Dict[str, Any]:
    return {"id": f"u-{role}", "role": role,
            "technician_id": "k6-tech" if role == "technician" else None,
            "tenant_id": tid,
            "email": f"{role}@example.com",
            "name": role.title()}


def _patch(**kw):
    from routers.jobs import JobEditPatch
    return JobEditPatch(**kw)


async def _drain(tid: str) -> None:
    for coll in ("jobs", "job_edits", "quotes", "audit_events"):
        await _db()[coll].delete_many({
            "$or": [
                {"id": {"$regex": "^k6-"}},
                {"job_id": {"$regex": "^k6-"}},
                {"payload.job_id": {"$regex": "^k6-"}},
                {"customer_id": "cust-k6"},
                {"scheduled_job_id": {"$regex": "^k6-"}},
            ],
        })
    await _db().customers.delete_many({"id": "cust-k6"})


# ═══════════════════════════════════════════════════════════════════
# 1. K6 roles bypass the 24h window
# ═══════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("role", ["super_admin", "admin",
                                                    "manager", "technician"])
def test_k6_role_can_edit_past_24h_window(role):
    async def _go():
        tid = await _tenant_id()
        jid = await _mk_completed_job(tid, hours_ago=72.0)
        try:
            from routers.jobs import patch_job_edit_window
            fresh = await patch_job_edit_window(
                jid, _patch(notes=f"K6 · {role} late fix"),
                user=_mk_user(tid, role),
                tenant=await _tenant_dep(tid),
            )
            assert fresh["notes"] == f"K6 · {role} late fix"
            audit = await _db().audit_events.find_one(
                {"event_type": "job_edited_after_completion",
                 "payload.job_id": jid})
            assert audit is not None
            assert audit["payload"]["user_role"] == role
            assert "notes" in audit["payload"]["fields_changed"]
        finally:
            await _drain(tid)
    _run(_go())


# ═══════════════════════════════════════════════════════════════════
# 2. Non-K6 role is still 403 (customer / viewer / marketer)
# ═══════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("role", ["customer", "viewer", "marketer"])
def test_k6_non_allowed_role_still_403(role):
    async def _go():
        tid = await _tenant_id()
        jid = await _mk_completed_job(tid, hours_ago=1.0)
        try:
            from routers.jobs import patch_job_edit_window
            with pytest.raises(HTTPException) as ei:
                await patch_job_edit_window(
                    jid, _patch(notes="nope"),
                    user=_mk_user(tid, role),
                    tenant=await _tenant_dep(tid),
                )
            assert ei.value.status_code == 403
        finally:
            await _drain(tid)
    _run(_go())


# ═══════════════════════════════════════════════════════════════════
# 3. price_cents · no linked invoice → 200
# ═══════════════════════════════════════════════════════════════════
def test_k6_priced_field_no_invoice_allowed():
    async def _go():
        tid = await _tenant_id()
        jid = await _mk_completed_job(tid, hours_ago=48.0, price_cents=10000)
        try:
            from routers.jobs import patch_job_edit_window
            fresh = await patch_job_edit_window(
                jid, _patch(price_cents=15000),
                user=_mk_user(tid, "admin"),
                tenant=await _tenant_dep(tid),
            )
            assert fresh["price_cents"] == 15000
            audit = await _db().audit_events.find_one(
                {"event_type": "job_edited_after_completion",
                 "payload.job_id": jid})
            assert audit["payload"]["invoice_recalculated"] is False
        finally:
            await _drain(tid)
    _run(_go())


# ═══════════════════════════════════════════════════════════════════
# 4. price_cents · draft invoice → 200 + invoice total recalculated
# ═══════════════════════════════════════════════════════════════════
def test_k6_priced_field_draft_invoice_recalculates_total():
    async def _go():
        tid = await _tenant_id()
        jid = await _mk_completed_job(tid, hours_ago=48.0, price_cents=10000)
        iid = await _mk_invoice(tid, job_id=jid, status="draft",
                                     subtotal=100.00,
                                     payment_status="unpaid")
        try:
            from routers.jobs import patch_job_edit_window
            # Bump job price by +$50.00 (5000 cents delta).
            await patch_job_edit_window(
                jid, _patch(price_cents=15000),
                user=_mk_user(tid, "admin"),
                tenant=await _tenant_dep(tid),
            )
            inv = await _db().quotes.find_one({"id": iid})
            # K6c writes integer-cents fields; legacy dollar mirrors
            # are left untouched (services/auto_invoice.py doesn't
            # populate them either).
            assert inv["subtotal_cents"] == 15000, inv
            assert inv["total_cents"]    == 15000, inv
            assert inv["k6_last_recalc_delta_cents"] == 5000
            audit = await _db().audit_events.find_one(
                {"event_type": "job_edited_after_completion",
                 "payload.job_id": jid})
            assert audit["payload"]["invoice_recalculated"] is True
            assert audit["payload"]["invoice_id"] == iid
        finally:
            await _drain(tid)
    _run(_go())


# ═══════════════════════════════════════════════════════════════════
# 5. price_cents · paid invoice → 409 with exact error string
# ═══════════════════════════════════════════════════════════════════
def test_k6_priced_field_paid_invoice_blocks_409():
    async def _go():
        tid = await _tenant_id()
        jid = await _mk_completed_job(tid, hours_ago=48.0, price_cents=10000)
        iid = await _mk_invoice(tid, job_id=jid, status="issued",
                                     subtotal=100.00,
                                     payment_status="paid")
        try:
            from routers.jobs import patch_job_edit_window
            with pytest.raises(HTTPException) as ei:
                await patch_job_edit_window(
                    jid, _patch(price_cents=20000),
                    user=_mk_user(tid, "admin"),
                    tenant=await _tenant_dep(tid),
                )
            assert ei.value.status_code == 409
            detail = ei.value.detail
            assert detail["detail"] == "invoice_locked"
            expected = (
                f"Invoice {iid} is paid — void or refund the invoice "
                f"before editing priced fields on this completed job.")
            assert detail["message"] == expected
            # Job untouched — the 409 rolled back nothing because we
            # short-circuited BEFORE the audit + update writes.
            job = await _db().jobs.find_one({"id": jid})
            assert job["price_cents"] == 10000
            audit = await _db().audit_events.find_one(
                {"event_type": "job_edited_after_completion",
                 "payload.job_id": jid})
            assert audit is None
        finally:
            await _drain(tid)
    _run(_go())


# ═══════════════════════════════════════════════════════════════════
# 6. Timeline audit row shape — fields_changed + invoice_recalculated
# ═══════════════════════════════════════════════════════════════════
def test_k6_audit_row_shape_and_appears_on_communication_timeline():
    async def _go():
        tid = await _tenant_id()
        jid = await _mk_completed_job(tid, hours_ago=48.0, price_cents=10000)
        iid = await _mk_invoice(tid, job_id=jid, status="sent",
                                     subtotal=100.00)
        try:
            from routers.jobs import patch_job_edit_window
            await patch_job_edit_window(
                jid,
                _patch(notes="K6 · combined edit",
                          service_notes="K6 field note",
                          price_cents=12500),
                user=_mk_user(tid, "manager"),
                tenant=await _tenant_dep(tid),
            )
            audit = await _db().audit_events.find_one(
                {"event_type": "job_edited_after_completion",
                 "payload.job_id": jid})
            assert audit is not None
            p = audit["payload"]
            assert set(p["fields_changed"]) == {
                "notes", "service_notes", "price_cents"}
            assert p["invoice_recalculated"] is True
            assert p["invoice_id"] == iid
            assert p["user_role"] == "manager"
            # Belt-and-suspenders — never leak before/after values.
            row_dump = str(audit)
            assert "K6 · combined edit" not in row_dump
            assert "K6 field note"       not in row_dump

            # Timeline router surfaces the row under the customer.
            from routers.communication_timeline import (
                communication_timeline)
            resp = await communication_timeline(
                customer_id="cust-k6", limit=50, before=None, types=None,
                tenant=await _tenant_dep(tid),
                user=_mk_user(tid, "admin"),
            )
            job_edits = [i for i in resp["items"]
                              if i.get("type") == "job_edited"
                              and i.get("job_id") == jid]
            assert job_edits, resp
            item = job_edits[0]
            assert "Job edited after completion" == item["subject"]
            assert item["invoice_recalculated"] is True
            assert set(item["fields_changed"]) == {
                "notes", "service_notes", "price_cents"}
        finally:
            await _drain(tid)
    _run(_go())


# ═══════════════════════════════════════════════════════════════════
# 7. Regression guard — a role OUTSIDE the K6 unlock set + past the
#    24h window is stopped by ``_authorize_edit`` (not by the window
#    gate).  Belt-and-suspenders that the window gate still exists
#    for the rare surface where a non-K6 role does get here.
# ═══════════════════════════════════════════════════════════════════
def test_edit_window_still_blocks_non_k6_roles_outside_window():
    async def _go():
        tid = await _tenant_id()
        jid = await _mk_completed_job(tid, hours_ago=30.0)
        try:
            from routers.jobs import patch_job_edit_window
            with pytest.raises(HTTPException) as ei:
                await patch_job_edit_window(
                    jid, _patch(notes="x"),
                    user=_mk_user(tid, "customer"),
                    tenant=await _tenant_dep(tid),
                )
            # Customer role hits _authorize_edit first — that's fine,
            # both gates converge on 403 which is what portal / non-
            # K6 roles must see.
            assert ei.value.status_code == 403
        finally:
            await _drain(tid)
    _run(_go())
