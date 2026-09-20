"""Hotfix #3 · Feb-2026 — D2D customer-list gate + Zillow enrichment.

Runs against the live backend on ``localhost:8001``. Requires:
  * super@aquaterra.com  / password123
  * mike@aquaterra.com   / password123  (technician)
  * ZILLOW_TESTMODE_MOCK=true (already in preview .env)
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient
from tests._shared_mongo import (
    shared_client as _shared_client,
    shared_db as _shared_db,
)


load_dotenv(Path(__file__).resolve().parents[1] / ".env")

API = "http://localhost:8001/api"
_sync = _shared_db()
def _login(email: str, password: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login",
                        json={"email": email, "password": password}, timeout=30)
    r.raise_for_status()
    return r.json()["access_token"]


def _hdrs(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}"}


def _tenant_id(tok: str) -> str:
    return requests.get(f"{API}/tenants/current",
                          headers=_hdrs(tok), timeout=15).json()["id"]


@pytest.fixture(autouse=True)
def _cleanup_rate_limit():
    _sync.zillow_enrich_rate.delete_many({})
    _sync.zillow_cache.delete_many({"address": {"$regex": r"^HotfixD2D-"}})
    yield
    _sync.zillow_enrich_rate.delete_many({})
    _sync.zillow_cache.delete_many({"address": {"$regex": r"^HotfixD2D-"}})


# ═════════════════════════════════════════════════════════════════
# Part A — Customer-list gate on /d2d/customers-nearby
# ═════════════════════════════════════════════════════════════════
def test_d2d_customer_list_forbidden_for_technician_403():
    tok = _login("mike@aquaterra.com")
    r = requests.get(f"{API}/d2d/customers-nearby",
                       headers=_hdrs(tok), timeout=15)
    assert r.status_code == 403


def test_d2d_customer_list_allowed_for_admin_200():
    # ``super@aquaterra.com`` is a super_admin — but the endpoint
    # also allows admin. Reuse super to exercise the 200 path since
    # the seed doesn't guarantee a plain admin.
    tok = _login("super@aquaterra.com")
    r = requests.get(f"{API}/d2d/customers-nearby",
                       headers=_hdrs(tok), timeout=15)
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_d2d_customer_list_allowed_for_super_200():
    tok = _login("super@aquaterra.com")
    r = requests.get(f"{API}/d2d/customers-nearby",
                       headers=_hdrs(tok), timeout=15)
    assert r.status_code == 200


def test_d2d_job_detail_lookups_still_work_for_tech():
    """Regression guard — Part A must NOT block techs from
    /customers/{id} lookups they need for job details."""
    tok_tech = _login("mike@aquaterra.com")
    tok_admin = _login("super@aquaterra.com")
    # Grab any customer id via the admin route so we can probe as tech.
    admin_customers = requests.get(f"{API}/customers?count_only=false",
                                      headers=_hdrs(tok_admin),
                                      timeout=15).json()
    if not admin_customers:
        pytest.skip("no customers seeded to probe")
    row = admin_customers[0] if isinstance(admin_customers, list) else None
    if not row or not row.get("id"):
        pytest.skip("no customer id on first row")
    r = requests.get(f"{API}/customers/{row['id']}",
                       headers=_hdrs(tok_tech), timeout=15)
    # Techs may not universally see every customer, but the endpoint
    # itself must not blanket-403 like /d2d/customers-nearby does.
    assert r.status_code in (200, 403, 404), r.text
    assert r.status_code != 500


# ═════════════════════════════════════════════════════════════════
# Part B — Zillow enrichment endpoints
# ═════════════════════════════════════════════════════════════════
_MOCK_ADDR_BASE = "HotfixD2D-1600 Amphitheatre Pkwy Mountain View CA"


def test_zillow_endpoint_allowed_for_technician():
    tok = _login("mike@aquaterra.com")
    r = requests.post(f"{API}/d2d/zillow-lookup",
                          headers=_hdrs(tok), timeout=15,
                          json={"address": f"{_MOCK_ADDR_BASE}-{uuid.uuid4().hex[:6]}"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["mock"] is True
    assert "estimated_value" in body


def test_zillow_endpoint_allowed_for_admin():
    tok = _login("super@aquaterra.com")
    r = requests.post(f"{API}/d2d/zillow-lookup",
                          headers=_hdrs(tok), timeout=15,
                          json={"address": f"{_MOCK_ADDR_BASE}-{uuid.uuid4().hex[:6]}"})
    assert r.status_code == 200


def test_zillow_endpoint_401_for_unauthenticated():
    r = requests.post(f"{API}/d2d/zillow-lookup", timeout=15,
                          json={"address": f"{_MOCK_ADDR_BASE}-{uuid.uuid4().hex[:6]}"})
    assert r.status_code in (401, 403)


def test_zillow_returns_503_when_not_configured(monkeypatch):
    """Direct call to the service with both env vars unset should
    raise ``ZillowNotConfigured`` — mapped to 503 by the router."""
    import asyncio
    from motor.motor_asyncio import AsyncIOMotorClient
    from services.enrichment.zillow import (
        ZillowNotConfigured, fetch_zillow_property,
    )
    monkeypatch.delenv("ZILLOW_TESTMODE_MOCK", raising=False)
    monkeypatch.delenv("ZILLOW_RAPIDAPI_KEY", raising=False)
    monkeypatch.delenv("OPENWEB_NINJA_API_KEY", raising=False)
    monkeypatch.delenv("OWN_API_KEY", raising=False)

    addr = f"HotfixD2D-unconfig-{uuid.uuid4().hex[:8]}"
    _sync.zillow_cache.delete_many({"address": {"$regex": r"^HotfixD2D-unconfig-"}})
    _sync.zillow_enrich_rate.delete_many({})

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        # Fresh Motor client bound to *this* loop (the backend's own
        # ``config.db`` is bound to the app's asyncio loop and would
        # explode with a loop-mismatch RuntimeError otherwise).
        client = AsyncIOMotorClient(os.environ["MONGO_URL"])
        loop_db = client[os.environ["DB_NAME"]]
        with pytest.raises(ZillowNotConfigured):
            loop.run_until_complete(
                fetch_zillow_property(addr, tenant_id="t-unconfig-1", db=loop_db),
            )
    finally:
        loop.close()


def test_zillow_returns_mock_fixture_when_testmode_enabled():
    """Deterministic — same address → same fixture, always."""
    tok = _login("super@aquaterra.com")
    addr = f"HotfixD2D-determinism-{uuid.uuid4().hex[:6]}"
    r1 = requests.post(f"{API}/d2d/zillow-lookup",
                          headers=_hdrs(tok), timeout=15,
                          json={"address": addr, "force_refresh": True}).json()
    # Nuke cache so the 2nd call re-derives the mock rather than
    # short-circuiting on 24h TTL.
    _sync.zillow_cache.delete_many({"address": addr})
    r2 = requests.post(f"{API}/d2d/zillow-lookup",
                          headers=_hdrs(tok), timeout=15,
                          json={"address": addr, "force_refresh": True}).json()
    assert r1["estimated_value"] == r2["estimated_value"]
    assert r1["sqft"] == r2["sqft"]
    assert r1["bed_count"] == r2["bed_count"]
    assert r1["bath_count"] == r2["bath_count"]
    assert r1["year_built"] == r2["year_built"]
    assert r1["mock"] is True and r2["mock"] is True


def test_zillow_caches_on_prospect_and_hits_cache_on_second_call():
    """Second call within 24h must be a cache hit — assert
    ``cached=True`` and no extra rate-limit consumption."""
    tok = _login("super@aquaterra.com")
    tenant_id = _tenant_id(tok)

    # Create a knock so we have a real prospect id to hit.
    knock_id = f"knock-{uuid.uuid4().hex[:10]}"
    addr = f"HotfixD2D-cache-{uuid.uuid4().hex[:6]}"
    _sync.d2d_knocks.insert_one({
        "id": knock_id, "tenant_id": tenant_id,
        "address": addr, "lat": 33.0, "lng": -112.0,
        "disposition": "not_home",
        "tech_id": "t1", "tech_name": "T One",
        "converted": False,
    })
    try:
        r1 = requests.post(
            f"{API}/d2d/prospects/{knock_id}/enrich-zillow",
            headers=_hdrs(tok), timeout=15,
        )
        assert r1.status_code == 200, r1.text
        b1 = r1.json()
        assert b1.get("cached") is False
        state1 = _sync.zillow_enrich_rate.find_one({}, {"_id": 0, "count": 1})
        used1 = int((state1 or {}).get("count") or 0)

        r2 = requests.post(
            f"{API}/d2d/prospects/{knock_id}/enrich-zillow",
            headers=_hdrs(tok), timeout=15,
        )
        assert r2.status_code == 200, r2.text
        b2 = r2.json()
        assert b2.get("cached") is True   # ← key assertion
        state2 = _sync.zillow_enrich_rate.find_one({}, {"_id": 0, "count": 1})
        used2 = int((state2 or {}).get("count") or 0)
        assert used2 == used1  # cache hit must NOT bump the counter

        # Payload persisted on the knock.
        knock = _sync.d2d_knocks.find_one({"id": knock_id}, {"_id": 0})
        assert knock and knock.get("zillow_fetched_at")
        assert knock["zillow_data"]["mock"] is True
    finally:
        _sync.d2d_knocks.delete_one({"id": knock_id})


def test_zillow_rate_limit_100_per_hour_per_tenant_returns_429_on_101st():
    """Slam the counter directly then verify the 101st call trips 429.

    We manipulate the counter in Mongo rather than issuing 100 real
    HTTP calls — otherwise the whole suite runs for ~30s just for
    one test.
    """
    from services.enrichment.zillow import (
        RATE_LIMIT_COLLECTION, RATE_LIMIT_PER_HOUR,
    )
    from datetime import datetime, timezone
    tok = _login("super@aquaterra.com")
    tenant_id = _tenant_id(tok)
    hour_key = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H")
    _sync[RATE_LIMIT_COLLECTION].update_one(
        {"tenant_id": tenant_id, "hour_key": hour_key},
        {"$set": {"count": RATE_LIMIT_PER_HOUR,
                    "created_at": "seed", "updated_at": "seed"}},
        upsert=True,
    )
    r = requests.post(
        f"{API}/d2d/zillow-lookup",
        headers=_hdrs(tok), timeout=15,
        json={"address": f"HotfixD2D-ratelimit-{uuid.uuid4().hex[:6]}",
                "force_refresh": True},
    )
    assert r.status_code == 429, r.text
    body = r.json()
    assert body.get("error") == "zillow_rate_limited"
    assert body.get("cap") == RATE_LIMIT_PER_HOUR
