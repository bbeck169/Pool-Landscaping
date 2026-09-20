"""Phase 6 · pytest — Reputation Response Drafts.

Stubs Claude via ``llm_call`` injection where possible, and hits the
live FastAPI endpoints for role-guard + status-mirror checks.
"""
from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient
from tests._shared_mongo import (
    shared_client as _shared_client,
    shared_db as _shared_db,
)


_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = _shared_db()
API = "http://localhost:8001/api"

# Shared loop + fresh motor client bound to it (see Phase 5c note).
_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)
from services import response_drafts as _rd_module  # noqa: E402
_FRESH_MOTOR = AsyncIOMotorClient(_ENV["MONGO_URL"], io_loop=_LOOP)
_rd_module.db = _FRESH_MOTOR[_ENV["DB_NAME"]]


def _run(coro):
    try:
        asyncio.set_event_loop(_LOOP)
    except Exception:
        pass
    # Phase 10 hardening — other pytest files may share the response_drafts
    # module and clobber `db` with their own loop-bound Motor client. Re-bind
    # before each run so our loop-bound client is always in use.
    _rd_module.db = _FRESH_MOTOR[_ENV["DB_NAME"]]
    return _LOOP.run_until_complete(coro)


def _login(email: str) -> str:
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": "password123"}, timeout=10)
    r.raise_for_status()
    return r.json()["access_token"]


def _seed_mention(*, domain: str, sentiment: str = "negative",
                     snippet: str = "This company was awful, don't use them.") -> str:
    tid = _sync.users.find_one({"email": "manager@aquaterra.com"})["tenant_id"]
    mid = f"p6_{uuid.uuid4().hex[:10]}"
    _sync.brand_mentions.insert_one({
        "tenant_id": tid, "mention_id": mid,
        "url": f"https://{domain}/post/1", "domain": domain,
        "title": "Bad review", "snippet": snippet,
        "sentiment": sentiment, "is_competitor_domain": False,
        "is_own_domain": False, "discovered_at": "2026-07-30"})
    return mid


def _tenant_row():
    tid = _sync.users.find_one({"email": "manager@aquaterra.com"})["tenant_id"]
    return {"id": tid, **(_sync.tenants.find_one({"id": tid}) or {})}


# ── 1. Platform detection ──────────────────────────────────────────
def test_platform_detection():
    from services.response_drafts import detect_platform
    assert detect_platform("www.yelp.com") == "yelp"
    assert detect_platform("nextdoor.com") == "nextdoor"
    assert detect_platform("reddit.com") == "reddit"
    assert detect_platform("business.facebook.com") == "facebook"
    assert detect_platform("google.com", "https://google.com/maps/place/foo") == "google_reviews"
    assert detect_platform("randomsite.io") == "generic"


# ── 2. Draft creation with stubbed LLM ────────────────────────────
def test_draft_creation_calls_stub_once_and_persists():
    from services import response_drafts as rd
    rd.reset_rate_limit_for_tests()
    mid = _seed_mention(domain="yelp.com")
    tenant = _tenant_row()
    calls = {"n": 0, "systems": [], "users": []}
    async def stub(system: str, user: str):
        calls["n"] += 1
        calls["systems"].append(system); calls["users"].append(user)
        return {"text": "We're truly sorry to hear about your experience — please call us so we can make it right.", "tokens_used": 42}
    try:
        r1 = _run(rd.create_or_get_draft(tenant=tenant,
            mention=_sync.brand_mentions.find_one({"mention_id": mid}),
            tone="empathetic", user_id="u1", llm_call=stub))
        assert r1.get("draft_text"), r1
        assert r1["platform"] == "yelp"
        assert r1["cost_est_usd"] > 0
        # 24h dedup — second call returns cached, stub NOT called again.
        r2 = _run(rd.create_or_get_draft(tenant=tenant,
            mention=_sync.brand_mentions.find_one({"mention_id": mid}),
            tone="empathetic", user_id="u1", llm_call=stub))
        assert r2["cached"] is True
        assert r2["draft_id"] == r1["draft_id"]
        assert calls["n"] == 1
        # Regenerate → new call, new row.
        r3 = _run(rd.create_or_get_draft(tenant=tenant,
            mention=_sync.brand_mentions.find_one({"mention_id": mid}),
            tone="empathetic", regenerate=True, user_id="u1", llm_call=stub))
        assert calls["n"] == 2
        assert r3.get("cached", False) is False
        assert r3["draft_id"] != r1["draft_id"]
    finally:
        _sync.mention_response_drafts.delete_many({"mention_id": mid})
        _sync.brand_mentions.delete_one({"mention_id": mid})


