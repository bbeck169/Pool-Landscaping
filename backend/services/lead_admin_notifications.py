"""Feb-2026 · Lead admin notification email.

The K63 dispatcher (:mod:`services.lead_notifications`) already
handles the tenant's explicit "lead notification recipients" list
(power-user opt-in, one row per person with per-channel toggles).

**This module solves a different problem.** Under K63 alone, a
tenant whose admin never opened the K63 config page — or a tenant
whose K63 list has fallen behind their real staff roster — silently
misses every inbound lead notification. The business owner reported
inbound leads that never produced an email despite an active
``lead_alert_email_recipients`` list.

Fix: unconditionally fan out a full-HTML lead-created email to
**every admin/manager user** on the tenant plus the optional
``tenant.business_settings.notification_email`` mailbox. Recipients
already covered by the K63 rich list are deduplicated so nobody
receives two copies.

Contract:

- Fires ONLY on the *initial* insert of a new lead — the caller
  passes the freshly-inserted ``lead`` dict.
- Fire-and-forget via ``BackgroundTasks``; a Resend outage cannot
  bound the caller's response tail latency.
- Uses the existing K63 idempotency table
  (``lead_notification_dispatches``) with a distinct ``target``
  suffix (``:admin-fanout``) so its rows don't collide with K63's
  own dispatch rows.
- Every send writes an audit row to ``audit_logs`` (event
  ``lead_admin_notification_sent`` / ``…_failed``) so ops can
  trace missed inbounds.
- When the tenant has ZERO resolvable admin recipients (empty
  users collection + no ``business_settings.notification_email``)
  the helper logs a WARNING and returns cleanly — no silent no-op.

Response payload:

    {"queued": int, "recipients": list[str], "reason"?: str}
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from fastapi import BackgroundTasks

from config import db, logger
from utils import new_id, now_iso


_ADMIN_ROLES = ("admin", "super_admin", "manager", "owner")
_PHX = ZoneInfo("America/Phoenix")
_FALLBACK_APP_URL = "https://app.plofv.com"


def _resolve_app_url(tenant: Dict[str, Any]) -> str:
    env_url = (os.environ.get("APP_URL") or "").rstrip("/")
    if env_url:
        return env_url
    dom = (tenant.get("domain") or "").rstrip("/")
    if dom:
        return dom if dom.startswith("http") else f"https://{dom}"
    return _FALLBACK_APP_URL


def _fmt_phx(iso: Optional[str]) -> str:
    if not iso:
        return ""
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.astimezone(_PHX).strftime("%b %d, %Y · %I:%M %p %Z")
    except Exception:
        return iso


def _compose_address_block(lead: Dict[str, Any]) -> str:
    """Compose a multi-line HTML address block.

    Prefers the composite ``service_address`` when present. When the
    widget stored the fields separately (``address``/``city``/
    ``state``/``zip``), we render them on two lines: street then
    city, state zip. Falls back to the empty string when no address
    data is available so the caller can drop the row.
    """
    street = (lead.get("address") or "").strip()
    service_addr = (lead.get("service_address") or "").strip()
    city = (lead.get("city") or "").strip()
    state = (lead.get("state") or "").strip()
    zip_code = (lead.get("zip") or "").strip()

    # Prefer the composite service_address when it contains city/state/zip
    # inline (typical widget composite string).
    if service_addr and (not street or "," in service_addr):
        first_line = service_addr
    elif street:
        first_line = street
    else:
        first_line = service_addr  # may be empty

    second_line_parts: List[str] = []
    if city:
        second_line_parts.append(city)
    if state:
        second_line_parts.append(state)
    if zip_code:
        second_line_parts.append(zip_code)
    # Avoid duplicating city/state/zip if they're already in first_line
    second_line = ""
    if second_line_parts and not (
        first_line and all(p in first_line for p in second_line_parts if p)
    ):
        second_line = f"{', '.join(second_line_parts[:2])}"
        if zip_code and zip_code not in second_line:
            second_line = (second_line + " " + zip_code).strip()

    if not first_line and not second_line:
        return ""
    lines = [ln for ln in (first_line, second_line) if ln]
    return "<br>".join(lines)


def _compose_email_html(*, lead: Dict[str, Any], app_url: str,
                          branding: Dict[str, Any]) -> str:
    """Full-HTML template wrapped in the tenant's brand shell."""
    from services.email.theming import wrap_html_in_shell
    name = (lead.get("name") or "Website Visitor").strip()
    address_block = _compose_address_block(lead)
    rows: List[str] = []

    def _row(label: str, value: str) -> None:
        rows.append(
            f"<tr><td style='padding:6px 16px 6px 0;color:#64748B;"
            f"font-weight:600;vertical-align:top;white-space:nowrap'>"
            f"{label}</td>"
            f"<td style='padding:6px 0;color:#0F172A'>{value}</td></tr>"
        )

    if lead.get("email"):
        _row("Email", str(lead["email"]))
    if lead.get("phone"):
        _row("Phone", str(lead["phone"]))
    if address_block:
        _row("Address", address_block)
    if lead.get("service_interest"):
        _row("Requested Service", str(lead["service_interest"]))
    notes = (lead.get("notes") or lead.get("message") or "").strip()
    if notes:
        _row(
            "Notes",
            f"<div style='white-space:pre-wrap'>{notes}</div>",
        )
    _row("Submitted", _fmt_phx(lead.get("created_at")))
    _row("Source", str(lead.get("source") or "website"))

    cta = (
        f"<div style='margin-top:20px'>"
        f"<a href='{app_url}/leads/{lead.get('id')}' "
        "style='display:inline-block;padding:12px 22px;"
        "background:#0EA5E9;color:#ffffff;text-decoration:none;"
        "border-radius:8px;font-weight:600;font-size:14px'>"
        "View lead in admin</a></div>"
    )
    inner = (
        f"<h2 style='margin:0 0 8px;font-size:20px;color:#0F172A'>"
        f"New lead — {name}</h2>"
        "<p style='margin:0 0 16px;color:#475569;font-size:14px'>"
        "A new inquiry just came in. Full details below.</p>"
        "<table style='border-collapse:collapse;font-size:14px;"
        "line-height:1.4'>"
        f"{''.join(rows)}</table>"
        f"{cta}"
    )
    try:
        return wrap_html_in_shell(inner, branding=branding)
    except Exception:  # pragma: no cover — theming must never crash send
        return inner


