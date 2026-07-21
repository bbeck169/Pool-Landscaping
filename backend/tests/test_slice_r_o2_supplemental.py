"""Feb 2026 · Supplemental supplemental coverage for Slice R + O.2 + L.

Fills gaps not covered by test_slice_r_o2_l_batch.py:
  * decline with reason persistence
  * request-changes 422 when message empty
  * magic-link invalid-token 401
  * tech RBAC on /decline and /pdf
  * revoke double-call → 409
  * widget denied TTL index presence
  * cross-tenant referral credit safety
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


@pytest.fixture(scope="module")
def tech_headers():
    return {"Authorization": f"Bearer {_login('mike@aquaterra.com')}"}


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


async def _tenant_id(slug="aquaterra"):
    t = await _db().tenants.find_one({"slug": slug}, {"_id": 0, "id": 1})
    return t["id"]


async def _fresh_estimate():
    """Return a pending (not accepted/declined) estimate id."""
    tid = await _tenant_id()
    est = await _db().quotes.find_one(
        {"tenant_id": tid, "doc_type": "quote",
         "decision": {"$nin": ["accepted", "declined"]}},
        {"_id": 0, "id": 1},
    )
    return est["id"] if est else None


# ═════════════════════════════════════════════════════════════════════
# Slice R — decline reason + request-changes + magic-link error paths
# ═════════════════════════════════════════════════════════════════════
def test_decline_stores_reason(admin_headers):
    eid = _run(_fresh_estimate())
    if not eid:
        pytest.skip("no pending estimate")
    reason = f"customer-not-ready-{uuid.uuid4().hex[:6]}"
    r = requests.post(f"{API}/estimates/{eid}/decline",
                       headers=admin_headers,
                       json={"reason": reason}, timeout=15)
    assert r.status_code == 200, r.text
    # DB confirms persistence.
    async def _c():
        e = await _db().quotes.find_one({"id": eid}, {"_id": 0})
        assert e["decision"] == "declined"
        assert e["decline_reason"] == reason
    _run(_c())


def test_request_changes_empty_message_422(admin_headers):
    eid = _run(_fresh_estimate())
    if not eid:
        pytest.skip("no pending estimate")
    r = requests.post(f"{API}/estimates/{eid}/request-changes",
                       headers=admin_headers,
                       json={"message": ""}, timeout=15)
    assert r.status_code == 422, f"expected 422 on empty message, got {r.status_code}: {r.text}"


def test_magic_link_invalid_token_401():
    r = requests.get(f"{API}/portal/estimates/via-token?token=totally-bogus-{uuid.uuid4().hex}",
                      timeout=15)
    assert r.status_code == 401, r.text


def test_tech_forbidden_on_decline_and_pdf(tech_headers):
    eid = _run(_fresh_estimate())
    if not eid:
        # any quote works for RBAC
        async def _any():
            tid = await _tenant_id()
            e = await _db().quotes.find_one({"tenant_id": tid}, {"_id": 0, "id": 1})
            return e["id"] if e else None
        eid = _run(_any())
    r_dec = requests.post(f"{API}/estimates/{eid}/decline",
                           headers=tech_headers, json={"reason": "no"}, timeout=15)
    assert r_dec.status_code == 403, r_dec.text
    r_pdf = requests.get(f"{API}/estimates/{eid}/pdf",
                          headers=tech_headers, timeout=15)
    assert r_pdf.status_code == 403, r_pdf.text


# ═════════════════════════════════════════════════════════════════════
# Slice O.2 — revoke idempotency (2nd call → 409)
# ═════════════════════════════════════════════════════════════════════
async def _cid_for(email):
    u = await _db().users.find_one({"email": email},
                                     {"_id": 0, "customer_id": 1, "id": 1})
    return u.get("customer_id") or u.get("id")


async def _wipe_customer_referrals(cid):
    await _db().referrals.delete_many({"referrer_customer_id": cid})
    await _db().leads.delete_many({"source": f"referral_from_customer:{cid}"})
    await _db().customer_credits.delete_many(
        {"customer_id": cid, "source": {"$in": ["referral_reward",
                                                 "referral_reward_revoke"]}},
    )
    await _db().customer_credits_balance.delete_one({"customer_id": cid})


def test_revoke_second_call_409(admin_headers, customer_headers):
    cid = _run(_cid_for("customer@aquaterra.com"))
    _run(_wipe_customer_referrals(cid))
    ref = requests.post(f"{API}/customer-portal/referrals",
                         headers=customer_headers,
                         json={"friend_name": "Revoke Twice",
                                "friend_email": f"{uuid.uuid4().hex[:6]}@ex.com"},
                         timeout=15).json()
    lead_id = ref["lead_id"]
    r = requests.post(f"{API}/leads/{lead_id}/convert",
                       headers=admin_headers, timeout=15)
    assert r.status_code == 200
    async def _rid():
        row = await _db().referrals.find_one({"lead_id": lead_id},
                                              {"_id": 0, "id": 1})
        return row["id"]
    rid = _run(_rid())
    r1 = requests.post(f"{API}/admin/referrals/{rid}/revoke-reward",
                        headers=admin_headers, timeout=15)
    assert r1.status_code == 200
    r2 = requests.post(f"{API}/admin/referrals/{rid}/revoke-reward",
                        headers=admin_headers, timeout=15)
    assert r2.status_code == 409, r2.text


# ═════════════════════════════════════════════════════════════════════
# Slice L.c — TTL index presence on widget_denied_requests
# ═════════════════════════════════════════════════════════════════════
def test_widget_denied_ttl_index():
    async def _c():
        idx = await _db().widget_denied_requests.index_information()
        # Look for a TTL (expireAfterSeconds) index of ~7 days.
        ttl = [name for name, meta in idx.items()
               if meta.get("expireAfterSeconds") is not None]
        assert ttl, f"no TTL index on widget_denied_requests. indexes={list(idx.keys())}"
        # Named per problem statement.
        assert any("widget_denied_ttl" in n or "ttl" in n.lower() for n in ttl), (
            f"expected TTL index named widget_denied_ttl_*, got {ttl}"
        )
        # Tenant/time compound index.
        assert any("tenant" in n for n in idx.keys()), (
            f"missing tenant/time index; indexes={list(idx.keys())}"
        )
    _run(_c())


# ═════════════════════════════════════════════════════════════════════
# Cross-tenant safety — Aquaterra referral must never credit another tenant
# ═════════════════════════════════════════════════════════════════════
def test_no_cross_tenant_credit_leak(admin_headers, customer_headers):
    cid = _run(_cid_for("customer@aquaterra.com"))
    _run(_wipe_customer_referrals(cid))
    ref = requests.post(f"{API}/customer-portal/referrals",
                         headers=customer_headers,
                         json={"friend_name": "Tenant Fence",
                                "friend_email": f"{uuid.uuid4().hex[:6]}@ex.com"},
                         timeout=15).json()
    lead_id = ref["lead_id"]
    r = requests.post(f"{API}/leads/{lead_id}/convert",
                       headers=admin_headers, timeout=15)
    assert r.status_code == 200
    async def _c():
        aqua_tid = await _tenant_id("aquaterra")
        # All credits created in this test must belong to Aquaterra tenant.
        rows = await _db().customer_credits.find(
            {"customer_id": cid, "source": "referral_reward"},
            {"_id": 0, "tenant_id": 1},
        ).to_list(length=100)
        assert rows, "no reward credit written"
        for row in rows:
            assert row["tenant_id"] == aqua_tid, (
                f"cross-tenant leak — credit tenant={row['tenant_id']} != {aqua_tid}"
            )
        # And no credits under this customer_id under a different tenant.
        bad = await _db().customer_credits.count_documents(
            {"customer_id": cid, "tenant_id": {"$ne": aqua_tid}},
        )
        assert bad == 0, f"found {bad} credit rows under wrong tenant"
    _run(_c())
