"""Feb-2026 · Google Business Profile adapter tests.

GBP is a "conditional-green" adapter — the code path is fully
wired end-to-end (OAuth + refresh + localPosts), but publishing
requires per-instance OAuth completion. On a fresh preview env
(no OAuth done), ``check_credentials`` returns the specific
"not configured" or "not connected" pending gate.  These tests
exercise the three-state check + the publish path via
in-process monkeypatching of ``routers.gbp`` helpers (so we
don't hit Google in CI).
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest
from dotenv import load_dotenv
from pymongo import MongoClient
from tests._shared_mongo import (
    shared_client as _shared_client,
    shared_db as _shared_db,
)


load_dotenv(Path(__file__).resolve().parent.parent / ".env")

_sync = _shared_client()
_db = _shared_db()
def _run(coro):
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


@pytest.fixture
def clean_gbp():
    """Clear GBP settings before + after each test so preview
    env state (if any) doesn't leak into the tri-state assertions."""
    saved_config = _db.gbp_settings.find_one({"id": "config"})
    saved_tokens = _db.gbp_settings.find_one({"id": "tokens"})
    _db.gbp_settings.delete_many({"id": {"$in": ["config", "tokens"]}})
    yield
    # Restore whatever was there.
    _db.gbp_settings.delete_many({"id": {"$in": ["config", "tokens"]}})
    if saved_config:
        saved_config.pop("_id", None)
        _db.gbp_settings.insert_one(saved_config)
    if saved_tokens:
        saved_tokens.pop("_id", None)
        _db.gbp_settings.insert_one(saved_tokens)


def test_check_credentials_returns_not_configured_when_no_client_id(clean_gbp):
    from services.social.gbp_adapter import GBPAdapter
    r = _run(GBPAdapter().check_credentials("any-tenant"))
    assert r["ok"] is False
    assert "not configured" in r["detail"].lower()
    assert "Client ID" in r["detail"]


def test_check_credentials_returns_not_connected_when_client_id_but_no_tokens(clean_gbp):
    from services.social.gbp_adapter import GBPAdapter
    _db.gbp_settings.insert_one({
        "id": "config",
        "client_id": "test-client-id.apps.googleusercontent.com",
        "client_secret": "test-secret",  # nosec B106: test fixture
        "redirect_uri": "https://example.test/api/gbp/callback",
    })
    r = _run(GBPAdapter().check_credentials("any-tenant"))
    assert r["ok"] is False
    assert "not connected" in r["detail"].lower()
    assert "Connect Google" in r["detail"]


def test_check_credentials_returns_ok_when_fully_connected(clean_gbp):
    from services.social.gbp_adapter import GBPAdapter
    _db.gbp_settings.insert_one({
        "id": "config",
        "client_id": "test-client-id.apps.googleusercontent.com",
        "client_secret": "test-secret",  # nosec B106: test fixture
    })
    _db.gbp_settings.insert_one({
        "id": "tokens",
        "access_token": "test-access-token",   # nosec B106: fixture
        "refresh_token": "test-refresh-token", # nosec B106: fixture
        "expires_at": 9999999999.0,
    })
    r = _run(GBPAdapter().check_credentials("any-tenant"))
    assert r["ok"] is True
    assert "ready" in r["detail"].lower()


def test_publish_text_delegates_to_gbp_helpers(monkeypatch, clean_gbp):
    """Full unit test of the publish path — monkeypatch the
    three ``routers.gbp`` helpers so we don't hit Google."""
    from routers import gbp as gbp_router
    from services.social.gbp_adapter import GBPAdapter

    calls = {"token": 0, "location": 0, "post": None}

    async def _fake_token():
        calls["token"] += 1
        return "faketoken-XYZ"

    async def _fake_first_location(token):
        calls["location"] += 1
        assert token == "faketoken-XYZ"
        return "accounts/123/locations/456"

    async def _fake_do_publish_post(token, location, summary,
                                          cta_url, action_type="LEARN_MORE"):
        calls["post"] = {"token": token, "location": location,
                            "summary": summary, "cta_url": cta_url,
                            "action_type": action_type}
        return {
            "name": f"{location}/localPosts/pytestPost001",
            "state": "LIVE",
            "createTime": "2026-02-01T00:00:00Z",
            "updateTime": "2026-02-01T00:00:00Z",
            "searchUrl": "https://business.google.com/pytest001",
        }

    monkeypatch.setattr(gbp_router, "_access_token", _fake_token)
    monkeypatch.setattr(gbp_router, "_first_location", _fake_first_location)
    monkeypatch.setattr(gbp_router, "_do_publish_post", _fake_do_publish_post)

    res = _run(GBPAdapter().publish_text(
        "any-tenant", "Fresh pool service today across Vistancia.",
        link="https://poolandlandscapingofvistancia.com/services",
        cta_action="LEARN_MORE",
    ))
    assert res["platform_post_id"].endswith("/pytestPost001")
    assert res["url"].startswith("https://business.google.com/")
    assert res["status"] == "published"
    assert calls["token"] == 1
    assert calls["location"] == 1
    assert calls["post"]["summary"].startswith("Fresh pool service")
    assert calls["post"]["cta_url"].endswith("/services")


def test_publish_text_trims_to_1500_chars(monkeypatch, clean_gbp):
    """GBP caps localPost summaries at 1,500 chars.  Confirm the
    adapter trims deterministically before hitting Google."""
    from routers import gbp as gbp_router
    from services.social.gbp_adapter import GBPAdapter

    captured = {}

    async def _fake_token():
        return "faketoken"
    async def _fake_location(token):
        return "accounts/1/locations/1"
    async def _fake_post(token, location, summary, cta_url, action_type):
        captured["summary"] = summary
        return {"name": "n/localPosts/1", "state": "LIVE"}
    monkeypatch.setattr(gbp_router, "_access_token", _fake_token)
    monkeypatch.setattr(gbp_router, "_first_location", _fake_location)
    monkeypatch.setattr(gbp_router, "_do_publish_post", _fake_post)

    long_text = "A" * 2000
    _run(GBPAdapter().publish_text("t-any", long_text))
    assert len(captured["summary"]) <= 1500
    assert captured["summary"].endswith("…")


def test_supported_content_types_text_and_link():
    from services.social.gbp_adapter import GBPAdapter
    assert GBPAdapter().supported_content_types() == {"text", "link"}


def test_gbp_registered_in_platforms():
    from services.social import PLATFORMS
    assert "gbp" in PLATFORMS
    # Second position after wordpress — the live/code-live adapters
    # come first for debug ergonomics.
    keys = list(PLATFORMS.keys())
    assert keys.index("gbp") == 1
    assert keys[0] == "wordpress"
