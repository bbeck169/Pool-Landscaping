"""Phase I7 · Wave A · Feb-2026 — Communication timeline.

``GET /api/customers/{customer_id}/communication-timeline`` — merges
per-customer SMS + email events across three log collections into
a single time-sorted stream:

  * ``notification_dispatch_log`` — primary. Per-message rows with
    ``channel`` = ``sms`` | ``email``, populated for every dispatch
    through the F7 idempotent notifier + the F5 marketing sequences.
    Linked to the customer via ``recipient_id`` OR via
    ``resolved_address`` matching a phone / email on the customer.
  * ``audit_events`` — supplementary. Surfaces ``portal_invite_bulk``
    rows whose payload lists this customer_id (so operators can see
    "portal invite email fired 3 days ago" without needing to open
    the dispatch log directly).
  * ``email_delivery_log`` — INTENTIONALLY EXCLUDED.  Audit surfaced
    that this collection stores weekly digest batches
    (``week_start`` / ``week_end`` / ``total_completed``) — a
    per-customer view is not extractable without denormalizing the
    ``recipients`` list, and the same per-email row also lives on
    ``notification_dispatch_log``.  Excluding it prevents duplicate
    rows and keeps the query surface honest.

Portal filtering: when the caller's role is ``customer`` the
response strips ``actor_user_id`` + ``delivery_error`` before
returning.  The frontend never sees those fields on the wire, so a
future portal regression can't accidentally leak them.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query

from config import db
from routers.tenants import get_current_tenant
from utils import get_current_user

router = APIRouter()
logger = logging.getLogger("communication_timeline")

_ADMIN_ROLES = {"admin", "manager", "super_admin"}
_TECH_ROLES = {"tech", "technician"}
_MAX_PER_COLLECTION = 200
_DEFAULT_LIMIT = 50
_MAX_LIMIT = 200

_AUDIT_EVENT_TYPES = ("portal_invite_bulk",)


def _preview(text: Optional[str], n: int = 500) -> str:
    if not text:
        return ""
    s = str(text).strip()
    return s[:n]


async def _load_customer(customer_id: str, tenant_id: str) -> Dict[str, Any]:
    row = await db.customers.find_one(
        {"id": customer_id, "tenant_id": tenant_id},
        {"_id": 0, "id": 1, "email": 1, "emails": 1,
            "phone": 1, "phones": 1, "mobile_phone": 1, "home_phone": 1},
    )
    if not row:
        raise HTTPException(404, "customer not found")
    return row


def _customer_addresses(customer: Dict[str, Any]) -> Tuple[List[str], List[str]]:
    """Return (emails, phones) — lowercased/normalized for matching
    against ``notification_dispatch_log.resolved_address``."""
    emails: List[str] = []
    for k in ("email",):
        v = customer.get(k)
        if v:
            emails.append(str(v).strip().lower())
    for v in customer.get("emails") or []:
        if isinstance(v, dict):
            v = v.get("address") or v.get("email")
        if v:
            emails.append(str(v).strip().lower())
    phones: List[str] = []
    for k in ("phone", "mobile_phone", "home_phone"):
        v = customer.get(k)
        if v:
            phones.append(str(v).strip())
    for v in customer.get("phones") or []:
        if isinstance(v, dict):
            v = v.get("number") or v.get("phone")
        if v:
            phones.append(str(v).strip())
    return sorted(set(emails)), sorted(set(phones))


def _dispatch_to_item(row: Dict[str, Any]) -> Dict[str, Any]:
    channel = (row.get("channel") or "").lower()
    kind = "sms" if channel == "sms" else "email"
    ts = row.get("sent_at") or row.get("reserved_at") or ""
    meta = row.get("metadata") or {}
    actor_user_id = meta.get("actor_user_id") or meta.get("user_id")
    actor_email = meta.get("actor_email")
    if actor_email:
        actor_label = actor_email
        actor_kind = "user"
    elif actor_user_id:
        actor_label = "User"
        actor_kind = "user"
    else:
        actor_label = "System / Automation"
        actor_kind = "system"
    return {
        "id": row.get("id") or row.get("dedupe_key"),
        "type": kind,
        "occurred_at": ts,
        "actor_label": actor_label,
        "actor_kind": actor_kind,
        "actor_user_id": actor_user_id,
        "direction": "outbound",
        "channel_id": row.get("id"),
        "subject": row.get("subject") or None,
        "body_preview": _preview(meta.get("body") or meta.get("message")
                                        or row.get("subject")),
        "recipient": row.get("resolved_address") or "",
        "delivery_status": row.get("status") or "queued",
        "delivery_error": row.get("error"),
    }


def _audit_to_item(row: Dict[str, Any]) -> Dict[str, Any]:
    payload = row.get("payload") or {}
    actor_email = row.get("actor_email")
    actor_user_id = row.get("actor_id")
    label = actor_email or ("User" if actor_user_id else "System / Automation")
    kind = "user" if (actor_email or actor_user_id) else "system"
    return {
        "id": row.get("id"),
        "type": "email",  # portal invites are emails
        "occurred_at": row.get("timestamp") or "",
        "actor_label": label,
        "actor_kind": kind,
        "actor_user_id": actor_user_id,
        "direction": "outbound",
        "channel_id": row.get("id"),
        "subject": "Portal invite",
        "body_preview": _preview(
            f"Bulk portal invite fired by {label}. "
            f"Sent to {payload.get('sent', 0)} customer(s); "
            f"skipped {payload.get('skipped_already_activated', 0)} already "
            "active."
        ),
        "recipient": "",  # not stored on audit_events
        "delivery_status": "sent" if payload.get("sent") else "failed",
        "delivery_error": row.get("reason") or None,
    }


def _strip_admin_fields(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Portal role: never leak actor_user_id + delivery_error over
    the wire.  Applied server-side so a frontend regression can't
    accidentally surface them."""
    stripped = []
    for it in items:
        clean = dict(it)
        clean.pop("actor_user_id", None)
        clean.pop("delivery_error", None)
        stripped.append(clean)
    return stripped


