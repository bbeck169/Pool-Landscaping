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
    # Feb-2026 · Task 3 · Invoices bypass portal — customer-facing
    # {{invoice_pay_url}} merge tag now emits a magic-link URL under
    # ``/i/<token>`` instead of the portal auto-login path. Callers
    # that already populate ``ctx['invoice_pay_link']`` win via
    # ``_invoice_pay_magic_url`` above; this branch is the fallback
    # when no explicit link was minted at send time (e.g. dunning
    # reminders processing legacy templates).
    try:
        from services.pay_link_builder import issue_invoice_magic_token
        tenant_id = ((ctx.get("tenant") or {}).get("id") or "")
        if tenant_id:
            token = issue_invoice_magic_token(inv_id, tenant_id, days=30)
            return f"{base}/i/{token}"
    except Exception:  # noqa: BLE001
        pass
    return f"{base}/i/{inv_id}"


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


_COMPANY_NAME_ULTIMATE_FALLBACK = "Your Service Provider"


def _company_name(ctx: Dict[str, Any]) -> str:
    """Company display name.

    Feb-2026 · Portal-invite merge-tag fix — widened the fallback
    chain so the resolver NEVER returns an empty string.  A blank
    company name in a customer-trust send (portal invite, password
    reset, invoice, etc.) is a data-integrity signal we prefer to
    surface via a WARN log + a human-readable placeholder rather
    than a literal ``{{COMPANY_NAME}}`` in the rendered body.

    Cascade order:

      1. ``tenant.settings.business_card.company_name`` — source of
         truth (admin editor at Settings → Business Card).
      2. ``tenant.settings.company_name`` — legacy nested field
         still populated by a handful of pre-rebrand seed rows.
      3. ``tenant.name`` — legacy root field.
      4. ``"Your Service Provider"`` — ultimate fallback; logs a
         WARN so ops can spot the broken tenant record.
    """
    t = ctx.get("tenant") or {}
    settings = t.get("settings") or {}
    card = settings.get("business_card") or {}
    for candidate in (card.get("company_name"),
                       settings.get("company_name"),
                       t.get("name")):
        val = _safe_str(candidate).strip()
        if val:
            return val
    logger.warning(
        "[merge_tags] COMPANY_NAME resolver fell through to ultimate"
        " fallback %r — tenant_id=%s slug=%s.  Fix Settings →"
        " Business Card → Company Name to remove this warning.",
        _COMPANY_NAME_ULTIMATE_FALLBACK,
        t.get("id"), t.get("slug"),
    )
    return _COMPANY_NAME_ULTIMATE_FALLBACK


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


# ─── Phase DOOR-HANGER · Feb 2026 — Job Photos gallery resolver ─────
# Renders a responsive CSS-grid gallery of clickable job photos. The
# resolver accepts BOTH the door-hanger shape (``resolve_photo_items``
# output — carries ``url_absolute``) AND the raw job-doc shape
# (``job.photos[]`` — each item carries ``id`` + optional ``url`` /
# ``data_url`` / base64 ``data``).  Empty string when the job has
# zero photos so the tag mirrors ``_dh_render_photos``'s no-orphan-
# section behaviour and is safe to embed in a template that fires
# on both photo-heavy and photo-less visits.
#
# Ctx key contract:
#   * ``ctx['_dh_job_photos']`` — send-path override list (canonical).
#     Underscore-prefixed so ``render_template``'s flat-key cascade
#     (which resolves ``{{JOB_PHOTOS}}`` → ``ctx['job_photos']`` when
#     that flat key exists) can't intercept a raw ``list`` and
#     stringify it before this resolver runs.
#   * ``ctx['job']['photos']`` — fallback for callers that only
#     pass a job doc (generic template previews, marketing UI test
#     renders, etc.).

_JOB_PHOTOS_HEADING_STYLE = (
    "margin:0 0 8px 0;font-size:16px;color:#0F172A;font-weight:600;"
)
_JOB_PHOTOS_CARD_STYLE = (
    "border-collapse:collapse;background:#FFFFFF;"
    "border:1px solid #E2E8F0;border-radius:8px;margin:12px 0;"
)
_JOB_PHOTOS_GRID_STYLE = (
    "display:grid;"
    "grid-template-columns:repeat(auto-fill,minmax(140px,1fr));"
    "gap:8px;margin:12px 0;"
)
_JOB_PHOTOS_THUMB_STYLE = (
    "width:100%;height:auto;max-height:140px;object-fit:cover;"
    "border-radius:6px;border:1px solid #ddd;"
)


def _job_photo_url(photo: Dict[str, Any]) -> str:
    """Extract the best available URL for a photo dict.

    Cascade order (matches the door hanger's historical shape first,
    then the PortalServiceDetail shape flagged in the DOOR-HANGER
    brief):
      1. ``url_absolute`` — door-hanger canonical (server-prefixed).
      2. ``url``          — PortalServiceDetail canonical.
      3. ``data_url``     — legacy data-URI capture.
      4. ``data``         — raw base64 payload (upgraded to data URI).
      5. ``uri``          — generic S3-ish location.
    """
    for key in ("url_absolute", "url", "data_url", "uri"):
        v = _safe_str((photo or {}).get(key)).strip()
        if v:
            return v
    raw = _safe_str((photo or {}).get("data")).strip()
    if raw:
        if raw.startswith("data:"):
            return raw
        # Assume PNG when the payload doesn't self-declare — mirrors
        # the door-hanger fixture shape used in
        # test_door_hanger_email_body.py.
        return f"data:image/png;base64,{raw}"
    return ""


