"""Phase B2 · Feb 2026 — Portal chat threads with F0 attachment support.

Extends the legacy `messages` (single-thread AI-relay) with a new
`portal_chats` + `portal_chat_messages` schema for multi-topic support.

- Customers create threads and post messages against them.
- Admins list all threads in the tenant + reply.
- Techs are blocked (403).
- Real-time via `bus.broadcast(user_id, {type: "portal_chat_message"})`.

Phase B2 (Feb 2026) — attachment_ids: messages can now carry a list
of F0 file ids. Ownership is enforced at post-time: the requesting
customer may only attach files where one of the following is true:
  • file.linked_entity_type == "customer" AND linked_entity_id == customer_id
  • file.linked_entity_type == "job" AND linked_entity_id ∈ customer's jobs
  • file.uploaded_by_user_id == user_id   (defensive fallback)
Otherwise → 403 ``not_your_attachment`` and the message is NOT persisted.

On GET, ``attachment_ids`` are hydrated to
``attachments: [{id, filename, mime, size, signed_url}]`` using
``services.chat_attachment_hydration.hydrate_message_attachments``
so TeamChat + PortalChat share the same reader path.
"""
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from config import db, logger
from utils import now_iso, new_id, get_current_user
from routers.tenants import get_current_tenant
from services.chat_attachment_hydration import (
    hydrate_message_attachments,
)

router = APIRouter()


def _require_customer(user: dict) -> str:
    if user.get("role") != "customer" or not user.get("customer_id"):
        raise HTTPException(403, "Customers only")
    return user["customer_id"]


def _require_customer_or_admin(user: dict):
    if user.get("role") == "tech":
        raise HTTPException(403, "Not allowed")
    if user.get("role") not in ("customer", "admin", "super_admin"):
        raise HTTPException(403, "Not allowed")


class ChatCreateIn(BaseModel):
    subject: Optional[str] = None
    first_message: Optional[str] = None
    attachment_ids: Optional[List[str]] = None


class MessagePostIn(BaseModel):
    body: str = ""
    attachment_ids: Optional[List[str]] = None
    # ``attachments`` kept as a legacy alias so older callers still work.
    attachments: Optional[List[str]] = None


async def _customer_owned_job_ids(customer_id: str, tenant_id: str) -> set:
    """Return the set of job ids owned by ``customer_id`` in ``tenant_id``.
    Best-effort; empty set on failure."""
    try:
        rows = await db.jobs.find(
            {"customer_id": customer_id, "tenant_id": tenant_id},
            {"_id": 0, "id": 1},
        ).to_list(2000)
        return {r["id"] for r in rows if r.get("id")}
    except Exception:                                                # noqa: BLE001
        return set()


async def _verify_customer_attachment_ownership(
    ids: List[str], tenant_id: str, customer_id: str, user_id: str,
) -> None:
    """Raise 403 ``not_your_attachment`` if ANY id fails ownership.

    Ownership rules (any one is sufficient):
      • linked_entity_type=="customer" AND linked_entity_id==customer_id
      • linked_entity_type=="job"      AND linked_entity_id ∈ customer's jobs
      • uploaded_by_user_id == user_id (defensive fallback)
    Tenant scope is also enforced.
    """
    if not ids:
        return
    owned_jobs = await _customer_owned_job_ids(customer_id, tenant_id)
    for fid in ids:
        doc = await db.files.find_one({"id": fid}, {"_id": 0})
        if not doc or doc.get("tenant_id") != tenant_id or doc.get("is_deleted"):
            raise HTTPException(
                403, detail={"error": "not_your_attachment", "file_id": fid},
            )
        let_type = doc.get("linked_entity_type")
        let_id = doc.get("linked_entity_id")
        uploader = doc.get("uploaded_by_user_id")
        if (
            (let_type == "customer" and let_id == customer_id)
            or (let_type == "job" and let_id in owned_jobs)
            or (uploader == user_id)
        ):
            continue
        raise HTTPException(
            403, detail={"error": "not_your_attachment", "file_id": fid},
        )


