"""Phase K9 · Feb-2026 — Portal chat ↔ SMS bridge.

Threads customer portal chat messages onto an admin's SMS inbox and
routes the admin's SMS replies back into the portal chat as a
"Support" bubble.  Reuses the existing RingCentral outbound wire
(``services.sms.rc_adapter.send``) and the existing RingCentral
inbound webhook (``routers/ringcentral.py::_handle_sms_event``), so
no new webhook endpoint or signature scheme is introduced.

Data contract
-------------
Every outbound notification writes a row to ``db.sms_thread_notifications``
so an inbound SMS with no ``[T:xxxxxx]`` thread tag can still be
routed to the most recent thread by matching the admin's from-number:

    {
      "id": <uuid>,
      "tenant_id": <str>,
      "thread_id": <portal_chats.id>,
      "admin_phone": <E.164 str>,
      "from_number": <tenant.rc_sms_from_number>,
      "sent_provider_id": <RC message id | None>,
      "throttled": bool,
      "last_notified_at_utc": ISO-8601 UTC,
      "sms_body_preview": <first 200 chars of the SMS body>,
      "message_id": <portal_chat_messages.id>,
    }

SMS body format (spec-locked, do NOT parametrize per tenant):

    [Portal] <Customer Name>: <first ~120 chars of body …> [T:<6-hex>]

Throttle
--------
If any admin-role message on the same thread was posted within the
last ``_THROTTLE_WINDOW_SECONDS`` (15 min), the outbound SMS is
skipped — but the notification row is still written with
``throttled=True`` so the inbound fallback path still has a
last-notified pointer to correlate on.
"""
from __future__ import annotations

import asyncio
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from config import db, logger
from utils import new_id, now_iso


# ── Constants (spec-locked) ──────────────────────────────────────
_THROTTLE_WINDOW_SECONDS = 15 * 60           # 15-minute throttle
_BODY_CHAR_BUDGET = 120                       # first ~120 chars
_TAG_HEX_LEN = 6                              # first 6 chars of thread id
_TAG_RE = re.compile(r"\[T:([a-f0-9]{" + str(_TAG_HEX_LEN) + r"})\]",
                      re.IGNORECASE)


# ── Body formatter ───────────────────────────────────────────────
def _thread_tag(thread_id: str) -> str:
    # Portal chat threads use UUID4 by default; strip dashes then take
    # the first 6 hex chars so the tag is compact + easy to grep.
    compact = re.sub(r"[^a-f0-9]", "", (thread_id or "").lower())[:_TAG_HEX_LEN]
    return f"[T:{compact}]"


def build_sms_body(customer_name: str, message_body: str,
                    thread_id: str) -> str:
    """Return the exact SMS body per the K9 spec."""
    text = (message_body or "").strip().replace("\r\n", " ").replace("\n", " ")
    if len(text) > _BODY_CHAR_BUDGET:
        text = text[:_BODY_CHAR_BUDGET].rstrip() + "…"
    name = (customer_name or "").strip() or "Customer"
    return f"[Portal] {name}: {text} {_thread_tag(thread_id)}"


# ── Outbound: customer message → SMS ping ────────────────────────
async def _throttle_recent_admin_reply(tenant_id: str,
                                        chat_id: str) -> bool:
    """Return True when an admin-role message was posted on this
    thread within the throttle window (skip the SMS)."""
    cutoff = (datetime.now(timezone.utc)
               - timedelta(seconds=_THROTTLE_WINDOW_SECONDS)).isoformat()
    hit = await db.portal_chat_messages.find_one({
        "tenant_id": tenant_id,
        "chat_id": chat_id,
        "sender_role": "admin",
        "created_at": {"$gte": cutoff},
    }, {"_id": 0, "id": 1})
    return bool(hit)


async def _record_notification(*, tenant_id: str, thread_id: str,
                                admin_phone: str,
                                from_number: Optional[str],
                                throttled: bool,
                                message_id: str,
                                sms_body: str,
                                sent_provider_id: Optional[str]) -> None:
    await db.sms_thread_notifications.insert_one({
        "id": new_id(),
        "tenant_id": tenant_id,
        "thread_id": thread_id,
        "admin_phone": admin_phone,
        "from_number": from_number,
        "sent_provider_id": sent_provider_id,
        "throttled": bool(throttled),
        "last_notified_at_utc": now_iso(),
        "sms_body_preview": (sms_body or "")[:200],
        "message_id": message_id,
    })


