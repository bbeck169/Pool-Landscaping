"""TD-22 · Feb-2026 — credit auto-apply wire-ins for long-tail
invoice-create callsites.

See module header in previous revision for scope + harness notes.
Each test performs ALL DB operations inside a single ``_run()``
block to keep every Motor coroutine bound to the same event
loop (per the loop-binding harness pattern used by
``test_bulk_apply_credit_endpoint.py``).
"""
from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from dotenv import dotenv_values


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
        # Drain any fire-and-forget tasks (e.g. mobile_sync's
        # credit-apply task) before closing the loop so the test
        # can observe their side effects.
        pending = asyncio.all_tasks(loop)
        if pending:
            loop.run_until_complete(
                asyncio.gather(*pending, return_exceptions=True),
            )
        loop.close()


def _tid() -> str:
    return f"test-td22-{uuid.uuid4()}"


async def _seed_tenant(db, tid):
    await db.tenants.update_one(
        {"id": tid}, {"$set": {"id": tid, "name": "TD22"}},
        upsert=True,
    )


async def _seed_customer(db, tid, cid: str = None) -> str:
    cid = cid or str(uuid.uuid4())
    await db.customers.insert_one({
        "id": cid, "tenant_id": tid, "name": "Cust",
    })
    return cid


async def _seed_credit(db, tid, cid, dollars):
    cents = int(round(dollars * 100))
    now = datetime.now(timezone.utc).isoformat()
    await db.customer_credits_balance.update_one(
        {"tenant_id": tid, "customer_id": cid},
        {"$set": {
            "balance_cents": cents, "balance": dollars,
            "updated_at": now,
        }},
        upsert=True,
    )


async def _seed_open_invoice(db, tid, cid, total: float) -> str:
    iid = str(uuid.uuid4())
    await db.quotes.insert_one({
        "id": iid, "tenant_id": tid, "customer_id": cid,
        "customer_name": "Cust", "doc_type": "invoice",
        "total": total, "amount_paid": 0.0,
        "payment_status": "unpaid", "status": "sent",
        "due_date": "2026-02-10", "created_at": "2026-02-01T00:00:00Z",
    })
    return iid


async def _cleanup(db, *tids):
    for tid in tids:
        await db.customers.delete_many({"tenant_id": tid})
        await db.customer_credits_balance.delete_many(
            {"tenant_id": tid})
        await db.customer_credits.delete_many({"tenant_id": tid})
        await db.quotes.delete_many({"tenant_id": tid})
        await db.payments.delete_many({"tenant_id": tid})
        await db.billing_plans.delete_many({"tenant_id": tid})
        await db.tenants.delete_many({"id": tid})


# ─── 1 · reports.run_all_due_billing_plans — inline wire-in ──────
def test_reports_run_all_due_billing_plans_fires_credit_apply():
    """reports.py:712 wire-in — cron creates an invoice via a
    billing plan, sweep fires AFTER insert, pre-existing opens
    absorb credit."""
    from config import db
    tid = _tid()

    async def _go():
        await _seed_tenant(db, tid)
        try:
            cid = await _seed_customer(db, tid)
            # Seed enough credit that the Phase 10 line-item path
            # (``apply_and_persist`` called by the loop body BEFORE
            # my sweep wire-in) consumes some against the new
            # invoice and leaves a positive remainder for the
            # sweep to absorb against the pre-existing open row.
            await _seed_credit(db, tid, cid, 200.00)
            old_iid = await _seed_open_invoice(db, tid, cid, total=40.00)
            plan_id = str(uuid.uuid4())
            today = datetime.now(timezone.utc).date().isoformat()
            await db.billing_plans.insert_one({
                "id": plan_id, "tenant_id": tid, "customer_id": cid,
                "service": "Weekly Pool", "amount": 100.00,
                "frequency": "weekly", "next_run": today,
                "active": True,
            })
            from routers.reports import run_all_due_billing_plans
            result = await run_all_due_billing_plans(
                user={"id": "cron", "email": "cron@x.test",
                      "role": "admin", "tenant_id": tid},
            )
            # Shape: {"fired": N, "runs": [{...}, ...]}.
            assert result.get("fired") == 1
            old = await db.quotes.find_one(
                {"id": old_iid, "tenant_id": tid}, {"_id": 0})
            assert old.get("payment_status") == "paid"
            pays = await db.payments.find({
                "tenant_id": tid, "invoice_id": old_iid,
                "method": "credit_balance",
            }, {"_id": 0}).to_list(5)
            # Debug: list all payments for the tenant.
            all_pays = await db.payments.find(
                {"tenant_id": tid}, {"_id": 0},
            ).to_list(10)
            assert len(pays) == 1, (
                f"expected 1 credit payment on old invoice; got "
                f"{len(pays)}. All tenant payments: {all_pays}"
            )
        finally:
            await _cleanup(db, tid)

    _run(_go())


