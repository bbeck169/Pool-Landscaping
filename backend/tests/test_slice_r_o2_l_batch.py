"""Feb 2026 · Slice R + O.2 + L.c/L.j combined test suite."""
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


async def _pick_estimate():
    tid = await _tenant_id()
    est = await _db().quotes.find_one(
        {"tenant_id": tid, "doc_type": "quote",
         "decision": {"$nin": ["accepted", "declined"]}},
        {"_id": 0, "id": 1},
    )
    return est["id"] if est else None


# ══════════════════════════════════════════════════════════════════════
# Slice R — Estimate viewer + Accept/Decline + Magic-link + PDF
# ══════════════════════════════════════════════════════════════════════
def test_r_admin_full_has_margin_columns(admin_headers):
    eid = _run(_pick_estimate())
    r = requests.get(f"{API}/estimates/{eid}/full",
                      headers=admin_headers, timeout=15)
    assert r.status_code == 200
    body = r.json()
    for k in ("estimated_profit", "total_b_hrs", "total_b_hrs_revenue"):
        assert k in body["totals"], f"admin missing {k}"
    assert body["as_customer"] is False


def test_r_tech_forbidden(tech_headers):
    eid = _run(_pick_estimate())
    r = requests.get(f"{API}/estimates/{eid}/full",
                      headers=tech_headers, timeout=15)
    assert r.status_code == 403


def test_r_magic_link_customer_projection():
    """Magic-link viewer is treated as customer — no margin/BH columns."""
    # Admin issues link.
    a = requests.post(f"{API}/auth/login",
                       json={"email": "admin@aquaterra.com",
                              "password": "password123"}, timeout=15).json()["access_token"]
    eid = _run(_pick_estimate())
    r = requests.get(f"{API}/estimates/{eid}/magic-link",
                      headers={"Authorization": f"Bearer {a}"}, timeout=15)
    assert r.status_code == 200
    token = r.json()["token"]
    r = requests.get(f"{API}/portal/estimates/via-token?token={token}", timeout=15)
    assert r.status_code == 200
    body = r.json()
    assert body["as_customer"] is True
    for banned in ("estimated_profit", "total_b_hrs", "total_b_hrs_revenue"):
        assert banned not in body["totals"], banned


def test_r_accept_locks_estimate(admin_headers):
    eid = _run(_pick_estimate())
    if not eid:
        pytest.skip("no pending estimate")
    r = requests.post(f"{API}/estimates/{eid}/accept",
                       headers=admin_headers, timeout=15)
    assert r.status_code == 200
    assert r.json()["decision"] == "accepted"
    # Second accept 409.
    r = requests.post(f"{API}/estimates/{eid}/accept",
                       headers=admin_headers, timeout=15)
    assert r.status_code == 409


def test_r_pdf(admin_headers):
    eid = _run(_pick_estimate())
    if not eid:
        # fall back to any quote — even accepted ones can render PDFs
        async def _any():
            tid = await _tenant_id()
            e = await _db().quotes.find_one(
                {"tenant_id": tid, "doc_type": "quote"}, {"_id": 0, "id": 1},
            )
            return e["id"] if e else None
        eid = _run(_any())
    r = requests.get(f"{API}/estimates/{eid}/pdf",
                      headers=admin_headers, timeout=30)
    assert r.status_code == 200
    assert r.content[:4] == b"%PDF"


# ══════════════════════════════════════════════════════════════════════
# Slice O.2 — Referral rewards loop
# ══════════════════════════════════════════════════════════════════════
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


def _submit_referral(customer_headers, name, email=None):
    payload = {"friend_name": name,
               "friend_email": email or f"{uuid.uuid4().hex[:6]}@ex.com"}
    r = requests.post(f"{API}/customer-portal/referrals",
                      headers=customer_headers, json=payload, timeout=15)
    assert r.status_code == 201, r.text
    return r.json()


def test_o2_convert_applies_reward(admin_headers, customer_headers):
    cid = _run(_cid_for("customer@aquaterra.com"))
    _run(_wipe_customer_referrals(cid))
    ref = _submit_referral(customer_headers, "Rewards Friend One")
    lead_id = ref["lead_id"]
    # Convert the lead.
    r = requests.post(f"{API}/leads/{lead_id}/convert",
                       headers=admin_headers, timeout=15)
    assert r.status_code == 200, r.text
    new_cust = r.json()
    # Referral row updated with reward metadata.
    async def _check():
        row = await _db().referrals.find_one({"lead_id": lead_id}, {"_id": 0})
        assert row is not None
        assert row["status"] == "converted"
        assert row["converted_to_customer_id"] == new_cust["id"]
        assert row["reward_amount"] == 25.00
        assert row["reward_applied_at"]
        assert row["reward_transaction_id"]
        # Credit ledger row inserted.
        tx = await _db().customer_credits.find_one(
            {"id": row["reward_transaction_id"]}, {"_id": 0},
        )
        assert tx and tx["delta"] == 25.00
        # Balance rollup.
        bal = await _db().customer_credits_balance.find_one(
            {"customer_id": cid}, {"_id": 0, "balance": 1},
        )
        assert bal and abs(bal["balance"] - 25.00) < 0.01
    _run(_check())


