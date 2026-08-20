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
from utils import get_current_user, new_id, now_iso

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
    """Emit the ORDERED checklist for this job's service line, marking
    each item completed based on the per-job ``checklist`` array. When a
    job's per-item ``done`` flag is missing, fall back to service_reports
    checklist_items so both storage lanes render consistently.

    P0 · Feb 2026 (Fix C) — match on ``key`` first, then on
    ``_norm(label)`` only when both write and canonical entries lack a
    ``key``.  The pre-fix code matched on normalised label alone, so a
    tech payload of ``"Brushed Pool"`` never matched the canonical
    ``"Brush Pool"`` and the item silently rendered unchecked.
    """
    from routers.checklists import DEFAULT_POOL_ITEMS, DEFAULT_LANDSCAPE_ITEMS
    kind = _classify(job)
    tenant_doc = await db.service_checklists.find_one(
        {"tenant_id": tenant_id, "service_line": kind},
        {"_id": 0, "items": 1},
    )
    canon = (tenant_doc or {}).get("items") or (
        DEFAULT_POOL_ITEMS if kind == "pool" else DEFAULT_LANDSCAPE_ITEMS
    )

    # Build TWO lookups from the write side — one by ``key``
    # (preferred, exact-match) and one by ``_norm(label)`` (fuzzy
    # fallback for legacy entries that lack a key).
    key_map: Dict[str, bool] = {}
    label_map: Dict[str, bool] = {}

    def _record(it: dict) -> None:
        if not (it.get("done") or it.get("checked")):
            return
        k = (it.get("key") or "").strip()
        if k:
            key_map[k] = True
            return
        lbl = _norm(it.get("label"))
        if lbl:
            label_map[lbl] = True

    for it in (job.get("checklist") or []):
        _record(it)
    rep = await db.service_reports.find_one(
        {"tenant_id": tenant_id, "job_id": job.get("id"),
         "checklist_items": {"$exists": True}},
        {"_id": 0, "checklist_items": 1},
    )
    for it in ((rep or {}).get("checklist_items") or []):
        _record(it)

    items_out: List[Dict[str, Any]] = []
    for it in canon:
        ck = (it.get("key") or "").strip()
        completed = False
        if ck and ck in key_map:
            completed = True
        else:
            # Canonical entry has no key OR the write side never
            # supplied one → fall back to label match.
            completed = bool(label_map.get(_norm(it.get("label"))))
        items_out.append({
            "key": it.get("key"),
            "label": it.get("label"),
            "completed": completed,
        })
    return {"service_line": kind, "items": items_out, "count": len(items_out)}


# Canonical water-test key list — ordered for the Workstream panel.
# Free Chlorine → Total Chlorine → pH → Alkalinity → CYA → Conditioner
# → anything else the tech submitted (rendered in submission order).
# Note: ``cyanuric_acid`` was added Feb 2026 (P0 Workstream read/write
# reconciliation).  ``conditioner`` is the legacy synonym kept for
# backward compatibility with older service reports.
_WATER_TEST_CANONICAL: List[tuple] = [
    ("free_chlorine",   "Free Chlorine",  "ppm"),
    ("total_chlorine",  "Total Chlorine", "ppm"),
    ("ph",              "Ph Balance",     ""),
    ("alkalinity",      "Alkalinity",     "ppm"),
    ("cyanuric_acid",   "CYA",            "ppm"),
    ("conditioner",     "Conditioner",    "ppm"),
]


def _coerce_readings(raw: Any) -> Dict[str, Any]:
    """Normalise both storage shapes into a single ``{key: value}`` dict.

    Accepts:
      * ``dict`` — ``{"free_chlorine": 2.5, ...}`` (legacy job doc).
      * ``list`` of ``{"key": ..., "value": ...}`` (tech write path via
        ``PATCH /jobs/{jid}/service-report`` — the canonical shape).
      * ``None`` — returns ``{}``.
    """
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, list):
        out: Dict[str, Any] = {}
        for row in raw:
            if not isinstance(row, dict):
                continue
            k = (row.get("key") or "").strip()
            if not k:
                continue
            out[k] = row.get("value")
        return out
    return {}


async def _water_test(job: dict, tenant_id: str) -> List[Dict[str, Any]]:
    """Emit the water-test rows.

    P0 · Feb 2026 (Fix A) — reads the service_reports collection FIRST
    (where the tech's ``PATCH /jobs/{jid}/service-report`` actually
    lands), falls back to ``job.chemical_readings`` for backward
    compat with legacy jobs that stored inline.  Accepts BOTH the
    list-of-``{key, label, value, unit}`` shape (canonical) and the
    dict shape (legacy).
    """
    rep = await db.service_reports.find_one(
        {"tenant_id": tenant_id, "job_id": job.get("id"),
         "chemical_readings": {"$exists": True}},
        {"_id": 0, "chemical_readings": 1},
    )
    readings = _coerce_readings((rep or {}).get("chemical_readings"))
    if not readings:
        readings = _coerce_readings(job.get("chemical_readings"))

    out: List[Dict[str, Any]] = []
    emitted: set = set()
    # 1. Canonical order first.
    for key, label, unit in _WATER_TEST_CANONICAL:
        if key not in readings:
            continue
        v = readings[key]
        if v in (None, ""):
            continue
        try:
            fv = float(v)
        except (TypeError, ValueError):
            continue
        out.append({"key": key, "label": label, "value": fv, "unit": unit})
        emitted.add(key)
    # 2. Any other keys the tech typed — rendered after the canonical
    #    block in insertion order so we don't drop custom readings.
    for key, v in readings.items():
        if key in emitted or v in (None, ""):
            continue
        try:
            fv = float(v)
        except (TypeError, ValueError):
            continue
        out.append({
            "key": key,
            "label": key.replace("_", " ").title(),
            "value": fv,
            "unit": "",
        })
    return out


