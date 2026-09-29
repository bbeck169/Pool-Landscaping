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

Phase LD2 · Feb 2026 — invoice-style redesign:
  * Header bar rendered with the tenant's ``brand_primary_hex``
    (falls back to :data:`_DEFAULT_PRIMARY_HEX` when unset).
  * Structured "Lead card" + "Service details" + "Source" +
    "Message" sections mirroring the estimate/invoice/auto-visit
    email pattern (see ``services/auto_visit_email.py``).
  * Phone rendered as ``tel:`` link + email as ``mailto:`` link.
  * CTA button uses the tenant's derived brand accent + resolves
    to ``{app_url}/admin/leads/{lead_id}``.
  * Every row is optional — a missing field HIDES its row.
  * Preheader text (≤90 chars) improves inbox scannability.
  * Subject upgraded to ``New lead — {name} · {source_label}``.
    Set ``LEAD_ADMIN_LEGACY_SUBJECT=1`` in the environment to fall
    back to the previous format if admin inbox rules depended on it.
  * Plain-text alternate produced alongside the HTML for text-only
    clients — same content, one row per line.

Response payload:

    {"queued": int, "recipients": list[str], "reason"?: str}
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional
from zoneinfo import ZoneInfo

from fastapi import BackgroundTasks

from config import db, logger
from utils import new_id, now_iso


_ADMIN_ROLES = ("admin", "super_admin", "manager", "owner")
_PHX = ZoneInfo("America/Phoenix")
_FALLBACK_APP_URL = "https://app.plofv.com"

# Phase LD2 · brand palette defaults — kept in sync with
# ``services/auto_visit_email.py`` so both surfaces read the same
# fallbacks when the tenant hasn't picked colours yet.
_DEFAULT_PRIMARY_HEX   = "#0B4A6F"
_DEFAULT_SECONDARY_HEX = "#0369A1"
_DEFAULT_ACCENT_HEX    = "#2563EB"

_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def _valid_hex(candidate: Any) -> Optional[str]:
    if not candidate:
        return None
    s = str(candidate).strip()
    if not _HEX_RE.match(s):
        return None
    return s.lower()


def _resolve_palette(branding: Optional[Mapping[str, Any]]) -> Dict[str, str]:
    """Return ``{primary, secondary, accent}`` from the tenant's
    stored brand colors. Falls back to ``_DEFAULT_*`` when unset.

    Reads BOTH the ``brand_primary_hex`` (effective-settings shape)
    and ``brand_primary`` (raw tenant shape) so the helper works
    with whatever branding dict the caller has on hand — matching
    the pattern used by ``services/auto_visit_email.py``.
    """
    b: Mapping[str, Any] = branding or {}
    primary = (
        _valid_hex(b.get("brand_primary_hex"))
        or _valid_hex(b.get("brand_primary"))
        or _DEFAULT_PRIMARY_HEX
    )
    secondary = (
        _valid_hex(b.get("brand_secondary_hex"))
        or _valid_hex(b.get("brand_secondary"))
        or _DEFAULT_SECONDARY_HEX
    )
    accent = (
        _valid_hex(b.get("brand_accent_hex"))
        or _valid_hex(b.get("brand_accent"))
        or (secondary if secondary != _DEFAULT_SECONDARY_HEX
              else _DEFAULT_ACCENT_HEX)
    )
    return {"primary": primary, "secondary": secondary, "accent": accent}


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


# Phase LD2 · Feb 2026 — mirror of the frontend ``SOURCE_LABEL``
# helper in ``LeadsDashboardPage.jsx``. Kept intentionally simple
# so admins see the same human-friendly source string in the
# email inbox and in the CRM list.
def _source_label(src: Optional[str]) -> str:
    if not src:
        return "Unknown"
    s = str(src).strip()
    if s == "chat_widget":
        return "Chat widget"
    if s.startswith("form:"):
        return f"Form · {s[5:]}"
    if s.startswith("referral_from_customer:"):
        return "Referral"
    aliases = {
        "website_form": "Website form",
        "admin_manual": "Admin entry",
        "phone": "Phone",
        "walk_in": "Walk-in",
        "referral": "Referral",
        "widget_chat": "Chat widget",
        "import": "Import",
    }
    return aliases.get(s, s.replace("_", " ").title())


def _tenant_business_name(tenant: Dict[str, Any],
                             branding: Mapping[str, Any]) -> str:
    return (
        (branding or {}).get("company_display_name")
        or (branding or {}).get("business_name")
        or tenant.get("business_name")
        or tenant.get("company_name")
        or tenant.get("name")
        or "Your business"
    )