async def _broadcast_new(chat_id: str, tenant_id: str, sender_role: str,
                          sender_id: str, body_preview: str):
    """Fan-out to admins (if customer sent) or to the customer (if admin sent)."""
    try:
        from routers.realtime import bus
        if sender_role == "customer":
            admins = await db.users.find(
                {"role": {"$in": ["admin", "super_admin"]}, "tenant_id": tenant_id},
                {"_id": 0, "id": 1},
            ).to_list(200)
            for a in admins:
                await bus.broadcast(a["id"], {
                    "type": "portal_chat_message",
                    "payload": {"chat_id": chat_id, "preview": body_preview[:200]},
                })
        elif sender_role in ("admin", "super_admin"):
            chat = await db.portal_chats.find_one(
                {"id": chat_id, "tenant_id": tenant_id}, {"_id": 0, "customer_id": 1}
            )
            if chat and chat.get("customer_id"):
                await bus.broadcast(chat["customer_id"], {
                    "type": "portal_chat_message",
                    "payload": {"chat_id": chat_id, "preview": body_preview[:200]},
                })
    except Exception as e:
        logger.warning(f"portal_chat WS notify failed: {e}")


@router.post("/portal/chats")
async def create_chat(body: ChatCreateIn,
                      user: dict = Depends(get_current_user),
                      tenant: dict = Depends(get_current_tenant)):
    cid = _require_customer(user)
    # Verify ownership BEFORE persisting the thread's first message.
    first_att_ids = list(body.attachment_ids or [])
    if first_att_ids:
        await _verify_customer_attachment_ownership(
            first_att_ids, tenant["id"], cid, user["id"],
        )
    chat = {
        "id": new_id(),
        "tenant_id": tenant["id"],
        "customer_id": cid,
        "assigned_admin_id": None,
        "subject": (body.subject or "").strip() or "New conversation",
        "last_message_at": now_iso(),
        "unread_by_admin": 0,
        "unread_by_customer": 0,
        "created_at": now_iso(),
    }
    await db.portal_chats.insert_one(dict(chat))
    if (body.first_message and body.first_message.strip()) or first_att_ids:
        msg = {
            "id": new_id(),
            "tenant_id": tenant["id"],
            "chat_id": chat["id"],
            "sender_role": "customer",
            "sender_id": user["id"],
            "sender_name": user.get("name", "Customer"),
            "body": (body.first_message or "").strip(),
            "attachment_ids": first_att_ids,
            "attachments": [],  # legacy field retained for backward compat
            "created_at": now_iso(),
        }
        await db.portal_chat_messages.insert_one(dict(msg))
        await db.portal_chats.update_one(
            {"id": chat["id"]},
            {"$set": {"last_message_at": msg["created_at"]},
             "$inc": {"unread_by_admin": 1}},
        )
        await _broadcast_new(chat["id"], tenant["id"], "customer",
                              user["id"], msg["body"])
    chat.pop("_id", None)
    return chat


@router.get("/portal/chats")
async def list_chats(user: dict = Depends(get_current_user),
                     tenant: dict = Depends(get_current_tenant)):
    _require_customer_or_admin(user)
    q: dict = {"tenant_id": tenant["id"]}
    if user.get("role") == "customer":
        q["customer_id"] = user["customer_id"]
    chats = await db.portal_chats.find(q, {"_id": 0}).sort("last_message_at", -1).to_list(500)
    if user.get("role") in ("admin", "super_admin"):
        for c in chats:
            cust = await db.customers.find_one(
                {"id": c["customer_id"], "tenant_id": tenant["id"]},
                {"_id": 0, "name": 1, "email": 1},
            )
            c["customer_name"] = (cust or {}).get("name") or (cust or {}).get("email") or "Customer"
    return chats


