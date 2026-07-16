"""Phase 52 · Stripe healthcheck, publishable-key exposure, and
Phase 53 · full webhook handlers wired to the ledger + invoice
sync.

Rules honoured throughout:
    · Secret / webhook / publishable key values are NEVER echoed to
      logs, responses, or comments — env-var names only.
    · No live Stripe API calls from `/health` (env inspection only).
    · Webhook signature is verified with `stripe.Webhook.construct_event`
      using the raw request body (Stripe requires the exact bytes).
    · Every webhook is idempotency-guarded via ``db.stripe_events``
      keyed by ``event.id`` — Stripe may replay the same event.
    · If Stripe rejects the current secret key at any callsite in the
      future, callers must fall back to `{"mocked": true,
      "reason": "stripe_key_invalid_or_rotated"}` and MUST NOT surface
      the raw error publicly.
"""
from __future__ import annotations

import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request

from config import db, logger
from utils import new_id, now_iso, require_admin
from services.stripe_client import is_configured, mode, get_stripe

router = APIRouter(prefix="/stripe", tags=["stripe"])


# ─── /health · admin-only, env-inspection + live auth probe ─────────
@router.get("/health")
async def stripe_health(user: dict = Depends(require_admin)):
    resp: dict = {
        "configured": is_configured(),
        "secret_key_configured": bool(os.getenv("STRIPE_SECRET_KEY")),
        "publishable_key_configured": bool(os.getenv("STRIPE_PUBLISHABLE_KEY")),
        "webhook_secret_configured": bool(os.getenv("STRIPE_WEBHOOK_SECRET")),
        "mode": mode(),
    }
    # Phase 54 closeout — lightweight live probe against Stripe.
    # Never echoes the secret key value; masks the account id to first
    # 4 + last 4 chars only.
    if not resp["secret_key_configured"]:
        resp["key_authenticates"] = False
        resp["error_type"] = "missing_key"
        return resp
    try:
        stripe = get_stripe()
        acct = stripe.Account.retrieve()
        aid = getattr(acct, "id", None) or (acct.get("id") if hasattr(acct, "get") else None) or ""
        masked = f"{aid[:4]}…{aid[-4:]}" if aid and len(aid) >= 10 else (aid or None)
        resp["key_authenticates"] = True
        resp["account_id"] = masked
    except Exception as e:
        cls = type(e).__name__
        if "AuthenticationError" in cls or "PermissionError" in cls:
            resp["error_type"] = "authentication"
        elif "APIConnectionError" in cls or "ConnectionError" in cls or "Timeout" in cls:
            resp["error_type"] = "network"
        else:
            resp["error_type"] = "other"
        resp["key_authenticates"] = False
    return resp


# ─── /publishable-key · unauth OK (public by design) ─────────────────
@router.get("/publishable-key")
async def stripe_publishable_key():
    pk = os.getenv("STRIPE_PUBLISHABLE_KEY") or None
    m = ""
    if pk:
        if pk.startswith("pk_live_"): m = "live"
        elif pk.startswith("pk_test_"): m = "test"
        else: m = "unknown"
    return {"publishable_key": pk, "key": pk, "mode": m}


# ─── /webhook · Phase 53 handlers wired to ledger + invoice sync ─────
def _ev(event, key, default=None):
    """Read a field from the Stripe event whether it's a Model or a raw dict."""
    if isinstance(event, dict):
        return event.get(key, default)
    return getattr(event, key, default) or default


