"""Phase 20B.1c · Customer photo history.

Returns all photos across the calling customer's completed service reports.
"""
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query

from config import db
from utils import get_current_user
from utils import not_deleted_filter as _nd
from routers.tenants import get_current_tenant

router = APIRouter()


@router.get("/portal/photos")
async def portal_photos(
    since: Optional[str] = Query(None, description="ISO date lower bound"),
    until: Optional[str] = Query(None, description="ISO date upper bound"),
    service_type: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    """Flat, newest-first list of photo entries the calling customer can view."""
    if user.get("role") != "customer" or not user.get("customer_id"):
        raise HTTPException(403, "Customers only")
    cid = user["customer_id"]
    tid = tenant["id"]

    # First, find the customer's job ids in this tenant.
    job_query: dict = {"tenant_id": tid, "customer_id": cid}
    if service_type:
        job_query["service_type"] = service_type
    job_query = {**job_query, **_nd()}
    jobs = await db.jobs.find(job_query, {"_id": 0, "id": 1, "title": 1,
                                          "service_type": 1, "scheduled_start": 1,
                                          "scheduled_date": 1}).to_list(2000)
    job_by_id = {j["id"]: j for j in jobs}
    if not job_by_id:
        return {"photos": [], "total": 0}

    q_report: dict = {"tenant_id": tid, "job_id": {"$in": list(job_by_id.keys())}}
    if since:
        q_report.setdefault("submitted_at", {})["$gte"] = since
    if until:
        q_report.setdefault("submitted_at", {})["$lte"] = until

    reports = await db.service_reports.find(q_report, {"_id": 0}).sort(
        "submitted_at", -1
    ).to_list(500)

    out: List[dict] = []
    for r in reports:
        j = job_by_id.get(r.get("job_id")) or {}
        for p in (r.get("photos") or []):
            if isinstance(p, dict):
                url = p.get("url") or p.get("path") or p.get("data")
                thumb = p.get("thumb") or url
                caption = p.get("caption") or ""
            else:
                url = p
                thumb = p
                caption = ""
            if not url:
                continue
            out.append({
                "url": url,
                "thumb": thumb,
                "caption": caption,
                "job_id": r.get("job_id"),
                "job_title": j.get("title") or j.get("service_type") or "Service Visit",
                "service_type": j.get("service_type"),
                "submitted_at": r.get("submitted_at"),
                "report_id": r.get("id"),
            })
    return {"photos": out[:limit], "total": len(out)}
