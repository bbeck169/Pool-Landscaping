"""Feb-2026 · Business Signup SP1 — end-to-end route tests.

Uses HTTP ``requests`` against the supervisor-managed backend on
``localhost:8001`` (the codebase convention — avoids the Motor
loop-binding trap that catches ``TestClient`` on Python 3.11).
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


os.environ.setdefault("ALLOW_TEST_HOOKS", "1")
_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = MongoClient(_ENV["MONGO_URL"])[_ENV["DB_NAME"]]
API = "http://localhost:8001/api"


def _drop_signup_email(email: str) -> None:
    user = _sync.users.find_one({"email": email.lower()})
    if user:
        _sync.tenants.delete_many({"id": user.get("tenant_id")})
        _sync.users.delete_many({"id": user["id"]})


@pytest.fixture(autouse=True)
def _clean_state():
    """Wipe rate-limit windows before each test (in-process; the
    supervisor server owns the rate-limit state, so we need to reach
    into it via a test-only reset hook exposed by the router).
    Since the tests hit a separate process, we use unique emails per
    test to avoid rate-limit collision. No rate-limit reset is
    needed for tests that don't exceed 5 hits."""
    yield


def _valid_payload(**overrides: Any) -> Dict[str, Any]:
    body = {
        "business_name":            "Vistancia Pools",
        "admin_name":               "Diego Rivera",
        "admin_email":              f"diego-{uuid.uuid4().hex[:6]}@vistancia-signup-test.example",
        "admin_password":           "correcthorse42battery",
        "admin_phone":              "+15551234567",
        # SP3 · Feb-2026 — canonical singular ``"pool"`` (D1 source
        # of truth). ``"pools"`` still works via alias-normalize but
        # the payload uses canonical to keep the happy path clean.
        "primary_industry":         "pool",
        "timezone":                 "America/Phoenix",
        "country":                  "US",
        "stripe_payment_method_id": "pm_test_1",
    }
    body.update(overrides)
    return body


# ── Happy path ────────────────────────────────────────────────────

def test_signup_happy_path_creates_tenant_and_admin():
    payload = _valid_payload()
    email = payload["admin_email"]
    _drop_signup_email(email)
    r = requests.post(f"{API}/signup", json=payload, timeout=15)
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["email_verification_sent_to"] == email.lower()
    assert data["onboarding_step"] == 1
    assert data["billing_status"] == "pending_stripe_config"

    user = _sync.users.find_one({"email": email.lower()}, {"_id": 0})
    assert user is not None
    assert user["role"] == "admin"
    assert user["password_hash"]
    assert user["phone"] == "+15551234567"
    tenant = _sync.tenants.find_one({"id": user["tenant_id"]}, {"_id": 0})
    assert tenant["email_verified"] is False
    assert tenant["timezone"] == "America/Phoenix"
    assert tenant["country"] == "US"
    assert tenant["primary_industry"] == "pool"
    assert "pool" in tenant["industries"]
    assert tenant["onboarding_step"] == 1
    assert tenant["onboarding_completed_at"] is None
    _drop_signup_email(email)


# ── Validation ────────────────────────────────────────────────────

@pytest.mark.parametrize("field,bad_value,code", [
    ("admin_password",   "short",             "weak_password"),
    ("admin_password",   "onlyletters!!!",    "weak_password"),
    ("admin_password",   "1234567890123",     "weak_password"),
    ("primary_industry", "made_up_slug",      "invalid_industry"),
    ("timezone",         "Not/A/Zone",        "invalid_timezone"),
    ("country",          "ZZ",                "invalid_country"),
])
def test_signup_validation_errors(field, bad_value, code):
    payload = _valid_payload()
    payload[field] = bad_value
    r = requests.post(f"{API}/signup", json=payload, timeout=15)
    assert r.status_code == 400, r.text
    body = r.json()
    detail = body.get("detail") if isinstance(body, dict) else body
    assert isinstance(detail, dict), body
    assert detail.get("code") == code


