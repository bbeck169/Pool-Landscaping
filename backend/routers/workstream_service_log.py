"""Phase 5A.2 · Workstream Service-Log detail aggregator + door-hanger email.

Endpoints
=========
* ``GET  /api/jobs/{jid}/service-log``      — admin-only aggregator that
  returns EVERY chunk the new Service Log detail view needs in one call:
  log_details, checklist_state, water_test, chemicals_used,
  chemical_cost_usd, service_images, previous_service, employee,
  customer, property.
* ``POST /api/jobs/{jid}/email-door-hanger`` — admin-only. Renders a door
  hanger via the existing Resend adapter from ``cs@plofv.com`` (or the
  tenant-configured fallback) and logs a ``marketing_deliveries`` row
  with ``trigger_entity.kind == 'job_door_hanger'``. Idempotency-guarded
  — a second send within 60s returns HTTP 429 with the original delivery
  id in the response body.

Chemical cost pricing
=====================
Cost is computed server-side from a deterministic price lookup so the
UI can render the red "Chemical Cost $XX.XX" pill without needing a
second call. Prices live in ``chemical_prices`` (per-tenant document);
if a tenant has no override, the ``_DEFAULT_CHEM_PRICES`` fallback
below is used. All prices are USD cents to keep money as ints.

    3" Chlorine Tablets   → $1.20 / tablet
    Liquid Chlorine       → $8.00 / gallon
    Liquid Acid           → $8.00 / gallon
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from config import db, logger
from routers.tenants import get_current_tenant
from services.service_report_view import (
    resolve_water_test as _resolve_water_test,
    resolve_chemicals_used_with_cost as _resolve_chems_with_cost,
    resolve_checklist_state as _resolve_checklist_shared,
    resolve_notes as _resolve_notes,
    resolve_photo_items as _resolve_photo_items,
)
from services.job_assignee import effective_tid
from utils import get_current_user, new_id, now_iso
from utils import not_deleted_filter as _nd

router = APIRouter()


# ─── Constants ────────────────────────────────────────────────────────
_DEFAULT_CHEM_PRICES_CENTS: Dict[str, int] = {
    # keys are the canonical lower-cased ``item.name`` from
    # chemicals_added entries. Aliases fold in normalise().
    "chlorine tablets":       120,   # per tablet
    "3\" chlorine tablets":   120,
    "liquid chlorine":        800,   # per gallon
    "liquid acid":            800,   # per gallon
    "muriatic acid":          800,
}

_DOOR_HANGER_COOLDOWN_SECS = 60


def _is_admin(user: dict) -> bool:
    return (user or {}).get("role") in ("admin", "super_admin")


def _require_admin_or_403(user: dict) -> None:
    if not _is_admin(user):
        raise HTTPException(403, "Admin access required")


def _norm(s: Any) -> str:
    return re.sub(r"\s+", " ", str(s or "").strip()).lower()


async def _load_price_map(tenant_id: str) -> Dict[str, int]:
    doc = await db.chemical_prices.find_one(
        {"tenant_id": tenant_id}, {"_id": 0, "prices": 1},
    ) or {}
    prices = doc.get("prices") or {}
    merged = {**_DEFAULT_CHEM_PRICES_CENTS}
    for k, v in prices.items():
        try:
            merged[_norm(k)] = int(round(float(v) * 100))
        except (TypeError, ValueError):
            continue
    return merged


def _chem_line_cost_cents(name: str, qty: float, prices: Dict[str, int]) -> int:
    key = _norm(name)
    if key in prices:
        return int(round(qty * prices[key]))
    # loose contains-match fallback so "Chlorine Tablets (3\")" still hits.
    for k, price in prices.items():
        if k and k in key:
            return int(round(qty * price))
    return 0


def _addr_str(address: Any) -> Optional[str]:
    if not address:
        return None
    if isinstance(address, str):
        return address.strip() or None
    if not isinstance(address, dict):
        return None
    parts = [address.get("line1"), address.get("city"),
             address.get("state"), address.get("postal_code")]
    return ", ".join([p for p in parts if p]) or None


def _photo_thumb(jid: str, pid: str) -> str:
    return f"/api/public/job-photo/{jid}/{pid}"


def _video_url(storage_path: str) -> str:
    return f"/api/media/videos/{storage_path}"


def _classify(job: dict) -> str:
    """Return 'pool' | 'landscape' — reuse the same heuristic surface as
    jobs.py so the ServiceLog view lines up with the rest of the app."""
    from routers.jobs import _derive_checklist_kind
    return _derive_checklist_kind(job, (job.get("_technician_department") or None))


async def _resolve_checklist_state(job: dict, tenant_id: str) -> Dict[str, Any]:
    """Thin adapter — the canonical implementation lives in
    ``services/service_report_view.resolve_checklist_state``.  Kept
    in this module (as ``_resolve_checklist_state``) for backward
    compat with tests that import it directly."""
    from routers.checklists import DEFAULT_POOL_ITEMS, DEFAULT_LANDSCAPE_ITEMS
    return await _resolve_checklist_shared(
        db, job, tenant_id, _classify(job),
        DEFAULT_POOL_ITEMS, DEFAULT_LANDSCAPE_ITEMS,
    )


async def _water_test(job: dict, tenant_id: str) -> List[Dict[str, Any]]:
    """Thin adapter — see
    ``services/service_report_view.resolve_water_test``."""
    return await _resolve_water_test(db, job, tenant_id)


async def _chemicals_used_source(job: dict, tenant_id: str) -> List[Dict[str, Any]]:
    """Thin adapter — returns raw ``chemicals_added`` list."""
    from services.service_report_view import resolve_chemicals_used_raw
    return await resolve_chemicals_used_raw(db, job, tenant_id)


def _media_items(job: dict) -> List[Dict[str, Any]]:
    photos = job.get("photos") or []
    videos = [v for v in (job.get("videos") or []) if not v.get("is_deleted")]
    jid = job.get("id") or ""
    out: List[Dict[str, Any]] = []
    for p in photos:
        pid = p.get("id")
        if not pid:
            continue
        out.append({
            "id": pid,
            "kind": "image",
            "url": _photo_thumb(jid, pid),
            "label": p.get("label"),
            "created_at": p.get("created_at"),
        })
    for v in videos:
        sp = v.get("storage_path")
        if not sp:
            continue
        out.append({
            "id": v.get("id"),
            "kind": "video",
            "url": _video_url(sp),
            "mime": v.get("mime"),
            "duration_ms": int((v.get("duration_seconds") or 0) * 1000) or None,
            "caption": v.get("caption"),
        })
    return out


async def _previous_service(job: dict, tenant_id: str) -> List[Dict[str, Any]]:
    pid = job.get("property_id")
    cid = job.get("customer_id")
    q: Dict[str, Any] = {
        "tenant_id": tenant_id,
        "status": "completed",
        "id": {"$ne": job.get("id")},
    }
    if pid:
        q["property_id"] = pid
    elif cid:
        q["customer_id"] = cid
    else:
        return []
    q = {**q, **_nd()}
    docs = await db.jobs.find(
        q,
        {"_id": 0, "id": 1, "completed_at": 1, "scheduled_date": 1,
         "service_type": 1, "title": 1},
    ).sort("completed_at", -1).limit(5).to_list(5)
    return [{
        "job_id": d.get("id"),
        "completed_at": d.get("completed_at") or d.get("scheduled_date"),
        "title": d.get("title") or d.get("service_type") or "Service",
    } for d in docs]


# ─── GET /api/jobs/{jid}/service-log ─────────────────────────────────
@router.get("/jobs/{jid}/service-log")
async def get_service_log(
    jid: str,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    _require_admin_or_403(user)
    job = await db.jobs.find_one(
        {"id": jid, "tenant_id": tenant["id"]}, {"_id": 0},
    )
    if not job:
        raise HTTPException(404, "Job not found")

    # Enrich with technician_department so _classify() can pick pool/land.
    # Feb-2026 · P1 hotfix — read-path union across all four tech-id
    # field shapes (see ``services/job_assignee.py``).
    tid = effective_tid(job)
    if tid:
        # Fetch a doc under all four id shapes for department + phone.
        tech = await db.technicians.find_one(
            {"$or": [{"id": tid}, {"user_id": tid}], "tenant_id": tenant["id"]},
            {"_id": 0, "id": 1, "name": 1, "phone": 1, "department": 1},
        ) or {}
        job["_technician_department"] = tech.get("department")
        # Name resolution goes through the shared cascade so a
        # ``users.id``-shaped ``technician_id`` still renders.
        from services.service_report_view import resolve_technician_names
        _names = await resolve_technician_names(db, tenant["id"], [tid])
        resolved_name = _names.get(tid) or tech.get("name") \
            or job.get("technician_name") or "Unassigned"
        employee = {
            "id": tech.get("id") or tid,
            "name": resolved_name,
            "phone": tech.get("phone"),
            "department": tech.get("department"),
        }
    else:
        employee = {"id": None, "name": "Unassigned", "phone": None, "department": None}

    kind = _classify(job)

    cust = None
    if job.get("customer_id"):
        cust = await db.customers.find_one(
            {"id": job["customer_id"], "tenant_id": tenant["id"]},
            {"_id": 0, "id": 1, "name": 1, "email": 1, "phone": 1, "address": 1},
        )
    prop = None
    if job.get("property_id"):
        prop = await db.properties.find_one(
            {"id": job["property_id"], "tenant_id": tenant["id"]},
            {"_id": 0, "id": 1, "label": 1, "address": 1},
        )

    prop_addr = _addr_str((prop or {}).get("address")) or _addr_str((cust or {}).get("address"))

    # Time spent: prefer started/completed pair; fall back to duration.
    time_spent_min: Optional[int] = None
    started = job.get("started_at")
    completed = job.get("completed_at")
    if started and completed:
        try:
            s = datetime.fromisoformat(str(started).replace("Z", "+00:00"))
            c = datetime.fromisoformat(str(completed).replace("Z", "+00:00"))
            time_spent_min = max(int((c - s).total_seconds() // 60), 0)
        except Exception:
            time_spent_min = None
    if not time_spent_min and job.get("duration_minutes"):
        try:
            time_spent_min = int(job["duration_minutes"])
        except (TypeError, ValueError):
            pass

    # Chemicals used + cost.
    # P0 · Feb 2026 (Fix B) — source list now comes from the
    # ``_chemicals_used_source`` helper (service_reports → job legacy
    # fallback).  Cost math + price map are unchanged.
    prices = await _load_price_map(tenant["id"])
    chems_used: List[Dict[str, Any]] = []
    total_cents = 0
    for c in await _chemicals_used_source(job, tenant["id"]):
        name = c.get("name") or c.get("chemical") or ""
        qty = c.get("quantity") or c.get("amount") or 0
        unit = c.get("unit") or ""
        try:
            qty_f = float(qty)
        except (TypeError, ValueError):
            qty_f = 0.0
        cost_c = _chem_line_cost_cents(name, qty_f, prices)
        total_cents += cost_c
        chems_used.append({
            "name": name,
            "quantity": qty_f,
            "unit": unit,
            "display": _format_chem_qty(qty_f, unit),
            "cost_cents": cost_c,
        })

    payload = {
        "job_id": jid,
        "service_line": kind,
        "log_details": {
            "customer_name": (cust or {}).get("name") or job.get("customer_name") or "",
            "customer_id": (cust or {}).get("id"),
            "customer_email": (cust or {}).get("email"),
            "customer_phone": (cust or {}).get("phone") or job.get("customer_phone"),
            "property_address": prop_addr,
            "property_id": (prop or {}).get("id"),
            "service_at": completed or job.get("scheduled_date"),
            "time_spent_minutes": time_spent_min,
            "employee_name": employee["name"],
            "employee_id": employee["id"],
            # Feb-2026 · Repair-mode marker for the workstream badge.
            # ``work_class`` on the job is the source of truth; the
            # service_report copy inherits it at bootstrap.
            "work_class": (job.get("work_class") or "service").lower(),
        },
        "employee": employee,
        "customer": cust,
        "property": prop,
        "checklist_state": await _resolve_checklist_state(job, tenant["id"]),
        "water_test": await _water_test(job, tenant["id"]) if kind == "pool" else [],
        "chemicals_used": chems_used if kind == "pool" else [],
        "chemical_cost_cents": total_cents if kind == "pool" else 0,
        "chemical_cost_usd": round(total_cents / 100.0, 2) if kind == "pool" else 0.0,
        "service_notes": job.get("service_notes") or job.get("notes") or "",
        "materials_used": [
            li for li in (job.get("line_items") or []) if li.get("material")
        ] if kind == "landscape" else [],
        "service_images": _media_items(job),
        "previous_service": await _previous_service(job, tenant["id"]),
    }
    return payload


def _format_chem_qty(qty: float, unit: str) -> str:
    unit = (unit or "").strip()
    if unit.lower() in ("gal", "gallon", "gallons"):
        u = "Gallon" if qty <= 1 else "Gallons"
        return f"{int(qty) if qty == int(qty) else qty} {u}"
    if unit:
        return f"{int(qty) if qty == int(qty) else qty} {unit}"
    return str(int(qty) if qty == int(qty) else qty)


# ─── Service-date formatter ──────────────────────────────────────────
_DEFAULT_TZ_NAME = "America/Phoenix"


def _format_service_date(job: Dict[str, Any], tenant: Dict[str, Any]) -> str:
    """Long-form ("Monday, November 4, 2025") service date in the
    tenant's timezone.

    Field cascade: ``job.completed_at`` → ``job.scheduled_end`` →
    ``job.scheduled_start`` → ``datetime.utcnow()``.  Timezone cascade:
    ``tenant.timezone`` → ``tenant.settings.timezone`` →
    ``America/Phoenix`` (pod-wide fallback — same default used by
    ``services/invoice_numbering.py``,
    ``services/equipment_trackers_cron.py``, and the Phase 12C tenant
    timezone backfill in ``services/add_card_links.py``).
    """
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    raw = (
        job.get("completed_at")
        or job.get("scheduled_end")
        or job.get("scheduled_start")
    )
    dt: Optional[datetime] = None
    if raw:
        try:
            dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            dt = None
    if dt is None:
        dt = datetime.now(timezone.utc)

    tz_name = (
        (tenant or {}).get("timezone")
        or ((tenant or {}).get("settings") or {}).get("timezone")
        or _DEFAULT_TZ_NAME
    )
    try:
        tz = ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        tz = ZoneInfo(_DEFAULT_TZ_NAME)
    local = dt.astimezone(tz)
    # ``%A, %B %-d, %Y`` — but ``%-d`` is Linux-only; strip the padding
    # zero manually so this works on macOS + Windows if ever exercised.
    day = str(local.day)
    return f"{local.strftime('%A')}, {local.strftime('%B')} {day}, {local.year}"


# ─── Door-hanger email · shared builder + dispatcher ─────────────────
# Feb-2026 · Part A + Part B refactor.  The body composition and the
# Resend dispatch are hoisted out of the POST endpoint so BOTH the
# manual endpoint and the auto-send on job-completion path share a
# single template + delivery record shape.  Only the dedupe primitive
# differs — see :func:`maybe_auto_send_door_hanger` below.
#
# Feb-2026 · Slice 5 — Visual redesign.  ``_build_door_hanger_email``
# is now a thin orchestrator; each section is built by a dedicated
# ``_dh_render_*`` helper (below) that returns an email-safe
# ``<table>``-wrapped card.  Inline styles only — no ``<style>``
# blocks, no ``class=`` attributes.  All existing body copy is
# preserved verbatim; the only new copy lives in the elevated-CTA
# helper.


# Chip color map for water-test band chips (email-safe, inline only).
_DH_BAND_CHIPS = {
    "Below Average": {"bg": "#DBEAFE", "fg": "#1E40AF"},
    "Average":       {"bg": "#DCFCE7", "fg": "#166534"},
    "Above Average": {"bg": "#FEF3C7", "fg": "#92400E"},
    "Elevated":      {"bg": "#FEE2E2", "fg": "#991B1B"},
}


# Feb-2026 · Door-hanger water-test layout — customer-facing labels
# in fixed display order. Combined Chlorine is intentionally NOT in
# the list (product spec). Any key not present here is dropped by
# the renderer, so unknown / experimental readings never leak.
_DH_DISPLAY_ORDER = [
    ("free_chlorine",    "Free Chlorine"),
    ("total_chlorine",   "Total Chlorine"),
    ("ph",               "pH"),
    ("alkalinity",       "Alkalinity"),
    ("cyanuric_acid",    "Cyanuric Acid"),
    ("calcium_hardness", "Calcium Hardness"),
    ("salt",             "Salt"),
    ("tds",              "TDS"),
    ("phosphates",       "Phosphates"),
    ("water_temp",       "Water Temp"),
]

# Core (chemistry-gate-required) readings — see
# ``services/chemistry_gate.py::CORE_READINGS``. Duplicated as a
# ``frozenset`` here because the renderer needs O(1) membership and
# a stable local reference (avoids a circular import at module load).
_DH_CORE_KEYS = frozenset({
    "free_chlorine", "total_chlorine", "ph", "alkalinity", "cyanuric_acid",
})


def _dh_band_chip(band: str) -> str:
    """Return a pill-shaped band chip with inline styles.

    The ``<b>{band}</b>`` inner markup is intentional — several
    existing regression tests slice the Water Test section and
    assert on ``<b>Average</b>`` / ``<b>Elevated</b>`` substrings.
    """
    tone = _DH_BAND_CHIPS.get(band, _DH_BAND_CHIPS["Average"])
    return (
        f'<span style="display:inline-block;padding:3px 10px;'
        f'border-radius:12px;background:{tone["bg"]};color:{tone["fg"]};'
        f'font-size:12px;line-height:1.4;">'
        f'<b>{band}</b></span>'
    )


def _dh_card(inner_html: str, *, bg: str = "#FFFFFF",
             border: str = "#E2E8F0") -> str:
    """Email-safe card wrapper — ``<table role="presentation">`` for
    Outlook parity. Fixed 100% width, 12px radius, subtle border.
    """
    return (
        f'<table role="presentation" cellpadding="0" cellspacing="0" '
        f'border="0" width="100%" style="border-collapse:collapse;'
        f'background:{bg};border:1px solid {border};'
        f'border-radius:12px;margin:0 0 16px 0;">'
        f'<tr><td style="padding:20px;">{inner_html}</td></tr></table>'
    )


def _dh_section_heading(text: str) -> str:
    """``<h3>`` for the section heading — kept as ``<h3>`` (not
    ``<p>``) so the existing regression tests that anchor slices on
    ``Water Test</h3>`` / ``Chemicals Used</h3>`` remain valid.
    """
    return (
        f'<h3 style="color:#0F172A;margin:0 0 12px 0;font-size:16px;'
        f'font-weight:700;">{text}</h3>'
    )


def _dh_render_hero(*, logo_url: str, company: str, first_name: str,
                     service_date: str, job_title: str,
                     service_address: str, completed: Any) -> str:
    """Header card — centered logo + greeting + service date + job
    title + service address + completion date.  Copy is unchanged
    from the pre-Slice-5 builder; every line uses inline styles."""
    logo = (
        f'<div style="text-align:center;margin-bottom:20px;">'
        f'<img src="{logo_url}" alt="{company}" width="200" '
        f'style="max-width:200px;height:auto;display:inline-block;"/>'
        f'</div>'
    )
    inner = [
        logo,
        f'<p style="color:#0F172A;margin:0 0 8px;font-size:15px;'
        f'font-weight:normal;">'
        f'Hi {first_name}, your visit has been completed.</p>',
    ]
    if service_date:
        inner.append(
            f'<p style="margin:4px 0;font-size:14px;color:#555;">'
            f'Service Date: {service_date}</p>'
        )
    if job_title:
        inner.append(
            f'<p style="margin:4px 0;font-size:15px;"><b>{job_title}</b></p>'
        )
    if service_address:
        inner.append(
            f'<p style="margin:4px 0;font-size:14px;color:#334155;">'
            f'<b>{service_address}</b></p>'
        )
    inner.append(
        f'<p style="font-size:13px;color:#64748B;margin-top:8px;">'
        f'Completed on <b>{str(completed)[:10]}</b>.</p>'
    )
    return _dh_card("".join(inner))


def _dh_render_water_test(water_test: List[Dict[str, Any]]) -> str:
    """Water Test card — customer-facing labels + range chips for
    every configured reading.

    Feb-2026 spec (product-approved):
      * Combined Chlorine is intentionally NOT rendered — customers
        find the row confusing and it's noise on the email.
      * Long-form labels ("Free Chlorine", "Cyanuric Acid") replace
        the tech-facing shorthand ("Free Cl", "CYA"). Tech UIs keep
        their compact chips via ``chemistry_gate.DISPLAY_LABELS``.
      * Every banded key (5 core + 4 extended: calcium hardness,
        salt, TDS, phosphates) renders a chip; Water Temp is
        informational-only and renders as raw value + unit.
      * Zero-valued OPTIONAL readings are treated as an
        "unmeasured" sentinel and omitted (many techs skip these on
        routine visits and the checklist defaults to 0.0). CORE
        readings render even at 0 — the chemistry gate already
        requires them at submit, so 0 there is a legitimate value.
    """
    if not water_test:
        return ""
    from services.chemistry_bands import band_for_reading

    by_key = {r.get("key"): r for r in water_test if r.get("key")}

    def _row_html(label: str, right_html: str) -> str:
        return (
            f'<tr>'
            f'<td style="padding:6px 12px 6px 0;color:#64748B;font-size:14px;'
            f'white-space:nowrap;vertical-align:middle;">{label}</td>'
            f'<td style="padding:6px 0;text-align:right;vertical-align:middle;">'
            f'{right_html}</td>'
            f'</tr>'
        )

    rows = ""
    for key, label in _DH_DISPLAY_ORDER:
        r = by_key.get(key)
        if not r:
            continue
        v = r.get("value")
        if v is None or v == "":
            continue
        # Zero-sentinel skip for optional readings — see docstring.
        if key not in _DH_CORE_KEYS:
            try:
                _fv = float(v)
            except (TypeError, ValueError):
                _fv = None
            if _fv == 0:
                continue
        band = band_for_reading(key, v)
        if band:
            rows += _row_html(label, _dh_band_chip(band))
        else:
            # Informational (e.g. water_temp) — raw value + unit.
            val_str = f"{v} {r.get('unit') or ''}".strip()
            rows += _row_html(
                label,
                f'<span style="color:#0F172A;font-size:14px;'
                f'font-weight:600;"><b>{val_str}</b></span>',
            )

    if not rows:
        return ""
    body = (
        _dh_section_heading("Water Test") +
        f'<table role="presentation" cellpadding="0" cellspacing="0" '
        f'border="0" width="100%" '
        f'style="border-collapse:collapse;font-size:14px;">{rows}</table>'
    )
    return _dh_card(body)


def _dh_elevated_core_count(water_test: List[Dict[str, Any]]) -> int:
    """Count of *core* readings in the ``Elevated`` band.  Returns 0
    for non-pool jobs (empty ``water_test``) so the CTA is naturally
    suppressed on landscaping-only visits.
    """
    if not water_test:
        return 0
    from services.chemistry_bands import band_for_reading
    from services.chemistry_gate import CORE_READINGS
    by_key = {r["key"]: r for r in water_test}
    n = 0
    for key in CORE_READINGS:
        r = by_key.get(key)
        if not r:
            continue
        if band_for_reading(key, r.get("value")) == "Elevated":
            n += 1
    return n


def _dh_render_elevated_cta(*, elevated_count: int,
                              cust: Optional[Dict[str, Any]],
                              tenant: Optional[Dict[str, Any]],
                              job_id: str, brand_color: str) -> str:
    """Feb-2026 · Slice 5 — service-recommendation CTA block.

    Rendered ONLY when 2+ core readings land in the ``Elevated`` band
    AND the customer has not opted out. Landscape jobs never trigger
    (they carry an empty ``water_test`` → ``elevated_count == 0``).

    Suppression rules (each returns ``""`` — the caller silently
    drops the block):
      * ``elevated_count < 2``
      * ``cust.unsubscribed`` or ``cust.do_not_contact``
    When ``tenant.phone`` (or ``rc_sms_from_number``) is missing the
    Call button is hidden and the Reply button spans full-width.
    """
    if elevated_count < 2:
        return ""
    if cust and (bool(cust.get("unsubscribed"))
                 or bool(cust.get("do_not_contact"))):
        return ""

    # Mailto cascade: reply-to sender → tenant support/contact → fallback.
    settings = ((tenant or {}).get("settings") or {})
    sender = settings.get("email_sender") or {}
    reply_email = (
        sender.get("reply_to")
        or (tenant or {}).get("support_email")
        or (tenant or {}).get("contact_email")
        or "hello@plofv.com"
    )
    # ``%20%E2%80%94%20`` = " — " (space + em-dash + space) URL-safe.
    mailto = (
        f'mailto:{reply_email}?subject='
        f'Follow-Up%20Request%20%E2%80%94%20Job%20{job_id}'
    )
    reply_btn = (
        f'<a href="{mailto}" '
        f'style="display:inline-block;background:{brand_color};'
        f'color:#FFFFFF;padding:14px 32px;border-radius:8px;'
        f'text-decoration:none;font-weight:600;font-size:14px;'
        f'text-align:center;line-height:1;">'
        f'Reply to Schedule Follow-Up</a>'
    )
    # Configured phone (no hardcoded fallback — CTA button hides if
    # nothing is on the tenant record; footer still uses the wider
    # cascade with the hardcoded fallback).
    configured_phone = (
        (tenant or {}).get("phone")
        or (tenant or {}).get("rc_sms_from_number")
    )
    if configured_phone:
        tel_digits = "".join(ch for ch in configured_phone if ch.isdigit() or ch == "+")
        call_btn = (
            f'<a href="tel:{tel_digits}" '
            f'style="display:inline-block;background:#FFFFFF;'
            f'color:{brand_color};padding:13px 32px;'
            f'border:1px solid {brand_color};border-radius:8px;'
            f'text-decoration:none;font-weight:600;font-size:14px;'
            f'text-align:center;line-height:1;">'
            f'Call {configured_phone}</a>'
        )
        button_row = (
            f'<table role="presentation" cellpadding="0" cellspacing="0" '
            f'border="0" width="100%" '
            f'style="border-collapse:collapse;margin-top:16px;">'
            f'<tr>'
            f'<td width="50%" align="center" '
            f'style="padding:4px 6px 4px 0;">{reply_btn}</td>'
            f'<td width="50%" align="center" '
            f'style="padding:4px 0 4px 6px;">{call_btn}</td>'
            f'</tr></table>'
        )
    else:
        button_row = (
            f'<div style="text-align:center;margin-top:16px;">{reply_btn}</div>'
        )

    body = (
        f'<p style="margin:0 0 4px 0;color:#64748B;font-size:11px;'
        f'font-weight:700;letter-spacing:0.08em;'
        f'text-transform:uppercase;">NEXT STEPS</p>'
        f'<p style="margin:0 0 8px 0;color:#0F172A;font-size:16px;'
        f'font-weight:700;">A few readings look elevated</p>'
        f'<p style="margin:0;color:#334155;font-size:14px;line-height:1.5;">'
        f"A couple of today's readings came back on the higher side. "
        f"We'd like to swing by for a quick follow-up to get things back "
        f'to ideal.</p>'
        f'{button_row}'
    )
    return _dh_card(body, bg="#FFFBF5", border="#FDE68A")


def _dh_render_chemicals(chems_used: List[Dict[str, Any]]) -> str:
    """Chemicals Used card. Feb-2026 · Slice 4 (chemical cost hide)
    invariant: customer-facing view — no cost line, no ``$`` symbols.
    """
    if not chems_used:
        return ""
    rows = "".join(
        f'<li style="margin:4px 0;color:#0F172A;font-size:14px;">'
        f'{c["name"]} — {c.get("display") or c["quantity"]}</li>'
        for c in chems_used
    )
    body = (
        _dh_section_heading("Chemicals Used") +
        f'<ul style="padding-left:20px;margin:4px 0;">{rows}</ul>'
    )
    return _dh_card(body)


def _dh_render_checklist(checklist_items: List[Dict[str, Any]]) -> str:
    if not checklist_items:
        return ""

    def _tick(done: bool) -> str:
        return "&#10003;" if done else "&#9633;"

    rows = "".join(
        f'<li style="margin:4px 0;font-size:14px;list-style:none;'
        f'color:{"#0F172A" if it["completed"] else "#94A3B8"};">'
        f'{_tick(bool(it["completed"]))} {it["label"]}</li>'
        for it in checklist_items
    )
    body = (
        _dh_section_heading("Service Checklist") +
        f'<ul style="padding-left:0;margin:4px 0;list-style:none;">'
        f'{rows}</ul>'
    )
    return _dh_card(body)


def _dh_render_notes(notes_text: str) -> str:
    """Notes card.  When notes are empty renders the muted ``Notes:
    —`` fallback line (copy preserved verbatim from pre-Slice-5)."""
    if notes_text:
        safe = (notes_text.replace("<", "&lt;")
                            .replace(">", "&gt;")
                            .replace("\n", "<br/>"))
        body = (
            _dh_section_heading("Notes from your technician") +
            f'<div style="font-size:14px;color:#0F172A;'
            f'white-space:pre-wrap;">{safe}</div>'
        )
        return _dh_card(body)
    # Empty-state fallback — muted, no card. Copy MUST match the
    # existing "Notes: —" contract asserted by
    # ``test_door_hanger_empty_report_renders_gracefully``.
    return (
        f'<p style="color:#94A3B8;font-size:13px;margin:16px 0;'
        f'text-align:center;">Notes: —</p>'
    )


def _dh_render_photos(photos: List[Dict[str, Any]]) -> str:
    if not photos:
        return ""
    thumbs = "".join(
        f'<a href="{p["url_absolute"]}" '
        f'style="display:inline-block;margin:4px;">'
        f'<img src="{p["url_absolute"]}" '
        f'alt="{(p.get("label") or "service photo")}" '
        f'width="140" style="display:block;border-radius:8px;'
        f'border:1px solid #E2E8F0;"/></a>'
        for p in photos
    )
    body = (
        _dh_section_heading("Service Photos") +
        f'<div style="margin:4px 0;text-align:center;">{thumbs}</div>'
    )
    return _dh_card(body)


def _dh_render_portal_cta(portal_url: str, brand_color: str) -> str:
    """Feb-2026 · Addition 2 — portal auto-login CTA.  Copy preserved
    verbatim ("View Service Report in Portal").
    """
    return (
        f'<div style="text-align:center;margin:24px 0 8px 0;">'
        f'<a href="{portal_url}" '
        f'style="display:inline-block;background:{brand_color};'
        f'color:#FFFFFF;padding:12px 24px;border-radius:6px;'
        f'text-decoration:none;font-weight:600;font-size:14px;">'
        f'View Service Report in Portal</a>'
        f'</div>'
    )


def _dh_render_footer(company: str, tenant_phone: str) -> str:
    """Footer copy preserved verbatim ("We appreciate your business" +
    company name + phone). Centered for the card layout.
    """
    return (
        f'<p style="font-size:13px;color:#334155;margin-top:24px;'
        f'text-align:center;">We appreciate your business<br/>'
        f'<b>{company}</b><br/>'
        f'{tenant_phone}</p>'
    )


async def _record_elevated_followup_shown(
    *, tenant_id: str, customer_id: Optional[str], job_id: str,
) -> None:
    """Feb-2026 · Slice 5 add-on — measurable channel for the
    Elevated readings CTA. Emits ONE ``marketing_event_ledger`` row
    per job, keyed ``elevated_followup_shown:{job_id}``.

    Idempotent — repeat manual resends of the same job never create
    duplicate rows (relies on the same unique compound index the
    drip-events dedupe uses). Silent on any error — this is
    observability, not a business gate.
    """
    if not (tenant_id and job_id):
        return
    try:
        await _ensure_auto_send_index()
        await db.marketing_event_ledger.insert_one({
            "id": new_id(), "tenant_id": tenant_id,
            "customer_id": customer_id,
            "event_key": f"elevated_followup_shown:{job_id}",
            "trigger_type": "elevated_followup_shown",
            "correlation_id": job_id,
            "processed_at": now_iso(),
            "meta": {"job_id": job_id},
        })
    except Exception as exc:
        # DuplicateKeyError is the happy path (idempotent). Anything
        # else is logged and swallowed — we NEVER let observability
        # writes block or fail an email send.
        if type(exc).__name__ != "DuplicateKeyError":  # pragma: no cover
            logger.warning(
                f"[door-hanger] elevated_followup_shown ledger "
                f"insert failed: {exc}"
            )


async def _build_door_hanger_email(
    *, job: Dict[str, Any], tenant: Dict[str, Any],
    cust: Dict[str, Any], cid: Optional[str],
) -> Dict[str, Any]:
    """Compose the subject + HTML body for the door-hanger email.
    Pure builder — no send, no DB writes beyond the read helpers.
    Returns ``{"subject": str, "html": str}``.

    Feb-2026 · Slice 5 — Visual redesign: each section now renders
    inside an email-safe *card* (``<table role="presentation">``
    wrapper) via ``_dh_render_*`` helpers so the output looks the same
    in Gmail, Outlook, and iOS Mail. Inline styles only — no
    ``<style>`` blocks and no ``class=`` attributes. All body copy is
    preserved verbatim; the only new copy is the Elevated CTA block
    (see ``_dh_render_elevated_cta``).
    """
    # P0 · Feb 2026 — resolve every service-report chunk via the same
    # helpers the Workstream Service Log page uses (chemistry,
    # chemicals used, checklist, notes, photos).  Pre-fix the door
    # hanger read from ``job.notes`` / ``job.service_notes`` only.
    from services.service_report_view import (
        resolve_water_test, resolve_chemicals_used_with_cost,
        resolve_checklist_state, resolve_notes, resolve_photo_items,
        _resolve_public_base_url,
    )
    from routers.checklists import DEFAULT_POOL_ITEMS, DEFAULT_LANDSCAPE_ITEMS
    kind = _classify(job)
    jid = job.get("id") or ""
    water_test = await resolve_water_test(db, job, tenant["id"]) if kind == "pool" else []
    chems_used, _chem_total_cents = await resolve_chemicals_used_with_cost(
        db, job, tenant["id"],
    ) if kind == "pool" else ([], 0)
    checklist = await resolve_checklist_state(
        db, job, tenant["id"], kind, DEFAULT_POOL_ITEMS, DEFAULT_LANDSCAPE_ITEMS,
    )
    notes_text = await resolve_notes(db, job, tenant["id"])
    photos = resolve_photo_items(job)
    # Fetch the property doc for the footer service-address line.
    prop = None
    if job.get("property_id"):
        prop = await db.properties.find_one(
            {"id": job["property_id"], "tenant_id": tenant["id"]},
            {"_id": 0, "id": 1, "address": 1, "label": 1},
        )

    company = (tenant or {}).get("name") or "Pool & Landscaping of Vistancia"
    # Feb-2026 · Door hanger copy — first name only in the greeting;
    # never emit the customer's last name anywhere in this email
    # (other templates unchanged).  Cascade: explicit ``first_name``
    # field → first token of ``name`` → ``"Neighbor"`` fallback.
    _first = (cust or {}).get("first_name") or ""
    if not _first:
        _first = ((cust or {}).get("name") or "").split(" ", 1)[0]
    customer_first_name = _first.strip() or "Neighbor"
    completed = job.get("completed_at") or job.get("scheduled_date") or now_iso()
    subject = f"Job Completed - {company}"

    # Feb-2026 · Addition 1 — Service Date line (long-form, tenant TZ).
    service_date_line = _format_service_date(job, tenant)

    # Job title cascade: ``job.title`` → ``job.service_template.title``
    # → ``job.service_type``.
    job_title = (
        job.get("title")
        or (job.get("service_template") or {}).get("title")
        or job.get("service_type")
        or ""
    )
    # Service address — resolved from the enriched ``prop`` doc loaded
    # earlier in the function.  Format: ``street, city, state zip``.
    addr = (prop or {}).get("address") or {}
    address_parts = [
        (addr.get("line1") or "").strip(),
        ", ".join(filter(None, [(addr.get("city") or "").strip(),
                                    " ".join(filter(None, [(addr.get("state") or "").strip(),
                                                            (addr.get("zip") or "").strip()]))])),
    ]
    service_address = " · ".join([p for p in address_parts if p])
    if not service_address:
        # Legacy jobs may denormalise the address onto the job itself.
        service_address = (job.get("service_address") or "").strip()

    # Tenant phone for footer.  Cascade: ``tenant.phone`` →
    # ``tenant.rc_sms_from_number`` → tenant-specific hardcode.
    tenant_phone = (
        (tenant or {}).get("phone")
        or (tenant or {}).get("rc_sms_from_number")
        or "602-887-4400"   # TODO make per-tenant once ``tenant.phone`` is reliably seeded
    )

    logo_url = f"{_resolve_public_base_url()}/logo-full.png"
    brand_color = (tenant or {}).get("brand_color") or "#1f2937"

    # ── Portal auto-login CTA (Feb-2026 Addition 2). ──
    # Skip rules preserved from the pre-redesign builder:
    #   * missing ``customer.id`` → omit CTA block entirely.
    #   * mint helper raises      → catch, log, omit CTA.
    portal_cta_html = ""
    customer_id_for_link = (cust or {}).get("id") or cid
    if customer_id_for_link and jid and (tenant or {}).get("id"):
        try:
            from services.portal_magic_links import build_job_view_url
            portal_url = build_job_view_url(
                _resolve_public_base_url(),
                customer_id_for_link, jid, tenant["id"],
            )
            portal_cta_html = _dh_render_portal_cta(portal_url, brand_color)
        except Exception as exc:  # pragma: no cover — belt-and-braces
            logger.warning(f"[door-hanger] portal CTA mint failed: {exc}")
            portal_cta_html = ""

    # ── Elevated readings CTA (Feb-2026 Slice 5). Only pool jobs
    # with 2+ elevated core readings; suppressed for unsubscribed /
    # do-not-contact customers. Placement: below Water Test, above
    # Chemicals Used (see body assembly below).
    elevated_count = _dh_elevated_core_count(water_test)
    elevated_cta_html = _dh_render_elevated_cta(
        elevated_count=elevated_count, cust=cust, tenant=tenant,
        job_id=jid, brand_color=brand_color,
    )
    # Observability — record one ledger row per job when the CTA
    # actually renders (all suppression rules already applied inside
    # ``_dh_render_elevated_cta``). Idempotent; safe on manual
    # resends of the same job.
    if elevated_cta_html:
        await _record_elevated_followup_shown(
            tenant_id=tenant["id"],
            customer_id=(cust or {}).get("id") or cid,
            job_id=jid,
        )

    # ── Section render order ──
    hero_html      = _dh_render_hero(
        logo_url=logo_url, company=company, first_name=customer_first_name,
        service_date=service_date_line, job_title=job_title,
        service_address=service_address, completed=completed,
    )
    water_html     = _dh_render_water_test(water_test)
    chems_html     = _dh_render_chemicals(chems_used)
    checklist_html = _dh_render_checklist((checklist or {}).get("items") or [])
    notes_html     = _dh_render_notes(notes_text)
    photos_html    = _dh_render_photos(photos)
    footer_html    = _dh_render_footer(company, tenant_phone)

    # Email-safe outer wrapper: table with fixed max-width and neutral
    # background. No ``<style>`` block, no ``class=`` — inline styles
    # only across every child element.
    html = (
        f'<table role="presentation" cellpadding="0" cellspacing="0" '
        f'border="0" width="100%" style="border-collapse:collapse;'
        f'background:#F1F5F9;">'
        f'<tr><td align="center" style="padding:24px 12px;">'
        f'<table role="presentation" cellpadding="0" cellspacing="0" '
        f'border="0" width="640" style="border-collapse:collapse;'
        f'max-width:640px;font-family:Inter,Arial,sans-serif;color:#0F172A;">'
        f'<tr><td>'
        f'{hero_html}'
        f'{water_html}'
        f'{elevated_cta_html}'
        f'{chems_html}'
        f'{checklist_html}'
        f'{notes_html}'
        f'{photos_html}'
        f'{portal_cta_html}'
        f'{footer_html}'
        f'</td></tr></table>'
        f'</td></tr></table>'
    )
    return {"subject": subject, "html": html}


# ─── Opt-out signals ─────────────────────────────────────────────────
# Door-hanger auto-send honours THREE signals (any true → skip):
#   1. ``customer.unsubscribed`` (bool)              — legacy explicit flag
#   2. ``customer.do_not_contact`` (bool)            — CRM DNC flag
#   3. ``subscribers.status == "unsubscribed"``      — Marketing M1 mirror
# The manual endpoint bypasses these checks — an admin clicking the
# manual button is an explicit override.
async def _customer_opt_out_reason(
    tenant_id: str, cust: Optional[Dict[str, Any]], email: str,
) -> Optional[str]:
    c = cust or {}
    if bool(c.get("unsubscribed")) is True:
        return "customer_unsubscribed"
    if bool(c.get("do_not_contact")) is True:
        return "customer_do_not_contact"
    if not email:
        return None
    try:
        sub = await db.subscribers.find_one(
            {"tenant_id": tenant_id, "email": email.strip().lower()},
            {"_id": 0, "status": 1},
        )
        if sub and str(sub.get("status") or "").lower() == "unsubscribed":
            return "subscriber_unsubscribed"
    except Exception as exc:  # pragma: no cover
        logger.warning(f"[door-hanger] subscriber lookup failed: {exc}")
    return None


async def _record_door_hanger_skip(
    *, tenant_id: str, jid: str, cid: Optional[str],
    email: str, reason: str, actor: str,
) -> str:
    """Log a ``skipped`` row to ``marketing_deliveries`` so ops can see
    WHY a door hanger auto-fire didn't send.  Ledger still records
    ``sent`` (see caller) so we don't retry-loop on the same job."""
    did = new_id()
    try:
        await db.marketing_deliveries.insert_one({
            "id": did, "tenant_id": tenant_id, "kind": "transactional",
            "trigger_entity": {"kind": "job_door_hanger", "id": jid},
            "customer_id": cid, "channel": "email",
            "recipient_email": email or None,
            "subject_rendered": None, "body_rendered": None,
            "provider": "skipped",
            "provider_status": "skipped",
            "skip_reason": reason,
            "actor": actor,
            "attempts": 0, "mock": False,
            "sent_at": now_iso(),
        })
    except Exception as exc:  # pragma: no cover
        logger.warning(f"[door-hanger] skip-log insert failed: {exc}")
    return did


