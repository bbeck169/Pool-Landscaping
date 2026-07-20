"""Review-sync HTTP surface — Reviews Phase 3 (Feb 2026).

Three admin endpoints:
- ``POST /api/reviews/sync/{platform}/sync-now``   → immediate sweep
- ``GET  /api/reviews/sync/events``                → sync history

The dispatcher (``services/review_scraper``) does the heavy lifting;
this router is a thin authorised entry point.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from config import db
from utils import require_admin
from routers.tenants import get_current_tenant
from services import review_scraper

logger = logging.getLogger(__name__)

router = APIRouter()

_ALL_PLATFORMS = {"google", "facebook", "yelp", "bbb", "custom"}


@router.post("/reviews/sync/{platform}/sync-now")
async def sync_now(platform: str,
                    user: dict = Depends(require_admin),
                    tenant: dict = Depends(get_current_tenant)):
    """Fire a scrape immediately for the caller's tenant + platform.

    Returns the same summary shape the daily sweeps write to
    ``review_sync_events``. BBB / custom respond 404 — see Phase 3
    deviations for why (no viable API).
    """
    p = (platform or "").strip().lower()
    if p not in _ALL_PLATFORMS:
        raise HTTPException(404, f"Unknown platform '{platform}'")
    if p in review_scraper.UNSUPPORTED_PLATFORMS:
        raise HTTPException(
            404,
            "BBB has no public review API and HTML scraping is legally "
            "and technically fragile; capture BBB reviews via "
            "`POST /api/reviews/reviews` (source='manual_entry')."
            if p == "bbb"
            else "Custom platforms are managed manually.",
        )
    summary = await review_scraper.sync_platform(tenant["id"], p)
    return summary


@router.get("/reviews/sync/events")
async def list_sync_events(user: dict = Depends(require_admin),
                            tenant: dict = Depends(get_current_tenant),
                            platform: Optional[str] = Query(None),
                            limit: int = Query(50, ge=1, le=500)):
    """Return recent sync-attempt rows for this tenant, newest first."""
    q = {"tenant_id": tenant["id"]}
    if platform:
        q["platform"] = platform.strip().lower()
    rows = await (db.review_sync_events
                    .find(q, {"_id": 0})
                    .sort("ran_at", -1)
                    .to_list(limit))
    return {"count": len(rows), "events": rows}


@router.get("/reviews/sync/latest")
async def latest_per_platform(user: dict = Depends(require_admin),
                                tenant: dict = Depends(get_current_tenant)):
    """One row per platform showing the most-recent sync outcome — used
    by the dashboard "Sync status" strip."""
    out = {}
    for p in ("google", "facebook", "yelp"):
        row = await db.review_sync_events.find_one(
            {"tenant_id": tenant["id"], "platform": p},
            {"_id": 0},
            sort=[("ran_at", -1)],
        )
        out[p] = row
    return out
