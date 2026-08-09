"""Phase 52.1a · Feb-2026 — Walkie live-streaming signaling router.

WebRTC signaling ONLY. The backend never sees or relays audio bytes:
peers dial each other P2P (TURN-relayed via metered.ca in Phase 52.1d)
and the backend just brokers SDP offer/answer + ICE candidates. All
room state lives in an in-process ``dict[channel_id, LiveRoom]`` — no
Redis needed for the MVP. On server restart, orphaned sessions in
``walkie_live_sessions`` are closed out by
``services/walkie/live_cleanup_cron.py``.

Endpoint
--------
* ``WS /api/ws/walkie/{channel_id}?token=<jwt>`` — JWT is required as
  a query param (mirrors ``routers.realtime`` ``/ws/notifications``
  pattern used elsewhere in the codebase). No first-message
  handshake — accept the WS, decode the JWT, close 4401 on failure.

Channel access
--------------
Channel gate mirrors Phase 51a's async-post gate exactly — the caller
must satisfy ``is_channel_member(channel, user, db)`` AND (if the
channel is ``all_hands``) hold a role in ``BROADCAST_ROLES``. That is
the same permission surface a caller needs to POST an async voice
clip. Locked user decision #5: "no admin gate for live" — a tech
absolutely CAN join an all-hands live session, because a tech
CANNOT async-post to all-hands either (BROADCAST_ROLES gate). We are
mirroring, not adding, gates.

Wire message envelope
---------------------
Every JSON frame carries ``{type, ...}``. Client → server frames
never carry a sender identity — the backend stamps it from the
authenticated user. Server → client frames always carry the
originating peer's ``from_user_id`` so the client can route offers
to the right ``RTCPeerConnection``.

Client → Server
    join                 — no fields.  Creates or joins a
                             ``WalkieLiveSession`` row.
    offer                — ``{target_user_id, sdp}``
    answer               — ``{target_user_id, sdp}``
    ice-candidate        — ``{target_user_id, candidate}``
    speaking             — ``{is_speaking: bool}``
    leave                — no fields.  Removes the peer from the
                             room.  Last-out ends the session.

Server → Client
    session-state        — ``{session_id, roster: [user_ids]}``
    peer-joined          — ``{user_id}``
    peer-left            — ``{user_id}``
    offer                — ``{from_user_id, sdp}``
    answer               — ``{from_user_id, sdp}``
    ice-candidate        — ``{from_user_id, candidate}``
    speaking-update      — ``{user_id, is_speaking}``
    session-ended        — ``{session_id, reason}``

Auto-record hook
----------------
Session-end emits ``session-ended`` and calls
``services.walkie.live_events.on_session_ended`` (a no-op stub in
this slice; Phase 52.1b/c will implement the auto-record fan-out).
"""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

import jwt
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    WebSocket,
    WebSocketDisconnect,
)
from pydantic import BaseModel

from config import db, JWT_SECRET, JWT_ALGO
from services.walkie.channels import (
    BROADCAST_ROLES,
    STAFF_ROLES,
    is_channel_member,
)
from services.walkie.live_events import on_session_ended
from utils import get_current_user

logger = logging.getLogger("walkie.signaling")

router = APIRouter()


# ═══════════════════════════════════════════════════════════════════
# In-process room state
# ═══════════════════════════════════════════════════════════════════
class _Peer:
    """A single active WebSocket in a room."""

    __slots__ = ("user_id", "ws")

    def __init__(self, user_id: str, ws: WebSocket) -> None:
        self.user_id = user_id
        self.ws = ws


class LiveRoom:
    """In-process room for a single walkie channel.

    Holds the currently-joined peers and the Mongo session id so
    join/leave/broadcast are O(peers). Access is single-threaded (all
    calls run inside the same FastAPI event loop) so no lock is
    required to mutate ``peers``.
    """

    def __init__(self, channel_id: str, tenant_id: str, session_id: str) -> None:
        self.channel_id = channel_id
        self.tenant_id = tenant_id
        self.session_id = session_id
        self.peers: Dict[str, _Peer] = {}

    def roster(self) -> List[str]:
        return sorted(self.peers.keys())


# channel_id → LiveRoom.  Cleared on every server restart — the cron
# in ``services/walkie/live_cleanup_cron.py`` closes any Mongo rows
# left dangling after a restart.
ROOMS: Dict[str, LiveRoom] = {}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _open_session(channel_id: str, tenant_id: str, started_by_user_id: str) -> str:
    """Insert a new ``walkie_live_sessions`` row.  Returns its id."""
    sid = uuid.uuid4().hex
    await db.walkie_live_sessions.insert_one({
        "id": sid,
        "tenant_id": tenant_id,
        "channel_id": channel_id,
        "started_by_user_id": started_by_user_id,
        "started_at": _now_iso(),
        "ended_at": None,
        "participant_user_ids": [started_by_user_id],
        "recording_message_id": None,
    })
    return sid