def _job_photos_gallery(ctx: Dict[str, Any]) -> str:
    """DOOR-HANGER · Feb 2026 — Responsive CSS-grid photo gallery.

    Reads from ``ctx['_dh_job_photos']`` (send-path override — the
    door hanger's ``_build_door_hanger_email`` pre-populates this
    with the ``resolve_photo_items(job)`` output; the underscore
    prefix keeps the key out of ``render_template``'s flat-key
    cascade so ``{{JOB_PHOTOS}}`` reaches THIS resolver instead of
    being intercepted as a stringified list) first, then falls
    back to the raw ``ctx['job']['photos']`` list so generic
    templates that only pass a ``job`` doc still render.

    Zero photos → empty string. Empty-input mirroring keeps the
    existing "no photos = no photos section" contract in
    ``test_door_hanger_email_body.py``.
    """
    src = ctx.get("_dh_job_photos")
    if not src:
        src = ((ctx or {}).get("job") or {}).get("photos") or []
    if not isinstance(src, list):
        return ""
    thumbs: List[str] = []
    for i, p in enumerate(src):
        if not isinstance(p, dict):
            continue
        url = _job_photo_url(p)
        if not url:
            continue
        alt = _safe_str(p.get("label") or f"Job photo {i + 1}")
        # Basic HTML escaping for the alt (double-quote breaks the
        # attribute; other chars stay literal for parity with
        # ``_dh_render_photos``).
        alt = alt.replace('"', "&quot;")
        thumbs.append(
            f'<a href="{url}" target="_blank" rel="noopener" '
            f'style="display:block;">'
            f'<img src="{url}" alt="{alt}" '
            f'style="{_JOB_PHOTOS_THUMB_STYLE}"/></a>'
        )
    if not thumbs:
        return ""
    grid = (
        f'<div style="{_JOB_PHOTOS_GRID_STYLE}">'
        + "".join(thumbs)
        + '</div>'
    )
    # Section-shell wrapper — mirrors the ``_dh_section_heading +
    # _dh_card`` shape from ``routers.workstream_service_log`` so
    # existing test contracts asserting the "Service Photos" heading
    # + card boundaries keep matching.
    return (
        f'<table role="presentation" cellpadding="0" cellspacing="0" '
        f'border="0" width="100%" style="{_JOB_PHOTOS_CARD_STYLE}">'
        f'<tr><td style="padding:16px 24px;">'
        f'<h2 style="{_JOB_PHOTOS_HEADING_STYLE}">Service Photos</h2>'
        f'{grid}'
        f'</td></tr></table>'
    )


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


def _tenant_default_brand_field(tenant: Dict[str, Any], field: str) -> str:
    """Feb-2026 · Business Card defaults fallback.

    Consult ``routers.tenants._BUSINESS_CARD_DEFAULTS[<tenant.slug>]``
    when the tenant DB row + ``settings.business_card`` are both empty
    for ``field``. Keeps merge-tag renders realistic even when a
    fresh preview / disaster-recovery restore hasn't yet re-run the
    per-tenant seed. Falls back to empty string on any import
    hiccup so the render pipeline never crashes.
    """
    slug = _safe_str(tenant.get("slug"))
    if not slug:
        return ""
    try:
        from routers.tenants import _BUSINESS_CARD_DEFAULTS
    except Exception:
        return ""
    return _safe_str((_BUSINESS_CARD_DEFAULTS.get(slug) or {}).get(field) or "")


def _company_email(ctx: Dict[str, Any]) -> str:
    """Company support email.

    Feb-2026 · Aligned with the admin editor at Settings → Business
    Card, which writes to ``tenant.settings.business_card.email``.
    Cascades:

      1. ``settings.business_card.email`` — admin editor source-of-truth
      2. Legacy root ``support_email`` / ``email`` fields
      3. Per-tenant ``_BUSINESS_CARD_DEFAULTS[slug]["email"]`` fallback
         (keeps sends working after preview DB resets)
    """
    t = ctx.get("tenant") or {}
    settings = t.get("settings") or {}
    card = settings.get("business_card") or {}
    return _safe_str(card.get("email")
                     or t.get("support_email")
                     or t.get("email")
                     or _tenant_default_brand_field(t, "email"))


def _company_phone(ctx: Dict[str, Any]) -> str:
    """Company support phone.

    Feb-2026 · Same alignment as ``_company_email`` — prefers the
    Business Card editor's storage location and falls back through
    the legacy fields to ``_BUSINESS_CARD_DEFAULTS``.
    """
    t = ctx.get("tenant") or {}
    settings = t.get("settings") or {}
    card = settings.get("business_card") or {}
    return _safe_str(card.get("phone")
                     or t.get("support_phone_number")
                     or t.get("phone")
                     or _tenant_default_brand_field(t, "phone"))