def test_o2_reconvert_is_idempotent(admin_headers, customer_headers):
    cid = _run(_cid_for("customer@aquaterra.com"))
    _run(_wipe_customer_referrals(cid))
    ref = _submit_referral(customer_headers, "Idem Friend")
    lead_id = ref["lead_id"]
    r1 = requests.post(f"{API}/leads/{lead_id}/convert",
                        headers=admin_headers, timeout=15)
    assert r1.status_code == 200
    r2 = requests.post(f"{API}/leads/{lead_id}/convert",
                        headers=admin_headers, timeout=15)
    assert r2.status_code == 200
    async def _check():
        tx_count = await _db().customer_credits.count_documents({
            "customer_id": cid, "source": "referral_reward",
        })
        assert tx_count == 1, f"double-credit: {tx_count} rows"
        bal = await _db().customer_credits_balance.find_one(
            {"customer_id": cid}, {"_id": 0, "balance": 1},
        )
        assert bal["balance"] == 25.00
    _run(_check())


def test_o2_disabled_config_no_credit(admin_headers, super_headers, customer_headers):
    cid = _run(_cid_for("customer@aquaterra.com"))
    _run(_wipe_customer_referrals(cid))
    # Disable rewards.
    r = requests.patch(f"{API}/tenants/mine/referral-rewards",
                        headers=super_headers,
                        json={"referral_reward_enabled": False},
                        timeout=15)
    assert r.status_code == 200
    try:
        ref = _submit_referral(customer_headers, "No Credit Friend")
        r = requests.post(f"{API}/leads/{ref['lead_id']}/convert",
                          headers=admin_headers, timeout=15)
        assert r.status_code == 200
        async def _check():
            row = await _db().referrals.find_one({"lead_id": ref["lead_id"]}, {"_id": 0})
            assert row["status"] == "converted"
            assert not row.get("reward_applied_at")
            tx_count = await _db().customer_credits.count_documents({
                "customer_id": cid, "source": "referral_reward",
            })
            assert tx_count == 0
        _run(_check())
    finally:
        # Restore for downstream tests.
        requests.patch(f"{API}/tenants/mine/referral-rewards",
                        headers=super_headers,
                        json={"referral_reward_enabled": True,
                                "referral_reward_amount": 25.00},
                        timeout=15)


def test_o2_revoke_reward_removes_credit(admin_headers, customer_headers):
    cid = _run(_cid_for("customer@aquaterra.com"))
    _run(_wipe_customer_referrals(cid))
    ref = _submit_referral(customer_headers, "Revoke Friend")
    r = requests.post(f"{API}/leads/{ref['lead_id']}/convert",
                       headers=admin_headers, timeout=15)
    assert r.status_code == 200
    async def _rid():
        row = await _db().referrals.find_one(
            {"lead_id": ref["lead_id"]}, {"_id": 0, "id": 1},
        )
        return row["id"]
    rid = _run(_rid())
    r = requests.post(f"{API}/admin/referrals/{rid}/revoke-reward",
                       headers=admin_headers, timeout=15)
    assert r.status_code == 200, r.text
    async def _check_balance():
        bal = await _db().customer_credits_balance.find_one(
            {"customer_id": cid}, {"_id": 0, "balance": 1},
        )
        assert abs(bal["balance"]) < 0.01, f"balance not cleared: {bal}"
    _run(_check_balance())


def test_o2_my_referrals_summary(customer_headers, admin_headers):
    cid = _run(_cid_for("customer@aquaterra.com"))
    _run(_wipe_customer_referrals(cid))
    _submit_referral(customer_headers, "Summary A")
    b = _submit_referral(customer_headers, "Summary B")
    requests.post(f"{API}/leads/{b['lead_id']}/convert",
                    headers=admin_headers, timeout=15)
    r = requests.get(f"{API}/customer-portal/referrals/my",
                      headers=customer_headers, timeout=15)
    assert r.status_code == 200
    body = r.json()
    assert body["summary"]["total_referrals"] == 2
    assert body["summary"]["conversions"] == 1
    assert body["summary"]["rewards_earned"] == 25.00


# ══════════════════════════════════════════════════════════════════════
# Slice L.j — Slice I walkthrough alias
# ══════════════════════════════════════════════════════════════════════
def test_lj_has_completed_alias(customer_headers):
    r = requests.get(f"{API}/customer-portal/walkthrough/status",
                      headers=customer_headers, timeout=15)
    assert r.status_code == 200
    body = r.json()
    assert "completed" in body and "has_completed" in body
    assert body["completed"] == body["has_completed"]


# ══════════════════════════════════════════════════════════════════════
# Slice L.c — Denied-requests read still works after Mongo migration
# ══════════════════════════════════════════════════════════════════════
def test_lc_denied_requests_endpoint(admin_headers):
    r = requests.get(f"{API}/tenants/mine/widget-config/denied-requests",
                      headers=admin_headers, timeout=15)
    assert r.status_code == 200
    assert "denied" in r.json()
