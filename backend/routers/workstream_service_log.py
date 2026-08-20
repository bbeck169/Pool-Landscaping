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
    #
    # P0 · Feb 2026 — resolve every service-report chunk via the same
    # helpers the Workstream Service Log page uses (chemistry,
    # chemicals used, checklist, notes, photos).  Pre-fix the door
    # hanger read from ``job.notes`` / ``job.service_notes`` only —
    # which meant every real tech submission produced an empty "Notes:
    # —" email plus no chemistry, no chemicals, no checklist and no
    # images.
    from services.service_report_view import (
        resolve_water_test, resolve_chemicals_used_with_cost,
        resolve_checklist_state, resolve_notes, resolve_photo_items,
    )
    from routers.checklists import DEFAULT_POOL_ITEMS, DEFAULT_LANDSCAPE_ITEMS
    kind = _classify(job)
    water_test = await resolve_water_test(db, job, tenant["id"]) if kind == "pool" else []
    chems_used, chem_total_cents = await resolve_chemicals_used_with_cost(
        db, job, tenant["id"],
    ) if kind == "pool" else ([], 0)
    checklist = await resolve_checklist_state(
        db, job, tenant["id"], kind, DEFAULT_POOL_ITEMS, DEFAULT_LANDSCAPE_ITEMS,
    )
    notes_text = await resolve_notes(db, job, tenant["id"])
    photos = resolve_photo_items(job)

    company = "Pool & Landscaping of Vistancia"
    customer_name = (cust or {}).get("name") or "Neighbor"
    completed = job.get("completed_at") or job.get("scheduled_date") or now_iso()
    subject = f"Service door hanger — {company}"

    # ── Compose HTML fragments per section, hiding empty ones. ──
    def _row(label: str, value: str) -> str:
        return (
            f"<tr><td style=\"padding:4px 12px 4px 0;color:#64748B;white-space:nowrap\">{label}</td>"
            f"<td style=\"padding:4px 0;color:#0F172A\"><b>{value}</b></td></tr>"
        )

    water_html = ""
    if water_test:
        rows = "".join(
            _row(r["label"], f"{r['value']} {r.get('unit') or ''}".strip())
            for r in water_test
        )
        water_html = (
            f"<h3 style=\"color:#0F172A;margin:16px 0 4px;font-size:15px\">Water Test</h3>"
            f"<table cellpadding=0 cellspacing=0 style=\"font-size:14px;border-collapse:collapse\">"
            f"{rows}</table>"
        )

    chems_html = ""
    if chems_used:
        rows = "".join(
            f"<li>{c['name']} — {c.get('display') or c['quantity']}</li>"
            for c in chems_used
        )
        cost_line = (
            f"<div style=\"font-size:12px;color:#64748B;margin-top:4px\">"
            f"Chemical cost: <b style=\"color:#0F172A\">${chem_total_cents/100:.2f}</b></div>"
            if chem_total_cents else ""
        )
        chems_html = (
            f"<h3 style=\"color:#0F172A;margin:16px 0 4px;font-size:15px\">Chemicals Used</h3>"
            f"<ul style=\"font-size:14px;color:#0F172A;padding-left:20px;margin:4px 0\">{rows}</ul>"
            f"{cost_line}"
        )

    checklist_html = ""
    checklist_items = (checklist or {}).get("items") or []
    if checklist_items:
        # Split completed vs skipped so the customer sees BOTH — the
        # door hanger's job is transparency, not marketing.
        def _tick(done: bool) -> str:
            return "&#10003;" if done else "&#9633;"
        rows = "".join(
            f"<li style=\"color:{'#0F172A' if it['completed'] else '#94A3B8'}\">"
            f"{_tick(bool(it['completed']))} {it['label']}</li>"
            for it in checklist_items
        )
        checklist_html = (
            f"<h3 style=\"color:#0F172A;margin:16px 0 4px;font-size:15px\">Service Checklist</h3>"
            f"<ul style=\"font-size:14px;list-style:none;padding-left:0;margin:4px 0\">"
            f"{rows}</ul>"
        )

    notes_html = ""
    if notes_text:
        # Escape newlines to <br/> so the customer sees the tech's
        # freeform notes formatted the way they were typed.
        notes_safe = notes_text.replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br/>")
        notes_html = (
            f"<h3 style=\"color:#0F172A;margin:16px 0 4px;font-size:15px\">Notes from your technician</h3>"
            f"<div style=\"font-size:14px;color:#0F172A;white-space:pre-wrap\">{notes_safe}</div>"
        )
    else:
        notes_html = (
            f"<p style=\"color:#94A3B8;font-size:13px;margin-top:16px\">"
            f"Notes: —</p>"
        )

    photos_html = ""
    if photos:
        thumbs = "".join(
            f"<a href=\"{p['url_absolute']}\" style=\"display:inline-block;margin:4px\">"
            f"<img src=\"{p['url_absolute']}\" alt=\"{(p.get('label') or 'service photo')}\" "
            f"width=\"140\" style=\"display:block;border-radius:8px;border:1px solid #E2E8F0\"/></a>"
            for p in photos
        )
        photos_html = (
            f"<h3 style=\"color:#0F172A;margin:16px 0 4px;font-size:15px\">Service Photos</h3>"
            f"<div style=\"margin:4px 0\">{thumbs}</div>"
        )

    html = (
        f"<div style=\"font-family:Inter,Arial,sans-serif;max-width:640px;color:#0F172A\">"
        f"<h2 style=\"color:#0F172A;margin:0 0 8px;\">We stopped by, {customer_name}.</h2>"
        f"<p>Your service was completed on <b>{str(completed)[:10]}</b>.</p>"
        f"{water_html}"
        f"{chems_html}"
        f"{checklist_html}"
        f"{notes_html}"
        f"{photos_html}"
        f"<p style=\"font-size:12px;color:#64748B;margin-top:16px\">If anything looks off, "
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
