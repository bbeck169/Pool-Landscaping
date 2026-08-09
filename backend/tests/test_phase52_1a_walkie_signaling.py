"""Phase 52.1a · Feb-2026 — Walkie live-streaming signaling backend tests.

Covers:

* Pydantic model round-trip (WalkieChannel with the two new fields,
  ``supports_live`` defaulting to True on legacy rows).
* ``POST /api/walkie/channels`` — live_only creation is super/admin
  only; tech + customer get 403.
* WebSocket signaling:
    - Join denied for callers who can't async-post to the channel (4403).
    - session-state carries the fresh session id + roster.
    - peer-joined / peer-left broadcast.
    - offer / answer / ice-candidate relay verbatim.
    - speaking broadcasts speaking-update to every OTHER peer.
    - No live-talk role gate (tech joins their own dept channel — the
      channel gate is the async-post gate, not a "live" gate).
* Session lifecycle in Mongo (row created on first join, participants
  updated on subsequent joins, ended_at set when last peer leaves).
* Stale-cleanup cron closes orphan sessions after server-restart.

Uses ``websockets.sync.client`` against the running backend so the
JWT secret in .env is honored end-to-end.
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient
from websockets.sync.client import connect as ws_connect
from websockets.exceptions import ConnectionClosed, InvalidStatus


API = "http://localhost:8001/api"
WS_BASE = "ws://localhost:8001/api"
TIMEOUT = 30


# ═══════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════
@pytest.fixture(scope="module")
def sync_db():
    be = dotenv_values("/app/backend/.env")
    mc = MongoClient(be["MONGO_URL"])
    try:
        yield mc[be["DB_NAME"]]
    finally:
        mc.close()


TID = "3814833a-dd0d-4bd9-90ea-351c24924649"  # aquaterra
PW = "password123"

# Seeded fixture users specific to this suite — created with role /
# department the tests need and torn down at the end of the module.
FIX_TAG = "phase52-1a-fixture"


def _make_user(sync_db, email: str, *, role: str, department: str | None = None) -> str:
    pw_hash = bcrypt.hashpw(PW.encode(), bcrypt.gensalt()).decode()
    uid = f"p52-1a-{uuid.uuid4().hex[:12]}"
    doc = {
        "id": uid,
        "email": email,
        "name": email.split("@")[0],
        "role": role,
        "tenant_id": TID,
        "active": True,
        "password_hash": pw_hash,
        "_p52_1a_tag": FIX_TAG,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    if department:
        doc["department"] = department
    sync_db.users.insert_one(doc)
    return uid


@pytest.fixture(scope="module", autouse=True)
def seeded_users(sync_db):
    # Clean any prior fixture rows.
    sync_db.users.delete_many({"_p52_1a_tag": FIX_TAG})
    sync_db.walkie_live_sessions.delete_many({"tenant_id": TID, "_p52_1a_tag": FIX_TAG})

    users = {
        "admin":     _make_user(sync_db, f"p52-1a-admin-{uuid.uuid4().hex[:6]}@aquaterra.com", role="admin"),
        "super":     _make_user(sync_db, f"p52-1a-super-{uuid.uuid4().hex[:6]}@aquaterra.com", role="super_admin"),
        "tech_pool": _make_user(sync_db, f"p52-1a-tp-{uuid.uuid4().hex[:6]}@aquaterra.com",    role="technician", department="pool"),
        "tech_pool2": _make_user(sync_db, f"p52-1a-tp2-{uuid.uuid4().hex[:6]}@aquaterra.com",  role="technician", department="pool"),
        "tech_land": _make_user(sync_db, f"p52-1a-tl-{uuid.uuid4().hex[:6]}@aquaterra.com",   role="technician", department="landscape"),
        "customer":  _make_user(sync_db, f"p52-1a-cust-{uuid.uuid4().hex[:6]}@aquaterra.com", role="customer"),
    }
    # Update email lookup helper.
    email_by = {k: sync_db.users.find_one({"id": v})["email"] for k, v in users.items()}
    yield {"ids": users, "emails": email_by}

    # Teardown — remove seeded fixture rows.
    sync_db.users.delete_many({"_p52_1a_tag": FIX_TAG})
    sync_db.walkie_live_sessions.delete_many({"tenant_id": TID})
    sync_db.walkie_channels.delete_many({"tenant_id": TID, "kind": "live_room"})


_TOKENS: dict = {}


def _login(email: str) -> str:
    if email in _TOKENS:
        return _TOKENS[email]
    r = requests.post(f"{API}/auth/login",
                      json={"email": email, "password": PW},
                      timeout=TIMEOUT)
    assert r.status_code == 200, f"login {email} → {r.status_code}: {r.text[:200]}"
    tok = r.json()["access_token"]
    _TOKENS[email] = tok
    return tok


def _hdr(email: str) -> dict:
    return {"Authorization": f"Bearer {_login(email)}"}


def _pool_department_channel(sync_db) -> dict:
    """The pool-department walkie channel for aquaterra."""
    row = sync_db.walkie_channels.find_one(
        {"tenant_id": TID, "kind": "department", "department": "pool"},
        {"_id": 0},
    )
    assert row, "pool channel missing — boot bootstrap failed"
    return row


def _land_department_channel(sync_db) -> dict:
    row = sync_db.walkie_channels.find_one(
        {"tenant_id": TID, "kind": "department", "department": "landscape"},
        {"_id": 0},
    )
    assert row, "landscape channel missing"
    return row


# ═══════════════════════════════════════════════════════════════════
# 1. Pydantic model round-trip
# ═══════════════════════════════════════════════════════════════════
def test_walkie_channel_model_defaults_supports_live_true():
    from models import WalkieChannel  # local import — backend PYTHONPATH

    legacy_doc = {
        "id": "ch_legacy",
        "tenant_id": TID,
        "kind": "all_hands",
        "member_user_ids": [],
        "created_at": "2026-01-01T00:00:00+00:00",
    }
    m = WalkieChannel.from_mongo(legacy_doc)
    assert m.supports_live is True
    assert m.live_only is False


def test_walkie_channel_model_round_trip_new_fields():
    from models import WalkieChannel

    m = WalkieChannel(
        id="ch1", tenant_id=TID, kind="live_room",
        supports_live=True, live_only=True,
    )
    dumped = m.model_dump()
    assert dumped["supports_live"] is True
    assert dumped["live_only"] is True
    # Re-parse to confirm serialisation is symmetric.
    m2 = WalkieChannel.model_validate(dumped)
    assert m2.live_only is True


def test_walkie_live_session_model():
    from models import WalkieLiveSession
    doc = {
        "id": "sess1", "channel_id": "ch1", "tenant_id": TID,
        "started_at": "2026-02-15T00:00:00+00:00",
        "started_by_user_id": "u1",
        "participant_user_ids": ["u1", "u2"],
    }
    m = WalkieLiveSession.from_mongo(doc)
    assert m.ended_at is None
    assert m.participant_user_ids == ["u1", "u2"]


# ═══════════════════════════════════════════════════════════════════
# 2. POST /api/walkie/channels — live_only creation gate
# ═══════════════════════════════════════════════════════════════════
def test_create_live_only_channel_admin_ok(seeded_users, sync_db):
    email = seeded_users["emails"]["admin"]
    r = requests.post(
        f"{API}/walkie/channels",
        headers=_hdr(email),
        json={"name": "Ops Live", "live_only": True},
        timeout=TIMEOUT,
    )
    assert r.status_code == 200, r.text
    ch = r.json()["channel"]
    assert ch["live_only"] is True
    assert ch["supports_live"] is True
    assert ch["tenant_id"] == TID


def test_create_live_only_channel_super_admin_ok(seeded_users):
    email = seeded_users["emails"]["super"]
    r = requests.post(
        f"{API}/walkie/channels",
        headers=_hdr(email),
        json={"name": "Exec Live", "live_only": True},
        timeout=TIMEOUT,
    )
    assert r.status_code == 200


def test_create_live_only_channel_tech_forbidden(seeded_users):
    email = seeded_users["emails"]["tech_pool"]
    r = requests.post(
        f"{API}/walkie/channels",
        headers=_hdr(email),
        json={"name": "no", "live_only": True},
        timeout=TIMEOUT,
    )
    assert r.status_code == 403


def test_create_live_only_channel_customer_forbidden(seeded_users):
    email = seeded_users["emails"]["customer"]
    r = requests.post(
        f"{API}/walkie/channels",
        headers=_hdr(email),
        json={"name": "no", "live_only": True},
        timeout=TIMEOUT,
    )
    assert r.status_code == 403


# ═══════════════════════════════════════════════════════════════════
# 3. WebSocket signaling
# ═══════════════════════════════════════════════════════════════════
def _ws_url(channel_id: str, email: str) -> str:
    return f"{WS_BASE}/ws/walkie/{channel_id}?token={_login(email)}"


def _drain(ws, want_type: str, timeout: float = 5.0) -> dict:
    """Read frames until one with ``type == want_type`` arrives."""
    import time as _t
    end = _t.monotonic() + timeout
    while _t.monotonic() < end:
        remaining = max(0.05, end - _t.monotonic())
        raw = ws.recv(timeout=remaining)
        try:
            frame = json.loads(raw)
        except Exception:
            continue
        if frame.get("type") == want_type:
            return frame
    raise AssertionError(f"never received frame type={want_type}")


def _expect_ws_reject(url: str) -> None:
    """FastAPI/Starlette closes a WebSocket BEFORE ``accept()`` by
    sending an HTTP 403 handshake response — the sync ``websockets``
    client surfaces that as ``InvalidStatus``. If the server ever
    accepts and then closes (post-accept flow) we'd see
    ``ConnectionClosed`` with the close code. Accept either shape."""
    try:
        with ws_connect(url, close_timeout=2) as ws:
            ws.recv(timeout=2)
        raise AssertionError("expected connection rejection, got success")
    except InvalidStatus as exc:
        assert exc.response.status_code == 403
    except ConnectionClosed as exc:
        # 4401 (bad token) or 4403 (denied) are the two intended codes.
        assert exc.rcvd is not None
        assert exc.rcvd.code in (4401, 4403)


def test_ws_join_denied_when_not_channel_member(seeded_users, sync_db):
    """Landscape tech tries to join the pool-department channel — rejected."""
    ch = _pool_department_channel(sync_db)
    email = seeded_users["emails"]["tech_land"]
    _expect_ws_reject(_ws_url(ch["id"], email))


def test_ws_join_denied_for_customer(seeded_users, sync_db):
    ch = _pool_department_channel(sync_db)
    email = seeded_users["emails"]["customer"]
    _expect_ws_reject(_ws_url(ch["id"], email))


def test_ws_join_creates_session_and_sends_state(seeded_users, sync_db):
    ch = _pool_department_channel(sync_db)
    email = seeded_users["emails"]["tech_pool"]
    with ws_connect(_ws_url(ch["id"], email), close_timeout=2) as ws:
        frame = _drain(ws, "session-state", timeout=5)
        assert frame["session_id"]
        assert seeded_users["ids"]["tech_pool"] in frame["roster"]

    # Session should be in Mongo, ended after WS closed.
    row = sync_db.walkie_live_sessions.find_one(
        {"channel_id": ch["id"]}, sort=[("started_at", -1)],
    )
    assert row is not None
    assert row["started_by_user_id"] == seeded_users["ids"]["tech_pool"]


def test_ws_peer_joined_broadcast_and_roster(seeded_users, sync_db):
    ch = _pool_department_channel(sync_db)
    e1 = seeded_users["emails"]["tech_pool"]
    e2 = seeded_users["emails"]["tech_pool2"]
    with ws_connect(_ws_url(ch["id"], e1), close_timeout=2) as ws1:
        _drain(ws1, "session-state")
        with ws_connect(_ws_url(ch["id"], e2), close_timeout=2) as ws2:
            state2 = _drain(ws2, "session-state")
            assert seeded_users["ids"]["tech_pool"] in state2["roster"]
            assert seeded_users["ids"]["tech_pool2"] in state2["roster"]
            joined = _drain(ws1, "peer-joined", timeout=5)
            assert joined["user_id"] == seeded_users["ids"]["tech_pool2"]

    # After both close, session should end.
    import time as _t; _t.sleep(0.4)
    latest = sync_db.walkie_live_sessions.find_one(
        {"channel_id": ch["id"]}, sort=[("started_at", -1)],
    )
    assert latest is not None
    assert latest["ended_at"] is not None
    # Both users appended to roster.
    assert set(latest["participant_user_ids"]) >= {
        seeded_users["ids"]["tech_pool"],
        seeded_users["ids"]["tech_pool2"],
    }


def test_ws_sdp_offer_answer_and_ice_relay(seeded_users, sync_db):
    ch = _pool_department_channel(sync_db)
    e1 = seeded_users["emails"]["tech_pool"]
    e2 = seeded_users["emails"]["tech_pool2"]
    uid1 = seeded_users["ids"]["tech_pool"]
    uid2 = seeded_users["ids"]["tech_pool2"]
    with ws_connect(_ws_url(ch["id"], e1), close_timeout=2) as ws1:
        _drain(ws1, "session-state")
        with ws_connect(_ws_url(ch["id"], e2), close_timeout=2) as ws2:
            _drain(ws2, "session-state")
            _drain(ws1, "peer-joined")

            # Peer 1 → offer to peer 2
            ws1.send(json.dumps({
                "type": "offer",
                "target_user_id": uid2,
                "sdp": "v=0\r\no=- 1 1 IN IP4 0.0.0.0\r\n(SDP-OFFER)",
            }))
            offer = _drain(ws2, "offer", timeout=5)
            assert offer["from_user_id"] == uid1
            assert "(SDP-OFFER)" in offer["sdp"]

            # Peer 2 → answer to peer 1
            ws2.send(json.dumps({
                "type": "answer",
                "target_user_id": uid1,
                "sdp": "(SDP-ANSWER)",
            }))
            answer = _drain(ws1, "answer", timeout=5)
            assert answer["from_user_id"] == uid2
            assert answer["sdp"] == "(SDP-ANSWER)"

            # Peer 1 → ICE candidate to peer 2
            ws1.send(json.dumps({
                "type": "ice-candidate",
                "target_user_id": uid2,
                "candidate": {"candidate": "candidate:foo 1 udp 2113937151 10.0.0.1 5555 typ host"},
            }))
            ice = _drain(ws2, "ice-candidate", timeout=5)
            assert ice["from_user_id"] == uid1
            assert ice["candidate"]["candidate"].startswith("candidate:foo")


def test_ws_speaking_update_broadcasts_to_others(seeded_users, sync_db):
    ch = _pool_department_channel(sync_db)
    e1 = seeded_users["emails"]["tech_pool"]
    e2 = seeded_users["emails"]["tech_pool2"]
    uid1 = seeded_users["ids"]["tech_pool"]
    with ws_connect(_ws_url(ch["id"], e1), close_timeout=2) as ws1:
        _drain(ws1, "session-state")
        with ws_connect(_ws_url(ch["id"], e2), close_timeout=2) as ws2:
            _drain(ws2, "session-state")
            _drain(ws1, "peer-joined")

            ws1.send(json.dumps({"type": "speaking", "is_speaking": True}))
            update = _drain(ws2, "speaking-update", timeout=5)
            assert update["user_id"] == uid1
            assert update["is_speaking"] is True


def test_ws_no_live_role_gate_for_department_member(seeded_users, sync_db):
    """Locked user decision #5: no admin gate for live. A pool tech
    joining the pool-department channel — where they CAN async-post
    — must NOT be blocked from live-talking."""
    ch = _pool_department_channel(sync_db)
    email = seeded_users["emails"]["tech_pool"]
    with ws_connect(_ws_url(ch["id"], email), close_timeout=2) as ws:
        frame = _drain(ws, "session-state", timeout=5)
        assert frame["session_id"]


# ═══════════════════════════════════════════════════════════════════
# 4. Stale-cleanup cron
# ═══════════════════════════════════════════════════════════════════
def test_stale_cleanup_closes_orphan_sessions_after_restart(sync_db):
    """Simulate a server restart: insert an ``ended_at=None`` row for
    a channel that has no in-process room. The cron closes it."""
    from motor.motor_asyncio import AsyncIOMotorClient
    from services.walkie.live_cleanup_cron import run_live_cleanup_once
    import asyncio

    be = dotenv_values("/app/backend/.env")
    tag_channel = f"p52-1a-orphan-{uuid.uuid4().hex[:8]}"
    sync_db.walkie_live_sessions.insert_one({
        "id": uuid.uuid4().hex,
        "tenant_id": TID,
        "channel_id": tag_channel,
        "started_by_user_id": "u_orphan",
        "started_at": (
            datetime.now(timezone.utc) - timedelta(hours=1)
        ).isoformat(),
        "ended_at": None,
        "participant_user_ids": ["u_orphan"],
        "recording_message_id": None,
    })

    async def _run() -> dict:
        mc = AsyncIOMotorClient(be["MONGO_URL"])
        try:
            _db = mc[be["DB_NAME"]]
            return await run_live_cleanup_once(_db, live_channel_ids=set())
        finally:
            mc.close()

    summary = asyncio.new_event_loop().run_until_complete(_run())
    assert summary["closed"] >= 1

    row = sync_db.walkie_live_sessions.find_one({"channel_id": tag_channel})
    assert row["ended_at"] is not None


def test_stale_cleanup_preserves_active_sessions(sync_db):
    """A row whose channel_id IS in the live set must be left alone."""
    from motor.motor_asyncio import AsyncIOMotorClient
    from services.walkie.live_cleanup_cron import run_live_cleanup_once
    import asyncio

    be = dotenv_values("/app/backend/.env")
    live_channel = f"p52-1a-live-{uuid.uuid4().hex[:8]}"
    sync_db.walkie_live_sessions.insert_one({
        "id": uuid.uuid4().hex,
        "tenant_id": TID,
        "channel_id": live_channel,
        "started_by_user_id": "u_live",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "ended_at": None,
        "participant_user_ids": ["u_live"],
        "recording_message_id": None,
    })

    async def _run() -> dict:
        mc = AsyncIOMotorClient(be["MONGO_URL"])
        try:
            _db = mc[be["DB_NAME"]]
            return await run_live_cleanup_once(_db, live_channel_ids={live_channel})
        finally:
            mc.close()

    asyncio.new_event_loop().run_until_complete(_run())
    row = sync_db.walkie_live_sessions.find_one({"channel_id": live_channel})
    assert row["ended_at"] is None

    # Cleanup this row so subsequent runs stay clean.
    sync_db.walkie_live_sessions.delete_one({"channel_id": live_channel})


# ═══════════════════════════════════════════════════════════════════
# 6. GET /api/walkie/ice-servers  (Phase 52.1b addition)
# ═══════════════════════════════════════════════════════════════════
def test_ice_servers_authed_user_ok(seeded_users):
    """Any authenticated user can fetch ICE server config."""
    email = seeded_users["emails"]["tech_pool"]
    r = requests.get(f"{API}/walkie/ice-servers", headers=_hdr(email), timeout=TIMEOUT)
    assert r.status_code == 200, r.text
    body = r.json()
    assert isinstance(body.get("ice_servers"), list)
    # Google STUN is the baseline entry in every response.
    stun = [e for e in body["ice_servers"] if "stun:" in (e.get("urls") or "")]
    assert stun, body


def test_ice_servers_unauthed_401(sync_db):
    r = requests.get(f"{API}/walkie/ice-servers", timeout=TIMEOUT)
    assert r.status_code in (401, 403)


def test_ice_servers_customer_ok(seeded_users):
    """Customer role has NO channel access but the endpoint gate is
    just ``get_current_user`` — same as any other authed lookup."""
    email = seeded_users["emails"]["customer"]
    r = requests.get(f"{API}/walkie/ice-servers", headers=_hdr(email), timeout=TIMEOUT)
    assert r.status_code == 200


# ═══════════════════════════════════════════════════════════════════
# 7. Bad token
# ═══════════════════════════════════════════════════════════════════
def test_ws_bad_token_closes_4401(sync_db):
    ch = _pool_department_channel(sync_db)
    url = f"{WS_BASE}/ws/walkie/{ch['id']}?token=obviously-not-a-jwt"
    _expect_ws_reject(url)