async def _add_participant(session_id: str, user_id: str) -> None:
    await db.walkie_live_sessions.update_one(
        {"id": session_id},
        {"$addToSet": {"participant_user_ids": user_id}},
    )


async def _end_session(session_id: str, reason: str = "empty") -> None:
    """Set ``ended_at`` + emit the auto-record hook (no-op stub in
    this slice; Phase 52.1b/c wires the actual clip creation)."""
    ended = _now_iso()
    await db.walkie_live_sessions.update_one(
        {"id": session_id, "ended_at": None},
        {"$set": {"ended_at": ended}},
    )
    try:
        await on_session_ended(session_id=session_id, reason=reason)
    except Exception as exc:  # pragma: no cover — hook is best-effort
        logger.warning("[walkie.signaling] on_session_ended raised: %s", exc)


# ═══════════════════════════════════════════════════════════════════
# JWT decode helper (mirrors routers.realtime)
# ═══════════════════════════════════════════════════════════════════
def _decode_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
    except Exception:
        return None


async def _fetch_user(user_id: str) -> Optional[dict]:
    return await db.users.find_one({"id": user_id}, {"_id": 0})


async def _access_ok(user: dict, channel: dict) -> bool:
    """Mirrors async-post gate: channel-member + broadcast-role for
    all_hands. Any customer role is already blocked by
    ``is_channel_member``."""
    if not await is_channel_member(channel, user, db):
        return False
    if channel.get("kind") == "all_hands":
        role = (user.get("role") or "").lower()
        if role not in BROADCAST_ROLES:
            return False
    if channel.get("live_only") and channel.get("kind") not in ("direct",):
        # ``live_only`` channels are still gated by the same member
        # check above — the extra flag doesn't loosen anything, just
        # marks the channel as inaccessible for async posts on the
        # client side.
        pass
    if channel.get("supports_live") is False:
        return False
    return True


# ═══════════════════════════════════════════════════════════════════
# Broadcast helpers
# ═══════════════════════════════════════════════════════════════════
async def _send_json_safe(peer: _Peer, payload: Dict[str, Any]) -> bool:
    try:
        await peer.ws.send_json(payload)
        return True
    except Exception:
        return False


async def _broadcast(room: LiveRoom, payload: Dict[str, Any], *, except_user: Optional[str] = None) -> None:
    """Send payload to every peer in the room (optionally excluding
    the originator). Serialised so slow peers don't hold others."""
    for peer in list(room.peers.values()):
        if except_user is not None and peer.user_id == except_user:
            continue
        await _send_json_safe(peer, payload)


async def _relay_to(room: LiveRoom, target_user_id: str, payload: Dict[str, Any]) -> bool:
    peer = room.peers.get(target_user_id)
    if peer is None:
        return False
    return await _send_json_safe(peer, payload)


