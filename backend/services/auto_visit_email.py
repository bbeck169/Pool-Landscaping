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


# ─── Feb-2026 · Property address resolution ─────────────────────────
# The visit-summary email used to read ``job.address`` (a text
# string copied at job-generation time).  That string goes stale
# when a customer moves or when the underlying property is edited
# after the recurring template stamped the job.  We now resolve
# the CURRENT address off ``db.properties`` and fall back to the
# text field only when the property_id is missing or unresolvable.
def _format_property_address(prop: Mapping[str, Any]) -> str:
    """Compose ``"line1, city, STATE POSTAL"`` from a property doc.

    Returns an empty string when the property has no usable address
    fragments — the caller then falls back to ``job.address``.
    """
    addr = prop.get("address")
    if not isinstance(addr, dict):
        return ""
    line1 = (addr.get("line1") or "").strip()
    line2 = (addr.get("line2") or "").strip()
    city = (addr.get("city") or "").strip()
    state = (addr.get("state") or "").strip()
    postal = (addr.get("postal_code") or "").strip()
    street = ", ".join(p for p in (line1, line2) if p)
    tail = " ".join(p for p in (state, postal) if p).strip()
    # Mirror the customer-side composition (see
    # ``routers.customers._mirror_address_to_primary_property``).
    parts: List[str] = []
    if street:
        parts.append(street)
    if city:
        parts.append(city)
    if tail:
        parts.append(tail)
    return ", ".join(parts)


async def _resolve_visit_email_address(
    tenant: Mapping[str, Any], job: Mapping[str, Any],
) -> str:
    """Resolve the address to show in the visit-summary email.

    Ladder (mirrors the ``on_my_way`` FK resolution at
    ``routers/on_my_way.py:93``):

    1. ``job.property_id`` → look up in ``db.properties`` under the
       requester's ``tenant_id`` and compose from the property's
       current ``address`` sub-doc.
    2. ``customer.primary_property_id`` → same lookup.
    3. Fallback → ``job.address`` (previous behavior).

    Emits ``logger.warning("auto_visit_email.property_unresolved",
    ...)`` when the ladder falls through to the text fallback so
    ops can trace stale-FK / cross-tenant / soft-deleted-property
    cases.  Never raises — the caller is a non-blocking best-
    effort path.
    """
    tenant_id = tenant.get("id")
    job_pid = job.get("property_id")
    cust_pid: Optional[str] = None
    fallback = (job.get("address") or "").strip()

    # Ladder rung 2 preflight — ``customer.primary_property_id``.
    if not job_pid:
        cid = job.get("customer_id")
        if tenant_id and cid:
            cust = await db.customers.find_one(
                {"id": cid, "tenant_id": tenant_id},
                {"_id": 0, "primary_property_id": 1},
            )
            if cust:
                cust_pid = cust.get("primary_property_id")

    pid = job_pid or cust_pid
    if not pid or not tenant_id:
        logger.warning(
            "auto_visit_email.property_unresolved "
            "reason=no_property_id tenant_id=%s job_id=%s "
            "customer_id=%s property_id=%s",
            tenant_id, job.get("id"), job.get("customer_id"), pid,
        )
        return fallback

    prop = await db.properties.find_one(
        {"id": pid, "tenant_id": tenant_id},
        {"_id": 0, "id": 1, "address": 1, "deleted_at": 1},
    )
    if not prop:
        # Cross-tenant lookup OR deleted-and-hard-removed property.
        logger.warning(
            "auto_visit_email.property_unresolved "
            "reason=property_not_found tenant_id=%s job_id=%s "
            "customer_id=%s property_id=%s",
            tenant_id, job.get("id"), job.get("customer_id"), pid,
        )
        return fallback
    if prop.get("deleted_at"):
        logger.warning(
            "auto_visit_email.property_unresolved "
            "reason=property_soft_deleted tenant_id=%s job_id=%s "
            "customer_id=%s property_id=%s",
            tenant_id, job.get("id"), job.get("customer_id"), pid,
        )
        return fallback
    composed = _format_property_address(prop)
    if not composed:
        logger.warning(
            "auto_visit_email.property_unresolved "
            "reason=empty_address_fields tenant_id=%s job_id=%s "
            "customer_id=%s property_id=%s",
            tenant_id, job.get("id"), job.get("customer_id"), pid,
        )
        return fallback
    return composed

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
    # CHEM-LOCK · Feb-2026 — route every chem row through
    # ``normalize_chemical`` so both ``quantity``- and ``amount``-only
    # writes render. Skip genuinely-blank rows (no name + no qty +
    # no label) rather than emit empty <li>s. Prior implementation
    # was ``amount``-only, silently dropping every ``quantity``-only
    # row and rendering "Chemical — " for blanks.
    from services.chemical_normalizer import normalize_chemical
    added_raw = sr.get("chemicals_added") or []
    added_norm = [n for n in (normalize_chemical(c) for c in added_raw)
                    if n is not None]
    if added_norm:
        def _row_html(n: dict) -> str:
            name = n["name"] or "Chemical"
            qty = "" if n["quantity"] is None else str(n["quantity"])
            unit = n["unit"] or ""
            return (
                f"<li style='margin:4px 0'>{name} — "
                f"{qty} {unit}</li>"
            )

        def _row_text(n: dict) -> str:
            name = n["name"] or "Chemical"
            qty = "" if n["quantity"] is None else str(n["quantity"])
            unit = n["unit"] or ""
            return f"  • {name} — {qty} {unit}"

        items = "".join(_row_html(n) for n in added_norm)
        sections.append({
            "title": "Chemicals added",
            "html": f"<ul style='padding-left:18px;margin:8px 0'>{items}</ul>",
            "text": "\n".join(_row_text(n) for n in added_norm),
        })
    checklist = sr.get("checklist_completed") or sr.get("checklist_items") or []
    done = [c for c in checklist
            if _checklist_is_done(c)]
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
    done = [c for c in checklist if _checklist_is_done(c)]
    if not done:
        return []
    items = "".join(f"<li>✓ {c.get('label', 'Item')}</li>" for c in done)
    return [{
        "title": "Landscape checklist",
        "html": f"<ul>{items}</ul>",
        "text": "\n".join(f"  ✓ {c.get('label', 'Item')}" for c in done),
    }]