def _company_website(ctx: Dict[str, Any]) -> str:
    """Company website URL.

    Feb-2026 · Aligned with the admin editor at Settings → Business
    Card, which writes to ``tenant.settings.business_card.website_url``.
    Cascades:

      1. ``settings.business_card.website_url``
      2. Legacy root ``website`` field
      3. Per-tenant ``_BUSINESS_CARD_DEFAULTS[slug]["website_url"]``

    Value returned verbatim — no auto ``https://`` prefix (template
    authors control href construction).
    """
    t = ctx.get("tenant") or {}
    settings = t.get("settings") or {}
    card = settings.get("business_card") or {}
    return _safe_str(card.get("website_url")
                     or card.get("website")
                     or t.get("website")
                     or _tenant_default_brand_field(t, "website_url"))


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
    # P0b Stage 2 S2-2 · Feb-2026 — Accept either the canonical
    # SINGULAR key ``credit_balance_cents`` (preferred, written by
    # the ``mutate_credit`` choke point via ``recompute_customer_
    # balance_denorm``) or the legacy PLURAL key ``credits_balance_
    # cents`` (deprecated — one caller in services/referral_watcher
    # still builds a ctx with it for the referral-credit email
    # template; left behind for one deprecation window). Both resolve
    # to the same cents value when the caller is honest about the
    # customer's current balance.
    c = ctx.get("customer") or {}
    cents = c.get("credit_balance_cents")
    if cents is None:
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
     "resolver": _company_website},
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

    # ─── Phase DOOR-HANGER · Feb 2026 — Job Photos gallery.
    # Renders a responsive CSS grid of clickable job photos.  Reads
    # from ``ctx['job_photos']`` (send-path pre-populated list of
    # ``resolve_photo_items(job)`` output — carries ``url_absolute``)
    # first, then falls back to ``ctx['job']['photos']`` (raw job
    # doc shape — carries ``url`` / ``data_url`` / ``data``).
    #
    # Zero photos → empty string (mirrors the pre-refactor
    # ``_dh_render_photos`` behaviour so tenants that keep the tag
    # in a template still get the "no photos = no orphan section"
    # semantics).
    {"token": "JOB_PHOTOS", "label": "Job Photos",
     "category": "Job",
     "description": ("Responsive CSS-grid gallery of the job's "
                       "photos.  Each thumbnail links to the "
                       "original high-res URL in a new tab.  Empty "
                       "string when the job has no photos."),
     "resolver": lambda ctx: _job_photos_gallery(ctx)},

    # ─── Phase DOOR-HANGER · Feb 2026 — Door Hanger section-injection
    # tags. Each resolver reads a pre-rendered HTML string that the
    # caller (``routers.workstream_service_log._build_door_hanger_email``)
    # stashes on ctx BEFORE calling ``render_template``. This keeps
    # the door hanger's business-logic-heavy sub-builders intact
    # (elevated-readings CTA, portal magic-link CTA, section-cards)
    # while making the template body itself editable in a
    # ``marketing_templates`` row.
    {"token": "DOOR_HANGER_HERO_HTML", "label": "Door Hanger — Hero",
     "category": "Door Hanger",
     "description": "Pre-rendered hero card (logo, greeting, service address, completed date).",
     "resolver": lambda ctx: _safe_str(ctx.get("dh_hero_html") or "")},
    {"token": "DOOR_HANGER_WATER_TEST_HTML", "label": "Door Hanger — Water Test",
     "category": "Door Hanger",
     "description": "Pre-rendered water-test readings table.",
     "resolver": lambda ctx: _safe_str(ctx.get("dh_water_test_html") or "")},
    # Phase DOOR-HANGER · Feb 2026 — friendly alias for
    # ``DOOR_HANGER_WATER_TEST_HTML``.  Same resolver, different
    # token so tenants who reposition the pre-rendered water-test
    # section in the Door Hanger template body can use the shorter
    # semantic name ``{{WATER_TEST_RESULTS}}``.  Documented in the
    # editable-templates palette under the same Door Hanger group.
    {"token": "WATER_TEST_RESULTS", "label": "Water Test Results (alias)",
     "category": "Door Hanger",
     "description": ("Alias for ``DOOR_HANGER_WATER_TEST_HTML``. "
                       "Renders the pre-rendered water-test readings "
                       "section so tenants can reposition it in the "
                       "editable Door Hanger template body."),
     "resolver": lambda ctx: _safe_str(ctx.get("dh_water_test_html") or "")},
    {"token": "DOOR_HANGER_ELEVATED_CTA_HTML", "label": "Door Hanger — Elevated CTA",
     "category": "Door Hanger",
     "description": "Pre-rendered elevated-readings follow-up CTA (empty for non-pool jobs / suppressed customers).",
     "resolver": lambda ctx: _safe_str(ctx.get("dh_elevated_cta_html") or "")},
    {"token": "DOOR_HANGER_CHEMICALS_HTML", "label": "Door Hanger — Chemicals Used",
     "category": "Door Hanger",
     "description": "Pre-rendered chemicals-used table.",
     "resolver": lambda ctx: _safe_str(ctx.get("dh_chemicals_html") or "")},
    {"token": "DOOR_HANGER_CHECKLIST_HTML", "label": "Door Hanger — Checklist",
     "category": "Door Hanger",
     "description": "Pre-rendered service-checklist card.",
     "resolver": lambda ctx: _safe_str(ctx.get("dh_checklist_html") or "")},
    {"token": "DOOR_HANGER_NOTES_HTML", "label": "Door Hanger — Notes",
     "category": "Door Hanger",
     "description": "Pre-rendered tech notes card.",
     "resolver": lambda ctx: _safe_str(ctx.get("dh_notes_html") or "")},
    {"token": "DOOR_HANGER_PORTAL_CTA_HTML", "label": "Door Hanger — Portal CTA",
     "category": "Door Hanger",
     "description": "Pre-rendered 'View Service Report in Portal' CTA (empty when portal link mint fails).",
     "resolver": lambda ctx: _safe_str(ctx.get("dh_portal_cta_html") or "")},
    {"token": "DOOR_HANGER_FOOTER_HTML", "label": "Door Hanger — Footer",
     "category": "Door Hanger",
     "description": "Pre-rendered footer (thank-you copy, company name, phone).",
     "resolver": lambda ctx: _safe_str(ctx.get("dh_footer_html") or "")},

    # ═════════════════════════════════════════════════════════════════
    # Phase EMAIL-MIGRATE · Batch 1 · Feb-2026 — Auth / Invites.
    # ─────────────────────────────────────────────────────────────────
    # Merge tags consumed by the batch-1 transactional email seeds:
    #   * auth_password_reset_email
    #   * admin_user_password_reset_email
    #   * signup_verify_code_email
    #   * onboarding_wizard_invite_email
    # Every resolver reads from a bare-flat ctx key populated by the
    # caller and falls back to an empty string when absent.  Bodies
    # that reference a missing tag render an empty inline — never a
    # literal ``{{TOKEN}}`` — matching the ``missing="empty"`` default
    # in ``render_template``.
    # ═════════════════════════════════════════════════════════════════
    {"token": "RESET_LINK", "label": "Password Reset Link",
     "category": "Auth",
     "description": ("Time-limited URL that lands the recipient on "
                       "the password-reset form.  Populated by the "
                       "caller with the freshly-minted token URL."),
     "resolver": lambda ctx: _safe_str(ctx.get("reset_link") or "")},
    {"token": "TEMP_PASSWORD", "label": "Temporary Password",
     "category": "Auth",
     "description": ("One-time temporary password issued by an admin "
                       "via the admin-driven password-reset flow.  "
                       "Never populated on the self-serve reset "
                       "flow (that flow uses ``RESET_LINK``)."),
     "resolver": lambda ctx: _safe_str(ctx.get("temp_password") or "")},
    {"token": "VERIFY_CODE", "label": "Signup Verify URL / Code",
     "category": "Auth",
     "description": ("Signup verification target — either a URL "
                       "(current signup flow) or a code (future flow). "
                       "Populated via ``ctx['verify_code']`` first, "
                       "then ``ctx['verify_url']`` as a fallback so "
                       "senders that thread only the URL still "
                       "resolve the tag."),
     "resolver": lambda ctx: _safe_str(
         ctx.get("verify_code") or ctx.get("verify_url") or "")},
    {"token": "ONBOARDING_LINK", "label": "Onboarding Invite Link",
     "category": "Auth",
     "description": ("Public link the invitee follows to accept an "
                       "onboarding invite / provisioning email.  "
                       "Populated via ``ctx['onboarding_link']`` "
                       "first, then ``ctx['accept_url']`` as a "
                       "fallback."),
     "resolver": lambda ctx: _safe_str(
         ctx.get("onboarding_link") or ctx.get("accept_url") or "")},
    {"token": "RECIPIENT_NAME", "label": "Recipient Name",
     "category": "Auth",
     "description": ("Display name of the email recipient — first "
                       "name preferred for greeting copy.  Populated "
                       "via ``ctx['recipient_name']`` first, then "
                       "``ctx['first_name']`` as a fallback so "
                       "callers can thread either shape."),
     "resolver": lambda ctx: _safe_str(
         ctx.get("recipient_name") or ctx.get("first_name") or "")},
    {"token": "RECIPIENT_EMAIL", "label": "Recipient Email",
     "category": "Auth",
     "description": ("Email address of the recipient.  Populated via "
                       "``ctx['recipient_email']`` first, then "
                       "``ctx['invited_email']`` (team-invite flow) "
                       "as a fallback."),
     "resolver": lambda ctx: _safe_str(
         ctx.get("recipient_email") or ctx.get("invited_email") or "")},
    {"token": "EXPIRY_LABEL", "label": "Link Expiry Label",
     "category": "Auth",
     "description": ("Human-readable expiry duration for a reset / "
                       "invite link (e.g. ``\"30 days\"`` or "
                       "``\"48 hours\"``).  Rendered verbatim in the "
                       "body copy."),
     "resolver": lambda ctx: _safe_str(ctx.get("expiry_label") or "")},
    {"token": "ACTOR_NAME", "label": "Actor Name",
     "category": "Auth",
     "description": ("Display name of the admin who triggered a "
                       "target-user action (e.g. the admin who reset "
                       "another user's password)."),
     "resolver": lambda ctx: _safe_str(ctx.get("actor_name") or "")},
    {"token": "LOGIN_URL", "label": "Login URL",
     "category": "Auth",
     "description": ("Absolute URL to the sign-in page.  Populated "
                       "by the send path — no on-demand mint here."),
     "resolver": lambda ctx: _safe_str(ctx.get("login_url") or "")},
    {"token": "ROLE", "label": "Assigned Role",
     "category": "Auth",
     "description": ("Team-member role assigned to an invitee "
                       "(e.g. ``\"technician\"``, ``\"office\"``)."),
     "resolver": lambda ctx: _safe_str(ctx.get("role") or "")},
    {"token": "BUSINESS_NAME", "label": "Business Name (alias)",
     "category": "Company",
     "description": ("Alias for ``COMPANY_NAME``.  Legacy "
                       "notification-template flows (signup verify, "
                       "team invite) referenced ``{business_name}`` "
                       "in the single-brace form — the alias keeps "
                       "the token names consistent when those "
                       "flows migrate to the double-brace catalog."),
     "resolver": _company_name},

    # ═════════════════════════════════════════════════════════════════
    # Phase EMAIL-MIGRATE · Batch 2 · Feb-2026 — Lead lifecycle.
    # ─────────────────────────────────────────────────────────────────
    # Merge tags consumed by the batch-2 transactional email seeds:
    #   * portal_service_request_admin_email
    #   * lead_thank_you_reply_email
    #   * lead_conversion_welcome_email
    #   * lead_internal_admin_alert_email
    #
    # Every resolver reads from a bare-flat ctx key populated by the
    # caller and falls back to an empty string when absent so a body
    # that references a missing tag renders an empty inline — never a
    # literal ``{{TOKEN}}``.
    # ═════════════════════════════════════════════════════════════════
    {"token": "LEAD_NAME", "label": "Lead — Name",
     "category": "Lead",
     "description": ("Display name of the inbound lead. Populated "
                       "via ``ctx['lead_name']`` first, then "
                       "``ctx['lead']['name']`` as a fallback."),
     "resolver": lambda ctx: _safe_str(
         ctx.get("lead_name")
         or (((ctx or {}).get("lead") or {}).get("name") or ""))},
    {"token": "LEAD_EMAIL", "label": "Lead — Email",
     "category": "Lead",
     "description": "Email address captured from the lead form.",
     "resolver": lambda ctx: _safe_str(
         ctx.get("lead_email")
         or (((ctx or {}).get("lead") or {}).get("email") or ""))},
    {"token": "LEAD_PHONE", "label": "Lead — Phone",
     "category": "Lead",
     "description": "Phone number captured from the lead form.",
     "resolver": lambda ctx: _safe_str(
         ctx.get("lead_phone")
         or (((ctx or {}).get("lead") or {}).get("phone") or ""))},
    {"token": "LEAD_SOURCE", "label": "Lead — Source",
     "category": "Lead",
     "description": ("Attribution channel for the lead (e.g. "
                       "``website``, ``google_ads``, ``referral``)."),
     "resolver": lambda ctx: _safe_str(
         ctx.get("lead_source")
         or (((ctx or {}).get("lead") or {}).get("source") or ""))},
    {"token": "LEAD_MESSAGE", "label": "Lead — Message",
     "category": "Lead",
     "description": ("Free-form message from the lead-capture form "
                       "(``message`` or ``service_interest``)."),
     "resolver": lambda ctx: _safe_str(ctx.get("lead_message") or "")},
    {"token": "LEAD_TIME_LABEL", "label": "Lead — Timestamp Label",
     "category": "Lead",
     "description": "Human-readable timestamp for the lead-created event.",
     "resolver": lambda ctx: _safe_str(ctx.get("lead_time_label") or "")},
    {"token": "LEAD_LINK", "label": "Lead — Detail URL",
     "category": "Lead",
     "description": "Admin URL that opens the lead detail page.",
     "resolver": lambda ctx: _safe_str(ctx.get("lead_link") or "")},
    {"token": "LEAD_REJECT_HEADER", "label": "Lead — Reject Header",
     "category": "Lead",
     "description": ("Pre-rendered banner emitted when the lead's "
                       "state is not in the tenant's serviced-states "
                       "list. Empty string when the lead is not "
                       "rejected — the section collapses cleanly."),
     "resolver": lambda ctx: _safe_str(ctx.get("lead_reject_header") or "")},
    {"token": "REJECT_STATE", "label": "Reject — State Code",
     "category": "Lead",
     "description": ("US state code that fell outside the tenant's "
                       "serviced-states list (e.g. ``\"CA\"``).  "
                       "Empty on the happy path."),
     "resolver": lambda ctx: _safe_str(ctx.get("reject_state") or "")},
    {"token": "SERVICE_TYPE", "label": "Service Type",
     "category": "Service Request",
     "description": ("Service type on the service-request payload "
                       "(``\"Pool Cleaning\"``, ``\"Landscaping\"``, "
                       "etc.)."),
     "resolver": lambda ctx: _safe_str(ctx.get("service_type") or "")},
    {"token": "REQUEST_DETAILS", "label": "Request Details",
     "category": "Service Request",
     "description": ("Free-form body of the service-request payload. "
                       "Rendered verbatim into the outbound admin "
                       "notification."),
     "resolver": lambda ctx: _safe_str(ctx.get("request_details") or "")},
    {"token": "PROPERTY_ADDRESS", "label": "Property Address",
     "category": "Service Request",
     "description": ("Free-form service address (``property.address`` "
                       "or ``lead.service_address``)."),
     "resolver": lambda ctx: _safe_str(ctx.get("property_address") or "")},
    {"token": "PREFERRED_DATE", "label": "Preferred Date",
     "category": "Service Request",
     "description": "Customer-preferred date on a service request.",
     "resolver": lambda ctx: _safe_str(ctx.get("preferred_date") or "")},
    {"token": "VIEW_REQUEST_LINK", "label": "View Request Link",
     "category": "Service Request",
     "description": ("Admin URL that opens the service-request "
                       "communication thread."),
     "resolver": lambda ctx: _safe_str(ctx.get("view_request_link") or "")},
    {"token": "TENANT_SERVICE_REQUEST_PHONE",
     "label": "Tenant — Service Request Phone",
     "category": "Company",
     "description": ("Number the tenant configured under "
                       "``settings.notifications.service_request_sms`` "
                       "for inbound service-request notifications. "
                       "Empty when unset — the DB body should collapse "
                       "the phone line entirely (PHONE-PURGE invariant)."),
     "resolver": lambda ctx: _safe_str(
         ctx.get("tenant_service_request_phone") or "")},
    {"token": "CUSTOMER_NAME", "label": "Customer — Name",
     "category": "Customer",
     "description": ("Display name of the customer (``customer.name`` "
                       "or ``customer.first_name``)."),
     "resolver": lambda ctx: _safe_str(
         ctx.get("customer_name")
         or (((ctx or {}).get("customer") or {}).get("name") or ""))},
    {"token": "CUSTOMER_EMAIL", "label": "Customer — Email",
     "category": "Customer",
     "description": ("Email address of the customer "
                       "(``customer.email``). Duplicate token under "
                       "the Lead-contact send-path category — same "
                       "resolver cascade."),
     "resolver": lambda ctx: _safe_str(
         ctx.get("customer_email")
         or (((ctx or {}).get("customer") or {}).get("email") or ""))},
    {"token": "CUSTOMER_PHONE", "label": "Customer — Phone",
     "category": "Customer",
     "description": ("Phone number of the customer "
                       "(``customer.phone``). Duplicate token under "
                       "the Lead-contact send-path category — same "
                       "resolver cascade."),
     "resolver": lambda ctx: _safe_str(
         ctx.get("customer_phone")
         or (((ctx or {}).get("customer") or {}).get("phone") or ""))},
    {"token": "PORTAL_LINK", "label": "Portal Login URL",
     "category": "Customer",
     "description": ("Absolute URL that lands the customer on their "
                       "portal login page, pre-populated with their "
                       "email when a magic link is available."),
     "resolver": lambda ctx: _safe_str(ctx.get("portal_link") or "")},

    # ═════════════════════════════════════════════════════════════════
    # Phase EMAIL-MIGRATE · Batch 3 · Feb-2026 — Internal ops + digests.
    # ─────────────────────────────────────────────────────────────────
    # Merge tags consumed by the batch-3 transactional email seeds:
    #   * quote_accepted_owner_email / quote_declined_owner_email
    #   * lead_admin_notification_email
    #   * equipment_tracker_weekly_reminder_email
    #   * tenant_billing_trial_reminder_email /
    #     tenant_billing_dunning_email
    # ═════════════════════════════════════════════════════════════════
    {"token": "QUOTE_LABEL", "label": "Quote — Doc Type Label",
     "category": "Quote",
     "description": ("Human-readable label for the estimate document "
                       "(\"Quote\", \"Estimate\", \"Proposal\")."),
     "resolver": lambda ctx: _safe_str(ctx.get("quote_label") or "")},
    {"token": "QUOTE_SHORT_ID", "label": "Quote — Short ID",
     "category": "Quote",
     "description": "First 8 chars of the quote UUID for compact display.",
     "resolver": lambda ctx: _safe_str(ctx.get("quote_short_id") or "")},
    {"token": "QUOTE_TOTAL", "label": "Quote — Total",
     "category": "Quote",
     "description": "Formatted dollar total for the quote.",
     "resolver": lambda ctx: _safe_str(ctx.get("quote_total") or "")},
    {"token": "QUOTE_HEADLINE", "label": "Quote — Headline",
     "category": "Quote",
     "description": ("Composed one-line summary "
                       "(``\"<customer> accepted <label> #<short>. \"``)."),
     "resolver": lambda ctx: _safe_str(ctx.get("quote_headline") or "")},
    {"token": "QUOTE_ADMIN_LINK", "label": "Quote — Admin URL",
     "category": "Quote",
     "description": "Admin URL that opens the quote/estimate detail page.",
     "resolver": lambda ctx: _safe_str(ctx.get("quote_admin_link") or "")},
    {"token": "LEAD_ADMIN_INNER_HTML", "label": "Lead Admin — Inner HTML",
     "category": "Lead",
     "description": ("Pre-rendered inner HTML for the canonical lead-"
                       "admin notification.  The Python builder still "
                       "composes the palette / header / dynamic sections; "
                       "the DB template body can wrap this block in any "
                       "additional chrome (e.g. tenant-specific "
                       "regulatory footer).  Default DB body is exactly "
                       "``{{LEAD_ADMIN_INNER_HTML}}`` so no chrome is "
                       "added unless the tenant edits the row."),
     "resolver": lambda ctx: _safe_str(ctx.get("lead_admin_inner_html") or "")},
    {"token": "ADMIN_NAME", "label": "Admin — Recipient Name (alias)",
     "category": "Auth",
     "description": ("Alias for ``RECIPIENT_NAME`` — the trial-reminder "
                       "and payment-failed on-disk templates use "
                       "``{admin_name}`` in the single-brace form. The "
                       "alias keeps token names consistent when those "
                       "bodies migrate to the double-brace catalog."),
     "resolver": lambda ctx: _safe_str(
         ctx.get("admin_name")
         or ctx.get("recipient_name")
         or ctx.get("first_name") or "")},
    {"token": "TRIAL_END_LOCAL", "label": "Trial End — Local Date",
     "category": "Billing",
     "description": ("Localised timestamp for when the tenant's "
                       "free trial ends (e.g. ``\"Feb 24, 2026 at "
                       "9:00 AM PST\"``)."),
     "resolver": lambda ctx: _safe_str(ctx.get("trial_end_local") or "")},
    {"token": "PLAN_AMOUNT", "label": "Plan — Amount",
     "category": "Billing",
     "description": ("Human-readable plan price (e.g. "
                       "``\"$249/month\"``)."),
     "resolver": lambda ctx: _safe_str(ctx.get("plan_amount") or "")},
    {"token": "CANCEL_LINK", "label": "Billing — Cancel URL",
     "category": "Billing",
     "description": "Admin URL to cancel the tenant's subscription.",
     "resolver": lambda ctx: _safe_str(ctx.get("cancel_link") or "")},
    {"token": "UPDATE_CARD_LINK", "label": "Billing — Update-card URL",
     "category": "Billing",
     "description": ("Admin URL to update the payment method on file "
                       "(surfaced in the dunning / payment-failed "
                       "email)."),
     "resolver": lambda ctx: _safe_str(ctx.get("update_card_link") or "")},

    # ═════════════════════════════════════════════════════════════════
    # Phase EMAIL-MIGRATE · Batch 4 · Feb-2026 — Job/finance
    # transactionals.  Registers merge tags consumed by:
    #   * job_completed_legacy_email
    #   * invoice_reminder_email
    #   * estimate_reminder_email
    #   * team_invite_email
    #   * tos_blast_email
    # ═════════════════════════════════════════════════════════════════
    {"token": "INVOICE_NUMBER", "label": "Invoice — Number",
     "category": "Finance",
     "description": ("Customer-facing invoice identifier "
                       "(``invoice_number`` → ``doc_number`` → id "
                       "short-form)."),
     "resolver": lambda ctx: _safe_str(ctx.get("invoice_number") or "")},
    {"token": "INVOICE_TOTAL", "label": "Invoice — Balance",
     "category": "Finance",
     "description": ("Outstanding balance on the invoice, formatted "
                       "as ``$1,234.56``."),
     "resolver": lambda ctx: _safe_str(ctx.get("invoice_total") or "")},
    {"token": "INVOICE_DUE_DATE", "label": "Invoice — Due Date",
     "category": "Finance",
     "description": "Localised due-date label for the reminder email.",
     "resolver": lambda ctx: _safe_str(ctx.get("invoice_due_date") or "")},
    {"token": "DAYS_OVERDUE", "label": "Invoice — Days Overdue",
     "category": "Finance",
     "description": ("Whole-number days past ``due_date`` (0 when "
                       "the invoice is not yet overdue)."),
     "resolver": lambda ctx: _safe_str(ctx.get("days_overdue") or "")},
    {"token": "PAY_LINK", "label": "Invoice — Pay Now URL",
     "category": "Finance",
     "description": ("Public pay-sheet URL built by "
                       "``services.pay_link_builder.build_pay_now_url``. "
                       "Never expires inside ``AppLayout`` — a stale "
                       "token routes to a friendly retry page rather "
                       "than the portal login screen."),
     "resolver": lambda ctx: _safe_str(ctx.get("pay_link") or "")},
    {"token": "ESTIMATE_NUMBER", "label": "Estimate — Number",
     "category": "Quote",
     "description": ("Short estimate identifier shown in the subject "
                       "line + body (duplicate of the Estimate-"
                       "category token, Quote-category send paths)."),
     "resolver": lambda ctx: _safe_str(ctx.get("estimate_number") or "")},
    {"token": "ESTIMATE_TOTAL", "label": "Estimate — Total",
     "category": "Quote",
     "description": ("Formatted total for the estimate (duplicate "
                       "of the Estimate-category token, Quote-"
                       "category send paths)."),
     "resolver": lambda ctx: _safe_str(ctx.get("estimate_total") or "")},
    {"token": "ESTIMATE_EXPIRES", "label": "Estimate — Expiry Label",
     "category": "Quote",
     "description": ("Human-readable expiration date for the estimate "
                       "(e.g. ``\"Mar 22, 2026\"``)."),
     "resolver": lambda ctx: _safe_str(ctx.get("estimate_expires") or "")},
    {"token": "ACCEPT_LINK", "label": "Estimate — Accept URL",
     "category": "Quote",
     "description": ("Customer-facing magic-link URL that lands on "
                       "the ``/e/estimate?token=…`` viewer."),
     "resolver": lambda ctx: _safe_str(ctx.get("accept_link") or "")},
    {"token": "INVITEE_NAME", "label": "Team — Invitee First Name",
     "category": "Team",
     "description": ("Display name of the team invitee. Populated via "
                       "``ctx['invitee_name']`` first, then falls back "
                       "to ``ctx['recipient_name']`` so callers that "
                       "thread the standard tag still resolve."),
     "resolver": lambda ctx: _safe_str(
         ctx.get("invitee_name") or ctx.get("recipient_name") or "")},
    {"token": "INVITER_NAME", "label": "Team — Inviter Name",
     "category": "Team",
     "description": "Display name of the admin who issued the team invite.",
     "resolver": lambda ctx: _safe_str(ctx.get("inviter_name") or "")},
    {"token": "ACCEPT_INVITE_LINK", "label": "Team — Accept URL",
     "category": "Team",
     "description": ("Login URL that lands the invitee on the "
                       "platform sign-in page.  Aliases ``ACCEPT_LINK`` "
                       "when the invite-specific ctx key is absent."),
     "resolver": lambda ctx: _safe_str(
         ctx.get("accept_invite_link")
         or ctx.get("accept_link") or "")},
    {"token": "TOS_VERSION", "label": "TOS — Document Version",
     "category": "Legal",
     "description": ("Version label on the ToS document (e.g. "
                       "``\"v2.1\"`` or the ``$service_type-2026-02``"
                       " slug)."),
     "resolver": lambda ctx: _safe_str(ctx.get("tos_version") or "")},
    {"token": "TOS_URL", "label": "TOS — Review URL",
     "category": "Legal",
     "description": ("Deep link to the customer-facing ToS acceptance "
                       "flow (portal login → ``/portal/tos/accept?"
                       "doc=…``)."),
     "resolver": lambda ctx: _safe_str(
         ctx.get("tos_url") or ctx.get("cta_url") or "")},
    {"token": "EFFECTIVE_DATE", "label": "Legal — Effective Date",
     "category": "Legal",
     "description": ("Effective date on the published ToS document "
                       "(ISO date string)."),
     "resolver": lambda ctx: _safe_str(ctx.get("effective_date") or "")},
    {"token": "SERVICE_LABEL", "label": "TOS — Service Category Label",
     "category": "Legal",
     "description": ("Human-readable service-type label on the ToS "
                       "document (``\"pool\"`` / ``\"landscaping\"``)."),
     "resolver": lambda ctx: _safe_str(ctx.get("service_label") or "")},

    # ═══════════════════════════════════════════════════════════════
    # M-TAG-FIX · Feb-2026 — short-form aliases for the "insert merge
    # tag" picker + portal-invite path tokens.  These delegate to the
    # long-form resolvers so templates authored with the shorter
    # name (``{{NAME}}`` vs ``{{CUSTOMER_FULL_NAME}}``) resolve
    # identically.  Required by the Feb-2026 picker-fix brief's
    # minimum tag set.
    # ═══════════════════════════════════════════════════════════════
    {"token": "NAME", "label": "Name", "category": "Customer",
     "description": "Recipient's full name — alias of CUSTOMER_FULL_NAME.",
     "sample_value": "Jane Smith", "resolver": _customer_full},
    {"token": "FIRST_NAME", "label": "First Name", "category": "Customer",
     "description": "Recipient's first name — alias of CUSTOMER_FIRST_NAME.",
     "sample_value": "Jane", "resolver": _customer_first},
    {"token": "LAST_NAME", "label": "Last Name", "category": "Customer",
     "description": "Recipient's last name — alias of CUSTOMER_LAST_NAME.",
     "sample_value": "Smith", "resolver": _customer_last},
    {"token": "EMAIL", "label": "Email", "category": "Customer",
     "description": "Recipient's email — alias of CUSTOMER_EMAIL.",
     "sample_value": "jane@example.com",
     "resolver": _res("customer", "email")},
    {"token": "PHONE", "label": "Phone", "category": "Customer",
     "description": "Recipient's phone — alias of CUSTOMER_PHONE.",
     "sample_value": "(555) 123-4567",
     "resolver": _res("customer", "phone")},
    {"token": "DUE_DATE", "label": "Due Date", "category": "Invoice",
     "description": "Invoice due date — alias of INVOICE_DUE_DATE.",
     "sample_value": "2026-03-15",
     "resolver": lambda ctx: _safe_str(
        ((ctx or {}).get("invoice") or {}).get("due_date") or ""
     )},
    {"token": "JOB_NAME", "label": "Job Name", "category": "Job",
     "description": "Job's service name — alias of SERVICE_NAME.",
     "sample_value": "Weekly Pool Service",
     "resolver": lambda ctx: _safe_str(
        ((ctx or {}).get("job") or {}).get("service_name")
        or ((ctx or {}).get("job") or {}).get("service_type")
        or ((ctx or {}).get("job") or {}).get("title") or ""
     )},
    {"token": "PORTAL_URL", "label": "Customer Portal URL",
     "category": "Portal",
     "description": "Portal auto-login URL — alias of CUSTOMER_PORTAL_LOGIN_LINK.",
     "sample_value": "https://app.example.com/portal/auto-login?token=...",
     "resolver": _portal_link},
    {"token": "LOGIN_URL", "label": "Portal Login URL",
     "category": "Portal",
     "description": "Direct portal login URL — portal-invite path.",
     "sample_value": "https://app.example.com/login",
     "resolver": lambda ctx: _safe_str((ctx or {}).get("login_url") or "")},
    {"token": "TEMP_PASSWORD", "label": "Temporary Password",
     "category": "Portal",
     "description": "Freshly minted portal password — portal-invite path.",
     "sample_value": "Abc123xyz",
     "resolver": lambda ctx: _safe_str((ctx or {}).get("temp_password") or "")},
    {"token": "TO", "label": "Recipient Email", "category": "Portal",
     "description": "Current send's recipient email — portal-invite path.",
     "sample_value": "jane@example.com",
     "resolver": lambda ctx: _safe_str(
        (ctx or {}).get("to") or _res("customer", "email")(ctx) or ""
     )},
    {"token": "PORTAL_REFERRALS_URL", "label": "Portal Referrals URL",
     "category": "Portal",
     "description": ("Deep-link to the customer-portal referrals "
                      "dashboard — populated by the referral watcher."),
     "sample_value": "https://app.example.com/portal/referrals",
     "resolver": lambda ctx: _safe_str(
        (ctx or {}).get("portal_referrals_url") or ""
     )},
    {"token": "LEAD_SUBJECT_PREFIX", "label": "Lead Subject Prefix",
     "category": "Lead",
     "description": ("Internal-only subject prefix on the admin "
                      "lead-alert email."),
     "sample_value": "[New lead] ",
     "resolver": lambda ctx: _safe_str(
        (ctx or {}).get("lead_subject_prefix") or ""
     )},
]

