"""Phase 10 · Feb 2026 — Referrals paid-window + promo codes coverage.

Covers the full Phase 10 loop end-to-end:

  · Promo code CRUD + validate + redeem
  · Uniqueness per tenant + role gates
  · Watcher happy path (30d elapsed → credit issued + ledger row +
    marketing_deliveries email + SMS)
  · Watcher skips under 30d
  · Refund inside window voids the referral
  · Dispute inside window voids the referral
  · Idempotency: repeat watcher on same eligible referral only issues once
  · Back-migration re-run inserts zero new rows
  · Merge tag resolvers for the 4 new tags
  · Manual promo redemption uses_count increments; same-invoice again → 400
"""
from __future__ import annotations

import asyncio
import os
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

API = "http://localhost:8001/api"

_BE_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_MONGO_URL = _BE_ENV.get("MONGO_URL") or os.environ.get("MONGO_URL")
_DB_NAME = _BE_ENV.get("DB_NAME") or os.environ.get("DB_NAME")
_sync_db = MongoClient(_MONGO_URL)[_DB_NAME]

from tests._shared_loop import LOOP as _LOOP, run as _run


def _login(email: str, pw: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": pw}, timeout=15)
    return r.json()["access_token"]


def _hdr(tok): return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _admin_tok() -> str: return _login("admin@aquaterra.com")


def _tenant_id() -> str:
    """The aquaterra tenant id for our sync helpers."""
    t = _sync_db.tenants.find_one({}, {"_id": 0, "id": 1})
    assert t, "no seeded tenant"
    return t["id"]


def _pick_two_customers() -> tuple:
    rows = list(_sync_db.customers.find({}, {"_id": 0, "id": 1}).limit(2))
    assert len(rows) >= 2, "need >= 2 customers"
    return rows[0]["id"], rows[1]["id"]


def _cleanup():
    tid = _tenant_id()
    _sync_db.referrals.delete_many({"tenant_id": tid, "id": {"$regex": "^pytest-p10-"}})
    _sync_db.promo_codes.delete_many({"tenant_id": tid, "metadata.pytest": True})
    _sync_db.customer_credits.delete_many({"tenant_id": tid, "note": {"$regex": "pytest-p10"}})
    _sync_db.stripe_events.delete_many({"tenant_id": tid, "source_row_id": "pytest-p10"})
    _sync_db.quotes.delete_many({"tenant_id": tid, "id": {"$regex": "^pytest-p10-"},
                                     "doc_type": "invoice"})


# ═══════════════════════════ Promo code CRUD ═════════════════════════
def test_promo_code_create_fixed_credit_uppercases_code():
    _cleanup()
    tok = _admin_tok()
    body = {"code": "friend25", "type": "manual",
             "discount_kind": "fixed_credit", "apply_to": "account_credit",
             "amount_cents": 2500, "max_uses": 5,
             "metadata": {"pytest": True}}
    r = requests.post(f"{API}/promo-codes", headers=_hdr(tok), json=body, timeout=15)
    assert r.status_code == 201, r.text
    j = r.json()
    assert j["code"] == "FRIEND25"
    assert j["discount_kind"] == "fixed_credit"
    assert j["uses_count"] == 0
    _sync_db.promo_codes.delete_many({"id": j["id"]})


def test_promo_code_duplicate_rejects_409_with_existing_id():
    _cleanup()
    tok = _admin_tok()
    code = f"dupetest{uuid.uuid4().hex[:4].upper()}"
    body = {"code": code, "discount_kind": "fixed_credit",
             "amount_cents": 1000, "metadata": {"pytest": True}}
    r1 = requests.post(f"{API}/promo-codes", headers=_hdr(tok), json=body, timeout=15)
    assert r1.status_code == 201
    r2 = requests.post(f"{API}/promo-codes", headers=_hdr(tok), json=body, timeout=15)
    assert r2.status_code == 409, r2.text
    detail = r2.json()["detail"]
    assert isinstance(detail, dict)
    assert detail["existing_promo_code_id"] == r1.json()["id"]
    _sync_db.promo_codes.delete_many({"id": r1.json()["id"]})


def test_promo_code_denies_technician():
    tech = _login("mike@aquaterra.com")
    r = requests.post(f"{API}/promo-codes", headers=_hdr(tech),
                       json={"discount_kind": "fixed_credit",
                              "amount_cents": 500}, timeout=15)
    assert r.status_code in (401, 403), r.text


def test_promo_code_validate_returns_effective_amount():
    _cleanup()
    tok = _admin_tok()
    p = requests.post(f"{API}/promo-codes", headers=_hdr(tok), json={
        "type": "manual", "discount_kind": "percent_off_invoice",
        "percent": 10, "max_uses": 3, "metadata": {"pytest": True},
    }, timeout=15).json()
    r = requests.post(f"{API}/promo-codes/validate", headers=_hdr(tok), json={
        "code": p["code"], "invoice_total_cents": 10_000,
    }, timeout=15)
    assert r.status_code == 200
    j = r.json()
    assert j["valid"] is True
    assert j["amount_cents_effective"] == 1000  # 10% of 10_000
    _sync_db.promo_codes.delete_many({"id": p["id"]})


def test_promo_code_validate_flags_expired_and_maxed():
    _cleanup()
    tok = _admin_tok()
    # Expired.
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    p1 = requests.post(f"{API}/promo-codes", headers=_hdr(tok), json={
        "discount_kind": "fixed_credit", "amount_cents": 500,
        "expires_at": past, "metadata": {"pytest": True},
    }, timeout=15).json()
    r1 = requests.post(f"{API}/promo-codes/validate", headers=_hdr(tok),
                        json={"code": p1["code"]}, timeout=15).json()
    assert r1 == {"valid": False, "reason": "expired"} or r1["reason"] == "expired"
    # Max uses reached — patch uses_count directly in mongo.
    p2 = requests.post(f"{API}/promo-codes", headers=_hdr(tok), json={
        "discount_kind": "fixed_credit", "amount_cents": 500,
        "max_uses": 1, "metadata": {"pytest": True},
    }, timeout=15).json()
    _sync_db.promo_codes.update_one({"id": p2["id"]}, {"$set": {"uses_count": 1}})
    r2 = requests.post(f"{API}/promo-codes/validate", headers=_hdr(tok),
                        json={"code": p2["code"]}, timeout=15).json()
    assert r2["reason"] == "max_uses_reached"
    _sync_db.promo_codes.delete_many({"id": {"$in": [p1["id"], p2["id"]]}})


def test_promo_code_redeem_increments_uses_and_blocks_same_invoice_twice():
    _cleanup()
    tok = _admin_tok()
    p = requests.post(f"{API}/promo-codes", headers=_hdr(tok), json={
        "discount_kind": "fixed_credit", "amount_cents": 2000,
        "max_uses": 5, "metadata": {"pytest": True},
    }, timeout=15).json()
    inv_id = f"pytest-p10-inv-{uuid.uuid4().hex[:8]}"
    tid = _tenant_id()
    # Phase 11: promo-code redeem hits db.quotes (source of truth).
    _sync_db.quotes.insert_one({
        "id": inv_id, "tenant_id": tid, "customer_id": "any",
        "total": 100.0, "doc_type": "invoice",
    })
    try:
        r1 = requests.post(f"{API}/promo-codes/redeem", headers=_hdr(tok), json={
            "code": p["code"], "invoice_id": inv_id, "invoice_total_cents": 10_000,
        }, timeout=15)
        assert r1.status_code == 200, r1.text
        j = r1.json()
        assert j["discount_cents"] == 2000
        assert j["new_invoice_total_cents"] == 8000
        # Same code, same invoice — 400.
        r2 = requests.post(f"{API}/promo-codes/redeem", headers=_hdr(tok), json={
            "code": p["code"], "invoice_id": inv_id, "invoice_total_cents": 10_000,
        }, timeout=15)
        assert r2.status_code == 400, r2.text
        assert "already applied" in r2.json().get("detail", "").lower()
        # uses_count = 1
        assert _sync_db.promo_codes.find_one({"id": p["id"]})["uses_count"] == 1
    finally:
        _sync_db.promo_codes.delete_many({"id": p["id"]})


# ═══════════════════════════ Referrals summary ═══════════════════════
def test_referrals_summary_returns_counts_by_status():
    tok = _admin_tok()
    r = requests.get(f"{API}/referrals/summary", headers=_hdr(tok), timeout=15)
    assert r.status_code == 200
    j = r.json()
    assert set(j["counts_by_status"].keys()) >= {
        "pending_conversion", "pending_paid_window", "credited", "voided",
    }
    assert "total_credited_cents" in j
    assert j["total_credited_formatted"].startswith("$")


# ═══════════════════════════ Watcher happy path + idempotency ═══════════
def _mk_ref(*, referrer_id, referred_id, first_paid_days_ago, tenant_id):
    rid = f"pytest-p10-{uuid.uuid4().hex[:8]}"
    first_paid = (
        (datetime.now(timezone.utc) - timedelta(days=first_paid_days_ago)).isoformat()
        if first_paid_days_ago is not None else None
    )
    doc = {
        "id": rid,
        "tenant_id": tenant_id,
        "referrer_customer_id": referrer_id,
        "referred_customer_id": referred_id,
        "converted_to_customer_id": referred_id,
        "status": "pending_paid_window",
        "friend_name": "Friend Frankie",
        "converted_at": (
            datetime.now(timezone.utc) - timedelta(days=(first_paid_days_ago or 0) + 1)
        ).isoformat(),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    if first_paid:
        doc["first_paid_at"] = first_paid
    _sync_db.referrals.insert_one(doc)
    return rid


def _run_watcher_for_current_tenant():
    from services.referral_watcher import run_referral_watcher
    async def _do():
        from config import db as motor_db
        tenant = await motor_db.tenants.find_one({}, {"_id": 0})
        return await run_referral_watcher(tenant)
    return _run(_do())


def test_watcher_credits_after_30d_and_writes_ledger_and_deliveries():
    _cleanup()
    tid = _tenant_id()
    referrer_id, referred_id = _pick_two_customers()
    rid = _mk_ref(referrer_id=referrer_id, referred_id=referred_id,
                    first_paid_days_ago=45, tenant_id=tid)
    # Prime the referrer's balance to a known state.
    _sync_db.customer_credits_balance.update_one(
        {"tenant_id": tid, "customer_id": referrer_id},
        {"$set": {"balance_cents": 0, "balance": 0}}, upsert=True,
    )
    try:
        res = _run_watcher_for_current_tenant()
        assert rid in res["credited"], res

        ref_after = _sync_db.referrals.find_one({"id": rid}, {"_id": 0})
        assert ref_after["status"] == "credited"
        assert ref_after["credited_at"]
        assert ref_after["credit_amount_cents"] == 2500
        assert ref_after["credited_promo_code_id"]
        # Promo code minted.
        promo = _sync_db.promo_codes.find_one(
            {"id": ref_after["credited_promo_code_id"]}, {"_id": 0})
        assert promo["type"] == "referral_reward"
        assert promo["amount_cents"] == 2500
        assert promo["code"].startswith("REF-")
        # Ledger row.
        led = _sync_db.customer_credits.find_one(
            {"referral_id": rid, "source": "referral_credit"}, {"_id": 0})
        assert led["delta_cents"] == 2500
        # Balance rolled up.
        bal = _sync_db.customer_credits_balance.find_one(
            {"tenant_id": tid, "customer_id": referrer_id}, {"_id": 0})
        assert bal["balance_cents"] == 2500
        # marketing_deliveries — email and/or sms row with the trigger tag.
        deliveries = list(_sync_db.marketing_deliveries.find({
            "tenant_id": tid,
            "trigger_entity.kind": "referral_credit_issued",
            "trigger_entity.referral_id": rid,
        }, {"_id": 0}))
        assert deliveries, "expected >= 1 delivery row for credit issuance"

        # Idempotency: run again → 0 credited.
        res2 = _run_watcher_for_current_tenant()
        assert rid not in res2["credited"]
    finally:
        # Cleanup delivered rows.
        _sync_db.marketing_deliveries.delete_many(
            {"trigger_entity.referral_id": rid})
        _sync_db.customer_credits.delete_many({"referral_id": rid})
        _sync_db.referrals.delete_many({"id": rid})
        _sync_db.promo_codes.delete_many({"metadata.referral_id": rid})


def test_watcher_skips_when_under_30_days():
    _cleanup()
    tid = _tenant_id()
    referrer_id, referred_id = _pick_two_customers()
    rid = _mk_ref(referrer_id=referrer_id, referred_id=referred_id,
                    first_paid_days_ago=10, tenant_id=tid)
    try:
        res = _run_watcher_for_current_tenant()
        assert rid not in res["credited"]
        ref = _sync_db.referrals.find_one({"id": rid}, {"_id": 0})
        assert ref["status"] == "pending_paid_window"
    finally:
        _sync_db.referrals.delete_many({"id": rid})


# ═══════════════════════════ Refund / dispute safeguard ═══════════════
def test_refund_inside_window_voids_referral():
    _cleanup()
    tid = _tenant_id()
    referrer_id, referred_id = _pick_two_customers()
    rid = _mk_ref(referrer_id=referrer_id, referred_id=referred_id,
                    first_paid_days_ago=45, tenant_id=tid)
    # Insert a stripe_events row saying the referred customer's paid
    # invoice was refunded 5 days into the window.
    first_paid = (datetime.now(timezone.utc) - timedelta(days=45)).isoformat()
    refund_at = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat()
    _sync_db.stripe_events.insert_one({
        "id": f"pytest-p10-stripe-{uuid.uuid4().hex[:6]}",
        "event_id": f"pytest-p10-evt-{uuid.uuid4().hex}",
        "tenant_id": tid, "customer_id": referred_id,
        "event_type": "charge.refunded",
        "created_at": refund_at,
    })
    try:
        res = _run_watcher_for_current_tenant()
        assert rid not in res["credited"]
        assert rid in res["voided"]
        row = _sync_db.referrals.find_one({"id": rid}, {"_id": 0})
        assert row["status"] == "voided"
        assert row["voided_reason"] == "refunded"
    finally:
        _sync_db.stripe_events.delete_many({"customer_id": referred_id,
                                              "id": {"$regex": "^pytest-p10-stripe-"}})
        _sync_db.referrals.delete_many({"id": rid})


def test_dispute_inside_window_voids_referral():
    _cleanup()
    tid = _tenant_id()
    referrer_id, referred_id = _pick_two_customers()
    rid = _mk_ref(referrer_id=referrer_id, referred_id=referred_id,
                    first_paid_days_ago=45, tenant_id=tid)
    dispute_at = (datetime.now(timezone.utc) - timedelta(days=20)).isoformat()
    _sync_db.stripe_events.insert_one({
        "id": f"pytest-p10-stripe-{uuid.uuid4().hex[:6]}",
        "event_id": f"pytest-p10-evt-{uuid.uuid4().hex}",
        "tenant_id": tid, "customer_id": referred_id,
        "event_type": "charge.dispute.created",
        "created_at": dispute_at,
    })
    try:
        res = _run_watcher_for_current_tenant()
        assert rid in res["voided"]
        row = _sync_db.referrals.find_one({"id": rid}, {"_id": 0})
        assert row["voided_reason"] == "disputed"
    finally:
        _sync_db.stripe_events.delete_many({"customer_id": referred_id,
                                              "id": {"$regex": "^pytest-p10-stripe-"}})
        _sync_db.referrals.delete_many({"id": rid})


# ═══════════════════════════ Admin re-eligible + void ═════════════════
def test_admin_can_re_eligible_a_voided_referral():
    _cleanup()
    tid = _tenant_id()
    referrer_id, referred_id = _pick_two_customers()
    rid = _mk_ref(referrer_id=referrer_id, referred_id=referred_id,
                    first_paid_days_ago=45, tenant_id=tid)
    _sync_db.referrals.update_one({"id": rid},
        {"$set": {"status": "voided", "voided_reason": "refunded"}})
    tok = _admin_tok()
    try:
        r = requests.post(f"{API}/referrals/{rid}/re-eligible",
                           headers=_hdr(tok), timeout=15)
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "pending_paid_window"
        row = _sync_db.referrals.find_one({"id": rid}, {"_id": 0})
        assert row["voided_reason"] is None
    finally:
        _sync_db.referrals.delete_many({"id": rid})


def test_admin_void_endpoint_marks_referral_voided():
    _cleanup()
    tid = _tenant_id()
    referrer_id, referred_id = _pick_two_customers()
    rid = _mk_ref(referrer_id=referrer_id, referred_id=referred_id,
                    first_paid_days_ago=5, tenant_id=tid)
    tok = _admin_tok()
    try:
        r = requests.post(f"{API}/referrals/{rid}/void", headers=_hdr(tok),
                           json={"reason": "test_manual"}, timeout=15)
        assert r.status_code == 200
        assert r.json()["status"] == "voided"
        row = _sync_db.referrals.find_one({"id": rid}, {"_id": 0})
        assert row["voided_reason"] == "test_manual"
    finally:
        _sync_db.referrals.delete_many({"id": rid})


# ═══════════════════════════ Customer credits view ═════════════════════
def test_customer_credits_endpoint_returns_balance_and_ledger():
    tok = _admin_tok()
    cid, _ = _pick_two_customers()
    tid = _tenant_id()
    _sync_db.customer_credits_balance.update_one(
        {"tenant_id": tid, "customer_id": cid},
        {"$set": {"balance_cents": 5000, "balance": 50.0}}, upsert=True)
    _sync_db.customer_credits.insert_one({
        "id": f"pytest-p10-led-{uuid.uuid4().hex[:6]}",
        "tenant_id": tid, "customer_id": cid,
        "delta_cents": 5000, "source": "referral_credit",
        "note": "pytest-p10 fixture", "created_at": datetime.now(timezone.utc).isoformat(),
    })
    try:
        r = requests.get(f"{API}/customers/{cid}/credits",
                          headers=_hdr(tok), timeout=15)
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["balance_cents"] == 5000
        assert j["balance_formatted"] == "$50.00"
        assert any(l["source"] == "referral_credit" for l in j["ledger"])
    finally:
        _sync_db.customer_credits.delete_many({"note": "pytest-p10 fixture"})


# ═══════════════════════════ Back-migration idempotency ═══════════════
def test_backmigration_second_run_inserts_zero():
    async def _do():
        from services.referral_watcher import backmigrate_legacy_referral_credits
        r1 = await backmigrate_legacy_referral_credits()
        r2 = await backmigrate_legacy_referral_credits()
        return r1, r2
    r1, r2 = _run(_do())
    assert r2 == {"upgraded": 0, "minted": 0}


# ═══════════════════════════ Merge tags ═══════════════════════════════
def test_referral_merge_tags_present_in_catalog():
    tok = _admin_tok()
    r = requests.get(f"{API}/marketing/merge-tags", headers=_hdr(tok), timeout=15).json()
    tokens = {t["token"] for t in r["categories"].get("Referrals", [])}
    assert tokens == {"REFERRAL_FRIEND_NAME", "REFERRAL_CREDIT_AMOUNT",
                       "REFERRAL_ELIGIBLE_DATE", "CUSTOMER_CREDIT_BALANCE"}


def test_referral_merge_tags_resolve_end_to_end():
    from services.marketing.merge_tags import render_template
    ctx = {
        "customer": {"credits_balance_cents": 5000, "name": "Alex Reyes"},
        "referral": {
            "friend_first_name": "Frankie",
            "credit_amount_cents": 2500,
            "eligible_at_pretty": "Aug 15, 2026",
        },
    }
    out, missing = render_template(
        "{{REFERRAL_FRIEND_NAME}} earned you {{REFERRAL_CREDIT_AMOUNT}} "
        "(eligible {{REFERRAL_ELIGIBLE_DATE}}). Your balance: "
        "{{CUSTOMER_CREDIT_BALANCE}}.", ctx,
    )
    assert out == (
        "Frankie earned you $25.00 (eligible Aug 15, 2026). Your balance: $50.00."
    )
    assert missing == []
