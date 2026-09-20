"""Feb-2026 · P18 — Instant SMS+email alert on new lead capture.

Fan-out point that every ``db.leads.insert_one`` call site invokes
after a successful insert.  Reads two tenant-scoped recipient lists:

  * ``tenant.lead_alert_sms_recipients: list[str]``  — E.164 phone numbers
  * ``tenant.lead_alert_email_recipients: list[str]`` — plain email addresses

Both default to ``[]``; a tenant with both lists empty is a no-op.

Delivery is dispatched via ``BackgroundTasks`` (matches the P12A
service-report submit hardening pattern) so a slow / broken adapter
cannot bound the lead-create request tail latency.  Each background
task carries its own try/except and never raises.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from fastapi import BackgroundTasks

from config import db, logger


_FALLBACK_APP_URL = "https://app.plofv.com"


def _resolve_app_url(tenant: Dict[str, Any]) -> str:
    """Return the base URL for the admin surface.  Prefers
    ``APP_URL`` env, then the tenant's ``domain`` field, then a
    hard-coded fallback with a WARN so ops can spot mis-configured
    tenants."""
    env_url = (os.environ.get("APP_URL") or "").rstrip("/")
    if env_url:
        return env_url
    dom = (tenant.get("domain") or "").rstrip("/")
    if dom:
        return dom if dom.startswith("http") else f"https://{dom}"
    logger.warning(
        f"[p18] APP_URL env unset and tenant {tenant.get('id')} has no "
        f"domain — falling back to {_FALLBACK_APP_URL}"
    )
    return _FALLBACK_APP_URL


def _skip_line(label: str, value: Optional[str]) -> str:
    """Return a single-line SMS row when ``value`` is truthy, else ""."""
    v = (value or "").strip()
    return f"{label} {v}\n" if v else ""


def build_sms_body(*, lead: Dict[str, Any], app_url: str,
                     locale: str = "en") -> str:
    """Compose the SMS alert body per the P18 template.  Skips any
    field whose value is empty; truncates the message to 80 chars.

    Phase D6.2 · Feb-2026 — the fixed strings (``New lead —`` /
    ``View: {url}`` / ``Website Visitor``) are resolved via the D6
    i18n catalog. Icons and lead data (phone, email, address,
    message body) are user data and pass through untranslated.
    """
    from services.email_body_i18n import t_email_body
    visitor_fallback = t_email_body(locale, "email.lead_alert.website_visitor")
    name = (lead.get("name") or "").strip() or visitor_fallback
    lines: List[str] = [
        t_email_body(locale, "sms.lead_alert.header", name=name) + "\n",
    ]
    lines.append(_skip_line("📞", lead.get("phone")))
    lines.append(_skip_line("✉️", lead.get("email")))
    lines.append(_skip_line("🏠",
                             lead.get("service_address") or lead.get("address")))
    lines.append(_skip_line("💼", lead.get("service_interest")))
    msg = (lead.get("message") or "").strip()
    if msg:
        snippet = msg[:80] + ("..." if len(msg) > 80 else "")
        lines.append(f'"{snippet}"\n')
    lines.append(t_email_body(
        locale, "sms.lead_alert.view_link",
        url=f"{app_url}/leads/{lead.get('id')}",
    ))
    return "".join(lines)


def build_email_html(*, lead: Dict[str, Any], app_url: str,
                       locale: str = "en") -> str:
    """Compose the HTML email alert body.  Full contact table + full
    (untruncated) message + CTA button.

    Phase D6.2 · Feb-2026 — field labels, heading, CTA and website-
    visitor fallback are resolved via the D6 i18n catalog. Lead
    data (values in the table + message body) are user data and
    pass through untranslated per the D6.2 spec.
    """
    from services.email_body_i18n import t_email_body
    visitor_fallback = t_email_body(locale, "email.lead_alert.website_visitor")
    rows: List[str] = []
    for label_key, key in (
        ("email.lead_alert.field.name",             "name"),
        ("email.lead_alert.field.phone",            "phone"),
        ("email.lead_alert.field.email",            "email"),
        ("email.lead_alert.field.address",          "address"),
        ("email.lead_alert.field.service_address",  "service_address"),
        ("email.lead_alert.field.service_interest", "service_interest"),
    ):
        v = (lead.get(key) or "").strip() if isinstance(lead.get(key), str) else lead.get(key)
        if v:
            label = t_email_body(locale, label_key)
            rows.append(
                f"<tr><td style='padding:6px 12px 6px 0;color:#64748B;"
                f"font-weight:600'>{label}</td>"
                f"<td style='padding:6px 0;color:#0F172A'>{v}</td></tr>"
            )
    message_block = ""
    if (lead.get("message") or "").strip():
        message_block = (
            "<div style='margin-top:16px;padding:12px;background:#F0F9FF;"
            "border:1px solid #BAE6FD;border-radius:8px;color:#0C4A6E;"
            "white-space:pre-wrap;font-size:14px'>"
            f"{lead['message']}</div>"
        )
    cta_label = t_email_body(locale, "email.lead_alert.cta_view")
    cta = (
        f"<a href='{app_url}/leads/{lead.get('id')}' "
        "style='display:inline-block;margin-top:16px;padding:10px 18px;"
        "background:#0EA5E9;color:#fff;text-decoration:none;"
        f"border-radius:8px;font-weight:600'>{cta_label}</a>"
    )
    heading = t_email_body(
        locale, "email.lead_alert.heading",
        name=(lead.get("name") or visitor_fallback),
    )
    return (
        "<div style='font-family:-apple-system,Segoe UI,Roboto,sans-serif;"
        "max-width:560px;color:#0F172A'>"
        f"<h2 style='margin:0 0 12px;font-size:18px'>{heading}</h2>"
        f"<table style='border-collapse:collapse;font-size:14px'>"
        f"{''.join(rows)}</table>"
        f"{message_block}{cta}</div>"
    )


async def _already_dispatched(*, tenant_id: str, lead_id: str,
                                    target: str, channel: str) -> bool:
    """K63 · Feb-2026 — idempotency check for the notification
    dispatcher.  Returns True if the same (lead, target, channel)
    triple has already been dispatched for this tenant so a widget
    double-submit doesn't spam recipients."""
    row = await db.lead_notification_dispatches.find_one({
        "tenant_id": tenant_id, "lead_id": lead_id,
        "target": target, "channel": channel,
    }, {"_id": 0, "id": 1})
    return row is not None