_TAG_INDEX: Dict[str, Callable] = {t["token"].upper(): t["resolver"]
                                        for t in MERGE_TAGS}


# ═══════════════════════════════════════════════════════════════════
# Feb-2026 · Portal-invite merge-tag fix — single-brace catalog
# token upgrader.
#
# Some legacy / user-edited ``marketing_templates`` rows carry
# CATALOG tokens in the single-brace form (``{COMPANY_NAME}``)
# instead of the canonical double-brace form (``{{COMPANY_NAME}}``).
# The ``render_template`` regex only matches double-brace tokens by
# design (so unrelated brace literals in prose / JSON snippets are
# left alone), and the pre-existing rebrace migration only covers
# four lowercase send-path tokens — so a single-brace catalog
# reference ships literally in the rendered body.
#
# This helper upgrades a single-brace token to its double-brace
# form ONLY when the token maps to a resolver in ``_TAG_INDEX``.
# Non-catalog braces (``{2024}``, ``{some prose}``, JSON bodies)
# are left byte-identical.  Scoped to the portal-invite send path
# per the Feb-2026 fix brief — other template surfaces stay on
# their own rebrace pipelines.
# ═══════════════════════════════════════════════════════════════════
_SINGLE_BRACE_TOKEN_RE = re.compile(
    r"(?<!\{)\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}(?!\})"
)


