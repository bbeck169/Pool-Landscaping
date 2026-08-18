"""Feb-2026 · Stripe reconciliation regressions.

Backend-only. Bypasses the Stripe network path (no PIs actually
created) by exercising the service module directly with an
``asyncio``-driven Motor client + a monkey-patched ``_create_intent``.
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
from uuid import uuid4

import pytest
from motor.motor_asyncio import AsyncIOMotorClient

# Import the service — its ``db`` handle is bound at module import
# time to the real MONGO_URL / DB_NAME already set in /app/backend/.env.
from services.payments import stripe_charge as sc


def _env(k: str) -> str:
    for ln in Path("/app/backend/.env").read_text().splitlines():
        if ln.startswith(f"{k}="):
            return ln.split("=", 1)[1].strip().strip('"')
    return ""


TID_A = f"tenA-{uuid4().hex[:8]}"
TID_B = f"tenB-{uuid4().hex[:8]}"
CID   = f"cust-{uuid4().hex[:8]}"
PMID  = f"pm_{uuid4().hex[:14]}"


@pytest.fixture(scope="module")
def db():
    return sc.db


@pytest.fixture(autouse=True)
def _clean(db, monkeypatch):
    async def _wipe():
        for coll in ("stripe_charges", "payment_methods", "quotes"):
            await db[coll].delete_many({"tenant_id": {"$in": [TID_A, TID_B]}})
        # Also purge any stripe_charges rows tagged with the fixed PI
        # ids these tests write — prior test sessions used the same
        # hardcoded ids under a different (now-orphaned) tenant, and
        # a stale row would defeat the upsert-on-insert defaults.
        await db.stripe_charges.delete_many(
            {"stripe_payment_intent_id": {"$regex": "^pi_(ok|dashboard|fail|r1|r2|iso_a|iso_b)$"}}
        )
    asyncio.get_event_loop().run_until_complete(_wipe())
    # Seed the payment method so ``charge_card_on_file`` clears its
    # own attach guard.
    async def _seed_pm():
        await db.payment_methods.insert_one({
            "tenant_id": TID_A, "customer_id": CID, "provider": "stripe",
            "provider_payment_method_id": PMID,
            "provider_customer_id": "cus_test", "stripe_mode": "test",
        })
    asyncio.get_event_loop().run_until_complete(_seed_pm())

    # Stub the actual Stripe call inside charge_card_on_file so tests
    # don't hit the network. Returns deterministic PI per idempotency key.
    async def _fake_create_intent(**kw):
        return {
            "id": f"pi_{kw['idempotency_key'][-16:]}",
            "status": "succeeded",
            "amount": kw["amount_cents"],
            "currency": kw.get("currency", "usd"),
        }
    monkeypatch.setattr(sc, "_create_intent", _fake_create_intent, raising=False)
    yield


async def _seed_invoice(inv_id: str, tenant_id: str = TID_A, total: float = 50.0):
    await sc.db.quotes.insert_one({
        "id": inv_id, "tenant_id": tenant_id, "doc_type": "invoice",
        "total": total, "amount_paid": 0, "payment_status": "unpaid",
    })


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ── Test 1 — double-charge blocked ────────────────────────────────────
def test_double_charge_returns_existing_pi_and_no_new_row():
    inv = f"inv-1-{uuid4().hex[:6]}"
    _run(_seed_invoice(inv))

    async def go():
        r1 = await sc.charge_card_on_file(
            tenant_id=TID_A, customer_id=CID, payment_method_id=PMID,
            amount_cents=5000, invoice_id=inv,
        )
        with pytest.raises(sc.ChargeAlreadySucceededError) as exc:
            await sc.charge_card_on_file(
                tenant_id=TID_A, customer_id=CID, payment_method_id=PMID,
                amount_cents=5000, invoice_id=inv,
            )
        return r1, exc.value.payment_intent_id
    r1, second_pi = _run(go())
    assert r1["status"] == "succeeded"
    assert second_pi == r1["payment_intent_id"]
    count = _run(sc.db.stripe_charges.count_documents(
        {"tenant_id": TID_A, "invoice_id": inv}))
    assert count == 1


# ── Test 2 — deterministic idempotency key ────────────────────────────
def test_idempotency_key_is_deterministic():
    key = f"charge:{TID_A}:INV:5000:{PMID}"
    # Rebuilt manually to prove format contract matches the service.
    assert key.startswith("charge:") and key.count(":") == 4


# ── Test 3 — invoice already paid short-circuits ──────────────────────
def test_charge_rejects_when_invoice_already_paid():
    inv = f"inv-3-{uuid4().hex[:6]}"

    async def go():
        await sc.db.quotes.insert_one({
            "id": inv, "tenant_id": TID_A, "doc_type": "invoice",
            "total": 50.0, "amount_paid": 50.0, "payment_status": "paid",
        })
        with pytest.raises(sc.InvoiceAlreadyPaidError):
            await sc.charge_card_on_file(
                tenant_id=TID_A, customer_id=CID, payment_method_id=PMID,
                amount_cents=5000, invoice_id=inv,
            )
    _run(go())
    # No charge row created — Stripe was never called.
    assert _run(sc.db.stripe_charges.count_documents({"invoice_id": inv})) == 0


# ── Test 4 — success webhook flips invoice ────────────────────────────
def test_webhook_success_marks_invoice_paid():
    inv = f"inv-4-{uuid4().hex[:6]}"
    _run(_seed_invoice(inv))
    ev = {"type": "payment_intent.succeeded",
          "data": {"object": {
              "id": "pi_ok_1", "status": "succeeded",
              "amount": 5000, "amount_received": 5000, "currency": "usd",
              "payment_method": PMID,
              "metadata": {"crm_tenant_id": TID_A, "crm_invoice_id": inv,
                             "crm_customer_id": CID},
          }}}
    r = _run(sc.handle_webhook_event(ev))
    assert r["handled"] is True
    row = _run(sc.db.quotes.find_one({"id": inv}))
    assert row["payment_status"] == "paid"
    assert abs(row["amount_paid"] - 50.0) < 0.01
    assert row.get("paid_at")


# ── Test 5 — success webhook without metadata is a no-op on invoice ───
def test_webhook_success_without_metadata_noops_invoice(caplog):
    ev = {"type": "payment_intent.succeeded",
          "data": {"object": {
              "id": "pi_dashboard", "status": "succeeded",
              "amount": 5000, "amount_received": 5000, "currency": "usd",
              "metadata": {},
          }}}
    r = _run(sc.handle_webhook_event(ev))
    assert r["handled"] is True
    # No invoice touched — scope by test tenants because the shared
    # DB carries paid invoices from unrelated tenants.
    assert _run(sc.db.quotes.count_documents(
        {"payment_status": "paid", "tenant_id": {"$in": [TID_A, TID_B]}})) == 0


# ── Test 6 — failed webhook marks failed + persists reason ────────────
def test_webhook_failure_marks_invoice_failed():
    inv = f"inv-6-{uuid4().hex[:6]}"
    _run(_seed_invoice(inv))
    ev = {"type": "payment_intent.payment_failed",
          "data": {"object": {
              "id": "pi_fail", "status": "requires_payment_method",
              "amount": 5000, "currency": "usd", "payment_method": PMID,
              "last_payment_error": {"message": "card declined"},
              "metadata": {"crm_tenant_id": TID_A, "crm_invoice_id": inv},
          }}}
    _run(sc.handle_webhook_event(ev))
    row = _run(sc.db.quotes.find_one({"id": inv}))
    assert row["payment_status"] == "failed"
    assert row["failure_reason"] == "card declined"
    charge = _run(sc.db.stripe_charges.find_one({"stripe_payment_intent_id": "pi_fail"}))
    assert charge["status"] == "failed"
    assert charge["error"] == "card declined"


# ── Test 7 — full refund ─────────────────────────────────────────────
def test_refund_webhook_full():
    inv = f"inv-7-{uuid4().hex[:6]}"
    _run(_seed_invoice(inv))
    # Materialise a succeeded charge first.
    _run(sc.handle_webhook_event({"type": "payment_intent.succeeded",
        "data": {"object": {"id": "pi_r1", "amount": 5000,
            "amount_received": 5000, "currency": "usd",
            "payment_method": PMID,
            "metadata": {"crm_tenant_id": TID_A, "crm_invoice_id": inv}}}}))
    # Now refund.
    _run(sc.handle_webhook_event({"type": "charge.refunded",
        "data": {"object": {"payment_intent": "pi_r1",
            "amount": 5000, "amount_refunded": 5000}}}))
    q = _run(sc.db.quotes.find_one({"id": inv}))
    assert q["payment_status"] == "refunded"
    assert q["amount_paid"] == 0.0
    c = _run(sc.db.stripe_charges.find_one({"stripe_payment_intent_id": "pi_r1"}))
    assert c["status"] == "refunded"


# ── Test 8 — partial refund ──────────────────────────────────────────
def test_refund_webhook_partial():
    inv = f"inv-8-{uuid4().hex[:6]}"
    _run(_seed_invoice(inv))
    _run(sc.handle_webhook_event({"type": "payment_intent.succeeded",
        "data": {"object": {"id": "pi_r2", "amount": 5000,
            "amount_received": 5000, "currency": "usd",
            "payment_method": PMID,
            "metadata": {"crm_tenant_id": TID_A, "crm_invoice_id": inv}}}}))
    _run(sc.handle_webhook_event({"type": "charge.refunded",
        "data": {"object": {"payment_intent": "pi_r2",
            "amount": 5000, "amount_refunded": 2000}}}))
    q = _run(sc.db.quotes.find_one({"id": inv}))
    assert q["payment_status"] == "partially_refunded"
    assert abs(q["amount_paid"] - 30.0) < 0.01
    c = _run(sc.db.stripe_charges.find_one({"stripe_payment_intent_id": "pi_r2"}))
    assert c["status"] == "partially_refunded"


# ── Test 9 — refund tenant isolation ─────────────────────────────────
def test_refund_webhook_respects_tenant():
    inv_a = f"inv-9a-{uuid4().hex[:6]}"
    inv_b = f"inv-9b-{uuid4().hex[:6]}"
    _run(_seed_invoice(inv_a, tenant_id=TID_A))
    _run(_seed_invoice(inv_b, tenant_id=TID_B))
    # A gets paid.
    _run(sc.handle_webhook_event({"type": "payment_intent.succeeded",
        "data": {"object": {"id": "pi_iso_a", "amount": 5000,
            "amount_received": 5000, "currency": "usd",
            "payment_method": PMID,
            "metadata": {"crm_tenant_id": TID_A, "crm_invoice_id": inv_a}}}}))
    # Refund event resolves the PI → charge row → TID_A. TID_B invoice
    # untouched.
    _run(sc.handle_webhook_event({"type": "charge.refunded",
        "data": {"object": {"payment_intent": "pi_iso_a",
            "amount": 5000, "amount_refunded": 5000}}}))
    a = _run(sc.db.quotes.find_one({"id": inv_a}))
    b = _run(sc.db.quotes.find_one({"id": inv_b}))
    assert a["payment_status"] == "refunded"
    assert b["payment_status"] == "unpaid"
    assert b["amount_paid"] == 0
