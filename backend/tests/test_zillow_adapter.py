"""Task TT / TT.5 · Feb 2026 — OpenWebNinja-Zillow adapter pytest.

Zero live network — every httpx call is monkey-patched. Cache is
exercised against a fresh in-memory fake so no test touches Mongo.
"""
from __future__ import annotations

import asyncio
import time
from datetime import timedelta
from typing import Any, Dict, List, Optional

import pytest


# ─── fake httpx.AsyncClient ──────────────────────────────────────────
class _FakeResponse:
    def __init__(self, status_code: int, payload: Optional[Dict[str, Any]] = None,
                 text_body: str = ""):
        self.status_code = status_code
        self._payload = payload
        self.text = text_body or (str(payload) if payload is not None else "")

    def json(self):
        if self._payload is None:
            raise ValueError("no json body")
        return self._payload


class _FakeAsyncClient:
    """Records every .get() and returns queued responses in order."""

    def __init__(self, queue: List[_FakeResponse]):
        self.queue = list(queue)
        self.calls: List[Dict[str, Any]] = []

    async def get(self, url, params=None, headers=None):
        self.calls.append({"url": url, "params": params, "headers": headers})
        if not self.queue:
            raise AssertionError("FakeAsyncClient: no more responses queued")
        return self.queue.pop(0)

    async def aclose(self):
        pass


# ─── fake Mongo collection ───────────────────────────────────────────
class _FakeCollection:
    def __init__(self):
        self.docs: Dict[str, Dict[str, Any]] = {}

    async def create_index(self, *args, **kwargs):
        return "ok"

    async def find_one(self, query: Dict[str, Any]):
        key = query.get("cache_key")
        return self.docs.get(key)

    async def update_one(self, query: Dict[str, Any], update: Dict[str, Any],
                          upsert: bool = False):
        key = query.get("cache_key")
        setdoc = update.get("$set", {})
        if key in self.docs:
            self.docs[key].update(setdoc)
        elif upsert:
            self.docs[key] = dict(setdoc)


class _FakeDB:
    def __init__(self):
        self._colls: Dict[str, _FakeCollection] = {}

    def __getitem__(self, name: str) -> _FakeCollection:
        if name not in self._colls:
            self._colls[name] = _FakeCollection()
        return self._colls[name]


# ─── OpenWebNinja response fixtures ──────────────────────────────────
# The provider wraps every payload under a top-level ``data`` key.
OWN_SEARCH_OK = {"data": {"zpid": "own-1", "streetAddress": "742 Aquaterra Way",
                           "zestimate": 425000, "bedrooms": 3, "bathrooms": 2}}
OWN_PROPERTY_OK = {"data": {"zpid": "own-detail-1", "streetAddress": "77 Aquaterra Ln",
                             "yearBuilt": 1998}}
OWN_ZESTIMATE_OK = {"data": {"zpid": "own-detail-1", "zestimate": 512000,
                              "priceHistory": [{"date": "2024-06-01", "price": 500000}]}}
OWN_EMPTY_DATA = {"data": None}  # OpenWebNinja "no match" shape


# ─── fixtures ────────────────────────────────────────────────────────
@pytest.fixture
def adapter_env(monkeypatch):
    """Reset adapter module state + env before each test."""
    from services.property_data import zillow_adapter as za

    monkeypatch.setenv("APP_ENV", "preview")
    monkeypatch.delenv("ZILLOW_TEST_ALLOWLIST_ADDRESSES", raising=False)
    # Set BOTH variant names to a synthetic value so we can assert the
    # env-per-call resolution order (ZILLOW variant preferred).
    monkeypatch.setenv("OPENWEB_NINJA_ZILLOW_API_KEY", "test-own-zillow-key")
    monkeypatch.delenv("OPENWEB_NINJA_API_KEY", raising=False)

    fake_db = _FakeDB()
    monkeypatch.setattr(za, "db", fake_db)
    za._reset_throttle_for_tests()
    za._indexes_ready = False
    return za, fake_db


def _run(coro):
    return asyncio.run(coro)


