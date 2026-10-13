"""P2 #5 · Feb-2026 · Communication detail resolver.

Serves ``GET /api/communications-detail/{id}`` — a single clickable-row
detail endpoint for the admin Communication Timeline modal.

The row id can live in any of five collections (audit §3) with
distinct row shapes.  Rather than make the frontend pick a collection,
this endpoint tries each one in priority order and returns the first
match wrapped in a stable shape.  Rows that don't persist body
(e.g. ``notification_dispatch_log``) return ``body_available=false``
with an operator-friendly fallback copy on the modal side.

RBAC: admin + manager only.  Technicians and customers are 403'd —
mirrors the strictest existing contract on
``/api/communications-log`` (``_require_admin``) + the admin+manager
contract on ``/api/leads/{id}/communications``.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException

from config import db
from utils import require_admin_or_manager
from routers.tenants import get_current_tenant

router = APIRouter()


def _coerce_direction(row: Dict[str, Any], source: str) -> str:
    """Normalize direction field across the heterogenous source
    collections.  Default outbound unless the source IS the inbound
    collection OR the row explicitly carries ``direction=inbound``."""
    if source == "sms_inbound":
        return "inbound"
    _d = (row.get("direction") or "").strip().lower()
    if _d in ("inbound", "outbound"):
        return _d
    return "outbound"


def _shape_marketing_delivery(row: Dict[str, Any]) -> Dict[str, Any]:
    channel = (row.get("channel") or "email").lower()
    body = row.get("body_rendered")
    body_available = bool(body)
    return {
        "source": "marketing_deliveries",
        "channel": channel,
        "direction": _coerce_direction(row, "marketing_deliveries"),
        "subject": row.get("subject_rendered") or row.get("subject") or "",
        "from": None,  # not persisted on this collection
        "to": (row.get("recipient_email") if channel == "email"
                else row.get("recipient_phone")) or None,
        "cc": [],
        "bcc": [],
        "sent_at": row.get("sent_at") or row.get("created_at"),
        "delivered_at": row.get("delivered_at"),
        "opened_at": row.get("opened_at"),
        "clicked_at": row.get("clicked_at"),
        "bounced_at": row.get("bounced_at"),
        "provider": row.get("provider"),
        "provider_response_id": row.get("provider_response_id"),
        "delivery_status": row.get("delivery_status") or row.get("provider_status"),
        "body_available": body_available,
        "body": body or "",
        "body_format": "html" if channel == "email" else "text",
    }


def _shape_lead_communication(row: Dict[str, Any]) -> Dict[str, Any]:
    channel = (row.get("channel") or "sms").lower()
    body = row.get("body")
    body_available = bool(body)
    return {
        "source": "lead_communications",
        "channel": channel,
        "direction": _coerce_direction(row, "lead_communications"),
        "subject": row.get("subject") or "",
        "from": row.get("from_identity"),
        "to": row.get("to_identity"),
        "cc": [],
        "bcc": [],
        "sent_at": row.get("created_at"),
        "delivered_at": None,
        "opened_at": None,
        "clicked_at": None,
        "bounced_at": None,
        "provider": None,
        "provider_response_id": row.get("provider_message_id"),
        "delivery_status": row.get("status") or row.get("provider_status_raw"),
        "body_available": body_available,
        "body": body or "",
        # Lead-side email sends go through the same path as SMS; body is
        # whatever the caller passed in.  Treat as html for channel=email
        # (consistent with marketing_deliveries) and text for sms.
        "body_format": "html" if channel == "email" else "text",
    }


def _shape_notification_dispatch(row: Dict[str, Any]) -> Dict[str, Any]:
    channel = (row.get("channel") or "email").lower()
    return {
        "source": "notification_dispatch_log",
        "channel": channel,
        "direction": _coerce_direction(row, "notification_dispatch_log"),
        "subject": row.get("subject") or "",
        "from": None,
        "to": row.get("resolved_address") or None,
        "cc": [],
        "bcc": [],
        "sent_at": row.get("sent_at") or row.get("reserved_at"),
        "delivered_at": None,
        "opened_at": None,
        "clicked_at": None,
        "bounced_at": None,
        "provider": None,
        "provider_response_id": row.get("provider_id"),
        "delivery_status": row.get("status"),
        # notification_dispatch_log is metadata-only; body is not persisted.
        "body_available": False,
        "body": "",
        "body_format": "html" if channel == "email" else "text",
    }


def _shape_communications_log(row: Dict[str, Any]) -> Dict[str, Any]:
    channel = (row.get("channel") or "email").lower()
    body = row.get("body") or row.get("body_rendered") or row.get("text")
    body_available = bool(body)
    return {
        "source": "communications_log",
        "channel": channel,
        "direction": _coerce_direction(row, "communications_log"),
        "subject": row.get("subject") or row.get("subject_rendered") or "",
        "from": row.get("from_identity") or row.get("sender"),
        "to": row.get("recipient") or row.get("to_identity")
             or row.get("recipient_email") or row.get("recipient_phone"),
        "cc": [],
        "bcc": [],
        "sent_at": row.get("sent_at") or row.get("created_at"),
        "delivered_at": row.get("delivered_at"),
        "opened_at": None,
        "clicked_at": None,
        "bounced_at": None,
        "provider": row.get("provider"),
        "provider_response_id": row.get("provider_response_id")
             or row.get("provider_message_id"),
        "delivery_status": row.get("status") or row.get("delivery_status"),
        "body_available": body_available,
        "body": body or "",
        "body_format": "html" if channel == "email" else "text",
    }


def _shape_sms_inbound(row: Dict[str, Any]) -> Dict[str, Any]:
    body = row.get("body")
    body_available = bool(body)
    return {
        "source": "sms_inbound",
        "channel": "sms",
        "direction": "inbound",
        "subject": "",
        "from": row.get("from_number"),
        "to": row.get("to_number"),
        "cc": [],
        "bcc": [],
        "sent_at": row.get("received_at"),
        "delivered_at": row.get("received_at"),
        "opened_at": None,
        "clicked_at": None,
        "bounced_at": None,
        "provider": "ringcentral",
        "provider_response_id": row.get("provider_message_id")
             or row.get("rc_message_id"),
        "delivery_status": "delivered",
        "body_available": body_available,
        "body": body or "",
        "body_format": "text",
    }


# Resolver priority order.  marketing_deliveries first because it has
# the richest row shape (full HTML body + provider telemetry); the
# dispatch-log and communications_log collections are checked later
# because they frequently hold metadata-only rows that would hide a
# richer sibling row with the same id.
_RESOLVERS = (
    ("marketing_deliveries", _shape_marketing_delivery),
    ("lead_communications", _shape_lead_communication),
    ("sms_inbound", _shape_sms_inbound),
    ("notification_dispatch_log", _shape_notification_dispatch),
    ("communications_log", _shape_communications_log),
)


async def _lookup(id_: str, tenant_id: str) -> Optional[Dict[str, Any]]:
    for coll_name, shaper in _RESOLVERS:
        coll = getattr(db, coll_name)
        row = await coll.find_one(
            {"id": id_, "tenant_id": tenant_id}, {"_id": 0},
        )
        if row is not None:
            return shaper(row)
    return None


@router.get("/communications-detail/{id}")
async def get_communication_detail(
    id: str,
    user: dict = Depends(require_admin_or_manager),
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    """Resolve ``id`` across the five supported log collections and
    return a stable detail envelope.  404 when no collection matches
    the ``(id, tenant_id)`` pair.  RBAC enforced by the dep —
    technicians / customers never reach this handler."""
    shaped = await _lookup(id, tenant["id"])
    if shaped is None:
        raise HTTPException(404, "Communication detail not found")
    return shaped