@router.get("/customers/{customer_id}/communication-timeline")
async def communication_timeline(
    customer_id: str,
    limit: int = Query(_DEFAULT_LIMIT, ge=1, le=_MAX_LIMIT),
    before: Optional[str] = Query(None),
    types: Optional[str] = Query(None,
                                       description="csv: sms,email"),
    user: Dict[str, Any] = Depends(get_current_user),
    tenant: Dict[str, Any] = Depends(get_current_tenant),
) -> Dict[str, Any]:
    role = (user.get("role") or "").lower()
    if role in _TECH_ROLES:
        raise HTTPException(403, "Technicians cannot access comms timeline")
    is_admin = role in _ADMIN_ROLES
    is_customer = role == "customer"
    if is_customer and user.get("customer_id") != customer_id:
        raise HTTPException(403, "Not allowed")
    if not (is_admin or is_customer):
        raise HTTPException(403, "Not allowed")

    customer = await _load_customer(customer_id, tenant["id"])
    emails, phones = _customer_addresses(customer)

    wanted_types = None
    if types:
        wanted_types = {t.strip().lower() for t in types.split(",")
                             if t.strip()}

    # ── notification_dispatch_log ─────────────────────────────────
    dispatch_filter: Dict[str, Any] = {
        "tenant_id": tenant["id"],
        "$or": [
            {"recipient_id": customer_id},
        ],
    }
    if emails or phones:
        dispatch_filter["$or"].append(
            {"resolved_address": {"$in": emails + phones}},
        )
    if wanted_types:
        dispatch_filter["channel"] = {"$in": list(wanted_types)}
    if before:
        dispatch_filter["$and"] = [
            {"$or": [{"sent_at": {"$lt": before}},
                        {"sent_at": None,
                             "reserved_at": {"$lt": before}}]},
        ]
    dispatch_rows: List[Dict[str, Any]] = []
    async for r in db.notification_dispatch_log.find(
        dispatch_filter, {"_id": 0},
    ).sort([("sent_at", -1), ("reserved_at", -1)]).limit(_MAX_PER_COLLECTION):
        dispatch_rows.append(r)

    # ── audit_events (portal_invite_bulk) ─────────────────────────
    audit_rows: List[Dict[str, Any]] = []
    include_audit = (wanted_types is None) or ("email" in wanted_types)
    if include_audit:
        audit_filter: Dict[str, Any] = {
            "tenant_id": tenant["id"],
            "event_type": {"$in": list(_AUDIT_EVENT_TYPES)},
            "$or": [
                {"payload.customer_ids": customer_id},
                {"payload.customer_id": customer_id},
            ],
        }
        if before:
            audit_filter["timestamp"] = {"$lt": before}
        async for r in db.audit_events.find(
            audit_filter, {"_id": 0},
        ).sort("timestamp", -1).limit(_MAX_PER_COLLECTION):
            audit_rows.append(r)

    # ── Merge + sort desc ────────────────────────────────────────
    items = [_dispatch_to_item(r) for r in dispatch_rows]
    items += [_audit_to_item(r) for r in audit_rows]
    items.sort(key=lambda i: i["occurred_at"] or "", reverse=True)

    # Pagination cursor: return one extra row to detect ``has_more``.
    page = items[:limit]
    has_more = len(items) > limit
    next_before = page[-1]["occurred_at"] if (has_more and page) else None

    if is_customer:
        page = _strip_admin_fields(page)

    return {
        "customer_id": customer_id,
        "items": page,
        "has_more": has_more,
        "next_before": next_before,
    }