# ═══════════════════════════════════════════════════════════════════
# 1. keys_missing → graceful (no HTTP call, no raise)
# ═══════════════════════════════════════════════════════════════════
def test_keys_missing_returns_graceful_for_all_methods(adapter_env, monkeypatch):
    za, _ = adapter_env
    monkeypatch.delenv("OPENWEB_NINJA_ZILLOW_API_KEY", raising=False)
    monkeypatch.delenv("OPENWEB_NINJA_API_KEY", raising=False)

    fake_http = _FakeAsyncClient([])  # zero responses — MUST NOT be called
    client = za.ZillowClient(http_client=fake_http)

    r1 = _run(client.search_by_address("123 aquaterra way"))
    r2 = _run(client.property_detail("z-1"))
    r3 = _run(client.zestimate("z-1"))

    assert r1 == {"unavailable": True, "reason": za.REASON_KEYS_NOT_CONFIGURED}
    assert r2 == {"unavailable": True, "reason": za.REASON_KEYS_NOT_CONFIGURED}
    assert r3 == {"unavailable": True, "reason": za.REASON_KEYS_NOT_CONFIGURED}
    assert fake_http.calls == [], "keys_missing MUST short-circuit before HTTP"


# ═══════════════════════════════════════════════════════════════════
# 2. cache hit — no HTTP call, cached=True
# ═══════════════════════════════════════════════════════════════════
def test_cache_hit_short_circuits_http(adapter_env):
    za, fake_db = adapter_env
    key = za._cache_key("search_by_address", "742 aquaterra way")
    fake_db[za.CACHE_COLL].docs[key] = {
        "cache_key": key,
        "response_json": OWN_SEARCH_OK,
        "expires_at": za._now_utc() + timedelta(days=6),
    }
    fake_http = _FakeAsyncClient([])
    client = za.ZillowClient(http_client=fake_http)

    r = _run(client.search_by_address("742 aquaterra way"))
    assert r["unavailable"] is False
    assert r["cached"] is True
    assert r["data"] == OWN_SEARCH_OK
    assert fake_http.calls == []


# ═══════════════════════════════════════════════════════════════════
# 3. cache miss — live call → writes fresh entry, sends x-api-key header
# ═══════════════════════════════════════════════════════════════════
def test_cache_miss_writes_fresh_entry_and_uses_x_api_key(adapter_env):
    za, fake_db = adapter_env
    fake_http = _FakeAsyncClient([_FakeResponse(200, OWN_SEARCH_OK)])
    client = za.ZillowClient(http_client=fake_http)

    r = _run(client.search_by_address("100 aquaterra ave"))

    assert r["unavailable"] is False
    assert r["cached"] is False
    assert r["data"] == OWN_SEARCH_OK
    assert len(fake_http.calls) == 1

    # ── the actual call assertions — this is what TT.5 reconciles ──
    call = fake_http.calls[0]
    assert call["url"] == f"{za.PROVIDER_BASE_URL}/property-details-address"
    assert call["params"] == {"address": "100 aquaterra ave"}
    assert call["headers"] == {"x-api-key": "test-own-zillow-key"}
    # No RapidAPI headers may leak in.
    assert "x-rapidapi-key" not in call["headers"]
    assert "x-rapidapi-host" not in call["headers"]

    # Cache written with 7-day TTL
    key = za._cache_key("search_by_address", "100 aquaterra ave")
    doc = fake_db[za.CACHE_COLL].docs[key]
    assert doc["response_json"] == OWN_SEARCH_OK
    exp = doc["expires_at"]
    assert timedelta(days=6, hours=23) < (exp - za._now_utc()) <= timedelta(days=7, minutes=1)


# ═══════════════════════════════════════════════════════════════════
# 4. property_detail hits /property?zpid= endpoint
# ═══════════════════════════════════════════════════════════════════
def test_property_detail_hits_property_endpoint(adapter_env):
    za, _ = adapter_env
    fake_http = _FakeAsyncClient([_FakeResponse(200, OWN_PROPERTY_OK)])
    client = za.ZillowClient(http_client=fake_http)

    r = _run(client.property_detail("own-detail-1-aquaterra"))
    assert r["unavailable"] is False
    assert r["data"] == OWN_PROPERTY_OK

    call = fake_http.calls[0]
    assert call["url"] == f"{za.PROVIDER_BASE_URL}/property"
    assert call["params"] == {"zpid": "own-detail-1-aquaterra"}


# ═══════════════════════════════════════════════════════════════════
# 5. zestimate reuses /property (OpenWebNinja has no /zestimate)
# ═══════════════════════════════════════════════════════════════════
def test_zestimate_reuses_property_endpoint(adapter_env):
    za, _ = adapter_env
    fake_http = _FakeAsyncClient([_FakeResponse(200, OWN_ZESTIMATE_OK)])
    client = za.ZillowClient(http_client=fake_http)

    r = _run(client.zestimate("own-detail-1-aquaterra"))
    assert r["unavailable"] is False
    assert r["data"] == OWN_ZESTIMATE_OK
    assert fake_http.calls[0]["url"] == f"{za.PROVIDER_BASE_URL}/property"


