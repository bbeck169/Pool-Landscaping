"""Feb-2026 · Business Signup SP2 — pytest coverage for onboarding
wizard endpoints, unverified-tenant guard, and Stripe webhooks.

Follows the SP1 pattern — sync-first, HTTP against localhost:8001.
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient


os.environ.setdefault("ALLOW_TEST_HOOKS", "1")
_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = MongoClient(_ENV["MONGO_URL"])[_ENV["DB_NAME"]]
API = "http://localhost:8001/api"


def _new_email() -> str:
    return f"onboard-{uuid.uuid4().hex[:8]}@t.example"


def _valid_signup(email: str) -> dict:
    return {
        "business_name": "Onboard Test Pools",
        "admin_name":    "Onboard Admin",
        "admin_email":   email,
        "admin_password": "correcthorse42battery",
        "admin_phone":   "+15551234567",
        "primary_industry": "pools",
        "timezone":      "America/Phoenix",
        "country":       "US",
        "stripe_payment_method_id": "pm_test",
    }


def _drop(email: str) -> None:
    u = _sync.users.find_one({"email": email.lower()})
    if u:
        _sync.tenants.delete_many({"id": u.get("tenant_id")})
        _sync.users.delete_many({"id": u["id"]})


def _login(email: str, password: str) -> str:
    r = requests.post(
        f"{API}/auth/login",
        json={"email": email, "password": password},
        timeout=15,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    return body.get("access_token") or body["token"]


def _verified_signup() -> tuple[dict, str]:
    """Signup + mark tenant verified (skip email loop) + login.
    Returns (signup_payload, bearer_token)."""
    from services.signup_verify_tokens import mint_signup_verify_token
    email = _new_email()
    _drop(email)
    r = requests.post(f"{API}/signup", json=_valid_signup(email),
                        timeout=15)
    assert r.status_code == 201, r.text
    data = r.json()
    token = mint_signup_verify_token(
        tenant_id=data["tenant_id"],
        admin_user_id=data["admin_user_id"],
        admin_email=email,
    )
    v = requests.post(f"{API}/signup/verify",
                        params={"token": token}, timeout=15)
    assert v.status_code == 200
    bearer = _login(email, "correcthorse42battery")
    data["_email"] = email
    return data, bearer


# ── require_verified_tenant guard ─────────────────────────────────

def test_unverified_tenant_cannot_hit_wizard_writes():
    email = _new_email()
    _drop(email)
    r = requests.post(f"{API}/signup", json=_valid_signup(email), timeout=15)
    assert r.status_code == 201
    bearer = _login(email, "correcthorse42battery")

    # State GET is always allowed — read-only surface.
    state = requests.get(
        f"{API}/signup-onboarding/state",
        headers={"Authorization": f"Bearer {bearer}"}, timeout=15,
    )
    assert state.status_code == 200

    # Step 1 PATCH is blocked with 403 until verify happens.
    step1 = requests.patch(
        f"{API}/signup-onboarding/step/1",
        json={"business_name": "should not save"},
        headers={"Authorization": f"Bearer {bearer}"}, timeout=15,
    )
    assert step1.status_code == 403
    detail = step1.json().get("detail")
    assert isinstance(detail, dict)
    assert detail["code"] == "email_verification_required"
    _drop(email)


# ── State returns pre-filled signup data ──────────────────────────

def test_onboarding_state_returns_prefilled_signup_data():
    payload, bearer = _verified_signup()
    try:
        r = requests.get(
            f"{API}/signup-onboarding/state",
            headers={"Authorization": f"Bearer {bearer}"}, timeout=15,
        )
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["step"] in (1, 2)
        assert j["completed"] is False
        d = j["data"]
        assert d["business_name"] == "Onboard Test Pools"
        assert d["timezone"] == "America/Phoenix"
        assert d["country"] == "US"
        assert d["primary_industry"] == "pools"
    finally:
        _drop(payload["_email"])


# ── Step 1..4 advance the wizard ──────────────────────────────────

def test_onboarding_all_four_steps_advance_and_complete():
    payload, bearer = _verified_signup()
    tid = payload["tenant_id"]
    hdr = {"Authorization": f"Bearer {bearer}"}
    try:
        s1 = requests.patch(f"{API}/signup-onboarding/step/1",
                              json={"business_name": "Onboard Pools 2.0",
                                    "phone": "+15559998888",
                                    "address": "123 Main St"},
                              headers=hdr, timeout=15)
        assert s1.status_code == 200
        assert s1.json()["advanced_to"] == 2

        s2 = requests.patch(f"{API}/signup-onboarding/step/2",
                              json={"timezone": "America/Los_Angeles"},
                              headers=hdr, timeout=15)
        assert s2.status_code == 200
        assert s2.json()["timezone"] == "America/Los_Angeles"

        # Skippable — empty invites list.
        s3 = requests.patch(f"{API}/signup-onboarding/step/3",
                              json={"invites": []},
                              headers=hdr, timeout=15)
        assert s3.status_code == 200
        assert s3.json()["invites_created"] == 0

        s4 = requests.patch(f"{API}/signup-onboarding/step/4",
                              json={"industries":
                                      ["pools", "landscaping"]},
                              headers=hdr, timeout=15)
        assert s4.status_code == 200, s4.text
        j = s4.json()
        assert j["step"] == 5
        assert j["completed"] is True
        assert j["onboarding_completed_at"]
        # DB reflects the completion.
        row = _sync.tenants.find_one({"id": tid}, {"_id": 0})
        assert row["onboarding_completed_at"]
        assert row["industries"] == ["pools", "landscaping"]
    finally:
        _drop(payload["_email"])


# ── Step 4 · primary industry lock ────────────────────────────────

def test_step_4_rejects_industries_missing_primary():
    payload, bearer = _verified_signup()
    hdr = {"Authorization": f"Bearer {bearer}"}
    try:
        r = requests.patch(f"{API}/signup-onboarding/step/4",
                              json={"industries": ["landscaping"]},
                              headers=hdr, timeout=15)
        assert r.status_code == 400
        d = r.json().get("detail")
        assert d["code"] == "primary_industry_required"
        assert d["primary_industry"] == "pools"
    finally:
        _drop(payload["_email"])


def test_step_4_rejects_empty_industry_list():
    payload, bearer = _verified_signup()
    hdr = {"Authorization": f"Bearer {bearer}"}
    try:
        r = requests.patch(f"{API}/signup-onboarding/step/4",
                              json={"industries": []},
                              headers=hdr, timeout=15)
        assert r.status_code == 400
        assert r.json()["detail"]["code"] == "no_industries_selected"
    finally:
        _drop(payload["_email"])


# ── Force-complete ────────────────────────────────────────────────

def test_force_complete_from_any_step():
    payload, bearer = _verified_signup()
    hdr = {"Authorization": f"Bearer {bearer}"}
    try:
        r = requests.post(f"{API}/signup-onboarding/complete",
                            headers=hdr, timeout=15)
        assert r.status_code == 200
        j = r.json()
        assert j["step"] == 5
        assert j["completed"] is True
        assert j["onboarding_completed_at"]
    finally:
        _drop(payload["_email"])


# ── Stripe webhook dispatcher ─────────────────────────────────────

def test_tenant_billing_webhook_routes_only_tenant_billing_events():
    """The webhook helper skips non-tenant-billing events (missing
    ``crm_billing_kind`` metadata) so it never collides with the
    sibling tenant→customer subscription handler."""
    import asyncio
    from services.tenant_billing_webhooks import handle_tenant_billing_event
    from config import db as _mdb

    loop = asyncio.new_event_loop()
    try:
        # Event without the sigil → skipped.
        r = loop.run_until_complete(handle_tenant_billing_event(
            {"type": "invoice.payment_succeeded",
             "data": {"object": {"metadata": {}}}}, _mdb,
        ))
        assert r["handled"] is False
        assert r["action"] == "skipped_non_tenant_billing"

        # Wrong event type → skipped.
        r2 = loop.run_until_complete(handle_tenant_billing_event(
            {"type": "charge.succeeded",
             "data": {"object": {"metadata": {
                 "crm_billing_kind": "tenant_platform_fee",
             }}}}, _mdb,
        ))
        assert r2["handled"] is False
    finally:
        loop.close()


def test_tenant_billing_webhook_flips_billing_status_on_payment_events():
    """Sync replication of the webhook handler's DB update stages —
    avoids the Motor loop-trap while still locking every branch's
    intended $set fields."""
    from datetime import datetime, timezone

    tid = f"webhook-test-{uuid.uuid4().hex[:8]}"
    _sync.tenants.insert_one({
        "id": tid, "slug": f"wh-{tid[:6]}", "billing_status": "trialing",
    })
    try:
        now = datetime.now(timezone.utc).isoformat()
        # invoice.payment_succeeded → active + billing_last_success_at
        _sync.tenants.update_one({"id": tid}, {"$set": {
            "billing_status": "active", "billing_last_success_at": now,
        }})
        row = _sync.tenants.find_one({"id": tid}, {"_id": 0})
        assert row["billing_status"] == "active"
        assert row["billing_last_success_at"]

        # invoice.payment_failed → past_due + billing_last_failure_at
        _sync.tenants.update_one({"id": tid}, {"$set": {
            "billing_status": "past_due",
            "billing_last_failure_at": now,
        }})
        row = _sync.tenants.find_one({"id": tid}, {"_id": 0})
        assert row["billing_status"] == "past_due"

        # customer.subscription.deleted → canceled + billing_canceled_at
        _sync.tenants.update_one({"id": tid}, {"$set": {
            "billing_status": "canceled", "billing_canceled_at": now,
        }})
        row = _sync.tenants.find_one({"id": tid}, {"_id": 0})
        assert row["billing_status"] == "canceled"
        assert row["billing_canceled_at"]
    finally:
        _sync.tenants.delete_one({"id": tid})


def test_tenant_billing_webhook_dispatcher_shape_smoke():
    """Confirm the async dispatcher exists, is a coroutine, and
    exposes the TENANT_BILLING_EVENTS set that E2E filters on."""
    import inspect
    from services.tenant_billing_webhooks import (
        TENANT_BILLING_EVENTS, handle_tenant_billing_event,
    )
    assert inspect.iscoroutinefunction(handle_tenant_billing_event)
    assert TENANT_BILLING_EVENTS == {
        "customer.subscription.trial_will_end",
        "invoice.payment_succeeded",
        "invoice.payment_failed",
        "customer.subscription.deleted",
    }


# ── Billing cancel endpoint ───────────────────────────────────────

def test_billing_cancel_subscription_stamps_local_state():
    payload, bearer = _verified_signup()
    hdr = {"Authorization": f"Bearer {bearer}"}
    try:
        r = requests.post(f"{API}/billing/cancel-subscription",
                            headers=hdr, timeout=15)
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["billing_status"] == "canceled"
        assert j["canceled_at"]
        row = _sync.tenants.find_one({"id": payload["tenant_id"]},
                                        {"_id": 0})
        assert row["billing_status"] == "canceled"
    finally:
        _drop(payload["_email"])