def _tenant_logo_url(tenant: Dict[str, Any],
                        branding: Mapping[str, Any]) -> str:
    return (
        (branding or {}).get("logo_url")
        or tenant.get("logo_url")
        or ((tenant.get("settings") or {}).get("business_card") or {}).get("logo_url")
        or ""
    )


def _escape(v: Any) -> str:
    """Minimal HTML escape — good enough for the plaintext fields
    (name/notes/service_interest) we render inside the email. Never
    escapes tenant-controlled hex colors or URLs which come from
    trusted server-side state."""
    s = "" if v is None else str(v)
    return (
        s.replace("&", "&amp;")
         .replace("<", "&lt;")
         .replace(">", "&gt;")
         .replace('"', "&quot;")
    )


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

    if service_addr and (not street or "," in service_addr):
        first_line = service_addr
    elif street:
        first_line = street
    else:
        first_line = service_addr

    second_line_parts: List[str] = []
    if city:
        second_line_parts.append(city)
    if state:
        second_line_parts.append(state)
    if zip_code:
        second_line_parts.append(zip_code)
    second_line = ""
    if second_line_parts and not (
        first_line and all(p in first_line for p in second_line_parts if p)
    ):
        second_line = f"{', '.join(second_line_parts[:2])}"
        if zip_code and zip_code not in second_line:
            second_line = (second_line + " " + zip_code).strip()

    if not first_line and not second_line:
        return ""
    lines = [_escape(ln) for ln in (first_line, second_line) if ln]
    return "<br>".join(lines)


def _plain_address(lead: Dict[str, Any]) -> str:
    """Plain-text version of :func:`_compose_address_block`."""
    html = _compose_address_block(lead)
    if not html:
        return ""
    return html.replace("<br>", " · ").replace("&amp;", "&")


def _compose_preheader(lead: Dict[str, Any]) -> str:
    """Return a ≤90-char preheader summarising the lead. Rendered
    hidden inline in the HTML so most inbox clients (Gmail, Apple
    Mail, Outlook) show it as the message preview line under the
    subject."""
    name = (lead.get("name") or "Website Visitor").strip()
    source = _source_label(lead.get("source"))
    interest = (lead.get("service_interest") or "").strip()
    parts = [name, source]
    if interest:
        parts.append(interest)
    line = " · ".join(parts)
    if len(line) > 90:
        line = line[:87].rstrip() + "…"
    return line