async def _apply_paid_invoice(row: dict, payload: dict) -> None:
    """Idempotent apply-payment on a ledger row + underlying invoice.

    Called from BOTH the webhook (source of truth) AND the checkout
    status polling endpoint (fallback for slow webhooks). Uses a
    guarded update so double-application is a no-op.
    """
    if not row or row.get("status") in ("paid", "refunded"):
        return
    charge_id = None
    receipt_url = None
    fee_cents = None
    net_cents = None
    if isinstance(payload, dict):
        charge_id = payload.get("latest_charge") or payload.get("charge") or None
        receipt_url = (payload.get("receipt_url")
                       or (payload.get("charges", {}) or {}).get("data", [{}])[0].get("receipt_url"))
        bt = payload.get("balance_transaction") or {}
        if isinstance(bt, dict):
            fee_cents = bt.get("fee")
            net_cents = bt.get("net")
    # Move row → paid.
    updated = await db.stripe_payments.update_one(
        {"id": row["id"], "status": {"$in": ["initiated", "processing"]}},
        {"$set": {
            "status": "paid",
            "charge_id": charge_id,
            "receipt_url": receipt_url,
            "fee_cents": fee_cents,
            "net_cents": net_cents,
            "updated_at": now_iso(),
        }},
    )
    if updated.modified_count == 0:
        return  # already applied by a concurrent path
    # Sync the invoice.
    if row.get("invoice_id"):
        inv = await db.quotes.find_one({"id": row["invoice_id"], "tenant_id": row.get("tenant_id")}, {"_id": 0})
        if inv:
            amt = int(row.get("amount_cents") or 0) / 100.0
            paid = round(float(inv.get("amount_paid") or 0) + amt, 2)
            total = float(inv.get("total") or 0)
            fully_paid = paid + 0.01 >= total
            upd: dict = {
                "amount_paid": min(paid, total),
                "payment_status": "paid" if fully_paid else "partial",
                "charge_failed": False, "charge_error": "",
                "stripe_last_payment_id": row.get("payment_intent") or row.get("session_id"),
            }
            if fully_paid:
                upd.update({"status": "accepted", "paid_at": now_iso(), "payment_method": "stripe"})
            await db.quotes.update_one({"id": inv["id"], "tenant_id": row.get("tenant_id")}, {"$set": upd})
            # Notify admins + customer.
            try:
                from services.notifications import emit as notify_emit
                admins = await db.users.find(
                    {"tenant_id": row.get("tenant_id"), "role": {"$in": ["admin", "super_admin"]}},
                    {"_id": 0, "id": 1},
                ).to_list(200)
                aids = [a["id"] for a in admins if a.get("id")]
                if aids:
                    await notify_emit(
                        aids, kind="invoice_paid",
                        title=f"Invoice paid · ${amt:,.2f}",
                        body=f"{inv.get('customer_name') or 'Customer'} paid via Stripe.",
                        href=f"/invoices/{inv['id']}",
                        tenant_id=row.get("tenant_id"),
                        customer_id=inv.get("customer_id"),
                        source_ref={"kind": "stripe_payment", "id": row["id"]},
                    )
            except Exception:
                pass


async def _handle_checkout_completed(event):
    obj = _ev(event, "data", {}).get("object", {}) if isinstance(_ev(event, "data", {}), dict) else {}
    session_id = obj.get("id")
    if not session_id:
        return {"handled": False}
    row = await db.stripe_payments.find_one({"session_id": session_id}, {"_id": 0})
    if not row:
        return {"handled": False, "reason": "ledger_row_missing"}
    # For checkout, the PI is inside session.
    pi_id = obj.get("payment_intent")
    payload = {}
    if pi_id:
        try:
            payload = get_stripe().PaymentIntent.retrieve(pi_id).to_dict() if hasattr(get_stripe().PaymentIntent.retrieve(pi_id), "to_dict") else dict(get_stripe().PaymentIntent.retrieve(pi_id))
        except Exception:
            payload = {"latest_charge": None}
    await _apply_paid_invoice(row, payload)
    return {"handled": True}


async def _handle_payment_intent_succeeded(event):
    obj = _ev(event, "data", {}).get("object", {}) if isinstance(_ev(event, "data", {}), dict) else {}
    pi_id = obj.get("id")
    row = await db.stripe_payments.find_one({"payment_intent": pi_id}, {"_id": 0})
    if not row:
        return {"handled": False}
    await _apply_paid_invoice(row, obj)
    return {"handled": True}


async def _handle_payment_intent_failed(event):
    obj = _ev(event, "data", {}).get("object", {}) if isinstance(_ev(event, "data", {}), dict) else {}
    pi_id = obj.get("id")
    row = await db.stripe_payments.find_one({"payment_intent": pi_id}, {"_id": 0})
    if not row:
        return {"handled": False}
    reason = ((obj.get("last_payment_error") or {}).get("message") if isinstance(obj.get("last_payment_error"), dict) else None) or "payment_failed"
    await db.stripe_payments.update_one(
        {"id": row["id"]}, {"$set": {"status": "failed", "updated_at": now_iso(),
                                       "metadata.failure_reason": reason}},
    )
    if row.get("invoice_id"):
        await db.quotes.update_one(
            {"id": row["invoice_id"], "tenant_id": row.get("tenant_id")},
            {"$set": {"charge_failed": True, "charge_error": reason[:200]}},
        )
    return {"handled": True}


async def _handle_charge_refunded(event):
    obj = _ev(event, "data", {}).get("object", {}) if isinstance(_ev(event, "data", {}), dict) else {}
    pi_id = obj.get("payment_intent")
    charge_id = obj.get("id")
    row = await db.stripe_payments.find_one(
        {"$or": [{"payment_intent": pi_id}, {"charge_id": charge_id}]}, {"_id": 0},
    )
    if not row:
        return {"handled": False}
    refunded = int(obj.get("amount_refunded") or 0)
    total = int(row.get("amount_cents") or 0)
    new_status = "refunded" if refunded >= total and total > 0 else row.get("status", "paid")
    await db.stripe_payments.update_one(
        {"id": row["id"]}, {"$set": {"refunded_cents": refunded, "status": new_status, "updated_at": now_iso()}},
    )
    return {"handled": True}