async def _record_dispatch(*, tenant_id: str, lead_id: str,
                                target: str, channel: str) -> None:
    """K63 · Feb-2026 — pin the (lead, target, channel) triple with
    an ``insert_one`` (unique key). Backfilled BEFORE the async
    send so a fast second submit sees the marker even if the
    RingCentral / Resend call is still in flight."""
    from utils import new_id, now_iso
    try:
        await db.lead_notification_dispatches.insert_one({
            "id": new_id(), "tenant_id": tenant_id,
            "lead_id": lead_id, "target": target,
            "channel": channel, "created_at": now_iso(),
        })
    except Exception:  # pragma: no cover — race with parallel POST
        pass


async def _send_lead_alert_sms(*, to: str, body: str,
                                    tenant_id: str, lead_id: str) -> None:
    """Fire-and-forget SMS delivery. Swallows every adapter failure.

    K63 · Feb-2026 — writes audit rows so ops can inspect the
    dispatch outcome. ``lead_notification_sent`` on success,
    ``lead_notification_failed`` on any exception. Audit rows never
    include the raw message body (PII-safe)."""
    from utils import new_id, now_iso
    try:
        from services.sms.rc_adapter import send as _send_sms
        result = await _send_sms(
            to=to, body=body, category="transactional",
            tenant_id=tenant_id, customer_id=None,
        )
        message_id = None
        if isinstance(result, dict):
            message_id = result.get("id") or result.get("message_id")
        await db.audit_logs.insert_one({
            "id": new_id(), "tenant_id": tenant_id,
            "event": "lead_notification_sent",
            "channel": "sms", "lead_id": lead_id,
            "target": to, "message_id": message_id,
            "created_at": now_iso(),
        })
        logger.info(f"[k63] lead alert SMS sent to={to} lead={lead_id}")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[k63] lead alert SMS failed to={to} err={e}")
        try:
            await db.audit_logs.insert_one({
                "id": new_id(), "tenant_id": tenant_id,
                "event": "lead_notification_failed",
                "channel": "sms", "lead_id": lead_id,
                "target": to, "error": str(e)[:500],
                "created_at": now_iso(),
            })
        except Exception:  # pragma: no cover
            pass


