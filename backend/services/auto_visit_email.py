"""Phase 56.20 — Auto End-of-Visit Customer Email.

Fires an email to the customer when a tech submits a service report.
Pipeline:

    submit_service_report(...)  ← existing endpoint
        └── send_visit_summary_email(tenant, job, service_report)
                ├── idempotency check on outbound_emails
                ├── redact via _redact_report_for_customer (existing)
                ├── render HTML + plain-text bodies
                └── Resend dispatch OR log-only fallback if key missing

All rows land in `db.outbound_emails` regardless of send status so the
audit trail exists even when RESEND_API_KEY is unset. Non-blocking:
any exception here is caught + logged; the submit endpoint still
returns success.

Phase COMM1 · Feb-2026:
    - Required-Four readings render as qualitative bands (Below /
      Average / Above / Elevated) with the numeric value as a small
      muted subtitle. Optional readings still render as plain
      values (see ``services.chemistry_bands``).
    - The email header, section titles, sub-headers, and CTA button
      use the tenant's stored brand colors
      (``business_settings.brand_primary_hex`` /
      ``brand_secondary_hex``); a per-tenant fallback palette kicks
      in when unset.
    - A "Visit photos" grid renders up to six tech-attached photos
      (customer-safe, tag-filtered); a "+N more in your report"
      link back to the portal appears when the tech attached more.
"""
from __future__ import annotations
import os
import re
from typing import Any, Dict, List, Mapping, Optional

from config import db, logger
from utils import new_id, now_iso

# Phase COMM1 · Feb-2026 — customer-facing band classifier used
# for the Required Four rows. Lives in ``chemistry_bands`` so the
# same thresholds render across door-hanger email, portal page,
# and this auto-visit email.
from services.chemistry_bands import (
    band_for_reading, CANONICAL_BAND_THRESHOLDS, DISPLAY_LABELS,
)


# ── Phase P45 · Feb-2026 · absolute-URL helper for email HTML ──────
# Email clients (Gmail, Outlook, Apple Mail) block or fail to
# resolve relative image URLs — the email is rendered outside the
# app's origin.  Every ``<img src="…">`` and CSS
# ``background-image:url(…)`` in the outgoing HTML must be an
# absolute URL with a scheme + host.  ``_absolute_url`` is the
# single choke point that prepends the public origin.
#
# Env-var precedence (per P45 spec):
#   1. PUBLIC_FRONTEND_ORIGIN   — canonical (P34 rollout)
#   2. APP_PUBLIC_URL            — codebase-legacy fallback
#   3. Hardcoded ``https://app.plofv.com`` — last-resort default,
#      one WARN emitted the first time it fires if both env vars
#      are absent.

_P45_HARDCODED_ORIGIN = "https://app.plofv.com"
_P45_WARNED_HARDCODE = False


def _absolute_url(path):
    """Prepend the public origin to a relative path so email
    clients can resolve the URL.  Already-absolute URLs pass
    through unchanged.  ``None`` / empty inputs return
    unchanged (caller filters empties).
    """
    global _P45_WARNED_HARDCODE
    if not path:
        return path
    if isinstance(path, str) and path.startswith(
        ("http://", "https://", "data:", "cid:"),
    ):
        # Already absolute — or a data:/cid: inline URL that email
        # clients handle natively.  Nothing to prepend.
        return path
    base = (
        os.environ.get("PUBLIC_FRONTEND_ORIGIN")
        or os.environ.get("APP_PUBLIC_URL")
        or _P45_HARDCODED_ORIGIN
    ).rstrip("/")
    if (base == _P45_HARDCODED_ORIGIN
            and not os.environ.get("PUBLIC_FRONTEND_ORIGIN")
            and not os.environ.get("APP_PUBLIC_URL")
            and not _P45_WARNED_HARDCODE):
        logger.warning(
            "[p45] _absolute_url falling back to hardcoded %s — "
            "set PUBLIC_FRONTEND_ORIGIN or APP_PUBLIC_URL to override",
            _P45_HARDCODED_ORIGIN,
        )
        _P45_WARNED_HARDCODE = True
    return f"{base}/{str(path).lstrip('/')}"