def rebrace_single_brace_catalog_tokens(body: str) -> str:
    """Rewrite ``{TOKEN}`` → ``{{TOKEN}}`` for every catalog token.

    A "catalog token" is any identifier whose uppercase form is a
    key in ``_TAG_INDEX`` — i.e. it has a registered resolver. Any
    other single-brace substring (``{2024}``, ``{prose}``, etc.)
    is preserved verbatim.

    Idempotent: already-double-braced tokens are ignored by the
    negative lookbehind/lookahead in the pattern, so calling this
    helper twice yields identical output.
    """
    if not isinstance(body, str) or not body:
        return body or ""

    def _upgrade(match: "re.Match[str]") -> str:
        token = match.group(1)
        if token.upper() in _TAG_INDEX:
            return "{{" + token + "}}"
        return match.group(0)

    return _SINGLE_BRACE_TOKEN_RE.sub(_upgrade, body)


# ═══════════════════════════════════════════════════════════════════
# Phase 21 · Feb-2026 — URL-encoded merge-tag normaliser.
#
# Some tenants have portal-invite / password-reset bodies stored
# with URL-encoded brace sequences (``%7B%7BNAME%7D%7D`` instead of
# ``{{NAME}}``). This happens when:
#
#   * a rich-text editor's clipboard-paste path URL-encodes the
#     payload before storing it,
#   * a legacy migration serialised the body through a querystring,
#     or
#   * an operator pasted a URL-encoded sample as the "default"
#     template body.
#
# ``render_template`` matches literal ``{{…}}`` only — a URL-encoded
# token slips through untouched and the recipient sees
# ``%7B%7BLOGIN_URL%7D%7D`` instead of their login link.
#
# This helper normalises those sequences BACK to the canonical
# brace form **only when they bracket a token-shaped identifier**
# (uppercase letters / digits / underscores). URL-encoded braces
# that appear elsewhere in the body (e.g. a legitimate ``%7B`` in
# a tracked click-through URL) are left verbatim.
#
# Handles both the double-brace (``%7B%7B…%7D%7D``) and the single-
# brace (``%7B…%7D``) encodings; the single-brace path routes
# through the catalog upgrade so ``%7BCOMPANY_NAME%7D`` →
# ``{{COMPANY_NAME}}`` in one pass.
#
# Case-insensitive on the hex nibbles — ``%7b%7b…%7d%7d`` and
# ``%7B%7B…%7D%7D`` are both covered. Idempotent — a body that
# already contains canonical ``{{…}}`` tokens is returned verbatim.
# ═══════════════════════════════════════════════════════════════════
_URL_ENC_DOUBLE_BRACE_RE = re.compile(
    r"%7B%7B\s*([A-Za-z_][A-Za-z0-9_.]*)\s*%7D%7D",
    re.IGNORECASE,
)
_URL_ENC_SINGLE_BRACE_RE = re.compile(
    r"(?<!%7B)%7B\s*([A-Za-z_][A-Za-z0-9_.]*)\s*%7D(?!%7D)",
    re.IGNORECASE,
)


