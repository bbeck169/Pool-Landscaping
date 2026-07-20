"""Internal Team Messaging — DMs, channels, threads, reactions, reads.

Reuses the existing ``routers.realtime.bus`` singleton for WebSocket
fan-out — clients already subscribed to ``/ws/notifications`` receive
chat events with ``type`` prefixed ``chat.*``. Attachments live in
Emergent Object Storage via ``services.object_storage``. Push
notifications enqueue into a local ``push_queue`` collection (send-side
is MOCKED — a real Expo Push wire is a small follow-up when device
tokens are populated).
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field

from config import db, logger
from utils import get_current_user, require_admin, new_id, now_iso
from routers.tenants import get_current_tenant
from routers.realtime import bus
from services import object_storage as store


router = APIRouter(tags=["Chat"])
MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024
MENTION_RE = re.compile(r"@([a-zA-Z0-9_.-]{2,64})")


# ─── Models ────────────────────────────────────────────────────────────

class ConversationIn(BaseModel):
    type: str = Field(..., description="'dm' | 'channel'")
    other_user_id: Optional[str] = None
    name: Optional[str] = None
    slug: Optional[str] = None
    description: Optional[str] = ""
    member_ids: Optional[List[str]] = None


class ConversationPatch(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None


class MembersPatch(BaseModel):
    add: List[str] = Field(default_factory=list)
    remove: List[str] = Field(default_factory=list)


class MessageIn(BaseModel):
    body_markdown: str = Field(..., max_length=8000)
    thread_root_id: Optional[str] = None
    attachment_ids: List[str] = Field(default_factory=list)


class MessagePatch(BaseModel):
    body_markdown: str = Field(..., max_length=8000)


class ReactionIn(BaseModel):
    emoji: str = Field(..., max_length=16)


class ReadIn(BaseModel):
    message_id: str


# ─── Helpers ───────────────────────────────────────────────────────────

def _dm_key(a: str, b: str) -> str:
    """Deterministic key for a 1:1 DM. Same for (a,b) and (b,a)."""
    lo, hi = sorted([a, b])
    return hashlib.sha1(f"{lo}::{hi}".encode()).hexdigest()


async def _load_conv(tenant_id: str, cid: str) -> Optional[Dict[str, Any]]:
    return await db.chat_conversations.find_one(
        {"id": cid, "tenant_id": tenant_id}, {"_id": 0})


def _is_member(conv: Dict[str, Any], user_id: str) -> bool:
    return user_id in (conv.get("member_ids") or [])


async def _resolve_mentions(tenant_id: str, body: str) -> List[str]:
    handles = list({m.lower() for m in MENTION_RE.findall(body or "")})
    if not handles:
        return []
    users = await db.users.find({
        "tenant_id": tenant_id,
        "username": {"$in": handles},
    }, {"id": 1, "_id": 0}).to_list(50)
    # Fallback: match by email prefix if no username field.
    if not users:
        users = await db.users.find({
            "tenant_id": tenant_id,
            "email": {"$regex": f"^({'|'.join(re.escape(h) for h in handles)})@", "$options": "i"},
        }, {"id": 1, "_id": 0}).to_list(50)
    return [u["id"] for u in users]


async def _hydrate_attachments(ids: List[str]) -> List[Dict[str, Any]]:
    if not ids:
        return []
    rows = await db.chat_attachments.find(
        {"id": {"$in": ids}}, {"_id": 0}).to_list(50)
    return rows


async def _enqueue_push(tenant_id: str, recipient_ids: List[str],
                          title: str, body: str,
                          data: Dict[str, Any]) -> int:
    """Insert one row per offline recipient into ``push_queue``.

    Real send is MOCKED — a follow-up ships the Expo Push HTTP call.
    Test suite asserts these rows are written.
    """
    if not recipient_ids:
        return 0
    now = now_iso()
    docs = []
    tokens = await db.push_tokens.find(
        {"tenant_id": tenant_id, "user_id": {"$in": recipient_ids}},
        {"_id": 0}).to_list(500)
    for t in tokens:
        docs.append({
            "id": new_id(), "tenant_id": tenant_id,
            "user_id": t["user_id"], "token": t.get("token"),
            "platform": t.get("platform"),
            "title": title, "body": body[:200],
            "data": data or {}, "status": "queued",
            "queued_at": now, "sent_at": None,
        })
    if docs:
        await db.push_queue.insert_many(docs)
    return len(docs)


async def _broadcast(members: List[str], event_type: str,
                        payload: Dict[str, Any]) -> None:
    for uid in members or []:
        await bus.broadcast(uid, {"type": event_type, "payload": payload})


async def _emit_chat_notifications(*, tenant_id: str,
                                       conv: Dict[str, Any],
                                       msg: Dict[str, Any],
                                       author: Dict[str, Any],
                                       mentions: List[str]) -> None:
    """Fan chat events into ``services/notifications`` so per-user
    preferences + Expo push + audit rows all flow through one path.

    Routing rules (Feb 2026 unified-notifications ship):
      * DM → find the non-author recipient(s). Emit ``chat_dm_to_admin``
        when the recipient's role is admin/super_admin, else
        ``chat_dm``. Both default push=ON for admins / techs.
      * Channel + ``mentions`` non-empty → emit
        ``chat_mention_in_channel`` per mentioned user.
      * Channel general → emit ``chat_message_in_channel`` to non-author
        members. Default push=OFF; members opt in via prefs.

    Every call is best-effort; failures are logged and never bubble.
    """
    from services.notifications import emit as _notif_emit
    author_name = author.get("name") or author.get("email") or "Teammate"
    author_uid = author.get("id")
    href = f"/chat?c={conv['id']}"
    body_preview = (msg.get("body_markdown") or "")[:200]
    recipients = [uid for uid in (conv.get("member_ids") or [])
                    if uid != author_uid]
    src = {"kind": "chat.message",
            "conversation_id": conv["id"],
            "message_id": msg["id"]}
    if conv.get("type") == "dm":
        # Resolve recipient roles in one round-trip.
        rows = await db.users.find(
            {"id": {"$in": recipients}},
            {"_id": 0, "id": 1, "role": 1}).to_list(20)
        admin_ids: List[str] = []
        other_ids: List[str] = []
        for r in rows:
            if (r.get("role") or "").lower() in ("admin", "super_admin"):
                admin_ids.append(r["id"])
            else:
                other_ids.append(r["id"])
        if admin_ids:
            await _notif_emit(admin_ids, "chat_dm_to_admin",
                                title=f"DM from {author_name}",
                                body=body_preview, source_ref=src,
                                href=href, tenant_id=tenant_id)
        if other_ids:
            await _notif_emit(other_ids, "chat_dm",
                                title=f"DM from {author_name}",
                                body=body_preview, source_ref=src,
                                href=href, tenant_id=tenant_id)
        return
    # Channel routing.
    if mentions:
        # Mentioned users MUST be conversation members and NOT the
        # author (author self-mention is a common pattern in previews).
        mention_targets = [uid for uid in mentions
                            if uid in recipients and uid != author_uid]
        if mention_targets:
            await _notif_emit(
                mention_targets, "chat_mention_in_channel",
                title=f"{author_name} mentioned you",
                body=body_preview, source_ref=src, href=href,
                tenant_id=tenant_id)
    # Broad channel message — default push OFF for everyone. In-app
    # still records (bell default=True).
    if recipients:
        await _notif_emit(
            recipients, "chat_message_in_channel",
            title=(conv.get("name") or "Team channel"),
            body=f"{author_name}: {body_preview}",
            source_ref=src, href=href, tenant_id=tenant_id)


async def _bump_convo(tenant_id: str, cid: str, preview: str) -> None:
    await db.chat_conversations.update_one(
        {"id": cid, "tenant_id": tenant_id},
        {"$set": {"last_message_at": now_iso(),
                   "last_message_preview": preview[:120]}})


def _clean(d: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not d:
        return d
    out = dict(d)
    out.pop("_id", None)
    return out


# ═════════════════════════════════════════════════════════════════════
# Conversations
# ═════════════════════════════════════════════════════════════════════

@router.get("/chat/conversations")
async def list_conversations(user: dict = Depends(get_current_user),
                                tenant: dict = Depends(get_current_tenant)):
    rows = await db.chat_conversations.find(
        {"tenant_id": tenant["id"],
          "member_ids": user["id"],
          "is_archived": {"$ne": True}}, {"_id": 0},
    ).sort("last_message_at", -1).to_list(200)
    # Include unread_count per convo.
    convo_ids = [r["id"] for r in rows]
    reads = {}
    async for rd in db.chat_reads.find(
            {"tenant_id": tenant["id"], "user_id": user["id"],
              "conversation_id": {"$in": convo_ids}}, {"_id": 0}):
        reads[rd["conversation_id"]] = rd.get("last_read_at") or ""
    for c in rows:
        cutoff = reads.get(c["id"]) or ""
        c["unread_count"] = await db.chat_messages.count_documents({
            "tenant_id": tenant["id"], "conversation_id": c["id"],
            "author_user_id": {"$ne": user["id"]},
            "created_at": {"$gt": cutoff},
            "deleted_at": None,
        })
    return {"count": len(rows), "conversations": rows}


@router.post("/chat/conversations", status_code=201)
async def create_conversation(body: ConversationIn,
                                  user: dict = Depends(get_current_user),
                                  tenant: dict = Depends(get_current_tenant)):
    now = now_iso()
    if body.type == "dm":
        if not body.other_user_id or body.other_user_id == user["id"]:
            raise HTTPException(422, "other_user_id required")
        other = await db.users.find_one(
            {"id": body.other_user_id, "tenant_id": tenant["id"]}, {"_id": 0})
        if not other:
            raise HTTPException(404, "other user not found")
        dm_key = _dm_key(user["id"], body.other_user_id)
        existing = await db.chat_conversations.find_one(
            {"tenant_id": tenant["id"], "type": "dm", "dm_key": dm_key},
            {"_id": 0})
        if existing:
            return existing
        doc = {
            "id": new_id(), "tenant_id": tenant["id"], "type": "dm",
            "dm_key": dm_key,
            "member_ids": sorted([user["id"], body.other_user_id]),
            "name": None, "slug": None, "description": "",
            "created_by": user["id"], "is_archived": False,
            "created_at": now, "last_message_at": now,
            "last_message_preview": "",
        }
        await db.chat_conversations.insert_one(doc)
        return _clean(doc)
    if body.type == "channel":
        tenant_settings = await db.tenants.find_one(
            {"id": tenant["id"]}, {"chat_channels_open_to_all": 1, "_id": 0})
        is_open = bool((tenant_settings or {})
                          .get("chat_channels_open_to_all", False))
        if not is_open and user.get("role") not in ("admin", "super_admin"):
            raise HTTPException(403, "channel creation restricted to admins")
        if not body.name:
            raise HTTPException(422, "channel name required")
        slug = (body.slug or re.sub(r"[^a-z0-9-]+", "-", body.name.lower())).strip("-")
        if await db.chat_conversations.find_one(
                {"tenant_id": tenant["id"], "type": "channel", "slug": slug},
                {"_id": 0}):
            raise HTTPException(409, "slug already taken")
        members = list({user["id"], *(body.member_ids or [])})
        doc = {
            "id": new_id(), "tenant_id": tenant["id"], "type": "channel",
            "name": body.name, "slug": slug,
            "description": body.description or "",
            "member_ids": members, "created_by": user["id"],
            "is_archived": False,
            "created_at": now, "last_message_at": now,
            "last_message_preview": "",
        }
        await db.chat_conversations.insert_one(doc)
        return _clean(doc)
    raise HTTPException(422, "type must be 'dm' or 'channel'")


@router.patch("/chat/conversations/{cid}")
async def patch_conversation(cid: str, body: ConversationPatch,
                                 user: dict = Depends(get_current_user),
                                 tenant: dict = Depends(get_current_tenant)):
    conv = await _load_conv(tenant["id"], cid)
    if not conv:
        raise HTTPException(404, "conversation not found")
    if conv["type"] != "channel":
        raise HTTPException(422, "only channels can be renamed")
    is_admin_or_creator = (user.get("role") in ("admin", "super_admin")
                              or conv["created_by"] == user["id"])
    if not is_admin_or_creator:
        raise HTTPException(403, "channel-admin only")
    updates = body.model_dump(exclude_none=True)
    updates["updated_at"] = now_iso()
    await db.chat_conversations.update_one(
        {"id": cid, "tenant_id": tenant["id"]}, {"$set": updates})
    return _clean(await _load_conv(tenant["id"], cid))


@router.post("/chat/conversations/{cid}/members")
async def patch_members(cid: str, body: MembersPatch,
                          user: dict = Depends(get_current_user),
                          tenant: dict = Depends(get_current_tenant)):
    conv = await _load_conv(tenant["id"], cid)
    if not conv:
        raise HTTPException(404, "conversation not found")
    if conv["type"] != "channel":
        raise HTTPException(422, "DM membership is fixed")
    if user.get("role") not in ("admin", "super_admin") \
            and conv["created_by"] != user["id"]:
        raise HTTPException(403, "channel-admin only")
    members = set(conv.get("member_ids") or [])
    members.update(body.add or [])
    for uid in body.remove or []:
        members.discard(uid)
    await db.chat_conversations.update_one(
        {"id": cid, "tenant_id": tenant["id"]},
        {"$set": {"member_ids": sorted(members),
                   "updated_at": now_iso()}})
    return _clean(await _load_conv(tenant["id"], cid))


@router.post("/chat/conversations/{cid}/archive")
async def archive_conversation(cid: str,
                                   user: dict = Depends(require_admin),
                                   tenant: dict = Depends(get_current_tenant)):
    conv = await _load_conv(tenant["id"], cid)
    if not conv:
        raise HTTPException(404, "conversation not found")
    await db.chat_conversations.update_one(
        {"id": cid, "tenant_id": tenant["id"]},
        {"$set": {"is_archived": True, "archived_at": now_iso()}})
    return {"ok": True, "id": cid}


# ═════════════════════════════════════════════════════════════════════
# Messages
# ═════════════════════════════════════════════════════════════════════

@router.get("/chat/conversations/{cid}/messages")
async def list_messages(cid: str,
                            user: dict = Depends(get_current_user),
                            tenant: dict = Depends(get_current_tenant),
                            before: Optional[str] = Query(None),
                            limit: int = Query(50, ge=1, le=200),
                            thread_root_id: Optional[str] = Query(None)):
    conv = await _load_conv(tenant["id"], cid)
    if not conv:
        raise HTTPException(404, "conversation not found")
    if not _is_member(conv, user["id"]) and user.get("role") not in ("admin", "super_admin"):
        raise HTTPException(403, "not a member")
    q: Dict[str, Any] = {"tenant_id": tenant["id"], "conversation_id": cid}
    if thread_root_id:
        q["thread_root_id"] = thread_root_id
    else:
        q["thread_root_id"] = None
    if before:
        q["created_at"] = {"$lt": before}
    rows = await db.chat_messages.find(q, {"_id": 0}) \
        .sort("created_at", -1).to_list(limit)
    # Hydrate attachments.
    all_att_ids = {aid for r in rows for aid in (r.get("attachment_ids") or [])}
    atts = {a["id"]: a for a in await _hydrate_attachments(list(all_att_ids))}
    for r in rows:
        r["attachments"] = [atts[a] for a in (r.get("attachment_ids") or [])
                             if a in atts]
    return {"count": len(rows), "messages": rows}


@router.post("/chat/conversations/{cid}/messages", status_code=201)
async def send_message(cid: str, body: MessageIn,
                          user: dict = Depends(get_current_user),
                          tenant: dict = Depends(get_current_tenant)):
    conv = await _load_conv(tenant["id"], cid)
    if not conv:
        raise HTTPException(404, "conversation not found")
    if not _is_member(conv, user["id"]):
        raise HTTPException(403, "not a member")
    mentions = await _resolve_mentions(tenant["id"], body.body_markdown)
    now = now_iso()
    doc = {
        "id": new_id(), "tenant_id": tenant["id"], "conversation_id": cid,
        "thread_root_id": body.thread_root_id,
        "author_user_id": user["id"],
        "body_markdown": body.body_markdown,
        "mentions": mentions,
        "attachment_ids": body.attachment_ids or [],
        "reactions": {},
        "edited_at": None, "deleted_at": None,
        "created_at": now,
    }
    await db.chat_messages.insert_one(doc)
    await _bump_convo(tenant["id"], cid, body.body_markdown)
    # Broadcast + push.
    payload = {**{k: v for k, v in doc.items() if k != "_id"},
                 "author_name": user.get("name") or user.get("email") or ""}
    await _broadcast(conv.get("member_ids") or [], "chat.message.new", payload)
    # Push to offline members (all non-author members receive; real
    # dedup requires WS presence tracking — MOCKED enqueue for now).
    offline = [uid for uid in (conv.get("member_ids") or [])
                if uid != user["id"]]
    await _enqueue_push(
        tenant["id"], offline,
        title=(conv.get("name") or user.get("name") or "New message"),
        body=body.body_markdown,
        data={"conversation_id": cid, "message_id": doc["id"]},
    )
    if mentions:
        await _broadcast(mentions, "chat.mention",
                           {"conversation_id": cid, "message_id": doc["id"],
                            "author_user_id": user["id"]})
    # ── Unified notifications: route to services/notifications so
    # per-user preferences + Expo push + email/sms channels honour the
    # single source of truth. This runs after the raw WS fan-out above
    # so real-time delivery is never blocked by prefs lookup latency.
    try:
        await _emit_chat_notifications(
            tenant_id=tenant["id"], conv=conv, msg=doc,
            author=user, mentions=mentions,
        )
    except Exception as _e:
        logger.warning(f"[chat] unified notify hook failed: {_e}")
    doc.pop("_id", None)
    return doc


@router.patch("/chat/messages/{mid}")
async def edit_message(mid: str, body: MessagePatch,
                          user: dict = Depends(get_current_user),
                          tenant: dict = Depends(get_current_tenant)):
    msg = await db.chat_messages.find_one(
        {"id": mid, "tenant_id": tenant["id"]}, {"_id": 0})
    if not msg:
        raise HTTPException(404, "message not found")
    if msg["author_user_id"] != user["id"]:
        raise HTTPException(403, "can only edit your own message")
    if msg.get("deleted_at"):
        raise HTTPException(409, "message is deleted")
    now = now_iso()
    await db.chat_messages.update_one(
        {"id": mid, "tenant_id": tenant["id"]},
        {"$set": {"body_markdown": body.body_markdown,
                   "edited_at": now,
                   "mentions": await _resolve_mentions(tenant["id"],
                                                          body.body_markdown)}})
    fresh = await db.chat_messages.find_one(
        {"id": mid, "tenant_id": tenant["id"]}, {"_id": 0})
    conv = await _load_conv(tenant["id"], msg["conversation_id"])
    await _broadcast(conv.get("member_ids") or [], "chat.message.updated", fresh)
    return fresh


@router.delete("/chat/messages/{mid}")
async def delete_message(mid: str,
                             user: dict = Depends(get_current_user),
                             tenant: dict = Depends(get_current_tenant)):
    msg = await db.chat_messages.find_one(
        {"id": mid, "tenant_id": tenant["id"]}, {"_id": 0})
    if not msg:
        raise HTTPException(404, "message not found")
    conv = await _load_conv(tenant["id"], msg["conversation_id"])
    is_admin = user.get("role") in ("admin", "super_admin")
    is_author = msg["author_user_id"] == user["id"]
    is_channel_creator = (conv or {}).get("created_by") == user["id"]
    if not (is_admin or is_author or is_channel_creator):
        raise HTTPException(403, "not allowed")
    now = now_iso()
    await db.chat_messages.update_one(
        {"id": mid, "tenant_id": tenant["id"]},
        {"$set": {"deleted_at": now, "body_markdown": "",
                   "attachment_ids": []}})
    await db.chat_audit_log.insert_one({
        "id": new_id(), "tenant_id": tenant["id"], "action": "message.deleted",
        "actor_user_id": user["id"], "message_id": mid,
        "created_at": now,
    })
    await _broadcast(conv.get("member_ids") or [],
                       "chat.message.deleted", {"id": mid})
    return {"ok": True}


# ═════════════════════════════════════════════════════════════════════
# Reactions / reads / typing / search / unread-count
# ═════════════════════════════════════════════════════════════════════

@router.post("/chat/messages/{mid}/reactions")
async def toggle_reaction(mid: str, body: ReactionIn,
                              user: dict = Depends(get_current_user),
                              tenant: dict = Depends(get_current_tenant)):
    msg = await db.chat_messages.find_one(
        {"id": mid, "tenant_id": tenant["id"]}, {"_id": 0})
    if not msg:
        raise HTTPException(404, "message not found")
    conv = await _load_conv(tenant["id"], msg["conversation_id"])
    if not _is_member(conv, user["id"]):
        raise HTTPException(403, "not a member")
    reactions = msg.get("reactions") or {}
    entry = reactions.get(body.emoji) or {"count": 0, "user_ids": []}
    if user["id"] in entry["user_ids"]:
        entry["user_ids"].remove(user["id"])
        entry["count"] = max(0, entry["count"] - 1)
    else:
        entry["user_ids"].append(user["id"])
        entry["count"] += 1
    if entry["count"] <= 0:
        reactions.pop(body.emoji, None)
    else:
        reactions[body.emoji] = entry
    await db.chat_messages.update_one(
        {"id": mid, "tenant_id": tenant["id"]},
        {"$set": {"reactions": reactions}})
    await _broadcast(conv.get("member_ids") or [],
                       "chat.reaction.updated",
                       {"message_id": mid, "reactions": reactions})
    return {"message_id": mid, "reactions": reactions}


@router.post("/chat/conversations/{cid}/read")
async def mark_read(cid: str, body: ReadIn,
                        user: dict = Depends(get_current_user),
                        tenant: dict = Depends(get_current_tenant)):
    conv = await _load_conv(tenant["id"], cid)
    if not conv:
        raise HTTPException(404, "conversation not found")
    if not _is_member(conv, user["id"]):
        raise HTTPException(403, "not a member")
    now = now_iso()
    await db.chat_reads.update_one(
        {"tenant_id": tenant["id"], "conversation_id": cid,
          "user_id": user["id"]},
        {"$set": {"last_read_message_id": body.message_id,
                   "last_read_at": now},
          "$setOnInsert": {"id": new_id()}},
        upsert=True)
    await _broadcast(conv.get("member_ids") or [], "chat.read.updated",
                       {"conversation_id": cid,
                        "user_id": user["id"],
                        "last_read_at": now})
    return {"ok": True, "last_read_at": now}


@router.post("/chat/conversations/{cid}/typing")
async def typing(cid: str,
                    user: dict = Depends(get_current_user),
                    tenant: dict = Depends(get_current_tenant)):
    conv = await _load_conv(tenant["id"], cid)
    if not conv:
        raise HTTPException(404, "conversation not found")
    if not _is_member(conv, user["id"]):
        raise HTTPException(403, "not a member")
    expires = (datetime.now(timezone.utc) + timedelta(seconds=10)).isoformat()
    await db.chat_typing.update_one(
        {"conversation_id": cid, "user_id": user["id"]},
        {"$set": {"expires_at": expires}}, upsert=True)
    await _broadcast(conv.get("member_ids") or [], "chat.typing",
                       {"conversation_id": cid,
                        "user_id": user["id"], "expires_at": expires})
    return {"ok": True}


@router.get("/chat/search")
async def search(user: dict = Depends(get_current_user),
                    tenant: dict = Depends(get_current_tenant),
                    q: str = Query(..., min_length=1),
                    conversation_id: Optional[str] = Query(None),
                    limit: int = Query(50, ge=1, le=200)):
    # Restrict to conversations the user is a member of.
    convo_q = {"tenant_id": tenant["id"], "member_ids": user["id"]}
    if conversation_id:
        convo_q["id"] = conversation_id
    convo_ids = [c["id"] async for c in db.chat_conversations.find(
        convo_q, {"id": 1, "_id": 0})]
    if not convo_ids:
        return {"count": 0, "hits": []}
    rows = await db.chat_messages.find({
        "tenant_id": tenant["id"],
        "conversation_id": {"$in": convo_ids},
        "deleted_at": None,
        "body_markdown": {"$regex": re.escape(q), "$options": "i"},
    }, {"_id": 0}).sort("created_at", -1).to_list(limit)
    return {"count": len(rows), "hits": rows}


@router.get("/chat/unread-count")
async def unread_count(user: dict = Depends(get_current_user),
                          tenant: dict = Depends(get_current_tenant)):
    convo_ids = [c["id"] async for c in db.chat_conversations.find(
        {"tenant_id": tenant["id"], "member_ids": user["id"],
          "is_archived": {"$ne": True}}, {"id": 1, "_id": 0})]
    if not convo_ids:
        return {"total": 0}
    reads = {r["conversation_id"]: r.get("last_read_at") or ""
              async for r in db.chat_reads.find(
                  {"tenant_id": tenant["id"], "user_id": user["id"]},
                  {"_id": 0})}
    total = 0
    for cid in convo_ids:
        cutoff = reads.get(cid, "")
        total += await db.chat_messages.count_documents({
            "tenant_id": tenant["id"], "conversation_id": cid,
            "author_user_id": {"$ne": user["id"]},
            "created_at": {"$gt": cutoff},
            "deleted_at": None,
        })
    return {"total": total}


# ═════════════════════════════════════════════════════════════════════
# Attachments
# ═════════════════════════════════════════════════════════════════════

@router.post("/chat/attachments/upload", status_code=201)
async def upload_attachment(file: UploadFile = File(...),
                              user: dict = Depends(get_current_user),
                              tenant: dict = Depends(get_current_tenant)):
    data = await file.read()
    if len(data) > MAX_ATTACHMENT_BYTES:
        raise HTTPException(413, f"attachment > {MAX_ATTACHMENT_BYTES // 1024 // 1024} MB")
    att_id = new_id()
    path = store.build_path(tenant["id"], "chat", att_id, file.filename or "file")
    try:
        result = store.put_object(path, data,
                                     file.content_type or "application/octet-stream")
        storage_url = result.get("public_url") or result.get("url") or path
    except Exception as e:
        logger.warning(f"[chat] object storage put failed: {e} — falling back to inline")
        storage_url = f"local://{path}"
    doc = {
        "id": att_id, "tenant_id": tenant["id"],
        "type": ("image" if (file.content_type or "").startswith("image/")
                   else "file"),
        "name": file.filename or "file",
        "size_bytes": len(data),
        "mime": file.content_type or "application/octet-stream",
        "storage_url": storage_url,
        "storage_path": path,
        "uploaded_by": user["id"],
        "created_at": now_iso(),
    }
    await db.chat_attachments.insert_one(doc)
    doc.pop("_id", None)
    return doc


# ═════════════════════════════════════════════════════════════════════
# Push tokens (register)
# ═════════════════════════════════════════════════════════════════════

class PushTokenIn(BaseModel):
    token: str
    platform: str = Field(..., description="'ios' | 'android' | 'web'")


@router.post("/chat/push-tokens", status_code=201)
async def register_push_token(body: PushTokenIn,
                                  user: dict = Depends(get_current_user),
                                  tenant: dict = Depends(get_current_tenant)):
    await db.push_tokens.update_one(
        {"tenant_id": tenant["id"], "user_id": user["id"],
          "token": body.token},
        {"$set": {"platform": body.platform, "updated_at": now_iso()},
          "$setOnInsert": {"id": new_id(), "created_at": now_iso()}},
        upsert=True)
    return {"ok": True}


# ═════════════════════════════════════════════════════════════════════
# Retention (called by scheduler / test)
# ═════════════════════════════════════════════════════════════════════

async def apply_retention(tenant_id: str) -> int:
    """Soft-delete messages older than tenant.chat_retention_days.
    Returns count deleted. Invoked by APScheduler nightly + tests."""
    t = await db.tenants.find_one({"id": tenant_id},
                                     {"chat_retention_days": 1, "_id": 0})
    days = (t or {}).get("chat_retention_days")
    if not days:
        return 0
    cutoff = (datetime.now(timezone.utc) - timedelta(days=int(days))).isoformat()
    r = await db.chat_messages.update_many(
        {"tenant_id": tenant_id, "deleted_at": None,
          "created_at": {"$lt": cutoff}},
        {"$set": {"deleted_at": now_iso(), "body_markdown": "",
                   "attachment_ids": []}})
    return r.modified_count


@router.post("/chat/_ops/apply-retention")
async def ops_apply_retention(user: dict = Depends(require_admin),
                                  tenant: dict = Depends(get_current_tenant)):
    n = await apply_retention(tenant["id"])
    return {"deleted": n}