AUTO_EMAIL_KEY = "auto_visit_email"


# ─── Phase COMM1 · brand palette resolution ─────────────────────────
#
# The tenant's stored ``brand_primary_hex`` / ``brand_secondary_hex``
# come from Business Settings. We derive a third accent hex from the
# secondary (or the primary, when only one color is set) so the CTA
# button always has enough contrast against the body background.
#
# NO new schema fields are introduced — the accent is a pure
# derivation of the two existing brand colors.
_DEFAULT_PRIMARY_HEX   = "#0B4A6F"   # matches services.email.theming
_DEFAULT_SECONDARY_HEX = "#0369A1"
_DEFAULT_ACCENT_HEX    = "#2563EB"


def _valid_hex(candidate: Any) -> Optional[str]:
    if not candidate:
        return None
    s = str(candidate).strip()
    if not s.startswith("#") or len(s) != 7:
        return None
    try:
        int(s[1:], 16)
    except ValueError:
        return None
    return s.lower()


def _resolve_palette(branding: Optional[Mapping[str, Any]]) -> Dict[str, str]:
    """Return ``{primary, secondary, accent}`` with per-tenant
    values when set, else a sensible defaults palette.

    Reads both the effective settings shape
    (``brand_primary_hex`` — used by the shared email shell) and
    the raw tenant shape (``brand_primary`` — used by portal
    widgets) so the helper works with whatever dict shape the
    caller has on hand.
    """
    b: Mapping[str, Any] = branding or {}
    primary = (
        _valid_hex(b.get("brand_primary_hex"))
        or _valid_hex(b.get("brand_primary"))
        or _valid_hex(b.get("primary_hex"))
        or _DEFAULT_PRIMARY_HEX
    )
    secondary = (
        _valid_hex(b.get("brand_secondary_hex"))
        or _valid_hex(b.get("brand_secondary"))
        or _valid_hex(b.get("secondary_hex"))
        or _DEFAULT_SECONDARY_HEX
    )
    # No dedicated accent field on the schema — reuse secondary
    # when set, else fall back to the platform accent.
    accent = secondary if secondary != _DEFAULT_SECONDARY_HEX else _DEFAULT_ACCENT_HEX
    return {"primary": primary, "secondary": secondary, "accent": accent}


def _get_settings(tenant: dict) -> dict:
    s = (tenant or {}).get("settings") or {}
    return s.get(AUTO_EMAIL_KEY) or {}


def _is_enabled(tenant: dict) -> bool:
    return bool(_get_settings(tenant).get("enabled", False))


def _google_review_link(tenant: dict) -> str:
    return (_get_settings(tenant).get("google_review_link") or "").strip()


def _footer_text(tenant: dict) -> str:
    return (_get_settings(tenant).get("footer_text") or "").strip()


def _include_reviews_cta(tenant: dict) -> bool:
    return bool(_get_settings(tenant).get("include_reviews_cta", True))


def _visit_date_formatted(sr: dict, job: dict) -> str:
    ts = sr.get("submitted_at") or job.get("service_report_submitted_at") \
        or job.get("scheduled_start") or ""
    return (ts or "")[:10]


# ─── Reading normaliser + band-aware row builder (Phase COMM1) ───────
#
# The customer email speaks CANONICAL keys (matches the chemistry
# gate). Legacy dict-shape readings might arrive with mixed casing
# ("pH", "chlorine", "Chlorine") — Phase P17.1 flipped the chlorine
# canonical from ``free_chlorine`` → ``chlorine`` and Phase P17.2
# unified the display label from ``Free Cl`` → ``Chlorine``.  Legacy
# spellings (``free_chlorine``, ``free_cl``, ``fc``) still resolve via
# the gate's alias table so the band classifier fires on every payload.
def _canonicalize_reading_key(raw: Any) -> Optional[str]:
    try:
        from services.chemistry_gate import _canonical_key
        ck = _canonical_key(raw)
        if ck:
            return ck
    except Exception:                                       # noqa: BLE001
        pass
    return None


