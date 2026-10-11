"""Phase 5A / DATA-PARITY-C3 · Feb-2026 — Portal video feed.

Thin wrapper over ``services.customer_media.get_customer_media``.
Pre-fix state (Feb-2026): this file was the sole live
``/api/portal/videos`` handler and walked ONLY ``jobs.videos[]`` +
``estimates.videos[]`` with a ``visibility=="customer"`` filter —
missing service-report videos and admin-uploaded files.  Post-fix:
the shared reader merges all four sources.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from config import db
from utils import get_current_user
from routers.tenants import get_current_tenant
from services.customer_media import get_customer_media

router = APIRouter()


@router.get("/portal/videos")
async def portal_videos(
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
    job_id: Optional[str] = Query(None),
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    """Flat, newest-first list of videos the calling customer can
    play.  The actual streaming happens through
    ``/api/media/videos/{path}`` or ``/api/public/service/<uuid>/
    video/<id>`` — this endpoint just enumerates what's playable."""
    if user.get("role") != "customer" or not user.get("customer_id"):
        raise HTTPException(403, "Customers only")
    cid = user["customer_id"]
    tid = tenant["id"]

    bag = await get_customer_media(
        db, tid, cid, kind="video",
        for_portal=True, limit=limit, offset=offset,
    )
    items = bag["items"]
    if job_id:
        items = [i for i in items if i.get("job_id") == job_id]
    # Backwards-compat shape — the previous handler returned
    # ``{videos: [...], total: N}`` keyed by ``video_id`` +
    # ``storage_path`` etc.  Mirror the superset of fields.
    videos_shape = [
        {
            "kind":             "job"
                                 if i.get("source") == "job"
                                 else ("estimate"
                                       if i.get("source") == "estimate"
                                       else "service_report"),
            "entity_id":        i.get("job_id") or i.get("estimate_id"),
            "entity_title":     i.get("job_title")
                                 or i.get("estimate_title"),
            "video_id":         i.get("media_id"),
            "storage_path":     i.get("url"),
            "url":              i.get("url"),
            "mime":             i.get("mime"),
            "size_bytes":       i.get("size_bytes"),
            "duration_seconds": i.get("duration_seconds"),
            "caption":          i.get("caption") or "",
            "uploaded_at":      i.get("uploaded_at"),
            "source":           i.get("source"),
        }
        for i in items
    ]
    return {
        "videos": videos_shape,
        "total":  bag["total"] if not job_id else len(videos_shape),
    }