async def _compose_and_send_door_hanger(
    *, job: Dict[str, Any], tenant: Dict[str, Any],
    cust: Dict[str, Any], cid: Optional[str], email: str,
    sent_by_user_id: Optional[str], actor: str,
) -> Dict[str, Any]:
    """Shared dispatcher used by BOTH the manual endpoint and the
    auto-send hook.  Builds the body, calls Resend (or the mock),
    and records the ``marketing_deliveries`` row.  Never raises —
    exceptions are logged and surfaced via ``provider_status``."""
    jid = job.get("id") or ""
    composed = await _build_door_hanger_email(
        job=job, tenant=tenant, cust=cust, cid=cid,
    )
    subject = composed["subject"]
    html = composed["html"]

    delivery_id = new_id()
    provider_res: Dict[str, Any] = {"provider": "mock", "provider_status": "queued"}
    try:
        from services.email.resend_adapter import send as _send_email
        provider_res = await _send_email(
            to=email, subject=subject, html=html,
            category="transactional", tenant_id=tenant["id"],
            customer_id=cid,
            idempotency_key=(
                f"door-hanger:{actor}:{jid}:"
                f"{int(datetime.now(timezone.utc).timestamp() // _DOOR_HANGER_COOLDOWN_SECS)}"
            ),
        )
    except Exception as exc:  # pragma: no cover
        logger.warning(f"[door-hanger] email send failed: {exc}")
        provider_res = {"provider": "error", "provider_status": "failed"}

    doc = {
        "id": delivery_id,
        "tenant_id": tenant["id"],
        "kind": "transactional",
        "trigger_entity": {"kind": "job_door_hanger", "id": jid},
        "customer_id": cid,
        "channel": "email",
        "recipient_email": email,
        "subject_rendered": subject,
        "body_rendered": html,
        "provider": provider_res.get("provider"),
        "provider_status": provider_res.get("provider_status"),
        "provider_response_id": provider_res.get("provider_response_id"),
        "attempts": provider_res.get("attempts") or 1,
        "mock": provider_res.get("provider") == "mock",
        "actor": actor,
        "sent_at": now_iso(),
        "sent_by_user_id": sent_by_user_id,
    }
    try:
        await db.marketing_deliveries.insert_one(doc)
    except Exception as exc:  # pragma: no cover
        logger.warning(f"[door-hanger] marketing_deliveries insert failed: {exc}")

    return {
        "ok": True,
        "delivery_id": delivery_id,
        "recipient": email,
        "provider": provider_res.get("provider"),
        "sent_at": doc["sent_at"],
    }