def _compose_email_html(*, lead: Dict[str, Any], app_url: str,
                          branding: Dict[str, Any],
                          tenant: Optional[Dict[str, Any]] = None) -> str:
    """Phase LD2 · Feb 2026 — invoice-style HTML template.

    Mirrors the ``services/auto_visit_email.py`` structure: a full-
    width brand-color header band, structured data sections rendered
    as email-friendly tables, and a CTA button styled with the
    tenant's accent color. Every field is optional — missing fields
    simply hide their row.

    ``tenant`` is optional so pre-Phase-LD2 callers that only pass
    the branding dict keep working. When both are provided, the
    header business name / logo prefer the tenant record.
    """
    tenant = tenant or {}
    palette = _resolve_palette(branding)
    company = _escape(_tenant_business_name(tenant, branding))
    logo = _tenant_logo_url(tenant, branding)
    preheader = _compose_preheader(lead)

    name = _escape((lead.get("name") or "Website Visitor").strip())
    company_name = _escape((lead.get("company_name") or "").strip())
    phone = (lead.get("phone") or "").strip()
    email = (lead.get("email") or "").strip()
    service_interest = _escape((lead.get("service_interest") or "").strip())
    address_html = _compose_address_block(lead)
    lat = lead.get("latitude")
    lng = lead.get("longitude")
    coords = ""
    if lat is not None and lng is not None:
        try:
            coords = f"📍 {float(lat):.5f}, {float(lng):.5f}"
        except Exception:
            coords = ""
    notes = _escape((lead.get("notes") or lead.get("message") or "").strip())
    source_lbl = _escape(_source_label(lead.get("source")))
    submitted = _escape(_fmt_phx(lead.get("created_at")))

    def _row(label: str, value_html: str) -> str:
        return (
            f"<tr>"
            f"<td class='email-friendly-label' "
            f"style='padding:8px 16px 8px 0;color:#64748B;"
            f"font-weight:600;font-size:13px;vertical-align:top;"
            f"white-space:nowrap;width:34%'>{label}</td>"
            f"<td style='padding:8px 0;color:#0F172A;font-size:14px;"
            f"vertical-align:top'>{value_html}</td>"
            f"</tr>"
        )

    lead_rows: List[str] = []
    lead_rows.append(_row("Name", f"<strong>{name}</strong>"))
    if company_name:
        lead_rows.append(_row("Company", company_name))
    if phone:
        digits = re.sub(r"[^0-9+]", "", phone) or phone
        lead_rows.append(_row(
            "Phone",
            f'<a href="tel:{_escape(digits)}" '
            f'style="color:{palette["primary"]};text-decoration:none;'
            f'font-weight:600">{_escape(phone)}</a>',
        ))
    if email:
        lead_rows.append(_row(
            "Email",
            f'<a href="mailto:{_escape(email)}" '
            f'style="color:{palette["primary"]};text-decoration:none;'
            f'font-weight:600">{_escape(email)}</a>',
        ))

    service_rows: List[str] = []
    if service_interest:
        service_rows.append(_row("Requested Service", service_interest))
    if address_html:
        service_rows.append(_row("Address", address_html))
    if coords:
        service_rows.append(_row(
            "Coordinates",
            f"<span style='font-family:ui-monospace,SFMono-Regular,"
            f"Menlo,monospace;font-size:12px;color:#475569'>"
            f"{_escape(coords)}</span>",
        ))

    badges: List[str] = []
    if (lead.get("source") or "").startswith("referral_from_customer:"):
        badges.append(
            "<span style='display:inline-block;padding:2px 10px;"
            "background:#FEF3C7;color:#92400E;border-radius:9999px;"
            "font-size:11px;font-weight:700;text-transform:uppercase;"
            "letter-spacing:0.02em;margin-left:6px'>Referral</span>"
        )
    if lead.get("duplicate_of_existing_contact"):
        badges.append(
            "<span style='display:inline-block;padding:2px 10px;"
            "background:#FEE2E2;color:#991B1B;border-radius:9999px;"
            "font-size:11px;font-weight:700;text-transform:uppercase;"
            "letter-spacing:0.02em;margin-left:6px'>Duplicate</span>"
        )
    source_row_value = source_lbl + "".join(badges)

    source_rows: List[str] = [_row("Source", source_row_value)]
    if submitted:
        source_rows.append(_row("Received", submitted))
    campaign = _escape((lead.get("utm_campaign")
                         or lead.get("campaign") or "").strip())
    if campaign:
        source_rows.append(_row("Campaign", campaign))
    tags = lead.get("tags") or []
    if isinstance(tags, list) and tags:
        tag_html = " ".join(
            f"<span style='display:inline-block;padding:2px 8px;"
            f"background:#F1F5F9;color:#334155;border-radius:9999px;"
            f"font-size:11px;font-weight:600;margin:0 4px 4px 0'>"
            f"{_escape(t)}</span>"
            for t in tags if t
        )
        source_rows.append(_row("Tags", tag_html))

    def _section(title: str, rows: List[str]) -> str:
        if not rows:
            return ""
        return (
            f"<h3 style='margin:20px 0 6px;font-family:system-ui,-apple-system,"
            f"Segoe UI,Roboto,sans-serif;font-size:14px;letter-spacing:0.04em;"
            f"text-transform:uppercase;color:{palette['secondary']}'>{title}</h3>"
            f"<table class='email-friendly' role='presentation' cellspacing='0' "
            f"cellpadding='0' style='width:100%;border-collapse:collapse'>"
            f"{''.join(rows)}</table>"
        )

    lead_section = _section("Lead", lead_rows)
    service_section = _section("Service details", service_rows)
    source_section = _section("Source", source_rows)

    message_html = ""
    if notes:
        message_html = (
            f"<h3 style='margin:20px 0 6px;font-family:system-ui,-apple-system,"
            f"Segoe UI,Roboto,sans-serif;font-size:14px;letter-spacing:0.04em;"
            f"text-transform:uppercase;color:{palette['secondary']}'>Message</h3>"
            f"<div style='background:#F8FAFC;border:1px solid #E2E8F0;"
            f"border-radius:8px;padding:14px 16px;color:#0F172A;font-size:14px;"
            f"line-height:1.55;white-space:pre-wrap'>{notes}</div>"
        )

    header_html = (
        f'<table role="presentation" cellspacing="0" cellpadding="0" '
        f'style="width:100%;border-collapse:collapse;'
        f'background:{palette["primary"]};padding:18px 24px" '
        f'bgcolor="{palette["primary"]}">'
        f'<tr><td>'
    )
    if logo:
        header_html += (
            f'<img src="{_escape(logo)}" alt="{company}" '
            f'style="max-height:44px;margin-bottom:8px;display:block" />'
        )
    header_html += (
        f'<div style="color:#FFFFFF;font-family:system-ui,-apple-system,'
        f'Segoe UI,Roboto,sans-serif;font-size:20px;font-weight:700;'
        f'line-height:1.2">{company}</div>'
        f'<div style="color:rgba(255,255,255,0.88);font-family:system-ui,'
        f'-apple-system,Segoe UI,Roboto,sans-serif;font-size:14px;'
        f'margin-top:4px;letter-spacing:0.02em">New lead</div>'
        f'</td></tr></table>'
    )

    cta_href = f"{app_url.rstrip('/')}/admin/leads/{lead.get('id', '')}"
    cta_html = (
        f'<div style="margin:24px 0 8px">'
        f'<a href="{_escape(cta_href)}" '
        f'style="display:inline-block;padding:12px 22px;'
        f'background:{palette["accent"]};color:#FFFFFF;text-decoration:none;'
        f'border-radius:10px;font-weight:700;font-size:14px;'
        f'font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif">'
        f'Open lead in CRM →</a></div>'
    )

    footer_html = (
        f'<p style="margin:24px 0 0;color:#94A3B8;font-size:12px;'
        f'line-height:1.5;font-family:system-ui,-apple-system,Segoe UI,'
        f'Roboto,sans-serif">'
        f'You&#39;re receiving this because you&#39;re on the admin '
        f'notification list for {company}. Manage notifications in '
        f'Settings.</p>'
    )

    # Preheader — hidden inline text so the inbox preview line
    # picks it up while the visible layout stays clean. Mobile
    # breakpoints tighten padding on narrow viewports.
    style_block = (
        "<style>"
        "@media only screen and (max-width:480px){"
        ".email-friendly-label{white-space:normal !important;width:auto !important}"
        ".email-friendly td{display:block !important;width:100% !important;padding:4px 0 !important}"
        ".email-friendly-shell{padding:16px !important}"
        "}"
        "</style>"
    )
    preheader_html = (
        f'<div style="display:none !important;visibility:hidden;opacity:0;'
        f'color:transparent;height:0;width:0;overflow:hidden;'
        f'mso-hide:all">{_escape(preheader)}</div>'
    )

    html = (
        f'{style_block}'
        f'<div style="font-family:system-ui,-apple-system,Segoe UI,Roboto,'
        f'sans-serif;max-width:640px;margin:0 auto;background:#FFFFFF;'
        f'color:#0F172A">'
        f'{preheader_html}'
        f'{header_html}'
        f'<div class="email-friendly-shell" style="padding:24px 28px">'
        f'{lead_section}'
        f'{service_section}'
        f'{source_section}'
        f'{message_html}'
        f'{cta_html}'
        f'{footer_html}'
        f'</div></div>'
    )
    return html