async def _chemicals_used_source(job: dict, tenant_id: str) -> List[Dict[str, Any]]:
    """Return the raw ``chemicals_added`` list for a job.

    P0 · Feb 2026 (Fix B) — pulls from ``service_reports.chemicals_added``
    first (canonical write target), falls back to
    ``job.chemicals_added`` for backward compat.
    """
    rep = await db.service_reports.find_one(
        {"tenant_id": tenant_id, "job_id": job.get("id"),
         "chemicals_added": {"$exists": True}},
        {"_id": 0, "chemicals_added": 1},
    )
    src = (rep or {}).get("chemicals_added")
    if not src:
        src = job.get("chemicals_added") or []
    return src or []


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
    tid = job.get("technician_id")
    if tid:
        tech = await db.technicians.find_one(
            {"id": tid, "tenant_id": tenant["id"]},
            {"_id": 0, "id": 1, "name": 1, "phone": 1, "department": 1},
        ) or {}
        job["_technician_department"] = tech.get("department")
        employee = {
            "id": tech.get("id"),
            "name": tech.get("name") or "Unassigned",
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
            "property_address": prop_addr,
            "property_id": (prop or {}).get("id"),
            "service_at": completed or job.get("scheduled_date"),
            "time_spent_minutes": time_spent_min,
            "employee_name": employee["name"],
            "employee_id": employee["id"],
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


# ─── POST /api/jobs/{jid}/email-door-hanger ──────────────────────────
@router.post("/jobs/{jid}/email-door-hanger")
async def email_door_hanger(
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
    cid = job.get("customer_id")
    cust = None
    if cid:
        cust = await db.customers.find_one(
            {"id": cid, "tenant_id": tenant["id"]},
            {"_id": 0, "id": 1, "name": 1, "email": 1},
        )
    email = (cust or {}).get("email") or ""
    if not email:
        raise HTTPException(400, "Customer has no email on file")

    # Idempotency: reject a second send within the cooldown window.
    cutoff_iso = (
        datetime.now(timezone.utc) - timedelta(seconds=_DOOR_HANGER_COOLDOWN_SECS)
    ).isoformat().replace("+00:00", "Z")
    recent = await db.marketing_deliveries.find_one(
        {"tenant_id": tenant["id"],
         "trigger_entity.kind": "job_door_hanger",
         "trigger_entity.id": jid,
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

    # Compose. Keep the body simple + branded; techs never call this
    # endpoint so no tech-projection needed.
    company = "Pool & Landscaping of Vistancia"
    customer_name = (cust or {}).get("name") or "Neighbor"
    completed = job.get("completed_at") or job.get("scheduled_date") or now_iso()
    subject = f"Service door hanger — {company}"
    html = (
        f"<div style=\"font-family:Inter,Arial,sans-serif;max-width:600px;\">"
        f"<h2 style=\"color:#0F172A;margin:0 0 8px;\">We stopped by, {customer_name}.</h2>"
        f"<p>Your service was completed on <b>{str(completed)[:10]}</b>.</p>"
        f"<p>Notes: {job.get('service_notes') or job.get('notes') or '—'}</p>"
        f"<p style=\"font-size:12px;color:#64748B\">If anything looks off, "
        f"reply to this email or call us — we'll make it right.</p>"
        f"<p style=\"margin-top:16px;font-weight:600;\">— {company}</p>"
        f"</div>"
    )

    delivery_id = new_id()
    provider_res: Dict[str, Any] = {"provider": "mock", "provider_status": "queued"}
    try:
        from services.email.resend_adapter import send as _send_email
        provider_res = await _send_email(
            to=email, subject=subject, html=html,
            category="transactional", tenant_id=tenant["id"],
            customer_id=cid,
            idempotency_key=f"door-hanger:{jid}:{int(datetime.now(timezone.utc).timestamp() // _DOOR_HANGER_COOLDOWN_SECS)}",
        )
    except Exception as exc:  # pragma: no cover
        logger.warning(f"[phase5a2] door-hanger email send failed: {exc}")
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
        "sent_at": now_iso(),
        "sent_by_user_id": user.get("id"),
    }
    try:
        await db.marketing_deliveries.insert_one(doc)
    except Exception as exc:  # pragma: no cover
        logger.warning(f"[phase5a2] marketing_deliveries insert failed: {exc}")

    return {
        "ok": True,
        "delivery_id": delivery_id,
        "recipient": email,
        "provider": provider_res.get("provider"),
        "sent_at": doc["sent_at"],
    }
