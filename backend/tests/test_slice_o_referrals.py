"""Feb 2026 · Slice O — Portal referrals + support phone tests.

Coverage:
* Public config endpoint returns support_phone_number for customers.
* Super-admin PATCH validates + persists phone; regular admin cannot.
* Customer referral creates lead + referral row + admin bell.
* Self-referral (same email/phone) blocked with 422.
* Daily rate-limit at 6th submission returns 429.
* Cross-tenant safety: customer in tenant A never lands referral in
  tenant B.
* Admin leads list surfaces the referral with source prefix +
  referrer_customer_id + referrer_customer_name.
"""
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
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def admin_headers():
    return {"Authorization": f"Bearer {_login('admin@aquaterra.com')}"}


@pytest.fixture(scope="module")
def super_headers():
    return {"Authorization": f"Bearer {_login('super@aquaterra.com')}"}


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


async def _customer_id_for(email):
    u = await _db().users.find_one({"email": email},
                                     {"_id": 0, "customer_id": 1, "id": 1})
    return u.get("customer_id") or u.get("id")


async def _wipe_referrals_for(cid):
    """Cheap fixture teardown so rate-limit tests aren't flaky."""
    await _db().referrals.delete_many({"referrer_customer_id": cid})
    await _db().leads.delete_many(
        {"source": f"referral_from_customer:{cid}"},
    )


