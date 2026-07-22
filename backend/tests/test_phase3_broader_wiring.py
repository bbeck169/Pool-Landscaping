"""Feb 2026 · Phase 3 — Twilio/Resend broader wiring tests."""
from __future__ import annotations

import asyncio
import os
import uuid

import pytest
import requests

API = "http://localhost:8001/api"


def _login(email, pw="password123"):
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": pw}, timeout=30)
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def admin_headers():
    return {"Authorization": f"Bearer {_login('admin@aquaterra.com')}"}


@pytest.fixture(scope="module")
def customer_headers():
    return {"Authorization": f"Bearer {_login('customer@aquaterra.com')}"}


_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)


def _run(coro):
    return _LOOP.run_until_complete(coro)


def _db():
    from motor.motor_asyncio import AsyncIOMotorClient
    from dotenv import load_dotenv
    load_dotenv("/app/backend/.env")
    return AsyncIOMotorClient(os.environ["MONGO_URL"],
                               io_loop=_LOOP)[os.environ["DB_NAME"]]


# ── Env / config assertions ─────────────────────────────────────────
def test_from_address_is_plofv():
    """The Resend adapter default From must be cs@plofv.com."""
    import sys
    sys.modules.pop("services.email.resend_adapter", None)
    from services.email.resend_adapter import ResendEmailAdapter
    a = ResendEmailAdapter()
    assert a.from_addr == "cs@plofv.com"
    assert a.from_name == "Pool & Landscaping of Vistancia"


# ── M2 SMS dispatch — code-inspection guard ─────────────────────────
def test_m2_sms_routes_through_rc_adapter():
    src = open("/app/backend/services/marketing_campaigns.py").read()
    assert "from services.sms.rc_adapter import send" in src
    assert '"m2:' in src or "'m2:" in src  # idempotency key namespace


# ── Widget escalation SMS wiring ────────────────────────────────────
def test_widget_escalation_sms_wiring():
    src = open("/app/backend/routers/widget_chat.py").read()
    assert "sms_escalation_recipients" in src
    assert "rc_adapter" in src


# ── Referral conversion end-to-end → transactional delivery rows ────
async def _cid_for(email):
    u = await _db().users.find_one({"email": email},
                                     {"_id": 0, "customer_id": 1, "id": 1})
    return u.get("customer_id") or u.get("id")


async def _wipe_referrals(cid):
    await _db().referrals.delete_many({"referrer_customer_id": cid})
    await _db().leads.delete_many({"source": f"referral_from_customer:{cid}"})
    await _db().customer_credits.delete_many({"customer_id": cid})
    await _db().customer_credits_balance.delete_one({"customer_id": cid})
    await _db().marketing_deliveries.delete_many(
        {"trigger_entity.kind": "referral"},
    )


def test_referral_conversion_records_transactional_deliveries(
    admin_headers, customer_headers,
):
    cid = _run(_cid_for("customer@aquaterra.com"))
    _run(_wipe_referrals(cid))
    payload = {"friend_name": f"Tx Friend {uuid.uuid4().hex[:5]}",
               "friend_email": f"tx-{uuid.uuid4().hex[:6]}@ex.com"}
    r = requests.post(f"{API}/customer-portal/referrals",
                      headers=customer_headers, json=payload, timeout=15)
    assert r.status_code == 201, r.text
    lead_id = r.json()["lead_id"]

    r = requests.post(f"{API}/leads/{lead_id}/convert",
                      headers=admin_headers, timeout=15)
    assert r.status_code == 200, r.text

    async def _check():
        rows = await _db().marketing_deliveries.find(
            {"trigger_entity.kind": "referral",
             "customer_id": cid},
            {"_id": 0},
        ).to_list(20)
        # We should see an email and (if customer has phone) an SMS row.
        assert any(r["channel"] == "email" for r in rows), (
            "no email delivery row"
        )
        for r in rows:
            assert r["kind"] == "transactional"
            assert r["provider"] in ("resend", "ringcentral", "mock")
            assert r["provider_status"] in (
                "sent", "mocked", "suppressed", "failed",
            )
    _run(_check())


def test_referral_delivery_rows_carry_provider_metadata(customer_headers):
    """Regression guard — every referral delivery row must carry
    provider + provider_status + attempts so the Slice L.h analytics
    can slice by channel outcome."""
    async def _check():
        rows = await _db().marketing_deliveries.find(
            {"trigger_entity.kind": "referral"}, {"_id": 0},
        ).limit(5).to_list(5)
        for r in rows:
            assert "provider" in r and r["provider"]
            assert "provider_status" in r
            assert "attempts" in r
    _run(_check())
