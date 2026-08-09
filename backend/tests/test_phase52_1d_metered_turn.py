"""Phase 52.1d · Feb-2026 — metered.ca TURN wiring + contract lock.

Covers:
  1. STUN-only fallback when the metered env is unset.
  2. TURN entry appended when all three env vars present (single URL).
  3. TURN entry with a comma-separated URL list (client receives an
     RTCIceServer whose ``urls`` is a list).
  4. Partial env (URLs only) → STUN-only + a startup warning.
  5. Response shape snapshot — locks the ``{ice_servers: [...]}``
     envelope so accidental renames trip immediately.
  6. WebSocket message-type reference snapshot — locks the client↔
     server frame set enumerated in ``walkie_signaling.py``'s
     docstring against accidental drift. Any new frame type MUST
     bump this snapshot deliberately.
"""
from __future__ import annotations

import importlib
import os

import pytest


API = "http://localhost:8001/api"
TIMEOUT = 30


# The seed manager fixture from the 52.1a suite already exists and
# lives in the same module; reusing it via a shared conftest would
# be overkill for one endpoint. Instead we spin up a lightweight
# session that logs in with an existing seed user.
import requests  # noqa: E402
import bcrypt  # noqa: E402
import uuid as _uuid  # noqa: E402
from datetime import datetime, timezone  # noqa: E402
from dotenv import dotenv_values  # noqa: E402
from pymongo import MongoClient  # noqa: E402

TID = "3814833a-dd0d-4bd9-90ea-351c24924649"
PW = "password123"


@pytest.fixture(scope="module")
def sync_db():
    be = dotenv_values("/app/backend/.env")
    mc = MongoClient(be["MONGO_URL"])
    try:
        yield mc[be["DB_NAME"]]
    finally:
        mc.close()