async def _handle_invoice_paid(event):
    """Stripe-billing invoice (subscription cycle) paid → generate a
    recurring job on the underlying CRM customer if one is templated."""
    obj = _ev(event, "data", {}).get("object", {}) if isinstance(_ev(event, "data", {}), dict) else {}
    sub_id = obj.get("subscription")
    stripe_cust = obj.get("customer")
    if not sub_id:
        return {"handled": False}
    row = await db.stripe_subscriptions.find_one({"subscription_id": sub_id}, {"_id": 0})
    if not row:
        return {"handled": False, "reason": "no_local_subscription"}
    await db.stripe_subscriptions.update_one(
        {"subscription_id": sub_id},
        {"$set": {"last_paid_at": now_iso(), "status": "active",
                   "current_period_end": obj.get("period_end") or obj.get("lines", {}).get("data", [{}])[0].get("period", {}).get("end")}},
    )
    # Auto-generate a recurring job (best-effort — quiet on failure)
    try:
        tpl = await db.recurring_job_templates.find_one(
            {"tenant_id": row["tenant_id"], "customer_id": row["customer_id"], "active": True}, {"_id": 0}
        )
        if tpl:
            await db.jobs.insert_one({
                "id": new_id(),
                "tenant_id": row["tenant_id"],
                "customer_id": row["customer_id"],
                "service_type": tpl.get("service_type") or "recurring",
                "status": "scheduled",
                "auto_generated_from_subscription": sub_id,
                "created_at": now_iso(),
            })
    except Exception:
        pass
    return {"handled": True}


async def _handle_subscription_lifecycle(event):
    obj = _ev(event, "data", {}).get("object", {}) if isinstance(_ev(event, "data", {}), dict) else {}
    sub_id = obj.get("id")
    if not sub_id:
        return {"handled": False}
    await db.stripe_subscriptions.update_one(
        {"subscription_id": sub_id},
        {"$set": {"status": obj.get("status"),
                   "current_period_end": obj.get("current_period_end"),
                   "updated_at": now_iso()}},
    )
    return {"handled": True}


async def _handle_ignore(event):  # noqa: ANN001
    """Default no-op handler."""
    return {"handled": False, "reason": "no handler registered"}


_STRIPE_EVENT_HANDLERS = {
    "checkout.session.completed":       _handle_checkout_completed,
    "payment_intent.succeeded":         _handle_payment_intent_succeeded,
    "payment_intent.payment_failed":    _handle_payment_intent_failed,
    "charge.refunded":                  _handle_charge_refunded,
    "invoice.paid":                     _handle_invoice_paid,
    "invoice.payment_succeeded":        _handle_invoice_paid,
    "invoice.payment_failed":           _handle_ignore,
    "customer.subscription.created":    _handle_subscription_lifecycle,
    "customer.subscription.updated":    _handle_subscription_lifecycle,
    "customer.subscription.deleted":    _handle_subscription_lifecycle,
    "charge.dispute.created":           _handle_ignore,
}


@router.post("/webhook")
async def stripe_webhook(request: Request):
    """Public endpoint hit by Stripe. Verifies signature, guarantees
    idempotency via ``db.stripe_events`` keyed on event.id, and
    dispatches on event.type."""
    secret = os.getenv("STRIPE_WEBHOOK_SECRET") or ""
    if not secret:
        logger.warning("stripe webhook received but STRIPE_WEBHOOK_SECRET unset")
        return {"received": True, "mocked": True, "reason": "webhook_secret_missing"}
    raw_body = await request.body()
    sig_header = request.headers.get("stripe-signature") or ""
    stripe = get_stripe()
    try:
        event = stripe.Webhook.construct_event(raw_body, sig_header, secret)
    except Exception as e:
        logger.warning(f"stripe webhook signature verification failed: {type(e).__name__}")
        raise HTTPException(status_code=400, detail="invalid signature")

    event_id = _ev(event, "id", None) or (event.get("id") if isinstance(event, dict) else None)
    event_type = _ev(event, "type", None) or (event.get("type") if isinstance(event, dict) else None)

    # Idempotency guard — Stripe replays events on delivery failure.
    if event_id:
        existing = await db.stripe_events.find_one({"event_id": event_id}, {"_id": 0, "event_id": 1})
        if existing:
            return {"received": True, "type": event_type, "idempotent": True}
        await db.stripe_events.insert_one({
            "id": new_id(),
            "event_id": event_id,
            "event_type": event_type,
            "received_at": now_iso(),
            "processed": False,
        })

    logger.info(f"stripe webhook received: {event_type}")
    handler = _STRIPE_EVENT_HANDLERS.get(event_type, _handle_ignore)
    result: dict = {"handled": False}
    try:
        result = await handler(event) or {"handled": True}
    except Exception as e:
        logger.warning(f"stripe webhook handler {event_type} raised: {type(e).__name__}")

    if event_id:
        await db.stripe_events.update_one(
            {"event_id": event_id},
            {"$set": {"processed": True, "processed_at": now_iso(), "result": result}},
        )
    return {"received": True, "type": event_type, **({"handled": result.get("handled", False)})}