def _compose_email_text(*, lead: Dict[str, Any], app_url: str,
                          branding: Dict[str, Any],
                          tenant: Optional[Dict[str, Any]] = None) -> str:
    """Plain-text alternate — same content, one row per line, for
    text-only email clients."""
    tenant = tenant or {}
    company = _tenant_business_name(tenant, branding)
    name = (lead.get("name") or "Website Visitor").strip()
    phone = (lead.get("phone") or "").strip()
    email = (lead.get("email") or "").strip()
    company_name = (lead.get("company_name") or "").strip()
    service_interest = (lead.get("service_interest") or "").strip()
    address = _plain_address(lead)
    lat = lead.get("latitude")
    lng = lead.get("longitude")
    coords = ""
    if lat is not None and lng is not None:
        try:
            coords = f"{float(lat):.5f}, {float(lng):.5f}"
        except Exception:
            coords = ""
    notes = (lead.get("notes") or lead.get("message") or "").strip()
    source_lbl = _source_label(lead.get("source"))
    submitted = _fmt_phx(lead.get("created_at"))

    lines: List[str] = [
        f"{company} — New lead",
        "-" * 40,
        "",
        "LEAD",
        f"  Name: {name}",
    ]
    if company_name:
        lines.append(f"  Company: {company_name}")
    if phone:
        lines.append(f"  Phone: {phone}")
    if email:
        lines.append(f"  Email: {email}")

    service_bits: List[str] = []
    if service_interest:
        service_bits.append(f"  Requested Service: {service_interest}")
    if address:
        service_bits.append(f"  Address: {address}")
    if coords:
        service_bits.append(f"  Coordinates: {coords}")
    if service_bits:
        lines += ["", "SERVICE DETAILS", *service_bits]

    source_bits: List[str] = [f"  Source: {source_lbl}"]
    if (lead.get("source") or "").startswith("referral_from_customer:"):
        source_bits[-1] += " (Referral)"
    if lead.get("duplicate_of_existing_contact"):
        source_bits[-1] += " · Duplicate"
    if submitted:
        source_bits.append(f"  Received: {submitted}")
    campaign = (lead.get("utm_campaign") or lead.get("campaign") or "").strip()
    if campaign:
        source_bits.append(f"  Campaign: {campaign}")
    tags = lead.get("tags") or []
    if isinstance(tags, list) and tags:
        source_bits.append(f"  Tags: {', '.join(str(t) for t in tags if t)}")
    lines += ["", "SOURCE", *source_bits]

    if notes:
        lines += ["", "MESSAGE", "  " + notes.replace("\n", "\n  ")]

    cta_href = f"{app_url.rstrip('/')}/admin/leads/{lead.get('id', '')}"
    lines += ["", f"Open lead in CRM: {cta_href}"]
    lines += ["", f"You're receiving this because you're on the admin "
              f"notification list for {company}. Manage notifications in Settings."]
    return "\n".join(lines)


