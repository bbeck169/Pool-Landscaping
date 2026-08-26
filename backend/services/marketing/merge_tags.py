"""Phase 9 · Feb 2026 — Canonical merge-tag registry + renderer.

Central catalogue of every merge tag the marketing / transactional
send-time code can substitute at render time. Ships two public entry
points:

* ``MERGE_TAGS`` — the registry (list of dicts). Grouped by
  ``category`` for the UI palette; every entry has a stable
  ``token`` (UPPERCASE_SNAKE), a ``label``, a ``description``, and a
  ``resolver(ctx)`` callable that returns the substituted string.
* ``render_template(body, ctx, missing="empty")`` — the renderer.
  Accepts BOTH ``{{TOKEN}}`` and ``{{ token }}`` styles, case-
  insensitive, whitespace-tolerant, never raises on unknown tokens.
* ``render_context(...)`` — helper that assembles the ``ctx`` dict
  from the caller's Mongo docs (recipient customer, tenant, invoice,
  etc.). Every send-time code path should call this helper so tag
  behavior is uniform across M2 / M5c / portal / referrals / etc.

The old ``services/marketing/render.py`` Mustache renderer keeps
working for legacy ``{{customer.first_name}}`` tags — Phase 9 layers
UPPERCASE tags on top without removing the legacy path.
"""
from __future__ import annotations

import logging
import os
import re
from datetime import date, datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("pool_crm.merge_tags")

_TAG_RE = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_.]*)\s*\}\}")


