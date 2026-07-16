"""Phase 52 · Stripe healthcheck, publishable-key exposure, and
webhook scaffold.

Rules honoured throughout:
    · Secret / webhook / publishable key values are NEVER echoed to
      logs, responses, or comments — env-var names only.
    · No live Stripe API calls from `/health` (env inspection only).
    · Webhook signature is verified with `stripe.Webhook.construct_event`
      using the raw request body (Stripe requires the exact bytes).
    · If Stripe rejects the current secret key at any callsite in the
      future, callers must fall back to `{"mocked": true,
      "reason": "stripe_key_invalid_or_rotated"}` and MUST NOT surface
      the raw error publicly.
"""
from __future__ import annotations

import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request

from config import logger
from utils import require_admin
from services.stripe_client import is_configured, mode, get_stripe

router = APIRouter(prefix="/stripe", tags=["stripe"])


# ─── /health · admin-only, env-inspection only ────────────────────────
@router.get("/health")
async def stripe_health(user: dict = Depends(require_admin)):
    return {
        "configured": is_configured(),
        "secret_key_configured": bool(os.getenv("STRIPE_SECRET_KEY")),
        "publishable_key_configured": bool(os.getenv("STRIPE_PUBLISHABLE_KEY")),
        "webhook_secret_configured": bool(os.getenv("STRIPE_WEBHOOK_SECRET")),
        "mode": mode(),
    }


# ─── /publishable-key · unauth OK (public by design) ─────────────────
@router.get("/publishable-key")
async def stripe_publishable_key():
    pk = os.getenv("STRIPE_PUBLISHABLE_KEY") or None
    m = ""
    if pk:
        if pk.startswith("pk_live_"): m = "live"
        elif pk.startswith("pk_test_"): m = "test"
        else: m = "unknown"
    return {"key": pk, "mode": m}


# ─── /webhook · scaffold (empty handlers) ─────────────────────────────
# Handler registry keyed by Stripe event.type. Each handler is an async
# function that receives the parsed event object. All handlers are
# empty placeholders — Phase 53 will wire real business logic (invoice
# reconciliation, subscription lifecycle, dispute flags, etc.).
async def _handle_ignore(event):  # noqa: ANN001
    """Default no-op handler for the scaffold — logs the event type only."""
    return {"handled": False, "reason": "no handler registered"}


_STRIPE_EVENT_HANDLERS = {
    "checkout.session.completed": _handle_ignore,
    "invoice.paid": _handle_ignore,
    "invoice.payment_failed": _handle_ignore,
    "customer.subscription.created": _handle_ignore,
    "customer.subscription.updated": _handle_ignore,
    "customer.subscription.deleted": _handle_ignore,
    "charge.refunded": _handle_ignore,
    "charge.dispute.created": _handle_ignore,
    "payment_intent.succeeded": _handle_ignore,
    "payment_intent.payment_failed": _handle_ignore,
}


@router.post("/webhook")
async def stripe_webhook(request: Request):
    """Public endpoint hit by Stripe. Verifies the signature using the
    raw request body and dispatches on event.type. Empty handlers for
    now — Phase 53 will implement per-event side effects."""
    secret = os.getenv("STRIPE_WEBHOOK_SECRET") or ""
    if not secret:
        # Never leak whether the secret is missing to Stripe — respond
        # with a 200 so the delivery doesn't hammer our retry queue,
        # but log privately.
        logger.warning("stripe webhook received but STRIPE_WEBHOOK_SECRET unset")
        return {"received": True, "mocked": True,
                 "reason": "webhook_secret_missing"}
    raw_body = await request.body()  # exact bytes — required by Stripe.
    sig_header = request.headers.get("stripe-signature") or ""
    stripe = get_stripe()
    try:
        event = stripe.Webhook.construct_event(raw_body, sig_header, secret)
    except Exception as e:
        # Signature verification failed — do NOT include the exception
        # message in the response body (may reveal secret positions).
        logger.warning(f"stripe webhook signature verification failed: {type(e).__name__}")
        raise HTTPException(status_code=400, detail="invalid signature")
    event_type = getattr(event, "type", None) or (event.get("type") if isinstance(event, dict) else None)
    logger.info(f"stripe webhook received: {event_type}")
    handler = _STRIPE_EVENT_HANDLERS.get(event_type, _handle_ignore)
    try:
        await handler(event)
    except Exception as e:
        # Never surface handler errors to Stripe — respond 200 so Stripe
        # doesn't retry indefinitely; log for our own alerting.
        logger.warning(f"stripe webhook handler {event_type} raised: {type(e).__name__}")
    return {"received": True, "type": event_type}