def _iter_readings(readings: Any):
    """Yield ``(canonical_key, display_label, value, band_label)``
    tuples for the render loop. Accepts BOTH the list-of-dicts shape
    (``[{"key": "chlorine", "value": 2.5, "unit": "ppm", "label": …}]``)
    and the legacy dict shape (``{"chlorine": 2.5}``).

    ``band_label`` is the pre-computed band string set by the
    portal redact (``_redact_report_for_customer`` — Slice 3C).
    When present, the render loop uses it verbatim; when absent, it
    falls back to ``band_for_reading(key, value)``.
    """
    if isinstance(readings, dict):
        for k, v in readings.items():
            ck = _canonicalize_reading_key(k)
            display = DISPLAY_LABELS.get(ck, str(k))
            yield ck, display, v, None
        return
    if isinstance(readings, list):
        for row in readings:
            if not isinstance(row, dict):
                continue
            raw_key = row.get("key") or row.get("name")
            ck = _canonicalize_reading_key(raw_key)
            display = (row.get("label_display")
                         or DISPLAY_LABELS.get(ck)
                         or str(raw_key or ""))
            yield ck, display, row.get("value"), row.get("label")
        return


def _reading_unit(raw: Any) -> str:
    """Best-effort unit lookup for the numeric subtitle. Canonical
    keys carry standardised units — everything else prints unit-less."""
    UNIT = {
        "chlorine":         "ppm",
        "alkalinity":       "ppm",
        "cyanuric_acid":    "ppm",
        "ph":               "",
        "calcium_hardness": "ppm",
        "salt":             "ppm",
        "tds":              "ppm",
        "phosphates":       "ppb",
    }
    if isinstance(raw, dict) and raw.get("unit"):
        return str(raw["unit"]) or ""
    if isinstance(raw, str):
        return UNIT.get(raw, "")
    return ""


