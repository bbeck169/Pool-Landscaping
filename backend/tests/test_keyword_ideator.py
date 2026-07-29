"""Phase SEO-C · Feb-2026 — Keyword ideation tests.

Split into unit tests (no network — parser edges, dedupe, cache
semantics via mocked fetchers) and live-server tests (against the
running backend for RBAC, cross-tenant, and rate-limiting).
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

# ─── Env ───────────────────────────────────────────────────────────

_BACKEND_ENV = Path(__file__).resolve().parents[1] / ".env"
_ENV = dotenv_values(_BACKEND_ENV)
_MONGO_URL = _ENV.get("MONGO_URL") or os.environ.get("MONGO_URL")
_DB_NAME = _ENV.get("DB_NAME") or os.environ.get("DB_NAME")
_sync = MongoClient(_MONGO_URL)[_DB_NAME]

_REACT_ENV = Path(__file__).resolve().parents[2] / "frontend" / ".env"
_REACT = dotenv_values(_REACT_ENV) if _REACT_ENV.is_file() else {}
_PUBLIC_URL = _REACT.get("REACT_APP_BACKEND_URL") or os.environ.get(
    "REACT_APP_BACKEND_URL")
API = os.environ.get("BACKEND_API_URL") or (
    (_PUBLIC_URL.rstrip("/") + "/api") if _PUBLIC_URL else
    "http://localhost:8001/api"
)


def _login(email: str, pw: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": pw}, timeout=15)
    r.raise_for_status()
    return r.json()["access_token"]


def _hdr(email: str) -> dict:
    return {"Authorization": f"Bearer {_login(email)}",
            "X-Tenant-Slug": "aquaterra"}


def _super_h(): return _hdr("super@aquaterra.com")
def _customer_h(): return _hdr("customer@aquaterra.com")
def _tech_h():
    tech = _sync.users.find_one({"role": "technician",
                                  "email": {"$exists": True, "$ne": None}})
    return _hdr(tech["email"])


# ═══════════════════════ UNIT TESTS (no network) ═══════════════════

class TestAutocompleteParser:
    def test_parses_standard_shape(self):
        import httpx
        from services.keyword_ideator import fetch_google_autocomplete
        payload = ["pool service",
                    ["pool service phoenix",
                     "pool service near me",
                     "pool service cost"],
                    [], {"google:suggestrelevance": [400, 400, 400]}]
        transport = httpx.MockTransport(
            lambda req: httpx.Response(200, text=str(payload).replace("'", '"')))

        import asyncio
        async def _run():
            async with httpx.AsyncClient(transport=transport) as c:
                return await fetch_google_autocomplete(c, "pool service")
        r = asyncio.run(_run())
        assert r == ["pool service phoenix",
                     "pool service near me",
                     "pool service cost"]

    def test_empty_response_returns_empty(self):
        import httpx
        from services.keyword_ideator import fetch_google_autocomplete
        transport = httpx.MockTransport(
            lambda req: httpx.Response(200, text="[]"))

        import asyncio
        async def _run():
            async with httpx.AsyncClient(transport=transport) as c:
                return await fetch_google_autocomplete(c, "seed")
        assert asyncio.run(_run()) == []

    def test_429_returns_empty_no_raise(self):
        import httpx
        from services.keyword_ideator import fetch_google_autocomplete
        transport = httpx.MockTransport(
            lambda req: httpx.Response(429, text="Too Many Requests"))

        import asyncio
        async def _run():
            async with httpx.AsyncClient(transport=transport) as c:
                return await fetch_google_autocomplete(c, "seed")
        assert asyncio.run(_run()) == []


class TestDedupe:
    def test_dedupes_case_insensitive(self):
        from services.keyword_ideator import _dedupe
        r = _dedupe(["Pool", "pool", "POOL service", "pool service"])
        assert r == ["pool", "pool service"]

    def test_caps_at_max(self):
        from services.keyword_ideator import _dedupe
        r = _dedupe([f"item-{i}" for i in range(100)], cap=25)
        assert len(r) == 25


class TestPytrendsErrorSurfacing:
    def test_pytrends_exception_captured(self):
        import asyncio
        from services import keyword_ideator

        def _boom(*a, **kw):
            raise RuntimeError("simulated_flake")
        with patch.object(keyword_ideator, "_fetch_pytrends_sync",
                            side_effect=_boom):
            r = asyncio.run(keyword_ideator.fetch_pytrends(
                "seed", "en", "US"))
        # Wrapper catches sync exceptions too.
        assert "error" in r


# ═══════════════════════ LIVE-SERVER TESTS ═════════════════════════

_UNIQUE_SEED = f"seoc-test-{uuid.uuid4().hex[:8]}"


@pytest.fixture
def clean_db():
    _sync.keyword_lookups.delete_many(
        {"seed_keyword": {"$regex": r"^seoc-"}})
    _sync.keyword_search_history.delete_many(
        {"seed_keyword": {"$regex": r"^seoc-"}})
    yield
    _sync.keyword_lookups.delete_many(
        {"seed_keyword": {"$regex": r"^seoc-"}})
    _sync.keyword_search_history.delete_many(
        {"seed_keyword": {"$regex": r"^seoc-"}})


def test_customer_forbidden(clean_db):
    r = requests.post(f"{API}/keywords/ideate",
                        json={"seed_keyword": _UNIQUE_SEED},
                        headers=_customer_h(), timeout=15)
    assert r.status_code == 403


def test_tech_forbidden(clean_db):
    r = requests.post(f"{API}/keywords/ideate",
                        json={"seed_keyword": _UNIQUE_SEED},
                        headers=_tech_h(), timeout=15)
    assert r.status_code == 403


def test_cache_hit_returns_cached_true(clean_db):
    # Seed a fresh row directly (bypasses network) so the first
    # POST /ideate short-circuits to the cache.
    tid = _sync.tenants.find_one({"slug": "aquaterra"})["id"]
    seed = _UNIQUE_SEED
    _sync.keyword_lookups.insert_one({
        "id": str(uuid.uuid4()), "tenant_id": tid,
        "requested_by_user_id": "seed",
        "seed_keyword": seed, "language": "en", "region": "US",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "autocomplete_suggestions": ["cached one"],
        "question_suggestions": [], "comparison_suggestions": [],
        "preposition_suggestions": [],
        "trends_summary": {"interest_over_time": [],
                             "related_queries_top": [],
                             "related_queries_rising": []},
        "cache_ttl_seconds": 86400,
    })
    r = requests.post(f"{API}/keywords/ideate",
                        json={"seed_keyword": seed},
                        headers=_super_h(), timeout=30)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["cached"] is True
    assert body["autocomplete_suggestions"] == ["cached one"]


def test_force_refresh_bypasses_cache(clean_db):
    # Seed a stale-but-still-in-TTL row, then force_refresh=true.
    tid = _sync.tenants.find_one({"slug": "aquaterra"})["id"]
    seed = _UNIQUE_SEED + "-refresh"
    _sync.keyword_lookups.insert_one({
        "id": str(uuid.uuid4()), "tenant_id": tid,
        "requested_by_user_id": "seed",
        "seed_keyword": seed, "language": "en", "region": "US",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "autocomplete_suggestions": ["stale"],
        "question_suggestions": [], "comparison_suggestions": [],
        "preposition_suggestions": [],
        "trends_summary": None,
        "cache_ttl_seconds": 86400,
    })
    r = requests.post(f"{API}/keywords/ideate",
                        json={"seed_keyword": seed,
                                "force_refresh": True},
                        headers=_super_h(), timeout=60)
    assert r.status_code == 200
    assert r.json()["cached"] is False


def test_history_endpoint(clean_db):
    seed = _UNIQUE_SEED + "-hist"
    tid = _sync.tenants.find_one({"slug": "aquaterra"})["id"]
    _sync.keyword_lookups.insert_one({
        "id": "hist-cached", "tenant_id": tid,
        "requested_by_user_id": "seed",
        "seed_keyword": seed, "language": "en", "region": "US",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "autocomplete_suggestions": [], "question_suggestions": [],
        "comparison_suggestions": [], "preposition_suggestions": [],
        "trends_summary": None, "cache_ttl_seconds": 86400,
    })
    # Fire an ideate to log a history row.
    r = requests.post(f"{API}/keywords/ideate",
                        json={"seed_keyword": seed},
                        headers=_super_h(), timeout=30)
    assert r.status_code == 200
    h = requests.get(f"{API}/keywords/history",
                      headers=_super_h(), timeout=15).json()
    assert any(x["seed_keyword"] == seed for x in h["items"])


def test_cross_tenant_isolation(clean_db):
    other = _sync.tenants.find_one({"slug": "sunbelt"})
    if not other:
        pytest.skip("sunbelt tenant missing")
    seed = _UNIQUE_SEED + "-xt"
    _sync.keyword_lookups.insert_one({
        "id": "xt-cached", "tenant_id": other["id"],
        "requested_by_user_id": "seed",
        "seed_keyword": seed, "language": "en", "region": "US",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "autocomplete_suggestions": ["sunbelt-only"],
        "question_suggestions": [], "comparison_suggestions": [],
        "preposition_suggestions": [],
        "trends_summary": None, "cache_ttl_seconds": 86400,
    })
    # Aquaterra super_admin POST — should NOT return sunbelt cache,
    # must run a fresh lookup instead.
    r = requests.post(f"{API}/keywords/ideate",
                        json={"seed_keyword": seed},
                        headers=_super_h(), timeout=60)
    assert r.status_code == 200
    body = r.json()
    # Different tenant_id.
    assert body["tenant_id"] != other["id"]
    assert "sunbelt-only" not in body["autocomplete_suggestions"]


def test_rate_limit_21st_call(clean_db):
    # Direct-seed 20 history rows in the last hour for super_admin,
    # then verify a 21st POST /ideate returns 429.
    super_user = _sync.users.find_one(
        {"email": "super@aquaterra.com"})
    tid = _sync.tenants.find_one({"slug": "aquaterra"})["id"]
    now = datetime.now(timezone.utc)
    _sync.keyword_search_history.insert_many([{
        "id": str(uuid.uuid4()),
        "tenant_id": tid,
        "user_id": super_user["id"],
        "seed_keyword": f"seoc-rate-{i}",
        "requested_at": (now - timedelta(minutes=30)).isoformat(),
        "cached": False,
    } for i in range(20)])
    r = requests.post(f"{API}/keywords/ideate",
                        json={"seed_keyword": "seoc-rate-21"},
                        headers=_super_h(), timeout=15)
    assert r.status_code == 429, r.text
    assert "rate_limited" in r.text
