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
# Task L+P · Feb-2026 — reuse Commit-1's ``_media_items`` merge for
# the new ``service_report_photos`` slice of the JobDetail response.
from routers.workstream_service_log import _media_items as _wsl_media_items
# Feb-2026 · Phase F1 — crew-aware tech authorization helper. Same
# helper as ``routers/jobs.py`` so this endpoint (which powers the
# JobDetail UI) matches the schedule/list authorization semantics.
from services.authz import is_tech_authorized_on_job

router = APIRouter()

# Media caps mirror the enforcement in media_uploads.py / jobs.py so the
# UI can render a "3/10 photos" style counter without a second call.
PHOTO_LIMIT = 10
VIDEO_LIMIT = 3


# Deep-scrub key set. Any dict encountered under the tech payload has
# these keys popped, no matter how deeply nested. This is the last
# line of defence for the tech-pricing invariant (Slice K2 + M5). Add
# to the tuple below if a new admin-only field is introduced anywhere
# in the aggregator response tree.
_TECH_DEEP_HIDDEN_KEYS = (
    "price", "cost", "total", "subtotal", "tax_rate", "tax_amount",
    "revenue", "invoice_total", "quote_total", "margin", "labor_cost",
    "materials_cost", "gross_margin", "job_totals", "unit_price",
    "internal_notes",
)


def _scrub_tech_deep(node):
    """Recursively strip every admin-only field from ``node``. Mutates
    lists/dicts in place; scalars are returned untouched."""
    if isinstance(node, dict):
        for k in _TECH_DEEP_HIDDEN_KEYS:
            node.pop(k, None)
        for v in node.values():
            _scrub_tech_deep(v)
    elif isinstance(node, list):
        for item in node:
            _scrub_tech_deep(item)


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


async def _build_service_report_photos(
    job: dict, tenant_id: str,
) -> List[Dict[str, Any]]:
    """Task L+P · Feb-2026 — Service Report photos slice for the
    JobDetail aggregator.

    Reuses ``routers/workstream_service_log._media_items`` (the
    Commit-1 merge) and filters the result to entries with
    ``source == "service_report"`` and ``kind == "image"``.  This
    surfaces the SR-side photos as a separate section on the
    JobDetail page (rendered ADJACENT to the existing
    ``media.photos`` grid — NOT merged into it).

    Dedupe policy (inherited from ``_media_items``): a photo id
    present in BOTH ``jobs.photos`` AND ``service_reports.photos``
    ends up in the SR-source slot (SR wins on collision), so the
    same photo never appears in both sections of the response.

    Return shape: ``[{"id", "kind", "url", "label", "created_at",
    "source"}]``.  Empty list when the job has no SR photos.  Never
    ``None``.

    Videos are intentionally excluded — SR videos surface via the
    existing ``media.videos`` grid on the JobDetail response and
    the SR-photos section is photos-only per the Commit-5 spec.
    """
    try:
        merged = await _wsl_media_items(job, tenant_id)
    except Exception as exc:  # pragma: no cover — never break parent
        logger.warning(
            "[task-lp] _build_service_report_photos merge failed "
            "job=%s tenant=%s err=%s",
            job.get("id"), tenant_id, exc,
        )
        return []
    return [
        i for i in merged
        if i.get("source") == "service_report" and i.get("kind") == "image"
    ]



@router.get("/jobs/{jid}/detail")
async def get_job_detail(
    jid: str,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    role = user.get("role") or ""
    if role == "customer":
        raise HTTPException(403, "Job detail is a staff-only surface")

    job = await db.jobs.find_one({"id": jid, "tenant_id": tenant["id"]}, {"_id": 0, "photos.data": 0})
    if not job:
        raise HTTPException(404, "Job not found")

    # Tech isolation — can act on jobs directly assigned OR on
    # jobs bound only to a crew the tech belongs to. F1 · crew-aware
    # gate; see ``services/authz.py``.
    if _is_tech(user):
        if not await is_tech_authorized_on_job(user, job, db, tenant["id"]):
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
    # Task L+P · Feb-2026 — new ``service_report_photos`` slice.
    # Reuses Commit-1's ``_media_items`` merge (both sources,
    # deduped by id with SR winning on collision, timestamp-desc)
    # and filters to ``source == "service_report"`` + ``kind ==
    # "image"``.  Rendered as a new "Service Report Photos" grid
    # section on the JobDetail page — adjacent to the existing
    # ``media.photos`` (``jobs.photos``) grid, NOT merged into it.
    # Empty array when the job has no SR photos.  See
    # ``frontend/src/pages/jobs/JobDetail.jsx`` for the render
    # site.
    service_report_photos = await _build_service_report_photos(
        job, tenant["id"],
    )

    payload: Dict[str, Any] = {
        "header": header,
        "media": media,
        "line_items": line_items,
        "notes": notes,
        "checklist": checklist,
        "forms": forms,
        "timeline": timeline,
        "service_report_photos": service_report_photos,
    }

    # Belt-and-braces: recursively scrub every admin-only field from
    # the ENTIRE payload tree for techs — header, forms, timeline,
    # notes, everything. This is the last line of defence; per-section
    # projection above is the first.
    if _is_tech(user):
        _scrub_tech_deep(payload)

    return payload