def _pool_body_sections(sr: dict, palette: Dict[str, str]) -> list[dict]:
    """Phase COMM1 · Feb-2026 — Required Four render as bands (with
    the numeric value as a muted subtitle). Optional readings still
    render as raw ``value + unit``; ``palette`` supplies the sub-
    header color (secondary) so section titles pick up brand.
    """
    sections: list[dict] = []
    readings = sr.get("chemical_readings")
    if readings:
        # Split rendered rows into two visual buckets for tests:
        #   * banded (Required Four + extended optionals that HAVE
        #     a threshold in chemistry_bands)
        #   * plain (unknown keys, or the tech typed a non-numeric
        #     value → we still surface the raw string)
        html_rows: list[str] = []
        text_rows: list[str] = []
        for ck, display, val, pre_label in _iter_readings(readings):
            # Phase COMM1 · Feb-2026 — a row renders when EITHER
            # the numeric value is present OR the redact
            # pipeline has pre-attached a band ``label``. That
            # keeps the customer-safe (numerics-stripped) shape
            # rendering as band-only rows while the tech-facing /
            # pre-redact shape shows band + numeric subtitle.
            has_value = val not in (None, "", 0)
            if not has_value and not pre_label:
                continue
            band = pre_label or (band_for_reading(ck, val) if ck else None)
            unit = _reading_unit(ck) if ck else ""
            # Subtitle only rendered when we have a numeric value.
            subtitle = ""
            if has_value:
                num_str = str(val)
                subtitle = (
                    f"{band} · {num_str}{(' ' + unit) if unit else ''}"
                    if band
                    else f"{num_str}{(' ' + unit) if unit else ''}"
                )
            primary_line = band if band else (str(val) if has_value else "")
            html_rows.append(
                f"<tr>"
                f"<td style='padding:6px 12px 6px 0;color:#555;font-size:13px'>"
                f"{display}</td>"
                f"<td style='padding:6px 0;font-weight:600;font-size:14px;"
                f"color:{palette['primary']}'>{primary_line}"
                f"<div style='font-size:11px;color:#888;font-weight:400'>"
                f"{subtitle}</div></td>"
                f"</tr>"
            )
            text_rows.append(f"  {display}: {primary_line}"
                              + (f"  ({subtitle})" if subtitle else ""))
        if html_rows:
            sections.append({
                "title": "Water chemistry",
                "html": (f"<table cellspacing='0' style='width:100%;"
                          f"border-collapse:collapse'>{''.join(html_rows)}</table>"),
                "text": "\n".join(text_rows),
            })
    added = sr.get("chemicals_added") or []
    if added:
        items = "".join(
            f"<li style='margin:4px 0'>{c.get('name', c.get('type', 'Chemical'))} — "
            f"{c.get('amount', '')} {c.get('unit', '')}</li>"
            for c in added if isinstance(c, dict)
        )
        sections.append({
            "title": "Chemicals added",
            "html": f"<ul style='padding-left:18px;margin:8px 0'>{items}</ul>",
            "text": "\n".join(f"  • {c.get('name', 'Chemical')} — {c.get('amount', '')} {c.get('unit', '')}"
                              for c in added if isinstance(c, dict)),
        })
    checklist = sr.get("checklist_completed") or sr.get("checklist_items") or []
    done = [c for c in checklist
            if isinstance(c, dict) and c.get("done")]
    if done:
        items = "".join(f"<li>✓ {c.get('label', 'Item')}</li>" for c in done)
        sections.append({
            "title": "Completed",
            "html": f"<ul>{items}</ul>",
            "text": "\n".join(f"  ✓ {c.get('label', 'Item')}" for c in done),
        })
    algae = (sr.get("observations") or {}).get("visible_algae")
    if algae and algae != "none":
        msg = "Light algae was observed and treated." if algae == "light" \
            else "Heavy algae was observed and treated." if algae == "heavy" \
            else f"Algae ({algae}) was observed and treated."
        sections.append({
            "title": "Algae observation",
            "html": f"<p>{msg}</p>",
            "text": msg,
        })
    return sections


def _landscape_body_sections(sr: dict) -> list[dict]:
    checklist = sr.get("checklist_completed") or sr.get("checklist_items") or []
    done = [c for c in checklist if isinstance(c, dict) and c.get("done")]
    if not done:
        return []
    items = "".join(f"<li>✓ {c.get('label', 'Item')}</li>" for c in done)
    return [{
        "title": "Landscape checklist",
        "html": f"<ul>{items}</ul>",
        "text": "\n".join(f"  ✓ {c.get('label', 'Item')}" for c in done),
    }]


def _photo_ts(p: Dict[str, Any]) -> str:
    """Sort-key extractor for the photos grid — newest first. Falls
    back to a stable string so the sort is deterministic when the
    ``taken_at`` timestamps aren't set (older seed data)."""
    for k in ("taken_at", "created_at", "uploaded_at", "submitted_at"):
        v = p.get(k)
        if v:
            return str(v)
    return ""