def _compose_subject(lead: Dict[str, Any]) -> str:
    """Phase LD2 · Feb 2026 — upgraded subject line.

    ``New lead — {name} · {source_label}`` for inbox scanability.
    Set ``LEAD_ADMIN_LEGACY_SUBJECT=1`` in the environment to fall
    back to the pre-LD2 format if admin inbox filter rules depended
    on it.
    """
    name = (lead.get("name") or "Website Visitor").strip()
    if os.environ.get("LEAD_ADMIN_LEGACY_SUBJECT") == "1":
        interest = (lead.get("service_interest") or "").strip() \
            or "Get a Free Quote"
        return f"New Lead: {name} — {interest}"
    source = _source_label(lead.get("source"))
    return f"New lead — {name} · {source}"


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
                       tenant_id: str, lead_id: str,
                       text: Optional[str] = None) -> None:
    """Fire-and-forget send + audit trail. Never raises."""
    try:
        from services.email.resend_adapter import send as _send_email
        result = await _send_email(
            to=to, subject=subject, html=html, text=text,
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
        # Phase LD2 · Feb 2026 — signature fix: the helper takes
        # ``db`` first (the pre-LD2 call site dropped it and always
        # got ``{}`` via the outer except).
        branding = await get_effective_business_settings(
            db, tid, absolutize=True,
        ) or {}
    except Exception:  # pragma: no cover
        branding = {}
    subject = _compose_subject(lead)
    html = _compose_email_html(lead=lead, app_url=app_url,
                                  branding=branding, tenant=tenant)
    text = _compose_email_text(lead=lead, app_url=app_url,
                                  branding=branding, tenant=tenant)
    # Phase EMAIL-MIGRATE · Batch 3 · Feb-2026 — DB-first passthrough.
    # The composed ``html`` above is stashed on the ctx as the
    # ``{{LEAD_ADMIN_INNER_HTML}}`` merge tag.  The DB row's body
    # then wraps / repositions it — by default the row body is
    # exactly ``{{LEAD_ADMIN_INNER_HTML}}`` so no visual change.
    # A tenant that has edited the row to add e.g. a compliance
    # footer sees their chrome + the composed inner HTML.
    try:
        from services.marketing_template_lookup import (
            get_template_with_global_fallback,
        )
        from services.marketing.merge_tags import render_template
        tpl = await get_template_with_global_fallback(
            "lead_admin_notification_email", tid or None,
        )
        if tpl and tpl.get("body"):
            ctx = {
                "tenant": tenant,
                "customer": {},
                "lead": lead,
                "lead_name": lead.get("name") or "",
                "lead_admin_inner_html": html,
            }
            rendered_body, _ = render_template(
                tpl["body"], ctx, missing="empty",
            )
            if rendered_body:
                html = rendered_body
    except Exception as exc:  # noqa: BLE001 — defensive
        logger.warning(
            "[lead-admin-fanout] DB template render failed — using "
            "hardcoded composed HTML tenant=%s lead=%s: %s",
            tid, lid, exc,
        )
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
            tenant_id=tid, lead_id=lid, text=text,
        )
        queued.append(addr)
    return {"queued": len(queued), "recipients": queued}
