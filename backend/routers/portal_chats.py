"""Phase 20B.1a · Portal chat threads.

Extends the legacy `messages` (single-thread AI-relay) with a new
`portal_chats` + `portal_chat_messages` schema for multi-topic support.

- Customers create threads and post messages against them.
- Admins list all threads in the tenant + reply.
- Techs are blocked (403).
- Real-time via `bus.broadcast(user_id, {type: "portal_chat_message"})`.
"""
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from config import db, logger
from utils import now_iso, new_id, get_current_user
from routers.tenants import get_current_tenant

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


class MessagePostIn(BaseModel):
    body: str
    attachments: Optional[List[str]] = None


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
    if body.first_message and body.first_message.strip():
        msg = {
            "id": new_id(),
            "tenant_id": tenant["id"],
            "chat_id": chat["id"],
            "sender_role": "customer",
            "sender_id": user["id"],
            "sender_name": user.get("name", "Customer"),
            "body": body.first_message.strip(),
            "attachments": [],
            "created_at": now_iso(),
        }
        await db.portal_chat_messages.insert_one(dict(msg))
        await db.portal_chats.update_one(
            {"id": chat["id"]},
            {"$set": {"last_message_at": msg["created_at"]},
             "$inc": {"unread_by_admin": 1}},
        )
        await _broadcast_new(chat["id"], tenant["id"], "customer", user["id"], msg["body"])
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
    # Enrich for admin view with customer name.
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
    msg = {
        "id": new_id(),
        "tenant_id": tenant["id"],
        "chat_id": chat_id,
        "sender_role": role,
        "sender_id": user["id"],
        "sender_name": user.get("name") or "Support",
        "body": (body.body or "").strip(),
        "attachments": body.attachments or [],
        "created_at": now_iso(),
    }
    if not msg["body"] and not msg["attachments"]:
        raise HTTPException(400, "Empty message")
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
    return msg


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