def _photos_grid(
    sr: dict, portal_link: str, palette: Dict[str, str], safe_photos: List[Dict[str, Any]],
) -> Dict[str, str]:
    """Phase COMM1 · Feb-2026 — 3-column, up-to-6-photo thumbnail
    grid + optional "+N more in your report" link. Each thumbnail
    links back to the portal (never a raw S3 URL) so auth stays in
    the loop.

    Returns ``{"html": …, "text": …}``. Both are empty strings when
    ``safe_photos`` is empty — callers can concatenate unconditionally.
    """
    if not safe_photos:
        return {"html": "", "text": ""}
    ordered = sorted(safe_photos, key=_photo_ts, reverse=True)
    top6 = ordered[:6]
    overflow = max(0, len(ordered) - 6)
    grid_cells = []
    for p in top6:
        url = p.get("url") or p.get("uri") or ""
        if not url:
            continue
        # Phase P45 · Feb-2026 — absolute URL for email-client
        # compatibility (Gmail/Outlook can't resolve relative
        # paths); already-absolute URLs pass through unchanged.
        abs_url = _absolute_url(url)
        grid_cells.append(
            f'<td style="width:33.33%;padding:6px" valign="top" align="center">'
            f'<a href="{portal_link}" style="text-decoration:none;">'
            f'<img src="{abs_url}" alt="Visit photo" '
            f'style="max-width:180px;width:100%;height:auto;border-radius:8px;'
            f'border:1px solid #E5E7EB;display:block" />'
            f'</a></td>'
        )
    # Bucket into rows of 3 for reliable email-client rendering
    # (grid CSS is unreliable across Outlook variants).
    html_rows = []
    for i in range(0, len(grid_cells), 3):
        html_rows.append("<tr>" + "".join(grid_cells[i:i + 3]) + "</tr>")
    section = (
        f'<h3 style="margin:20px 0 8px;font-family:system-ui;font-size:15px;'
        f'color:{palette["primary"]}">Visit photos</h3>'
        f'<table cellspacing="0" cellpadding="0" style="width:100%;'
        f'border-collapse:collapse">{"".join(html_rows)}</table>'
    )
    if overflow > 0:
        section += (
            f'<p style="margin:6px 0 0;font-size:12px">'
            f'<a href="{portal_link}" '
            f'style="color:{palette["accent"]};text-decoration:none">'
            f'+{overflow} more in your report →</a></p>'
        )
    text = f"Visit photos: {len(top6)} attached"
    if overflow > 0:
        text += f" (+{overflow} more in your portal)"
    text += f"\n  {portal_link}"
    return {"html": section, "text": text}


