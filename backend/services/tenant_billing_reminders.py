"""Feb-2026 · Business Signup SP1 — trial-ending 24h reminder cron.

Runs every hour via the ``AsyncIOScheduler`` registered in
``server.py``. Queries tenants whose ``trial_end_utc`` is between
``now + 23h`` and ``now + 25h`` AND whose ``trial_reminder_sent_at``
is missing. Sends the localized ``trial_ending_reminder`` email
and stamps ``trial_reminder_sent_at`` so the tenant isn't emailed
twice.

Fallbacks:
    * If the tenant's Stripe price lookup fails (network / not
      configured), the email uses the generic "your plan pricing"
      wording. Logged as WARN so ops can trace it — see the
      integration playbook in ``README-translation-notes.md``.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("trial_reminder_cron")


def _base_url() -> str:
    return (
        os.environ.get("FRONTEND_BASE_URL")
        or os.environ.get("APP_BASE_URL")
        or "https://app.example.com"
    ).rstrip("/")


async def _resolve_plan_amount_display(
    tenant: Dict[str, Any],
) -> Optional[str]:
    """Return a customer-facing dollar string for the tenant's
    subscription plan.

    Phase D6.2 · Feb-2026 — returns ``None`` on ANY failure (missing
    subscription, Stripe outage, malformed price). The caller
    substitutes the locale-appropriate fallback string from the D6
    catalog (``email.trial_reminder.fallback.plan_amount``) so the
    surrounding sentence stays coherent in every locale.
    """
    sub_id = tenant.get("stripe_subscription_id")
    if not sub_id:
        logger.warning(
            "[trial-reminder] tenant=%s missing subscription id — "
            "using generic plan-amount fallback",
            tenant.get("id"),
        )
        return None
    try:
        from services.payments.stripe_charge import (
            _asdict, _init_api_key, _stripe, _to_thread,
        )
        _init_api_key()
        sub = await _to_thread(
            _stripe.Subscription.retrieve, sub_id,
            expand=["items.data.price.product"],
        )
        d = _asdict(sub)
        items = (d.get("items") or {}).get("data") or []
        if not items:
            raise ValueError("no items")
        price = _asdict(items[0].get("price") or {})
        amount = price.get("unit_amount")
        currency = (price.get("currency") or "usd").upper()
        interval = ((price.get("recurring") or {}).get("interval")
                    or "month")
        if amount is None:
            raise ValueError("unit_amount missing")
        dollars = int(amount) / 100.0
        money = f"${dollars:,.2f}".rstrip("0").rstrip(".")
        if currency != "USD":
            money = f"{money} {currency}"
        return f"{money}/{interval}"
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "[trial-reminder] tenant=%s plan-amount lookup failed: "
            "%s — using generic fallback",
            tenant.get("id"), exc,
        )
        return None


def _format_trial_end_local(iso: str, tenant: Dict[str, Any]) -> str:
    """Render trial-end datetime in the tenant's TZ. Falls back to
    a bare UTC date if the tenant TZ is malformed."""
    try:
        from services.tenant_helpers import get_tenant_timezone
        tz = get_tenant_timezone(tenant)
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.astimezone(tz).strftime("%A, %B %-d, %Y at %-I:%M %p %Z")
    except Exception:  # noqa: BLE001
        return iso


async def run_trial_ending_reminders(
    db: Any, *, now: Optional[datetime] = None,
) -> Dict[str, int]:
    """Scan for tenants whose trial ends in ~24h and email each
    once. Returns ``{"sent": N, "skipped": N, "errored": N}``.
    """
    ref = now or datetime.now(timezone.utc)
    lower = (ref + timedelta(hours=23)).isoformat()
    upper = (ref + timedelta(hours=25)).isoformat()
    query = {
        "trial_end_utc":            {"$gte": lower, "$lte": upper},
        "trial_reminder_sent_at":   {"$in": [None, False]},
        "billing_status":           "trialing",
    }
    sent = skipped = errored = 0
    async for tenant in db.tenants.find(query, {"_id": 0}):
        try:
            admin = await db.users.find_one({
                "tenant_id": tenant["id"],
                "role":      "admin",
            }, {"_id": 0})
            if not admin:
                skipped += 1
                continue
            # Phase D6.2 · Feb-2026 — the D5 ``trial_ending_reminder``
            # template body is already localised per admin locale;
            # the fallback strings interpolated INTO the template
            # (plan-amount when Stripe lookup fails, admin-name /
            # business-name defaults) live in the D6 catalog so the
            # surrounding sentence stays coherent in every locale.
            from services.i18n_notifications import (
                resolve_notification_body, resolve_recipient_locale,
            )
            from services.email_body_i18n import t_email_body
            locale = resolve_recipient_locale(
                tenant=tenant, user=admin, audience="customer",
            )
            plan_amount_raw = await _resolve_plan_amount_display(tenant)
            plan_amount = plan_amount_raw or t_email_body(
                locale, "email.trial_reminder.fallback.plan_amount",
            )
            admin_name = admin.get("name") or t_email_body(
                locale, "email.trial_reminder.fallback.admin_name",
            )
            business_name = tenant.get("name") or t_email_body(
                locale, "email.trial_reminder.fallback.business_name",
            )
            trial_end_local = _format_trial_end_local(
                tenant.get("trial_end_utc") or "", tenant,
            )
            cancel_url = f"{_base_url()}/settings/billing"
            body = resolve_notification_body(
                "trial_ending_reminder", locale,
                context={
                    "admin_name":      admin_name,
                    "business_name":   business_name,
                    "trial_end_local": trial_end_local,
                    "plan_amount":     plan_amount,
                    "cancel_url":      cancel_url,
                },
            )
            try:
                from services.email.resend_adapter import send as _send
                await _send(
                    to=admin.get("email"),
                    subject=body["subject"],
                    html=body["body_html"],
                    text=body["body_text"],
                    tenant_id=tenant["id"],
                )
            except Exception as send_exc:  # noqa: BLE001
                logger.warning(
                    "[trial-reminder] send failed tenant=%s: %s",
                    tenant["id"], send_exc,
                )
                errored += 1
                continue
            await db.tenants.update_one(
                {"id": tenant["id"]},
                {"$set": {"trial_reminder_sent_at":
                            datetime.now(timezone.utc).isoformat()}},
            )
            sent += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "[trial-reminder] tenant=%s failed: %s",
                tenant.get("id"), exc,
            )
            errored += 1
    return {"sent": sent, "skipped": skipped, "errored": errored}
