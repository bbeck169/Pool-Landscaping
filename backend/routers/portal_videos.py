"""Phase 5A · Customer portal — shareable video feed (Feb 2026).

Parallel to ``portal_photos.py``. Returns the videos across the calling
customer's jobs + estimates in the current tenant whose
``visibility == "customer"`` and ``is_deleted == false``. The actual
streaming happens through ``/api/media/videos/{path}`` — this endpoint
just enumerates what's playable.
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from config import db
from routers.tenants import get_current_tenant
from utils import get_current_user
from utils import not_deleted_filter as _nd

router = APIRouter()


def _project_video(v: dict, entity_kind: str, entity: dict) -> dict:
    return {
        "kind": entity_kind,                       # "job" or "estimate"
        "entity_id": entity.get("id"),
        "entity_title": entity.get("title") or entity.get("service_type") or "Service",
        "job_scheduled_date": entity.get("scheduled_date") if entity_kind == "job" else None,
        "video_id": v.get("id"),
        "storage_path": v.get("storage_path"),
        "mime": v.get("mime"),
        "size_bytes": v.get("size_bytes"),
        "duration_seconds": v.get("duration_seconds"),
        "caption": v.get("caption"),
        "uploaded_at": v.get("uploaded_at"),
        "uploaded_by_name": v.get("uploaded_by_name"),
    }


@router.get("/portal/videos")
async def portal_videos(
    limit: int = Query(200, ge=1, le=500),
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    """Return every shareable video the calling customer can play,
    newest-first."""
    if user.get("role") != "customer" or not user.get("customer_id"):
        raise HTTPException(403, "Customers only")
    cid = user["customer_id"]
    tid = tenant["id"]

    projection = {"_id": 0, "id": 1, "title": 1, "service_type": 1,
                  "scheduled_date": 1, "videos": 1}

    jobs = await db.jobs.find(
        {"tenant_id": tid, "customer_id": cid, "videos": {"$exists": True, "$ne": []}},
        projection,
    ).to_list(2000)

    estimates = await db.estimates.find(
        {"tenant_id": tid, "customer_id": cid, "videos": {"$exists": True, "$ne": []}},
        projection,
    ).to_list(2000)

    out: List[dict] = []
    for j in jobs:
        for v in (j.get("videos") or []):
            if v.get("visibility") == "customer" and not v.get("is_deleted"):
                out.append(_project_video(v, "job", j))
    for e in estimates:
        for v in (e.get("videos") or []):
            if v.get("visibility") == "customer" and not v.get("is_deleted"):
                out.append(_project_video(v, "estimate", e))

    out.sort(key=lambda r: r.get("uploaded_at") or "", reverse=True)
    return {"videos": out[:limit], "total": len(out)}