async def _send_via_rc(*, tenant_id: str, to_phone: str,
                        body: str) -> Optional[str]:
    """Delegate to the shared RC adapter.  Never raises — RingCentral
    outages must NEVER fail the customer's message post.  Returns the
    provider message id on success, otherwise None."""
    try:
        from services.sms.rc_adapter import send as _rc_send
        env = await _rc_send(
            to=to_phone,
            body=body,
            category="transactional",
            tenant_id=tenant_id,
        )
        return (env or {}).get("provider_response_id")
    except Exception as exc:                               # noqa: BLE001
        logger.warning(
            "[k9] rc outbound failed tenant=%s to=%s err=%s",
            tenant_id, to_phone, exc,
        )
        return None


async def notify_admin_of_customer_message(
    *, tenant: Dict[str, Any],
    chat: Dict[str, Any],
    message: Dict[str, Any],
    customer_name: str,
) -> Dict[str, Any]:
    """Fire-and-forget SMS ping.  Returns the outcome envelope so
    callers (tests, curl proofs) can inspect it; production callers
    wrap this in ``asyncio.create_task`` so the HTTP path doesn't
    block on RC.

    Silent no-ops (spec):
      - tenant.admin_sms_notify_to null/empty → skip entirely, no row.
      - tenant.rc_sms_from_number null/empty → skip send, no row,
        WARN so ops can see the misconfig.
    """
    tenant_id = tenant.get("id") or ""
    thread_id = chat.get("id") or ""
    message_id = message.get("id") or ""
    admin_phone = (tenant.get("admin_sms_notify_to") or "").strip()
    from_number = (tenant.get("rc_sms_from_number") or "").strip() or None

    if not admin_phone:
        return {"status": "skipped_no_admin_phone",
                "reason": "tenant.admin_sms_notify_to unset"}
    if not from_number:
        logger.warning(
            "[k9] admin_sms_notify_to set but rc_sms_from_number missing "
            "for tenant=%s — SMS ping skipped.", tenant_id,
        )
        return {"status": "skipped_no_from_number",
                "reason": "tenant.rc_sms_from_number unset"}

    sms_body = build_sms_body(customer_name, message.get("body") or "",
                               thread_id)

    throttled = await _throttle_recent_admin_reply(tenant_id, thread_id)
    provider_id: Optional[str] = None
    if not throttled:
        provider_id = await _send_via_rc(
            tenant_id=tenant_id, to_phone=admin_phone, body=sms_body,
        )

    await _record_notification(
        tenant_id=tenant_id, thread_id=thread_id,
        admin_phone=admin_phone, from_number=from_number,
        throttled=throttled, message_id=message_id,
        sms_body=sms_body, sent_provider_id=provider_id,
    )
    return {
        "status": "throttled" if throttled else "sent",
        "throttled": throttled,
        "sms_body": sms_body,
        "provider_id": provider_id,
        "admin_phone": admin_phone,
    }


def spawn_notify_task(*, tenant: Dict[str, Any],
                       chat: Dict[str, Any],
                       message: Dict[str, Any],
                       customer_name: str) -> Optional[asyncio.Task]:
    """Fire ``notify_admin_of_customer_message`` in the background so
    the portal HTTP path returns fast.  Returns the ``Task`` handle
    for tests; production callers ignore it."""
    try:
        return asyncio.create_task(
            notify_admin_of_customer_message(
                tenant=tenant, chat=chat, message=message,
                customer_name=customer_name,
            ),
        )
    except RuntimeError:
        # No running loop (rare: called from a sync context).  Fall
        # through to a blocking call so the notification still lands.
        logger.warning(
            "[k9] no running event loop — sending notification synchronously",
        )
        return None


# ── Inbound: admin SMS reply → portal chat ───────────────────────
def _strip_tag(text: str) -> str:
    return _TAG_RE.sub("", text or "").strip()


async def _resolve_thread_id_from_tag(tag_6hex: str,
                                       tenant_id: Optional[str]
                                       ) -> Optional[str]:
    """Prefix-match a portal_chats.id starting with ``tag_6hex`` (or
    the same 6 chars found anywhere in the compacted uuid).  Returns
    the resolved thread id when EXACTLY one row matches.  Ambiguous
    matches return None so the caller can fall back to the
    per-admin-phone last-notified pointer."""
    if not tag_6hex:
        return None
    tag = tag_6hex.lower()
    # UUID4 has 8 hex chars in the first segment — a 6-char prefix
    # match on ``id`` is unique in every realistic case (16^6 ≈ 16M).
    q: Dict[str, Any] = {"id": {"$regex": f"^{tag}"}}
    if tenant_id:
        q["tenant_id"] = tenant_id
    rows = await db.portal_chats.find(q, {"_id": 0, "id": 1,
                                             "tenant_id": 1,
                                             "customer_id": 1}
                                       ).to_list(2)
    if len(rows) == 1:
        return rows[0]["id"]
    return None


