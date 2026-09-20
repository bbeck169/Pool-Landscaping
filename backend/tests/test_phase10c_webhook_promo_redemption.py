"""Phase 10c · Feb 2026 — Webhook-side promo redemption + refund revert.

Exercises ``_phase10_redeem_promo_on_success`` and
``_phase10_revert_promo_on_full_refund`` directly (no Stripe wire calls
needed). Ensures:
  * account_credit path adds to ``customer_credits_balance`` and
    inserts a ``customer_credits`` ledger row.
  * Repeated ``payment_intent.succeeded`` for the same PI is a no-op
    (idempotency guard).
  * Full refund reverts the credit + decrements ``uses_count``.
  * Partial refund is a no-op.
"""
from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

import pytest
from dotenv import dotenv_values
from pymongo import MongoClient
from tests._shared_mongo import (
    shared_client as _shared_client,
    shared_db as _shared_db,
)


from tests._shared_loop import run as _run

_env = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = _shared_db()
_TENANT_ID = _sync.tenants.find_one({}, {"_id": 0, "id": 1})["id"]


def _mk_promo(*, apply_to, amount_cents=None, discount_kind=None):
    pid = f"pytest-p10c-webhook-promo-{uuid.uuid4().hex[:8]}"
    code = f"WHKP{uuid.uuid4().hex[:6].upper()}"
    _sync.promo_codes.insert_one({
        "id": pid, "tenant_id": _TENANT_ID, "code": code,
        "type": "manual",
        "discount_kind": discount_kind or ("fixed_credit"
            if apply_to == "account_credit" else "fixed_off_invoice"),
        "apply_to": apply_to,
        "amount_cents": amount_cents,
        "max_uses": 5, "uses_count": 0, "is_active": True,
        "metadata": {"pytest": True},
    })
    return pid, code


def _mk_customer():
    cid = f"pytest-p10c-cust-{uuid.uuid4().hex[:8]}"
    _sync.customers.insert_one({
        "id": cid, "tenant_id": _TENANT_ID, "name": "Webhook Redemption",
        "email": "webhook@pytest.local",
    })
    return cid


def _mk_invoice(customer_id, cents=10_000):
    iid = f"pytest-p10c-inv-{uuid.uuid4().hex[:8]}"
    _sync.quotes.insert_one({
        "id": iid, "tenant_id": _TENANT_ID, "customer_id": customer_id,
        "doc_type": "invoice", "status": "sent",
        "total": cents / 100.0, "total_cents": cents,
        "outstanding_cents": cents, "currency": "usd",
        "line_items": [],
    })
    return iid


def _cleanup(*, promo_id=None, customer_id=None, invoice_id=None, pi_id=None):
    if promo_id:
        _sync.promo_codes.delete_many({"id": promo_id})
    if customer_id:
        _sync.customers.delete_many({"id": customer_id})
        _sync.customer_credits.delete_many({"customer_id": customer_id})
        _sync.customer_credits_balance.delete_many({"customer_id": customer_id})
    if invoice_id:
        _sync.quotes.delete_many({"id": invoice_id})
    if pi_id:
        _sync.promo_redemptions_live.delete_many({"payment_intent_id": pi_id})
        _sync.stripe_payments_live.delete_many({"payment_intent_id": pi_id})