# AUTO-NON-POOL-EMAIL-FIX · Feb-2026 — generic non_pool body
# sections.  Mirrors ``_landscape_body_sections`` but with a
# generic "Completed:" title so the auto-visit email reads
# cleanly for tree_service / hvac / pest_control / irrigation /
# fencing / snow_removal (and any other industry that
# ``_derive_checklist_kind`` classifies as ``"non_pool"``).
# Returns an empty list when nothing was checked off so the
# auto-email never emits an orphan "Completed:" header on an
# empty data set.
def _non_pool_body_sections(sr: dict) -> list[dict]:
    checklist = sr.get("checklist_completed") or sr.get("checklist_items") or []
    done = [c for c in checklist if _checklist_is_done(c)]
    if not done:
        return []
    items = "".join(f"<li>✓ {c.get('label', 'Item')}</li>" for c in done)
    return [{
        "title": "Completed",
        "html": f"<ul>{items}</ul>",
        "text": "\n".join(f"  ✓ {c.get('label', 'Item')}" for c in done),
    }]


# AUTO-NON-POOL-EMAIL-FIX · Feb-2026 — kind-detection seam.
#
# The auto-visit email path historically did a naive substring
# match on ``sr.kind | job.service_type`` (``"landscape" in kind``)
# which left tree_service / hvac / pest_control / irrigation /
# fencing / snow_removal falling through to the pool template.
# The canonical priority chain lives in
# ``routers.jobs._derive_checklist_kind`` and already returns
# ``"pool" | "landscape" | "non_pool"``.
#
# Import is deferred to call time so an interpreter-load ordering
# surprise (routers.jobs still loading, or a lightweight unit test
# that mocks the module out) safely falls back to the pre-fix
# ``"landscape"`` keyword check — zero regression on existing
# landscape routing.
#
# NB: there is NO circular import between
# ``services.auto_visit_email`` and ``routers.jobs``
# (``routers.jobs`` carries no auto_visit_email import at either
# module scope or inside its handlers — verified Feb-2026).  The
# lazy pattern here is defence-in-depth, not a cycle break.
def _derive_recap_kind(sr: Mapping[str, Any],
                       job: Mapping[str, Any]) -> str:
    """Return ``"pool" | "landscape" | "non_pool"`` for a visit.

    ``_derive_checklist_kind`` consults, in order:
      1. ``job.checklist_kind_override``
      2. ``job.industry`` (``"pool"`` / ``"landscaping"`` / else
         ``"non_pool"``)
      3. ``job.service_type`` / ``job.title`` keyword matches
      4. Tech department fallback

    Falls back to the pre-fix keyword match on import / runtime
    error so a surprise interpreter state keeps the previous
    landscape routing intact.
    """
    try:
        from routers.jobs import _derive_checklist_kind as _der
    except Exception:
        _der = None
    if _der is not None:
        try:
            return _der(job or {}, None)
        except Exception:
            pass
    # Keyword-match fallback (pre-fix behaviour).
    kind = (sr.get("kind") or (job or {}).get("service_type")
             or "pool").lower() if sr is not None else "pool"
    if "landscap" in kind:
        return "landscape"
    return "pool"