def render_email(
    tenant: dict, job: dict, sr: dict, customer: dict,
    branding: Optional[Mapping[str, Any]] = None,
) -> dict:
    """Return {subject, html, text}. `sr` must already be customer-redacted.

    Phase COMM1 · Feb-2026 — ``branding`` (effective business
    settings dict, keyword-only) supplies the per-tenant palette.
    Callers that don't have the dict on hand may omit it and the
    renderer falls back to the raw ``tenant`` doc's brand keys.
    """
    palette = _resolve_palette(branding or tenant)
    company = tenant.get("name") or "Pool & Landscaping"
    # Phase 34 · Feb 2026 — brand logo header. Tenant override wins;
    # falls back to the shared brand mark so every service-visit email
    # matches the estimate/invoice/login surfaces.
    logo = (tenant.get("logo_url")
            or ((tenant.get("settings") or {}).get("business_card") or {}).get("logo_url")
            or "https://app.plofv.com/logo-full.png")
    kind = (sr.get("kind") or job.get("service_type") or "pool").lower()
    is_landscape = "landscape" in kind or "landscap" in kind
    visit_date = _visit_date_formatted(sr, job)
    # Phase D5 · Feb-2026 — subject line resolves through the i18n
    # loader so a customer with ``locale="es"`` receives a Spanish
    # subject even though the body sections below remain composed in
    # English. Body-section i18n is deferred to a follow-up (D6). If
    # the loader fails for any reason (missing template, missing
    # merge var, etc.) we fall back to the pre-D5 English wording so
    # a template-tree bug can never blank an outbound subject.
    try:
        from services.i18n_notifications import (
            resolve_notification_body as _resolve_body,
            resolve_recipient_locale as _resolve_loc,
        )
        _locale = _resolve_loc(
            customer=customer, tenant=tenant, audience="customer",
        )
        _rendered = _resolve_body(
            "visit_summary_email", _locale,
            context={
                "business_name": company,
                "visit_date": visit_date,
                # NB: the HTML/text bodies are NOT consumed here yet
                # (we still use the dynamic composer below), but
                # both files exist and are placeholder-parity checked
                # so a future D6 wire-through has a stable target.
                "customer_first_name": (
                    (customer.get("first_name")
                     or (customer.get("name") or "").split(" ")[0]
                     or "").strip() or "there"
                ),
                "portal_link": "",  # unused for subject render
            },
        )
        subject = _rendered["subject"]
    except Exception as _i18n_exc:  # noqa: BLE001
        logger.warning(
            "[i18n-email] visit_summary_email subject fallback: %s: %s",
            type(_i18n_exc).__name__, str(_i18n_exc)[:200],
        )
        subject = f"Your {company} service visit — {visit_date}"

    if is_landscape:
        sections = _landscape_body_sections(sr)
    else:
        sections = _pool_body_sections(sr, palette)

    customer_notes = (sr.get("customer_notes") or "").strip()
    # Safety net: even though _redact strips internal_notes at data
    # source, we regex-scrub any accidental "internal_notes:" leak here.
    customer_notes = re.sub(r"internal[_ ]notes?\s*:.*",
                              "", customer_notes, flags=re.IGNORECASE)

    photos = [p for p in (sr.get("photos") or []) if isinstance(p, dict)]
    safe_photos = [p for p in photos
                   if not any(str(t).lower() in ("internal", "issue", "private")
                              for t in (p.get("tags") or []))]

    review_link = _google_review_link(tenant)
    include_reviews = _include_reviews_cta(tenant) and bool(review_link)
    custom_footer = _footer_text(tenant)
    app_url = os.environ.get("APP_PUBLIC_URL", "").rstrip("/")
    # Phase P45 · Feb-2026 — portal_link is EMBEDDED IN <a href> tags
    # in email HTML; absolute is mandatory or Gmail/Outlook will
    # rewrite the ``/portal/service-reports`` bare path to their own
    # domain.  Route through ``_absolute_url`` so PUBLIC_FRONTEND_ORIGIN
    # takes precedence over the legacy APP_PUBLIC_URL when both are
    # set; falls back to hardcoded ``https://app.plofv.com`` if
    # neither is configured.
    portal_link = _absolute_url("/portal/service-reports")

    # ─── HTML ───────────────────────────────────────────────────────
    # Phase COMM1 · Feb-2026 — header uses the tenant primary color
    # as the band background so the email surface matches the
    # customer's brand at a glance.
    header_html = (
        f'<table cellspacing="0" cellpadding="0" style="width:100%;'
        f'border-collapse:collapse;background:{palette["primary"]};'
        f'padding:16px 20px" bgcolor="{palette["primary"]}">'
        f'<tr><td>'
    )
    if logo:
        # Phase P45 · Feb-2026 — absolute URL for email-client
        # compatibility (Gmail/Outlook can't resolve relative
        # paths); already-absolute URLs pass through unchanged.
        abs_logo = _absolute_url(logo)
        header_html += (
            f'<img src="{abs_logo}" alt="{company}" '
            f'style="max-height:48px;margin-bottom:8px;display:block" />'
        )
    header_html += (
        f'<div style="color:#FFFFFF;font-family:system-ui;'
        f'font-size:20px;font-weight:700">{company}</div>'
        f'<div style="color:rgba(255,255,255,0.85);font-family:system-ui;'
        f'font-size:14px;margin-top:2px">Service visit summary</div>'
        f'</td></tr></table>'
    )

    info_rows = [
        ("Date", visit_date),
        ("Technician", sr.get("tech_name") or ""),
        ("Address", job.get("address") or ""),
    ]
    info_html = "".join(
        f"<tr><td style='padding:2px 12px 2px 0;color:#555'>{k}</td>"
        f"<td style='padding:2px 0;font-weight:600'>{v}</td></tr>"
        for k, v in info_rows if v
    )

    sections_html = "".join(
        f'<h3 style="margin:16px 0 4px;font-family:system-ui;font-size:15px;'
        f'color:{palette["secondary"]}">{s["title"]}</h3>{s["html"]}'
        for s in sections
    )
    notes_html = ""
    if customer_notes:
        notes_html = (
            f'<h3 style="margin:16px 0 4px;font-family:system-ui;font-size:15px;'
            f'color:{palette["secondary"]}">Notes from your tech</h3>'
            f'<p style="white-space:pre-line;background:#f6f6f6;padding:12px;'
            f'border-radius:6px">{customer_notes}</p>'
        )
    photos_block = _photos_grid(sr, portal_link, palette, safe_photos)
    photos_html = photos_block["html"]

    cta_html = ""
    if include_reviews:
        cta_html += (
            f'<p><a href="{review_link}" '
            f'style="background:{palette["accent"]};color:#fff;'
            f'text-decoration:none;padding:10px 16px;border-radius:6px;'
            f'display:inline-block;font-weight:600">Leave us a review</a></p>'
        )
    cta_html += (
        f'<p><a href="{portal_link}" '
        f'style="background:{palette["accent"]};color:#fff;'
        f'text-decoration:none;padding:10px 16px;border-radius:6px;'
        f'display:inline-block;font-weight:600">View full report →</a></p>'
    )

    footer_html = ('<p style="color:#888;font-size:12px;margin-top:24px">'
                   'This is an automatic recap of the customer-facing portion of your visit. '
                   'Internal service notes are not included.')
    if custom_footer:
        footer_html += f' {custom_footer}'
    footer_html += (f' <br/><a href="{app_url}/portal/unsubscribe" style="color:#888">Unsubscribe</a>'
                    if app_url else '')
    footer_html += '</p>'

    html = (f'<div style="font-family:system-ui;max-width:600px;margin:0 auto;'
            f'background:#FFFFFF">'
            f'{header_html}'
            f'<div style="padding:20px">'
            f'<table style="margin-top:12px" cellspacing="0">{info_html}</table>'
            f'{sections_html}{notes_html}{photos_html}{cta_html}{footer_html}'
            f'</div>'
            f'</div>')

    # ─── Text ───────────────────────────────────────────────────────
    text_lines = [
        company, "Service visit summary", "",
        f"Date: {visit_date}",
        f"Tech: {sr.get('tech_name') or ''}",
        f"Address: {job.get('address') or ''}",
        "",
    ]
    for s in sections:
        text_lines.append(s["title"] + ":")
        text_lines.append(s["text"])
        text_lines.append("")
    if customer_notes:
        text_lines += ["Notes from your tech:", customer_notes, ""]
    if photos_block["text"]:
        text_lines += [photos_block["text"], ""]
    if include_reviews:
        text_lines.append(f"Leave a review: {review_link}")
    text_lines.append(f"Portal: {portal_link}")
    if custom_footer:
        text_lines += ["", custom_footer]
    text_lines.append("")
    text_lines.append("Internal service notes are not included in this summary.")

    return {"subject": subject, "html": html, "text": "\n".join(text_lines),
            "kind": ("landscape" if is_landscape else "pool")}