# ─── Auto-send on job-completion transition ──────────────────────────
_AUTO_SEND_LEDGER_INDEX_READY = False


async def _ensure_auto_send_index() -> None:
    """Idempotent bootstrap of the unique index used by the
    ``door_hanger_auto:{job_id}`` ledger row.  Reuses the same
    ``marketing_event_ledger`` collection the drip-events dedupe uses;
    the compound key ``(tenant_id, customer_id, event_key)`` is already
    unique.  This function is a no-op on subsequent calls."""
    global _AUTO_SEND_LEDGER_INDEX_READY
    if _AUTO_SEND_LEDGER_INDEX_READY:
        return
    try:
        # Piggy-back on the drip_events bootstrap so we have exactly
        # one unique index on the collection.  Safe to call multiple
        # times — Mongo dedupes by name.
        from services.marketing.drip_events import _ensure_event_ledger_index
        await _ensure_event_ledger_index()
        _AUTO_SEND_LEDGER_INDEX_READY = True
    except Exception as exc:  # pragma: no cover
        logger.warning(f"[door-hanger] ledger index bootstrap failed: {exc}")


async def maybe_auto_send_door_hanger(jid: str, tenant_id: str) -> Dict[str, Any]:
    """Fire the door-hanger email once when a job transitions to
    ``completed``.  Called fire-and-forget from every completion write
    path via ``asyncio.create_task`` so the API response never blocks
    on Resend or the ledger insert.

    Idempotency contract:
      * A UNIQUE row in ``marketing_event_ledger`` with
        ``event_key = "door_hanger_auto:{job_id}"`` gates the whole
        thing.  The insert is attempted BEFORE dispatch so two
        concurrent completions cannot double-send.
      * Manual ``POST /api/jobs/{jid}/email-door-hanger`` uses a
        60-second cooldown against ``marketing_deliveries`` and is
        intentionally NOT gated by this ledger key.

    Skip contract (all silent — no exceptions):
      * Job or customer missing.
      * ``status != "completed"``.
      * No customer email on file.
      * Customer ``unsubscribed`` / ``do_not_contact`` flag set, or
        the corresponding ``subscribers`` row is ``unsubscribed``.
      * Ledger key already exists.

    Returns a dict for logging + tests: ``{"status": ..., ...}``.
    Never raises."""
    try:
        job = await db.jobs.find_one(
            {"id": jid, "tenant_id": tenant_id}, {"_id": 0},
        )
        if not job:
            return {"status": "skipped", "reason": "job_not_found"}
        if (job.get("status") or "").lower() != "completed":
            return {"status": "skipped", "reason": "status_not_completed"}
        cid = job.get("customer_id")
        if not cid:
            return {"status": "skipped", "reason": "no_customer"}

        # Dedupe barrier — insert-first so two concurrent completions
        # can't race to double-send.  Any FAILURE to insert (dup or
        # crash) bails out.
        await _ensure_auto_send_index()
        event_key = f"door_hanger_auto:{jid}"
        try:
            await db.marketing_event_ledger.insert_one({
                "id": new_id(), "tenant_id": tenant_id,
                "customer_id": cid, "event_key": event_key,
                "trigger_type": "door_hanger_auto",
                "correlation_id": jid,
                "processed_at": now_iso(),
                "meta": {"job_id": jid},
            })
        except Exception as exc:
            if type(exc).__name__ == "DuplicateKeyError":
                return {"status": "skipped", "reason": "already_sent"}
            # Any OTHER exception — log and stop; don't double-send.
            logger.warning(f"[door-hanger] ledger insert crashed: {exc}")
            return {"status": "skipped", "reason": "ledger_error"}

        # Load supporting docs.
        cust = await db.customers.find_one(
            {"id": cid, "tenant_id": tenant_id},
            {"_id": 0, "id": 1, "name": 1, "first_name": 1, "email": 1,
             "unsubscribed": 1, "do_not_contact": 1},
        ) or {}
        tenant = await db.tenants.find_one(
            {"id": tenant_id}, {"_id": 0},
        ) or {"id": tenant_id}
        email = (cust.get("email") or "").strip()

        # Recipient skip checks — ledger already stamped ``sent`` so we
        # do NOT retry on subsequent completions.
        if not email:
            await _record_door_hanger_skip(
                tenant_id=tenant_id, jid=jid, cid=cid, email="",
                reason="no_email", actor="auto",
            )
            return {"status": "skipped", "reason": "no_email"}
        opt_out = await _customer_opt_out_reason(tenant_id, cust, email)
        if opt_out:
            await _record_door_hanger_skip(
                tenant_id=tenant_id, jid=jid, cid=cid, email=email,
                reason=opt_out, actor="auto",
            )
            return {"status": "skipped", "reason": opt_out}

        result = await _compose_and_send_door_hanger(
            job=job, tenant=tenant, cust=cust, cid=cid, email=email,
            sent_by_user_id=None, actor="auto",
        )
        return {"status": "sent", **result}
    except Exception as exc:  # pragma: no cover — belt-and-braces
        logger.warning(f"[door-hanger] auto-send crashed: {exc}")
        return {"status": "error", "error": str(exc)}


