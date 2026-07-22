"""Phase 4B · Stripe Live Payments — canonical webhook handler.

Endpoint: ``POST /api/webhooks/stripe``

Contract
========
* Signature is verified via ``stripe.Webhook.construct_event`` using
  ``STRIPE_WEBHOOK_SECRET`` and the raw request bytes (Stripe requires
  exact-byte payload).
* Deduped via ``stripe_events_processed`` — a dedicated collection
  with a 30-day TTL index on ``processed_at`` (created at startup by
  ``db_indexes.ensure_deployment_indexes``). Replay-safe: identical
  ``event.id`` values are processed exactly once.
* Returns 200 fast; heavy work (Resend + Twilio receipts, admin
  fan-out on disputes) runs inside the same request but the mutations
  are additive/idempotent so a slow send never blocks Stripe's retry
  logic beyond the usual 20-second webhook budget.

Event handlers wired
====================
* ``payment_intent.succeeded``        → mark invoice paid, insert
                                        payment record, send Resend +
                                        Twilio receipts (both recorded
                                        in ``marketing_deliveries``
                                        with ``kind='transactional'``).
* ``payment_intent.payment_failed``   → flag ledger + invoice.
* ``charge.refunded``                 → sync refund progress on ledger.
* ``charge.dispute.created``          → notify admins via email + SMS
                                        (respecting
                                        ``sms_escalation_recipients``).
* ``invoice.paid`` / ``invoice.payment_failed`` /
  ``checkout.session.completed`` / ``payment_method.attached`` — best-
  effort routed to the Phase-53 handlers so multi-flow tenants stay
  consistent.

Never echoes secret values in logs.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request

from config import db, logger
from services.stripe_client import get_stripe, is_configured
from utils import new_id, now_iso

router = APIRouter()


def _get(d: Any, k: str, default=None):
    if isinstance(d, dict):
        return d.get(k, default)
    return getattr(d, k, default) or default


async def _load_ledger_row(pi_id: Optional[str], charge_id: Optional[str]) -> Optional[dict]:
    q: dict = {"$or": []}
    if pi_id:
        q["$or"].append({"payment_intent_id": pi_id})
    if charge_id:
        q["$or"].append({"charge_id": charge_id})
    if not q["$or"]:
        return None
    return await db.stripe_payments_live.find_one(q, {"_id": 0})


async def _record_delivery(*, tenant_id: str, kind: str, channel: str,
                            recipient: str, subject: Optional[str],
                            body: str, provider_res: dict,
                            trigger_id: str, customer_id: Optional[str]) -> None:
    """Persist a transactional delivery row shaped like the pre-existing
    marketing_deliveries entries so downstream analytics work unchanged."""
    doc = {
        "id": new_id(),
        "tenant_id": tenant_id,
        "kind": kind,   # 'transactional'
        "trigger_entity": {"kind": "payment", "id": trigger_id},
        "customer_id": customer_id,
        "channel": channel,
        "subject_rendered": subject or "",
        "body_rendered": body,
        "provider": provider_res.get("provider"),
        "provider_status": provider_res.get("provider_status"),
        "provider_response_id": provider_res.get("provider_response_id"),
        "attempts": provider_res.get("attempts") or 0,
        "mock": provider_res.get("provider") == "mock",
        "sent_at": now_iso(),
    }
    if channel == "email":
        doc["recipient_email"] = recipient
    else:
        doc["recipient_phone"] = recipient
    try:
        await db.marketing_deliveries.insert_one(doc)
    except Exception as exc:  # pragma: no cover
        logger.warning("[phase4b] marketing_deliveries insert failed: %s", exc)


async def _send_receipts(*, tenant_id: str, invoice_id: str,
                          payment_intent_id: str, amount_cents: int) -> None:
    """Send Resend email + Twilio SMS receipts on payment_intent.succeeded."""
    inv = await db.quotes.find_one(
        {"id": invoice_id, "tenant_id": tenant_id, "doc_type": "invoice"},
        {"_id": 0},
    )
    if not inv:
        return
    cust = None
    if inv.get("customer_id"):
        cust = await db.customers.find_one(
            {"id": inv["customer_id"], "tenant_id": tenant_id}, {"_id": 0},
        )
    email = (cust or {}).get("email") or inv.get("customer_email") or ""
    phone = (cust or {}).get("phone") or inv.get("customer_phone") or ""
    inv_num = inv.get("invoice_number") or (inv.get("id") or "")[:8].upper()
    amount = amount_cents / 100.0
    subject = f"Payment received — Invoice {inv_num}"
    html = (
        f"<p>Thank you! We received your payment of "
        f"<b>${amount:,.2f}</b> for invoice <b>{inv_num}</b>.</p>"
        f"<p>Payment reference: <code>{payment_intent_id}</code>.</p>"
        f"<p>— Pool &amp; Landscaping of Vistancia</p>"
    )
    sms_body = (
        f"Pool & Landscaping of Vistancia: payment received "
        f"${amount:,.2f} for invoice {inv_num}. Thank you."
    )

    if email:
        try:
            from services.email.resend_adapter import send as _send_email
            res = await _send_email(
                to=email, subject=subject, html=html,
                category="transactional", tenant_id=tenant_id,
                customer_id=inv.get("customer_id"),
                idempotency_key=f"pi-receipt:{payment_intent_id}",
            )
            await _record_delivery(
                tenant_id=tenant_id, kind="transactional",
                channel="email", recipient=email, subject=subject,
                body=html, provider_res=res,
                trigger_id=payment_intent_id,
                customer_id=inv.get("customer_id"),
            )
        except Exception as exc:  # pragma: no cover
            logger.warning("[phase4b] receipt email failed: %s", exc)

    if phone:
        try:
            from services.sms.rc_adapter import send as _send_sms
            res = await _send_sms(
                to=phone, body=sms_body,
                category="transactional", tenant_id=tenant_id,
                customer_id=inv.get("customer_id"),
                idempotency_key=f"pi-receipt:{payment_intent_id}",
            )
            await _record_delivery(
                tenant_id=tenant_id, kind="transactional",
                channel="sms", recipient=phone, subject=None,
                body=sms_body, provider_res=res,
                trigger_id=payment_intent_id,
                customer_id=inv.get("customer_id"),
            )
        except Exception as exc:  # pragma: no cover
            logger.warning("[phase4b] receipt sms failed: %s", exc)


async def _mark_invoice_paid(row: dict, obj: dict) -> None:
    """Idempotent apply of a paid PaymentIntent to the invoice row +
    ledger. No-op if already paid."""
    if not row or row.get("status") in ("paid", "refunded"):
        return
    charge_id = obj.get("latest_charge") or (
        (obj.get("charges", {}) or {}).get("data", [{}])[0].get("id")
        if isinstance(obj.get("charges"), dict) else None
    )
    upd_row = await db.stripe_payments_live.update_one(
        {"id": row["id"], "status": {"$in": ["initiated", "processing"]}},
        {"$set": {
            "status": "paid",
            "charge_id": charge_id,
            "paid_at": now_iso(),
            "updated_at": now_iso(),
        }},
    )
    if upd_row.modified_count == 0:
        return
    if not row.get("invoice_id"):
        return
    inv = await db.quotes.find_one(
        {"id": row["invoice_id"], "tenant_id": row.get("tenant_id")}, {"_id": 0},
    )
    if not inv:
        return
    amt_dollars = int(row.get("amount_cents") or 0) / 100.0
    new_paid = round(float(inv.get("amount_paid") or 0) + amt_dollars, 2)
    total = float(inv.get("total") or 0)
    fully_paid = new_paid + 0.01 >= total
    set_fields: dict = {
        "amount_paid": min(new_paid, total),
        "payment_status": "paid" if fully_paid else "partial",
        "charge_failed": False,
        "charge_error": "",
        "stripe_last_payment_id": row.get("payment_intent_id"),
    }
    if fully_paid:
        set_fields.update({
            "status": "accepted",
            "paid_at": now_iso(),
            "payment_method": "stripe",
        })
    await db.quotes.update_one(
        {"id": inv["id"], "tenant_id": row.get("tenant_id")},
        {"$set": set_fields},
    )


async def _handle_payment_intent_succeeded(event: dict) -> dict:
    obj = _get(_get(event, "data", {}), "object", {}) or {}
    pi_id = obj.get("id")
    row = await _load_ledger_row(pi_id, None)
    tenant_id = None
    invoice_id = None
    amount_cents = int(obj.get("amount_received") or obj.get("amount") or 0)
    if row:
        tenant_id = row.get("tenant_id")
        invoice_id = row.get("invoice_id")
        await _mark_invoice_paid(row, obj)
    else:
        # Fallback: metadata carries the mapping. Useful for
        # PaymentIntents created by legacy flows (or by other Emergent
        # slices) that don't populate the stripe_payments_live ledger.
        md = obj.get("metadata") or {}
        tenant_id = md.get("tenant_id")
        invoice_id = md.get("invoice_id")
    if tenant_id and invoice_id and pi_id:
        await _send_receipts(
            tenant_id=tenant_id, invoice_id=invoice_id,
            payment_intent_id=pi_id, amount_cents=amount_cents,
        )
    # Fan out to the Phase-53 handler so its invoice-paid automation
    # (bell notifications) keeps firing.
    try:
        from routers.stripe_admin import _handle_payment_intent_succeeded as _p53
        await _p53(event)
    except Exception:
        pass
    return {"handled": True}


async def _handle_payment_intent_failed(event: dict) -> dict:
    obj = _get(_get(event, "data", {}), "object", {}) or {}
    pi_id = obj.get("id")
    row = await _load_ledger_row(pi_id, None)
    if row:
        reason = (
            (obj.get("last_payment_error") or {}).get("message")
            if isinstance(obj.get("last_payment_error"), dict) else None
        ) or "payment_failed"
        await db.stripe_payments_live.update_one(
            {"id": row["id"]},
            {"$set": {"status": "failed",
                       "updated_at": now_iso(),
                       "failure_reason": reason[:200]}},
        )
        if row.get("invoice_id"):
            await db.quotes.update_one(
                {"id": row["invoice_id"], "tenant_id": row.get("tenant_id")},
                {"$set": {"charge_failed": True, "charge_error": reason[:200]}},
            )
    try:
        from routers.stripe_admin import _handle_payment_intent_failed as _p53
        await _p53(event)
    except Exception:
        pass
    return {"handled": True}


# ─── Phase 10 · Feb 2026 — Referral safeguard helper ─────────────────
async def _phase10_void_referrals_on_refund(row: dict, *, kind: str) -> None:
    """Called from ``_handle_charge_refunded`` + ``_handle_dispute_created``.

    Emits a ``stripe_events`` marker (so the referral watcher's own
    retro check can see it) AND, for any referral of the affected
    customer that is still ``pending_paid_window``, marks it voided
    with ``voided_reason="refunded"`` or ``"disputed"``.

    Never raises — caller has its own try/except but this fn is
    already defensive."""
    tenant_id = row.get("tenant_id")
    customer_id = row.get("customer_id")
    if not tenant_id or not customer_id:
        return
    reason = "refunded" if kind == "charge.refunded" else "disputed"
    await db.stripe_events.insert_one({
        "id": new_id(),
        "event_id": f"phase10-{new_id()}",
        "tenant_id": tenant_id,
        "customer_id": customer_id,
        "event_type": kind,
        "created_at": now_iso(),
        "source_row_id": row.get("id"),
    })
    now = now_iso()
    await db.referrals.update_many(
        {"tenant_id": tenant_id,
          "$or": [
              {"converted_to_customer_id": customer_id},
              {"referred_customer_id": customer_id},
          ],
          "status": "pending_paid_window"},
        {"$set": {"status": "voided",
                   "voided_reason": reason,
                   "voided_at": now,
                   "updated_at": now}},
    )




async def _handle_charge_refunded(event: dict) -> dict:
    obj = _get(_get(event, "data", {}), "object", {}) or {}
    pi_id = obj.get("payment_intent")
    charge_id = obj.get("id")
    row = await _load_ledger_row(pi_id, charge_id)
    if row:
        refunded = int(obj.get("amount_refunded") or 0)
        total = int(row.get("amount_cents") or 0)
        new_status = (
            "refunded" if refunded >= total and total > 0 else "partially_refunded"
        )
        await db.stripe_payments_live.update_one(
            {"id": row["id"]},
            {"$set": {"refunded_cents": refunded,
                       "charge_id": charge_id,
                       "status": new_status,
                       "updated_at": now_iso()}},
        )
        # Phase 10 · Feb 2026 — void any pending_paid_window referral
        # whose referred customer had this refunded invoice inside
        # the 30-day window. Also log a stripe_events row for the
        # watcher's own retro check.
        try:
            await _phase10_void_referrals_on_refund(row, kind="charge.refunded")
        except Exception as exc:
            logger.warning(f"[phase10] refund void hook failed: {exc}")
    try:
        from routers.stripe_admin import _handle_charge_refunded as _p53
        await _p53(event)
    except Exception:
        pass
    return {"handled": True}


async def _handle_dispute_created(event: dict) -> dict:
    obj = _get(_get(event, "data", {}), "object", {}) or {}
    charge_id = obj.get("charge")
    pi_id = obj.get("payment_intent")
    row = await _load_ledger_row(pi_id, charge_id)
    if not row:
        return {"handled": False}
    reason = obj.get("reason") or "unknown"
    amount = int(obj.get("amount") or 0) / 100.0
    await db.stripe_payments_live.update_one(
        {"id": row["id"]},
        {"$set": {"status": "disputed",
                   "dispute_reason": reason,
                   "updated_at": now_iso()}},
    )
    # Phase 10 · Feb 2026 — same void-inside-window safeguard as refund.
    try:
        await _phase10_void_referrals_on_refund(row, kind="charge.dispute.created")
    except Exception as exc:
        logger.warning(f"[phase10] dispute void hook failed: {exc}")
    tenant_id = row.get("tenant_id")
    if not tenant_id:
        return {"handled": True}
    tenant = await db.tenants.find_one({"id": tenant_id}, {"_id": 0}) or {}
    recips = list(tenant.get("sms_escalation_recipients") or [])
    admins = await db.users.find(
        {"tenant_id": tenant_id, "role": {"$in": ["admin", "super_admin"]}},
        {"_id": 0, "email": 1, "phone": 1, "id": 1},
    ).to_list(50)
    admin_emails = [a.get("email") for a in admins if a.get("email")]
    subject = f"⚠️ Stripe dispute opened — {reason}"
    html = (
        f"<p>A Stripe dispute was opened for <b>${amount:,.2f}</b> "
        f"(charge <code>{charge_id}</code>, reason <b>{reason}</b>).</p>"
        f"<p>Invoice: <code>{row.get('invoice_id') or 'n/a'}</code></p>"
    )
    sms = (
        f"Stripe dispute opened ${amount:,.2f} reason={reason}. "
        f"Check the admin dashboard now."
    )
    for em in admin_emails:
        try:
            from services.email.resend_adapter import send as _send_email
            res = await _send_email(
                to=em, subject=subject, html=html,
                category="transactional", tenant_id=tenant_id,
                idempotency_key=f"dispute:{obj.get('id')}",
            )
            await _record_delivery(
                tenant_id=tenant_id, kind="transactional",
                channel="email", recipient=em, subject=subject,
                body=html, provider_res=res,
                trigger_id=charge_id or (obj.get("id") or ""),
                customer_id=None,
            )
        except Exception as exc:  # pragma: no cover
            logger.warning("[phase4b] dispute email failed: %s", exc)

    for phone in recips:
        try:
            from services.sms.rc_adapter import send as _send_sms
            res = await _send_sms(
                to=phone, body=sms,
                category="transactional", tenant_id=tenant_id,
                idempotency_key=f"dispute:{obj.get('id')}",
            )
            await _record_delivery(
                tenant_id=tenant_id, kind="transactional",
                channel="sms", recipient=phone, subject=None,
                body=sms, provider_res=res,
                trigger_id=charge_id or (obj.get("id") or ""),
                customer_id=None,
            )
        except Exception as exc:  # pragma: no cover
            logger.warning("[phase4b] dispute sms failed: %s", exc)

    return {"handled": True}


async def _handle_delegate_phase53(event: dict) -> dict:
    """Delegate to the pre-existing Phase-53 handler so subscription /
    checkout-session flows continue to work when the Stripe Dashboard
    is configured to send to this canonical endpoint."""
    et = _get(event, "type", "")
    try:
        from routers import stripe_admin
        handler = stripe_admin._STRIPE_EVENT_HANDLERS.get(et)
        if handler:
            await handler(event)
            return {"handled": True, "delegated": True}
    except Exception as exc:
        logger.warning(f"[phase4b] delegate to phase53 failed: {exc}")
    return {"handled": False}


_HANDLERS = {
    "payment_intent.succeeded":       _handle_payment_intent_succeeded,
    "payment_intent.payment_failed":  _handle_payment_intent_failed,
    "charge.refunded":                _handle_charge_refunded,
    "charge.dispute.created":         _handle_dispute_created,
    "invoice.paid":                   _handle_delegate_phase53,
    "invoice.payment_failed":         _handle_delegate_phase53,
    "checkout.session.completed":     _handle_delegate_phase53,
    "payment_method.attached":        _handle_delegate_phase53,
}


@router.post("/webhooks/stripe")
async def stripe_webhook(request: Request):
    secret = os.getenv("STRIPE_WEBHOOK_SECRET") or ""
    if not secret:
        logger.warning("[phase4b] webhook hit but STRIPE_WEBHOOK_SECRET is unset")
        return {"received": True, "reason": "webhook_secret_missing"}

    raw_body = await request.body()
    sig_header = request.headers.get("stripe-signature") or ""
    if not sig_header:
        raise HTTPException(400, "Missing stripe-signature header")
    if not is_configured():
        return {"received": True, "reason": "stripe_not_configured"}
    stripe = get_stripe()
    try:
        event = stripe.Webhook.construct_event(raw_body, sig_header, secret)
    except Exception as e:
        logger.warning(f"[phase4b] webhook signature failed: {type(e).__name__}")
        raise HTTPException(400, "Invalid signature")

    event_id = _get(event, "id", None)
    event_type = _get(event, "type", None)
    if not event_id:
        return {"received": True, "reason": "missing_event_id"}

    # Idempotency guard — Stripe replays events.
    existing = await db.stripe_events_processed.find_one(
        {"event_id": event_id}, {"_id": 0, "event_id": 1},
    )
    if existing:
        return {"received": True, "type": event_type, "idempotent": True}
    # Insert placeholder first so concurrent replays lose the race.
    # ``expires_at`` is a BSON Date honoured by the 30-day TTL index.
    try:
        await db.stripe_events_processed.insert_one({
            "id": new_id(),
            "event_id": event_id,
            "event_type": event_type,
            "processed_at": now_iso(),
            "expires_at": datetime.now(timezone.utc) + timedelta(days=30),
        })
    except Exception:
        # Unique index violation → dupe won the race, be idempotent.
        return {"received": True, "type": event_type, "idempotent": True}

    logger.info(f"[phase4b] webhook accepted: {event_type} ({event_id[:10]}…)")
    handler = _HANDLERS.get(event_type)
    result = {"handled": False}
    if handler:
        try:
            payload = event if isinstance(event, dict) else event.to_dict()
        except Exception:
            payload = event
        try:
            result = await handler(payload) or {"handled": True}
        except Exception as exc:  # pragma: no cover
            logger.warning(
                f"[phase4b] handler {event_type} raised: {type(exc).__name__}"
            )
    return {"received": True, "type": event_type, "handled": bool(result.get("handled"))}