@router.get("/portal/chats/{chat_id}/messages")
async def get_messages(chat_id: str,
                       user: dict = Depends(get_current_user),
                       tenant: dict = Depends(get_current_tenant)):
    _require_customer_or_admin(user)
    chat = await db.portal_chats.find_one(
        {"id": chat_id, "tenant_id": tenant["id"]}, {"_id": 0}
    )
    if not chat:
        raise HTTPException(404, "Chat not found")
    if user.get("role") == "customer" and chat.get("customer_id") != user.get("customer_id"):
        raise HTTPException(403, "Not your chat")
    msgs = await db.portal_chat_messages.find(
        {"chat_id": chat_id, "tenant_id": tenant["id"]}, {"_id": 0},
    ).sort("created_at", 1).to_list(2000)
    # Hydrate F0 attachment ids → objects on each message. Shared with
    # TeamChat's staff-side reader by living in services/.
    msgs = await hydrate_message_attachments(msgs, tenant["id"])
    return {"chat": chat, "messages": msgs}


@router.post("/portal/chats/{chat_id}/messages")
async def post_message(chat_id: str, body: MessagePostIn,
                       user: dict = Depends(get_current_user),
                       tenant: dict = Depends(get_current_tenant)):
    _require_customer_or_admin(user)
    chat = await db.portal_chats.find_one(
        {"id": chat_id, "tenant_id": tenant["id"]}, {"_id": 0}
    )
    if not chat:
        raise HTTPException(404, "Chat not found")
    if user.get("role") == "customer" and chat.get("customer_id") != user.get("customer_id"):
        raise HTTPException(403, "Not your chat")

    role = "customer" if user.get("role") == "customer" else "admin"
    att_ids = list(body.attachment_ids or body.attachments or [])
    if att_ids and role == "customer":
        await _verify_customer_attachment_ownership(
            att_ids, tenant["id"], user["customer_id"], user["id"],
        )
    text = (body.body or "").strip()
    if not text and not att_ids:
        raise HTTPException(400, "Empty message")
    msg = {
        "id": new_id(),
        "tenant_id": tenant["id"],
        "chat_id": chat_id,
        "sender_role": role,
        "sender_id": user["id"],
        "sender_name": user.get("name") or "Support",
        "body": text,
        "attachment_ids": att_ids,
        "attachments": [],  # legacy field retained
        "created_at": now_iso(),
    }
    await db.portal_chat_messages.insert_one(dict(msg))
    inc: dict = {}
    if role == "customer":
        inc["unread_by_admin"] = 1
    else:
        inc["unread_by_customer"] = 1
    update = {"$set": {"last_message_at": msg["created_at"]}}
    if role == "admin" and not chat.get("assigned_admin_id"):
        update["$set"]["assigned_admin_id"] = user["id"]
    if inc:
        update["$inc"] = inc
    await db.portal_chats.update_one({"id": chat_id}, update)
    await _broadcast_new(chat_id, tenant["id"], role, user["id"], msg["body"])
    msg.pop("_id", None)
    # Hydrate on return so the sender immediately sees rendered tiles.
    hydrated = await hydrate_message_attachments([msg], tenant["id"])
    return hydrated[0] if hydrated else msg


@router.post("/portal/chats/{chat_id}/read")
async def mark_read(chat_id: str,
                    user: dict = Depends(get_current_user),
                    tenant: dict = Depends(get_current_tenant)):
    _require_customer_or_admin(user)
    chat = await db.portal_chats.find_one(
        {"id": chat_id, "tenant_id": tenant["id"]}, {"_id": 0}
    )
    if not chat:
        raise HTTPException(404, "Chat not found")
    if user.get("role") == "customer":
        if chat.get("customer_id") != user.get("customer_id"):
            raise HTTPException(403, "Not your chat")
        await db.portal_chats.update_one(
            {"id": chat_id}, {"$set": {"unread_by_customer": 0}}
        )
    else:
        await db.portal_chats.update_one(
            {"id": chat_id}, {"$set": {"unread_by_admin": 0}}
        )
    return {"ok": True}