# ── 3. Length hint present in prompt per platform ──────────────────
def test_prompt_length_hints_per_platform():
    from services import response_drafts as rd
    rd.reset_rate_limit_for_tests()
    tenant = _tenant_row()
    prompts = {}
    async def spy(system, user):
        # Store latest prompt then return dummy.
        prompts["last"] = user
        return {"text": "ok reply", "tokens_used": 5}
    for dom, plat, cap in [("yelp.com", "yelp", 750),
                              ("reddit.com", "reddit", 400)]:
        mid = _seed_mention(domain=dom)
        try:
            _run(rd.create_or_get_draft(tenant=tenant,
                mention=_sync.brand_mentions.find_one({"mention_id": mid}),
                tone="empathetic", llm_call=spy))
            assert f"Max length: {cap}" in prompts["last"], (dom, prompts["last"])
            assert f"Platform: {plat}" in prompts["last"]
        finally:
            _sync.mention_response_drafts.delete_many({"mention_id": mid})
            _sync.brand_mentions.delete_one({"mention_id": mid})


# ── 4. Rate limit — 11th call → 429 (unit) ────────────────────────
def test_rate_limit_after_10_calls():
    from services.response_drafts import (check_rate_limit,
                                             reset_rate_limit_for_tests)
    reset_rate_limit_for_tests()
    tid = "rl-tenant"
    for i in range(10):
        assert check_rate_limit(tid) is None, i
    retry = check_rate_limit(tid)
    assert isinstance(retry, int) and retry > 0


# ── 5. Role guard on all 4 endpoints ──────────────────────────────
@pytest.mark.parametrize("email", ["landscaper@aquaterra.com",
                                    "customer@aquaterra.com"])
def test_role_guard(email):
    tok = _login(email)
    for method, path, body in [
        ("post",   "/aeo/mentions/abc/response/draft", {"tone": "empathetic"}),
        ("get",    "/aeo/mentions/abc/response/drafts", None),
        ("post",   "/aeo/response/drafts/xyz",          {"status": "posted"}),
        ("delete", "/aeo/response/drafts/xyz",          None),
    ]:
        headers = {"Authorization": f"Bearer {tok}"}
        if method == "post":
            r = requests.post(f"{API}{path}", headers=headers,
                               json=body or {}, timeout=10)
        elif method == "get":
            r = requests.get(f"{API}{path}", headers=headers, timeout=10)
        else:
            r = requests.delete(f"{API}{path}", headers=headers, timeout=10)
        assert r.status_code == 403, f"{email} {method} {path} → {r.status_code}"


# ── 6. Status transition mirrors to brand_mentions ────────────────
def test_status_update_mirrors_to_brand_mention():
    from services import response_drafts as rd
    rd.reset_rate_limit_for_tests()
    mid = _seed_mention(domain="reddit.com")
    tenant = _tenant_row()
    async def stub(s, u): return {"text": "Sorry to hear that, please DM us.", "tokens_used": 8}
    try:
        d = _run(rd.create_or_get_draft(tenant=tenant,
            mention=_sync.brand_mentions.find_one({"mention_id": mid}),
            tone="empathetic", llm_call=stub))
        # Update to "posted".
        upd = _run(rd.update_draft(tenant_id=tenant["id"],
                                       draft_id=d["draft_id"],
                                       status="posted", user_id="u1"))
        assert upd["status"] == "posted"
        m = _sync.brand_mentions.find_one({"mention_id": mid})
        assert m["latest_draft_status"] == "posted"
    finally:
        _sync.mention_response_drafts.delete_many({"mention_id": mid})
        _sync.brand_mentions.delete_one({"mention_id": mid})


# ── 7. Discard sets status without hard-delete ────────────────────
def test_discard_soft_delete():
    from services import response_drafts as rd
    rd.reset_rate_limit_for_tests()
    mid = _seed_mention(domain="facebook.com")
    tenant = _tenant_row()
    async def stub(s, u): return {"text": "Thanks for the feedback, please contact us.", "tokens_used": 5}
    try:
        d = _run(rd.create_or_get_draft(tenant=tenant,
            mention=_sync.brand_mentions.find_one({"mention_id": mid}),
            tone="professional", llm_call=stub))
        _run(rd.update_draft(tenant_id=tenant["id"],
                                 draft_id=d["draft_id"],
                                 status="discarded", user_id="u1"))
        row = _sync.mention_response_drafts.find_one({"draft_id": d["draft_id"]})
        assert row is not None, "draft must still exist"
        assert row["status"] == "discarded"
    finally:
        _sync.mention_response_drafts.delete_many({"mention_id": mid})
        _sync.brand_mentions.delete_one({"mention_id": mid})


# ── 8. Live HTTP: 404 on missing mention ──────────────────────────
def test_http_404_on_missing_mention():
    from services.response_drafts import reset_rate_limit_for_tests
    reset_rate_limit_for_tests()
    tok = _login("manager@aquaterra.com")
    r = requests.post(f"{API}/aeo/mentions/nonexistent_p6/response/draft",
                       headers={"Authorization": f"Bearer {tok}"},
                       json={"tone": "empathetic"}, timeout=10)
    assert r.status_code == 404, r.text