def test_signup_email_normalized_to_lowercase():
    payload = _valid_payload(
        admin_email=f"MixedCase-Signup-{uuid.uuid4().hex[:6]}@t.example"
    )
    _drop_signup_email(payload["admin_email"])
    r = requests.post(f"{API}/signup", json=payload, timeout=15)
    assert r.status_code == 201
    assert r.json()["email_verification_sent_to"] == payload["admin_email"].lower()
    _drop_signup_email(payload["admin_email"])


# ── Email verification ────────────────────────────────────────────

def test_signup_email_verification_flow():
    from services.signup_verify_tokens import mint_signup_verify_token
    payload = _valid_payload(
        admin_email=f"verify-flow-{uuid.uuid4().hex[:6]}@t.example"
    )
    _drop_signup_email(payload["admin_email"])
    r = requests.post(f"{API}/signup", json=payload, timeout=15)
    assert r.status_code == 201
    data = r.json()
    token = mint_signup_verify_token(
        tenant_id=data["tenant_id"],
        admin_user_id=data["admin_user_id"],
        admin_email=payload["admin_email"].lower(),
    )
    v = requests.post(f"{API}/signup/verify", params={"token": token},
                        timeout=15)
    assert v.status_code == 200, v.text
    assert v.json()["verified"] is True
    assert v.json()["redirect_to"] == "/onboarding"
    tenant = _sync.tenants.find_one({"id": data["tenant_id"]}, {"_id": 0})
    assert tenant["email_verified"] is True
    _drop_signup_email(payload["admin_email"])


def test_signup_verify_rejects_bad_token():
    r = requests.post(f"{API}/signup/verify",
                        params={"token": "obviously.invalid.token"},
                        timeout=15)
    assert r.status_code == 401


def test_signup_verify_is_idempotent():
    from services.signup_verify_tokens import mint_signup_verify_token
    payload = _valid_payload(
        admin_email=f"idem-verify-{uuid.uuid4().hex[:6]}@t.example"
    )
    _drop_signup_email(payload["admin_email"])
    r = requests.post(f"{API}/signup", json=payload, timeout=15)
    data = r.json()
    token = mint_signup_verify_token(
        tenant_id=data["tenant_id"],
        admin_user_id=data["admin_user_id"],
        admin_email=payload["admin_email"].lower(),
    )
    first = requests.post(f"{API}/signup/verify",
                            params={"token": token}, timeout=15)
    second = requests.post(f"{API}/signup/verify",
                             params={"token": token}, timeout=15)
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["verified"] is True
    _drop_signup_email(payload["admin_email"])


# ── Idempotency (option b — resend on duplicate unverified email) ──

def test_duplicate_signup_while_unverified_resends_token():
    email = f"dup-resend-{uuid.uuid4().hex[:6]}@t.example"
    _drop_signup_email(email)
    r1 = requests.post(f"{API}/signup",
                          json=_valid_payload(admin_email=email), timeout=15)
    assert r1.status_code == 201
    tid_before = r1.json()["tenant_id"]
    r2 = requests.post(f"{API}/signup",
                          json=_valid_payload(admin_email=email), timeout=15)
    assert r2.status_code == 201
    body = r2.json()
    assert body["tenant_id"] == tid_before
    assert body["admin_user_id"] == r1.json()["admin_user_id"]
    assert body.get("resent") is True
    _drop_signup_email(email)


def test_duplicate_signup_after_verify_returns_409():
    email = f"dup-verified-{uuid.uuid4().hex[:6]}@t.example"
    _drop_signup_email(email)
    r = requests.post(f"{API}/signup",
                        json=_valid_payload(admin_email=email), timeout=15)
    data = r.json()
    _sync.tenants.update_one(
        {"id": data["tenant_id"]},
        {"$set": {"email_verified": True}},
    )
    dup = requests.post(f"{API}/signup",
                            json=_valid_payload(admin_email=email), timeout=15)
    assert dup.status_code == 409
    detail = dup.json().get("detail")
    assert isinstance(detail, dict)
    assert detail["code"] == "email_already_registered"
    _drop_signup_email(email)