def normalize_url_encoded_merge_tags(body: str) -> str:
    """Rewrite URL-encoded merge-tag braces back to the canonical
    ``{{TOKEN}}`` / ``{TOKEN}`` form.

    Scope:
      * ``%7B%7BTOKEN%7D%7D`` → ``{{TOKEN}}`` (ANY identifier
        shape — the render engine itself gates on resolver
        presence, so this is safe for non-catalog values the
        caller passes directly through ``ctx``).
      * ``%7BTOKEN%7D`` → ``{TOKEN}`` (gated on catalog
        resolver presence — identical behaviour to
        ``rebrace_single_brace_catalog_tokens`` but on the
        URL-encoded surface).

    Non-brace URL encodings (``%2F``, ``%3A`` in tracked URLs,
    etc.) are untouched. Already-canonical ``{{…}}`` tokens are
    not re-matched (the regex requires the ``%7B%7B`` prefix).
    """
    if not isinstance(body, str):
        return ""
    if not body:
        return body

    body = _URL_ENC_DOUBLE_BRACE_RE.sub(
        lambda m: "{{" + m.group(1) + "}}", body,
    )

    def _single(match: "re.Match[str]") -> str:
        token = match.group(1)
        if token.upper() in _TAG_INDEX:
            return "{" + token + "}"
        return match.group(0)

    body = _URL_ENC_SINGLE_BRACE_RE.sub(_single, body)
    return body