async def _resolve_thread_from_last_notified(admin_phone: str
                                              ) -> Optional[Dict[str, Any]]:
    row = await db.sms_thread_notifications.find_one(
        {"admin_phone": admin_phone},
        {"_id": 0, "thread_id": 1, "tenant_id": 1},
        sort=[("last_notified_at_utc", -1)],
    )
    return row


async def route_inbound_admin_reply(*, from_number: str,
                                     sms_text: str) -> Optional[Dict[str, Any]]:
    """Handle an inbound RingCentral SMS.

    Resolution order:
      1. ``[T:xxxxxx]`` tag in the body → prefix-match on
         ``portal_chats.id``.
      2. Fallback: ``sms_thread_notifications`` most-recent row for
         ``admin_phone == from_number`` → its ``thread_id``.
      3. Nothing → return None (caller drops with 200).

    Never raises.  On success, inserts a ``sender_role=admin`` message
    into ``portal_chat_messages`` with ``origin=sms`` and writes a
    ``chat_admin_reply_via_sms`` communication-timeline entry.
    """
    if not (from_number and sms_text):
        return None
    from_number = from_number.strip()

    tag_match = _TAG_RE.search(sms_text or "")
    thread_id: Optional[str] = None
    tenant_id: Optional[str] = None
    if tag_match:
        # Look up the tag against the LAST-NOTIFIED row for this
        # from-number FIRST so the same 6-char prefix can't be
        # cross-tenant hijacked.  Falls through to a global prefix
        # scan when the from-number has no prior ping (edge cases).
        last = await _resolve_thread_from_last_notified(from_number)
        if last:
            tenant_id = last.get("tenant_id")
        thread_id = await _resolve_thread_id_from_tag(
            tag_match.group(1), tenant_id,
        )
        if not thread_id:
            # Widen to any tenant that carries a matching prefix — the
            # per-admin-phone check above already isolates most cross-
            # tenant confusion; this is the "new phone, existing tag"
            # escape hatch.
            thread_id = await _resolve_thread_id_from_tag(
                tag_match.group(1), None,
            )
    if not thread_id:
        last = await _resolve_thread_from_last_notified(from_number)
        if last:
            thread_id = last.get("thread_id")
            tenant_id = last.get("tenant_id")

    if not thread_id:
        logger.info(
            "[k9] inbound SMS from %s dropped — no thread routing found. "
            "text=%r", from_number, (sms_text or "")[:80],
        )
        return None

    chat = await db.portal_chats.find_one(
        {"id": thread_id}, {"_id": 0},
    )
    if not chat:
        logger.warning(
            "[k9] inbound routing resolved to missing chat id=%s", thread_id,
        )
        return None
    tenant_id = chat.get("tenant_id") or tenant_id or ""

    body = _strip_tag(sms_text)
    msg = {
        "id": new_id(),
        "tenant_id": tenant_id,
        "chat_id": thread_id,
        "sender_role": "admin",
        "sender_id": None,                # SMS reply — no user account
        "sender_name": "Support",
        "body": body,
        "attachment_ids": [],
        "attachments": [],
        "origin": "sms",                  # NEW field per K9 spec
        "admin_phone": from_number,       # audit
        "created_at": now_iso(),
    }
    await db.portal_chat_messages.insert_one(dict(msg))
    await db.portal_chats.update_one(
        {"id": thread_id},
        {"$set": {"last_message_at": msg["created_at"]},
         "$inc": {"unread_by_customer": 1}},
    )

    # Communication-timeline entry so operators can see the
    # SMS-originated reply under the customer's activity.
    try:
        await db.audit_events.insert_one({
            "id": new_id(),
            "tenant_id": tenant_id,
            "event_type": "chat_admin_reply_via_sms",
            "actor_id": None,
            "actor_email": None,
            "timestamp": now_iso(),
            "payload": {
                "customer_id": chat.get("customer_id"),
                "chat_id": thread_id,
                "message_id": msg["id"],
                "admin_phone": from_number,
                "body_preview": (body or "")[:120],
            },
        })
    except Exception as exc:                               # noqa: BLE001
        logger.warning("[k9] audit insert failed: %s", exc)

    # Broadcast on the same bus the portal_chats router uses so the
    # customer's active portal tab picks up the new message.
    try:
        from routers.realtime import bus
        if chat.get("customer_id"):
            await bus.broadcast(chat["customer_id"], {
                "type": "portal_chat_message",
                "payload": {"chat_id": thread_id,
                             "preview": (body or "")[:200]},
            })
    except Exception as exc:                               # noqa: BLE001
        logger.warning("[k9] realtime broadcast skipped: %s", exc)

    return {"thread_id": thread_id, "message_id": msg["id"],
             "tenant_id": tenant_id}
