"""Phase 10b · Feb 2026 — credits_apply helper + public-leads ?ref= capture.

Focused unit tests for the two backend follow-ups shipped alongside
the Phase 10 UI work:
  · services.credits_apply.apply_credits_to_invoice — happy path + cap
    + zero balance no-op + double-apply idempotency guard.
  · services.credits_apply.revert_credits_from_invoice — restores
    balance + only touches draft/sent invoices.
  · POST /api/public/leads?ref=<valid> → lead + referrals row created.
  · POST /api/public/leads?ref=<invalid> → lead created, referral silently
    ignored, no referrals row inserted.
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any, Dict

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

API = "http://localhost:8001/api"

_env = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = MongoClient(_env["MONGO_URL"])[_env["DB_NAME"]]


# ═══════════════════════════ credits_apply ════════════════════════════
def test_apply_happy_path_deducts_and_writes_ledger():
    from services.credits_apply import apply_credits_to_invoice
    cust = {"id": "c1", "credits_balance_cents": 3000}
    inv = {"id": "i1", "customer_id": "c1", "total": 100.00,
             "line_items": [], "status": "draft"}
    r = apply_credits_to_invoice(inv, cust)
    assert r["credits_applied_cents"] == 3000
    assert r["updated_customer"]["credits_balance_cents"] == 0
    assert r["updated_invoice"]["credits_applied_cents"] == 3000
    assert r["updated_invoice"]["total_cents"] == 7000
    assert r["updated_invoice"]["total"] == 70.0
    lines = r["updated_invoice"]["line_items"]
    assert any(li.get("credit_line") and li["unit_price"] == -30.0 for li in lines)
    e = r["ledger_entry"]
    assert e["delta_cents"] == -3000
    assert e["source"] == "redeemed"
    assert e["invoice_id"] == "i1"


def test_apply_caps_at_invoice_total_preserving_remainder():
    from services.credits_apply import apply_credits_to_invoice
    cust = {"id": "c1", "credits_balance_cents": 5000}
    inv = {"id": "i2", "customer_id": "c1", "total": 20.00, "line_items": []}
    r = apply_credits_to_invoice(inv, cust)
    assert r["credits_applied_cents"] == 2000
    assert r["updated_customer"]["credits_balance_cents"] == 3000
    assert r["updated_invoice"]["total_cents"] == 0


def test_apply_zero_balance_is_noop():
    from services.credits_apply import apply_credits_to_invoice
    cust = {"id": "c1", "credits_balance_cents": 0}
    inv = {"id": "i3", "customer_id": "c1", "total": 100.00, "line_items": []}
    r = apply_credits_to_invoice(inv, cust)
    assert r["credits_applied_cents"] == 0
    assert r["ledger_entry"] is None
    # No credit line added.
    assert r["updated_invoice"]["line_items"] == []


def test_apply_double_apply_is_noop():
    from services.credits_apply import apply_credits_to_invoice
    cust = {"id": "c1", "credits_balance_cents": 5000}
    inv = {"id": "i4", "customer_id": "c1", "total": 100.00, "line_items": [],
             "credits_applied_cents": 1500}  # already applied earlier
    r = apply_credits_to_invoice(inv, cust)
    assert r["credits_applied_cents"] == 0
    assert r["reason"] == "already_applied"
    assert r["updated_customer"]["credits_balance_cents"] == 5000


def test_revert_restores_balance_and_removes_credit_line():
    from services.credits_apply import (
        apply_credits_to_invoice, revert_credits_from_invoice,
    )
    cust = {"id": "c1", "credits_balance_cents": 5000,
             "credits_ledger": []}
    inv = {"id": "i5", "customer_id": "c1", "total": 60.00,
             "line_items": [{"description": "Service", "unit_price": 60.0}],
             "status": "sent"}
    r1 = apply_credits_to_invoice(inv, cust)
    assert r1["credits_applied_cents"] == 5000
    # simulate persistence.
    cust2 = r1["updated_customer"]
    cust2.setdefault("credits_ledger", []).append(r1["ledger_entry"])
    inv2 = r1["updated_invoice"]
    inv2["status"] = "sent"
    # revert.
    r2 = revert_credits_from_invoice(inv2, cust2)
    assert r2["credits_applied_cents"] == 5000
    assert r2["updated_customer"]["credits_balance_cents"] == 5000
    assert r2["updated_invoice"]["credits_applied_cents"] == 0
    assert all(not li.get("credit_line") for li in r2["updated_invoice"]["line_items"])
    assert r2["ledger_entry"]["source"] == "revert"
    assert r2["ledger_entry"]["reverted_from_entry_id"] == r1["ledger_entry"]["id"]


def test_revert_refuses_paid_invoice():
    from services.credits_apply import revert_credits_from_invoice
    cust = {"id": "c1", "credits_balance_cents": 0}
    inv = {"id": "i6", "status": "paid", "credits_applied_cents": 2500,
             "line_items": [], "total": 100.00}
    r = revert_credits_from_invoice(inv, cust)
    assert r["credits_applied_cents"] == 0
    assert r["reason"] == "invoice_not_reversible"


# ═══════════════════════════ Public leads ?ref= capture ═══════════════
def _tenant_id() -> str:
    return _sync.tenants.find_one({}, {"_id": 0, "id": 1})["id"]


def _pick_customer_with_ref_code() -> Dict[str, Any]:
    """Ensure at least one customer has a referral_code we can test with."""
    tid = _tenant_id()
    cust = _sync.customers.find_one({"tenant_id": tid}, {"_id": 0})
    # If the customer doesn't have a referral_code yet, mint one.
    if not cust.get("referral_code"):
        code = f"P10R{uuid.uuid4().hex[:4].upper()}"
        _sync.customers.update_one(
            {"id": cust["id"]},
            {"$set": {"referral_code": code}},
        )
        cust["referral_code"] = code
    return cust


def _seed_widget_origin_allow():
    """Public leads intake requires origin allowlist. Add localhost."""
    tid = _tenant_id()
    _sync.tenants.update_one(
        {"id": tid},
        {"$addToSet": {"widget_allowed_domains": "http://localhost:8001"}},
    )


def test_public_leads_with_valid_ref_stamps_referrer_and_inserts_referrals_row():
    _seed_widget_origin_allow()
    ref = _pick_customer_with_ref_code()
    payload = {
        "name": f"Pytest Ref {uuid.uuid4().hex[:6]}",
        "email": "p10ref@example.com",
        "phone": "5555550100",
        "referral_code": ref["referral_code"],
    }
    r = requests.post(
        f"{API}/public/leads", json=payload, timeout=15,
        headers={"Origin": "http://localhost:8001"},
    )
    assert r.status_code == 200, r.text
    lid = r.json()["lead_id"]
    try:
        lead = _sync.leads.find_one({"id": lid}, {"_id": 0})
        assert lead["referred_by_customer_id"] == ref["id"]
        assert lead["source"].startswith("referral_from_customer:")
        # Companion referrals row inserted with status=pending_conversion.
        ref_row = _sync.referrals.find_one({"lead_id": lid}, {"_id": 0})
        assert ref_row is not None
        assert ref_row["referrer_customer_id"] == ref["id"]
        assert ref_row["status"] == "pending_conversion"
    finally:
        _sync.leads.delete_many({"id": lid})
        _sync.referrals.delete_many({"lead_id": lid})


def test_public_leads_with_invalid_ref_is_silent_ignore():
    _seed_widget_origin_allow()
    payload = {
        "name": f"Pytest Bad Ref {uuid.uuid4().hex[:6]}",
        "email": "p10bad@example.com",
        "phone": "5555550101",
        "referral_code": "ZZZ99999NOPE",
    }
    r = requests.post(
        f"{API}/public/leads", json=payload, timeout=15,
        headers={"Origin": "http://localhost:8001"},
    )
    # Silent ignore — MUST still 200 (invalid codes never block a real inquiry).
    assert r.status_code == 200, r.text
    lid = r.json()["lead_id"]
    try:
        lead = _sync.leads.find_one({"id": lid}, {"_id": 0})
        assert lead["referred_by_customer_id"] is None
        assert lead["source"] == "website_form"
        # No referrals row was inserted.
        assert _sync.referrals.find_one({"lead_id": lid}) is None
    finally:
        _sync.leads.delete_many({"id": lid})


def test_public_leads_with_query_param_ref_matches_body_field():
    _seed_widget_origin_allow()
    ref = _pick_customer_with_ref_code()
    payload = {
        "name": f"Pytest QParam {uuid.uuid4().hex[:6]}",
        "email": "p10qparam@example.com",
    }
    r = requests.post(
        f"{API}/public/leads?ref={ref['referral_code']}",
        json=payload, timeout=15,
        headers={"Origin": "http://localhost:8001"},
    )
    assert r.status_code == 200
    lid = r.json()["lead_id"]
    try:
        lead = _sync.leads.find_one({"id": lid}, {"_id": 0})
        assert lead["referred_by_customer_id"] == ref["id"]
    finally:
        _sync.leads.delete_many({"id": lid})
        _sync.referrals.delete_many({"lead_id": lid})
