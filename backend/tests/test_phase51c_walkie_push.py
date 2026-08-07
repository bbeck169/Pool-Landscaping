"""Phase 51c · Feb 2026 — Walkie push fan-out tests.

Isolated from the main Phase 51a suite so we can stub
``fan_out_walkie_push`` at import time and toggle
``WALKIE_PUSH_LIVE`` / ``EXPO_PUSH_ACCESS_TOKEN`` per test without
touching the live-server flow used by the other tests.

Every test exercises the helper directly (no HTTP hop) — the helper
is what ``routers/walkie.py`` calls after receipts have been
fanned-out.
"""
from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from dotenv import dotenv_values
from pymongo import MongoClient

from services.walkie import push as walkie_push


TID = "3814833a-dd0d-4bd9-90ea-351c24924649"  # aquaterra


@pytest.fixture(scope="module")
def sync_db():
    be = dotenv_values("/app/backend/.env")
    mc = MongoClient(be["MONGO_URL"])
    try:
        yield mc[be["DB_NAME"]]
    finally:
        mc.close()


@pytest.fixture
def seeded_tokens(sync_db):
    """Register two throw-away mobile push tokens against two staff users."""
    admin = sync_db.users.find_one({"email": "admin@aquaterra.com"}, {"_id": 0, "id": 1})
    tech = sync_db.users.find_one({"email": "mike@aquaterra.com"}, {"_id": 0, "id": 1})
    assert admin and tech
    token_admin = f"ExponentPushToken[{uuid.uuid4().hex}]"
    token_tech = f"ExponentPushToken[{uuid.uuid4().hex}]"
    sync_db.mobile_tokens.insert_many([
        {"id": uuid.uuid4().hex, "user_id": admin["id"], "token": token_admin, "platform": "ios",
         "created_at": "2026-02-07T00:00:00Z", "last_seen": "2026-02-07T00:00:00Z"},
        {"id": uuid.uuid4().hex, "user_id": tech["id"], "token": token_tech, "platform": "android",
         "created_at": "2026-02-07T00:00:00Z", "last_seen": "2026-02-07T00:00:00Z"},
    ])
    yield {"admin_uid": admin["id"], "tech_uid": tech["id"], "admin_token": token_admin, "tech_token": token_tech}
    sync_db.mobile_tokens.delete_many({"token": {"$in": [token_admin, token_tech]}})


CHANNEL_ALL_HANDS = {"id": "ch_ah_test", "kind": "all_hands", "tenant_id": TID}
CHANNEL_POOL = {"id": "ch_pool_test", "kind": "department", "department": "pool", "tenant_id": TID}
SENDER = {"id": "u_sender", "name": "Alice Admin", "email": "alice@ex.com"}


def _run(coro):
    """Run one coroutine on a fresh loop — keeps this file isolated
    from the Motor loop rebinds in the conftest. We MUST also
    rebind Motor's own ``_io_loop`` to this fresh loop for the
    duration of the coro (Phase 41.1d conftest pins Motor to the
    main-thread loop, which isn't the one this helper runs on), and
    restore it afterwards so later tests in the batch — which use
    the ``requests``-against-uvicorn pattern — aren't affected."""
    from config import client as _motor_client
    prev = getattr(_motor_client, "_io_loop", None)
    loop = asyncio.new_event_loop()
    _motor_client._io_loop = loop
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()
        _motor_client._io_loop = prev


def test_dry_run_when_flag_off(monkeypatch, seeded_tokens):
    monkeypatch.delenv("WALKIE_PUSH_LIVE", raising=False)
    monkeypatch.setenv("EXPO_PUSH_ACCESS_TOKEN", "fake-key")
    res = _run(walkie_push.fan_out_walkie_push(
        recipients=[seeded_tokens["admin_uid"], seeded_tokens["tech_uid"]],
        channel=CHANNEL_ALL_HANDS,
        sender=SENDER,
        message_id="msg_1",
        duration_ms=3400,
    ))
    assert res["mode"] == "dry_run"
    assert res["reason"] == "flag-off"
    assert res["tokens"] == 2
    assert res["title"].startswith("Alice Admin")
    assert "All-Hands" in res["title"]
    assert "3s" in res["body"] or "4s" in res["body"]


