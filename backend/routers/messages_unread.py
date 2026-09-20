"""Phase G1.1 · Feb-2026 — Unified messages unread-count.

Aggregates unread counts across every message-type channel the app
exposes (team chat + SMS conversations). Consumed by the Mobile
Messages tab badge and any web-side dot indicator that wants a
single number without having to know which channels the tenant has
enabled.

Contract
--------
::

    GET /api/messages/unread-count            (any authenticated user)
    →   { "unread_count": N,
          "by_channel":    { "chat": N?, "sms": N? } }

* ``by_channel`` only lists channels that exist and returned a non-
  zero count. Zero-state channels are omitted so the mobile badge
  logic can stay boolean-simple.
* Everything is tenant-scoped via ``get_current_tenant``.
* Chat count = same math as the pre-existing ``/api/chat/unread-count``
  (messages in the caller's channels newer than their ``chat_reads``
  cutoff, non-self, non-deleted).
* SMS count = threads owned by the caller's tenant where the last
  ``inbound`` message hasn't been marked read (``read_at`` missing on
  the last inbound line).  Falls back gracefully when the SMS layer
  isn't wired in the pod.
"""
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends

from config import db
from utils import get_current_user
from routers.tenants import get_current_tenant


router = APIRouter(tags=["Messages"])


async def _chat_unread_count(tenant_id: str, user_id: str) -> int:
    convo_ids = [c["id"] async for c in db.chat_conversations.find(
        {"tenant_id": tenant_id, "member_ids": user_id,
          "is_archived": {"$ne": True}},
        {"id": 1, "_id": 0})]
    if not convo_ids:
        return 0
    reads: Dict[str, str] = {}
    async for r in db.chat_reads.find(
            {"tenant_id": tenant_id, "user_id": user_id,
              "conversation_id": {"$in": convo_ids}}, {"_id": 0}):
        reads[r["conversation_id"]] = r.get("last_read_at") or ""
    total = 0
    for cid in convo_ids:
        cutoff = reads.get(cid, "")
        total += await db.chat_messages.count_documents({
            "tenant_id": tenant_id, "conversation_id": cid,
            "author_user_id": {"$ne": user_id},
            "created_at": {"$gt": cutoff},
            "deleted_at": None,
        })
    return total


async def _sms_unread_count(tenant_id: str) -> int:
    """Count SMS threads in this tenant with at least one unread
    inbound message. The SMS layer stores per-message rows in
    ``sms_messages`` linked to a ``sms_conversations`` doc via
    ``conversation_id``; unread inbounds have ``read_at`` absent or
    ``None``.  If either collection is missing (tenant hasn't enabled
    SMS yet) the aggregate falls back to 0."""
    try:
        cnt = await db.sms_messages.count_documents({
            "tenant_id": tenant_id,
            "direction": "inbound",
            "$or": [{"read_at": None}, {"read_at": {"$exists": False}}],
        })
    except Exception:  # noqa: BLE001
        cnt = 0
    return cnt


@router.get("/messages/unread-count")
async def messages_unread_count(
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    chat_n = await _chat_unread_count(tenant["id"], user["id"])
    sms_n  = await _sms_unread_count(tenant["id"])
    by_channel: Dict[str, int] = {}
    if chat_n:
        by_channel["chat"] = chat_n
    if sms_n:
        by_channel["sms"] = sms_n
    return {
        "unread_count": int(chat_n + sms_n),
        "by_channel":   by_channel,
    }
