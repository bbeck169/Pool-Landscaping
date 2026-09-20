"""Feb-2026 · Phase 25 — AI Photo/Voice → Repair Estimate pytest.

Covers:

* Photo endpoint returns the normalized schema (parts / labor_hours /
  concerns / confidence / raw_analysis) via TEST_LLM_MOCK.
* Voice endpoint returns ``voice_provider_disabled`` when
  ``OPENAI_API_KEY`` is unset — graceful degrade contract.
* Fuzzy pricebook match swaps AI-inferred cost for the tenant catalog
  price when the name is close enough.
* Rate limit fires on the 21st call within an hour.
* Techs are 403'd from both endpoints (pricing surface guardrail).
"""
from __future__ import annotations
import asyncio
import io
import os
import uuid
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient
from tests._shared_mongo import (
    shared_client as _shared_client,
    shared_db as _shared_db,
)


_BACKEND_ENV = Path(__file__).resolve().parents[1] / ".env"
_ENV = dotenv_values(_BACKEND_ENV)
_MONGO_URL = _ENV.get("MONGO_URL") or os.environ.get("MONGO_URL")
_DB_NAME = _ENV.get("DB_NAME") or os.environ.get("DB_NAME")
_sync = _shared_db()
def _run_async(coro):
    """Run an async coroutine on a fresh event loop, rebinding the
    Motor client to that loop so ``db.items`` calls don't hit a closed
    IOLoop between successive tests. Restores a usable default loop
    afterward so later tests that use the deprecated
    ``asyncio.get_event_loop()`` pattern continue to work."""
    from motor.motor_asyncio import AsyncIOMotorClient
    import config
    try:
        prev_loop = asyncio.get_event_loop()
    except RuntimeError:
        prev_loop = None
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        client = AsyncIOMotorClient(_MONGO_URL, io_loop=loop)
        prev_client = config.client
        prev_db = config.db
        config.client = client
        config.db = client[_DB_NAME]
        try:
            return loop.run_until_complete(coro)
        finally:
            config.client = prev_client
            config.db = prev_db
            client.close()
    finally:
        loop.close()
        try:
            asyncio.set_event_loop(prev_loop if prev_loop and not prev_loop.is_closed()
                                     else asyncio.new_event_loop())
        except Exception:
            asyncio.set_event_loop(asyncio.new_event_loop())

_REACT_ENV = Path(__file__).resolve().parents[2] / "frontend" / ".env"
_REACT = dotenv_values(_REACT_ENV) if _REACT_ENV.is_file() else {}
_PUBLIC_URL = _REACT.get("REACT_APP_BACKEND_URL") or os.environ.get("REACT_APP_BACKEND_URL")
API = os.environ.get("BACKEND_API_URL") or (
    (_PUBLIC_URL.rstrip("/") + "/api") if _PUBLIC_URL else "http://localhost:8001/api"
)


def _login(email: str, pw: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": pw},
                       timeout=15)
    r.raise_for_status()
    return r.json()["access_token"]


def _admin_headers():
    return {"Authorization": f"Bearer {_login('admin@aquaterra.com')}"}


def _tech_headers():
    return {"Authorization": f"Bearer {_login('mike@aquaterra.com')}"}


def _admin_tenant_id() -> str:
    return _sync.users.find_one(
        {"email": "admin@aquaterra.com"}, {"_id": 0, "tenant_id": 1})["tenant_id"]


@pytest.fixture
def _clean_generations():
    tid = _admin_tenant_id()
    _sync.ai_estimate_generations.delete_many(
        {"tenant_id": tid, "endpoint": {"$in": ["photo", "voice"]}})
    yield
    _sync.ai_estimate_generations.delete_many(
        {"tenant_id": tid, "endpoint": {"$in": ["photo", "voice"]}})


PNG_1x1 = bytes.fromhex(
    "89504E470D0A1A0A0000000D49484452000000010000000108060000001F15C489"
    "0000000A49444154789C6300010000000500010D0A2DB40000000049454E44AE426082"
)


