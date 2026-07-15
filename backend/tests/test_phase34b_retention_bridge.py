"""Phase 34b — Churn → Marketing Studio retention bridge tests."""
import asyncio
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from motor.motor_asyncio import AsyncIOMotorClient

_FE = dotenv_values(Path(__file__).resolve().parents[2] / "frontend" / ".env")
BASE = (_FE.get("REACT_APP_BACKEND_URL") or "http://localhost:8001").rstrip("/")
API = f"{BASE}/api"

ADMIN_A = {"email": "admin@aquaterra.com", "password": "password123"}
ADMIN_B = {"email": "admin@sunbelt.com",   "password": "password123"}
TECH    = {"email": "mike@aquaterra.com",  "password": "password123"}


def _login(creds):
    r = requests.post(f"{API}/auth/login", json=creds, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _auth(t): return {"Authorization": f"Bearer {t}"}


def _tid(email):
    env = dotenv_values("/app/backend/.env")
    cli = AsyncIOMotorClient(env["MONGO_URL"])
    db = cli[env["DB_NAME"]]

    async def _q():
        u = await db.users.find_one({"email": email})
        return u["tenant_id"] if u else None
    x = asyncio.get_event_loop().run_until_complete(_q())
    cli.close()
    return x


@pytest.fixture
def seeded_scores():
    """Seed 3 churn scores + 3 customers on aquaterra with scores 85/65/40."""
    env = dotenv_values("/app/backend/.env")
    cli = AsyncIOMotorClient(env["MONGO_URL"])
    db = cli[env["DB_NAME"]]
    tid = _tid(ADMIN_A["email"])
    marker = f"TEST-retention-{uuid.uuid4().hex[:6]}"
    seeds = []
    for score in (85, 65, 40):
        cid = f"{marker}-cust-{score}"
        seeds.append((cid, score))

    async def _seed():
        # Phase 41 · Item J — pre-seed sweep. If a prior interrupted test
        # session left `TEST-retention-*` docs on this tenant, the
        # threshold-filter assertion below will fail (target_count > 2).
        # Purge our own family of TEST- markers before every run so the
        # test is order-independent.
        await db.customers.delete_many(
            {"tenant_id": tid, "id": {"$regex": "^TEST-retention-|^TEST_retention"}})
        await db.customer_churn_scores.delete_many(
            {"tenant_id": tid, "customer_id": {"$regex": "^TEST-retention-|^TEST_retention"}})
        stale_targets = await db.retention_campaign_targets.find(
            {"tenant_id": tid, "customer_ids": {"$elemMatch":
                {"$regex": "^TEST-retention-|^TEST_retention"}}},
            {"campaign_id": 1, "_id": 0},
        ).to_list(100)
        stale_camp_ids = [t["campaign_id"] for t in stale_targets]
        if stale_camp_ids:
            await db.marketing_campaigns.delete_many({"id": {"$in": stale_camp_ids}})
            await db.retention_campaign_targets.delete_many({"campaign_id": {"$in": stale_camp_ids}})

        for cid, score in seeds:
            await db.customers.insert_one({
                "id": cid, "tenant_id": tid,
                "name": f"TEST Customer {score}",
                "last_service_date": "2025-11-01",
            })
            await db.customer_churn_scores.insert_one({
                "id": f"{cid}-score", "tenant_id": tid,
                "customer_id": cid, "risk_score": score,
                "tier": "critical" if score >= 80 else ("high" if score >= 60 else "low"),
                "top_signals": [f"signal-{score}-1", f"signal-{score}-2"],
                "signals_snapshot": {}, "analyzed_at": datetime.now(timezone.utc).isoformat(),
            })

    async def _cleanup():
        cids = [s[0] for s in seeds]
        await db.customers.delete_many({"id": {"$in": cids}})
        await db.customer_churn_scores.delete_many({"customer_id": {"$in": cids}})
        # Sweep any campaigns created by these tests.
        targets = await db.retention_campaign_targets.find(
            {"customer_ids": {"$in": cids}}, {"campaign_id": 1, "_id": 0}
        ).to_list(50)
        camp_ids = [t["campaign_id"] for t in targets]
        if camp_ids:
            await db.marketing_campaigns.delete_many({"id": {"$in": camp_ids}})
            await db.retention_campaign_targets.delete_many({"campaign_id": {"$in": camp_ids}})

    loop = asyncio.get_event_loop()
    loop.run_until_complete(_seed())
    yield tid, seeds
    loop.run_until_complete(_cleanup())
    cli.close()


@pytest.fixture(scope="module")
def admin_a_tok(): return _login(ADMIN_A)


@pytest.fixture(scope="module")
def admin_b_tok(): return _login(ADMIN_B)


@pytest.fixture(scope="module")
def tech_tok(): return _login(TECH)


def _fetch_targets(campaign_id):
    env = dotenv_values("/app/backend/.env")
    cli = AsyncIOMotorClient(env["MONGO_URL"])
    db = cli[env["DB_NAME"]]

    async def _q():
        return await db.retention_campaign_targets.find_one(
            {"campaign_id": campaign_id}, {"_id": 0}
        )
    row = asyncio.get_event_loop().run_until_complete(_q())
    cli.close()
    return row


def test_threshold_filter_and_write(admin_a_tok, seeded_scores):
    tid, seeds = seeded_scores
    r = requests.post(f"{API}/churn/create-retention-campaign",
                       headers=_auth(admin_a_tok),
                       json={"channel": "email", "min_risk_score": 60,
                              "max_customers": 10},
                       timeout=90)
    assert r.status_code == 200, r.text
    j = r.json()
    # Phase 41 · Item J — tolerate real seed churn scores on this tenant
    # (e.g. the demo "Jennifer Carson" account carries a live risk score
    # in the 70s). What we care about is that BOTH of our seeded
    # high-risk TEST customers (85 & 65) are targeted and the low one
    # (40) is not. Exact count matching was the original flake trigger.
    assert j["target_count"] >= 2, j
    assert j["campaign_id"]
    row = _fetch_targets(j["campaign_id"])
    assert row is not None
    expected = {s[0] for s in seeds if s[1] >= 60}
    excluded = {s[0] for s in seeds if s[1] < 60}
    hit = set(row["customer_ids"])
    assert expected.issubset(hit), (expected, hit)
    assert excluded.isdisjoint(hit), (excluded, hit)


def test_max_customers_cap(admin_a_tok, seeded_scores):
    r = requests.post(f"{API}/churn/create-retention-campaign",
                       headers=_auth(admin_a_tok),
                       json={"channel": "email", "min_risk_score": 60,
                              "max_customers": 1},
                       timeout=90)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["target_count"] == 1, j
    row = _fetch_targets(j["campaign_id"])
    # Phase 41 · Item J — cap must be enforced regardless of which
    # highest-risk customer wins (our seed 85 vs any real tenant seed
    # with a higher live score). What we assert: cap=1 → exactly one
    # customer_id in the row and none of our low-risk (40) seeds are
    # in it.
    assert len(row["customer_ids"]) == 1
    below_threshold = {s[0] for s in seeded_scores[1] if s[1] < 60}
    assert not below_threshold.intersection(row["customer_ids"])


def test_zero_matches(admin_a_tok, seeded_scores):
    r = requests.post(f"{API}/churn/create-retention-campaign",
                       headers=_auth(admin_a_tok),
                       json={"channel": "email", "min_risk_score": 99,
                              "max_customers": 10},
                       timeout=15)
    assert r.status_code == 200
    j = r.json()
    assert j["campaign_id"] is None
    assert j["target_count"] == 0
    assert j["mocked"] is False
    assert j["reason"] == "no customers match threshold"


def test_llm_error_falls_back_but_still_creates(admin_a_tok, seeded_scores, monkeypatch):
    """Patch the LlmChat import so any call raises; endpoint must still
    return a campaign_id with a fallback goal + mocked=true."""
    import sys
    sys.path.insert(0, "/app/backend")
    import routers.churn as churn_mod

    # Reach the coroutine directly (uvicorn worker doesn't see monkeypatch).
    from routers.churn import create_retention_campaign, RetentionCampaignBody
    tid, _ = seeded_scores

    class _Boom:
        def __init__(self, *a, **kw): pass
        def with_model(self, *a, **kw): return self
        def with_params(self, **kw): return self
        async def send_message(self, *a, **kw):
            raise RuntimeError("stubbed llm blow-up")

    # Patch the module import path — the endpoint does
    # `from emergentintegrations.llm.chat import LlmChat, UserMessage`
    # inside the try block, so monkey-patching the imported name at the
    # top of that call is fiddly. Simpler: patch EMERGENT_LLM_KEY to a
    # non-empty stub but shim the emergentintegrations module to raise.
    import types, sys as _sys
    fake = types.ModuleType("emergentintegrations.llm.chat")
    fake.LlmChat = _Boom
    fake.UserMessage = lambda text=None: text
    _sys.modules["emergentintegrations.llm.chat"] = fake

    result = asyncio.get_event_loop().run_until_complete(
        create_retention_campaign(
            body=RetentionCampaignBody(channel="email",
                                        min_risk_score=60, max_customers=5),
            user={"role": "admin", "id": "TEST-actor"},
            tenant={"id": tid},
        )
    )
    assert result["mocked"] is True
    assert "llm error" in (result["reason"] or "").lower() or \
           "stubbed llm blow-up" in (result["reason"] or "")
    assert result["campaign_id"], "campaign must still be created"
    assert result["target_count"] >= 2

    # Verify the campaign row exists + goal string is the fallback.
    env = dotenv_values("/app/backend/.env")
    cli = AsyncIOMotorClient(env["MONGO_URL"])
    db = cli[env["DB_NAME"]]

    async def _check():
        return await db.marketing_campaigns.find_one(
            {"id": result["campaign_id"]}, {"_id": 0}
        )
    row = asyncio.get_event_loop().run_until_complete(_check())
    cli.close()
    assert row is not None
    assert "at-risk" in (row["goal"] or "").lower()


def test_tech_forbidden(tech_tok):
    r = requests.post(f"{API}/churn/create-retention-campaign",
                       headers=_auth(tech_tok),
                       json={"channel": "email"}, timeout=15)
    assert r.status_code == 403


def test_tenant_isolation(admin_a_tok, admin_b_tok, seeded_scores):
    """A campaign created by aquaterra must NOT be visible to sunbelt."""
    r = requests.post(f"{API}/churn/create-retention-campaign",
                       headers=_auth(admin_a_tok),
                       json={"channel": "email", "min_risk_score": 60,
                              "max_customers": 10}, timeout=90)
    j = r.json()
    cid = j["campaign_id"]
    assert cid
    # Sunbelt admin fetches the campaign list — must NOT contain cid.
    b_list = requests.get(f"{API}/marketing/campaigns",
                           headers=_auth(admin_b_tok), timeout=15).json()
    b_ids = [c.get("id") for c in (b_list if isinstance(b_list, list)
                                     else b_list.get("items", []))]
    assert cid not in b_ids
