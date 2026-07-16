"""Phase 52 · RingCentral webhook scaffold.

Rules honoured:
    · `RINGCENTRAL_WEBHOOK_TOKEN` value is NEVER echoed to logs,
      responses, or comments — env-var name only.
    · Raw event payloads are NEVER persisted — only metadata
      (event_type, event_id, received_at, subscription_id,
      raw_payload_size_bytes). Opt-in per-type storage can be added
      later once we know which event families need archival.
    · Subscription-validation flow (`Validation-Token` inbound header)
      is echoed back verbatim so RingCentral can activate the
      subscription — this is mandatory per RC's Webhook v2 spec.
    · No RingCentral SDK is initialised here. No live outbound calls.
      Signature verification for actual event deliveries is left as a
      TODO because the token flavour (webhook validation vs.
      server-API access vs. client secret) is still unclear.
"""
from __future__ import annotations

import os
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from config import db, logger, APP_PUBLIC_URL
from utils import new_id, now_iso, require_admin

router = APIRouter(prefix="/ringcentral", tags=["ringcentral"])


_INDEXES_READY = False


async def _ensure_indexes() -> None:
    global _INDEXES_READY
    if _INDEXES_READY:
        return
    try:
        # Sparse — many rows won't have `event_id` (e.g., duplicate
        # dev-tool replays without an id).
        await db.ringcentral_events.create_index(
            "event_id", unique=True, sparse=True,
        )
        await db.ringcentral_events.create_index("received_at")
        _INDEXES_READY = True
    except Exception as e:
        logger.warning(f"ringcentral_events index create failed: {e}")


def _webhook_url() -> str:
    base = (APP_PUBLIC_URL or "").rstrip("/")
    return f"{base}/api/ringcentral/webhook" if base else "/api/ringcentral/webhook"


# ─── /health · admin-only ─────────────────────────────────────────────
@router.get("/health")
async def ringcentral_health(user: dict = Depends(require_admin)):
    return {
        "configured": bool(os.getenv("RINGCENTRAL_WEBHOOK_TOKEN")),
        "webhook_token_configured": bool(os.getenv("RINGCENTRAL_WEBHOOK_TOKEN")),
        "webhook_url": _webhook_url(),
    }


# ─── /webhook · public (RingCentral hits this URL) ────────────────────
@router.post("/webhook")
async def ringcentral_webhook(request: Request):
    """RC subscription validation + event receiver.

    Validation flow (RC Webhook v2):
        RC sends an initial POST with a `Validation-Token` header.
        We MUST echo it back in the response's `Validation-Token`
        header with a 200 body — otherwise RC will not activate the
        subscription.

    Event flow:
        Subsequent POSTs contain the actual event payload. We only
        persist metadata (event_type, event_id, subscription_id,
        received_at, raw_payload_size_bytes). Signature verification
        against `RINGCENTRAL_WEBHOOK_TOKEN` is left as a TODO until
        the token flavour is confirmed.
    """
    await _ensure_indexes()
    validation_token = request.headers.get("Validation-Token") or request.headers.get("validation-token")
    if validation_token:
        # Never log the token value — only note that a validation
        # request was serviced.
        logger.info("ringcentral webhook validation request handled")
        return Response(
            content='{"received": true, "kind": "validation"}',
            media_type="application/json",
            headers={"Validation-Token": validation_token},
            status_code=200,
        )

    raw_body = await request.body()
    size = len(raw_body or b"")
    # Parse minimally — RC event envelope. Any parse error → 400 so RC
    # doesn't keep retrying malformed payloads forever.
    try:
        import json as _json
        payload: Dict[str, Any] = _json.loads(raw_body or b"{}")
    except Exception:
        raise HTTPException(status_code=400, detail="invalid json body")

    # TODO(phase 53) — verify HMAC signature using
    # RINGCENTRAL_WEBHOOK_TOKEN once the token flavour is confirmed.
    # For now we accept + persist metadata only.
    event_type = str(payload.get("event") or payload.get("eventType") or "")
    event_id = str(payload.get("uuid") or payload.get("eventId") or payload.get("id") or "") or None
    subscription_id = str(payload.get("subscriptionId") or "") or None

    doc = {
        "id": new_id(),
        "tenant_id": None,  # populated once we resolve mapping
        "event_type": event_type or "unknown",
        "event_id": event_id,
        "subscription_id": subscription_id,
        "received_at": now_iso(),
        "processed": False,
        "raw_payload_size_bytes": size,
    }
    try:
        await db.ringcentral_events.insert_one(doc)
    except Exception as e:
        # Duplicate key on event_id = replay — safe to skip.
        if "duplicate key" in str(e).lower() or "E11000" in str(e):
            logger.info(f"ringcentral webhook duplicate event skipped: {event_type}")
            return {"received": True, "duplicate": True, "type": event_type}
        logger.warning(f"ringcentral event insert failed: {type(e).__name__}")

    # Only log the type / size — never the payload contents.
    logger.info(f"ringcentral webhook event received: type={event_type} size={size}b")
    # Preserve legacy behavior (Phase 52 migration from ai_ops.py) for
    # telephony events — create a call_log and, when the caller is
    # unknown, a lead. Only field-level data is persisted; no raw
    # payload is stored in `ringcentral_events`.
    try:
        await _maybe_create_call_log_and_lead(payload)
    except Exception as e:
        logger.warning(f"ringcentral call_log side-effect failed: {type(e).__name__}")
    return {"received": True, "type": event_type}