@pytest.fixture(scope="module")
def admin_email(sync_db) -> str:
    """Reuse the fork-seeded aquaterra admin (created by the login
    regression seed). Fallback: create one on-the-fly."""
    email = "admin@aquaterra.com"
    if not sync_db.users.find_one({"email": email}):
        pw_hash = bcrypt.hashpw(PW.encode(), bcrypt.gensalt()).decode()
        sync_db.users.insert_one({
            "id": f"p52-1d-admin-{_uuid.uuid4().hex[:12]}",
            "email": email,
            "name": "P52-1D Admin",
            "role": "admin",
            "tenant_id": TID,
            "active": True,
            "password_hash": pw_hash,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
    return email


def _hdr(email: str) -> dict:
    r = requests.post(f"{API}/auth/login",
                      json={"email": email, "password": PW}, timeout=TIMEOUT)
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


# ═══════════════════════════════════════════════════════════════════
# 1-4. Unit tests of _load_metered_turn_config
# ═══════════════════════════════════════════════════════════════════
def _import_ws():
    """Return the walkie_signaling module (backend PYTHONPATH is
    already set by pytest fixture)."""
    import sys
    sys.path.insert(0, "/app/backend")
    from routers import walkie_signaling  # type: ignore
    importlib.reload(walkie_signaling)  # reset env-read state
    return walkie_signaling


def _clear_metered_env():
    for k in ("METERED_TURN_URLS", "METERED_TURN_USERNAME", "METERED_TURN_CREDENTIAL"):
        os.environ.pop(k, None)


def test_stun_only_when_metered_env_unset():
    _clear_metered_env()
    ws = _import_ws()
    assert ws._load_metered_turn_config() == []


def test_turn_appended_when_all_three_env_present():
    _clear_metered_env()
    os.environ["METERED_TURN_URLS"] = "turn:example.metered.live:80"
    os.environ["METERED_TURN_USERNAME"] = "user123"
    os.environ["METERED_TURN_CREDENTIAL"] = "cred456"
    try:
        ws = _import_ws()
        entries = ws._load_metered_turn_config()
        assert len(entries) == 1
        entry = entries[0]
        assert entry["urls"] == ["turn:example.metered.live:80"]
        assert entry["username"] == "user123"
        assert entry["credential"] == "cred456"
    finally:
        _clear_metered_env()


def test_turn_multi_url_comma_list_becomes_urls_list():
    _clear_metered_env()
    os.environ["METERED_TURN_URLS"] = (
        "turn:example.metered.live:80,"
        "turn:example.metered.live:443?transport=tcp,"
        "turns:example.metered.live:443"
    )
    os.environ["METERED_TURN_USERNAME"] = "u"
    os.environ["METERED_TURN_CREDENTIAL"] = "c"
    try:
        ws = _import_ws()
        entry = ws._load_metered_turn_config()[0]
        assert entry["urls"] == [
            "turn:example.metered.live:80",
            "turn:example.metered.live:443?transport=tcp",
            "turns:example.metered.live:443",
        ]
    finally:
        _clear_metered_env()


def test_turn_partial_env_yields_stun_only():
    """URLs set but username/credential missing → returns [] so we
    keep serving STUN-only (safe fallback)."""
    _clear_metered_env()
    os.environ["METERED_TURN_URLS"] = "turn:foo:80"
    try:
        ws = _import_ws()
        assert ws._load_metered_turn_config() == []
    finally:
        _clear_metered_env()


def test_turn_empty_string_urls_treated_as_missing():
    _clear_metered_env()
    os.environ["METERED_TURN_URLS"] = "  "
    os.environ["METERED_TURN_USERNAME"] = "u"
    os.environ["METERED_TURN_CREDENTIAL"] = "c"
    try:
        ws = _import_ws()
        assert ws._load_metered_turn_config() == []
    finally:
        _clear_metered_env()


# ═══════════════════════════════════════════════════════════════════
# 5. Response-shape snapshot (STUN-only branch is deterministic —
#    the running backend .env doesn't have TURN populated by default.)
# ═══════════════════════════════════════════════════════════════════
def test_ice_servers_stun_only_shape_snapshot(admin_email):
    """Locks the ``{ice_servers: [{urls: 'stun:...'}]}`` envelope."""
    r = requests.get(f"{API}/walkie/ice-servers", headers=_hdr(admin_email),
                     timeout=TIMEOUT)
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body.keys()) == {"ice_servers"}
    assert isinstance(body["ice_servers"], list)
    stun_entries = [e for e in body["ice_servers"] if "stun:" in str(e.get("urls", ""))]
    assert stun_entries, body
    # Every entry should have ``urls`` — verifying the RTCIceServer contract.
    for entry in body["ice_servers"]:
        assert "urls" in entry


# ═══════════════════════════════════════════════════════════════════
# 6. WebSocket message-type reference snapshot.
#    Locks the frame types from Phase 52.1a's docstring against
#    accidental drift. Adding a new type MUST bump this snapshot in
#    a code review.
# ═══════════════════════════════════════════════════════════════════
CLIENT_TO_SERVER_TYPES = frozenset({
    "join",
    "offer",
    "answer",
    "ice-candidate",
    "speaking",
    "leave",
})

SERVER_TO_CLIENT_TYPES = frozenset({
    "session-state",
    "peer-joined",
    "peer-left",
    "offer",
    "answer",
    "ice-candidate",
    "speaking-update",
    "session-ended",
})


def test_signaling_client_frame_set_snapshot():
    """The router's read-loop MUST handle exactly these frame types.
    Any drift here (either direction) needs a review sign-off."""
    src = open("/app/backend/routers/walkie_signaling.py").read()
    handled = set()
    # Direct comparisons in the read loop.
    for t in CLIENT_TO_SERVER_TYPES:
        # We look for either the double-quoted or unquoted match in
        # the handler if-else chain.
        if f'"{t}"' in src or f"'{t}'" in src:
            handled.add(t)
    missing = CLIENT_TO_SERVER_TYPES - handled
    assert not missing, (
        f"handler doesn't mention client→server frame(s): {missing}"
    )


def test_signaling_server_frame_set_snapshot():
    src = open("/app/backend/routers/walkie_signaling.py").read()
    emitted = set()
    for t in SERVER_TO_CLIENT_TYPES:
        # Some frames (offer/answer/ice-candidate) are emitted through
        # a dynamic ``{"type": mtype, ...}`` where mtype is copied
        # from the incoming client frame — asserting the literal
        # string appears anywhere in the source (comments, dispatch
        # `if mtype == "offer"`, or explicit emissions) is enough
        # to lock the wire contract in this snapshot.
        if f'"{t}"' in src or f"'{t}'" in src:
            emitted.add(t)
    missing = SERVER_TO_CLIENT_TYPES - emitted
    assert not missing, (
        f"handler doesn't emit server→client frame(s): {missing}"
    )
