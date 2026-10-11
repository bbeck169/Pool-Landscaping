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
    from utils import not_deleted_filter as _nd
    cur = db.jobs.find(
        {"customer_id": customer_id, "tenant_id": tenant_id, **_nd()},
        {"_id": 0, "id": 1, "title": 1},
    )
    return [j async for j in cur]


def _is_image(mime: Optional[str]) -> bool:
    return bool(mime) and mime.lower().startswith("image/")


def _is_video(mime: Optional[str]) -> bool:
    return bool(mime) and mime.lower().startswith("video/")


# ═════════════════════════════════════════════════════════════════════
# GET /api/portal/photos  —  DATA-PARITY-C3 · Feb-2026
# RETIRED.  Duplicate registration with ``routers/portal_photos.py``.
# Both files registered the same path; FastAPI first-match wins so
# this handler was dead code.  Post-DATA-PARITY-C3 the live
# ``portal_photos.py`` delegates to
# ``services/customer_media.get_customer_media`` which merges every
# source this handler used to walk (``files`` + ``service_reports``)
# PLUS the two it missed (``jobs.photos[]`` + ``estimates.photos[]``).
# This block is left as a tombstone comment so future audits see
# why the file carries only an unread-count endpoint.
# ═════════════════════════════════════════════════════════════════════
async def _retired_portal_photos(*args, **kwargs):
    raise RuntimeError(
        "portal_media.portal_photos retired by DATA-PARITY-C3 · Feb-2026; "
        "use services.customer_media.get_customer_media instead."
    )


# ═════════════════════════════════════════════════════════════════════
# GET /api/portal/videos  —  DATA-PARITY-C3 · Feb-2026
# RETIRED.  Same reason as /api/portal/photos above — duplicate
# registration with ``routers/portal_videos.py``, dead code via
# FastAPI first-match ordering.  Post-fix the live
# ``portal_videos.py`` delegates to the shared reader.
# ═════════════════════════════════════════════════════════════════════
async def _retired_portal_videos(*args, **kwargs):
    raise RuntimeError(
        "portal_media.portal_videos retired by DATA-PARITY-C3 · Feb-2026; "
        "use services.customer_media.get_customer_media instead."
    )


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
