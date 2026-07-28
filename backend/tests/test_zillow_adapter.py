"""Task TT · Feb 2026 — RapidAPI-Zillow adapter pytest.

Zero live network — every httpx call is monkey-patched. Cache is
exercised against a fresh in-memory fake so no test touches Mongo.
"""
from __future__ import annotations

import asyncio
import hashlib
import time
from datetime import datetime, timezone, timedelta
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


# ─── fixtures ────────────────────────────────────────────────────────
@pytest.fixture
def adapter_env(monkeypatch):
    """Reset adapter module state + env before each test."""
    from services.property_data import zillow_adapter as za

    # Force test-scope-allowing address for most tests via synthetic
    # token. Individual tests override APP_ENV/allowlist as needed.
    monkeypatch.setenv("APP_ENV", "preview")
    monkeypatch.delenv("ZILLOW_TEST_ALLOWLIST_ADDRESSES", raising=False)
    monkeypatch.setenv("RAPIDAPI_KEY", "test-key-xxx")
    monkeypatch.setenv("RAPIDAPI_ZILLOW_HOST", "zillow-fake.p.rapidapi.com")

    fake_db = _FakeDB()
    monkeypatch.setattr(za, "db", fake_db)
    za._reset_throttle_for_tests()
    za._indexes_ready = False
    return za, fake_db


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro) if False else asyncio.run(coro)


# ═══════════════════════════════════════════════════════════════════
# 1. keys_missing → 503-graceful (no HTTP call, no raise)
# ═══════════════════════════════════════════════════════════════════
def test_keys_missing_returns_graceful_for_all_methods(adapter_env, monkeypatch):
    za, _ = adapter_env
    monkeypatch.delenv("RAPIDAPI_KEY", raising=False)
    monkeypatch.delenv("RAPIDAPI_ZILLOW_HOST", raising=False)

    fake_http = _FakeAsyncClient([])  # zero responses queued — MUST NOT be called
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

    # Seed cache directly with a fresh (non-expired) doc.
    key = za._cache_key("search_by_address", "742 aquaterra way")
    fake_db[za.CACHE_COLL].docs[key] = {
        "cache_key": key,
        "response_json": {"props": [{"zpid": "cached-1"}]},
        "expires_at": za._now_utc() + timedelta(days=6),
    }

    fake_http = _FakeAsyncClient([])
    client = za.ZillowClient(http_client=fake_http)
    r = _run(client.search_by_address("742 aquaterra way"))

    assert r["unavailable"] is False
    assert r["cached"] is True
    assert r["data"] == {"props": [{"zpid": "cached-1"}]}
    assert fake_http.calls == []


# ═══════════════════════════════════════════════════════════════════
# 3. cache miss — live call, cache writes fresh doc with expires_at
# ═══════════════════════════════════════════════════════════════════
def test_cache_miss_writes_fresh_entry(adapter_env):
    za, fake_db = adapter_env

    payload = {"props": [{"zpid": "fresh-1"}]}
    fake_http = _FakeAsyncClient([_FakeResponse(200, payload)])
    client = za.ZillowClient(http_client=fake_http)

    r = _run(client.search_by_address("100 aquaterra ave"))

    assert r["unavailable"] is False
    assert r["cached"] is False
    assert r["data"] == payload
    assert len(fake_http.calls) == 1

    # cache written
    key = za._cache_key("search_by_address", "100 aquaterra ave")
    doc = fake_db[za.CACHE_COLL].docs[key]
    assert doc["response_json"] == payload
    exp = doc["expires_at"]
    # 7-day TTL (within a small clock-skew tolerance)
    assert timedelta(days=6, hours=23) < (exp - za._now_utc()) <= timedelta(days=7, minutes=1)


# ═══════════════════════════════════════════════════════════════════
# 4. 429 arms throttle memo and returns quota_exhausted
# ═══════════════════════════════════════════════════════════════════
def test_429_arms_throttle_and_returns_quota(adapter_env):
    za, _ = adapter_env
    fake_http = _FakeAsyncClient([_FakeResponse(429, text_body="rate limit")])
    client = za.ZillowClient(http_client=fake_http)

    r = _run(client.search_by_address("55 aquaterra"))

    assert r == {"unavailable": True, "reason": za.REASON_QUOTA_EXHAUSTED}
    # Throttle armed
    host = za._rapidapi_host()
    assert host in za._throttle_until
    assert za._throttle_until[host] > time.time()


# ═══════════════════════════════════════════════════════════════════
# 5. throttle active → subsequent call skips HTTP
# ═══════════════════════════════════════════════════════════════════
def test_throttle_active_short_circuits(adapter_env):
    za, _ = adapter_env
    host = za._rapidapi_host()
    za._throttle_until[host] = time.time() + 60  # armed for 60s

    fake_http = _FakeAsyncClient([])  # would fail if hit
    client = za.ZillowClient(http_client=fake_http)

    r = _run(client.property_detail("z-throttled-aquaterra"))
    assert r == {"unavailable": True, "reason": za.REASON_QUOTA_EXHAUSTED}
    assert fake_http.calls == []


