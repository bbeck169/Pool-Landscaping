"""Phase K63.polish · Feb-2026 — Notification Dispatch Log read API.

Exposes the ``audit_logs`` rows written by the K63 lead-alert
dispatcher (``services.lead_notifications``) as a tenant-scoped,
admin-only observability feed:

  * ``GET /api/admin/notification-dispatch-log``

Filters (all optional):
  * ``lead_id``   — exact match on ``audit_logs.lead_id``.
  * ``recipient`` — case-insensitive prefix / equality match on the
                     stored ``target``. Emails are lower-cased before
                     comparison, phone numbers are compared as-is.
  * ``channel``   — ``email`` | ``sms``.
  * ``status``    — ``sent`` | ``failed``.
  * ``since``     — ISO-8601 timestamp; rows with
                     ``created_at >= since`` are returned.
  * ``limit``     — 1..200, defaults to 50. Values > 200 clamp to
                     200 (avoids someone yanking the whole audit
                     table over one request).

Contract:
  * Response is newest-first (``created_at`` desc).
  * ``status`` is derived from the event name so the caller doesn't
    need to know the audit_logs schema.
  * ``provider_message_id`` is echoed straight from the row when
    present; nulls are preserved so a Playwright / QA harness can
    distinguish "adapter returned no id" from "we never called".
  * Tenant scoping is enforced against the acting user's tenant via
    ``get_current_tenant`` — a caller can NEVER read another tenant's
    audit rows.
  * No mutation endpoints; this router is strictly read-only.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from config import db
from utils import require_admin
from routers.tenants import get_current_tenant


router = APIRouter(tags=["admin"])


_ALLOWED_CHANNELS = {"email", "sms"}
_ALLOWED_STATUSES = {"sent", "failed"}
_STATUS_TO_EVENT = {
    "sent": "lead_notification_sent",
    "failed": "lead_notification_failed",
}
_MAX_LIMIT = 200
_DEFAULT_LIMIT = 50


def _parse_since(since: Optional[str]) -> Optional[str]:
    """Return the ``since`` value if it round-trips through
    ``datetime.fromisoformat`` — else raise a 400 so the FE can
    surface a clear error. We accept trailing ``Z`` (Node's default
    ISO output). Value is echoed back into the Mongo query as a
    plain string because ``created_at`` is stored as an ISO string
    on ``audit_logs`` (see ``services.lead_notifications``)."""
    if not since:
        return None
    raw = since.strip()
    if not raw:
        return None
    probe = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        datetime.fromisoformat(probe)
    except ValueError:
        raise HTTPException(400, "Invalid `since` — expected ISO-8601")
    return raw


@router.get("/admin/notification-dispatch-log")
async def list_notification_dispatch_log(
    lead_id: Optional[str] = Query(None),
    recipient: Optional[str] = Query(None),
    channel: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    since: Optional[str] = Query(None),
    limit: int = Query(_DEFAULT_LIMIT, ge=1),
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    if channel is not None and channel not in _ALLOWED_CHANNELS:
        raise HTTPException(400, "Invalid `channel` — expected `email` or `sms`")
    if status is not None and status not in _ALLOWED_STATUSES:
        raise HTTPException(400, "Invalid `status` — expected `sent` or `failed`")
    since_str = _parse_since(since)
    limit = min(limit, _MAX_LIMIT)

    query: dict = {
        "tenant_id": tenant["id"],
        "event": {"$in": list(_STATUS_TO_EVENT.values())},
    }
    if status is not None:
        query["event"] = _STATUS_TO_EVENT[status]
    if channel is not None:
        query["channel"] = channel
    if lead_id is not None:
        query["lead_id"] = lead_id
    if recipient is not None:
        raw = recipient.strip()
        if raw:
            # Emails are stored lower-cased by the settings PUT +
            # dispatcher; phones are E.164. Case-fold only the
            # email flavour to keep phone lookups exact.
            if "@" in raw:
                query["target"] = raw.lower()
            else:
                query["target"] = raw
    if since_str is not None:
        query["created_at"] = {"$gte": since_str}

    cursor = db.audit_logs.find(
        query, {"_id": 0},
    ).sort("created_at", -1).limit(limit)
    rows = await cursor.to_list(length=limit)

    items = []
    for r in rows:
        event = r.get("event") or ""
        items.append({
            "id": r.get("id"),
            "lead_id": r.get("lead_id"),
            "recipient": r.get("target"),
            "channel": r.get("channel"),
            "status": "sent" if event == "lead_notification_sent" else "failed",
            "provider_message_id": r.get("message_id"),
            "error": r.get("error"),
            "created_at": r.get("created_at"),
        })
    return {"items": items, "total": len(items), "limit": limit}