async def _maybe_create_call_log_and_lead(body: Dict[str, Any]) -> None:
    """Migrated from the legacy `ai_ops.ringcentral_webhook`.

    Accepts either the nested (`{"call": {...}}`) or top-level RC
    shape. Persists a sanitized `call_logs` row and, when the caller
    is unknown, an inbound lead. Does NOT store the raw envelope."""
    call = body.get("call") if isinstance(body.get("call"), dict) else None
    if call:
        src = call
        from_raw = src.get("from"); to_raw = src.get("to")
        from_number = from_raw if isinstance(from_raw, str) else (from_raw or {}).get("phoneNumber", "")
        to_number = to_raw if isinstance(to_raw, str) else (to_raw or {}).get("phoneNumber", "")
        duration = src.get("duration") or 0
        recording_url = (
            src.get("recording_url")
            or ((src.get("recording") or {}).get("contentUri") if isinstance(src.get("recording"), dict) else None)
        )
        direction = src.get("direction")
    else:
        from_number = (body.get("from") or {}).get("phoneNumber") or body.get("from_number") or ""
        to_number = (body.get("to") or {}).get("phoneNumber") or body.get("to_number") or ""
        duration = body.get("duration") or 0
        recording_url = (body.get("recording") or {}).get("contentUri") or body.get("recording_url")
        direction = body.get("direction")

    # No-op for non-call events (subscription-status, presence, etc.)
    if not from_number and not to_number:
        return

    match = None
    if from_number:
        match = (await db.customers.find_one({"phones": from_number}, {"_id": 0})
                  or await db.customers.find_one({"phones": {"$regex": from_number[-7:]}}, {"_id": 0}))
    await db.call_logs.insert_one({
        "id": new_id(),
        "from_number": from_number, "to_number": to_number,
        "duration": duration, "recording_url": recording_url,
        "direction": direction,
        "customer_id": (match or {}).get("id"),
        "customer_name": (match or {}).get("name"),
        "created_at": now_iso(),
        # NOTE: raw payload deliberately NOT persisted per Phase 52
        # rules. If a future feature needs it, add an opt-in flag
        # scoped by event_type.
    })
    if not match and from_number:
        await db.leads.insert_one({
            "id": new_id(), "source": "ringcentral-inbound",
            "phone": from_number,
            "name": f"Unknown caller {from_number[-4:]}",
            "created_at": now_iso(), "status": "new",
        })
