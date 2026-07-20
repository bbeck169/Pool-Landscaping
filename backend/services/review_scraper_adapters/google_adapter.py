"""Google Business Profile review scraper — Reviews Phase 3.

Reuses the existing GBP OAuth infrastructure (``routers/gbp.py``): the
``_access_token()`` helper refreshes the tenant's stored refresh token
transparently, and ``_google_get()`` handles the low-level HTTP.

Contract with the dispatcher:
- Returns ``list[dict]`` on success (each dict shaped for
  ``review_scraper._upsert_review``).
- Returns ``{"status": "disabled"}`` when
  ``GOOGLE_GBP_INTEGRATION_ENABLED`` is falsy.
- Returns ``{"status": "not_connected"}`` when the tenant hasn't
  completed OAuth (no refresh token) or no location is configured.

Errors during the fetch propagate as exceptions so the dispatcher can
journal them.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Union

from config import db

logger = logging.getLogger(__name__)


def _enabled() -> bool:
    v = (os.environ.get("GOOGLE_GBP_INTEGRATION_ENABLED") or "").strip().lower()
    # Default = false so a stale env doesn't sync unexpectedly.
    return v in ("1", "true", "yes", "on")


async def _resolve_location() -> str:
    """Read the GBP settings singleton so we know which location to
    fetch reviews from. Currently a global config — future work could
    key it per-tenant if a tenant runs multiple GBP profiles."""
    from routers.gbp import CONFIG_ID  # local import to avoid cycles
    doc = await db.gbp_settings.find_one({"id": CONFIG_ID}, {"_id": 0})
    return (doc or {}).get("location") or ""


async def fetch_recent_reviews(tenant_id: str) -> Union[List[Dict[str, Any]], Dict[str, str]]:
    if not _enabled():
        return {"status": "disabled",
                "detail": "GOOGLE_GBP_INTEGRATION_ENABLED is not set to true."}

    # Lazy-import GBP internals so a broken GBP module doesn't crash
    # import-time of the whole scraper package.
    try:
        from routers.gbp import _access_token, _google_get, V4_API
    except Exception as e:
        return {"status": "not_configured",
                "detail": f"GBP module unavailable: {e}"}

    tokens = await db.gbp_settings.find_one({"id": "gbp:tokens"}, {"_id": 0})
    if not tokens or not tokens.get("refresh_token"):
        return {"status": "not_connected",
                "detail": "GBP OAuth not completed — connect via /gbp/auth-url."}

    location = await _resolve_location()
    if not location:
        return {"status": "not_configured",
                "detail": "No GBP location configured on the tenant."}

    try:
        token = await _access_token()
        raw = await _google_get(f"{V4_API}/{location}/reviews", token)
    except Exception as e:
        logger.warning(f"[review_scraper.google] fetch failed: {e}")
        raise

    reviews = (raw or {}).get("reviews") or []
    out: List[Dict[str, Any]] = []
    for r in reviews:
        # GBP star ratings arrive as words (ONE..FIVE). Map to ints.
        stars = _star_word_to_int(r.get("starRating"))
        if stars is None:
            continue
        out.append({
            "source_review_id": r.get("reviewId") or (r.get("name") or "").split("/")[-1],
            "star_rating": stars,
            "review_text": r.get("comment") or "",
            "reviewer_name": (r.get("reviewer") or {}).get("displayName"),
            "external_review_url": (r.get("reviewer") or {}).get("profilePhotoUrl"),
            "created_at": r.get("createTime"),
            "partial_content": False,
        })
    return out


_STAR_MAP = {
    "STAR_RATING_UNSPECIFIED": None,
    "ONE": 1, "TWO": 2, "THREE": 3, "FOUR": 4, "FIVE": 5,
}


def _star_word_to_int(word: Any) -> Any:
    if isinstance(word, int):
        return max(1, min(5, word))
    if isinstance(word, str):
        return _STAR_MAP.get(word.upper())
    return None