# ─── 2 · mobile_sync — fire-and-forget wire-in ───────────────────
def test_mobile_sync_handle_invoice_create_schedules_credit_apply():
    """mobile_sync.py:558 wire-in — handler returns immediately;
    the fire-and-forget task completes during loop drain."""
    from config import db
    tid = _tid()

    async def _go():
        await _seed_tenant(db, tid)
        try:
            cid = await _seed_customer(db, tid)
            await _seed_credit(db, tid, cid, 50.00)
            old_iid = await _seed_open_invoice(db, tid, cid, total=40.00)
            from routers.mobile_sync import (
                _handle_invoice_create, _SyncOp,
            )
            new_iid = str(uuid.uuid4())
            op = _SyncOp(
                client_op_id=f"co-{uuid.uuid4()}",
                op_type="invoice.create",
                entity_id=new_iid,
                payload={
                    "customer_id": cid,
                    "doc_type": "invoice",
                    "total": 10.00,
                    "status": "sent",
                    "payment_status": "unpaid",
                },
            )
            resp = await _handle_invoice_create(op, tid, "user-mob")
            # Handler returns before the credit-apply task completes.
            assert resp.get("server_id") == new_iid
            # Explicitly await the pending task(s) scheduled by the
            # handler so the test can observe their side-effects.
            pending = [t for t in asyncio.all_tasks()
                       if not t.done()
                       and t is not asyncio.current_task()]
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
            old = await db.quotes.find_one(
                {"id": old_iid, "tenant_id": tid}, {"_id": 0})
            assert old.get("payment_status") == "paid"
        finally:
            await _cleanup(db, tid)

    _run(_go())


# ─── 3 · finances.run_monthly_chem_billing — draft→sent ──────────
def test_finances_run_monthly_chem_billing_fires_credit_apply():
    """finances.py:195 wire-in — chem draft promoted to sent,
    sweep fires + pre-existing open absorbs the credit."""
    from config import db
    tid = _tid()

    async def _go():
        await _seed_tenant(db, tid)
        try:
            cid = await _seed_customer(db, tid)
            await _seed_credit(db, tid, cid, 50.00)
            old_iid = await _seed_open_invoice(db, tid, cid, total=40.00)
            draft_iid = str(uuid.uuid4())
            await db.quotes.insert_one({
                "id": draft_iid, "tenant_id": tid, "customer_id": cid,
                "customer_name": "Cust", "doc_type": "invoice",
                "total": 25.00, "amount_paid": 0.0,
                "payment_status": "unpaid", "status": "draft",
                "auto_chem": True, "billing_month": "2025-12",
                "line_items": [
                    {"description": "Chlorine", "line_total": 25.00},
                ],
                "created_at": "2025-12-15T00:00:00Z",
            })
            from routers.finances import run_monthly_chem_billing
            # Downstream auto-charge path is not under test; patch
            # it so this test only exercises the draft→sent +
            # credit-apply chain.  The attribute name follows the
            # finances.py helper for charging a card on file.
            try:
                import routers.finances as _fin
                _orig = getattr(_fin, "charge_card_on_file", None)
                if _orig is not None:
                    setattr(_fin, "charge_card_on_file",
                            lambda *a, **kw: None)
                await run_monthly_chem_billing()
            finally:
                if _orig is not None:
                    setattr(_fin, "charge_card_on_file", _orig)
            old = await db.quotes.find_one(
                {"id": old_iid, "tenant_id": tid}, {"_id": 0})
            assert old.get("payment_status") == "paid"
            promoted = await db.quotes.find_one(
                {"id": draft_iid, "tenant_id": tid}, {"_id": 0})
            assert promoted.get("status") == "sent"
        finally:
            await _cleanup(db, tid)

    _run(_go())