def test_dry_run_when_expo_token_missing(monkeypatch, seeded_tokens):
    monkeypatch.setenv("WALKIE_PUSH_LIVE", "1")
    monkeypatch.delenv("EXPO_PUSH_ACCESS_TOKEN", raising=False)
    res = _run(walkie_push.fan_out_walkie_push(
        recipients=[seeded_tokens["admin_uid"]],
        channel=CHANNEL_POOL,
        sender=SENDER,
        message_id="msg_2",
        duration_ms=2000,
    ))
    assert res["mode"] == "dry_run"
    assert res["reason"] == "expo-token-not-configured"
    assert "Pool Team" in res["title"]


def test_dry_run_recipients_with_no_tokens(monkeypatch, sync_db):
    monkeypatch.setenv("WALKIE_PUSH_LIVE", "1")
    monkeypatch.setenv("EXPO_PUSH_ACCESS_TOKEN", "fake-key")
    # A user id that owns zero mobile_tokens rows.
    unknown_uid = f"nobody_{uuid.uuid4().hex}"
    res = _run(walkie_push.fan_out_walkie_push(
        recipients=[unknown_uid],
        channel=CHANNEL_ALL_HANDS,
        sender=SENDER,
        message_id="msg_3",
        duration_ms=1500,
    ))
    assert res["mode"] == "dry_run"
    assert res["reason"] == "no-tokens"
    assert res["tokens"] == 0


def test_skipped_when_no_recipients(monkeypatch):
    monkeypatch.setenv("WALKIE_PUSH_LIVE", "1")
    monkeypatch.setenv("EXPO_PUSH_ACCESS_TOKEN", "fake-key")
    res = _run(walkie_push.fan_out_walkie_push(
        recipients=[],
        channel=CHANNEL_ALL_HANDS,
        sender=SENDER,
        message_id="msg_4",
        duration_ms=2000,
    ))
    assert res["mode"] == "skipped_no_recipients"


def test_live_mode_calls_expo_exactly_once_per_batch(monkeypatch, seeded_tokens):
    """When ``WALKIE_PUSH_LIVE=1`` and the Expo access token is set,
    the helper makes exactly one POST to the Expo push endpoint
    with a JSON array containing one message per registered token."""
    monkeypatch.setenv("WALKIE_PUSH_LIVE", "1")
    monkeypatch.setenv("EXPO_PUSH_ACCESS_TOKEN", "fake-key")

    class FakeResponse:
        status_code = 200

    fake_post = AsyncMock(return_value=FakeResponse())

    class FakeClient:
        def __init__(self, *a, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, *a, **kw): return await fake_post(*a, **kw)

    with patch.object(walkie_push, "httpx") as mock_httpx:
        mock_httpx.AsyncClient = FakeClient
        res = _run(walkie_push.fan_out_walkie_push(
            recipients=[seeded_tokens["admin_uid"], seeded_tokens["tech_uid"]],
            channel=CHANNEL_ALL_HANDS,
            sender=SENDER,
            message_id="msg_5",
            duration_ms=5000,
        ))

    assert res["mode"] == "live"
    assert res["tokens"] == 2
    assert res["status"] == 200
    # Exactly one HTTP call, one payload, two messages inside.
    assert fake_post.call_count == 1
    _args, kwargs = fake_post.call_args
    payload = kwargs.get("json") or (fake_post.call_args.args[1] if len(fake_post.call_args.args) > 1 else None)
    assert isinstance(payload, list)
    assert len(payload) == 2
    tokens_in_payload = sorted(m["to"] for m in payload)
    assert tokens_in_payload == sorted([seeded_tokens["admin_token"], seeded_tokens["tech_token"]])
    for m in payload:
        assert m["data"]["type"] == "walkie"
        assert m["data"]["message_id"] == "msg_5"
        assert m["data"]["channel_id"] == CHANNEL_ALL_HANDS["id"]
        assert m["title"].startswith("Alice Admin")
        assert "clip" in m["body"]