async def _send_lead_alert_email(*, to: str, subject: str, html: str,
                                    tenant_id: str, lead_id: str) -> None:
    """Fire-and-forget email delivery. Same audit contract as the SMS
    twin — success + failure both audited via ``lead_notification_*``
    events. Never raises."""
    from utils import new_id, now_iso
    try:
        from services.email.resend_adapter import send as _send_email
        result = await _send_email(
            to=to, subject=subject, html=html,
            category="transactional",
            tenant_id=tenant_id, customer_id=None,
            # Phase K72 · Feb-2026 — K63 lead-notification recipients
            # are admin/staff users, not customers. Bypass the K72
            # customer-email kill switch so lead alerts keep flowing
            # during a customer-comms incident.
            audience="internal",
        )
        message_id = None
        if isinstance(result, dict):
            message_id = result.get("id") or result.get("message_id")
        await db.audit_logs.insert_one({
            "id": new_id(), "tenant_id": tenant_id,
            "event": "lead_notification_sent",
            "channel": "email", "lead_id": lead_id,
            "target": to, "message_id": message_id,
            "created_at": now_iso(),
        })
        logger.info(f"[k63] lead alert email sent to={to} lead={lead_id}")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[k63] lead alert email failed to={to} err={e}")
        try:
            await db.audit_logs.insert_one({
                "id": new_id(), "tenant_id": tenant_id,
                "event": "lead_notification_failed",
                "channel": "email", "lead_id": lead_id,
                "target": to, "error": str(e)[:500],
                "created_at": now_iso(),
            })
        except Exception:  # pragma: no cover
            pass


async def _is_contact_muted_in_tenant(
    *, tenant_id: str, phone: Optional[str], email: Optional[str],
) -> Optional[str]:
    """Feb-2026 · P27 — return the muted-customer id if this lead's
    phone or email matches any muted customer in ``tenant_id``, else
    None.  Full silent-mode: if it matches, the caller MUST skip
    fan-out to preserve the muted customer's opt-out.
    """
    if not tenant_id:
        return None
    match: List[Dict[str, Any]] = []
    p = (phone or "").strip()
    e = (email or "").strip().lower()
    if not p and not e:
        return None
    conds: List[Dict[str, Any]] = []
    if p:
        conds.append({"phone": p})
    if e:
        conds.append({"email": e})
    if not conds:
        return None
    q = {"tenant_id": tenant_id, "is_muted": True,
          "$or": conds}
    try:
        doc = await db.customers.find_one(q, {"_id": 0, "id": 1})
    except Exception:
        logger.exception("[P27] muted-contact lookup failed")
        return None
    return (doc or {}).get("id")


