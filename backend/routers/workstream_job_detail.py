"""Feb 2026 · Slice M5 — Job Detail aggregator.

``GET /api/jobs/{jid}/detail`` returns the refreshed 7-section job
detail payload used by the new Job Detail page (Slice M5) and the
inline drill-in from the Workstream feed (Slice M4). Bundled here
so the existing ``jobs.py`` router (already ~1600 lines) stays
focused on CRUD and legacy surfaces.

Sections emitted in a stable order:

1. ``header``     — job basics + customer/property/technician summary
2. ``media``      — photos, videos, counts, K1 remaining-slot counters
3. ``line_items`` — K2 role-projected (tech NEVER sees pricing)
4. ``notes``      — customer + service + internal notes (RBAC-gated)
5. ``checklist``  — derived template + items + reading report (pool)
6. ``forms``      — linked service_reports
7. ``timeline``   — workstream_events for this job.id, newest first

RBAC:
    • customer   → 403 (job detail is staff surface)
    • technician → only jobs assigned to them; pricing stripped
    • admin      → tenant-scoped full payload
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException

from config import db, logger
from utils import get_current_user
from routers.tenants import get_current_tenant
from routers.jobs import (
    with_field_report,
    _enrich_job_dept_and_kind,
)
from routers.workstream import (
    _TECH_HIDDEN_JOB_FIELDS,
    _TECH_HIDDEN_LINE_FIELDS,
    _photo_thumb,
    _video_url,
)

router = APIRouter()

# Media caps mirror the enforcement in media_uploads.py / jobs.py so the
# UI can render a "3/10 photos" style counter without a second call.
PHOTO_LIMIT = 10
VIDEO_LIMIT = 3


def _is_admin(user: dict) -> bool:
    return user.get("role") in ("admin", "super_admin")


def _is_tech(user: dict) -> bool:
    return user.get("role") in ("technician", "tech")


def _addr_str(address: Any) -> Optional[str]:
    """Address may be a dict (structured) or a plain string (legacy)."""
    if not address:
        return None
    if isinstance(address, str):
        return address.strip() or None
    if not isinstance(address, dict):
        return None
    parts = [address.get("line1"), address.get("city"),
             address.get("state"), address.get("postal_code")]
    return ", ".join([p for p in parts if p]) or None


async def _build_header(job: dict, tenant_id: str) -> Dict[str, Any]:
    cid = job.get("customer_id")
    tid = job.get("technician_id")
    pid = job.get("property_id")

    customer = None
    if cid:
        cust = await db.customers.find_one(
            {"id": cid, "tenant_id": tenant_id},
            {"_id": 0, "id": 1, "name": 1, "phone": 1, "email": 1,
             "is_vip": 1, "gate_code": 1, "address": 1},
        )
        if cust:
            customer = {
                "id": cust.get("id"),
                "name": cust.get("name") or "",
                "phone": cust.get("phone"),
                "email": cust.get("email"),
                "is_vip": bool(cust.get("is_vip")),
                "gate_code": cust.get("gate_code"),
                "address": _addr_str(cust.get("address")),
            }

    technician = None
    if tid:
        tech = await db.technicians.find_one(
            {"id": tid, "tenant_id": tenant_id},
            {"_id": 0, "id": 1, "name": 1, "phone": 1, "department": 1},
        )
        if tech:
            technician = {
                "id": tech.get("id"),
                "name": tech.get("name") or "",
                "phone": tech.get("phone"),
                "department": tech.get("department"),
            }

    prop = None
    if pid:
        p = await db.properties.find_one(
            {"id": pid, "tenant_id": tenant_id},
            {"_id": 0, "id": 1, "label": 1, "address": 1},
        )
        if p:
            prop = {
                "id": p.get("id"),
                "label": p.get("label"),
                "address": _addr_str(p.get("address")),
            }

    return {
        "id": job.get("id"),
        "title": job.get("title") or "",
        "status": job.get("status") or "",
        "service_type": job.get("service_type") or job.get("job_type") or "",
        "scheduled_date": job.get("scheduled_date"),
        "on_my_way_at": job.get("on_my_way_at"),
        "arrived_at": job.get("arrived_at"),
        "started_at": job.get("started_at"),
        "completed_at": job.get("completed_at"),
        "created_at": job.get("created_at"),
        "updated_at": job.get("updated_at"),
        "customer": customer,
        "technician": technician,
        "property": prop,
    }


def _build_media(job: dict) -> Dict[str, Any]:
    """Section 2 — media grid. Emits full lists (no truncation) so the
    detail page can render the whole gallery, plus K1 remaining-slot
    counters for the upload UI."""
    photos = job.get("photos") or []
    videos = [v for v in (job.get("videos") or []) if not v.get("is_deleted")]
    jid = job.get("id") or ""
    p_out = [{
        "id": p.get("id"),
        "url": _photo_thumb(jid, p.get("id")),
        "label": p.get("label"),
        "created_at": p.get("created_at"),
    } for p in photos if p.get("id")]
    v_out = [{
        "id": v.get("id"),
        "url": _video_url(v.get("storage_path")) if v.get("storage_path") else None,
        "mime": v.get("mime"),
        "size_bytes": v.get("size_bytes"),
        "duration_seconds": v.get("duration_seconds"),
        "caption": v.get("caption"),
        "uploaded_at": v.get("uploaded_at"),
        "uploaded_by_user_id": v.get("uploaded_by_user_id"),
        "uploaded_by_name": v.get("uploaded_by_name"),
        "visibility": v.get("visibility") or "internal",
    } for v in videos if v.get("storage_path")]
    return {
        "photos": p_out,
        "videos": v_out,
        "photos_count": len(p_out),
        "videos_count": len(v_out),
        "photos_remaining": max(0, PHOTO_LIMIT - len(p_out)),
        "videos_remaining": max(0, VIDEO_LIMIT - len(v_out)),
        "photo_limit": PHOTO_LIMIT,
        "video_limit": VIDEO_LIMIT,
    }


def _build_line_items(job: dict, is_tech: bool) -> Dict[str, Any]:
    """Section 3 — K2 role-projected. Tech never sees pricing at all."""
    raw = job.get("line_items") or []
    if is_tech:
        items = [{k: v for k, v in li.items()
                    if k not in _TECH_HIDDEN_LINE_FIELDS} for li in raw]
        return {"items": items, "count": len(items)}
    return {
        "items": raw,
        "count": len(raw),
        "job_totals": job.get("job_totals") or None,
    }


async def _build_notes(job: dict, tenant_id: str, user: dict) -> Dict[str, Any]:
    """Section 4 — public + internal notes. Techs get all operational
    notes (customer_note, account_notes, service_note); ``internal_notes``
    remains admin-only. Customers can never reach this endpoint (403)."""
    admin = _is_admin(user)
    cid = job.get("customer_id")
    account_notes = None
    service_note = None
    if cid:
        cust = await db.customers.find_one(
            {"id": cid, "tenant_id": tenant_id},
            {"_id": 0, "notes": 1, "service_notes": 1},
        )
        if cust:
            account_notes = cust.get("notes") or None
            try:
                from routers.customers import _resolve_service_note
                service_note = _resolve_service_note(
                    cust, job.get("service_type") or job.get("job_type"), user,
                )
            except Exception:
                service_note = None
    out: Dict[str, Any] = {
        "customer_note": job.get("customer_note") or None,
        "account_notes": account_notes,
        "service_note": service_note,
    }
    if admin:
        out["internal_notes"] = job.get("internal_notes") or None
    return out


def _build_checklist(job: dict) -> Dict[str, Any]:
    """Section 5 — reuses with_field_report so the derived template and
    reading report are identical to what /api/jobs/{jid} emits today."""
    enriched = with_field_report(dict(job))
    return {
        "kind": enriched.get("checklist_kind") or enriched.get("job_type"),
        "items": enriched.get("checklist") or [],
        "reading_fields": enriched.get("reading_fields") or [],
        "reading_report": enriched.get("reading_report") or [],
        "chemicals_added": enriched.get("chemicals_added") or [],
    }


async def _build_forms(job: dict, tenant_id: str) -> Dict[str, Any]:
    """Section 6 — service_reports linked to this job."""
    jid = job.get("id")
    reports = await db.service_reports.find(
        {"tenant_id": tenant_id, "job_id": jid},
        {"_id": 0},
    ).sort("updated_at", -1).to_list(50)
    return {
        "service_reports": reports,
        "count": len(reports),
    }


async def _build_timeline(job: dict, tenant_id: str) -> Dict[str, Any]:
    """Section 7 — workstream_events for this job.id, newest first."""
    jid = job.get("id")
    # Match either related_ref.id == jid (structured link) or a
    # payload.job_id echo (legacy events). Non-fatal on failure.
    q = {
        "tenant_id": tenant_id,
        "$or": [
            {"related_ref.id": jid, "related_ref.type": "job"},
            {"payload.job_id": jid},
        ],
    }
    try:
        events = await db.workstream_events.find(
            q, {"_id": 0}
        ).sort("created_at", -1).to_list(200)
    except Exception:
        events = []
    return {"events": events, "count": len(events)}


@router.get("/jobs/{jid}/detail")
async def get_job_detail(
    jid: str,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    role = user.get("role") or ""
    if role == "customer":
        raise HTTPException(403, "Job detail is a staff-only surface")

    job = await db.jobs.find_one({"id": jid, "tenant_id": tenant["id"]}, {"_id": 0})
    if not job:
        raise HTTPException(404, "Job not found")

    # Tech isolation — can only view jobs assigned to them.
    if _is_tech(user):
        assigned = job.get("technician_id")
        if assigned not in (user.get("id"), user.get("technician_id")):
            raise HTTPException(403, "Not your job")

    # Read-time enrichment (dept + checklist_kind).
    try:
        await _enrich_job_dept_and_kind(job, tenant["id"])
    except Exception:
        pass

    header = await _build_header(job, tenant["id"])
    media = _build_media(job)
    line_items = _build_line_items(job, is_tech=_is_tech(user))
    notes = await _build_notes(job, tenant["id"], user)
    checklist = _build_checklist(job)
    forms = await _build_forms(job, tenant["id"])
    timeline = await _build_timeline(job, tenant["id"])

    payload: Dict[str, Any] = {
        "header": header,
        "media": media,
        "line_items": line_items,
        "notes": notes,
        "checklist": checklist,
        "forms": forms,
        "timeline": timeline,
    }

    # Belt-and-braces: strip any pricing that leaked into the header
    # from legacy job fields. The header builder above already doesn't
    # copy them, but this makes tampering with the spec cost-free.
    if _is_tech(user):
        for k in _TECH_HIDDEN_JOB_FIELDS:
            payload["header"].pop(k, None)

    return payload