# ═══════════════════════════════════════════════════════════════════
# 6. 429 arms throttle memo and returns quota_exhausted
# ═══════════════════════════════════════════════════════════════════
def test_429_arms_throttle_and_returns_quota(adapter_env):
    za, _ = adapter_env
    fake_http = _FakeAsyncClient([_FakeResponse(429, text_body="rate limit")])
    client = za.ZillowClient(http_client=fake_http)

    r = _run(client.search_by_address("55 aquaterra"))
    assert r == {"unavailable": True, "reason": za.REASON_QUOTA_EXHAUSTED}
    assert za.PROVIDER_HOST in za._throttle_until
    assert za._throttle_until[za.PROVIDER_HOST] > time.time()


# ═══════════════════════════════════════════════════════════════════
# 7. throttle active → subsequent call skips HTTP
# ═══════════════════════════════════════════════════════════════════
def test_throttle_active_short_circuits(adapter_env):
    za, _ = adapter_env
    za._throttle_until[za.PROVIDER_HOST] = time.time() + 60

    fake_http = _FakeAsyncClient([])
    client = za.ZillowClient(http_client=fake_http)

    r = _run(client.property_detail("z-throttled-aquaterra"))
    assert r == {"unavailable": True, "reason": za.REASON_QUOTA_EXHAUSTED}
    assert fake_http.calls == []


# ═══════════════════════════════════════════════════════════════════
# 8. test-scope refusal — non-prod + non-synthetic
# ═══════════════════════════════════════════════════════════════════
def test_test_scope_refuses_non_synthetic(adapter_env, monkeypatch):
    za, _ = adapter_env
    monkeypatch.setenv("APP_ENV", "preview")

    fake_http = _FakeAsyncClient([])
    client = za.ZillowClient(http_client=fake_http)

    r = _run(client.search_by_address("742 Evergreen Terrace, Springfield"))
    assert r == {"unavailable": True, "reason": za.REASON_TEST_SCOPE_REFUSED}
    assert fake_http.calls == []


# ═══════════════════════════════════════════════════════════════════
# 9. test-scope allowlist — env unlocks a specific address
# ═══════════════════════════════════════════════════════════════════
def test_test_scope_allowlist_env(adapter_env, monkeypatch):
    za, _ = adapter_env
    monkeypatch.setenv("APP_ENV", "preview")
    monkeypatch.setenv(
        "ZILLOW_TEST_ALLOWLIST_ADDRESSES",
        "evergreen terrace, springfield",
    )
    fake_http = _FakeAsyncClient([_FakeResponse(200, OWN_SEARCH_OK)])
    client = za.ZillowClient(http_client=fake_http)

    r = _run(client.search_by_address("742 Evergreen Terrace, Springfield"))
    assert r["unavailable"] is False
    assert r["data"] == OWN_SEARCH_OK


# ═══════════════════════════════════════════════════════════════════
# 10. production env skips test-scope guard
# ═══════════════════════════════════════════════════════════════════
def test_production_env_skips_test_scope_guard(adapter_env, monkeypatch):
    za, _ = adapter_env
    monkeypatch.setenv("APP_ENV", "production")
    fake_http = _FakeAsyncClient([_FakeResponse(200, OWN_SEARCH_OK)])
    client = za.ZillowClient(http_client=fake_http)

    r = _run(client.search_by_address("742 Evergreen Terrace, Springfield"))
    assert r["unavailable"] is False


# ═══════════════════════════════════════════════════════════════════
# 11. TTL expiry — stale cache doc ignored, fresh call fires
# ═══════════════════════════════════════════════════════════════════
def test_ttl_expiry_forces_refresh(adapter_env):
    za, fake_db = adapter_env
    key = za._cache_key("search_by_address", "300 aquaterra st")
    fake_db[za.CACHE_COLL].docs[key] = {
        "cache_key": key,
        "response_json": {"stale": True},
        "expires_at": za._now_utc() - timedelta(minutes=1),
    }
    fresh = {"data": {"zpid": "fresh-1", "streetAddress": "300 Aquaterra St"}}
    fake_http = _FakeAsyncClient([_FakeResponse(200, fresh)])
    client = za.ZillowClient(http_client=fake_http)

    r = _run(client.search_by_address("300 aquaterra st"))
    assert r["unavailable"] is False
    assert r["cached"] is False
    assert r["data"] == fresh
    assert len(fake_http.calls) == 1