async def send_lead_alert_notifications(
    *,
    lead: Dict[str, Any],
    tenant: Dict[str, Any],
    background_tasks: BackgroundTasks,
) -> Dict[str, int]:
    """Fan out lead-alert SMS + email to the tenant-configured
    recipient lists.  Every send is deferred via ``BackgroundTasks``
    so the caller's response returns immediately.  Returns
    ``{sms_queued, email_queued, muted_suppressed_customer_id?}`` for
    observability + tests.

    No-op when both recipient lists are empty (tenant hasn't opted in).
    Cross-tenant safe by construction: the caller MUST pass the
    tenant doc that owns the lead — this helper does NO tenant
    lookup on its own.

    Feb-2026 · P27 — before fanning out, we check if the lead's
    phone/email matches a MUTED customer in the same tenant. If it
    does, we suppress the alert entirely and log the suppression.
    A muted customer's inbound touch must never trigger an alert
    (that's the whole point of the "silent-mode" contract).
    """
    from typing import cast  # noqa: F401 — retained for type-clarity in tests

    # Feb-2026 · Ticket #3 · Notifications org-toggle. Admin can
    # switch OFF ``lead_confirmation`` in Org Settings → Notifications;
    # honour it as a hard short-circuit BEFORE the mute check so
    # the audit chain matches the toggle's semantic intent.
    from services.org_settings import (
        is_org_notification_enabled, log_notification_skipped,
    )
    if not is_org_notification_enabled(tenant, "lead_confirmation"):
        log_notification_skipped(tenant.get("id") or "", "lead_confirmation")
        return {"sms_queued": 0, "email_queued": 0,
                "org_toggle_disabled": True}

    muted_cid = await _is_contact_muted_in_tenant(
        tenant_id=tenant.get("id") or "",
        phone=lead.get("phone"),
        email=lead.get("email"),
    )
    if muted_cid:
        logger.info(
            "[p27] lead alert suppressed — matches muted customer %s "
            "(tenant=%s, lead=%s)",
            muted_cid, tenant.get("id"), lead.get("id"),
        )
        return {
            "sms_queued": 0, "email_queued": 0,
            "muted_suppressed_customer_id": muted_cid,
        }

    sms_recips_legacy = list(tenant.get("lead_alert_sms_recipients") or [])
    email_recips_legacy = list(tenant.get("lead_alert_email_recipients") or [])
    # K63 · Feb-2026 — read the rich recipient list (opt-in toggles
    # per channel). Falls back to the legacy flat lists when the new
    # field isn't set so pre-K63 tenants keep working.
    rich_recips = list(tenant.get("lead_notification_recipients") or [])
    sms_recips: list[str] = []
    email_recips: list[str] = []
    if rich_recips:
        for r in rich_recips:
            if not isinstance(r, dict):
                continue
            phone = (r.get("phone") or "").strip()
            email = (r.get("email") or "").strip()
            if phone and r.get("sms_opt_in"):
                sms_recips.append(phone)
            if email and r.get("email_opt_in"):
                email_recips.append(email)
    else:
        sms_recips = [x for x in sms_recips_legacy if isinstance(x, str) and x.strip()]
        email_recips = [x for x in email_recips_legacy if isinstance(x, str) and x.strip()]
    # Feb-2026 · Fire the ``new_lead`` sequence trigger unconditionally
    # (BEFORE the early-return for tenants without alert config).
    # Sequence enrolment is a separate concern from lead alerts and
    # must not be gated by whether the tenant has SMS/email
    # recipients configured. Deferred via ``BackgroundTasks``.
    try:
        from services.marketing.lead_triggers import (
            fire_new_lead_sequence_trigger,
        )
        await fire_new_lead_sequence_trigger(
            lead=lead, tenant_id=tenant.get("id") or "",
            background_tasks=background_tasks,
        )
    except Exception as exc:  # pragma: no cover
        logger.warning(
            f"[p18] new-lead sequence trigger fan-out failed tenant="
            f"{tenant.get('id')} lead={lead.get('id')}: {exc}"
        )
    if not sms_recips and not email_recips:
        return {"sms_queued": 0, "email_queued": 0}

    app_url = _resolve_app_url(tenant)
    lead_id = lead.get("id") or ""
    tenant_id = tenant.get("id") or ""
    # Phase D6.2 · Feb-2026 — lead-alert recipients are the tenant's
    # admin/staff (``audience="internal"`` on the send adapter side).
    # The subject + body sentences are still localised per the
    # tenant's ``default_locale`` so a Spanish-speaking staff
    # doesn't get English lead alerts. No recipient-level locale is
    # available (recipients are configured as bare email/phone
    # strings on the tenant doc), so we resolve off the tenant.
    from services.i18n.email_locale import resolve_email_locale
    from services.email_body_i18n import t_email_body
    _locale = resolve_email_locale(recipient=None, tenant=tenant)
    visitor_fallback = t_email_body(
        _locale, "email.lead_alert.website_visitor",
    )
    sms_body = build_sms_body(lead=lead, app_url=app_url, locale=_locale)
    phone_raw = (lead.get("phone") or "").strip()
    if phone_raw:
        subject = t_email_body(
            _locale, "email.lead_alert.subject.with_phone",
            name=lead.get("name") or visitor_fallback,
            phone=phone_raw,
        )
    else:
        subject = t_email_body(
            _locale, "email.lead_alert.subject.no_phone",
            name=lead.get("name") or visitor_fallback,
        )
    html = build_email_html(lead=lead, app_url=app_url, locale=_locale)

    for phone in sms_recips:
        if isinstance(phone, str) and phone.strip():
            # K63 · Feb-2026 — idempotency guard. Skip the fan-out
            # when the same (lead_id, target, channel) triple has
            # already been dispatched (handles widget double-submits
            # + retry storms without spamming recipients).
            if await _already_dispatched(
                tenant_id=tenant_id, lead_id=lead_id,
                target=phone.strip(), channel="sms",
            ):
                continue
            await _record_dispatch(
                tenant_id=tenant_id, lead_id=lead_id,
                target=phone.strip(), channel="sms",
            )
            background_tasks.add_task(
                _send_lead_alert_sms, to=phone.strip(),
                body=sms_body, tenant_id=tenant_id, lead_id=lead_id,
            )
    for addr in email_recips:
        if isinstance(addr, str) and addr.strip():
            if await _already_dispatched(
                tenant_id=tenant_id, lead_id=lead_id,
                target=addr.strip(), channel="email",
            ):
                continue
            await _record_dispatch(
                tenant_id=tenant_id, lead_id=lead_id,
                target=addr.strip(), channel="email",
            )
            background_tasks.add_task(
                _send_lead_alert_email, to=addr.strip(),
                subject=subject, html=html,
                tenant_id=tenant_id, lead_id=lead_id,
            )
    return {"sms_queued": len(sms_recips), "email_queued": len(email_recips)}