# ═══════════════════════════ Renderer ════════════════════════════════

# M-TAG-FIX · Feb-2026 — residual sweep patterns applied AFTER the
# cascade resolver.  Any ``{{…}}`` / ``%7B%7B…%7D%7D`` that still
# survives is scrubbed + logged so recipients never see raw braces.
_RESIDUAL_URL_ENCODED_RE = re.compile(
    r"%7B%7B[^%]*?%7D%7D", re.IGNORECASE,
)
_RESIDUAL_LITERAL_RE = re.compile(r"\{\{[^{}]*?\}\}")


def _strip_residual_merge_tags(
    body: str, *,
    template_key: Optional[str] = None,
    template_id: Optional[str] = None,
) -> str:
    """Belt-and-braces scrub: strip any residual ``{{…}}`` or URL-
    encoded ``%7B%7B…%7D%7D`` from an already-rendered body.  Logs
    a WARNING per unique leaked token so operators can trace via
    existing log tooling."""
    if not isinstance(body, str) or not body:
        return body or ""
    leaked: List[str] = []
    def _log_and_strip(match: "re.Match[str]") -> str:
        leaked.append(match.group(0))
        return ""
    out = _RESIDUAL_URL_ENCODED_RE.sub(_log_and_strip, body)
    out = _RESIDUAL_LITERAL_RE.sub(_log_and_strip, out)
    if leaked:
        for tok in sorted(set(leaked))[:5]:
            logger.warning(
                "[merge_tags] residual merge-tag stripped from"
                " rendered body: token=%r template_id=%s"
                " template_key=%s",
                tok, template_id, template_key,
            )
    return out