def _compose_subject(lead: Dict[str, Any]) -> str:
    name = (lead.get("name") or "Website Visitor").strip()
    interest = (lead.get("service_interest") or "").strip() \
        or "Get a Free Quote"
    return f"New Lead: {name} — {interest}"


async def _resolve_admin_recipients(tenant: Dict[str, Any]) -> List[str]:
    """Return the deduped, lower-cased email list to notify.

    Order of resolution (union then dedupe):

    1. Every ``users`` row on the tenant whose ``role`` is in the
       admin whitelist, ``email`` is populated, ``deactivated_at``
       is unset (or missing), and the optional per-user opt-out
       ``notify_new_leads`` is not explicitly ``False``.
    2. ``tenant.business_settings.notification_email`` when set.
    3. Legacy K63 ``lead_notification_recipients`` rows are
       INTENTIONALLY skipped here — the K63 dispatcher handles
       those separately. We only dedupe against them at send time
       via the shared ``lead_notification_dispatches`` table.
    """
    emails: List[str] = []
    tid = tenant.get("id") or ""
    if tid:
        # Feb-2026 · Bug fix — the aquaterra seed marks retired
        # accounts with ``active: False`` (not ``deactivated_at``).
        # The original filter missed that flag and kept mailing
        # deactivated placeholder rows. Guard on BOTH conventions:
        #   * ``deactivated_at`` unset / null (Phase-13 convention)
        #   * ``active`` unset or explicitly True (seed convention)
        # PLUS the per-user opt-out ``notify_new_leads``.
        cursor = db.users.find(
            {"tenant_id": tid,
              "role": {"$in": list(_ADMIN_ROLES)},
              "$and": [
                  {"$or": [{"deactivated_at": {"$exists": False}},
                             {"deactivated_at": None}]},
                  {"$or": [{"active": {"$exists": False}},
                             {"active": True}]},
                  {"$or": [{"notify_new_leads": {"$exists": False}},
                             {"notify_new_leads": {"$ne": False}}]},
              ]},
            {"_id": 0, "email": 1},
        )
        async for u in cursor:
            e = (u.get("email") or "").strip()
            if e:
                emails.append(e)
    biz = (tenant.get("business_settings") or {})
    biz_email = (biz.get("notification_email") or "").strip()
    if biz_email:
        emails.append(biz_email)
    # Dedupe case-insensitively while preserving first-seen order.
    seen: set = set()
    out: List[str] = []
    for e in emails:
        k = e.lower()
        if k not in seen:
            seen.add(k)
            out.append(e)
    return out


