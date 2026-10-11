"""Phase 20B.1c / DATA-PARITY-C3 · Feb-2026 — Portal photo history.

Thin wrapper over ``services.customer_media.get_customer_media``.
Pre-fix state (Feb-2026): this file was the sole live
``/api/portal/photos`` handler and walked ONLY
``service_reports.photos[]`` — missing tech uploads on
``jobs.photos[]``, estimate attachments, and admin-uploaded images
on the ``files`` collection.  Post-fix: the shared reader merges
all four sources and ``portal_media.py`` no longer registers a
competing route.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from config import db
from utils import get_current_user
from routers.tenants import get_current_tenant
from services.customer_media import get_customer_media

router = APIRouter()


@router.get("/portal/photos")
async def portal_photos(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    job_id: Optional[str] = Query(None),
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    """Flat, newest-first list of photo entries the calling customer
    can view."""
    if user.get("role") != "customer" or not user.get("customer_id"):
        raise HTTPException(403, "Customers only")
    cid = user["customer_id"]
    tid = tenant["id"]

    bag = await get_customer_media(
        db, tid, cid, kind="photo",
        for_portal=True, limit=limit, offset=offset,
    )
    items = bag["items"]
    # Backwards-compat shape — the previous handler returned
    # ``{photos, total}`` keyed by ``url``/``thumb``/``caption``.
    # Preserve the top-level ``photos`` key for the frontend.
    if job_id:
        items = [i for i in items if i.get("job_id") == job_id]
    photos_shape = [
        {
            "url":          i.get("url"),
            "thumb":        i.get("url"),
            "caption":      i.get("caption") or "",
            "job_id":       i.get("job_id"),
            "job_title":    i.get("job_title"),
            "service_type": i.get("job_title"),
            "submitted_at": i.get("uploaded_at"),
            "report_id":    i.get("report_id"),
            "source":       i.get("source"),
            "mime":         i.get("mime"),
        }
        for i in items
    ]
    return {
        "photos": photos_shape,
        "total":  bag["total"] if not job_id else len(photos_shape),
    }
