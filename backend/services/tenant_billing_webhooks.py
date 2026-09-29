"""Feb-2026 · Business Signup SP2 — tenant-billing Stripe webhook handlers.

Extends the existing Stripe webhook dispatcher
(``services.payments.stripe_charge.handle_webhook_event``) with 4
new events keyed on ``metadata.crm_billing_kind == "tenant_platform_fee"``
so tenant-billing events never collide with the tenant→customer
subscription events already handled.

The router-side ``POST /api/stripe/webhook`` already handles
signature verification, dedup, dead-letter, and retry — all we do
here is a pure-python handler that flips ``tenant.billing_status``
and (for ``invoice.payment_failed``) sends the ``payment_failed``
email that SP1 already localised.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger("tenant_billing_webhooks")


TENANT_BILLING_EVENTS = {
    "customer.subscription.trial_will_end",
    "invoice.payment_succeeded",
    "invoice.payment_failed",
    "customer.subscription.deleted",
}


def _is_tenant_billing(payload_obj: Dict[str, Any]) -> bool:
    """Route only events whose object carries the SP1 metadata sigil."""
    meta = payload_obj.get("metadata") or {}
    kind = (meta.get("crm_billing_kind") or "").strip()
    return kind == "tenant_platform_fee"


def _tenant_id(payload_obj: Dict[str, Any]) -> Optional[str]:
    return (payload_obj.get("metadata") or {}).get("crm_tenant_id")


async def handle_tenant_billing_event(
    event: Dict[str, Any], db: Any,
) -> Dict[str, Any]:
    """Dispatch a Stripe event to the tenant-billing handler.

    Returns ``{"handled": bool, "action": str, "tenant_id": str}``
    for the caller (webhook route + tests). Never raises — a bad
    event is logged as WARN and swallowed so the outer signature
    check + dedup ledger stay authoritative."""
    etype = event.get("type") or ""
    if etype not in TENANT_BILLING_EVENTS:
        return {"handled": False, "action": "skipped_wrong_type",
                 "tenant_id": None}
    obj = ((event.get("data") or {}).get("object") or {})
    if not _is_tenant_billing(obj):
        # Might be a tenant→customer subscription event — let the
        # sibling handler in stripe_charge own it.
        return {"handled": False, "action": "skipped_non_tenant_billing",
                 "tenant_id": None}
    tid = _tenant_id(obj)
    if not tid:
        logger.warning(
            "[tenant-billing-webhook] event=%s missing crm_tenant_id",
            etype,
        )
        return {"handled": False, "action": "missing_tenant_id",
                 "tenant_id": None}
    now_iso = datetime.now(timezone.utc).isoformat()

    if etype == "customer.subscription.trial_will_end":
        # Stripe's 3-day pre-trial-end signal. Purely informational
        # here — the actual reminder email fires from our own
        # tenant_billing_reminders cron at 24h. Log for ops trace.
        logger.info("[tenant-billing-webhook] trial_will_end tenant=%s", tid)
        await db.tenants.update_one(
            {"id": tid},
            {"$set": {"stripe_trial_will_end_seen_at": now_iso}},
        )
        return {"handled": True, "action": "trial_will_end_ack",
                 "tenant_id": tid}

    if etype == "invoice.payment_succeeded":
        await db.tenants.update_one(
            {"id": tid},
            {"$set": {"billing_status": "active",
                        "billing_last_success_at": now_iso}},
        )
        logger.info("[tenant-billing-webhook] payment_succeeded tenant=%s", tid)
        return {"handled": True, "action": "activated",
                 "tenant_id": tid}

    if etype == "invoice.payment_failed":
        await db.tenants.update_one(
            {"id": tid},
            {"$set": {"billing_status": "past_due",
                        "billing_last_failure_at": now_iso}},
        )
        # Best-effort send of the SP1 ``payment_failed`` email.
        try:
            admin = await db.users.find_one({
                "tenant_id": tid, "role": "admin",
            }, {"_id": 0})
            tenant = await db.tenants.find_one({"id": tid}, {"_id": 0})
            if admin and tenant:
                import os
                base = (os.environ.get("FRONTEND_BASE_URL")
                          or "https://app.example.com").rstrip("/")
                from services.i18n_notifications import (
                    resolve_notification_body, resolve_recipient_locale,
                )
                locale = resolve_recipient_locale(
                    tenant=tenant, user=admin, audience="customer",
                )
                body = resolve_notification_body(
                    "payment_failed", locale,
                    context={
                        "admin_name":      admin.get("name") or "there",
                        "business_name":   tenant.get("name") or "your business",
                        "update_card_url": f"{base}/settings/billing",
                    },
                )
                # Phase EMAIL-MIGRATE · Batch 3 · Feb-2026 — DB-first
                # HTML body for English recipients.  Non-English keeps
                # the D5 i18n path (decision (c)).
                subject_out = body["subject"]
                html_out = body["body_html"]
                text_out = body["body_text"]
                if str(locale or "").lower() == "en":
                    try:
                        from services.marketing_template_lookup import (
                            get_template_with_global_fallback,
                        )
                        from services.marketing.merge_tags import render_template
                        tpl = await get_template_with_global_fallback(
                            "tenant_billing_dunning_email",
                            tenant.get("id") or None,
                        )
                        if tpl and tpl.get("body"):
                            admin_name = admin.get("name") or "there"
                            business_name = tenant.get("name") or "your business"
                            ctx = {
                                "tenant": tenant,
                                "customer": {},
                                "admin_name": admin_name,
                                "business_name": business_name,
                                "recipient_name": admin_name,
                                "update_card_link": f"{base}/settings/billing",
                            }
                            rendered_body, _ = render_template(
                                tpl["body"], ctx, missing="empty",
                            )
                            if rendered_body:
                                html_out = rendered_body
                    except Exception as exc:  # noqa: BLE001 — defensive
                        logger.warning(
                            "[tenant-billing-webhook] dunning DB "
                            "template render failed — using D5 i18n "
                            "fallback tenant=%s: %s", tid, exc,
                        )
                from services.email.resend_adapter import send as _send
                await _send(
                    to=admin.get("email"),
                    subject=subject_out,
                    html=html_out,
                    text=text_out,
                    tenant_id=tid,
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "[tenant-billing-webhook] payment_failed email send "
                "failed tenant=%s: %s", tid, exc,
            )
        return {"handled": True, "action": "past_due", "tenant_id": tid}

    if etype == "customer.subscription.deleted":
        await db.tenants.update_one(
            {"id": tid},
            {"$set": {"billing_status": "canceled",
                        "billing_canceled_at": now_iso}},
        )
        logger.info(
            "[tenant-billing-webhook] subscription_deleted tenant=%s", tid,
        )
        return {"handled": True, "action": "canceled",
                 "tenant_id": tid}

    return {"handled": False, "action": "unknown_type",
             "tenant_id": tid}