# ═══════════════════════════════════════════════════════════════════
# 12. 404 → not_found (not cached)
# ═══════════════════════════════════════════════════════════════════
def test_404_returns_not_found(adapter_env):
    za, fake_db = adapter_env
    fake_http = _FakeAsyncClient([_FakeResponse(404, text_body="nope")])
    client = za.ZillowClient(http_client=fake_http)

    r = _run(client.property_detail("does-not-exist-aquaterra"))
    assert r == {"unavailable": True, "reason": za.REASON_NOT_FOUND}
    key = za._cache_key("property_detail", "does-not-exist-aquaterra")
    assert key not in fake_db[za.CACHE_COLL].docs


# ═══════════════════════════════════════════════════════════════════
# 13. OpenWebNinja "empty data" 200 → not_found (provider-specific
#     idiom: it returns HTTP 200 with ``{"data": null}`` on no match)
# ═══════════════════════════════════════════════════════════════════
def test_empty_data_wrapper_returns_not_found(adapter_env):
    za, fake_db = adapter_env
    fake_http = _FakeAsyncClient([_FakeResponse(200, OWN_EMPTY_DATA)])
    client = za.ZillowClient(http_client=fake_http)

    r = _run(client.search_by_address("999 phantom aquaterra"))
    assert r == {"unavailable": True, "reason": za.REASON_NOT_FOUND}
    # Not cached — same rationale as 404.
    key = za._cache_key("search_by_address", "999 phantom aquaterra")
    assert key not in fake_db[za.CACHE_COLL].docs


# ═══════════════════════════════════════════════════════════════════
# 14. 5xx → provider_error
# ═══════════════════════════════════════════════════════════════════
def test_5xx_returns_provider_error(adapter_env):
    za, _ = adapter_env
    fake_http = _FakeAsyncClient([_FakeResponse(502, text_body="bad gateway")])
    client = za.ZillowClient(http_client=fake_http)

    r = _run(client.zestimate("z-5xx-aquaterra"))
    assert r == {"unavailable": True, "reason": za.REASON_PROVIDER_ERROR}


# ═══════════════════════════════════════════════════════════════════
# 15. Startup log reflects provider + keys state (True + False)
# ═══════════════════════════════════════════════════════════════════
def test_startup_log_reflects_provider_and_keys_state(adapter_env, monkeypatch):
    za, _ = adapter_env
    banner_on = za.startup_log_line()
    assert "provider=openwebninja" in banner_on
    assert "keys_configured=True" in banner_on

    monkeypatch.delenv("OPENWEB_NINJA_ZILLOW_API_KEY", raising=False)
    monkeypatch.delenv("OPENWEB_NINJA_API_KEY", raising=False)
    banner_off = za.startup_log_line()
    assert "provider=openwebninja" in banner_off
    assert "keys_configured=False" in banner_off


# ═══════════════════════════════════════════════════════════════════
# 16. Env-per-call resolution order — ZILLOW variant preferred, but
#     if only OPENWEB_NINJA_API_KEY is set the adapter still arms.
# ═══════════════════════════════════════════════════════════════════
def test_key_resolution_falls_back_to_base_env(adapter_env, monkeypatch):
    za, _ = adapter_env
    monkeypatch.delenv("OPENWEB_NINJA_ZILLOW_API_KEY", raising=False)
    monkeypatch.setenv("OPENWEB_NINJA_API_KEY", "fallback-key-xxx")

    fake_http = _FakeAsyncClient([_FakeResponse(200, OWN_SEARCH_OK)])
    client = za.ZillowClient(http_client=fake_http)
    r = _run(client.search_by_address("400 aquaterra"))
    assert r["unavailable"] is False
    assert fake_http.calls[0]["headers"] == {"x-api-key": "fallback-key-xxx"}


# ═══════════════════════════════════════════════════════════════════
# 17. Second call after cache write hits cache (no second HTTP)
# ═══════════════════════════════════════════════════════════════════
def test_second_call_hits_cache(adapter_env):
    za, _ = adapter_env
    fake_http = _FakeAsyncClient([_FakeResponse(200, OWN_SEARCH_OK)])
    client = za.ZillowClient(http_client=fake_http)

    r1 = _run(client.search_by_address("77 aquaterra ln"))
    r2 = _run(client.search_by_address("77 aquaterra ln"))

    assert r1["cached"] is False
    assert r2["cached"] is True
    assert r2["data"] == OWN_SEARCH_OK
    assert len(fake_http.calls) == 1
