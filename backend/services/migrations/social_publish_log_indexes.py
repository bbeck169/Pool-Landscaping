"""Feb-2026 · Social publishing idempotency + audit indexes.

Sentinel: ``social_publish_log_indexes_v1``. Idempotent +
sentinel-guarded.

Shipped alongside the Soshie AI-Agent Expansion P2 (WordPress
publishing).  Two indexes on ``db.social_publish_log``:

    1. **Compound unique** on ``(tenant_id, action_id, platform)`` —
       primary idempotency key.  Two ``POST /soshie/publish`` calls
       with the same approved action MUST land the same
       platform_post_id, not two.
    2. **Non-unique** on ``(tenant_id, platform, dispatched_at)`` —
       covers the "show me every publish attempt on this
       platform" list view in the admin dashboard.

Two indexes on ``db.social_posts`` (audit collection):

    3. Non-unique on ``(tenant_id, platform, published_at)`` —
       covers the publish history feed.
    4. Non-unique on ``(tenant_id, status)`` — covers "show me
       pending / failed posts" filters.

Two indexes on ``db.social_platform_credentials`` (config):

    5. Compound unique on ``(tenant_id, platform)`` — one row
       per (tenant, platform).  Guarantees a re-connect UPSERTs
       instead of creating a duplicate row.

Kept as a single migration so the sentinel + rollback story is
one unit rather than five overlapping ones.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from config import db


logger = logging.getLogger("social_publish_log_indexes_migration")


_SENTINEL_ID = "social_publish_log_indexes_v1"


async def _sentinel_row() -> Optional[Dict[str, Any]]:
    return await db.migrations.find_one({"id": _SENTINEL_ID}, {"_id": 0})


async def _write_sentinel(summary: Dict[str, Any]) -> None:
    await db.migrations.update_one(
        {"id": _SENTINEL_ID},
        {"$set": {
            "id": _SENTINEL_ID,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "summary": summary,
        }},
        upsert=True,
    )


async def _ensure_index(coll, keys, name, *, unique=False,
                             summary_bucket=None):
    try:
        existing = set()
        async for idx in coll.list_indexes():
            existing.add(idx.get("name") or "")
        if name in existing:
            if summary_bucket is not None:
                summary_bucket["already_present"].append(name)
            return
        await coll.create_index(keys, name=name, unique=unique)
        if summary_bucket is not None:
            summary_bucket["created"].append(name)
    except Exception as exc:                                      # noqa: BLE001
        logger.warning("[social_publish_log_indexes] %s failed: %s",
                          name, exc)
        if summary_bucket is not None:
            summary_bucket["errors"].append(f"{name}: {exc}")


async def run_social_publish_log_indexes_migration(
    *, force: bool = False,
) -> Dict[str, Any]:
    if not force:
        sentinel = await _sentinel_row()
        if sentinel:
            return {"status": "skipped",
                    "reason": "sentinel_present",
                    "sentinel": sentinel}

    summary: Dict[str, Any] = {
        "created": [], "already_present": [], "errors": [],
    }
    await _ensure_index(
        db.social_publish_log,
        [("tenant_id", 1), ("action_id", 1), ("platform", 1)],
        name="social_publish_log_uniq",
        unique=True, summary_bucket=summary,
    )
    await _ensure_index(
        db.social_publish_log,
        [("tenant_id", 1), ("platform", 1), ("dispatched_at", -1)],
        name="social_publish_log_by_platform",
        summary_bucket=summary,
    )
    await _ensure_index(
        db.social_posts,
        [("tenant_id", 1), ("platform", 1), ("published_at", -1)],
        name="social_posts_by_platform",
        summary_bucket=summary,
    )
    await _ensure_index(
        db.social_posts,
        [("tenant_id", 1), ("status", 1)],
        name="social_posts_by_status",
        summary_bucket=summary,
    )
    await _ensure_index(
        db.social_platform_credentials,
        [("tenant_id", 1), ("platform", 1)],
        name="social_platform_credentials_uniq",
        unique=True, summary_bucket=summary,
    )

    await _write_sentinel(summary)
    logger.info(
        "[social_publish_log_indexes] created=%d already_present=%d errors=%d",
        len(summary["created"]), len(summary["already_present"]),
        len(summary["errors"]),
    )
    return {"status": "ok", "summary": summary}
