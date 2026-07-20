"""Yelp Fusion review scraper — Reviews Phase 3.

Yelp Fusion's ``/businesses/{id}/reviews`` endpoint returns up to
**3 excerpts** per business (`text_excerpt`) rather than full review
text, and does not include the reviewer's Yelp profile URL. Each row
we upsert is flagged ``partial_content=true`` so the admin UI can
warn users that Yelp doesn't publish full reviews via API.

Requires:
- ``YELP_API_KEY`` — from https://fusion.yelp.com/
- Tenant needs a Yelp business identifier configured (we read it from
  the ``tenant_review_platforms`` row where ``platform="yelp"`` — the
  ``review_url`` is expected to be a canonical Yelp URL from which we
  parse the business slug).

When either the key or the tenant config is missing, the adapter
returns ``{"status": "not_configured"}`` without making a network
call.
"""
from __future__ import annotations

import logging
import os
import re
from typing import Any, Dict, List, Union

import httpx

from config import db

logger = logging.getLogger(__name__)

_YELP_API_ROOT = "https://api.yelp.com/v3"


def _api_key() -> str:
    return (os.environ.get("YELP_API_KEY") or "").strip()


_URL_RE = re.compile(r"yelp\.com/biz/([^/?#]+)")


async def _resolve_business_id(tenant_id: str) -> str:
    """Parse the ``business slug`` out of the tenant-configured Yelp
    Review URL. Yelp Fusion accepts either the numeric business ID or
    the slug in the ``/businesses/{id}/reviews`` path."""
    row = await db.tenant_review_platforms.find_one(
        {"tenant_id": tenant_id, "platform": "yelp", "is_active": True},
        {"_id": 0, "review_url": 1},
    )
    if not row:
        return ""
    url = row.get("review_url") or ""
    m = _URL_RE.search(url)
    return m.group(1) if m else ""


async def fetch_recent_reviews(tenant_id: str) -> Union[List[Dict[str, Any]], Dict[str, str]]:
    key = _api_key()
    if not key:
        return {"status": "not_configured",
                "detail": "YELP_API_KEY env var is not set."}

    biz_id = await _resolve_business_id(tenant_id)
    if not biz_id:
        return {"status": "not_configured",
                "detail": "No active Yelp platform row for this tenant, or the "
                           "review_url is not a canonical yelp.com/biz/… URL."}

    url = f"{_YELP_API_ROOT}/businesses/{biz_id}/reviews"
    try:
        async with httpx.AsyncClient(timeout=25) as c:
            r = await c.get(url, headers={"Authorization": f"Bearer {key}"})
    except Exception as e:
        logger.warning(f"[review_scraper.yelp] http error: {e}")
        raise

    if r.status_code == 401 or r.status_code == 403:
        return {"status": "not_configured",
                "detail": f"Yelp API rejected the key ({r.status_code})."}
    if r.status_code >= 400:
        raise RuntimeError(f"Yelp Fusion returned HTTP {r.status_code}: {r.text[:200]}")

    payload = r.json() or {}
    out: List[Dict[str, Any]] = []
    for row in payload.get("reviews", [])[:3]:  # Yelp caps at 3.
        rid = row.get("id")
        if not rid:
            continue
        out.append({
            "source_review_id": str(rid),
            "star_rating": int(row.get("rating") or 0),
            "review_text": (row.get("text") or "").strip(),  # excerpt
            "reviewer_name": ((row.get("user") or {}).get("name") or "").strip() or None,
            "external_review_url": row.get("url"),
            "created_at": row.get("time_created"),
            "partial_content": True,
        })
    return out