def _photo_ts(p: Dict[str, Any]) -> str:
    """Sort-key extractor for the photos grid — newest first. Falls
    back to a stable string so the sort is deterministic when the
    ``taken_at`` timestamps aren't set (older seed data)."""
    for k in ("taken_at", "created_at", "uploaded_at", "submitted_at"):
        v = p.get(k)
        if v:
            return str(v)
    return ""


# Feb-2026 · Batch follow-up B — checklist key normaliser.
#
# The customer-facing service report can arrive with two different
# "this item was performed" flags in the wild:
#
# * ``"done"``  — used by older tech submission payloads and the
#   admin-facing annotations in ``routers.service_reports``.
# * ``"checked"`` — used by the current portal / mobile picker
#   widgets and stamped through ``_redact_report_for_customer``
#   (see ``routers/service_reports.py:2571``).
#
# The renderer had four ``c.get("done")`` filters; on the current
# seed shape (all ``checked`` keys) that meant the SERVICE
# CHECKLIST card never rendered in the customer email.  This
# helper is a narrow seam — every renderer accepts BOTH keys and
# the redact / write paths stay unchanged.
def _checklist_is_done(item: Any) -> bool:
    """Return True iff the checklist item was completed by the tech.

    Accepts either shape: ``{"done": True}`` (legacy) OR
    ``{"checked": True}`` (post-redact / current UI widgets).
    Non-dicts and falsy values return False.
    """
    if not isinstance(item, dict):
        return False
    return bool(item.get("done") or item.get("checked"))


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


# ═════════════════════════════════════════════════════════════════════
# Feb-2026 · Portal-style branded template (pool template only).
# ═════════════════════════════════════════════════════════════════════
# In-place restructure of the ``render_email`` pool branch into small
# pure card composers so the email matches the portal service-report
# detail visual (header logo strip → job title card with pills →
# POOL 2x2 metrics grid → service checklist → visit photos).
#
# The landscape branch keeps the pre-existing single-column render
# path so no landscape smoke regressions can leak in.
#
# Email-safety rules honored:
#   * Table-based layout; every card is an outer <table>.
#   * All CSS inline; no <style> block; no external stylesheet.
#   * Images: absolute URLs, ``alt`` set, explicit width/height where
#     known, ``display:block`` on <img>.
#   * Buttons: solid brand-blue backgrounds, no CSS gradients.
#   * Preheader: hidden ``display:none`` pre-render string.
#   * No ``@media`` queries — email clients strip them unpredictably.


# Portal chip color mapping — mirrors ``CHEM_BAND_STYLES`` at
# ``frontend/src/pages/portal/PortalServiceReports.jsx:1229``:
#   below    -> bg-sky-500     -> #0EA5E9
#   average  -> bg-emerald-500 -> #10B981
#   above    -> bg-amber-500   -> #F59E0B
#   elevated -> bg-red-500     -> #EF4444
# Backend band strings come from ``services.chemistry_bands`` and
# are Title Case with a space — mapping key preserves that shape.
_BAND_HEX_MAP: Dict[str, Dict[str, str]] = {
    "Below Average": {"bg": "#0EA5E9", "fg": "#FFFFFF", "label": "Below"},
    "Average":       {"bg": "#10B981", "fg": "#FFFFFF", "label": "Average"},
    "Above Average": {"bg": "#F59E0B", "fg": "#FFFFFF", "label": "Above Avg"},
    "Elevated":      {"bg": "#EF4444", "fg": "#FFFFFF", "label": "Elevated"},
}

# Neutral card + text tokens (email-safe, dark-mode agnostic).
_CARD_BG          = "#FFFFFF"
_CARD_BORDER      = "#E5E7EB"
_CARD_SHADOW      = "0 1px 3px rgba(0,0,0,0.08)"
_TEXT_PRIMARY     = "#0F172A"
_TEXT_SECONDARY   = "#475569"
_TEXT_MUTED       = "#94A3B8"
_SECTION_HEADER   = "#334155"
_CHECKMARK_GREEN  = "#10B981"
_PAGE_BG          = "#F5F7FA"


def _band_style(band: Optional[str]) -> Dict[str, str]:
    """Return the ``{bg, fg, label}`` chip style for a band string.

    Accepts both vocabularies the app produces:

    * ``chemistry_bands`` Title-Case (``"Below Average"``, ``"Above
      Average"``, ``"Average"``, ``"Elevated"``) — the source used
      by ``band_for_reading`` in the non-redacted render path.
    * ``chemistry.classify_reading`` lowercase short tokens
      (``"below"``, ``"above"``, ``"average"``, ``"elevated"``) —
      what the customer-redact pipeline (``_redact_report_for_customer``)
      stamps onto ``sr["chemical_readings"][i]["label"]``.  The
      customer email is the primary consumer of that shape.

    Lookup is case-insensitive; unknown tokens fall through to the
    Average palette so the email always renders SOMETHING legible.
    """
    if band:
        canonical = _BAND_ALIAS.get(str(band).strip().lower())
        if canonical:
            return _BAND_HEX_MAP[canonical]
    return _BAND_HEX_MAP["Average"]


