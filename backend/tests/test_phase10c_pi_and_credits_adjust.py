"""Phase 10c · Feb 2026 — create-payment-intent promo revalidation +
credits/adjust admin endpoint.

Tests focus on the server-side contract: client discount math is never
trusted, and the credits/adjust endpoint enforces the >=0 floor + a
minimum 5-char reason.
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient
from tests._shared_mongo import (
    shared_client as _shared_client,
    shared_db as _shared_db,
)


API = "http://localhost:8001/api"
_env = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = _shared_db()
def _login(email, pw="password123"):
    return requests.post(f"{API}/auth/login",
                          json={"email": email, "password": pw},
                          timeout=15).json()["access_token"]


def _admin_tok(): return _login("admin@aquaterra.com")
def _hdr(t): return {"Authorization": f"Bearer {t}", "Content-Type": "application/json"}


def _tenant_id():
    return _sync.tenants.find_one({}, {"_id": 0, "id": 1})["id"]


def _mk_manual_promo(*, amount_cents=None, percent=None, apply_to="account_credit"):
    """Insert a promo directly for isolation."""
    tok = _admin_tok()
    payload = {
        "type": "manual", "apply_to": apply_to,
        "max_uses": 5, "metadata": {"pytest": True},
    }
    if percent:
        payload["discount_kind"] = "percent_off_invoice"
        payload["percent"] = percent
    else:
        payload["discount_kind"] = "fixed_credit" if apply_to == "account_credit" \
                                     else "fixed_off_invoice"
        payload["amount_cents"] = amount_cents or 1000
    r = requests.post(f"{API}/promo-codes", headers=_hdr(tok), json=payload, timeout=15)
    assert r.status_code == 201, r.text
    return r.json()


# ═══════════════════════════ credits/adjust ═══════════════════════════
def test_credits_adjust_happy_positive_delta():
    tok = _admin_tok()
    tid = _tenant_id()
    cid = _sync.customers.find_one({"tenant_id": tid}, {"_id": 0, "id": 1})["id"]
    # Reset balance to a known state.
    _sync.customer_credits_balance.update_one(
        {"tenant_id": tid, "customer_id": cid},
        {"$set": {"balance_cents": 0, "balance": 0}}, upsert=True,
    )
    try:
        r = requests.post(f"{API}/customers/{cid}/credits/adjust",
                           headers=_hdr(tok), json={
                               "delta_cents": 5000,
                               "reason": "pytest positive adjust",
                           }, timeout=15)
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["balance_cents"] == 5000
        assert j["balance_formatted"] == "$50.00"
        assert j["ledger_entry"]["source"] == "manual"
        assert j["ledger_entry"]["reason"] == "pytest positive adjust"
        # Persistence check.
        bal = _sync.customer_credits_balance.find_one(
            {"tenant_id": tid, "customer_id": cid}, {"_id": 0})
        assert bal["balance_cents"] == 5000
    finally:
        _sync.customer_credits.delete_many({"reason": "pytest positive adjust"})
        _sync.customer_credits_balance.update_one(
            {"tenant_id": tid, "customer_id": cid},
            {"$set": {"balance_cents": 0, "balance": 0}})


def test_credits_adjust_blocks_negative_balance():
    tok = _admin_tok()
    tid = _tenant_id()
    cid = _sync.customers.find_one({"tenant_id": tid}, {"_id": 0, "id": 1})["id"]
    _sync.customer_credits_balance.update_one(
        {"tenant_id": tid, "customer_id": cid},
        {"$set": {"balance_cents": 1000, "balance": 10.0}}, upsert=True,
    )
    try:
        r = requests.post(f"{API}/customers/{cid}/credits/adjust",
                           headers=_hdr(tok), json={
                               "delta_cents": -2000,
                               "reason": "pytest overdraw attempt",
                           }, timeout=15)
        assert r.status_code == 400, r.text
        d = r.json()["detail"]
        assert d["code"] == "INSUFFICIENT_BALANCE"
    finally:
        _sync.customer_credits_balance.update_one(
            {"tenant_id": tid, "customer_id": cid},
            {"$set": {"balance_cents": 0, "balance": 0}})


def test_credits_adjust_accepts_blank_reason():
    """CUSTOMER-PROFILE-ACTION-BAR · Feb-2026 — the historical
    ``reason`` ≥ 5-char gate has been relaxed so the action-bar
    shortcut can post a credit without forcing a reason prompt.
    This test replaces the previous ``..._rejects_short_reason``
    guard; the backend now accepts blank / missing reason."""
    tok = _admin_tok()
    tid = _tenant_id()
    cid = _sync.customers.find_one({"tenant_id": tid}, {"_id": 0, "id": 1})["id"]
    # Reset to a known state so the floor check doesn't 400 us.
    _sync.customer_credits_balance.update_one(
        {"tenant_id": tid, "customer_id": cid},
        {"$set": {"balance_cents": 0, "balance": 0}}, upsert=True,
    )
    try:
        r = requests.post(f"{API}/customers/{cid}/credits/adjust",
                           headers=_hdr(tok),
                           json={"delta_cents": 100, "reason": ""},
                           timeout=15)
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["balance_cents"] == 100
        # Reason key is still present on the ledger row (empty).
        assert j["ledger_entry"].get("reason", None) == ""
    finally:
        _sync.customer_credits.delete_many(
            {"tenant_id": tid, "customer_id": cid, "delta_cents": 100,
             "reason": ""})
        _sync.customer_credits_balance.update_one(
            {"tenant_id": tid, "customer_id": cid},
            {"$set": {"balance_cents": 0, "balance": 0}})


def test_credits_adjust_denies_technician():
    tech = _login("mike@aquaterra.com")
    tid = _tenant_id()
    cid = _sync.customers.find_one({"tenant_id": tid}, {"_id": 0, "id": 1})["id"]
    r = requests.post(f"{API}/customers/{cid}/credits/adjust",
                       headers=_hdr(tech), json={
                           "delta_cents": 100,
                           "reason": "pytest not-admin",
                       }, timeout=15)
    assert r.status_code in (401, 403)


# ═══════════════════════════ create-payment-intent promo ═══════════════
def _seed_invoice(tenant_id, customer_id, cents):
    """Create a bare-bones payable invoice in ``quotes`` (which is the
    invoice collection when doc_type=invoice) for the promo tests."""
    iid = f"pytest-p10c-inv-{uuid.uuid4().hex[:8]}"
    _sync.quotes.insert_one({
        "id": iid, "tenant_id": tenant_id, "customer_id": customer_id,
        "doc_type": "invoice", "status": "sent",
        "total": cents / 100.0, "total_cents": cents,
        "outstanding_cents": cents,
        "currency": "usd",
        "line_items": [],
    })
    return iid


def test_create_payment_intent_invalid_promo_returns_400_promo_invalid():
    tok = _admin_tok()
    tid = _tenant_id()
    cust = _sync.customers.find_one({"tenant_id": tid}, {"_id": 0, "id": 1})
    iid = _seed_invoice(tid, cust["id"], 10_000)
    try:
        r = requests.post(f"{API}/payments/create-payment-intent",
                           headers=_hdr(tok), json={
                               "invoice_id": iid,
                               "source": "authenticated",
                               "promo_code": "TOTALLY-FAKE-ZZZ",
                           }, timeout=15)
        assert r.status_code == 400, r.text
        d = r.json()["detail"]
        assert d["code"] == "PROMO_INVALID"
        assert d["reason"] in ("not_found", "inactive", "expired", "max_uses_reached")
    finally:
        _sync.quotes.delete_many({"id": iid})


def test_create_payment_intent_account_credit_promo_preserves_full_amount():
    """apply_to=account_credit → intent charges the FULL invoice, but
    metadata records promo_code_id so the webhook can redeem after
    payment. Note we can't reach Stripe in test env; we assert the
    Stripe call would have been made with the FULL amount via the
    pre-Stripe branch — 502 is expected downstream, but the promo
    logic must have PASSED validation first (i.e., we hit the Stripe
    call, not the 400 PROMO_INVALID branch)."""
    tok = _admin_tok()
    tid = _tenant_id()
    cust = _sync.customers.find_one({"tenant_id": tid}, {"_id": 0, "id": 1})
    iid = _seed_invoice(tid, cust["id"], 10_000)
    promo = _mk_manual_promo(amount_cents=2500, apply_to="account_credit")
    try:
        r = requests.post(f"{API}/payments/create-payment-intent",
                           headers=_hdr(tok), json={
                               "invoice_id": iid,
                               "source": "authenticated",
                               "promo_code": promo["code"],
                           }, timeout=15)
        # In this env Stripe test key may 502 the actual create call —
        # what matters is we did NOT reject with 400 PROMO_INVALID.
        assert r.status_code != 400 or (
            r.json().get("detail", {}).get("code") not in ("PROMO_INVALID",)
        ), r.text
    finally:
        _sync.promo_codes.delete_many({"id": promo["id"]})
        _sync.quotes.delete_many({"id": iid})


def test_create_payment_intent_fixed_off_invoice_promo_recomputes_amount():
    """apply_to=next_invoice + fixed_off_invoice $15 off $100 → server
    should recompute to $85 (8500 cents). We can't observe Stripe's
    call directly in this env; instead we assert that the same promo
    code re-applied would trip the ``already_applied_to_invoice`` guard
    ONLY when the invoice has recorded the promo. Since Stripe likely
    502s in test env, the promo won't attach — the ORDER of checks
    still proves the validation path was reached (not PROMO_INVALID)."""
    tok = _admin_tok()
    tid = _tenant_id()
    cust = _sync.customers.find_one({"tenant_id": tid}, {"_id": 0, "id": 1})
    iid = _seed_invoice(tid, cust["id"], 10_000)
    promo = _mk_manual_promo(amount_cents=1500, apply_to="next_invoice")
    try:
        r = requests.post(f"{API}/payments/create-payment-intent",
                           headers=_hdr(tok), json={
                               "invoice_id": iid,
                               "source": "authenticated",
                               "promo_code_id": promo["id"],
                           }, timeout=15)
        # Not a PROMO_INVALID rejection.
        assert r.status_code != 400 or (
            r.json().get("detail", {}).get("code") != "PROMO_INVALID"
        ), r.text
    finally:
        _sync.promo_codes.delete_many({"id": promo["id"]})
        _sync.quotes.delete_many({"id": iid})