def _post_photo(headers, body=PNG_1x1, filename="test.png",
                  content_type="image/png"):
    return requests.post(
        f"{API}/ai/estimate-from-photo",
        headers=headers,
        files={"file": (filename, body, content_type)},
        timeout=60,
    )


def _post_voice(headers, body=b"fake-audio-bytes-\x00\x01\x02", filename="memo.webm",
                  content_type="audio/webm"):
    return requests.post(
        f"{API}/ai/estimate-from-voice",
        headers=headers,
        files={"file": (filename, body, content_type)},
        timeout=60,
    )


# ─────────────────────────────────────────────────────────────────────
# Photo endpoint
# ─────────────────────────────────────────────────────────────────────
def test_photo_endpoint_returns_normalized_schema_when_mocked(_clean_generations):
    """TEST_LLM_MOCK=1 in-process only affects the pytest process, not
    the running uvicorn — so we can't force the API to mock. Instead we
    hit the service function directly here and hit the HTTP endpoint
    for schema + status shape only.
    """
    # 1. Service-level (deterministic mock via TEST_LLM_MOCK).
    from services.ai.estimate_from_media import estimate_from_photo
    os.environ["TEST_LLM_MOCK"] = "1"
    try:
        est = _run_async(estimate_from_photo(
            PNG_1x1, tenant_id=_admin_tenant_id(),
            context_hint="pump humming loudly"))
    finally:
        os.environ.pop("TEST_LLM_MOCK", None)
    assert isinstance(est.get("parts"), list)
    assert "labor_hours_estimated" in est
    assert "concerns" in est
    assert 0 <= est.get("confidence", 0) <= 100
    assert est.get("provider") == "claude"
    assert est.get("input_kind") == "photo"

    # 2. HTTP round-trip — we accept either a real Claude result OR a
    # provider-level failure surfaced as 200+error (graceful degrade).
    r = _post_photo(_admin_headers())
    assert r.status_code == 200, r.text
    data = r.json()
    assert "generation_id" in data
    assert data.get("handoff_url") == "/ops/repair-calculator"
    assert isinstance(data.get("parts"), list)


def test_photo_endpoint_blocks_tech():
    r = _post_photo(_tech_headers())
    assert r.status_code == 403


def test_photo_endpoint_rejects_wrong_mime():
    r = _post_photo(_admin_headers(),
                      body=b"not-an-image",
                      filename="foo.txt", content_type="text/plain")
    assert r.status_code == 415


def test_photo_endpoint_rejects_empty_upload():
    r = _post_photo(_admin_headers(), body=b"",
                      filename="empty.png", content_type="image/png")
    assert r.status_code == 422


def test_photo_endpoint_records_generation_row(_clean_generations):
    _post_photo(_admin_headers())
    tid = _admin_tenant_id()
    rows = list(_sync.ai_estimate_generations.find(
        {"tenant_id": tid, "endpoint": "photo"}))
    assert len(rows) >= 1
    row = rows[-1]
    assert row.get("byte_size") == len(PNG_1x1)
    assert row.get("filename") == "test.png"


# ─────────────────────────────────────────────────────────────────────
# Voice endpoint — graceful degrade (OPENAI_API_KEY unset)
# ─────────────────────────────────────────────────────────────────────
def test_voice_endpoint_reports_provider_disabled_when_key_missing(_clean_generations):
    if os.environ.get("OPENAI_API_KEY", "").strip():
        pytest.skip("OPENAI_API_KEY is set — voice endpoint is live in this env")
    r = _post_voice(_admin_headers())
    assert r.status_code == 200, r.text
    data = r.json()
    assert data.get("error") == "voice_provider_disabled"
    # Graceful shape — parts/labor still present so the UI can render.
    assert data.get("parts") == []
    assert data.get("labor_hours_estimated") == 0.0


def test_voice_endpoint_blocks_tech():
    r = _post_voice(_tech_headers())
    assert r.status_code == 403


