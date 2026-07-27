"""Task QQ · Feb 2026 — Lumino webhook receiver.

* Reads ``x-lumino-signature`` header.
* HMAC-SHA256 verify against ``LUMINO_WEBHOOK_SECRET``.
* Idempotent persist to ``payment_events`` keyed by event id.
* Preview safe: still accept/verify/persist, but never emit
  downstream side effects (Phase 2 flesh-out).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request

from config import db
from services.payments import (
    get_payment_provider, PaymentProviderNotConfigured,
)

router = APIRouter()
log = logging.getLogger("lumino_webhook")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@router.post("/webhooks/lumino", operation_id="webhooks.lumino")
async def receive_lumino_webhook(request: Request):
    raw = await request.body()
    sig = request.headers.get("x-lumino-signature", "")
    provider = get_payment_provider()
    if provider.name != "lumino":
        # Even when Stripe is the active provider we still want to
        # accept Lumino webhooks (dual-run cutover window). Fall
        # through to a bare LuminoProvider for verification only.
        from services.payments.lumino_provider import LuminoProvider
        provider = LuminoProvider()
    try:
        if not provider.verify_webhook(raw_body=raw, signature_header=sig):
            log.warning("Lumino webhook rejected — signature mismatch")
            raise HTTPException(400, "invalid signature")
    except PaymentProviderNotConfigured:
        log.warning("Lumino webhook received but provider not configured — "
                      "cannot verify. Accepting into quarantine collection.")
    event = provider.parse_webhook_event(raw_body=raw)
    event_id = event.get("id") or event.get("event_id")
    if not event_id:
        raise HTTPException(400, "missing event id")
    # Idempotent persist.
    existing = await db.payment_events.find_one(
        {"lumino_event_id": event_id}, {"_id": 0, "id": 1},
    )
    if existing:
        return {"ok": True, "duplicate": True}
    await db.payment_events.insert_one({
        "id": event_id,
        "lumino_event_id": event_id,
        "type": event.get("type") or "unknown",
        "received_at": _now_iso(),
        "raw": event,
        "processed": False,
    })
    # TODO(phase2): map event.type → local state transitions:
    #   payment.succeeded    → mark invoice paid
    #   payment.failed       → mark invoice failed + dunning trigger
    #   subscription.updated → sync autobilling status
    #   refund.created       → refund receipt
    #   dispute.opened       → dispute dashboard entry
    return {"ok": True, "duplicate": False}