def schedule_auto_send_door_hanger(jid: str, tenant_id: str) -> None:
    """Fire-and-forget wrapper — used by write-path callers so the
    HTTP response returns immediately.  Any exception is swallowed
    inside :func:`maybe_auto_send_door_hanger`; this thin wrapper
    only exists so callers don't need to import asyncio."""
    try:
        import asyncio
        asyncio.create_task(maybe_auto_send_door_hanger(jid, tenant_id))
    except Exception as exc:  # pragma: no cover
        logger.warning(f"[door-hanger] auto-send schedule failed: {exc}")


# ─── POST /api/jobs/{jid}/email-door-hanger (manual) ─────────────────
@router.post("/jobs/{jid}/email-door-hanger")
async def email_door_hanger(
    jid: str,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    """Manual admin resend of the door-hanger email.  Kept as an
    explicit override — does NOT consult the
    ``door_hanger_auto:{job_id}`` ledger key so an admin can always
    resend after an auto-fire.  A 60-second cooldown against
    ``marketing_deliveries`` still protects against accidental
    double-clicks on the button."""
    _require_admin_or_403(user)
    job = await db.jobs.find_one(
        {"id": jid, "tenant_id": tenant["id"]}, {"_id": 0},
    )
    if not job:
        raise HTTPException(404, "Job not found")
    cid = job.get("customer_id")
    cust = None
    if cid:
        cust = await db.customers.find_one(
            {"id": cid, "tenant_id": tenant["id"]},
            {"_id": 0, "id": 1, "name": 1, "first_name": 1, "email": 1,
             "unsubscribed": 1, "do_not_contact": 1},
        )
    email = (cust or {}).get("email") or ""
    if not email:
        raise HTTPException(400, "Customer has no email on file")

    # Manual-only 60s cooldown (auto-send is gated by the ledger key
    # in ``maybe_auto_send_door_hanger``; manual bypasses that key on
    # purpose — the admin is an explicit override).
    cutoff_iso = (
        datetime.now(timezone.utc) - timedelta(seconds=_DOOR_HANGER_COOLDOWN_SECS)
    ).isoformat().replace("+00:00", "Z")
    recent = await db.marketing_deliveries.find_one(
        {"tenant_id": tenant["id"],
         "trigger_entity.kind": "job_door_hanger",
         "trigger_entity.id": jid,
         "actor": {"$ne": "auto"},
         "sent_at": {"$gte": cutoff_iso}},
        {"_id": 0, "id": 1, "sent_at": 1},
    )
    if recent:
        return JSONResponse(
            status_code=429,
            content={
                "ok": False,
                "reason": "cooldown",
                "cooldown_seconds": _DOOR_HANGER_COOLDOWN_SECS,
                "last_delivery_id": recent.get("id"),
                "last_sent_at": recent.get("sent_at"),
            },
        )

    return await _compose_and_send_door_hanger(
        job=job, tenant=tenant, cust=cust or {}, cid=cid, email=email,
        sent_by_user_id=user.get("id"), actor="manual",
    )
