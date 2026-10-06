"""Phase B3 · Feb-2026 — invoice.* webhook handlers.

Verifies:
  * ``invoice.paid`` on a tracked local invoice → ``payment_status=paid``.
  * ``invoice.payment_failed`` → ``payment_status=payment_failed``
    (via ``_mark_invoice_failed``).
  * ``invoice.finalized`` → stripe_invoice_id + finalized_at written
    to the linked CRM invoice.
  * Untracked Stripe invoices (no ``crm_invoice_id`` metadata) →
    no-op, no crash.
"""
from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

import pytest
from dotenv import dotenv_values

from tests._phase34_asyncio import batch_safe_run
from services.payments import stripe_charge as sc


_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
TID = f"tenINV-{uuid.uuid4().hex[:8]}"


@pytest.fixture
def db():
    # STRIPE-TEST-ISOLATION · Feb-2026 — trigger the Phase-41.1d
    # Motor-client rebuild on the session-persistent loop BEFORE
    # handing ``sc.db`` to the test. After the rebuild, ``sc.db``
    # points at the fresh client bound to the persistent loop
    # (see tests/_phase34_asyncio._rebuild_motor_client_on_loop).
    import asyncio as _asyncio
    batch_safe_run(_asyncio.sleep(0))
    return sc.db


@pytest.fixture(autouse=True)
def _clean(db):
    async def _wipe():
        await db.quotes.delete_many({"tenant_id": TID})
    batch_safe_run(_wipe())
    yield
    batch_safe_run(_wipe())


async def _seed_invoice(inv_id: str, total: float = 50.0):
    await sc.db.quotes.insert_one({
        "id": inv_id, "tenant_id": TID, "doc_type": "invoice",
        "total": total, "amount_paid": 0, "payment_status": "unpaid",
    })


def _inv_event(evt_type: str, inv_id: str, crm_invoice_id: str | None = None,
                 amount_cents: int = 5000, error_msg: str | None = None) -> dict:
    meta = {}
    if crm_invoice_id:
        meta = {"crm_tenant_id": TID, "crm_invoice_id": crm_invoice_id}
    obj = {
        "id": inv_id,
        "amount_paid": amount_cents,
        "total": amount_cents,
        "payment_intent": "pi_from_invoice",
        "metadata": meta,
    }
    if error_msg:
        obj["last_finalization_error"] = {"message": error_msg, "code": "card_declined"}
    return {"id": f"evt_{uuid.uuid4().hex}", "type": evt_type,
            "data": {"object": obj}}


def test_invoice_paid_marks_local_invoice_paid(db):
    inv_id = f"inv-{uuid.uuid4().hex[:8]}"
    batch_safe_run(_seed_invoice(inv_id))
    evt = _inv_event("invoice.paid", f"in_stripe_{inv_id}", crm_invoice_id=inv_id)
    res = batch_safe_run(sc.handle_webhook_event(evt))
    assert res["handled"] is True
    row = batch_safe_run(
        db.quotes.find_one({"id": inv_id, "tenant_id": TID}, {"_id": 0}),
    )
    assert row["payment_status"] == "paid"


def test_invoice_payment_failed_marks_local_invoice_failed(db):
    inv_id = f"inv-{uuid.uuid4().hex[:8]}"
    batch_safe_run(_seed_invoice(inv_id))
    evt = _inv_event("invoice.payment_failed", f"in_stripe_{inv_id}",
                       crm_invoice_id=inv_id, error_msg="Your card was declined.")
    res = batch_safe_run(sc.handle_webhook_event(evt))
    assert res["handled"] is True
    row = batch_safe_run(
        db.quotes.find_one({"id": inv_id, "tenant_id": TID}, {"_id": 0}),
    )
    # ``_mark_invoice_failed`` writes payment_status="payment_failed".
    assert row["payment_status"] in ("payment_failed", "failed")


def test_invoice_finalized_stamps_stripe_invoice_id(db):
    inv_id = f"inv-{uuid.uuid4().hex[:8]}"
    stripe_inv_id = f"in_stripe_{inv_id}"
    batch_safe_run(_seed_invoice(inv_id))
    evt = _inv_event("invoice.finalized", stripe_inv_id, crm_invoice_id=inv_id)
    res = batch_safe_run(sc.handle_webhook_event(evt))
    assert res["handled"] is True
    row = batch_safe_run(
        db.quotes.find_one({"id": inv_id, "tenant_id": TID}, {"_id": 0}),
    )
    assert row["stripe_invoice_id"] == stripe_inv_id
    assert row.get("stripe_invoice_finalized_at")


def test_untracked_stripe_invoice_is_noop(db):
    # No crm_invoice_id in metadata → handler logs + returns unhandled.
    evt = _inv_event("invoice.paid", "in_dashboard_only", crm_invoice_id=None)
    res = batch_safe_run(sc.handle_webhook_event(evt))
    assert res["handled"] is False
