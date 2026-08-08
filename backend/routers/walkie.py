"""Phase 51a · Feb 2026 — Walkie-Talkie router.

Async voice-clip messaging with role-scoped channels. Ephemeral (24h
retention enforced by a Mongo TTL index — see ``services/walkie/
channels.ensure_indexes``). Reuses the existing ``/api/files/`` upload
service for audio storage.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel

from config import db, logger
from utils import get_current_user
from services.walkie.channels import (
    BROADCAST_ROLES,
    PIN_ROLES,
    STAFF_ROLES,
    get_or_create_direct_channel,
    is_channel_member,
    list_visible_channels_for_user,
    resolve_recipients,
)
from services.walkie.push import fan_out_walkie_push as _fan_out_walkie_push

router = APIRouter(prefix="/walkie", tags=["walkie"])

# Server-side upload constraints.
MAX_AUDIO_BYTES = 2 * 1024 * 1024  # 2 MB — covers 30s at typical opus/aac bitrates
MAX_DURATION_MS = 30_000
MIN_DURATION_MS = 500
ALLOWED_AUDIO_MIMES = frozenset({
    "audio/webm",
    "audio/mp4",
    "audio/aac",
    "audio/mpeg",
    "audio/ogg",
})


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _require_staff(user: dict) -> None:
    role = (user.get("role") or "").lower()
    if role not in STAFF_ROLES:
        raise HTTPException(403, detail="walkie_staff_only")


class DirectChannelIn(BaseModel):
    user_id: str


class ListenedAck(BaseModel):
    ok: bool = True


class PinIn(BaseModel):
    message_id: str


def _require_pin_role(user: dict) -> None:
    role = (user.get("role") or "").lower()
    if role not in PIN_ROLES:
        raise HTTPException(403, detail="Only admins can pin messages")


# ═══════════════════════════════════════════════════════════════════
# GET /api/walkie/channels
# ═══════════════════════════════════════════════════════════════════
@router.get("/channels")
async def get_channels(user: dict = Depends(get_current_user)):
    _require_staff(user)
    channels = await list_visible_channels_for_user(user, db)
    return {"channels": channels}


# ═══════════════════════════════════════════════════════════════════
# POST /api/walkie/channels/direct
# ═══════════════════════════════════════════════════════════════════
@router.post("/channels/direct")
async def create_direct_channel(
    body: DirectChannelIn,
    user: dict = Depends(get_current_user),
):
    _require_staff(user)
    try:
        row = await get_or_create_direct_channel(user, body.user_id, db)
    except LookupError as e:
        raise HTTPException(404, detail=str(e))
    except ValueError as e:
        raise HTTPException(400, detail=str(e))
    return {"channel": row}


# ═══════════════════════════════════════════════════════════════════
# POST /api/walkie/messages
# ═══════════════════════════════════════════════════════════════════
@router.post("/messages")
async def post_message(
    channel_id: str = Form(...),
    duration_ms: int = Form(...),
    audio_file: UploadFile = File(...),
    waveform_peaks: Optional[str] = Form(None),  # JSON-encoded list
    user: dict = Depends(get_current_user),
):
    _require_staff(user)
    if duration_ms > MAX_DURATION_MS or duration_ms < MIN_DURATION_MS:
        raise HTTPException(400, detail={
            "code": "DURATION_OUT_OF_RANGE",
            "message": f"duration_ms must be between {MIN_DURATION_MS} and {MAX_DURATION_MS}",
        })
    content_type = (audio_file.content_type or "").lower()
    if content_type not in ALLOWED_AUDIO_MIMES:
        raise HTTPException(400, detail={
            "code": "UNSUPPORTED_AUDIO_MIME",
            "message": f"content-type {content_type!r} not allowed",
        })
    data = await audio_file.read()
    if len(data) > MAX_AUDIO_BYTES:
        raise HTTPException(400, detail={
            "code": "AUDIO_TOO_LARGE",
            "message": f"max audio size is {MAX_AUDIO_BYTES} bytes",
        })
    if not data:
        raise HTTPException(400, detail="empty_audio")

    channel = await db.walkie_channels.find_one({"id": channel_id}, {"_id": 0})
    if not channel:
        raise HTTPException(404, detail="channel_not_found")
    if not await is_channel_member(channel, user, db):
        raise HTTPException(403, detail="not_a_channel_member")
    # Phase 51b · Feb 2026 — broadcast gate. All-hands is
    # leadership-only; techs/dispatchers can still hit their own
    # department + directs.
    if channel.get("kind") == "all_hands":
        role = (user.get("role") or "").lower()
        if role not in BROADCAST_ROLES:
            raise HTTPException(403, detail="Only admins can broadcast to all-hands")

    # Persist audio via the existing file storage service (same one
    # /api/files/upload uses under the hood).
    from services.file_storage import put_object  # type: ignore
    tenant_id = user.get("tenant_id") or ""
    ext = {
        "audio/webm": "webm", "audio/mp4": "m4a", "audio/aac": "aac",
        "audio/mpeg": "mp3", "audio/ogg": "ogg",
    }.get(content_type, "bin")
    fname = f"{uuid.uuid4().hex}.{ext}"
    path = f"tenants/{tenant_id}/walkie/{fname}"
    file_id = uuid.uuid4().hex
    try:
        put_object(path, data, content_type=content_type)
    except Exception as e:
        raise HTTPException(503, detail=f"storage_error: {e}")
    # Register in files collection so /api/files/{id}/download works.
    await db.files.insert_one({
        "id": file_id,
        "tenant_id": tenant_id,
        "owner_user_id": user.get("id"),
        "path": path,
        "content_type": content_type,
        "size": len(data),
        "purpose": "walkie_audio",
        "created_at": _now().isoformat(),
    })

    peaks: list[float] = []
    if waveform_peaks:
        try:
            import json as _json
            parsed = _json.loads(waveform_peaks)
            if isinstance(parsed, list):
                peaks = [float(x) for x in parsed[:200]]
        except Exception:
            peaks = []

    created_at = _now()
    expires_at = created_at + timedelta(hours=24)
    msg_id = uuid.uuid4().hex
    msg = {
        "id": msg_id,
        "tenant_id": tenant_id,
        "channel_id": channel_id,
        "sender_user_id": user.get("id"),
        "audio_file_id": file_id,
        "duration_ms": int(duration_ms),
        "waveform_peaks": peaks,
        "created_at": created_at,
        "expires_at": expires_at,
    }
    await db.walkie_messages.insert_one(dict(msg))

    # Fan-out receipts (excludes sender).
    recipients = await resolve_recipients(channel, user.get("id") or "", db)
    if recipients:
        now_iso = created_at.isoformat()
        await db.walkie_receipts.insert_many([
            {
                "id": uuid.uuid4().hex,
                "tenant_id": tenant_id,
                "message_id": msg_id,
                "recipient_user_id": rid,
                "listened_at": None,
                "created_at": now_iso,
            }
            for rid in recipients
        ])

    # ── Phase 51c · Feb 2026 — Expo push fan-out ────────────────────
    # Best-effort push to every recipient with a registered device
    # token. Env-gated: real Expo API calls only when
    # ``WALKIE_PUSH_LIVE=1`` is set on the server. Default is
    # dry-run (log payload, no network) so CI + local dev stay quiet.
    if recipients:
        try:
            await _fan_out_walkie_push(
                recipients=recipients,
                channel=channel,
                sender=user,
                message_id=msg_id,
                duration_ms=int(duration_ms),
            )
        except Exception as e:  # pragma: no cover — push must never break send
            logger.warning(f"[walkie] push fan-out failed: {e}")

    # Return a JSON-safe copy (ISO strings for datetimes).
    return {"message": {
        **{k: v for k, v in msg.items() if k not in ("created_at", "expires_at")},
        "created_at": created_at.isoformat(),
        "expires_at": expires_at.isoformat(),
        "recipient_count": len(recipients),
    }}


# ═══════════════════════════════════════════════════════════════════
# GET /api/walkie/messages
# ═══════════════════════════════════════════════════════════════════
@router.get("/messages")
async def list_messages(
    channel_id: str = Query(...),
    since: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    user: dict = Depends(get_current_user),
):
    _require_staff(user)
    channel = await db.walkie_channels.find_one({"id": channel_id}, {"_id": 0})
    if not channel:
        raise HTTPException(404, detail="channel_not_found")
    if not await is_channel_member(channel, user, db):
        raise HTTPException(403, detail="not_a_channel_member")

    if since:
        try:
            since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
        except Exception:
            raise HTTPException(400, detail="since_must_be_iso8601")
    else:
        since_dt = _now() - timedelta(hours=24)

    tenant_id = user.get("tenant_id") or ""
    q = {
        "tenant_id": tenant_id,
        "channel_id": channel_id,
        "created_at": {"$gte": since_dt},
    }
    rows = await db.walkie_messages.find(q, {"_id": 0}).sort("created_at", -1).limit(limit).to_list(length=limit)
    # Phase 51.5 · Feb 2026 — Pinned messages ALWAYS surface at the
    # top regardless of ``since=`` window. We fetch the pinned row
    # separately (if it's not already in ``rows``) and inject it as
    # the first element with ``is_pinned: true``.
    pinned_id = channel.get("pinned_message_id")
    pinned_row = None
    if pinned_id:
        # Already in the recent window? Just tag it there. Otherwise
        # fetch it explicitly so long-lived pins survive filter drift.
        for r in rows:
            if r["id"] == pinned_id:
                pinned_row = r
                break
        if pinned_row is None:
            pinned_row = await db.walkie_messages.find_one({"id": pinned_id}, {"_id": 0})
    # Scope to caller-visible only (sender OR recipient).
    uid = user.get("id") or ""
    msg_ids = [r["id"] for r in rows]
    if pinned_row and pinned_row["id"] not in msg_ids:
        msg_ids.append(pinned_row["id"])
    receipts = await db.walkie_receipts.find(
        {"tenant_id": tenant_id, "recipient_user_id": uid, "message_id": {"$in": msg_ids}},
        {"_id": 0, "message_id": 1, "listened_at": 1},
    ).to_list(length=len(msg_ids))
    receipt_map = {r["message_id"]: r for r in receipts}

    def _serialize(r: dict) -> dict:
        item = dict(r)
        for k in ("created_at", "expires_at"):
            v = item.get(k)
            if hasattr(v, "isoformat"):
                item[k] = v.isoformat()
        item["audio_url"] = f"/api/files/{r['audio_file_id']}/download"
        rec = receipt_map.get(r["id"])
        item["listened_at"] = (rec.get("listened_at") if rec else None)
        item["is_pinned"] = (pinned_id is not None and r["id"] == pinned_id)
        return item

    out = []
    # Pinned first (if visible to caller).
    if pinned_row and (pinned_row["sender_user_id"] == uid or pinned_row["id"] in receipt_map):
        out.append(_serialize(pinned_row))
    for r in rows:
        if r["id"] == pinned_id:
            continue  # already emitted at the top
        if r["sender_user_id"] != uid and r["id"] not in receipt_map:
            continue  # not visible to this user
        out.append(_serialize(r))
    return {"messages": out}


# ═══════════════════════════════════════════════════════════════════
# POST /api/walkie/messages/{id}/listened
# ═══════════════════════════════════════════════════════════════════
@router.post("/messages/{message_id}/listened")
async def mark_listened(message_id: str, user: dict = Depends(get_current_user)):
    _require_staff(user)
    tenant_id = user.get("tenant_id") or ""
    uid = user.get("id") or ""
    res = await db.walkie_receipts.update_one(
        {
            "tenant_id": tenant_id,
            "message_id": message_id,
            "recipient_user_id": uid,
        },
        {"$set": {"listened_at": _now().isoformat()}},
    )
    if res.matched_count == 0:
        raise HTTPException(404, detail="receipt_not_found")
    return ListenedAck()


# ═══════════════════════════════════════════════════════════════════
# Phase 51.5 · Pin / unpin (admin-only)
# ═══════════════════════════════════════════════════════════════════
async def _restore_expiry(message_id: str) -> None:
    """When unpinning, recompute ``expires_at = created_at + 24h`` so
    Mongo's TTL index picks the row up on its next sweep. If the
    message is already older than 24h the TTL index will delete it
    on the very next tick — safer + clearer than us deleting
    directly here."""
    row = await db.walkie_messages.find_one({"id": message_id}, {"_id": 0, "created_at": 1})
    if not row or not row.get("created_at"):
        return
    created = row["created_at"]
    if isinstance(created, str):
        try:
            created = datetime.fromisoformat(created.replace("Z", "+00:00"))
        except Exception:
            return
    await db.walkie_messages.update_one(
        {"id": message_id},
        {"$set": {"expires_at": created + timedelta(hours=24)}},
    )


@router.post("/channels/{channel_id}/pin")
async def pin_message(
    channel_id: str,
    body: PinIn,
    user: dict = Depends(get_current_user),
):
    _require_staff(user)
    _require_pin_role(user)
    channel = await db.walkie_channels.find_one({"id": channel_id}, {"_id": 0})
    if not channel:
        raise HTTPException(404, detail="channel_not_found")
    if not await is_channel_member(channel, user, db):
        raise HTTPException(403, detail="not_a_channel_member")
    # Verify the target message exists AND belongs to this channel.
    msg = await db.walkie_messages.find_one(
        {"id": body.message_id, "channel_id": channel_id}, {"_id": 0}
    )
    if not msg:
        raise HTTPException(404, detail="message_not_found_in_channel")
    # Idempotent — pinning the already-pinned message is a no-op.
    prev = channel.get("pinned_message_id")
    if prev == body.message_id:
        return {"ok": True, "pinned_message_id": body.message_id, "unchanged": True}
    # Auto-unpin the previous pinned message: restore its expires_at.
    if prev:
        await _restore_expiry(prev)
    # Pin the new message: unset expires_at so TTL skips it.
    await db.walkie_messages.update_one(
        {"id": body.message_id},
        {"$unset": {"expires_at": ""}},
    )
    await db.walkie_channels.update_one(
        {"id": channel_id},
        {"$set": {"pinned_message_id": body.message_id, "updated_at": _now()}},
    )
    return {"ok": True, "pinned_message_id": body.message_id, "unchanged": False}


@router.delete("/channels/{channel_id}/pin")
async def unpin_message(channel_id: str, user: dict = Depends(get_current_user)):
    _require_staff(user)
    _require_pin_role(user)
    channel = await db.walkie_channels.find_one({"id": channel_id}, {"_id": 0})
    if not channel:
        raise HTTPException(404, detail="channel_not_found")
    if not await is_channel_member(channel, user, db):
        raise HTTPException(403, detail="not_a_channel_member")
    prev = channel.get("pinned_message_id")
    if not prev:
        return {"ok": True, "pinned_message_id": None, "unchanged": True}
    await _restore_expiry(prev)
    await db.walkie_channels.update_one(
        {"id": channel_id},
        {"$set": {"pinned_message_id": None, "updated_at": _now()}},
    )
    return {"ok": True, "pinned_message_id": None, "unchanged": False}