def render_template(body: str, ctx: Optional[Dict[str, Any]] = None,
                     missing: str = "empty",
                     *,
                     template_id: Optional[str] = None,
                     template_key: Optional[str] = None) -> Tuple[str, List[str]]:
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

    # M-TAG-FIX · Feb-2026 — normalise URL-encoded brace sequences
    # (``%7B%7BTOKEN%7D%7D`` / ``%7BTOKEN%7D``) back to canonical
    # ``{{TOKEN}}`` BEFORE substitution.  Legacy template bodies
    # ingested through a URL-encoding clipboard-paste or querystring
    # migration path otherwise slip past ``_TAG_RE`` and leak
    # ``%7B%7B…%7D%7D`` to the recipient.  Idempotent — a body
    # already in the canonical form is byte-identical after this
    # call.
    body = normalize_url_encoded_merge_tags(body)

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

    # M-TAG-FIX · Feb-2026 — belt-and-braces residual sweep.  Any
    # odd-shaped brace sequence that survives the primary cascade
    # (invalid identifiers like ``{{some phrase}}``, URL-encoded
    # tokens with whitespace padding, etc.) is scrubbed + logged
    # so the recipient never sees raw braces.
    rendered = _strip_residual_merge_tags(
        rendered,
        template_id=template_id,
        template_key=template_key,
    )
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
    ``GET /api/marketing/merge-tags``.

    M-TAG-FIX · Feb-2026 — hardened against entries that omit the
    optional ``description`` / ``sample_value`` keys; both fall
    back to the empty string so a single under-documented tag can
    no longer 500 the whole endpoint and empty the picker.

    M-TAG-FIX FOLLOWUP Fix 2 · Feb-2026 — the canonical identifier
    field is now ``key`` (aligned with the flat endpoint consumed by
    the upcoming visual-email-builder + mobile port).  ``token`` is
    emitted alongside as a DEPRECATED alias for one release cycle
    so no in-flight consumer breaks mid-rollout.  See
    ``/app/memory/deprecations.md`` for the removal schedule.
    """
    by_cat: Dict[str, List[Dict[str, Any]]] = {}
    for t in MERGE_TAGS:
        tok = t["token"]
        by_cat.setdefault(t["category"], []).append({
            "key": tok,
            # DEPRECATED alias — remove after visual-email-builder
            # phase ships + mobile port consumes ``key``.
            "token": tok,
            "label": t.get("label", tok),
            "description": t.get("description", ""),
            "sample_value": t.get("sample_value", ""),
        })
    return by_cat


def catalog_flat() -> List[Dict[str, Any]]:
    """M-TAG-FIX · Feb-2026 — flat JSON-serialisable registry used
    by ``GET /api/merge-tags`` (visual-email-builder prerequisite).
    Response-item shape: ``{key, label, description, category,
    sample_value}``.

    M-TAG-FIX FOLLOWUP Fix 2 · Feb-2026 — also emits the DEPRECATED
    ``token`` alias (byte-equal to ``key``) for one release cycle so
    legacy consumers that haven't yet switched to ``key`` keep
    working.  See ``/app/memory/deprecations.md``.
    """
    out: List[Dict[str, Any]] = []
    for t in MERGE_TAGS:
        tok = t["token"]
        out.append({
            "key": tok,
            # DEPRECATED alias — remove after visual-email-builder
            # phase ships + mobile port consumes ``key``.
            "token": tok,
            "label": t.get("label", tok),
            "description": t.get("description", ""),
            "category": t["category"],
            "sample_value": t.get("sample_value", ""),
        })
    return out