# ─── 4 · failure isolation ───────────────────────────────────────
def test_reports_invoice_create_isolated_from_credit_apply_failure():
    """Credit-apply exception swallowed; invoice still persisted."""
    from config import db
    tid = _tid()

    async def _go():
        await _seed_tenant(db, tid)
        try:
            cid = await _seed_customer(db, tid)
            plan_id = str(uuid.uuid4())
            today = datetime.now(timezone.utc).date().isoformat()
            await db.billing_plans.insert_one({
                "id": plan_id, "tenant_id": tid, "customer_id": cid,
                "service": "Service", "amount": 100.00,
                "frequency": "weekly", "next_run": today,
                "active": True,
            })
            from routers.reports import run_all_due_billing_plans
            async def _boom(*a, **kw):
                raise RuntimeError(
                    "boom — credit_apply synthetic failure"
                )
            with patch(
                "services.credit_apply."
                "apply_credit_to_customer_open_invoices", new=_boom,
            ):
                result = await run_all_due_billing_plans(
                    user={"id": "cron", "email": "cron@x.test",
                          "role": "admin", "tenant_id": tid},
                )
            assert result.get("fired") == 1
            invs = await db.quotes.find({
                "tenant_id": tid, "doc_type": "invoice",
            }, {"_id": 0}).to_list(5)
            assert len(invs) == 1
        finally:
            await _cleanup(db, tid)

    _run(_go())


# ─── 5 · no-double-apply · exclude_invoice_ids honored ───────────
def test_reports_sweep_excludes_newly_created_invoice():
    """Sweep excludes the just-created invoice so credit lands
    only on OLDER opens."""
    from config import db
    tid = _tid()

    async def _go():
        await _seed_tenant(db, tid)
        try:
            cid = await _seed_customer(db, tid)
            await _seed_credit(db, tid, cid, 200.00)
            old_iid = await _seed_open_invoice(db, tid, cid, total=50.00)
            plan_id = str(uuid.uuid4())
            today = datetime.now(timezone.utc).date().isoformat()
            await db.billing_plans.insert_one({
                "id": plan_id, "tenant_id": tid, "customer_id": cid,
                "service": "Service", "amount": 75.00,
                "frequency": "weekly", "next_run": today,
                "active": True,
            })
            from routers.reports import run_all_due_billing_plans
            result = await run_all_due_billing_plans(
                user={"id": "cron", "email": "cron@x.test",
                      "role": "admin", "tenant_id": tid},
            )
            new_iid = result["runs"][0]["invoice_id"]
            pays_new = await db.payments.find({
                "tenant_id": tid, "invoice_id": new_iid,
                "method": "credit_balance",
            }, {"_id": 0}).to_list(5)
            pays_old = await db.payments.find({
                "tenant_id": tid, "invoice_id": old_iid,
                "method": "credit_balance",
            }, {"_id": 0}).to_list(5)
            assert len(pays_new) == 0, (
                "sweep must exclude the just-created invoice"
            )
            assert len(pays_old) == 1
        finally:
            await _cleanup(db, tid)

    _run(_go())