async def _already_dispatched(*, tenant_id: str, lead_id: str,
                                target: str) -> bool:
    row = await db.lead_notification_dispatches.find_one({
        "tenant_id": tenant_id, "lead_id": lead_id,
        "target": target, "channel": "email",
    }, {"_id": 0, "id": 1})
    return row is not None


async def _record_dispatch(*, tenant_id: str, lead_id: str,
                              target: str) -> None:
    try:
        await db.lead_notification_dispatches.insert_one({
            "id": new_id(), "tenant_id": tenant_id,
            "lead_id": lead_id, "target": target,
            "channel": "email", "created_at": now_iso(),
        })
    except Exception:  # pragma: no cover — race
        pass


async def _send_one(*, to: str, subject: str, html: str,
                       tenant_id: str, lead_id: str) -> None:
    """Fire-and-forget send + audit trail. Never raises."""
    try:
        from services.email.resend_adapter import send as _send_email
        result = await _send_email(
            to=to, subject=subject, html=html,
            category="transactional",
            tenant_id=tenant_id, customer_id=None,
            idempotency_key=f"lead-admin-fanout:{lead_id}:{to.lower()}",
            audience="internal",
        )
        provider_id = None
        if isinstance(result, dict):
            provider_id = (result.get("provider_response_id")
                           or result.get("id"))
        await db.audit_logs.insert_one({
            "id": new_id(), "tenant_id": tenant_id,
            "event": "lead_admin_notification_sent",
            "channel": "email", "lead_id": lead_id,
            "target": to, "message_id": provider_id,
            "created_at": now_iso(),
        })
        logger.info(
            f"[lead-admin-fanout] sent to={to} lead={lead_id}"
        )
    except Exception as e:  # noqa: BLE001
        logger.warning(
            f"[lead-admin-fanout] send failed to={to} err={e}"
        )
        try:
            await db.audit_logs.insert_one({
                "id": new_id(), "tenant_id": tenant_id,
                "event": "lead_admin_notification_failed",
                "channel": "email", "lead_id": lead_id,
                "target": to, "error": str(e)[:500],
                "created_at": now_iso(),
            })
        except Exception:  # pragma: no cover
            pass


async def dispatch_admin_lead_email(
    *,
    lead: Dict[str, Any],
    tenant: Dict[str, Any],
    background_tasks: BackgroundTasks,
) -> Dict[str, Any]:
    """Public entry point. Callers pass the freshly-inserted lead
    doc AND the full tenant doc (with ``business_settings``)."""
    tid = tenant.get("id") or ""
    lid = lead.get("id") or ""
    recipients = await _resolve_admin_recipients(tenant)
    if not recipients:
        logger.warning(
            "[lead-admin-fanout] no admin recipients resolved "
            f"tenant={tid} lead={lid} — check users collection and "
            "tenant.business_settings.notification_email"
        )
        return {"queued": 0, "recipients": [],
                 "reason": "no_admin_recipients"}
    app_url = _resolve_app_url(tenant)
    try:
        from services.tenants.business_settings import (
            get_effective_business_settings,
        )
        branding = await get_effective_business_settings(tid) or {}
    except Exception:  # pragma: no cover
        branding = {}
    subject = _compose_subject(lead)
    html = _compose_email_html(lead=lead, app_url=app_url,
                                  branding=branding)
    queued: List[str] = []
    for addr in recipients:
        target = f"{addr.lower()}:admin-fanout"
        if await _already_dispatched(tenant_id=tid, lead_id=lid,
                                       target=target):
            continue
        await _record_dispatch(tenant_id=tid, lead_id=lid,
                                target=target)
        background_tasks.add_task(
            _send_one, to=addr, subject=subject, html=html,
            tenant_id=tid, lead_id=lid,
        )
        queued.append(addr)
    return {"queued": len(queued), "recipients": queued}
