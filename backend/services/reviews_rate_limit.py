"""Reviews Phase 1 · Widget rate-limit adapter (Feb 2026).

Public review widget is CORS-open by design. This service protects it
with a lightweight per-IP + per-tenant TTL-indexed Mongo counter,
mirroring the Zillow rate-limit pattern already in use elsewhere in
the codebase (see ``services/zillow_rate_limit.py``).

* 60 hits per minute per (ip, tenant_slug) — enforced by counting the
  rows in ``reviews_widget_rate`` whose ``bucket_iso`` matches the
  current minute.
* Rows carry a TTL index (``bucket_dt + 300s``) so the collection stays
  small — a couple of thousand rows even under sustained abuse before
  Mongo garbage-collects them.
* Never raises — on Mongo hiccups the call is logged and allowed
  through (fail-open, since this is the *public* widget and blocking
  it would deny legitimate embed traffic during a partial outage).
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Optional

from config import db, logger

WIDGET_MAX_PER_MINUTE = 60
_TTL_SECONDS = 300
_INDEX_ENSURED = False


async def _ensure_index() -> None:
    global _INDEX_ENSURED
    if _INDEX_ENSURED:
        return
    try:
        await db.reviews_widget_rate.create_index(
            "bucket_dt", expireAfterSeconds=_TTL_SECONDS,
        )
        await db.reviews_widget_rate.create_index(
            [("ip", 1), ("tenant_slug", 1), ("bucket_iso", 1)],
        )
        _INDEX_ENSURED = True
    except Exception as e:
        logger.warning(f"[reviews_widget_rate] index setup partial: {e}")


def _minute_bucket(now: Optional[datetime] = None) -> tuple[str, datetime]:
    dt = (now or datetime.now(timezone.utc)).replace(second=0, microsecond=0)
    return dt.isoformat(), dt


async def check_and_charge(ip: str, tenant_slug: str) -> tuple[bool, int]:
    """Return ``(allowed, count_after_charge)``. On error, allow through.

    ``ip`` may be ``""`` if the caller couldn't resolve one; in that
    case we still charge under the literal ``""`` string so that
    unauthenticated widget hits from a single edge without a
    forwardable IP still get throttled collectively.
    """
    await _ensure_index()
    try:
        bucket_iso, bucket_dt = _minute_bucket()
        count = await db.reviews_widget_rate.count_documents({
            "ip": ip, "tenant_slug": tenant_slug, "bucket_iso": bucket_iso,
        })
        if count >= WIDGET_MAX_PER_MINUTE:
            return False, count
        await db.reviews_widget_rate.insert_one({
            "ip": ip, "tenant_slug": tenant_slug,
            "bucket_iso": bucket_iso, "bucket_dt": bucket_dt,
        })
        return True, count + 1
    except Exception as e:
        # Fail-open. Widget must stay embeddable during storage hiccups.
        logger.warning(f"[reviews_widget_rate] check_and_charge failed: {e}")
        return True, 0