# Feb-2026 · Band-label casing fix (batch follow-up A) — alias every
# lowercase token ``chemistry.classify_reading`` emits (see grep on
# ``services/chemistry.py:125-133``) plus the ``high`` / ``low``
# variants seen historically in older seed rows, mapped to the four
# canonical ``_BAND_HEX_MAP`` buckets.  Keys are pre-lowered so the
# lookup site only needs to lower once.
_BAND_ALIAS: Dict[str, str] = {
    "below":          "Below Average",
    "below average":  "Below Average",
    "low":            "Below Average",
    "average":        "Average",
    "above":          "Above Average",
    "above average":  "Above Average",
    "elevated":       "Elevated",
    "high":           "Elevated",
}


def _render_preheader(company: str, customer_name: str,
                       address: str) -> str:
    """Hidden preheader (Gmail/Apple Mail inbox row snippet)."""
    who = (customer_name or "").strip() or "your visit"
    where = (address or "").strip()
    tail = f" at {where}" if where else ""
    text = f"Visit summary for {who}{tail}"
    return (
        f'<div style="display:none;max-height:0;overflow:hidden;'
        f'mso-hide:all;visibility:hidden;opacity:0;color:transparent;'
        f'height:0;width:0;font-size:1px;line-height:1px;">'
        f'{text}'
        f'</div>'
    )


def _render_pill(text: str, bg: str, fg: str = "#FFFFFF") -> str:
    """Solid-color inline pill."""
    return (
        f'<span style="display:inline-block;background:{bg};color:{fg};'
        f'font-size:12px;font-weight:600;letter-spacing:0.02em;'
        f'padding:4px 10px;border-radius:999px;line-height:1;'
        f'margin-right:6px;white-space:nowrap;">{text}</span>'
    )


def _render_header_bar(company: str, logo_url: Optional[str],
                       palette: Dict[str, str]) -> str:
    """Portal-style top bar: brand-navy strip with the tenant logo
    (or the company name in white when no logo is set)."""
    inner: str
    if logo_url:
        abs_logo = _absolute_url(logo_url)
        inner = (
            f'<img src="{abs_logo}" alt="{company}" '
            f'height="40" '
            f'style="display:block;max-height:40px;height:40px;'
            f'width:auto;border:0;outline:none;text-decoration:none" />'
        )
    else:
        inner = (
            f'<span style="color:#FFFFFF;font-family:system-ui,-apple-'
            f'system,BlinkMacSystemFont,sans-serif;font-size:18px;'
            f'font-weight:700;letter-spacing:0.02em;">{company}</span>'
        )
    return (
        f'<table role="presentation" width="100%" cellspacing="0" '
        f'cellpadding="0" style="background:{palette["primary"]};'
        f'border-collapse:collapse;" bgcolor="{palette["primary"]}">'
        f'<tr><td align="left" '
        f'style="padding:14px 24px;background:{palette["primary"]};" '
        f'bgcolor="{palette["primary"]}">{inner}</td></tr></table>'
    )


def _card_open(padding: str = "20px") -> str:
    return (
        f'<table role="presentation" width="100%" cellspacing="0" '
        f'cellpadding="0" style="background:{_CARD_BG};border:1px '
        f'solid {_CARD_BORDER};border-radius:12px;box-shadow:'
        f'{_CARD_SHADOW};border-collapse:separate;margin-bottom:16px;">'
        f'<tr><td style="padding:{padding};">'
    )


def _card_close() -> str:
    return "</td></tr></table>"


def _render_job_title_card(
    job: Dict[str, Any],
    tech_name: str,
    resolved_address: str,
    visit_date: str,
    service_type_label: str,
    status_label: str,
    palette: Dict[str, str],
) -> str:
    """Hero card: service-type + status pills, title, meta row."""
    title = (job.get("title") or job.get("service_type")
             or "Service visit").strip() or "Service visit"
    pills: List[str] = []
    if service_type_label:
        pills.append(_render_pill(service_type_label, palette["primary"]))
    if status_label:
        pills.append(_render_pill(status_label, palette["primary"]))
    pills_html = "".join(pills)

    meta_bits: List[str] = []
    if visit_date:
        meta_bits.append(
            f'<span style="white-space:nowrap;">📅 {visit_date}</span>')
    if tech_name:
        meta_bits.append(
            f'<span style="white-space:nowrap;">👤 {tech_name}</span>')
    if resolved_address:
        meta_bits.append(
            f'<span>📍 {resolved_address}</span>')
    meta_html = (
        f'<span style="color:{_TEXT_MUTED};">&nbsp;·&nbsp;</span>'
    ).join(meta_bits)

    return (
        _card_open()
        + (
            f'<div style="margin-bottom:10px;">{pills_html}</div>'
            f'<h1 style="margin:0 0 10px;padding:0;'
            f'font-family:system-ui,-apple-system,BlinkMacSystemFont,'
            f'sans-serif;font-size:22px;line-height:1.25;font-weight:700;'
            f'color:{_TEXT_PRIMARY};">{title}</h1>'
            f'<div style="font-family:system-ui,-apple-system,'
            f'BlinkMacSystemFont,sans-serif;font-size:13px;color:'
            f'{_TEXT_SECONDARY};">{meta_html}</div>'
        )
        + _card_close()
    )


