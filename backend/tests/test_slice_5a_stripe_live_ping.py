"""Phase 5A follow-up · Feb 2026 — Stripe live-ping health-check.

Covers:
    * happy path — stubbed Account.retrieve returns 200 with account fields
    * failure path — stubbed Account.retrieve raises AuthenticationError,
      endpoint returns 200 with ok=false + error_type populated
    * RBAC — tech, customer get 403
    * masking — response never echoes ``sk_live_``, ``sk_test_``,
      ``rk_live_``, ``rk_test_``, or ``whsec_``.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone

import jwt
import pytest
import requests

API = "http://localhost:8001/api"


def _jwt_secret() -> str:
    from dotenv import load_dotenv
    load_dotenv("/app/backend/.env")
    return os.environ["JWT_SECRET"]


def _mk_token(user_id: str, role: str) -> str:
    return jwt.encode(
        {"sub": user_id, "email": f"{user_id}@ex.com", "role": role,
         "exp": datetime.now(timezone.utc) + timedelta(hours=2)},
        _jwt_secret(), algorithm="HS256",
    )


@pytest.fixture(scope="module", autouse=True)
def stubs():
    r = requests.post(f"{API}/dev/_phase4b_stub_stripe", timeout=15)
    assert r.status_code == 200
    yield
    requests.post(f"{API}/dev/_phase4b_unstub_stripe", timeout=15)


def _hdr(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}"}


def _login_admin() -> str:
    r = requests.post(f"{API}/auth/login",
                        json={"email": "admin@aquaterra.com",
                                "password": "password123"}, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def test_live_ping_ok_when_account_retrieve_succeeds():
    # Ensure stub is in "ok" mode.
    requests.post(f"{API}/dev/_phase4b_stub_account_ok", timeout=15)
    tok = _login_admin()
    r = requests.post(f"{API}/dev/stripe-live-ping", headers=_hdr(tok), timeout=15)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["ok"] is True
    assert j["account_id"] == "acct_test_phase4b_ok"
    assert j["account_country"] == "US"
    assert j["charges_enabled"] is True
    assert j["payouts_enabled"] is True
    assert j["details_submitted"] is True
    assert j["mode"] in ("live", "test")
    # Never leak secret keys
    body = json.dumps(j)
    for banned in ("sk_live_", "sk_test_", "rk_live_", "rk_test_", "whsec_"):
        assert banned not in body, f"leaked key prefix: {banned}"


def test_live_ping_returns_ok_false_on_auth_error():
    requests.post(f"{API}/dev/_phase4b_stub_account_raise", timeout=15)
    try:
        tok = _login_admin()
        r = requests.post(f"{API}/dev/stripe-live-ping", headers=_hdr(tok), timeout=15)
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["ok"] is False
        assert j["error_type"] == "AuthenticationError"
        assert "Invalid API Key" in j["error_message"]
        # Message should have sk_live_ prefix masked
        assert "sk_live_" not in j["error_message"]
        assert j["mode"] in ("live", "test")
    finally:
        requests.post(f"{API}/dev/_phase4b_stub_account_ok", timeout=15)


def test_live_ping_denies_technician():
    async def _tid():
        from motor.motor_asyncio import AsyncIOMotorClient
        from dotenv import load_dotenv
        load_dotenv("/app/backend/.env")
        import asyncio
        db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ.get("DB_NAME", "aquaterra")]
        row = await db.users.find_one({"email": "mike@aquaterra.com"}, {"_id": 0, "id": 1})
        return row["id"] if row else None
    import asyncio
    uid = asyncio.new_event_loop().run_until_complete(_tid())
    if not uid:
        pytest.skip("mike@aquaterra.com missing")
    tok = _mk_token(uid, "technician")
    r = requests.post(f"{API}/dev/stripe-live-ping", headers=_hdr(tok), timeout=15)
    assert r.status_code == 403


def test_live_ping_denies_customer():
    async def _cid():
        from motor.motor_asyncio import AsyncIOMotorClient
        from dotenv import load_dotenv
        load_dotenv("/app/backend/.env")
        import asyncio
        db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ.get("DB_NAME", "aquaterra")]
        row = await db.users.find_one({"email": "customer@aquaterra.com"}, {"_id": 0, "id": 1})
        return row["id"] if row else None
    import asyncio
    uid = asyncio.new_event_loop().run_until_complete(_cid())
    if not uid:
        pytest.skip("customer@aquaterra.com missing")
    tok = _mk_token(uid, "customer")
    r = requests.post(f"{API}/dev/stripe-live-ping", headers=_hdr(tok), timeout=15)
    assert r.status_code == 403
