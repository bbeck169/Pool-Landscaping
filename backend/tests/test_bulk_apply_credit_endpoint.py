"""Feb-2026 · Bulk Apply Credit pytest — covers the new endpoint
``POST /api/invoices/bulk-apply-credit`` + the shared helper
``apply_credit_to_specific_invoice`` on
``services/credit_apply.py``.

Uses the SAME loop-binding harness as the sibling
``test_credit_apply.py`` suite (``_run()`` + explicit
``asyncio.new_event_loop`` + ``cfg.db.client._io_loop`` rebind)
because this feature's writer path is the credit-apply service,
which inherits that suite's harness constraints.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from dotenv import dotenv_values
from fastapi import HTTPException


_TEST_DIR = Path(__file__).resolve().parent
_BE = dotenv_values(_TEST_DIR.parent / ".env")
for _k in ("MONGO_URL", "DB_NAME"):
    if _k not in os.environ and _BE.get(_k):
        os.environ[_k] = _BE[_k]


def _run(coro):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        import config as _cfg
        try:
            _cfg.db.client._io_loop = loop  # noqa: SLF001
        except Exception:
            pass
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _tid() -> str:
    return f"test-bulk-apc-{uuid.uuid4()}"


async def _seed_tenant(db, tid: str):
    await db.tenants.update_one(
        {"id": tid},
        {"$set": {"id": tid, "name": f"Synthetic {tid}"}},
        upsert=True,
    )


async def _seed_customer(db, tid: str, name: str = "Cust") -> str:
    cid = str(uuid.uuid4())
    await db.customers.insert_one({
        "id": cid, "tenant_id": tid, "name": name,
    })
    return cid


async def _seed_credit(db, tid: str, cid: str, dollars: float):
    cents = int(round(dollars * 100))
    now = datetime.now(timezone.utc).isoformat()
    await db.customer_credits_balance.update_one(
        {"tenant_id": tid, "customer_id": cid},
        {"$set": {
            "balance_cents": cents,
            "balance": dollars,
            "updated_at": now,
        }},
        upsert=True,
    )
    await db.customers.update_one(
        {"id": cid, "tenant_id": tid},
        {"$set": {
            "credit_balance_cents": cents,
            "updated_at": now,
        }},
        upsert=True,
    )


async def _seed_invoice(
    db, tid: str, cid: str, *,
    total: float, amount_paid: float = 0.0,
    payment_status: str = "unpaid",
    status: str = "sent",
    due_date: str = "2026-02-10",
    invoice_number: str = None,
) -> str:
    iid = str(uuid.uuid4())
    await db.quotes.insert_one({
        "id": iid,
        "tenant_id": tid,
        "customer_id": cid,
        "customer_name": "Cust",
        "doc_type": "invoice",
        "total": total,
        "amount_paid": amount_paid,
        "payment_status": payment_status,
        "status": status,
        "due_date": due_date,
        "created_at": "2026-02-01T00:00:00Z",
        "invoice_number": invoice_number or f"INV-{iid[:6]}",
    })
    return iid


async def _cleanup(db, *tids: str):
    for tid in tids:
        await db.customers.delete_many({"tenant_id": tid})
        await db.customer_credits_balance.delete_many(
            {"tenant_id": tid})
        await db.customer_credits.delete_many({"tenant_id": tid})
        await db.quotes.delete_many({"tenant_id": tid})
        await db.payments.delete_many({"tenant_id": tid})
        await db.audit_logs.delete_many({"tenant_id": tid})
        await db.audit_events.delete_many({"tenant_id": tid})
        await db.tenants.delete_many({"id": tid})


async def _call_endpoint(tid: str, invoice_ids, role: str = "admin"):
    from routers.invoices_bulk_apply_credit import (
        bulk_apply_credit, BulkApplyCreditBody,
    )
    return await bulk_apply_credit(
        body=BulkApplyCreditBody(invoice_ids=list(invoice_ids)),
        user={"id": "admin-1", "email": "a@x.test", "role": role},
        tenant={"id": tid},
    )


# ─── 1 · simplest happy path ─────────────────────────────────────
def test_single_invoice_fully_credited():
    from config import db
    tid = _tid()

    async def _go():
        await _seed_tenant(db, tid)
        cid = await _seed_customer(db, tid)
        await _seed_credit(db, tid, cid, 100.00)
        iid = await _seed_invoice(db, tid, cid, total=50)
        return await _call_endpoint(tid, [iid])

    try:
        resp = _run(_go())
        assert resp["summary"]["credited"] == 1
        assert resp["summary"]["total_amount_applied"] == 50.00
        r = resp["results"][0]
        assert r["status"] == "credited"
        assert r["amount_applied"] == 50.00
        assert r["balance_remaining"] == 0
        assert r["payment_status_after"] == "paid"
    finally:
        _run(_cleanup(db, tid))


# ─── 2 · partial coverage keeps invoice partial ──────────────────
def test_partial_credit_coverage_invoice_stays_partial():
    from config import db
    tid = _tid()

    async def _go():
        await _seed_tenant(db, tid)
        cid = await _seed_customer(db, tid)
        await _seed_credit(db, tid, cid, 100.00)
        iid = await _seed_invoice(db, tid, cid, total=200)
        return await _call_endpoint(tid, [iid])

    try:
        resp = _run(_go())
        r = resp["results"][0]
        assert r["status"] == "credited"
        assert r["amount_applied"] == 100.00
        assert r["balance_remaining"] == 100.00
        assert r["payment_status_after"] == "partial"
    finally:
        _run(_cleanup(db, tid))


# ─── 3 · three invoices · credit drained oldest-first ────────────
def test_three_invoices_credit_drained_oldest_first():
    from config import db
    tid = _tid()

    async def _go():
        await _seed_tenant(db, tid)
        cid = await _seed_customer(db, tid)
        await _seed_credit(db, tid, cid, 100.00)
        iid1 = await _seed_invoice(
            db, tid, cid, total=40, due_date="2026-02-01",
            invoice_number="INV-1")
        iid2 = await _seed_invoice(
            db, tid, cid, total=30, due_date="2026-02-05",
            invoice_number="INV-2")
        iid3 = await _seed_invoice(
            db, tid, cid, total=50, due_date="2026-02-10",
            invoice_number="INV-3")
        resp = await _call_endpoint(tid, [iid3, iid1, iid2])
        bal = await db.customer_credits_balance.find_one(
            {"tenant_id": tid, "customer_id": cid},
            {"_id": 0, "balance_cents": 1},
        ) or {}
        return resp, bal

    try:
        resp, bal = _run(_go())
        # Response order mirrors INPUT order.
        assert [r["invoice_number"] for r in resp["results"]] == [
            "INV-3", "INV-1", "INV-2",
        ]
        by_num = {r["invoice_number"]: r for r in resp["results"]}
        assert by_num["INV-1"]["amount_applied"] == 40.00
        assert by_num["INV-1"]["payment_status_after"] == "paid"
        assert by_num["INV-2"]["amount_applied"] == 30.00
        assert by_num["INV-2"]["payment_status_after"] == "paid"
        assert by_num["INV-3"]["amount_applied"] == 30.00
        assert by_num["INV-3"]["payment_status_after"] == "partial"
        assert resp["summary"]["total_amount_applied"] == 100.00
        assert int(bal.get("balance_cents") or 0) == 0
    finally:
        _run(_cleanup(db, tid))


# ─── 4 · zero credit → skipped_no_credit ─────────────────────────
def test_zero_credit_skipped_no_credit():
    from config import db
    tid = _tid()

    async def _go():
        await _seed_tenant(db, tid)
        cid = await _seed_customer(db, tid)
        iid = await _seed_invoice(db, tid, cid, total=50)
        resp = await _call_endpoint(tid, [iid])
        n = await db.payments.count_documents({"tenant_id": tid})
        return resp, n

    try:
        resp, n = _run(_go())
        r = resp["results"][0]
        assert r["status"] == "skipped_no_credit"
        assert r["amount_applied"] == 0
        assert resp["summary"]["skipped_no_credit"] == 1
        assert n == 0
    finally:
        _run(_cleanup(db, tid))


# ─── 5 · already paid → skipped_already_paid ─────────────────────
def test_already_paid_invoice_skipped():
    from config import db
    tid = _tid()

    async def _go():
        await _seed_tenant(db, tid)
        cid = await _seed_customer(db, tid)
        await _seed_credit(db, tid, cid, 100.00)
        iid = await _seed_invoice(
            db, tid, cid, total=50, amount_paid=50,
            payment_status="paid")
        resp = await _call_endpoint(tid, [iid])
        n = await db.payments.count_documents({"tenant_id": tid})
        return resp, n

    try:
        resp, n = _run(_go())
        r = resp["results"][0]
        assert r["status"] == "skipped_already_paid"
        assert resp["summary"]["skipped_already_paid"] == 1
        assert n == 0
    finally:
        _run(_cleanup(db, tid))


# ─── 6 · void / cancelled → skipped_blocked_status ───────────────
def test_void_invoice_blocked():
    from config import db
    tid = _tid()

    async def _go():
        await _seed_tenant(db, tid)
        cid = await _seed_customer(db, tid)
        await _seed_credit(db, tid, cid, 100.00)
        iid = await _seed_invoice(
            db, tid, cid, total=50, status="void")
        return await _call_endpoint(tid, [iid])

    try:
        resp = _run(_go())
        assert resp["results"][0]["status"] == "skipped_blocked_status"
        assert resp["summary"]["skipped_blocked_status"] == 1
    finally:
        _run(_cleanup(db, tid))


# ─── 7 · unknown id → skipped_not_found ──────────────────────────
def test_unknown_invoice_id_skipped_not_found():
    from config import db
    tid = _tid()

    async def _go():
        await _seed_tenant(db, tid)
        return await _call_endpoint(tid, ["does-not-exist-xyz"])

    try:
        resp = _run(_go())
        r = resp["results"][0]
        assert r["status"] == "skipped_not_found"
        assert r["customer_id"] is None
        assert resp["summary"]["skipped_not_found"] == 1
    finally:
        _run(_cleanup(db, tid))


# ─── 8 · cross-tenant id → skipped_not_found (no leak) ───────────
def test_cross_tenant_invoice_id_skipped_not_found():
    from config import db
    tid_a = _tid()
    tid_b = _tid()

    async def _go():
        await _seed_tenant(db, tid_a)
        await _seed_tenant(db, tid_b)
        cid_b = await _seed_customer(db, tid_b, "B Cust")
        await _seed_credit(db, tid_b, cid_b, 100.00)
        iid_b = await _seed_invoice(db, tid_b, cid_b, total=50)
        resp = await _call_endpoint(tid_a, [iid_b])
        n = await db.payments.count_documents({"tenant_id": tid_b})
        return resp, n

    try:
        resp, n = _run(_go())
        r = resp["results"][0]
        assert r["status"] == "skipped_not_found"
        assert r["customer_id"] is None
        assert r["customer_name"] is None
        assert n == 0
    finally:
        _run(_cleanup(db, tid_a, tid_b))


# ─── 9 · 501 ids → 400 too_many_invoice_ids ──────────────────────
def test_too_many_invoice_ids_returns_400():
    from config import db
    tid = _tid()

    async def _go():
        await _seed_tenant(db, tid)
        too_many = [str(uuid.uuid4()) for _ in range(501)]
        with pytest.raises(HTTPException) as exc:
            await _call_endpoint(tid, too_many)
        assert exc.value.status_code == 400
        assert exc.value.detail["error_code"] == "too_many_invoice_ids"
        assert exc.value.detail["max"] == 500
        assert exc.value.detail["received"] == 501

    try:
        _run(_go())
    finally:
        _run(_cleanup(db, tid))


# ─── 10 · multi-customer allocation + summary totals ─────────────
def test_multi_customer_allocation_and_summary_totals():
    from config import db
    tid = _tid()

    async def _go():
        await _seed_tenant(db, tid)
        cid_a = await _seed_customer(db, tid, "A Cust")
        await _seed_credit(db, tid, cid_a, 20.00)
        iid_a1 = await _seed_invoice(
            db, tid, cid_a, total=15, due_date="2026-02-01",
            invoice_number="A-1")
        iid_a2 = await _seed_invoice(
            db, tid, cid_a, total=10, due_date="2026-02-05",
            invoice_number="A-2")
        cid_b = await _seed_customer(db, tid, "B Cust")
        iid_b1 = await _seed_invoice(
            db, tid, cid_b, total=30, invoice_number="B-1")
        cid_c = await _seed_customer(db, tid, "C Cust")
        await _seed_credit(db, tid, cid_c, 100.00)
        iid_c1 = await _seed_invoice(
            db, tid, cid_c, total=40, invoice_number="C-1")
        return await _call_endpoint(
            tid, [iid_a1, iid_a2, iid_b1, iid_c1],
        )

    try:
        resp = _run(_go())
        by_num = {r["invoice_number"]: r for r in resp["results"]}
        assert by_num["A-1"]["amount_applied"] == 15.00
        assert by_num["A-1"]["payment_status_after"] == "paid"
        assert by_num["A-2"]["amount_applied"] == 5.00
        assert by_num["A-2"]["payment_status_after"] == "partial"
        assert by_num["B-1"]["status"] == "skipped_no_credit"
        assert by_num["C-1"]["amount_applied"] == 40.00
        assert by_num["C-1"]["payment_status_after"] == "paid"
        s = resp["summary"]
        assert s["credited"] == 3
        assert s["skipped_no_credit"] == 1
        assert s["total_amount_applied"] == 60.00
    finally:
        _run(_cleanup(db, tid))


# ─── 11 · idempotency · second call does not double-apply ────────
def test_second_call_does_not_double_apply():
    from config import db
    tid = _tid()

    async def _go():
        await _seed_tenant(db, tid)
        cid = await _seed_customer(db, tid)
        await _seed_credit(db, tid, cid, 100.00)
        iid = await _seed_invoice(db, tid, cid, total=50)
        resp1 = await _call_endpoint(tid, [iid])
        resp2 = await _call_endpoint(tid, [iid])
        n = await db.payments.count_documents({
            "tenant_id": tid, "customer_id": cid,
            "method": "credit_balance",
            "$or": [
                {"deleted_at": None},
                {"deleted_at": {"$exists": False}},
            ],
        })
        return resp1, resp2, n

    try:
        resp1, resp2, n = _run(_go())
        assert resp1["summary"]["total_amount_applied"] == 50.00
        assert resp2["summary"]["skipped_already_paid"] == 1
        assert resp2["summary"]["total_amount_applied"] == 0
        assert n == 1
    finally:
        _run(_cleanup(db, tid))


# ─── 12 · audit log row written ──────────────────────────────────
def test_audit_log_row_written_with_correct_payload():
    from config import db
    tid = _tid()

    async def _go():
        await _seed_tenant(db, tid)
        cid = await _seed_customer(db, tid)
        await _seed_credit(db, tid, cid, 100.00)
        iid = await _seed_invoice(db, tid, cid, total=50)
        resp = await _call_endpoint(tid, [iid])
        audit = await db.audit_logs.find_one({
            "tenant_id": tid,
            "action": "invoices.bulk_apply_credit",
        }, {"_id": 0})
        return resp, audit, iid

    try:
        resp, audit, iid = _run(_go())
        assert audit is not None
        assert audit["actor_id"] == "admin-1"
        assert audit["actor_email"] == "a@x.test"
        assert audit["request_id"] == resp["request_id"]
        assert audit["total_selected"] == 1
        assert audit["credited"] == 1
        assert audit["total_amount_applied"] == 50.00
        assert audit["invoice_ids_sample"] == [iid]
    finally:
        _run(_cleanup(db, tid))


# ─── 13 · non-admin → 403 ─────────────────────────────────────────
def test_non_admin_role_rejected_403():
    from config import db
    tid = _tid()

    async def _go():
        await _seed_tenant(db, tid)
        with pytest.raises(HTTPException) as exc:
            await _call_endpoint(tid, ["any-id"], role="technician")
        assert exc.value.status_code == 403

    try:
        _run(_go())
    finally:
        _run(_cleanup(db, tid))
