"""Portal media aggregation · Feb-2026.

Read-only endpoints for the customer portal Quick Action tiles:

* ``GET /api/portal/photos``  — every image the current customer has
  visibility on (files linked to their jobs, files linked directly to
  their customer record, plus photos embedded in their service reports).
* ``GET /api/portal/videos``  — every video from the current customer's
  service reports (videos are currently ONLY authored via
  ``service_report_media``).
* ``GET /api/portal/messages/unread-count``  — total unread portal
  chat messages across the customer's chats.

All endpoints are customer-scoped: no cross-customer data leaks, tenant
scoping enforced on every query.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from config import db, logger
from routers.tenants import get_current_tenant
from utils import get_current_user

router = APIRouter()


def _require_customer(user: dict) -> str:
    """Return the customer_id for a portal customer, else 403."""
    if user.get("role") != "customer" or not user.get("customer_id"):
        raise HTTPException(403, "customer_only")
    return user["customer_id"]


async def _customer_job_ids(customer_id: str, tenant_id: str) -> List[str]:
    """Ids of every job the customer owns in this tenant."""
    cur = db.jobs.find(
        {"customer_id": customer_id, "tenant_id": tenant_id},
        {"_id": 0, "id": 1, "title": 1},
    )
    return [j async for j in cur]


def _is_image(mime: Optional[str]) -> bool:
    return bool(mime) and mime.lower().startswith("image/")


def _is_video(mime: Optional[str]) -> bool:
    return bool(mime) and mime.lower().startswith("video/")


# ═════════════════════════════════════════════════════════════════════
# GET /api/portal/photos
# ═════════════════════════════════════════════════════════════════════
@router.get("/portal/photos")
async def portal_photos(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    job_id: Optional[str] = Query(None),
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    """Aggregate all images visible to the current customer."""
    cid = _require_customer(user)
    tenant_id = tenant["id"]

    jobs = await _customer_job_ids(cid, tenant_id)
    job_ids = [j["id"] for j in jobs]
    if job_id:
        # Filter to a single job — but only if the customer owns it.
        if job_id not in job_ids:
            raise HTTPException(404, "job_not_found")
        job_ids = [job_id]
    job_title_by_id = {j["id"]: j.get("title") for j in jobs}

    # 1. Files linked to owned jobs OR directly to the customer.
    file_or_clauses: List[Dict[str, Any]] = []
    if job_ids:
        file_or_clauses.append(
            {"linked_entity_type": "job", "linked_entity_id": {"$in": job_ids}},
        )
    if not job_id:
        # Only include customer-level files when not filtering to a job.
        file_or_clauses.append(
            {"linked_entity_type": "customer", "linked_entity_id": cid},
        )

    file_items: List[Dict[str, Any]] = []
    if file_or_clauses:
        q = {
            "tenant_id": tenant_id,
            "is_deleted": False,
            "$or": file_or_clauses,
        }
        cur = db.files.find(q, {"_id": 0}).sort("created_at", -1)
        async for row in cur:
            mime = row.get("content_type") or ""
            if not _is_image(mime):
                continue
            file_items.append({
                "file_id": row.get("id"),
                "filename": row.get("original_filename"),
                "url": f"/api/files/{row.get('id')}/download",
                "mime": mime,
                "size": row.get("size") or 0,
                "job_id": (row.get("linked_entity_id")
                           if row.get("linked_entity_type") == "job" else None),
                "job_title": (job_title_by_id.get(row.get("linked_entity_id"))
                              if row.get("linked_entity_type") == "job" else None),
                "purpose": row.get("purpose"),
                "uploaded_at": row.get("created_at"),
                "source": "file",
            })

    # 2. Photos embedded in service reports for the customer's jobs.
    sr_items: List[Dict[str, Any]] = []
    if job_ids:
        rq = {
            "tenant_id": tenant_id,
            "job_id": {"$in": job_ids},
            "submitted_at": {"$exists": True},  # only show submitted reports
        }
        cur = db.service_reports.find(rq, {
            "_id": 0, "id": 1, "job_id": 1, "public_uuid": 1,
            "photos": 1, "submitted_at": 1, "updated_at": 1,
        })
        async for rep in cur:
            for p in (rep.get("photos") or []):
                if p.get("is_deleted"):
                    continue
                mime = p.get("mime") or p.get("content_type") or "image/jpeg"
                if not _is_image(mime):
                    continue
                pub = rep.get("public_uuid")
                sr_items.append({
                    "file_id": p.get("id"),
                    "filename": p.get("filename") or f"{p.get('id')}.jpg",
                    "url": (f"/api/public/service/{pub}/photo/{p.get('id')}"
                             if pub else p.get("url") or ""),
                    "mime": mime,
                    "size": p.get("size_bytes") or 0,
                    "job_id": rep.get("job_id"),
                    "job_title": job_title_by_id.get(rep.get("job_id")),
                    "purpose": "service_report_photo",
                    "uploaded_at": p.get("uploaded_at") or rep.get("submitted_at"),
                    "source": "service_report",
                })

    all_items = file_items + sr_items
    # Sort newest first — treat missing dates as oldest.
    all_items.sort(key=lambda r: r.get("uploaded_at") or "", reverse=True)

    total = len(all_items)
    page = all_items[offset:offset + limit]

    return {"items": page, "total": total,
             "limit": limit, "offset": offset}


# ═════════════════════════════════════════════════════════════════════
# GET /api/portal/videos
# ═════════════════════════════════════════════════════════════════════
@router.get("/portal/videos")
async def portal_videos(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    job_id: Optional[str] = Query(None),
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    """Videos from the current customer's submitted service reports.

    Videos are ONLY authored via ``service_report_media`` today — there
    is no other video source in the codebase. The endpoint iterates
    service reports rather than a ``files`` collection filter to reuse
    the existing public streaming URL shape.
    """
    cid = _require_customer(user)
    tenant_id = tenant["id"]

    jobs = await _customer_job_ids(cid, tenant_id)
    job_ids = [j["id"] for j in jobs]
    if job_id:
        if job_id not in job_ids:
            raise HTTPException(404, "job_not_found")
        job_ids = [job_id]
    job_title_by_id = {j["id"]: j.get("title") for j in jobs}

    items: List[Dict[str, Any]] = []
    if job_ids:
        rq = {
            "tenant_id": tenant_id,
            "job_id": {"$in": job_ids},
            "submitted_at": {"$exists": True},
        }
        cur = db.service_reports.find(rq, {
            "_id": 0, "id": 1, "job_id": 1, "public_uuid": 1,
            "videos": 1, "submitted_at": 1, "updated_at": 1,
        })
        async for rep in cur:
            for v in (rep.get("videos") or []):
                if v.get("is_deleted"):
                    continue
                mime = v.get("mime") or v.get("content_type") or "video/mp4"
                if not _is_video(mime):
                    continue
                pub = rep.get("public_uuid")
                items.append({
                    "file_id": v.get("id"),
                    "filename": v.get("filename") or f"{v.get('id')}.mp4",
                    "url": (f"/api/public/service/{pub}/video/{v.get('id')}"
                             if pub else v.get("url") or ""),
                    "poster_url": v.get("poster_url") or v.get("thumbnail_url"),
                    "duration_seconds": v.get("duration_seconds"),
                    "mime": mime,
                    "size": v.get("size_bytes") or 0,
                    "job_id": rep.get("job_id"),
                    "job_title": job_title_by_id.get(rep.get("job_id")),
                    "purpose": "service_report_video",
                    "uploaded_at": v.get("uploaded_at") or rep.get("submitted_at"),
                    "source": "service_report",
                })

    items.sort(key=lambda r: r.get("uploaded_at") or "", reverse=True)
    total = len(items)
    page = items[offset:offset + limit]

    return {"items": page, "total": total,
             "limit": limit, "offset": offset}


# ═════════════════════════════════════════════════════════════════════
# GET /api/portal/messages/unread-count
# ═════════════════════════════════════════════════════════════════════
@router.get("/portal/messages/unread-count")
async def portal_messages_unread_count(
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    """Sum of ``unread_by_customer`` across every chat the customer
    owns. Used for the Messages tile badge on the portal home."""
    cid = _require_customer(user)
    tenant_id = tenant["id"]
    total = 0
    cur = db.portal_chats.find(
        {"customer_id": cid, "tenant_id": tenant_id},
        {"_id": 0, "unread_by_customer": 1},
    )
    async for row in cur:
        try:
            total += int(row.get("unread_by_customer") or 0)
        except (TypeError, ValueError):
            continue
    return {"unread": total}


try:
    # Emitted once at import time so the platform log clearly shows the
    # video source of truth for anyone tracing behaviour later.
    logger.info(
        "[portal_media] video source of truth = db.service_reports[].videos "
        "(authored via /api/service-reports/{id}/media)",
    )
except Exception:  # pragma: no cover
    pass
