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


def build_sms_body(*, lead: Dict[str, Any], app_url: str) -> str:
    """Compose the SMS alert body per the P18 template.  Skips any
    field whose value is empty; truncates the message to 80 chars."""
    lines: List[str] = [f"New lead — {(lead.get('name') or '').strip() or 'Website Visitor'}\n"]
    lines.append(_skip_line("📞", lead.get("phone")))
    lines.append(_skip_line("✉️", lead.get("email")))
    lines.append(_skip_line("🏠",
                             lead.get("service_address") or lead.get("address")))
    lines.append(_skip_line("💼", lead.get("service_interest")))
    msg = (lead.get("message") or "").strip()
    if msg:
        snippet = msg[:80] + ("..." if len(msg) > 80 else "")
        lines.append(f'"{snippet}"\n')
    lines.append(f"View: {app_url}/leads/{lead.get('id')}")
    return "".join(lines)


def build_email_html(*, lead: Dict[str, Any], app_url: str) -> str:
    """Compose the HTML email alert body.  Full contact table + full
    (untruncated) message + CTA button."""
    rows: List[str] = []
    for label, key in (
        ("Name",             "name"),
        ("Phone",            "phone"),
        ("Email",            "email"),
        ("Address",          "address"),
        ("Service address",  "service_address"),
        ("Service interest", "service_interest"),
    ):
        v = (lead.get(key) or "").strip() if isinstance(lead.get(key), str) else lead.get(key)
        if v:
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
    cta = (
        f"<a href='{app_url}/leads/{lead.get('id')}' "
        "style='display:inline-block;margin-top:16px;padding:10px 18px;"
        "background:#0EA5E9;color:#fff;text-decoration:none;"
        "border-radius:8px;font-weight:600'>View lead in admin</a>"
    )
    return (
        "<div style='font-family:-apple-system,Segoe UI,Roboto,sans-serif;"
        "max-width:560px;color:#0F172A'>"
        f"<h2 style='margin:0 0 12px;font-size:18px'>New lead — "
        f"{(lead.get('name') or 'Website Visitor')}</h2>"
        f"<table style='border-collapse:collapse;font-size:14px'>"
        f"{''.join(rows)}</table>"
        f"{message_block}{cta}</div>"
    )


async def _send_lead_alert_sms(*, to: str, body: str,
                                 tenant_id: str, lead_id: str) -> None:
    """Fire-and-forget SMS delivery.  Swallows every adapter failure —
    a broken RingCentral SDK must NEVER 500 the lead-create request."""
    try:
        from services.sms.rc_adapter import send as _send_sms
        await _send_sms(
            to=to, body=body, category="transactional",
            tenant_id=tenant_id, customer_id=None,
        )
        logger.info(f"[p18-bg] lead alert SMS sent to={to} lead={lead_id}")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[p18-bg] lead alert SMS failed to={to} err={e}")


async def _send_lead_alert_email(*, to: str, subject: str, html: str,
                                    tenant_id: str, lead_id: str) -> None:
    """Fire-and-forget email delivery.  Swallows every adapter failure."""
    try:
        from services.email.resend_adapter import send as _send_email
        await _send_email(
            to=to, subject=subject, html=html,
            category="transactional",
            tenant_id=tenant_id, customer_id=None,
        )
        logger.info(f"[p18-bg] lead alert email sent to={to} lead={lead_id}")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[p18-bg] lead alert email failed to={to} err={e}")


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

    sms_recips = list(tenant.get("lead_alert_sms_recipients") or [])
    email_recips = list(tenant.get("lead_alert_email_recipients") or [])
    if not sms_recips and not email_recips:
        return {"sms_queued": 0, "email_queued": 0}

    app_url = _resolve_app_url(tenant)
    lead_id = lead.get("id") or ""
    tenant_id = tenant.get("id") or ""
    sms_body = build_sms_body(lead=lead, app_url=app_url)
    subject = (
        f"New lead — {lead.get('name') or 'Website Visitor'}"
        f"{' (' + lead['phone'] + ')' if (lead.get('phone') or '').strip() else ''}"
    )
    html = build_email_html(lead=lead, app_url=app_url)

    for phone in sms_recips:
        if isinstance(phone, str) and phone.strip():
            background_tasks.add_task(
                _send_lead_alert_sms, to=phone.strip(),
                body=sms_body, tenant_id=tenant_id, lead_id=lead_id,
            )
    for addr in email_recips:
        if isinstance(addr, str) and addr.strip():
            background_tasks.add_task(
                _send_lead_alert_email, to=addr.strip(),
                subject=subject, html=html,
                tenant_id=tenant_id, lead_id=lead_id,
            )
    return {"sms_queued": len(sms_recips), "email_queued": len(email_recips)}
