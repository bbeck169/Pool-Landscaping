"""Task QQ Phase 2 · Feb 2026 — Zapier bridge for Lumino async events.

Lumino has no native webhooks. Zapier bridges the async event stream:
Lumino event → Zap → POST /api/webhooks/lumino/zapier with a shared
secret. This endpoint verifies the secret, persists idempotently, and
dispatches to per-event handlers (stubs for now).

Preview safety: verification + persist still run; downstream state
transitions are TODO(phase2) stubs guarded by logging only.
"""
from __future__ import annotations

import hmac
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request

from config import db

router = APIRouter()
log = logging.getLogger("lumino_zapier_bridge")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _shared_secret() -> str:
    return (os.environ.get("LUMINO_ZAPIER_SHARED_SECRET") or "").strip()


async def _dispatch(event_type: str, data: Dict[str, Any]) -> None:
    """Per-event-type state-transition dispatcher. Phase 2 stubs —
    each branch logs the intent; Phase 3 (post-cutover) fills in
    the actual mutations."""
    if event_type == "subscription.renewed":
        # TODO: mark invoice paid on data.invoice_id, extend subscription.current_period_end.
        log.info("Zapier: subscription.renewed for %s", data.get("subscription_id"))
    elif event_type == "subscription.canceled":
        # TODO: mark subscription.status = canceled, freeze autobilling.
        log.info("Zapier: subscription.canceled for %s", data.get("subscription_id"))
    elif event_type == "payment.refunded":
        # TODO: mark invoice refunded, emit customer notification.
        log.info("Zapier: payment.refunded for %s", data.get("payment_id"))
    elif event_type in ("dispute.opened", "dispute.resolved"):
        # TODO: append to dispute dashboard.
        log.info("Zapier: %s for %s", event_type, data.get("dispute_id"))
    else:
        log.info("Zapier: unhandled event_type=%s", event_type)


@router.post("/webhooks/lumino/zapier",
              operation_id="webhooks.lumino.zapier")
async def receive_zapier_bridge(request: Request):
    expected = _shared_secret()
    if not expected:
        # Fail closed — refuse to accept anything until env is set.
        raise HTTPException(401, "shared secret not configured")
    got = (request.headers.get("x-zapier-shared-secret") or "").strip()
    if not hmac.compare_digest(expected, got):
        log.warning("Zapier bridge auth failed (header mismatch)")
        raise HTTPException(401, "invalid shared secret")
    try:
        body = await request.json()
    except Exception:                                                # noqa: BLE001
        raise HTTPException(400, "invalid json body")
    event_id = body.get("event_id")
    event_type = body.get("event_type")
    if not event_id or not event_type:
        raise HTTPException(400, "event_id and event_type required")
    existing = await db.payment_events.find_one(
        {"lumino_event_id": event_id}, {"_id": 0, "id": 1},
    )
    if existing:
        return {"ok": True, "deduped": True, "event_id": event_id}
    await db.payment_events.insert_one({
        "id": event_id,
        "lumino_event_id": event_id,
        "type": event_type,
        "source": "zapier",
        "occurred_at": body.get("occurred_at") or _now_iso(),
        "received_at": _now_iso(),
        "raw": body,
        "processed": False,
    })
    await _dispatch(event_type, body.get("data") or {})
    return {"ok": True, "deduped": False, "event_id": event_id}