def _safe_str(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    return str(v)


def _customer_name_parts(customer: Dict[str, Any]) -> Tuple[str, str]:
    name = _safe_str(customer.get("name") or "").strip()
    if not name:
        return "", ""
    parts = name.split(None, 1)
    return (parts[0], parts[1] if len(parts) > 1 else "")


def _open_balance(customer: Dict[str, Any]) -> str:
    v = customer.get("open_balance") or customer.get("balance_due") or 0
    try:
        return f"${float(v):,.2f}"
    except (TypeError, ValueError):
        return "$0.00"


# ═══════════════════════════ Resolvers ═══════════════════════════════
def _res(ctx_key: str, sub_key: str, transform: Optional[Callable] = None):
    """Factory: return a resolver that pulls ``ctx[ctx_key][sub_key]``
    (or an empty string) and optionally transforms it."""
    def _r(ctx: Dict[str, Any]) -> str:
        obj = ctx.get(ctx_key) or {}
        val = obj.get(sub_key) if isinstance(obj, dict) else None
        s = _safe_str(val)
        if transform:
            try:
                return transform(s, ctx)
            except Exception:
                return ""
        return s
    return _r


def _customer_first(ctx: Dict[str, Any]) -> str:
    """First name, or salutation fallback ``"there"`` per Phase 21
    Addition · Feb 2026 spec so customer-facing bodies never render an
    empty greeting when the customer record is missing a name."""
    c = ctx.get("customer") or {}
    first_field = _safe_str(c.get("first_name")).strip()
    if first_field:
        return first_field
    from_name = _customer_name_parts(c)[0]
    if from_name:
        return from_name
    return "there"


def _customer_last(ctx: Dict[str, Any]) -> str:
    c = ctx.get("customer") or {}
    last_field = _safe_str(c.get("last_name")).strip()
    if last_field:
        return last_field
    return _customer_name_parts(c)[1]


def _customer_full(ctx: Dict[str, Any]) -> str:
    """Full name — prefers ``first_name + " " + last_name`` when both
    exist, then the stored ``name`` field, then the first-name fallback,
    finally the email local-part (Phase 21 Addition spec)."""
    c = ctx.get("customer") or {}
    first = _safe_str(c.get("first_name")).strip()
    last = _safe_str(c.get("last_name")).strip()
    if first and last:
        return f"{first} {last}"
    if first:
        return first
    stored = _safe_str(c.get("name")).strip()
    if stored:
        return stored
    email = _safe_str(c.get("email"))
    if email and "@" in email:
        return email.split("@", 1)[0]
    return ""


# ─── Batch 12D · Feb 2026 — missing-tag polish additions ──────────────
def _customer_id(ctx: Dict[str, Any]) -> str:
    return _safe_str((ctx.get("customer") or {}).get("id"))


def _customer_street(ctx: Dict[str, Any]) -> str:
    """Alias for ``CUSTOMER_ADDRESS`` — reads either
    ``customer.address_line_1`` (Phase 8+ contact schema) or
    ``customer.address`` (legacy single-string field)."""
    c = ctx.get("customer") or {}
    return _safe_str(c.get("address_line_1") or c.get("address") or "")


def _tenant_timezone(ctx: Dict[str, Any]) -> str:
    t = ctx.get("tenant") or {}
    return _safe_str(t.get("timezone") or "America/Phoenix")


def _tenant_next_business_day(ctx: Dict[str, Any]) -> str:
    """Formatted next business day in the tenant's timezone. Skips
    Saturday + Sunday. Custom holidays live on
    ``tenant.business_holidays`` as a list of ``"YYYY-MM-DD"`` strings.
    Returned as ``"Mon, Feb 09"`` — the same format as ``TODAY``."""
    from zoneinfo import ZoneInfo
    from datetime import timedelta, datetime as _dt
    tz_name = _tenant_timezone(ctx) or "America/Phoenix"
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo("America/Phoenix")
    today_local = _dt.now(tz).date()
    holidays = set((ctx.get("tenant") or {}).get("business_holidays") or [])
    d = today_local + timedelta(days=1)
    for _ in range(14):   # cap the search — 2-week runway is generous
        if d.weekday() < 5 and d.isoformat() not in holidays:
            return d.strftime("%a, %b %d")
        d += timedelta(days=1)
    return d.strftime("%a, %b %d")


def _invoice_pay_url(ctx: Dict[str, Any]) -> str:
    """Portal-authenticated pay URL — customer signs in, then lands on
    the invoice detail with the Pay Now modal available. Never
    embeds a token; safe to include in emails that also mention
    login credentials.

    Phase 21 · Feb 2026 — base URL is resolved via
    ``services.tenant_urls.resolve_primary_app_domain`` so a
    per-tenant ``settings.primary_app_domain`` overrides the env
    default (e.g. once ``app.plofv.com`` is live).
    """
    inv = ctx.get("invoice") or {}
    inv_id = _safe_str(inv.get("id") or inv.get("invoice_id"))
    if not inv_id:
        return ""
    try:
        from services.tenant_urls import resolve_primary_app_domain
        base = resolve_primary_app_domain(ctx.get("tenant") or {})
    except Exception:
        base = (os.environ.get("APP_PUBLIC_URL")
                 or os.environ.get("PUBLIC_FRONTEND_ORIGIN")
                 or "").rstrip("/")
    if not base:
        return ""
    return f"{base}/portal/invoices/{inv_id}"


def _invoice_pay_magic_url(ctx: Dict[str, Any]) -> str:
    """Public magic-link pay URL — no login required. Uses whatever
    ``ctx['invoice_pay_link']`` the caller (e.g. the invoice send
    path) already built via
    ``services.pay_link_builder.build_invoice_pay_link``. Falls back
    to the portal URL if no magic link was provided."""
    return (_safe_str(ctx.get("invoice_pay_link"))
             or _invoice_pay_url(ctx))


def _estimate_accept_url(ctx: Dict[str, Any]) -> str:
    """Public magic-link accept URL for the estimate viewer. Reads
    ``ctx['estimate_accept_link']`` when populated by the estimate
    send path; falls back to the (already-registered)
    ``ESTIMATE_LINK`` value on ``ctx['estimate']['view_url']``."""
    if ctx.get("estimate_accept_link"):
        return _safe_str(ctx.get("estimate_accept_link"))
    est = ctx.get("estimate") or {}
    return _safe_str(est.get("view_url") or est.get("public_url") or "")


def _customer_balance(ctx: Dict[str, Any]) -> str:
    return _open_balance(ctx.get("customer") or {})


def _company_name(ctx: Dict[str, Any]) -> str:
    """Company display name. Phase 21 · Feb 2026 — prefers
    ``tenant.settings.business_card.company_name`` (the source of truth
    for the admin-editable brand) and falls back to legacy
    ``tenant.name`` so pre-rebrand tenants keep working."""
    t = ctx.get("tenant") or {}
    settings = t.get("settings") or {}
    card = settings.get("business_card") or {}
    return _safe_str(card.get("company_name") or t.get("name") or "")


def _invoice_amount(ctx: Dict[str, Any]) -> str:
    """Phase 21 · Feb 2026 · Addition — INVOICE_AMOUNT resolves the
    target invoice's ``total_cents`` to a formatted ``$X.YY`` string.
    Empty string when no invoice is in context (or the field is
    missing)."""
    inv = ctx.get("invoice") or {}
    cents = inv.get("total_cents")
    if cents is None:
        return ""
    try:
        return f"${float(cents) / 100.0:,.2f}"
    except (TypeError, ValueError):
        return ""


def _job_date(ctx: Dict[str, Any]) -> str:
    """JOB_DATE formats the job's ``scheduled_date`` in the tenant's
    timezone. Phase 27 · Feb 2026 — updated format to
    ``"Mon, Jan 15, 2026"`` (adds explicit year) so recipients don't
    have to guess the year on visits scheduled across a year boundary.
    Returns empty string when no job / no date."""
    from zoneinfo import ZoneInfo
    from datetime import datetime as _dt
    job = ctx.get("job") or {}
    raw = (job.get("scheduled_date") or job.get("scheduled_at")
           or job.get("scheduled_start") or job.get("date") or "")
    if not raw:
        return ""
    tz_name = _tenant_timezone(ctx) or "America/Phoenix"
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo("America/Phoenix")
    try:
        s = str(raw)
        if len(s) == 10:  # YYYY-MM-DD
            dt = _dt.strptime(s, "%Y-%m-%d")
        else:
            dt = _dt.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            return dt.strftime("%a, %b %d, %Y")
        return dt.astimezone(tz).strftime("%a, %b %d, %Y")
    except Exception:
        return ""


def _job_time(ctx: Dict[str, Any]) -> str:
    """JOB_TIME formats the job's scheduled time. Phase 27 · Feb 2026
    — updated to render a time window ``"9:00 AM – 11:00 AM"`` when
    both a start and end are available. Falls back to the single
    start time when only one is present."""
    from zoneinfo import ZoneInfo
    from datetime import datetime as _dt, timedelta as _td
    job = ctx.get("job") or {}
    tz_name = _tenant_timezone(ctx) or "America/Phoenix"
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo("America/Phoenix")

    def _fmt(dt_val: "_dt") -> str:
        # ``%-I`` is POSIX-only; fall back to stripping a leading zero.
        try:
            return dt_val.strftime("%-I:%M %p")
        except (ValueError, AttributeError):
            return dt_val.strftime("%I:%M %p").lstrip("0")

    def _parse(x: Any) -> Optional["_dt"]:
        if not x:
            return None
        try:
            dt = _dt.fromisoformat(str(x).replace("Z", "+00:00"))
            if dt.tzinfo is not None:
                dt = dt.astimezone(tz)
            return dt
        except Exception:
            return None

    start = _parse(job.get("scheduled_at") or job.get("start_at")
                   or job.get("scheduled_start"))
    end = _parse(job.get("scheduled_end") or job.get("end_at"))
    if not end and start:
        dur = job.get("duration_minutes") or job.get("duration_mins")
        if isinstance(dur, (int, float)) and dur > 0:
            end = start + _td(minutes=int(dur))
    if start and end and end > start:
        return f"{_fmt(start)} – {_fmt(end)}"
    if start:
        return _fmt(start)

    # Fallback — HH:MM string on scheduled_time.
    t_only = job.get("scheduled_time") or job.get("time")
    if t_only:
        try:
            parts = str(t_only).split(":")
            hh = int(parts[0])
            mm = int(parts[1]) if len(parts) > 1 else 0
            suffix = "AM" if hh < 12 else "PM"
            h12 = ((hh + 11) % 12) + 1
            return f"{h12}:{mm:02d} {suffix}"
        except Exception:
            return ""
    return ""


# ─── Phase 27 · Feb 2026 — CUSTOMER_ADDRESS full-line resolver ──────────
def _customer_address_full(ctx: Dict[str, Any]) -> str:
    """CUSTOMER_ADDRESS renders the customer's service address as a
    single line ``"street, city, state zip"``. Falls back to any
    individual component present. Reads Phase 8+ ``address_line_1``
    first, then the legacy single-string ``address`` field. Empty
    when the customer has no address stored."""
    c = ctx.get("customer") or {}
    street = _safe_str(c.get("address_line_1") or c.get("address") or "").strip()
    city = _safe_str(c.get("city") or "").strip()
    state = _safe_str(c.get("state") or "").strip()
    zip_code = _safe_str(c.get("zip") or c.get("postal_code") or "").strip()
    # If ``address`` is already a full formatted line and no split
    # parts are available, use it verbatim so we don't double-append.
    if street and not any([city, state, zip_code]) and "," in street:
        return street
    tail_parts: List[str] = []
    if city:
        tail_parts.append(city)
    if state and zip_code:
        tail_parts.append(f"{state} {zip_code}")
    elif state:
        tail_parts.append(state)
    elif zip_code:
        tail_parts.append(zip_code)
    tail = ", ".join(tail_parts)
    if street and tail:
        return f"{street}, {tail}"
    return street or tail


# ─── Phase 27 · Feb 2026 — Service Report content resolvers ─────────────
def _service_report_chemicals_added(ctx: Dict[str, Any]) -> str:
    """CHEMICALS_ADDED — HTML unordered list of chemicals the tech
    added on the visit (name + quantity + unit). Empty string when
    no service_report in scope or no chemicals were logged."""
    sr = ctx.get("service_report") or {}
    if not isinstance(sr, dict):
        return ""
    rows = sr.get("chemicals_added") or []
    lines: List[str] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        name = _safe_str(r.get("chemical") or r.get("name") or "").strip()
        qty = r.get("quantity") if r.get("quantity") is not None else r.get("amount")
        unit = _safe_str(r.get("unit") or "").strip()
        raw_label = _safe_str(r.get("raw_label") or "").strip()
        if raw_label and (name or True):
            label = f"{raw_label} of {name}".strip() if name else raw_label
        elif name and qty not in (None, "", 0):
            label = f"{qty} {unit} of {name}".strip() if unit else f"{qty} {name}".strip()
        elif name:
            label = name
        else:
            continue
        lines.append(f"<li>{label}</li>")
    if not lines:
        return ""
    return ('<ul style="margin:8px 0;padding-left:20px;line-height:1.6;">'
            + "".join(lines) + "</ul>")


def _service_report_chemical_readings(ctx: Dict[str, Any]) -> str:
    """CHEMICAL_READINGS — HTML table of chemistry readings the tech
    recorded (pH, chlorine, alkalinity, calcium, cyanuric acid …).
    Empty string when no service_report in scope or all readings
    are null/blank."""
    sr = ctx.get("service_report") or {}
    if not isinstance(sr, dict):
        return ""
    readings = sr.get("chemical_readings") or []
    rows: List[str] = []
    for r in readings:
        if not isinstance(r, dict):
            continue
        val = r.get("value")
        if val in (None, ""):
            continue
        name = _safe_str(r.get("name") or r.get("key") or "").strip()
        if not name:
            continue
        unit = _safe_str(r.get("unit") or "").strip()
        display = f"{val} {unit}".strip() if unit else f"{val}"
        rows.append(
            f'<tr><td style="padding:4px 12px 4px 0;color:#555">{name}</td>'
            f'<td style="padding:4px 0;font-weight:600">{display}</td></tr>'
        )
    if not rows:
        return ""
    return ('<table cellspacing="0" style="margin:8px 0;border-collapse:collapse;">'
            + "".join(rows) + "</table>")


def _service_report_checklist(ctx: Dict[str, Any]) -> str:
    """CHECKLIST — HTML unordered list of checklist items the tech
    marked complete. Empty string when no service_report in scope or
    the checklist is empty / all-unchecked."""
    sr = ctx.get("service_report") or {}
    if not isinstance(sr, dict):
        return ""
    items = sr.get("checklist_items") or []
    lines: List[str] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        if not it.get("checked"):
            continue
        label = _safe_str(it.get("label") or "").strip()
        if not label:
            continue
        lines.append(f'<li style="list-style:none;">✓ {label}</li>')
    if not lines:
        return ""
    return ('<ul style="margin:8px 0;padding-left:0;line-height:1.6;">'
            + "".join(lines) + "</ul>")


# ─── Phase 22 · Feb 2026 · Addition — SERVICE_RECORD_IMAGES ─────────────
# Renders the technician's service-visit photos as 200x200 clickable
# thumbnails inside outbound emails. Each thumbnail links to the public
# portal (``/portal/service/{public_uuid}``) so recipients can view the
# full-size image without a login. NEVER exposes customer PII — the
# public portal endpoint enforces redaction independently.
#
# Empty-string substitution when:
#   * no ``service_report`` in context, OR
#   * the report has no ``public_uuid`` (unsubmitted / legacy), OR
#   * the report has zero public (non-internal) photos.

_SERVICE_IMAGE_PRIVATE_TAGS = {"internal", "issue", "private"}
_SERVICE_IMAGE_THUMB_SIZE = 200


def _service_record_public_photos(sr: Dict[str, Any]) -> List[Dict[str, Any]]:
    photos = sr.get("photos") or []
    out: List[Dict[str, Any]] = []
    for p in photos:
        if not isinstance(p, dict):
            continue
        tags = p.get("tags") or []
        if isinstance(tags, list) and any(
                str(t).lower() in _SERVICE_IMAGE_PRIVATE_TAGS for t in tags):
            continue
        url = str(p.get("url") or p.get("public_url") or p.get("uri") or "")
        if not url:
            continue
        out.append({"url": url,
                    "thumbnail_url": p.get("thumbnail_url")
                                       or p.get("thumb_url") or url})
    return out


def _service_record_public_videos(sr: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Phase 27 · Feb 2026 — same shape as ``_service_record_public_photos``
    but for the ``videos`` list. Skips private/issue-tagged entries and
    drops rows without a poster (nothing to embed in an email)."""
    out: List[Dict[str, Any]] = []
    for v in (sr.get("videos") or []):
        if not isinstance(v, dict):
            continue
        tags = v.get("tags") or []
        if isinstance(tags, list) and any(
                str(t).lower() in _SERVICE_IMAGE_PRIVATE_TAGS for t in tags):
            continue
        url = str(v.get("url") or v.get("public_url") or "")
        poster = str(v.get("poster_url") or v.get("thumbnail_url") or "")
        if not url or not poster:
            # Email HTML cannot render a video inline; the poster
            # thumbnail IS the click target, so skip poster-less rows.
            continue
        out.append({"url": url, "poster_url": poster})
    return out


def _service_record_images(ctx: Dict[str, Any]) -> str:
    """Phase 28 · Feb 2026 — slider-preview rewrite. Renders a
    "first-3-big + counter tile" pattern instead of the old flat grid.

    Layout rules:
        * 0 media → empty string (unchanged)
        * 1 photo → single 300x300 tile
        * 2-3 media → all at 200x200
        * 4+ media → first 3 at 200x200 + a counter tile
          "View N more" that links to the same portal URL

    Photos and videos share the "first-3" pool so a report with
    ``12 photos + 2 videos`` renders as ``3 tiles + "View 11 more"``
    per the spec. Each tile — including the counter — links to the
    public portal at ``/portal/service/{public_uuid}``.

    Uses inline-CSS table layout for maximum email-client
    compatibility (Outlook / Gmail / Apple Mail all render nested
    tables reliably; flex is spotty in older clients).
    """
    sr = ctx.get("service_report") or {}
    if not isinstance(sr, dict):
        return ""
    public_uuid = sr.get("public_uuid")
    if not public_uuid:
        return ""
    # Require job context so we never render a stray tag when the sender
    # is not in a service-report scope (per spec §5).
    job = ctx.get("job") or {}
    if not (isinstance(job, dict) and job.get("id")):
        return ""
    photos = _service_record_public_photos(sr)
    videos = _service_record_public_videos(sr)
    if not photos and not videos:
        return ""
    # Resolve public base URL — prefers tenant override, then env fallback.
    try:
        from services.tenant_urls import resolve_primary_app_domain
        base = resolve_primary_app_domain(ctx.get("tenant") or {})
    except Exception:
        base = (os.environ.get("APP_PUBLIC_URL") or "").rstrip("/")
    if not base:
        # No public URL → thumbnails would 404 when clicked. Substitute
        # empty rather than emit a broken link.
        return ""
    link = f"{base.rstrip('/')}/portal/service/{public_uuid}"

    # Combined media pool preserving order — photos then videos.
    media: List[Dict[str, Any]] = []
    for p in photos:
        media.append({"kind": "photo",
                      "img": p["thumbnail_url"],
                      "alt": "Service photo"})
    for v in videos:
        media.append({"kind": "video",
                      "img": v["poster_url"],
                      "alt": "Service video"})
    total = len(media)

    # Sizing rule — 1 photo = 300x300, everything else = 200x200.
    if total == 1 and media[0]["kind"] == "photo":
        tile_size = 300
    else:
        tile_size = _SERVICE_IMAGE_THUMB_SIZE  # 200

    max_visible = 3 if total > 3 else total
    visible = media[:max_visible]
    hidden_count = total - max_visible

    def _tile(item: Dict[str, Any]) -> str:
        img_html = (
            f'<img src="{item["img"]}" alt="{item["alt"]}" '
            f'width="{tile_size}" height="{tile_size}" '
            f'style="display:block;width:{tile_size}px;'
            f'height:{tile_size}px;object-fit:cover;'
            f'border-radius:6px;border:1px solid #e5e7eb;"/>'
        )
        if item["kind"] == "video":
            # Play-icon overlay pinned to the centre — inline table
            # centering so clients without CSS positioning still show
            # the arrow.
            img_html = (
                f'<span style="display:inline-block;position:relative;'
                f'line-height:0;width:{tile_size}px;height:{tile_size}px;">'
                f'{img_html}'
                f'<span style="position:absolute;top:50%;left:50%;'
                f'transform:translate(-50%,-50%);width:44px;height:44px;'
                f'border-radius:50%;background:rgba(0,0,0,0.65);color:#fff;'
                f'display:inline-block;text-align:center;line-height:44px;'
                f'font-size:20px;'
                f'font-family:system-ui,-apple-system,sans-serif;">'
                f'&#9654;</span></span>'
            )
        return (
            f'<td style="padding:0 4px;">'
            f'<a href="{link}" target="_blank" rel="noopener" '
            f'style="text-decoration:none;color:#0f6ed1;">{img_html}</a>'
            f'</td>'
        )

    def _counter_tile(count: int) -> str:
        return (
            f'<td style="padding:0 4px;">'
            f'<a href="{link}" target="_blank" rel="noopener" '
            f'style="text-decoration:none;color:#0f6ed1;'
            f'display:inline-block;width:{tile_size}px;height:{tile_size}px;'
            f'background:#1f2937;color:#fff;border-radius:6px;'
            f'border:1px solid #111827;text-align:center;'
            f'font-family:system-ui,-apple-system,sans-serif;">'
            f'<table role="presentation" cellspacing="0" cellpadding="0" '
            f'style="width:100%;height:{tile_size}px;">'
            f'<tr><td style="text-align:center;color:#fff;'
            f'vertical-align:middle;font-size:15px;font-weight:600;'
            f'line-height:1.3;">+{count}<br/>View {count} more</td></tr>'
            f'</table></a></td>'
        )

    parts: List[str] = [
        '<table role="presentation" cellspacing="0" cellpadding="0" '
        'style="margin:12px 0;border-collapse:separate;"><tr>'
    ]
    for item in visible:
        parts.append(_tile(item))
    if hidden_count > 0:
        parts.append(_counter_tile(hidden_count))
    parts.append("</tr></table>")
    return "".join(parts)


def _tech_name(ctx: Dict[str, Any]) -> str:
    """Phase 21 · Feb 2026 · Addition — TECH_NAME resolves the assigned
    tech's display name. Cascades: ``ctx['tech']['name'] →
    ctx['technician']['name'] → ctx['job']['technician_name'] →
    ctx['employee']['name'] → """""" (empty)``."""
    for key in ("tech", "technician"):
        obj = ctx.get(key) or {}
        n = _safe_str(obj.get("name") or obj.get("display_name") or "")
        if n:
            return n
    job = ctx.get("job") or {}
    n = _safe_str(job.get("technician_name") or job.get("tech_name") or "")
    if n:
        return n
    emp = ctx.get("employee") or {}
    return _safe_str(emp.get("name") or "")


def _company_email(ctx: Dict[str, Any]) -> str:
    t = ctx.get("tenant") or {}
    return _safe_str(t.get("support_email") or t.get("email") or "")


def _company_phone(ctx: Dict[str, Any]) -> str:
    t = ctx.get("tenant") or {}
    return _safe_str(t.get("support_phone_number") or t.get("phone") or "")


def _current_month(ctx: Dict[str, Any]) -> str:
    return date.today().strftime("%B")


def _current_year(ctx: Dict[str, Any]) -> str:
    return str(date.today().year)


def _today(ctx: Dict[str, Any]) -> str:
    return date.today().strftime("%b %d, %Y")


def _portal_link(ctx: Dict[str, Any]) -> str:
    base = (os.environ.get("APP_PUBLIC_URL") or "").rstrip("/")
    email = _safe_str((ctx.get("customer") or {}).get("email"))
    if not base:
        return ""
    return f"{base}/portal/login" + (f"?email={email}" if email else "")


def _unsubscribe_link(ctx: Dict[str, Any]) -> str:
    base = (os.environ.get("APP_PUBLIC_URL") or "").rstrip("/")
    email = _safe_str((ctx.get("customer") or {}).get("email"))
    return f"{base}/unsubscribe?email={email}" if base and email else ""


def _invoice_number(ctx: Dict[str, Any]) -> str:
    inv = ctx.get("invoice") or {}
    return _safe_str(inv.get("invoice_number") or inv.get("id") or "")[:8]


def _invoice_total(ctx: Dict[str, Any]) -> str:
    inv = ctx.get("invoice") or {}
    try:
        return f"${float(inv.get('total') or 0):,.2f}"
    except (TypeError, ValueError):
        return "$0.00"


def _invoice_tax(ctx: Dict[str, Any]) -> str:
    inv = ctx.get("invoice") or {}
    try:
        return f"${float(inv.get('tax') or 0):,.2f}"
    except (TypeError, ValueError):
        return "$0.00"


def _invoice_due(ctx: Dict[str, Any]) -> str:
    inv = ctx.get("invoice") or {}
    return _safe_str(inv.get("due_date") or "")[:10]


def _estimate_total(ctx: Dict[str, Any]) -> str:
    est = ctx.get("estimate") or {}
    try:
        return f"${float(est.get('total') or 0):,.2f}"
    except (TypeError, ValueError):
        return "$0.00"


# Phase 11 · Feb 2026 — Equipment Service Tracker resolvers. Resolve
# against ``ctx['equipment_tracker']`` — outside that scope they
# resolve empty, which lands the token in ``unresolved_tokens`` when
# ``missing="placeholder"`` mode is used by the frontend banner.
def _equipment_type(ctx: Dict[str, Any]) -> str:
    et = ctx.get("equipment_tracker") or {}
    return _safe_str(et.get("type_label") or "")


def _equipment_last_cleaned_date(ctx: Dict[str, Any]) -> str:
    et = ctx.get("equipment_tracker") or {}
    return _safe_str(et.get("last_cleaned_at_pretty") or et.get("last_cleaned_at") or "")


def _equipment_due_date(ctx: Dict[str, Any]) -> str:
    et = ctx.get("equipment_tracker") or {}
    return _safe_str(et.get("due_at_pretty") or et.get("due_at") or "")


def _equipment_interval_months(ctx: Dict[str, Any]) -> str:
    et = ctx.get("equipment_tracker") or {}
    v = et.get("interval_months")
    try:
        return str(int(v)) if v is not None else ""
    except (TypeError, ValueError):
        return ""


# Phase 10 · Feb 2026 — Referral credit resolvers. Resolve against
# ``ctx['referral']`` — outside that scope they resolve empty and
# land in ``unresolved_tokens`` when ``missing="placeholder"``.
def _referral_friend_name(ctx: Dict[str, Any]) -> str:
    r = ctx.get("referral") or {}
    return _safe_str(r.get("friend_first_name") or r.get("friend_name") or "")


def _referral_credit_amount(ctx: Dict[str, Any]) -> str:
    r = ctx.get("referral") or {}
    cents = r.get("credit_amount_cents")
    if cents is None:
        return ""
    try:
        return f"${float(cents) / 100.0:,.2f}"
    except (TypeError, ValueError):
        return ""


def _referral_eligible_date(ctx: Dict[str, Any]) -> str:
    r = ctx.get("referral") or {}
    return _safe_str(r.get("eligible_at_pretty") or r.get("eligible_at") or "")


def _customer_credit_balance(ctx: Dict[str, Any]) -> str:
    c = ctx.get("customer") or {}
    cents = c.get("credits_balance_cents")
    if cents is None:
        return ""
    try:
        return f"${float(cents) / 100.0:,.2f}"
    except (TypeError, ValueError):
        return ""


# ─── Feb 2026 · Portal magic-link merge tags ──────────────────────────
# Two customer-facing tags that render an auto-login URL. On first
# reference inside a render, the resolver mints a portal magic-link
# JWT (14-day TTL) using ``services.portal_magic_links`` and caches
# the resulting URL on the ctx so subsequent occurrences reuse the
# same URL — a template that references the tag 3 times still mints
# ONE JWT.
#
# Contract highlights (see /app/memory/portal_magic_links.md):
#   * Scope: CUSTOMER_PORTAL_LOGIN_LINK → ``portal_home``
#            SERVICE_RECORD_LINK       → ``job_view``
#   * TTL: 14 days on both (override of the scope defaults in
#     ``portal_magic_links``, which use shorter TTLs for door-hanger
#     / invoice paths that don't route through the merge-tag catalog).
#   * Send-path override: callers may pre-populate
#     ``ctx['customer_portal_login_link']`` / ``ctx['service_record_link']``
#     and the resolver returns those verbatim — this matches the
#     existing pattern used by ``INVOICE_PAY_MAGIC_URL`` /
#     ``ADD_CARD_LINK`` and lets send paths mint outside the render
#     pipeline when they need a different TTL.
#   * Empty-string fail-safe: any missing dep (no ``APP_PUBLIC_URL``,
#     no ``customer.id`` / ``tenant.id``, mint failure) → empty
#     string. Token never appears as a literal ``{{...}}`` in the
#     rendered body.
#   * Fallback cascade: ``SERVICE_RECORD_LINK`` with no ``job.id``
#     in scope cascades to ``CUSTOMER_PORTAL_LOGIN_LINK`` (auto-
#     login to portal home) rather than empty — matches the
#     ``INVOICE_PAY_MAGIC_URL → INVOICE_PAY_URL`` precedent.
_PORTAL_MAGIC_TTL_HOURS = 14 * 24


def _customer_portal_login_link(ctx: Dict[str, Any]) -> str:
    """Auto-login magic URL that lands the recipient on
    ``/portal/home``. See module docstring for the full contract.
    """
    # 1. Send-path override wins.
    override = _safe_str(ctx.get("customer_portal_login_link") or "")
    if override:
        return override
    # 2. Mint from ctx.
    customer = ctx.get("customer") or {}
    tenant = ctx.get("tenant") or {}
    customer_id = _safe_str(customer.get("id"))
    tenant_id = _safe_str(tenant.get("id"))
    if not (customer_id and tenant_id):
        return ""
    base = (os.environ.get("APP_PUBLIC_URL") or "").rstrip("/")
    if not base:
        return ""
    try:
        # Deferred import — keeps ``merge_tags`` importable in
        # environments where ``config.JWT_SECRET`` isn't set (e.g.
        # docs generation, catalog introspection).
        from services.portal_magic_links import build_portal_home_url
        url = build_portal_home_url(
            base, customer_id, tenant_id,
            ttl_hours=_PORTAL_MAGIC_TTL_HOURS,
            preview=bool(ctx.get("_is_preview")),
        )
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning(
            "[merge_tags] CUSTOMER_PORTAL_LOGIN_LINK mint failed for "
            "customer=%s tenant=%s: %s",
            customer_id, tenant_id, exc,
        )
        return ""
    # Cache on ctx so re-references in the same render reuse the URL.
    ctx["customer_portal_login_link"] = url
    return url


def _service_record_link(ctx: Dict[str, Any]) -> str:
    """Auto-login magic URL that lands the recipient on the specific
    service-record page (``/portal/service-reports/{sr_id}`` — the
    sr_id is looked up server-side by the interstitial from
    ``tenant_id`` + ``job_id`` in the JWT payload). Cascades to
    :func:`_customer_portal_login_link` when no ``job.id`` is in
    scope so senders still get *some* CTA in the rendered body.
    """
    # 1. Send-path override wins.
    override = _safe_str(ctx.get("service_record_link") or "")
    if override:
        return override
    # 2. Mint from ctx (needs customer.id + tenant.id + job.id).
    customer = ctx.get("customer") or {}
    tenant = ctx.get("tenant") or {}
    job = ctx.get("job") or {}
    customer_id = _safe_str(customer.get("id"))
    tenant_id = _safe_str(tenant.get("id"))
    job_id = _safe_str(job.get("id"))
    if customer_id and tenant_id and job_id:
        base = (os.environ.get("APP_PUBLIC_URL") or "").rstrip("/")
        if base:
            try:
                from services.portal_magic_links import build_job_view_url
                url = build_job_view_url(
                    base, customer_id, job_id, tenant_id,
                    ttl_hours=_PORTAL_MAGIC_TTL_HOURS,
                    preview=bool(ctx.get("_is_preview")),
                )
                ctx["service_record_link"] = url
                return url
            except Exception as exc:  # pragma: no cover — defensive
                logger.warning(
                    "[merge_tags] SERVICE_RECORD_LINK mint failed for "
                    "customer=%s job=%s tenant=%s: %s",
                    customer_id, job_id, tenant_id, exc,
                )
    # 3. Cascade fallback → auto-login to portal home.
    logger.debug(
        "[merge_tags] SERVICE_RECORD_LINK cascaded to "
        "CUSTOMER_PORTAL_LOGIN_LINK (no job.id in ctx or mint failed)"
    )
    return _customer_portal_login_link(ctx)


# ═══════════════════════════ Catalogue ═══════════════════════════════
MERGE_TAGS: List[Dict[str, Any]] = [
    # ─── Job / Service
    {"token": "SERVICE_NAME", "label": "Service Name",
     "category": "Job",
     "description": "The service being performed — pulled from the job's "
                     "service_template.name (or recurring template name), "
                     "falling back to service_type / job title.",
     "resolver": lambda ctx: (
        ((ctx or {}).get("job") or {}).get("service_template", {}).get("name")
        or ((ctx or {}).get("job") or {}).get("service_name")
        or ((ctx or {}).get("job") or {}).get("service_type")
        or ((ctx or {}).get("job") or {}).get("title")
        or ((ctx or {}).get("service_name") or "")
     )},
    {"token": "SERVICE_TITLE", "label": "Service Title",
     "category": "Job",
     "description": "Title of the service, e.g., 'Weekly Pool Cleaning'. "
                     "Prefers ``service_template.title`` over ``.name``.",
     "resolver": lambda ctx: (
        ((ctx or {}).get("job") or {}).get("service_template", {}).get("title")
        or ((ctx or {}).get("job") or {}).get("service_template", {}).get("name")
        or ((ctx or {}).get("job") or {}).get("service_name")
        or ((ctx or {}).get("job") or {}).get("title")
        or ((ctx or {}).get("service_title") or "")
     )},
    {"token": "CUSTOMER_FIRST_NAME", "label": "First Name",
     "category": "Customer", "description": "The recipient customer's first name.",
     "resolver": _customer_first},
    {"token": "CUSTOMER_LAST_NAME", "label": "Last Name",
     "category": "Customer", "description": "The recipient customer's last name.",
     "resolver": _customer_last},
    {"token": "CUSTOMER_FULL_NAME", "label": "Full Name",
     "category": "Customer", "description": "The customer's full name as stored.",
     "resolver": _customer_full},
    {"token": "CUSTOMER_EMAIL", "label": "Email",
     "category": "Customer", "description": "The customer's email address.",
     "resolver": _res("customer", "email")},
    {"token": "CUSTOMER_PHONE", "label": "Phone",
     "category": "Customer", "description": "The customer's phone number.",
     "resolver": _res("customer", "phone")},
    {"token": "CUSTOMER_CELL", "label": "Mobile",
     "category": "Customer", "description": "The customer's mobile / cell.",
     "resolver": _res("customer", "phone")},
    {"token": "CUSTOMER_ACCOUNT_BALANCE", "label": "Account Balance",
     "category": "Customer", "description": "Formatted open balance in USD.",
     "resolver": _customer_balance},
    {"token": "CUSTOMER_ADDRESS", "label": "Street Address",
     "category": "Customer",
     "description": ("Customer's service address as a single line — "
                       "``street, city, state zip``. Phase 27 · Feb "
                       "2026 upgrade concatenates the split components "
                       "so recipients get the complete mailing address "
                       "on one line."),
     "resolver": _customer_address_full},
    {"token": "CUSTOMER_CITY", "label": "City", "category": "Customer",
     "description": "City parsed from the customer's address.",
     "resolver": _res("customer", "city")},
    {"token": "CUSTOMER_STATE", "label": "State", "category": "Customer",
     "description": "State parsed from the customer's address.",
     "resolver": _res("customer", "state")},
    {"token": "CUSTOMER_ZIP", "label": "ZIP", "category": "Customer",
     "description": "ZIP code parsed from the customer's address.",
     "resolver": _res("customer", "zip")},
    # Batch 12D · Feb 2026 — polish additions.
    {"token": "CUSTOMER_STREET", "label": "Street (alias)",
     "category": "Customer",
     "description": ("Alias for CUSTOMER_ADDRESS. Reads "
                       "``address_line_1`` (Phase 8+ contact schema) "
                       "or falls back to the legacy ``address`` field."),
     "resolver": _customer_street},
    {"token": "CUSTOMER_ID", "label": "Customer ID",
     "category": "Customer",
     "description": ("Raw customer record id — useful for admin-facing "
                       "templates and internal audit tools. Not for "
                       "customer-facing bodies."),
     "resolver": _customer_id},

    # ─── Company
    {"token": "COMPANY_NAME", "label": "Company Name",
     "category": "Company", "description": "Your company's name.",
     "resolver": _company_name},
    {"token": "COMPANY_OWNER_FIRST_NAME", "label": "Owner First",
     "category": "Company", "description": "Owner's first name from tenant record.",
     "resolver": _res("tenant", "owner_first_name")},
    {"token": "COMPANY_OWNER_LAST_NAME", "label": "Owner Last",
     "category": "Company", "description": "Owner's last name from tenant record.",
     "resolver": _res("tenant", "owner_last_name")},
    {"token": "COMPANY_PHONE", "label": "Company Phone",
     "category": "Company", "description": "Company support phone number.",
     "resolver": _company_phone},
    {"token": "COMPANY_EMAIL", "label": "Company Email",
     "category": "Company", "description": "Company support email.",
     "resolver": _company_email},
    {"token": "COMPANY_WEBSITE", "label": "Company Website",
     "category": "Company", "description": "Company website URL.",
     "resolver": _res("tenant", "website")},
    # Batch 12D · Feb 2026 — expose tenant timezone + next business day
    # to send-time templates (used by scheduling + reminder bodies).
    {"token": "TENANT_TIMEZONE", "label": "Tenant Timezone",
     "category": "Company",
     "description": ("IANA timezone name for the tenant, fallback "
                       "``America/Phoenix``. Useful when signing off "
                       "an email with a time-of-day hint."),
     "resolver": _tenant_timezone},
    {"token": "TENANT_NEXT_BUSINESS_DAY", "label": "Next Business Day",
     "category": "Company",
     "description": ("Formatted next business day in the tenant's "
                       "timezone. Skips Sat/Sun and any dates listed "
                       "on ``tenant.business_holidays``."),
     "resolver": _tenant_next_business_day},

    # ─── Estimate
    {"token": "ESTIMATE_TOTAL", "label": "Estimate Total",
     "category": "Estimate", "description": "Formatted total of the estimate.",
     "resolver": _estimate_total},
    {"token": "ESTIMATE_NUMBER", "label": "Estimate Number",
     "category": "Estimate", "description": "Short id of the estimate.",
     "resolver": lambda c: _safe_str((c.get("estimate") or {}).get("id"))[:8]},
    {"token": "ESTIMATE_LINK", "label": "Estimate Link",
     "category": "Estimate", "description": "Public-facing link to the estimate.",
     "resolver": lambda c: _safe_str((c.get("estimate") or {}).get("public_url"))},
    {"token": "ESTIMATE_EDIT_LINK", "label": "Estimate Edit Link",
     "category": "Estimate", "description": "Admin edit link to the estimate.",
     "resolver": lambda c: _safe_str((c.get("estimate") or {}).get("edit_url"))},
    {"token": "ESTIMATE_CHANGES", "label": "Estimate Changes",
     "category": "Estimate", "description": "Human summary of latest estimate changes.",
     "resolver": lambda c: _safe_str((c.get("estimate") or {}).get("changes_summary"))},

    # ─── Invoice
    {"token": "INVOICE_TOTAL", "label": "Invoice Total",
     "category": "Invoice", "description": "Formatted invoice total.",
     "resolver": _invoice_total},
    {"token": "INVOICE_TAX", "label": "Invoice Tax",
     "category": "Invoice", "description": "Formatted invoice tax amount.",
     "resolver": _invoice_tax},
    {"token": "INVOICE_NUMBER", "label": "Invoice Number",
     "category": "Invoice", "description": "Short invoice identifier.",
     "resolver": _invoice_number},
    {"token": "INVOICE_DUE_DATE", "label": "Invoice Due Date",
     "category": "Invoice", "description": "Invoice due date (YYYY-MM-DD).",
     "resolver": _invoice_due},
    {"token": "INVOICES_LINKS", "label": "All Invoice Links",
     "category": "Invoice", "description": "Bullet list of pay links.",
     "resolver": lambda c: _safe_str((c.get("invoice") or {}).get("all_links_html"))},
    # Batch 12D · Feb 2026 — canonical single-invoice pay URLs.
    {"token": "INVOICE_PAY_URL", "label": "Pay URL (portal)",
     "category": "Invoice",
     "description": ("Portal-authenticated URL to the invoice detail "
                       "page. Requires the customer to log in — safe "
                       "to reuse in emails that also mention creds."),
     "resolver": _invoice_pay_url},
    {"token": "INVOICE_PAY_MAGIC_URL", "label": "Pay URL (magic link)",
     "category": "Invoice",
     "description": ("Public magic-link pay URL — no login required. "
                       "Requires the send path to have populated "
                       "``ctx['invoice_pay_link']`` via the pay-link "
                       "builder; falls back to the portal URL when "
                       "unavailable."),
     "resolver": _invoice_pay_magic_url},

    {"token": "ESTIMATE_ACCEPT_URL", "label": "Estimate Accept URL",
     "category": "Estimate",
     "description": ("Public magic-link accept URL for the estimate "
                       "viewer. Populated by the estimate send path "
                       "via ``ctx['estimate_accept_link']``; falls "
                       "back to ESTIMATE_LINK when absent."),
     "resolver": _estimate_accept_url},

    # ─── Payment
    {"token": "PAYMENT_AMOUNT", "label": "Payment Amount",
     "category": "Payment", "description": "Formatted payment amount.",
     "resolver": lambda c: (
         f"${float((c.get('payment') or {}).get('amount') or 0):,.2f}"
     )},
    {"token": "PAYMENT_METHOD", "label": "Payment Method",
     "category": "Payment", "description": "Card brand / ACH label.",
     "resolver": _res("payment", "method")},
    {"token": "PAYMENT_DATE", "label": "Payment Date",
     "category": "Payment", "description": "Payment received date (YYYY-MM-DD).",
     "resolver": lambda c: _safe_str((c.get("payment") or {}).get("date"))[:10]},
    {"token": "RECEIPT_LINK", "label": "Receipt Link (Customer)",
     "category": "Payment", "description": "Customer-facing receipt URL.",
     "resolver": _res("payment", "receipt_url")},
    {"token": "RECEIPT_ADMIN_LINK", "label": "Receipt Link (Admin)",
     "category": "Payment", "description": "Admin console receipt URL.",
     "resolver": _res("payment", "admin_receipt_url")},

    # ─── Portal
    {"token": "CUSTOMER_PORTAL_LINK", "label": "Portal Link",
     "category": "Portal", "description": "Customer portal login URL.",
     "resolver": _portal_link},
    # ─── Feb 2026 · Portal magic-link auto-login tags. Additive —
    # ``CUSTOMER_PORTAL_LINK`` still points at the plain login page
    # so legacy templates keep their old behavior.
    {"token": "CUSTOMER_PORTAL_LOGIN_LINK", "label": "Portal Auto-Login Link",
     "category": "Portal",
     "description": ("Public auto-login magic link that lands the "
                       "recipient on their portal home without entering "
                       "credentials. Scope ``portal_home``; TTL 14 days. "
                       "Empty when no ``customer.id``/``tenant.id`` is in "
                       "scope. Callers may pre-populate "
                       "``ctx['customer_portal_login_link']`` to override "
                       "the on-demand mint."),
     "resolver": _customer_portal_login_link},
    {"token": "SERVICE_RECORD_LINK", "label": "Service Record Auto-Login Link",
     "category": "Portal",
     "description": ("Public auto-login magic link that lands the "
                       "recipient on the specific service-record page "
                       "(``/portal/service-reports/{sr_id}`` — the sr_id "
                       "is resolved server-side from the JWT). Scope "
                       "``job_view``; TTL 14 days. Cascades to "
                       "``CUSTOMER_PORTAL_LOGIN_LINK`` when no ``job.id`` "
                       "is in scope so senders still get a valid CTA."),
     "resolver": _service_record_link},
    {"token": "CUSTOMER_PORTAL_ADD_CREDIT_CARD_LINK", "label": "Add Card Link",
     "category": "Portal", "description": "Deep-link to add a credit card.",
     "resolver": lambda c: (_portal_link(c) or "") + "#add-card"},
    {"token": "UNSUBSCRIBE", "label": "Unsubscribe Link",
     "category": "Portal", "description": "Per-recipient unsubscribe URL.",
     "resolver": _unsubscribe_link},
    {"token": "REVIEW_PAGE", "label": "Review Page",
     "category": "Portal", "description": "Public review-request page URL.",
     "resolver": _res("tenant", "google_review_url")},
    {"token": "DOCUMENT_LINK", "label": "Document Link",
     "category": "Portal", "description": "Attached document URL.",
     "resolver": _res("document", "url")},
    {"token": "WORK_REQUEST_FORM", "label": "Work Request Form",
     "category": "Portal", "description": "URL of the public work request form.",
     "resolver": _res("tenant", "work_request_form_url")},

    # ─── Event
    {"token": "EVENT_TITLE", "label": "Event Title",
     "category": "Event", "description": "Title of the scheduled event.",
     "resolver": _res("event", "title")},
    {"token": "EVENT_DATE", "label": "Event Date",
     "category": "Event", "description": "Scheduled date of the event.",
     "resolver": lambda c: _safe_str((c.get("event") or {}).get("date"))[:10]},
    {"token": "EVENT_PROPERTY_ADDRESS", "label": "Event Property Address",
     "category": "Event", "description": "Property address for the event.",
     "resolver": _res("event", "property_address")},
    {"token": "EVENT_SCHEDULED_TIME", "label": "Event Time",
     "category": "Event", "description": "Scheduled time (HH:MM).",
     "resolver": _res("event", "time")},
    {"token": "EVENT_NOTES", "label": "Event Notes",
     "category": "Event", "description": "Free-form notes on the event.",
     "resolver": _res("event", "notes")},

    # ─── Employee
    {"token": "EMPLOYEE_FIRST_NAME", "label": "Employee First",
     "category": "Employee", "description": "Assigned employee's first name.",
     "resolver": lambda c: _customer_name_parts(c.get("employee") or {})[0]},
    {"token": "EMPLOYEE_LAST_NAME", "label": "Employee Last",
     "category": "Employee", "description": "Assigned employee's last name.",
     "resolver": lambda c: _customer_name_parts(c.get("employee") or {})[1]},
    {"token": "CALL_NOTES", "label": "Call Notes",
     "category": "Employee", "description": "Latest call notes summary.",
     "resolver": _res("event", "call_notes")},

    # ─── System
    {"token": "CURRENT_MONTH", "label": "Current Month",
     "category": "System", "description": "Full name of the current month.",
     "resolver": _current_month},
    {"token": "CURRENT_YEAR", "label": "Current Year",
     "category": "System", "description": "Current 4-digit year.",
     "resolver": _current_year},
    {"token": "TODAY", "label": "Today's Date",
     "category": "System", "description": "Today's date, Mon DD YYYY.",
     "resolver": _today},
    {"token": "NOTES_TO_DISPATCHER", "label": "Notes to Dispatcher",
     "category": "System", "description": "Free-form dispatcher notes on the job.",
     "resolver": _res("event", "dispatch_notes")},
    {"token": "PROPERTY_NOT_SERVICED_REASON", "label": "Not Serviced Reason",
     "category": "System", "description": "Reason a scheduled service was skipped.",
     "resolver": _res("event", "not_serviced_reason")},

    # ─── Equipment (Phase 11 · Feb 2026)
    # Resolves against ``ctx['equipment_tracker']``. Empty (and added
    # to the unresolved-tokens list) when rendered outside a tracker
    # context — e.g. a generic invoice email that accidentally embeds
    # ``{{EQUIPMENT_TYPE}}``.
    {"token": "EQUIPMENT_TYPE", "label": "Equipment Type",
     "category": "Equipment",
     "description": 'Human-readable equipment label — "Filter", "Salt Cell", etc.',
     "resolver": _equipment_type},
    {"token": "EQUIPMENT_LAST_CLEANED_DATE", "label": "Last Cleaned",
     "category": "Equipment",
     "description": "Date the equipment was last cleaned, formatted per tenant.",
     "resolver": _equipment_last_cleaned_date},
    {"token": "EQUIPMENT_DUE_DATE", "label": "Due Date",
     "category": "Equipment",
     "description": "Next scheduled cleaning date, formatted per tenant.",
     "resolver": _equipment_due_date},
    {"token": "EQUIPMENT_INTERVAL_MONTHS", "label": "Interval (months)",
     "category": "Equipment",
     "description": "Cadence in whole months (e.g. 3 for filters, 12 for salt cells).",
     "resolver": _equipment_interval_months},

    # ─── Referral credits (Phase 10 · Feb 2026)
    # Resolves against ``ctx['referral']`` (per-referral scope). The
    # customer balance tag reads from ``ctx['customer']`` (already
    # populated by ``render_context``).
    {"token": "REFERRAL_FRIEND_NAME", "label": "Referred Friend",
     "category": "Referrals",
     "description": "First name of the referred customer.",
     "resolver": _referral_friend_name},
    {"token": "REFERRAL_CREDIT_AMOUNT", "label": "Credit Amount",
     "category": "Referrals",
     "description": "Referral credit amount, formatted (e.g. $25.00).",
     "resolver": _referral_credit_amount},
    {"token": "REFERRAL_ELIGIBLE_DATE", "label": "Eligible Date",
     "category": "Referrals",
     "description": "Date the referral first became eligible for credit.",
     "resolver": _referral_eligible_date},
    {"token": "CUSTOMER_CREDIT_BALANCE", "label": "Credit Balance",
     "category": "Referrals",
     "description": "Customer's current account credit balance, formatted.",
     "resolver": _customer_credit_balance},

    # ─── Add-card magic link (Phase 12 · Feb 2026)
    # Reads ``ctx['add_card_link']`` — populated by the send path in
    # ``routers.customers.send_card_add_link`` when firing the
    # transactional email + SMS.
    {"token": "ADD_CARD_LINK", "label": "Add-Card Link",
     "category": "Payments",
     "description": ("Public magic link to the SetupIntent page for "
                       "saving a card. Expires in 30 days."),
     "resolver": lambda ctx: _safe_str(ctx.get("add_card_link") or "")},

    # ─── Batch 12C · Feb 2026 — Ambiguous Stripe-match digest tags.
    # Populated by ``services.stripe_customer_sync_cron._fire_ambiguous_alert``
    # when a scheduled sync surfaces > 0 rows admins need to resolve.
    {"token": "AMBIGUOUS_MATCH_COUNT", "label": "Ambiguous Match Count",
     "category": "Payments",
     "description": ("Number of CRM customers whose Stripe cross-"
                       "reference produced multiple candidates."),
     "resolver": lambda ctx: _safe_str(ctx.get("ambiguous_match_count") or 0)},
    {"token": "AMBIGUOUS_MATCH_SAMPLE", "label": "Ambiguous Match Sample",
     "category": "Payments",
     "description": ("Comma-joined preview of the first 3 ambiguous "
                       "customer names, for the digest email/SMS body."),
     "resolver": lambda ctx: _safe_str(
         ctx.get("ambiguous_match_sample") or "")},

    # ─── Phase 21 · Feb 2026 · Addition — merge-tag parity fills.
    # Populated at send time by the caller when a job / invoice /
    # technician is in scope. Missing context → empty string (never
    # the raw ``{{TOKEN}}`` literal).
    {"token": "INVOICE_AMOUNT", "label": "Invoice Amount",
     "category": "Invoice",
     "description": ("Formatted invoice amount derived from "
                       "``invoice.total_cents`` (e.g. ``$135.00``). "
                       "Empty when no invoice is in context."),
     "resolver": _invoice_amount},
    {"token": "JOB_DATE", "label": "Job Date",
     "category": "Job",
     "description": ("Scheduled job date formatted in the tenant's "
                       "timezone as ``Mon, Feb 24``. Empty when no "
                       "job / date is in context."),
     "resolver": _job_date},
    {"token": "JOB_TIME", "label": "Job Time",
     "category": "Job",
     "description": ("Scheduled job time in the tenant's timezone "
                       "as ``2:00 PM``. Empty when no job / time is "
                       "in context."),
     "resolver": _job_time},
    {"token": "TECH_NAME", "label": "Technician Name",
     "category": "Employee",
     "description": ("Assigned technician's display name — reads "
                       "``ctx['tech']``, ``ctx['technician']``, "
                       "``job.technician_name``, or ``ctx['employee']`` "
                       "in that order."),
     "resolver": _tech_name},

    # ─── Phase 22 · Feb 2026 · Addition — service-record photo gallery
    # for outbound emails. Renders 200x200 clickable thumbnails; each
    # links to the public ``/portal/service/{public_uuid}`` page. Empty
    # string when no job / no service_report / no photos.
    {"token": "SERVICE_RECORD_IMAGES", "label": "Service Record Images",
     "category": "Job",
     "description": ("HTML block of 200x200 thumbnails of the tech's "
                       "service-report photos. Each thumbnail links to a "
                       "public portal page (no login required). Empty "
                       "when there's no service report in scope, no "
                       "photos on the visit, or the report is missing a "
                       "public UUID."),
     "resolver": _service_record_images},

    # ─── Phase 27 · Feb 2026 · Addition — service-report content tags.
    # Pull directly from ``ctx['service_report']``. Empty string when
    # no service_report in scope OR no data recorded, so callers can
    # embed the tags in templates that fire for both pool + landscape
    # visits without emitting orphan headings on empty visits.
    {"token": "CHEMICALS_ADDED", "label": "Chemicals Added",
     "category": "Job",
     "description": ("HTML list of chemicals the tech added on the "
                       "visit (name + quantity + unit). Empty when no "
                       "chemicals were logged."),
     "resolver": _service_report_chemicals_added},
    {"token": "CHEMICAL_READINGS", "label": "Chemical Readings",
     "category": "Job",
     "description": ("HTML table of chemistry readings recorded on "
                       "the visit (pH, chlorine, alkalinity, calcium, "
                       "cyanuric acid, etc.). Empty when nothing was "
                       "tested."),
     "resolver": _service_report_chemical_readings},
    {"token": "CHECKLIST", "label": "Service Checklist",
     "category": "Job",
     "description": ("HTML list of checklist items the tech marked "
                       "complete on the visit. Empty when the "
                       "checklist has nothing checked."),
     "resolver": _service_report_checklist},
]

_TAG_INDEX: Dict[str, Callable] = {t["token"].upper(): t["resolver"]
                                        for t in MERGE_TAGS}


# ═══════════════════════════ Renderer ════════════════════════════════
def render_template(body: str, ctx: Optional[Dict[str, Any]] = None,
                     missing: str = "empty") -> Tuple[str, List[str]]:
    """Render ``body`` by substituting every ``{{TOKEN}}`` for its
    resolved value from ``ctx``.

    Returns ``(rendered_string, unresolved_tokens_list)``.

    * Case-insensitive: ``{{customer_first_name}}`` matches
      ``CUSTOMER_FIRST_NAME``.
    * Whitespace-tolerant: ``{{ CUSTOMER_FIRST_NAME }}`` is fine.
    * ``missing`` controls unknown-token behavior:
      * ``"empty"`` (default) → replaced with an empty string.
      * ``"placeholder"`` → replaced with ``[MISSING: TOKEN]``.
    * NEVER raises; a resolver that itself blows up produces an empty
      substitution and the token is added to the unresolved list.
    """
    if body is None:
        return "", []
    ctx = ctx or {}
    unresolved: List[str] = []

    def _sub(match: "re.Match[str]") -> str:
        raw = match.group(1)
        upper = raw.upper()

        # Phase 9D · Feb 2026 — cascade order (most-specific wins):
        #   1. Explicit flat-key override in the ctx (bare or flat-dotted).
        #      This lets legacy callers pass a precomputed value that
        #      would otherwise be masked by a catalog resolver's default.
        #   2. Nested-dotted lookup (``{{customer.first_name}}`` →
        #      ``ctx["customer"]["first_name"]``).
        #   3. Uppercase catalog resolver (Phase 9 canonical resolvers
        #      operate on the nested ctx shape).
        # A resolved value at any level short-circuits the cascade.

        # 1) Explicit flat-key override (bare or dotted string key).
        if isinstance(ctx, dict):
            for key in (raw, raw.lower()):
                if key in ctx:
                    v = ctx.get(key)
                    if v not in (None, ""):
                        return _safe_str(v)

        # 2) Nested-dotted lookup.
        if "." in raw:
            parts = raw.split(".")
            cursor: Any = ctx
            for p in parts:
                if isinstance(cursor, dict) and p in cursor:
                    cursor = cursor[p]
                else:
                    cursor = None
                    break
            if cursor not in (None, ""):
                return _safe_str(cursor)

        # 3) Uppercase catalog resolver.
        resolver = _TAG_INDEX.get(upper)
        if resolver is not None:
            try:
                val = resolver(ctx)
            except Exception:
                val = None
            if val not in (None, ""):
                return _safe_str(val)

        # Unresolved after full cascade.
        unresolved.append(upper)
        return "" if missing == "empty" else f"[MISSING: {upper}]"

    rendered = _TAG_RE.sub(_sub, body)
    return rendered, sorted(set(unresolved))


def render_context(*, customer: Optional[Dict[str, Any]] = None,
                    tenant: Optional[Dict[str, Any]] = None,
                    invoice: Optional[Dict[str, Any]] = None,
                    estimate: Optional[Dict[str, Any]] = None,
                    payment: Optional[Dict[str, Any]] = None,
                    employee: Optional[Dict[str, Any]] = None,
                    event: Optional[Dict[str, Any]] = None,
                    document: Optional[Dict[str, Any]] = None,
                    job: Optional[Dict[str, Any]] = None,
                    service_report: Optional[Dict[str, Any]] = None,
                    **extra: Any) -> Dict[str, Any]:
    """Build a render context dict from the caller's Mongo docs. Every
    Phase 9 send-time code path assembles its ctx via this helper so
    tag behavior stays uniform."""
    return {
        "customer": customer or {},
        "tenant": tenant or {},
        "invoice": invoice or {},
        "estimate": estimate or {},
        "payment": payment or {},
        "employee": employee or {},
        "event": event or {},
        "document": document or {},
        "job": job or {},
        "service_report": service_report or {},
        **extra,
    }


def catalog_grouped() -> Dict[str, List[Dict[str, Any]]]:
    """Return the merge-tag registry grouped by category, minus the
    resolver callables (JSON-serialisable). Used by
    ``GET /api/marketing/merge-tags``."""
    by_cat: Dict[str, List[Dict[str, Any]]] = {}
    for t in MERGE_TAGS:
        by_cat.setdefault(t["category"], []).append({
            "token": t["token"],
            "label": t["label"],
            "description": t["description"],
        })
    return by_cat