def test_webhook_promo_redemption_account_credit_credits_customer():
    from routers.stripe_webhooks_live import _phase10_redeem_promo_on_success
    promo_id, code = _mk_promo(apply_to="account_credit", amount_cents=2500)
    cid = _mk_customer()
    iid = _mk_invoice(cid)
    pi_id = f"pi_test_{uuid.uuid4().hex[:12]}"
    try:
        obj = {
            "id": pi_id,
            "metadata": {
                "tenant_id": _TENANT_ID, "invoice_id": iid,
                "customer_id": cid,
                "promo_code_id": promo_id,
                "promo_code": code,
                "promo_apply_to": "account_credit",
                "promo_discount_cents": "2500",
            },
        }
        _run(_phase10_redeem_promo_on_success(
            obj, tenant_id=_TENANT_ID, invoice_id=iid,
            pi_id=pi_id, customer_id=cid,
        ))
        bal = _sync.customer_credits_balance.find_one(
            {"tenant_id": _TENANT_ID, "customer_id": cid}, {"_id": 0})
        assert bal["balance_cents"] == 2500
        ledger = list(_sync.customer_credits.find(
            {"tenant_id": _TENANT_ID, "customer_id": cid}, {"_id": 0}))
        assert len(ledger) == 1
        assert ledger[0]["source"] == "promo_redemption"
        assert ledger[0]["delta_cents"] == 2500
        assert ledger[0]["promo_code_id"] == promo_id
        promo = _sync.promo_codes.find_one({"id": promo_id}, {"_id": 0})
        assert promo["uses_count"] == 1
        # Idempotency — second call should be a no-op.
        _run(_phase10_redeem_promo_on_success(
            obj, tenant_id=_TENANT_ID, invoice_id=iid,
            pi_id=pi_id, customer_id=cid,
        ))
        bal2 = _sync.customer_credits_balance.find_one(
            {"tenant_id": _TENANT_ID, "customer_id": cid}, {"_id": 0})
        assert bal2["balance_cents"] == 2500  # unchanged
    finally:
        _cleanup(promo_id=promo_id, customer_id=cid, invoice_id=iid, pi_id=pi_id)



def test_webhook_full_refund_reverts_account_credit_redemption():
    from routers.stripe_webhooks_live import (
        _phase10_redeem_promo_on_success, _phase10_revert_promo_on_full_refund,
    )
    promo_id, code = _mk_promo(apply_to="account_credit", amount_cents=1500)
    cid = _mk_customer()
    iid = _mk_invoice(cid, cents=10_000)
    pi_id = f"pi_test_{uuid.uuid4().hex[:12]}"
    try:
        # 1. Redeem via succeeded webhook.
        succ_obj = {
            "id": pi_id,
            "metadata": {
                "tenant_id": _TENANT_ID, "invoice_id": iid,
                "customer_id": cid,
                "promo_code_id": promo_id,
                "promo_apply_to": "account_credit",
                "promo_discount_cents": "1500",
            },
        }
        _run(_phase10_redeem_promo_on_success(
            succ_obj, tenant_id=_TENANT_ID, invoice_id=iid,
            pi_id=pi_id, customer_id=cid,
        ))
        # Ledger row for stripe_payments_live so revert sees it.
        _sync.stripe_payments_live.insert_one({
            "id": f"pytest-{uuid.uuid4().hex[:8]}",
            "tenant_id": _TENANT_ID, "invoice_id": iid,
            "customer_id": cid, "payment_intent_id": pi_id,
            "amount_cents": 10_000, "status": "paid",
        })
        # 2. Full refund — revert.
        refund_obj = {"amount_refunded": 10_000, "payment_intent": pi_id}
        row = _sync.stripe_payments_live.find_one(
            {"payment_intent_id": pi_id}, {"_id": 0})
        _run(_phase10_revert_promo_on_full_refund(row, refund_obj))
        bal = _sync.customer_credits_balance.find_one(
            {"tenant_id": _TENANT_ID, "customer_id": cid}, {"_id": 0})
        assert bal["balance_cents"] == 0
        ledger = list(_sync.customer_credits.find(
            {"tenant_id": _TENANT_ID, "customer_id": cid},
            {"_id": 0}).sort("created_at", 1))
        assert len(ledger) == 2
        assert ledger[1]["source"] == "revert"
        assert ledger[1]["delta_cents"] == -1500
        promo = _sync.promo_codes.find_one({"id": promo_id}, {"_id": 0})
        assert promo["uses_count"] == 0
    finally:
        _cleanup(promo_id=promo_id, customer_id=cid, invoice_id=iid, pi_id=pi_id)



