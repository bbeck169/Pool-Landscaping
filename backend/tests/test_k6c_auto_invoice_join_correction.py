"""Phase K6 · Feb-2026 — Correction · auto-invoice join.

Reproduces the tester's exact bug: landscape job → complete →
auto-invoice → record-payment → PATCH price_cents on super_admin
returned 200 instead of the specified 409.  The K6 fix now looks up
the invoice via ``job.auto_invoice_id`` first (falling back to the
``scheduled_job_id`` back-pointer only if that misses), matches
``payment_status`` values that the auto-invoice pipeline actually
writes (``paid`` / ``partial`` / ``unpaid``), and recalculates on
the integer-cents fields (``subtotal_cents`` / ``total_cents``).
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
    for mod in ("routers.jobs",):
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
        {"email": "admin@aquaterra.com"}, {"_id": 0, "tenant_id": 1})
    return u["tenant_id"]


async def _tenant_dep(tid: str) -> Dict[str, Any]:
    return await _db().tenants.find_one({"id": tid}, {"_id": 0}) or {"id": tid}


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


async def _seed_case(tid: str, *, payment_status: str,
                             subtotal_cents: int = 10000) -> tuple[str, str]:
    """Seed a completed job + auto_invoice_id-linked invoice mirror
    of the tester's scenario.  ``payment_status`` = ``paid`` |
    ``unpaid`` | ``partial``."""
    from utils import now_iso
    two_days_ago = _iso(datetime.now(timezone.utc) - timedelta(hours=48))
    jid = f"k6c-{payment_status}-{uuid.uuid4().hex[:8]}"
    iid = f"k6c-inv-{jid[-8:]}"
    await _db().customers.update_one(
        {"id": "cust-k6c"},
        {"$setOnInsert": {"id": "cust-k6c", "tenant_id": tid,
                              "name": "K6C", "email": "k6c@example.com",
                              "created_at": now_iso()}},
        upsert=True,
    )
    await _db().jobs.insert_one({
        "id": jid, "tenant_id": tid, "customer_id": "cust-k6c",
        "service_type": "Landscape · K6C",
        "technician_id": "k6c-tech",
        "status": "completed",
        "completed_at": two_days_ago,
        "scheduled_date": two_days_ago[:10],
        "price_cents": subtotal_cents,
        "auto_invoice_id": iid,   # THE join the tester exercised
        "created_at": two_days_ago,
    })
    await _db().quotes.insert_one({
        "id": iid, "tenant_id": tid, "doc_type": "invoice",
        "customer_id": "cust-k6c",
        "status": "issued",                       # auto-invoice sets issued
        "payment_status": payment_status,         # tester's payment column
        "subtotal_cents": subtotal_cents,
        "total_cents": subtotal_cents,
        "invoice_number": "INV-K6C-1",
        "created_at": two_days_ago,
    })
    return jid, iid


def _admin(tid: str) -> Dict[str, Any]:
    return {"id": "u-admin", "role": "super_admin",
              "tenant_id": tid, "email": "super@aquaterra.com",
              "name": "Super"}


def _patch(**kw):
    from routers.jobs import JobEditPatch
    return JobEditPatch(**kw)


async def _drain(tid: str) -> None:
    for coll in ("jobs", "job_edits", "quotes", "audit_events", "customers"):
        await _db()[coll].delete_many({
            "$or": [
                {"id": {"$regex": "^k6c-"}},
                {"customer_id": "cust-k6c"},
                {"payload.job_id": {"$regex": "^k6c-"}},
                {"job_id": {"$regex": "^k6c-"}},
                {"id": "cust-k6c"},
            ],
        })


# ═══════════════════════════════════════════════════════════════════
# 1. Tester's exact bug — PAID auto-invoice + PATCH price_cents → 409
# ═══════════════════════════════════════════════════════════════════
def test_k6c_paid_auto_invoice_blocks_priced_edit_via_auto_invoice_id():
    async def _go():
        tid = await _tenant_id()
        jid, iid = await _seed_case(tid, payment_status="paid",
                                              subtotal_cents=10000)
        try:
            from routers.jobs import patch_job_edit_window
            with pytest.raises(HTTPException) as ei:
                await patch_job_edit_window(
                    jid, _patch(price_cents=25000,
                                    edit_reason="test", edit_source="test"),
                    user=_admin(tid),
                    tenant=await _tenant_dep(tid),
                )
            assert ei.value.status_code == 409
            det = ei.value.detail
            assert det["detail"] == "invoice_locked"
            # EXACT spec message — mobile client keys off the phrase
            # "void or refund the invoice before editing priced fields".
            expected = (
                f"Invoice {iid} is paid — void or refund the invoice "
                f"before editing priced fields on this completed job.")
            assert det["message"] == expected, det["message"]
            assert det["invoice_id"] == iid
            assert det["invoice_status"] == "paid"
            # Job unchanged — nothing wrote to price_cents.
            job = await _db().jobs.find_one({"id": jid})
            assert job["price_cents"] == 10000
            # Belt-and-suspenders: NO audit row landed (409 fires
            # before the audit write).
            audit = await _db().audit_events.find_one(
                {"event_type": "job_edited_after_completion",
                 "payload.job_id": jid})
            assert audit is None
        finally:
            await _drain(tid)
    _run(_go())


# ═══════════════════════════════════════════════════════════════════
# 2. Same scenario but partial-paid → 409 (auto-invoice writes "partial")
# ═══════════════════════════════════════════════════════════════════
def test_k6c_partial_paid_also_locks():
    async def _go():
        tid = await _tenant_id()
        jid, iid = await _seed_case(tid, payment_status="partial")
        try:
            from routers.jobs import patch_job_edit_window
            with pytest.raises(HTTPException) as ei:
                await patch_job_edit_window(
                    jid, _patch(price_cents=20000),
                    user=_admin(tid),
                    tenant=await _tenant_dep(tid),
                )
            assert ei.value.status_code == 409
            assert ei.value.detail["detail"] == "invoice_locked"
        finally:
            await _drain(tid)
    _run(_go())


# ═══════════════════════════════════════════════════════════════════
# 3. UNPAID auto-invoice → 200 AND subtotal_cents + total_cents
#    updated on the invoice
# ═══════════════════════════════════════════════════════════════════
def test_k6c_unpaid_auto_invoice_recalculates_cents_fields():
    async def _go():
        tid = await _tenant_id()
        jid, iid = await _seed_case(tid, payment_status="unpaid",
                                              subtotal_cents=10000)
        try:
            from routers.jobs import patch_job_edit_window
            fresh = await patch_job_edit_window(
                jid, _patch(price_cents=25000,
                                edit_reason="test", edit_source="test"),
                user=_admin(tid),
                tenant=await _tenant_dep(tid),
            )
            assert fresh["price_cents"] == 25000
            inv = await _db().quotes.find_one({"id": iid})
            # +$150 delta = 15000 cents.
            assert inv["subtotal_cents"] == 25000
            assert inv["total_cents"] == 25000
            assert inv["k6_last_recalc_delta_cents"] == 15000
            audit = await _db().audit_events.find_one(
                {"event_type": "job_edited_after_completion",
                 "payload.job_id": jid})
            assert audit is not None
            assert audit["payload"]["invoice_recalculated"] is True
            assert audit["payload"]["invoice_id"] == iid
        finally:
            await _drain(tid)
    _run(_go())


# ═══════════════════════════════════════════════════════════════════
# 4. Fallback join still works — invoice has scheduled_job_id but no
#    auto_invoice_id back-pointer on the job (quote-converted-invoice
#    case).  Guard still fires.
# ═══════════════════════════════════════════════════════════════════
def test_k6c_fallback_scheduled_job_id_join_still_works():
    async def _go():
        tid = await _tenant_id()
        from utils import now_iso
        two_days_ago = _iso(datetime.now(timezone.utc) - timedelta(hours=48))
        jid = f"k6c-fb-{uuid.uuid4().hex[:8]}"
        iid = f"k6c-inv-{jid[-8:]}"
        await _db().customers.update_one(
            {"id": "cust-k6c"},
            {"$setOnInsert": {"id": "cust-k6c", "tenant_id": tid,
                                    "name": "K6C", "created_at": now_iso()}},
            upsert=True)
        await _db().jobs.insert_one({
            "id": jid, "tenant_id": tid, "customer_id": "cust-k6c",
            "status": "completed", "completed_at": two_days_ago,
            "scheduled_date": two_days_ago[:10], "price_cents": 10000,
            "service_type": "K6C fallback",
            # No auto_invoice_id — quote-converted path.
            "created_at": two_days_ago,
        })
        await _db().quotes.insert_one({
            "id": iid, "tenant_id": tid, "doc_type": "invoice",
            "customer_id": "cust-k6c",
            "scheduled_job_id": jid,          # only join available
            "status": "issued", "payment_status": "paid",
            "subtotal_cents": 10000, "total_cents": 10000,
            "created_at": two_days_ago,
        })
        try:
            from routers.jobs import patch_job_edit_window
            with pytest.raises(HTTPException) as ei:
                await patch_job_edit_window(
                    jid, _patch(price_cents=15000),
                    user=_admin(tid),
                    tenant=await _tenant_dep(tid),
                )
            assert ei.value.status_code == 409
            assert ei.value.detail["invoice_id"] == iid
        finally:
            await _drain(tid)
    _run(_go())