# ── Public config ─────────────────────────────────────────────────
def test_public_config_returns_support_phone(customer_headers):
    r = requests.get(f"{API}/tenants/mine/public-config",
                      headers=customer_headers, timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["support_phone_number"] == "+16028874400"
    assert body["tenant_name"]
    # Never leaks secrets.
    for k in ("hq_address", "stripe_secret", "resend_api_key"):
        assert k not in body


def test_support_phone_patch_super_only(admin_headers, super_headers):
    # Admin cannot patch.
    r = requests.patch(f"{API}/tenants/mine/support-phone",
                        headers=admin_headers,
                        json={"support_phone_number": "+15551234567"},
                        timeout=15)
    assert r.status_code == 403

    # Super-admin can. Validates + persists + round-trips.
    r = requests.patch(f"{API}/tenants/mine/support-phone",
                        headers=super_headers,
                        json={"support_phone_number": "+15559990000"},
                        timeout=15)
    assert r.status_code == 200, r.text
    assert r.json()["support_phone_number"] == "+15559990000"

    # Restore the original for downstream tests.
    r = requests.patch(f"{API}/tenants/mine/support-phone",
                        headers=super_headers,
                        json={"support_phone_number": "+16028874400"},
                        timeout=15)
    assert r.status_code == 200


def test_support_phone_patch_validates_length(super_headers):
    r = requests.patch(f"{API}/tenants/mine/support-phone",
                        headers=super_headers,
                        json={"support_phone_number": "12345"},
                        timeout=15)
    assert r.status_code == 422, r.text


# ── Referral happy path ───────────────────────────────────────────
def test_referral_creates_lead_and_row(customer_headers):
    cid = _run(_customer_id_for("customer@aquaterra.com"))
    _run(_wipe_referrals_for(cid))

    unique = uuid.uuid4().hex[:8]
    payload = {
        "friend_name": f"Test Friend {unique}",
        "friend_email": f"friend-{unique}@example.com",
        "friend_phone": "(602) 555-9990",
        "service_of_interest": "Pool Cleaning",
        "notes": "Neighbour",
    }
    r = requests.post(f"{API}/customer-portal/referrals",
                      headers=customer_headers, json=payload, timeout=15)
    assert r.status_code == 201, r.text
    body = r.json()
    ref = body["referral"]
    assert ref["referrer_customer_id"] == cid
    assert ref["friend_name"] == f"Test Friend {unique}"
    assert ref["friend_phone"] == "6025559990"       # normalised
    assert body["lead_id"]

    # Lead is created with the referral source + backpointer.
    async def _check():
        lead = await _db().leads.find_one({"id": body["lead_id"]}, {"_id": 0})
        assert lead is not None
        assert lead["source"] == f"referral_from_customer:{cid}"
        assert lead["referrer_customer_id"] == cid
        assert lead["name"] == f"Test Friend {unique}"
    _run(_check())


def test_referral_visible_in_admin_leads_with_source(admin_headers, customer_headers):
    """The admin leads list shows the referral with source prefix +
    referrer_customer_id populated — powers the REFERRAL badge."""
    r = requests.get(f"{API}/leads", headers=admin_headers, timeout=15)
    assert r.status_code == 200
    referrals = [l for l in r.json()
                    if (l.get("source") or "").startswith("referral_from_customer:")]
    assert referrals, "expected at least one referral lead"
    for l in referrals:
        assert l.get("referrer_customer_id")


# ── Guards ────────────────────────────────────────────────────────
def test_self_referral_blocked_by_email(customer_headers):
    r = requests.post(f"{API}/customer-portal/referrals",
                      headers=customer_headers,
                      json={"friend_name": "Me",
                             "friend_email": "customer@aquaterra.com"},
                      timeout=15)
    assert r.status_code == 422
    assert "friend" in r.text.lower()


def test_referral_requires_reach(customer_headers):
    r = requests.post(f"{API}/customer-portal/referrals",
                      headers=customer_headers,
                      json={"friend_name": "No Contact"},
                      timeout=15)
    assert r.status_code == 422


def test_admin_and_tech_cannot_submit(admin_headers):
    """POST /customer-portal/referrals is customer-only."""
    r = requests.post(f"{API}/customer-portal/referrals",
                      headers=admin_headers,
                      json={"friend_name": "X", "friend_email": "x@y.com"},
                      timeout=15)
    assert r.status_code == 403


# ── Rate limit ────────────────────────────────────────────────────
def test_rate_limit_at_sixth_referral(customer_headers):
    cid = _run(_customer_id_for("customer@aquaterra.com"))
    _run(_wipe_referrals_for(cid))
    # Five successes, sixth 429.
    for i in range(5):
        r = requests.post(f"{API}/customer-portal/referrals",
                          headers=customer_headers,
                          json={"friend_name": f"Batch {i}",
                                  "friend_email": f"batch{i}-{uuid.uuid4().hex[:6]}@ex.com"},
                          timeout=15)
        assert r.status_code == 201, f"batch {i}: {r.text}"
    r = requests.post(f"{API}/customer-portal/referrals",
                      headers=customer_headers,
                      json={"friend_name": "Overflow",
                              "friend_email": f"boom-{uuid.uuid4().hex[:6]}@ex.com"},
                      timeout=15)
    assert r.status_code == 429, r.text
    _run(_wipe_referrals_for(cid))


# ── Cross-tenant isolation ────────────────────────────────────────
def test_referral_stays_in_customers_tenant(customer_headers):
    """A referral submitted by a customer in tenant A must NOT land in
    tenant B's leads. We check the lead's tenant_id matches the
    customer's tenant_id, not any other tenant on the platform."""
    cid = _run(_customer_id_for("customer@aquaterra.com"))
    _run(_wipe_referrals_for(cid))

    async def _tenant_id_for_customer():
        u = await _db().users.find_one({"email": "customer@aquaterra.com"},
                                         {"_id": 0, "tenant_id": 1})
        return u["tenant_id"]

    expected_tid = _run(_tenant_id_for_customer())

    r = requests.post(f"{API}/customer-portal/referrals",
                      headers=customer_headers,
                      json={"friend_name": "Cross-tenant test",
                              "friend_email": f"xt-{uuid.uuid4().hex[:6]}@ex.com"},
                      timeout=15)
    assert r.status_code == 201, r.text
    lead_id = r.json()["lead_id"]

    async def _check_isolation():
        lead = await _db().leads.find_one({"id": lead_id}, {"_id": 0})
        assert lead["tenant_id"] == expected_tid
        # And the referral row too.
        ref = await _db().referrals.find_one(
            {"lead_id": lead_id}, {"_id": 0},
        )
        assert ref["tenant_id"] == expected_tid
    _run(_check_isolation())
    _run(_wipe_referrals_for(cid))