async def send_visit_summary_email(tenant: dict, job: dict, sr: dict) -> Optional[dict]:
    """Fire the visit-summary email. Non-blocking — any error is logged
    and swallowed so a failed email never breaks the submit flow.

    Idempotent: skips send if outbound_emails already has a
    (kind=visit_summary, service_report_id, customer_id) row.
    """
    if not _is_enabled(tenant):
        return None
    try:
        customer_id = job.get("customer_id")
        if not customer_id:
            return None
        customer = await db.customers.find_one(
            {"id": customer_id, "tenant_id": tenant["id"]}, {"_id": 0}
        )
        if not customer:
            return None
        # Feb-2026 · Multi-Contact Phase 2 · fan-out (automation).
        # Auto-fires when the tech submits a service report — respects
        # the customer-level mute.
        from services.customer_multi_contact import (
            active_email_recipients, log_mute_suppressed,
        )
        recipients = active_email_recipients(customer, context="automation")
        if not recipients:
            if customer.get("automations_muted"):
                await log_mute_suppressed(
                    tenant_id=tenant["id"], customer_id=customer_id,
                    channel="email", cluster="auto_visit_email",
                    context="automation",
                )
            return None
        sr_id = sr.get("id")
        # Idempotency check.
        dupe = await db.outbound_emails.find_one({
            "kind": "visit_summary",
            "service_report_id": sr_id,
            "customer_id": customer_id,
        }, {"_id": 0, "id": 1, "status": 1})
        if dupe:
            return {"skipped": "idempotent", "existing": dupe}

        # Redact via the same helper used by the customer portal.
        from routers.service_reports import _redact_report_for_customer
        safe_sr = _redact_report_for_customer(dict(sr))

        # Phase COMM1 · Feb-2026 — resolve effective branding once
        # per fan-out so every recipient shares the same palette.
        try:
            from services.tenants.business_settings import (
                get_effective_business_settings,
            )
            branding = await get_effective_business_settings(
                db, tenant["id"], absolutize=True,
            )
        except Exception:                                   # noqa: BLE001
            branding = None

        rendered = render_email(tenant, job, safe_sr, customer,
                                 branding=branding)
        resend_key = os.environ.get("RESEND_API_KEY")
        last_row = None
        for to_email in recipients:
            row = {
                "id": new_id(),
                "kind": "visit_summary",
                "tenant_id": tenant["id"],
                "customer_id": customer_id,
                "service_report_id": sr_id,
                "job_id": job.get("id"),
                "to": to_email,
                "subject": rendered["subject"],
                "html": rendered["html"],
                "text": rendered["text"],
                "report_kind": rendered["kind"],
                "created_at": now_iso(),
                "status": "pending",
                "fanned_out": True,
                "fanout_recipient_count": len(recipients),
            }
            if not resend_key:
                row["status"] = "not_sent_missing_key"
                await db.outbound_emails.insert_one(row)
                last_row = row
                continue
            try:
                import resend  # type: ignore
                resend.api_key = resend_key
                # Phase P14 · Feb-2026 · Item 3 — include the tenant's
                # company name in the ``From`` display name so a
                # recipient's inbox shows "Aquaterra Pool Service
                # <onboarding@resend.dev>" instead of the bare
                # address. Resend accepts the RFC 5322 ``Display Name
                # <address>`` shape natively. Any character that
                # would break the header (``,`` / ``;`` / ``<`` / ``"``
                # / control chars) is stripped BEFORE the concat so
                # a tenant with a funky name can't spoof extra
                # headers.
                _bare_from = os.environ.get("RESEND_FROM", "onboarding@resend.dev")
                _company = tenant.get("name") or "Pool & Landscaping"
                _safe_name = "".join(
                    ch for ch in _company
                    if ch not in "<>,;\"\r\n" and ord(ch) >= 0x20
                ).strip()
                _from_header = (
                    f"{_safe_name} <{_bare_from}>" if _safe_name else _bare_from
                )
                resp = resend.Emails.send({
                    "from": _from_header,
                    "to": [to_email],
                    "subject": rendered["subject"],
                    "html": rendered["html"],
                    "text": rendered["text"],
                })
                row["status"] = "sent"
                row["resend_id"] = (resp or {}).get("id") if isinstance(resp, dict) else None
                await db.outbound_emails.insert_one(row)
                last_row = row
            except Exception as e:
                row["status"] = "failed"
                row["error"] = str(e)[:200]
                await db.outbound_emails.insert_one(row)
                logger.warning(f"visit-summary email send failed for {to_email}: {type(e).__name__}: {str(e)[:120]}")
                last_row = row
        return last_row
    except Exception as e:
        logger.warning(f"send_visit_summary_email top-level error: {type(e).__name__}: {str(e)[:120]}")
        return None