def _iter_pool_metric_rows(sr: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Yield ``[{key, label, value, band}, ...]`` for the metrics
    grid — only readings with either a numeric value or a
    pre-computed band label."""
    rows: List[Dict[str, Any]] = []
    for ck, display, val, pre_label in _iter_readings(
            sr.get("chemical_readings") or []):
        has_value = val not in (None, "", 0)
        if not has_value and not pre_label:
            continue
        band = pre_label or (band_for_reading(ck, val) if ck else None)
        rows.append({
            "key": ck or display, "label": display,
            "value": val, "band": band,
        })
    return rows


def _render_pool_metrics_card(sr: Dict[str, Any],
                               palette: Dict[str, str]) -> str:
    """2x2 grid of POOL metric cells."""
    rows = _iter_pool_metric_rows(sr)
    if not rows:
        return ""

    def _cell(row: Dict[str, Any]) -> str:
        style = _band_style(row.get("band"))
        chip = _render_pill(style["label"], style["bg"], style["fg"])
        return (
            f'<td valign="top" width="50%" '
            f'style="padding:8px;width:50%;box-sizing:border-box;">'
            f'<table role="presentation" width="100%" cellspacing="0" '
            f'cellpadding="0" style="background:#F8FAFC;border:1px '
            f'solid {_CARD_BORDER};border-radius:8px;border-collapse:'
            f'separate;">'
            f'<tr><td style="padding:10px 12px;">'
            f'<div style="font-family:system-ui,-apple-system,'
            f'BlinkMacSystemFont,sans-serif;font-size:12px;color:'
            f'{_TEXT_SECONDARY};text-transform:uppercase;letter-spacing:'
            f'0.04em;margin-bottom:4px;">{row["label"]}</div>'
            f'<div>{chip}</div>'
            f'</td></tr></table>'
            f'</td>'
        )

    html_rows: List[str] = []
    for i in range(0, len(rows), 2):
        pair = rows[i:i + 2]
        cells = [_cell(r) for r in pair]
        if len(cells) < 2:
            cells.append(
                '<td valign="top" width="50%" '
                'style="padding:8px;width:50%;">&nbsp;</td>'
            )
        html_rows.append("<tr>" + "".join(cells) + "</tr>")

    grid = (
        f'<table role="presentation" width="100%" cellspacing="0" '
        f'cellpadding="0" style="border-collapse:collapse;margin:-8px;"'
        f'>{"".join(html_rows)}</table>'
    )
    header = (
        f'<div style="font-family:system-ui,-apple-system,'
        f'BlinkMacSystemFont,sans-serif;font-size:13px;font-weight:700;'
        f'letter-spacing:0.06em;color:{_SECTION_HEADER};'
        f'text-transform:uppercase;margin:0 0 12px;">'
        f'💧 POOL</div>'
    )
    return _card_open() + header + grid + _card_close()


def _render_checklist_card(sr: Dict[str, Any]) -> str:
    """Bulleted service checklist — green check per completed item."""
    checklist = (sr.get("checklist_completed")
                  or sr.get("checklist_items") or [])
    done = [c for c in checklist
            if _checklist_is_done(c)]
    if not done:
        return ""
    rows = "".join(
        f'<tr><td valign="top" '
        f'style="padding:6px 0;font-family:system-ui,-apple-system,'
        f'BlinkMacSystemFont,sans-serif;font-size:14px;color:'
        f'{_TEXT_PRIMARY};">'
        f'<span style="display:inline-block;width:18px;height:18px;'
        f'background:{_CHECKMARK_GREEN};color:#FFFFFF;border-radius:'
        f'4px;text-align:center;line-height:18px;font-weight:700;'
        f'font-size:13px;margin-right:10px;vertical-align:middle;">✓'
        f'</span>{c.get("label", "Item")}</td></tr>'
        for c in done
    )
    header = (
        f'<div style="font-family:system-ui,-apple-system,'
        f'BlinkMacSystemFont,sans-serif;font-size:13px;font-weight:700;'
        f'letter-spacing:0.06em;color:{_SECTION_HEADER};'
        f'text-transform:uppercase;margin:0 0 8px;">'
        f'📋 SERVICE CHECKLIST</div>'
    )
    return (
        _card_open()
        + header
        + '<table role="presentation" width="100%" cellspacing="0" '
        + 'cellpadding="0" style="border-collapse:collapse;">'
        + rows
        + '</table>'
        + _card_close()
    )


def _render_photos_card(sr: Dict[str, Any], portal_link: str,
                         safe_photos: List[Dict[str, Any]],
                         palette: Dict[str, str]) -> str:
    """Portal-style visit-photos card."""
    if not safe_photos:
        return ""
    ordered = sorted(safe_photos, key=_photo_ts, reverse=True)
    top6 = ordered[:6]
    overflow = max(0, len(ordered) - 6)
    cells: List[str] = []
    for p in top6:
        url = p.get("url") or p.get("uri") or ""
        if not url:
            continue
        abs_url = _absolute_url(url)
        cells.append(
            f'<td valign="top" width="33.33%" '
            f'style="padding:6px;width:33.33%;box-sizing:border-box;">'
            f'<a href="{portal_link}" '
            f'style="text-decoration:none;color:inherit;">'
            f'<img src="{abs_url}" alt="Visit photo" '
            f'width="180" '
            f'style="display:block;width:100%;max-width:180px;'
            f'height:auto;border-radius:8px;border:1px solid '
            f'{_CARD_BORDER};" />'
            f'</a></td>'
        )
    rows: List[str] = []
    for i in range(0, len(cells), 3):
        chunk = cells[i:i + 3]
        while len(chunk) < 3:
            chunk.append(
                '<td valign="top" width="33.33%" '
                'style="padding:6px;width:33.33%;">&nbsp;</td>'
            )
        rows.append("<tr>" + "".join(chunk) + "</tr>")
    header = (
        f'<div style="font-family:system-ui,-apple-system,'
        f'BlinkMacSystemFont,sans-serif;font-size:13px;font-weight:700;'
        f'letter-spacing:0.06em;color:{_SECTION_HEADER};'
        f'text-transform:uppercase;margin:0 0 8px;">'
        f'🖼️ VISIT PHOTOS</div>'
    )
    body = (
        '<table role="presentation" width="100%" cellspacing="0" '
        'cellpadding="0" style="border-collapse:collapse;margin:-6px;">'
        + "".join(rows)
        + '</table>'
    )
    overflow_html = ""
    if overflow > 0:
        overflow_html = (
            f'<p style="margin:8px 0 0;font-family:system-ui,'
            f'-apple-system,BlinkMacSystemFont,sans-serif;font-size:'
            f'12px;color:{_TEXT_SECONDARY};">'
            f'<a href="{portal_link}" style="color:{palette["accent"]};'
            f'text-decoration:none;font-weight:600;">'
            f'+{overflow} more in your report →</a></p>'
        )
    return _card_open() + header + body + overflow_html + _card_close()


def _compose_visit_summary_text(
    *,
    company: str, customer_name: str,
    service_type_label: str, status_label: str,
    title: str, visit_date: str, tech_name: str,
    resolved_address: str, metric_rows: List[Dict[str, Any]],
    checklist_labels: List[str], photos_count: int,
    photos_overflow: int, portal_link: str,
    customer_notes: str, review_link: Optional[str],
    custom_footer: str,
) -> str:
    """Plain-text sibling with the same info order as the HTML."""
    lines: List[str] = [company, "Service visit summary", ""]
    pills = " · ".join(p for p in (service_type_label, status_label) if p)
    if pills:
        lines.append(pills)
    if title:
        lines.append(title)
    meta = " · ".join(
        p for p in (visit_date, tech_name, resolved_address) if p)
    if meta:
        lines.append(meta)
    lines.append("")
    if metric_rows:
        lines.append("POOL")
        for r in metric_rows:
            style = _band_style(r.get("band"))
            val = r.get("value")
            val_str = f" ({val})" if val not in (None, "", 0) else ""
            lines.append(f"  - {r['label']}: {style['label']}{val_str}")
        lines.append("")
    if checklist_labels:
        lines.append("SERVICE CHECKLIST")
        for lbl in checklist_labels:
            lines.append(f"  - {lbl}")
        lines.append("")
    if photos_count > 0:
        suffix = (f" (+{photos_overflow} more in your portal)"
                  if photos_overflow else "")
        lines.append(
            f"Visit photos: {photos_count} attached{suffix}")
        lines.append(f"  View photos in portal: {portal_link}")
        lines.append("")
    if customer_notes:
        lines += ["Notes from your tech:", customer_notes, ""]
    if review_link:
        lines.append(f"Leave a review: {review_link}")
    lines.append(f"Portal: {portal_link}")
    if custom_footer:
        lines += ["", custom_footer]
    lines += [
        "",
        "Internal service notes are not included in this summary.",
    ]
    return "\n".join(lines)



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
    # AUTO-NON-POOL-EMAIL-FIX · Feb-2026 — canonical 3-way
    # discriminator via ``routers.jobs._derive_checklist_kind``.
    # ``_recap_kind`` preserves the pre-fix keyword fallback so a
    # mocked-out routers.jobs still routes landscape correctly.
    _recap_kind = _derive_recap_kind(sr, job)
    is_landscape = _recap_kind == "landscape"
    is_non_pool = _recap_kind == "non_pool"
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
    elif is_non_pool:
        # AUTO-NON-POOL-EMAIL-FIX · Feb-2026 — route non_pool to the
        # generic "Completed:" sections builder instead of pool
        # metrics / readings so tree_service, hvac, pest_control,
        # irrigation, fencing, snow_removal (and any catch-all
        # ``non_pool`` industry) stop auto-firing with pool framing.
        sections = _non_pool_body_sections(sr)
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

    # ─── HTML + Text ─────────────────────────────────────────────────
    # Feb-2026 · Pool branch → portal-style branded template using
    # the card composers above. Landscape branch stays on the
    # pre-existing single-column render path (no visual regression
    # for landscape reports).
    #
    # AUTO-NON-POOL-EMAIL-FIX · Feb-2026 — the non_pool branch
    # reuses the landscape single-column renderer (same shape,
    # same visual language) and injects an optional "Service type"
    # info row when the job carries a service_type so the customer
    # sees "HVAC Tune-up" / "Weekly pest control" etc. instead of
    # a bare "Service visit summary" header.
    if is_landscape or is_non_pool:
        # Landscape branch — unchanged inline render.
        header_html = (
            f'<table cellspacing="0" cellpadding="0" style="width:100%;'
            f'border-collapse:collapse;background:{palette["primary"]};'
            f'padding:16px 20px" bgcolor="{palette["primary"]}">'
            f'<tr><td>'
        )
        if logo:
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
        # AUTO-NON-POOL-EMAIL-FIX · Feb-2026 — surface the service
        # type on non_pool emails so the customer can tell "HVAC
        # tune-up" from "Pest control re-treat" at a glance.  Only
        # emitted when the job carries an explicit service_type /
        # job_type to avoid a bare "Service type: " row.
        if is_non_pool:
            _svc = (str(job.get("service_type") or job.get("job_type") or "")
                    .strip())
            if _svc:
                # Insert directly after the Date row so the service
                # type is the second row the eye lands on.
                info_rows.insert(1, ("Service type", _svc))
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
        return {"subject": subject, "html": html,
                "text": "\n".join(text_lines),
                "kind": "non_pool" if is_non_pool else "landscape"}

    # ─── Portal-style pool branch (Feb-2026) ─────────────────────────
    # Copy for pill / card composition — falls back to sane defaults
    # so the template still renders on legacy payloads that don't
    # carry ``service_type`` or ``status``.
    service_type_label = (
        (job.get("service_type") or "").strip()
        or (sr.get("kind") or "").strip().title()
        or "Pool service"
    )
    status_label = (
        (job.get("status") or "").strip().title()
        or "Completed"
    )
    tech_name = (sr.get("tech_name") or "").strip()
    resolved_address = (job.get("address") or "").strip()
    customer_name = (customer.get("name") or "").strip()
    metric_rows = _iter_pool_metric_rows(sr)
    checklist_labels = [
        c.get("label", "Item")
        for c in ((sr.get("checklist_completed")
                    or sr.get("checklist_items") or []))
        if _checklist_is_done(c)
    ]
    photos_count = len(safe_photos[:6])
    photos_overflow = max(0, len(safe_photos) - 6)

    # ── CTA row (review + portal) — sits BELOW the cards.
    cta_html = ""
    if include_reviews:
        cta_html += (
            f'<p style="margin:8px 0;text-align:center;">'
            f'<a href="{review_link}" '
            f'style="background:{palette["accent"]};color:#fff;'
            f'text-decoration:none;padding:12px 20px;border-radius:8px;'
            f'display:inline-block;font-weight:600;'
            f'font-family:system-ui,-apple-system,BlinkMacSystemFont,'
            f'sans-serif;">Leave us a review</a></p>'
        )
    cta_html += (
        f'<p style="margin:8px 0;text-align:center;">'
        f'<a href="{portal_link}" '
        f'style="background:{palette["accent"]};color:#fff;'
        f'text-decoration:none;padding:12px 20px;border-radius:8px;'
        f'display:inline-block;font-weight:600;'
        f'font-family:system-ui,-apple-system,BlinkMacSystemFont,'
        f'sans-serif;">View full report →</a></p>'
    )

    # ── Notes card (only when the tech left customer-facing notes).
    notes_html = ""
    if customer_notes:
        notes_html = (
            _card_open()
            + (
                f'<div style="font-family:system-ui,-apple-system,'
                f'BlinkMacSystemFont,sans-serif;font-size:13px;'
                f'font-weight:700;letter-spacing:0.06em;color:'
                f'{_SECTION_HEADER};text-transform:uppercase;'
                f'margin:0 0 8px;">📝 NOTES FROM YOUR TECH</div>'
                f'<p style="margin:0;white-space:pre-line;'
                f'font-family:system-ui,-apple-system,BlinkMacSystemFont,'
                f'sans-serif;font-size:14px;color:{_TEXT_PRIMARY};'
                f'line-height:1.5;">{customer_notes}</p>'
            )
            + _card_close()
        )

    footer_html = (
        f'<p style="color:{_TEXT_MUTED};font-size:12px;margin:24px 0 0;'
        f'text-align:center;font-family:system-ui,-apple-system,'
        f'BlinkMacSystemFont,sans-serif;">'
        f'This is an automatic recap of the customer-facing portion '
        f'of your visit. Internal service notes are not included.'
    )
    if custom_footer:
        footer_html += f' {custom_footer}'
    if app_url:
        footer_html += (
            f' <br/><a href="{app_url}/portal/unsubscribe" '
            f'style="color:{_TEXT_MUTED};text-decoration:underline;">'
            f'Unsubscribe</a>'
        )
    footer_html += "</p>"

    # ── Compose the HTML shell.
    preheader_html = _render_preheader(
        company, customer_name, resolved_address)
    header_bar_html = _render_header_bar(company, logo, palette)
    title_card_html = _render_job_title_card(
        job=job, tech_name=tech_name,
        resolved_address=resolved_address,
        visit_date=visit_date,
        service_type_label=service_type_label,
        status_label=status_label,
        palette=palette,
    )
    metrics_card_html = _render_pool_metrics_card(sr, palette)
    checklist_card_html = _render_checklist_card(sr)
    photos_card_html = _render_photos_card(
        sr, portal_link, safe_photos, palette)

    html = (
        f'<!DOCTYPE html><html><body style="margin:0;padding:0;'
        f'background:{_PAGE_BG};font-family:system-ui,-apple-system,'
        f'BlinkMacSystemFont,\'Segoe UI\',Roboto,sans-serif;">'
        f'{preheader_html}'
        f'<table role="presentation" width="100%" cellspacing="0" '
        f'cellpadding="0" style="background:{_PAGE_BG};'
        f'border-collapse:collapse;">'
        f'<tr><td align="center" style="padding:0;">'
        f'{header_bar_html}'
        f'</td></tr>'
        f'<tr><td align="center" style="padding:24px 12px;">'
        f'<table role="presentation" width="600" cellspacing="0" '
        f'cellpadding="0" style="max-width:600px;width:100%;'
        f'border-collapse:collapse;">'
        f'<tr><td>{title_card_html}</td></tr>'
        f'<tr><td>{metrics_card_html}</td></tr>'
        f'<tr><td>{checklist_card_html}</td></tr>'
        f'<tr><td>{photos_card_html}</td></tr>'
        f'<tr><td>{notes_html}</td></tr>'
        f'<tr><td>{cta_html}</td></tr>'
        f'<tr><td>{footer_html}</td></tr>'
        f'</table></td></tr></table></body></html>'
    )

    text = _compose_visit_summary_text(
        company=company, customer_name=customer_name,
        service_type_label=service_type_label,
        status_label=status_label,
        title=(job.get("title") or job.get("service_type")
                or "Service visit"),
        visit_date=visit_date, tech_name=tech_name,
        resolved_address=resolved_address,
        metric_rows=metric_rows, checklist_labels=checklist_labels,
        photos_count=photos_count, photos_overflow=photos_overflow,
        portal_link=portal_link, customer_notes=customer_notes,
        review_link=(review_link if include_reviews else None),
        custom_footer=custom_footer,
    )

    return {"subject": subject, "html": html, "text": text,
            "kind": "pool"}


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

        # Feb-2026 · Address resolution — read the CURRENT address
        # off ``db.properties`` when the job carries a ``property_id``,
        # falling back to ``job.address`` when the FK is missing /
        # stale / cross-tenant / soft-deleted.  Overlay onto a copy
        # of ``job`` so the pure ``render_email`` function stays
        # DB-free.
        resolved_address = await _resolve_visit_email_address(tenant, job)
        job_for_render = dict(job)
        if resolved_address:
            job_for_render["address"] = resolved_address

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

        rendered = render_email(tenant, job_for_render, safe_sr, customer,
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
                # safe-send: allowlist because legacy direct SDK call is gated by sdk_intercept.install_resend_gate() at the Resend SDK boundary; SAFE-SEND-D full migration pending
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
