"""Phase 5c · pytest — Brand Mention Crawler.

Every search call is stubbed via ``search_fn`` injection so no real
Serper / Google CSE calls happen in CI.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path
from typing import Any, Dict, List

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient
from tests._shared_mongo import (
    shared_client as _shared_client,
    shared_db as _shared_db,
)


_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = _shared_db()
API = "http://localhost:8001/api"

# Motor caches an executor bound to the first event loop it sees; when
# pytest runs sequential _run() calls, subsequent loops get
# closed and motor blows up with "Event loop is closed". Share one
# module-level loop across every service call so motor stays happy,
# AND rebind the motor client to that loop so ``config.db`` — imported
# earlier by other tests — doesn't drag us onto a dead loop.
_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)

from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402
from services import brand_mentions as _bm_module  # noqa: E402
_FRESH_MOTOR = AsyncIOMotorClient(_ENV["MONGO_URL"], io_loop=_LOOP)
_FRESH_DB = _FRESH_MOTOR[_ENV["DB_NAME"]]
_bm_module.db = _FRESH_DB


def _run(coro):
    # Motor binds internals to whichever loop is current at first use.
    # Prior test modules can close their loops out from under us — force
    # our shared loop back to "current" for every service call.
    try:
        asyncio.set_event_loop(_LOOP)
    except Exception:
        pass
    return _LOOP.run_until_complete(coro)


def _login(email: str) -> str:
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": "password123"},
                       timeout=10)
    r.raise_for_status()
    return r.json()["access_token"]


def _tenant_id_of(email: str) -> str:
    return _sync.users.find_one({"email": email})["tenant_id"]


# ── 1. Adapter selection ────────────────────────────────────────
def test_adapter_selection_by_env(monkeypatch):
    from services import search_provider
    # None configured.
    monkeypatch.delenv("SERPER_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_CSE_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_CSE_CX", raising=False)
    assert search_provider.selected_provider() is None
    # Serper wins.
    monkeypatch.setenv("SERPER_API_KEY", "x")
    assert search_provider.selected_provider() == "serper"
    # Google fallback.
    monkeypatch.delenv("SERPER_API_KEY", raising=False)
    monkeypatch.setenv("GOOGLE_CSE_API_KEY", "y")
    monkeypatch.setenv("GOOGLE_CSE_CX", "z")
    assert search_provider.selected_provider() == "google_cse"
    # Empty-config path (no key).
    monkeypatch.delenv("GOOGLE_CSE_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_CSE_CX", raising=False)
    r = _run(search_provider.search("anything"))
    assert r["provider_configured"] is False
    assert r["results"] == []


# ── 2. Dedup — same URL twice → 1 insert + 1 update ─────────────
def test_dedup_via_http(monkeypatch):
    # Force Serper as active provider so run_crawl proceeds.
    monkeypatch.setenv("SERPER_API_KEY", "stub-key")

    # Monkey-patch the service-level search callable used by the
    # running FastAPI process is impossible from an out-of-process test.
    # So we call the pure service directly.
    from services import brand_mentions as bm

    tid = f"tenant_p5c_{uuid.uuid4().hex[:6]}"
    tenant = {"id": tid, "name": "Dedup Pools",
              "url": "https://dedup.example",
              "address": {"city": "Phoenix", "state": "AZ"}}
    _sync.brand_mentions.delete_many({"tenant_id": tid})
    _sync.brand_mention_runs.delete_many({"tenant_id": tid})
    async def stub_search(q, max_results=10):
        return {"provider": "serper", "provider_configured": True,
                "cost_est_usd": 0.003,
                "results": [
                    {"url": "https://example.com/blog/dedup-post",
                      "title": "Dedup Pools review", "snippet": "Great service." * 3,
                      "domain": "example.com"},
                    {"url": "https://forum.example.com/thread/1",
                      "title": "Forum thread", "snippet": "Discussion thread." * 4,
                      "domain": "forum.example.com"},
                ]}
    async def stub_sentiment(snippet: str, tenant_id: str):
        return None  # skip LLM
    try:
        r1 = _run(bm.run_crawl(tenant, queries=["dedup pools"],
                                        search_fn=stub_search,
                                        sentiment_fn=stub_sentiment))
        assert r1["new_mentions"] == 2
        assert r1["updated_mentions"] == 0
        # Second run of the same query → all should be updates.
        r2 = _run(bm.run_crawl(tenant, queries=["dedup pools"],
                                        search_fn=stub_search,
                                        sentiment_fn=stub_sentiment))
        # Every URL already existed → 0 new + 2 updates.
        assert r2["new_mentions"] == 0
        assert r2["updated_mentions"] == 2
        # And there are still exactly 2 rows in Mongo.
        n = _sync.brand_mentions.count_documents({"tenant_id": tid})
        assert n == 2, n
    finally:
        _sync.brand_mentions.delete_many({"tenant_id": tid})
        _sync.brand_mention_runs.delete_many({"tenant_id": tid})


# ── 3. Cost cap ─────────────────────────────────────────────────
def test_cost_cap_stops_further_queries(monkeypatch):
    monkeypatch.setenv("SERPER_API_KEY", "stub-key")
    from services import brand_mentions as bm

    tid = f"tenant_p5c_cost_{uuid.uuid4().hex[:6]}"
    tenant = {"id": tid, "name": "Cap Co",
              "address": {"city": "Phoenix", "state": "AZ"}}

    # Seed a prior-month row exceeding the cap so any next probe stops.
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    month_start = datetime(now.year, now.month, 1,
                              tzinfo=timezone.utc).isoformat()
    _sync.brand_mention_runs.insert_one({
        "tenant_id": tid, "ran_at": month_start,
        "cost_est_usd": bm.MONTHLY_COST_CAP_USD + 0.01,
        "provider": "serper", "queries_run": 5,
        "new_mentions": 0, "updated_mentions": 0})

    async def stub_search(q, max_results=10):
        return {"provider": "serper", "provider_configured": True,
                "cost_est_usd": 0.003,
                "results": [{"url": "https://x/y", "title": "t",
                              "snippet": "s", "domain": "x"}]}
    try:
        r = _run(bm.run_crawl(tenant, queries=["a", "b", "c"],
                                       search_fn=stub_search,
                                       sentiment_fn=lambda *_a, **_k: None))
        assert r["cost_capped"] is True
        assert r["new_mentions"] == 0
    finally:
        _sync.brand_mentions.delete_many({"tenant_id": tid})
        _sync.brand_mention_runs.delete_many({"tenant_id": tid})


# ── 4. Sentiment cache — same snippet twice → LLM called once ───
def test_sentiment_cache_short_circuits_second_call(monkeypatch):
    from services import brand_mentions as bm
    tid = f"tenant_p5c_sent_{uuid.uuid4().hex[:6]}"
    _sync.brand_sentiment_cache.delete_many({"tenant_id": tid})
    calls = {"n": 0}
    async def stub_llm(prompt: str) -> str:
        calls["n"] += 1
        return "positive"
    snippet = ("This is a genuinely good review of the pool service, "
                "highly recommended in the neighborhood.")
    try:
        s1 = _run(bm._sentiment(snippet, tid, llm_call=stub_llm))
        s2 = _run(bm._sentiment(snippet, tid, llm_call=stub_llm))
        assert s1 == "positive" and s2 == "positive"
        assert calls["n"] == 1, f"LLM stub called {calls['n']} times"
    finally:
        _sync.brand_sentiment_cache.delete_many({"tenant_id": tid})


# ── 5. Competitor tagging ───────────────────────────────────────
def test_competitor_domains_retag(monkeypatch):
    from services.brand_mentions import set_competitor_domains
    tid = f"tenant_p5c_comp_{uuid.uuid4().hex[:6]}"
    _sync.tenants.insert_one({"id": tid, "name": "Comp Co"})
    _sync.brand_mentions.insert_many([
        {"tenant_id": tid, "url": "https://acme-comp.com/x",
          "domain": "acme-comp.com", "mention_id": "m1",
          "discovered_at": "2026-07-01"},
        {"tenant_id": tid, "url": "https://other.com/x",
          "domain": "other.com", "mention_id": "m2",
          "discovered_at": "2026-07-01"},
    ])
    try:
        r = _run(set_competitor_domains(tid, ["acme-comp.com"]))
        assert r["retagged_true"] >= 1
        docs = list(_sync.brand_mentions.find({"tenant_id": tid}))
        by_url = {d["url"]: d for d in docs}
        assert by_url["https://acme-comp.com/x"]["is_competitor_domain"] is True
        assert by_url["https://other.com/x"]["is_competitor_domain"] is False
    finally:
        _sync.tenants.delete_one({"id": tid})
        _sync.brand_mentions.delete_many({"tenant_id": tid})


# ── 6. Role guard — tech + customer forbidden ───────────────────
@pytest.mark.parametrize("email", ["landscaper@aquaterra.com",
                                    "customer@aquaterra.com"])
def test_role_guard(email):
    tok = _login(email)
    for path, method, body in [
        ("/aeo/mentions/run-now", "post", {}),
        ("/aeo/mentions/dashboard", "get", None),
        ("/aeo/mentions/list", "get", None),
        ("/aeo/mentions/competitors", "post", {"domains": []}),
        ("/aeo/mentions/some_id/mark", "post", {"sentiment": "neutral"}),
    ]:
        if method == "post":
            r = requests.post(f"{API}{path}",
                               headers={"Authorization": f"Bearer {tok}"},
                               json=body or {}, timeout=10)
        else:
            r = requests.get(f"{API}{path}",
                              headers={"Authorization": f"Bearer {tok}"},
                              timeout=10)
        assert r.status_code == 403, f"{email} {path} → {r.status_code}"


# ── 7. Unconfigured-provider live endpoints return 200, not 500 ──
def test_endpoints_survive_missing_provider():
    # Manager account, live endpoint. Assumes CI has no SERPER/GOOGLE key.
    tok = _login("manager@aquaterra.com")
    r = requests.get(f"{API}/aeo/mentions/dashboard",
                       headers={"Authorization": f"Bearer {tok}"}, timeout=10)
    assert r.status_code == 200, r.text
    d = r.json()
    assert "provider_configured" in d
    # If provider isn't configured, run-now must still respond 200 with an
    # empty result set — never 500.
    if not d["provider_configured"]:
        rr = requests.post(f"{API}/aeo/mentions/run-now",
                             headers={"Authorization": f"Bearer {tok}"},
                             json={}, timeout=15)
        # Could be 200 (executed, no results) OR cooldown-skipped from a
        # prior test.
        assert rr.status_code == 200, rr.text
        body = rr.json()
        assert body.get("provider_configured") is False or body.get("skipped_reason") == "cooldown"