# ═══════════════════════════════════════════════════════════════════
# 6. test-scope refusal — non-prod + non-synthetic address
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
# 7. test-scope allowlist — env unlocks a specific address
# ═══════════════════════════════════════════════════════════════════
def test_test_scope_allowlist_env(adapter_env, monkeypatch):
    za, _ = adapter_env
    monkeypatch.setenv("APP_ENV", "preview")
    monkeypatch.setenv(
        "ZILLOW_TEST_ALLOWLIST_ADDRESSES",
        "evergreen terrace, springfield",
    )

    payload = {"props": [{"zpid": "allowlisted-1"}]}
    fake_http = _FakeAsyncClient([_FakeResponse(200, payload)])
    client = za.ZillowClient(http_client=fake_http)

    r = _run(client.search_by_address("742 Evergreen Terrace, Springfield"))
    assert r["unavailable"] is False
    assert r["data"] == payload
    assert len(fake_http.calls) == 1


# ═══════════════════════════════════════════════════════════════════
# 8. production env skips test-scope guard
# ═══════════════════════════════════════════════════════════════════
def test_production_env_skips_test_scope_guard(adapter_env, monkeypatch):
    za, _ = adapter_env
    monkeypatch.setenv("APP_ENV", "production")

    payload = {"props": [{"zpid": "prod-1"}]}
    fake_http = _FakeAsyncClient([_FakeResponse(200, payload)])
    client = za.ZillowClient(http_client=fake_http)

    r = _run(client.search_by_address("742 Evergreen Terrace, Springfield"))
    assert r["unavailable"] is False
    assert r["data"] == payload


# ═══════════════════════════════════════════════════════════════════
# 9. TTL expiry — stale cache doc is ignored, fresh call fires
# ═══════════════════════════════════════════════════════════════════
def test_ttl_expiry_forces_refresh(adapter_env):
    za, fake_db = adapter_env

    key = za._cache_key("search_by_address", "300 aquaterra st")
    fake_db[za.CACHE_COLL].docs[key] = {
        "cache_key": key,
        "response_json": {"stale": True},
        "expires_at": za._now_utc() - timedelta(minutes=1),
    }
    fresh_payload = {"stale": False, "zpid": "fresh"}
    fake_http = _FakeAsyncClient([_FakeResponse(200, fresh_payload)])
    client = za.ZillowClient(http_client=fake_http)

    r = _run(client.search_by_address("300 aquaterra st"))
    assert r["unavailable"] is False
    assert r["cached"] is False
    assert r["data"] == fresh_payload
    assert len(fake_http.calls) == 1


# ═══════════════════════════════════════════════════════════════════
# 10. 404 → not_found (not cached)
# ═══════════════════════════════════════════════════════════════════
def test_404_returns_not_found(adapter_env):
    za, fake_db = adapter_env
    fake_http = _FakeAsyncClient([_FakeResponse(404, text_body="nope")])
    client = za.ZillowClient(http_client=fake_http)

    r = _run(client.property_detail("does-not-exist-aquaterra"))
    assert r == {"unavailable": True, "reason": za.REASON_NOT_FOUND}
    # Not cached — a real address that missed once may exist tomorrow.
    key = za._cache_key("property_detail", "does-not-exist-aquaterra")
    assert key not in fake_db[za.CACHE_COLL].docs


# ═══════════════════════════════════════════════════════════════════
# 11. Non-JSON / 5xx → provider_error
# ═══════════════════════════════════════════════════════════════════
def test_5xx_returns_provider_error(adapter_env):
    za, _ = adapter_env
    fake_http = _FakeAsyncClient([_FakeResponse(502, text_body="bad gateway")])
    client = za.ZillowClient(http_client=fake_http)

    r = _run(client.zestimate("z-5xx-aquaterra"))
    assert r == {"unavailable": True, "reason": za.REASON_PROVIDER_ERROR}


# ═══════════════════════════════════════════════════════════════════
# 12. Startup log reflects keys state (True + False)
# ═══════════════════════════════════════════════════════════════════
def test_startup_log_reflects_keys_state(adapter_env, monkeypatch):
    za, _ = adapter_env
    assert "keys_configured=True" in za.startup_log_line()
    monkeypatch.delenv("RAPIDAPI_KEY", raising=False)
    assert "keys_configured=False" in za.startup_log_line()


# ═══════════════════════════════════════════════════════════════════
# 13. Second call after cache write hits cache (no second HTTP)
# ═══════════════════════════════════════════════════════════════════
def test_second_call_hits_cache(adapter_env):
    za, _ = adapter_env
    payload = {"props": [{"zpid": "roundtrip-1"}]}
    fake_http = _FakeAsyncClient([_FakeResponse(200, payload)])
    client = za.ZillowClient(http_client=fake_http)

    r1 = _run(client.search_by_address("77 aquaterra ln"))
    r2 = _run(client.search_by_address("77 aquaterra ln"))

    assert r1["cached"] is False
    assert r2["cached"] is True
    assert r2["data"] == payload
    assert len(fake_http.calls) == 1, "second call MUST hit cache, not network"
