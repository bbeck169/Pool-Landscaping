"""Feb 2026 · Slice N — Resend webhooks + dev smoke test.

Endpoints:

* ``POST /api/webhooks/resend`` — public receiver for Resend delivery
  events (delivered / bounced / complained).  Signature is verified
  against ``RESEND_WEBHOOK_SECRET`` when set (svix-style HMAC).  If the
  secret is missing all events are rejected with 401 — safer default
  than blindly trusting unsigned callbacks.

* ``POST /api/dev/email-smoke-test`` — admin-only, gated on
  ``APP_ENV != production``.  Fires a canned test email through the
  adapter so ops can confirm the DNS domain + API key are live.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from config import db, logger
from utils import get_current_user, new_id, now_iso, require_admin
from routers.tenants import get_current_tenant

router = APIRouter()


# ══════════════════════════════════════════════════════════════════
# Webhook receiver
# ══════════════════════════════════════════════════════════════════
def _verify_svix_signature(body: bytes, headers: Dict[str, str],
                            secret: str) -> bool:
    """Resend uses svix-style signed headers:
        svix-id            : opaque delivery id
        svix-timestamp     : unix seconds
        svix-signature     : "v1,<b64-hmac-sha256>[ v1,<other>...]"

    The signing input is ``id.timestamp.body``.  Any of the versions
    listed after "v1," may match — we accept if any one matches to
    survive key rotation windows."""
    sig_header = headers.get("svix-signature") or headers.get("Svix-Signature")
    sid = headers.get("svix-id") or headers.get("Svix-Id")
    ts = headers.get("svix-timestamp") or headers.get("Svix-Timestamp")
    if not (sig_header and sid and ts):
        return False
    try:
        ts_int = int(ts)
    except ValueError:
        return False
    if abs(time.time() - ts_int) > 60 * 5:  # 5-minute clock skew
        return False
    # Secret arrives as "whsec_..." — strip prefix + b64-decode per svix.
    key_str = secret[6:] if secret.startswith("whsec_") else secret
    import base64
    try:
        key = base64.b64decode(key_str)
    except Exception:
        return False
    to_sign = f"{sid}.{ts}.".encode() + body
    expected = base64.b64encode(
        hmac.new(key, to_sign, hashlib.sha256).digest(),
    ).decode()
    for part in sig_header.split(" "):
        if not part.startswith("v1,"):
            continue
        candidate = part.split(",", 1)[1]
        if hmac.compare_digest(candidate, expected):
            return True
    return False


@router.post("/webhooks/resend")
async def resend_webhook(request: Request) -> Dict[str, Any]:
    """Receive delivery status events + auto-suppress bounces/complaints.

    Payload envelope (from Resend):
    ``{"type": "email.bounced", "data": {"email_id": "...", "to": [...] , ...}}``
    """
    body = await request.body()
    secret = os.environ.get("RESEND_WEBHOOK_SECRET", "").strip()
    if not secret:
        # Explicit reject — we don't want unsigned events auto-suppressing
        # customers in production.  Configure the secret first.
        raise HTTPException(401, "Webhook secret not configured")
    if not _verify_svix_signature(body, dict(request.headers), secret):
        raise HTTPException(401, "Invalid webhook signature")

    try:
        payload = json.loads(body.decode() or "{}")
    except json.JSONDecodeError:
        raise HTTPException(400, "Invalid JSON payload")

    event_type = payload.get("type") or ""
    data = payload.get("data") or {}
    email_id = data.get("email_id") or data.get("id")
    to_list = data.get("to") or []
    to_addr = (to_list[0] if to_list else "").strip().lower() or None

    # Persist a raw event log for audit + replay.
    event_row = {
        "id": new_id(),
        "type": event_type,
        "email_id": email_id,
        "to": to_addr,
        "raw": data,
        "created_at": now_iso(),
    }
    await db.resend_webhook_events.insert_one(event_row)

    # Update the delivery row (best-effort match by provider_response_id).
    if email_id:
        # Map event → (provider_status label, per-event timestamp field).
        # Feb-2026 · Slice O — added distinct timestamp columns so the
        # communications-log detail sheet can render a full timeline
        # (created → sent → delivered → opened → clicked / bounced),
        # not just the most-recent transition. Also keep
        # ``provider_last_event_at`` as the wall-clock cursor for
        # sorting the most-recent event across all types.
        _MAP = {
            "email.delivered":  ("delivered",  "delivered_at"),
            "email.bounced":    ("bounced",    "bounced_at"),
            "email.complained": ("complained", "complained_at"),
            "email.opened":     ("opened",     "opened_at"),
            "email.clicked":    ("clicked",    "clicked_at"),
        }
        entry = _MAP.get(event_type)
        if entry:
            upd_status, ts_field = entry
            set_doc = {
                "provider_status": upd_status,
                "provider_last_event_at": now_iso(),
                ts_field: now_iso(),
            }
            await db.marketing_deliveries.update_one(
                {"provider_response_id": email_id},
                {"$set": set_doc},
            )

    # Auto-suppress bounces + complaints so we never send to them again.
    # We add a global-tenant "all" suppression when we can locate the
    # tenant via the delivery row; otherwise skip.
    if event_type in ("email.bounced", "email.complained") and to_addr:
        delivery = await db.marketing_deliveries.find_one(
            {"provider_response_id": email_id},
            {"_id": 0, "tenant_id": 1, "customer_id": 1},
        )
        if delivery and delivery.get("tenant_id"):
            reason = "bounce" if event_type == "email.bounced" else "complaint"
            existing = await db.marketing_suppressions.find_one({
                "tenant_id": delivery["tenant_id"], "channel": "email",
                "address": to_addr, "category": "all",
                "deleted_at": None,
            })
            if not existing:
                await db.marketing_suppressions.insert_one({
                    "id": new_id(),
                    "tenant_id": delivery["tenant_id"],
                    "channel": "email",
                    "address": to_addr,
                    "reason": reason,
                    "category": "all",
                    "customer_id": delivery.get("customer_id"),
                    "created_at": now_iso(),
                    "created_by": "resend_webhook",
                    "deleted_at": None,
                })
                logger.info(
                    "[resend-webhook] auto-suppressed %s for tenant=%s reason=%s",
                    to_addr, delivery["tenant_id"], reason,
                )

    return {"ok": True}


# ══════════════════════════════════════════════════════════════════
# Dev smoke-test endpoint
# ══════════════════════════════════════════════════════════════════
@router.post("/dev/email-smoke-test")
async def email_smoke_test(
    to: str = Query(..., description="Recipient (must be a verified Resend address in test mode)"),
    subject: Optional[str] = Query(None),
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    """Fire a canned email through the adapter to confirm live wiring.
    Disabled when ``APP_ENV=production``."""
    if os.environ.get("APP_ENV", "").lower() == "production":
        raise HTTPException(403, "Smoke test disabled in production")
    from services.email.resend_adapter import send as _resend_send
    subj = subject or "Slice N · Resend smoke test"
    html = (
        "<h2>Slice N smoke test</h2>"
        "<p>If you can read this, the Resend adapter is live.</p>"
        f"<p><small>Tenant: {tenant.get('name') or tenant['id']}<br>"
        f"Actor: {user.get('email')}</small></p>"
    )
    res = await _resend_send(
        to=to,
        subject=subj,
        html=html,
        category="transactional",  # bypass suppression
        tenant_id=tenant["id"],
    )
    return {"result": res}


# ══════════════════════════════════════════════════════════════════
# Slice S · Twilio SMS smoke-test + status callback
# ══════════════════════════════════════════════════════════════════
@router.post("/dev/sms-smoke-test")
async def sms_smoke_test(
    to: str = Query(..., description="Recipient phone (E.164 or human-formatted)"),
    body: Optional[str] = Query(None),
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    """Fire a canned SMS through the Twilio adapter for wiring checks.
    Disabled when ``APP_ENV=production``.  Uses category=transactional
    so no ``Reply STOP`` suffix is auto-appended."""
    if os.environ.get("APP_ENV", "").lower() == "production":
        raise HTTPException(403, "Smoke test disabled in production")
    from services.sms.rc_adapter import send as _sms_send
    text = body or (
        f"Slice S smoke test from {tenant.get('name') or tenant['id']}. "
        "Twilio adapter live."
    )
    res = await _sms_send(
        to=to, body=text,
        category="transactional", tenant_id=tenant["id"],
    )
    return {"result": res}


@router.post("/webhooks/twilio/status")
@router.post("/webhooks/twilio/inbound")
async def twilio_deprecated_webhook(request: Request) -> Dict[str, Any]:
    """Phase 7B · Feb 2026 — Twilio has been fully retired in favor of
    RingCentral. These endpoints remain registered so any stale
    provider-side callback URLs at Twilio return a clear 410 Gone
    instead of a 404, but they do NOT process events. Removes silently
    once the last stale Twilio webhook URL is scrubbed from any
    third-party dashboards. Inbound STOP handling now lives on the RC
    message-store webhook (see routers/ringcentral.py)."""
    logger.info(
        "[twilio-webhook] deprecated endpoint hit — path=%s content_type=%s",
        request.url.path, request.headers.get("content-type", ""),
    )
    raise HTTPException(status_code=410,
                          detail="Twilio SMS retired; RC is the SMS provider")