def test_webhook_partial_refund_does_not_revert():
    from routers.stripe_webhooks_live import (
        _phase10_redeem_promo_on_success, _phase10_revert_promo_on_full_refund,
    )
    promo_id, code = _mk_promo(apply_to="account_credit", amount_cents=1500)
    cid = _mk_customer()
    iid = _mk_invoice(cid, cents=10_000)
    pi_id = f"pi_test_{uuid.uuid4().hex[:12]}"
    try:
        obj = {
            "id": pi_id,
            "metadata": {
                "tenant_id": _TENANT_ID, "invoice_id": iid,
                "customer_id": cid, "promo_code_id": promo_id,
                "promo_apply_to": "account_credit",
                "promo_discount_cents": "1500",
            },
        }
        _run(_phase10_redeem_promo_on_success(
            obj, tenant_id=_TENANT_ID, invoice_id=iid,
            pi_id=pi_id, customer_id=cid,
        ))
        _sync.stripe_payments_live.insert_one({
            "id": f"pytest-{uuid.uuid4().hex[:8]}",
            "tenant_id": _TENANT_ID, "invoice_id": iid,
            "customer_id": cid, "payment_intent_id": pi_id,
            "amount_cents": 10_000, "status": "partially_refunded",
        })
        row = _sync.stripe_payments_live.find_one(
            {"payment_intent_id": pi_id}, {"_id": 0})
        # Partial refund (5000 of 10000) — must not revert.
        _run(_phase10_revert_promo_on_full_refund(
            row, {"amount_refunded": 5000, "payment_intent": pi_id},
        ))
        bal = _sync.customer_credits_balance.find_one(
            {"tenant_id": _TENANT_ID, "customer_id": cid}, {"_id": 0})
        assert bal["balance_cents"] == 1500
        promo = _sync.promo_codes.find_one({"id": promo_id}, {"_id": 0})
        assert promo["uses_count"] == 1
    finally:
        _cleanup(promo_id=promo_id, customer_id=cid, invoice_id=iid, pi_id=pi_id)



def test_webhook_next_invoice_promo_records_but_no_credit():
    """apply_to=next_invoice → increments uses_count + records on
    invoice, but does NOT add to the customer balance (the invoice
    total was already reduced at PI create time)."""
    from routers.stripe_webhooks_live import _phase10_redeem_promo_on_success
    promo_id, code = _mk_promo(
        apply_to="next_invoice", amount_cents=1500,
        discount_kind="fixed_off_invoice",
    )
    cid = _mk_customer()
    iid = _mk_invoice(cid, cents=10_000)
    pi_id = f"pi_test_{uuid.uuid4().hex[:12]}"
    try:
        obj = {
            "id": pi_id,
            "metadata": {
                "tenant_id": _TENANT_ID, "invoice_id": iid,
                "customer_id": cid, "promo_code_id": promo_id,
                "promo_apply_to": "next_invoice",
                "promo_discount_cents": "1500",
            },
        }
        _run(_phase10_redeem_promo_on_success(
            obj, tenant_id=_TENANT_ID, invoice_id=iid,
            pi_id=pi_id, customer_id=cid,
        ))
        bal = _sync.customer_credits_balance.find_one(
            {"tenant_id": _TENANT_ID, "customer_id": cid}, {"_id": 0})
        assert bal is None or bal.get("balance_cents", 0) == 0
        promo = _sync.promo_codes.find_one({"id": promo_id}, {"_id": 0})
        assert promo["uses_count"] == 1
        inv = _sync.quotes.find_one({"id": iid}, {"_id": 0})
        assert promo_id in (inv.get("applied_promo_code_ids") or [])
    finally:
        _cleanup(promo_id=promo_id, customer_id=cid, invoice_id=iid, pi_id=pi_id)