# ═══════════════════════════════════════════════════════════════════
# WebSocket endpoint
# ═══════════════════════════════════════════════════════════════════
@router.websocket("/ws/walkie/{channel_id}")
async def ws_walkie_signaling(
    ws: WebSocket,
    channel_id: str,
    token: str = Query(...),
):
    # ── 1. Auth ────────────────────────────────────────────────────
    payload = _decode_token(token)
    if not payload or not payload.get("sub"):
        await ws.close(code=4401)
        return
    user = await _fetch_user(payload["sub"])
    if not user:
        await ws.close(code=4401)
        return

    # ── 2. Channel access gate (mirrors async-post) ────────────────
    channel = await db.walkie_channels.find_one({"id": channel_id}, {"_id": 0})
    if not channel or channel.get("tenant_id") != (user.get("tenant_id") or ""):
        await ws.close(code=4404)
        return
    if not await _access_ok(user, channel):
        await ws.close(code=4403)
        return

    await ws.accept()

    # ── 3. Join / create room ──────────────────────────────────────
    tenant_id = user.get("tenant_id") or ""
    user_id = user.get("id") or ""
    room = ROOMS.get(channel_id)
    if room is None:
        # First peer in — open a Mongo session row and stash the room.
        sid = await _open_session(channel_id, tenant_id, user_id)
        room = LiveRoom(channel_id, tenant_id, sid)
        ROOMS[channel_id] = room
    else:
        await _add_participant(room.session_id, user_id)

    # If a stale entry with the same user_id lingers, replace it.
    prev = room.peers.pop(user_id, None)
    if prev is not None:
        try:
            await prev.ws.close(code=4000)
        except Exception:
            pass

    room.peers[user_id] = _Peer(user_id, ws)

    # 3a. Send initial roster to the new peer.
    await ws.send_json({
        "type": "session-state",
        "session_id": room.session_id,
        "roster": room.roster(),
    })
    # 3b. Announce the join to every OTHER peer.
    await _broadcast(room, {"type": "peer-joined", "user_id": user_id}, except_user=user_id)

    # ── 4. Read-loop ───────────────────────────────────────────────
    try:
        while True:
            frame = await ws.receive_json()
            mtype = (frame.get("type") or "").lower()

            if mtype == "leave":
                break

            if mtype in ("offer", "answer", "ice-candidate"):
                target = frame.get("target_user_id")
                if not target or target == user_id:
                    continue
                out: Dict[str, Any] = {"type": mtype, "from_user_id": user_id}
                if mtype == "offer" or mtype == "answer":
                    out["sdp"] = frame.get("sdp")
                else:
                    out["candidate"] = frame.get("candidate")
                await _relay_to(room, target, out)
                continue

            if mtype == "speaking":
                await _broadcast(
                    room,
                    {
                        "type": "speaking-update",
                        "user_id": user_id,
                        "is_speaking": bool(frame.get("is_speaking")),
                    },
                    except_user=user_id,
                )
                continue

            if mtype == "join":
                # Re-join is a no-op — the initial ``session-state``
                # already carried the roster. Tolerate it so clients
                # that always send an explicit ``join`` after connect
                # stay compatible.
                continue

            # Unknown frame — silently drop.
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # pragma: no cover — defensive
        logger.info("[walkie.signaling] read-loop error: %s", exc)
    finally:
        # ── 5. Departure + session-end ────────────────────────────
        room.peers.pop(user_id, None)
        try:
            await ws.close()
        except Exception:
            pass
        await _broadcast(room, {"type": "peer-left", "user_id": user_id})
        if not room.peers:
            # Last one out — end the Mongo session + fire the hook.
            sid = room.session_id
            ROOMS.pop(channel_id, None)
            await _end_session(sid, reason="empty")


# ═══════════════════════════════════════════════════════════════════
# Additional endpoint: POST /api/walkie/channels — create a
# ``live_only`` channel (super_admin + admin only).
# ═══════════════════════════════════════════════════════════════════
_LIVE_ONLY_ROLES = frozenset({"super_admin", "admin"})


class CreateChannelBody(BaseModel):
    name: Optional[str] = None
    live_only: bool = True
    member_user_ids: Optional[List[str]] = None


@router.post("/walkie/channels")
async def create_walkie_channel(
    body: CreateChannelBody,
    user: dict = Depends(get_current_user),
) -> Dict[str, Any]:
    role = (user.get("role") or "").lower()
    if role not in _LIVE_ONLY_ROLES:
        raise HTTPException(403, detail={"error": "live_only_creation_forbidden"})
    tenant_id = user.get("tenant_id") or ""
    if not tenant_id:
        raise HTTPException(400, detail={"error": "missing_tenant"})

    now = _now_iso()
    row = {
        "id": uuid.uuid4().hex,
        "tenant_id": tenant_id,
        "kind": "direct" if body.member_user_ids else "live_room",
        "department": None,
        "member_user_ids": list(body.member_user_ids or []),
        "name": body.name or "Live Room",
        "supports_live": True,
        "live_only": bool(body.live_only),
        "created_at": now,
        "updated_at": now,
    }
    await db.walkie_channels.insert_one(dict(row))
    return {"channel": row}


# ═══════════════════════════════════════════════════════════════════
# Index bootstrap (called from server.py at startup)
# ═══════════════════════════════════════════════════════════════════
async def ensure_live_session_indexes() -> None:
    """Idempotent — create the two indexes the live-session collection
    needs. Called from ``server.py``'s startup hook alongside the
    other walkie indexes."""
    try:
        await db.walkie_live_sessions.create_index(
            [("tenant_id", 1), ("channel_id", 1), ("started_at", -1)],
            name="walkie_live_tenant_channel_started_desc",
        )
        await db.walkie_live_sessions.create_index(
            [("tenant_id", 1), ("ended_at", 1)],
            name="walkie_live_tenant_ended",
        )
    except Exception as exc:  # pragma: no cover — index race on cold start
        logger.info("[walkie.signaling] index bootstrap: %s", exc)