# ─────────────────────────────────────────────────────────────────────
# Fuzzy pricebook match
# ─────────────────────────────────────────────────────────────────────
def test_fuzzy_match_swaps_ai_inferred_for_pricebook_price():
    """Insert a temp pricebook row, prime the mock queue with an AI
    guess whose name is close enough (> 0.8 Levenshtein/SequenceMatcher),
    and confirm the returned part carries ``source="pricebook_match"``
    with the catalog cost."""
    from services.ai.estimate_from_media import (
        estimate_from_photo, prime_test_mocks, clear_test_mocks,
    )
    tid = _admin_tenant_id()
    pb_id = f"TEST_PB_{uuid.uuid4().hex[:8]}"
    _sync.items.insert_one({
        "id": pb_id, "tenant_id": tid,
        "name": f"TEST_pump_seal_kit_{uuid.uuid4().hex[:6]}",
        "unit_price": 89.99, "cost": 45.0, "active": True,
    })
    try:
        os.environ["TEST_LLM_MOCK"] = "1"
        clear_test_mocks()
        pb_row = _sync.items.find_one({"id": pb_id}, {"_id": 0, "name": 1})
        # A close-but-not-identical AI guess.
        prime_test_mocks({
            "parts": [
                {"name": pb_row["name"] + "!!", "cost": 25.0, "confidence": 60}
            ],
            "labor_hours_estimated": 1.0,
            "concerns": [],
            "confidence": 70,
            "raw_analysis": "Pump seal appears leaking.",
        })
        est = _run_async(estimate_from_photo(PNG_1x1, tenant_id=tid))
        assert len(est["parts"]) == 1
        part = est["parts"][0]
        assert part["source"] == "pricebook_match"
        assert part["matched_pricebook_id"] == pb_id
        assert part["cost"] == 89.99
    finally:
        os.environ.pop("TEST_LLM_MOCK", None)
        clear_test_mocks()
        _sync.items.delete_one({"id": pb_id})


def test_fuzzy_match_leaves_ai_inferred_when_no_close_pricebook_hit():
    from services.ai.estimate_from_media import (
        estimate_from_photo, prime_test_mocks, clear_test_mocks,
    )
    tid = _admin_tenant_id()
    try:
        os.environ["TEST_LLM_MOCK"] = "1"
        clear_test_mocks()
        prime_test_mocks({
            "parts": [{
                "name": f"nonexistent-hyperbaric-widget-{uuid.uuid4().hex[:8]}",
                "cost": 17.75, "confidence": 40,
            }],
            "labor_hours_estimated": 0.5,
            "concerns": [],
            "confidence": 30,
            "raw_analysis": "Uncertain.",
        })
        est = _run_async(estimate_from_photo(PNG_1x1, tenant_id=tid))
        assert est["parts"][0]["source"] == "ai_inferred"
        assert est["parts"][0]["cost"] == 17.75
    finally:
        os.environ.pop("TEST_LLM_MOCK", None)
        clear_test_mocks()


# ─────────────────────────────────────────────────────────────────────
# Rate limit
# ─────────────────────────────────────────────────────────────────────
def test_rate_limit_fires_after_20_calls(_clean_generations):
    """Seed 20 recent generation rows, then confirm the 21st call is
    429'd. Uses the same tenant/user pair the admin token resolves to."""
    from datetime import datetime, timezone
    tid = _admin_tenant_id()
    admin_row = _sync.users.find_one({"email": "admin@aquaterra.com"},
                                        {"_id": 0, "id": 1})
    uid = admin_row["id"]
    now_iso_str = datetime.now(timezone.utc).isoformat()
    # Seed exactly 20 recent rows.
    _sync.ai_estimate_generations.insert_many([
        {"id": f"rl-{i}", "tenant_id": tid, "user_id": uid,
          "endpoint": "photo", "created_at": now_iso_str}
        for i in range(20)
    ])
    r = _post_photo(_admin_headers())
    assert r.status_code == 429, r.text
