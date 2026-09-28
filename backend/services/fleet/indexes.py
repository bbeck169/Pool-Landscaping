"""FLEET-A · Index bootstrap for the fleet collections.

Idempotent — safe to call on every process start. Reads the
retention env var so ops can tune breadcrumb TTL without redeploying.
"""
from __future__ import annotations

import logging
import os

from pymongo import ASCENDING, DESCENDING, IndexModel

logger = logging.getLogger("fleet.indexes")


def _retention_days() -> int:
    try:
        return int(os.environ.get("FLEET_BREADCRUMB_RETENTION_DAYS", "30"))
    except (TypeError, ValueError):
        return 30


async def ensure_fleet_indexes(db) -> None:
    """Create the FLEET-A indexes. Idempotent."""
    retention_seconds = _retention_days() * 24 * 60 * 60

    await db.tech_locations.create_indexes([
        IndexModel(
            [("tenant_id", ASCENDING),
             ("tech_user_id", ASCENDING),
             ("recorded_at", DESCENDING)],
            name="tech_locations_tenant_tech_time_bg",
            background=True,
        ),
        IndexModel(
            [("tenant_id", ASCENDING), ("recorded_at", DESCENDING)],
            name="tech_locations_tenant_time_bg",
            background=True,
        ),
        # TTL — Mongo requires a bare datetime field on the doc.
        # We store both ``recorded_at`` (ISO string, for consumers)
        # and ``recorded_at_dt`` (BSON date, for the TTL sweep).
        IndexModel(
            [("recorded_at_dt", ASCENDING)],
            name="tech_locations_ttl",
            expireAfterSeconds=retention_seconds,
            background=True,
        ),
    ])

    await db.fleet_membership.create_indexes([
        IndexModel(
            [("tenant_id", ASCENDING), ("tech_user_id", ASCENDING)],
            name="fleet_membership_unique",
            unique=True,
            background=True,
        ),
    ])

    await db.fleet_eta_snapshots.create_indexes([
        IndexModel(
            [("tenant_id", ASCENDING), ("job_id", ASCENDING),
              ("computed_at", DESCENDING)],
            name="fleet_eta_tenant_job_time_bg",
            background=True,
        ),
        IndexModel(
            [("tenant_id", ASCENDING), ("tech_user_id", ASCENDING),
              ("computed_at", DESCENDING)],
            name="fleet_eta_tenant_tech_time_bg",
            background=True,
        ),
        IndexModel(
            [("computed_at_dt", ASCENDING)],
            name="fleet_eta_snapshots_ttl",
            expireAfterSeconds=24 * 60 * 60,       # 24h
            background=True,
        ),
    ])

    await db.fleet_notification_dedup.create_indexes([
        IndexModel(
            [("tenant_id", ASCENDING),
             ("tech_user_id", ASCENDING),
             ("job_id", ASCENDING),
             ("sent_at_dt", DESCENDING)],
            name="fleet_notif_dedup_lookup_bg",
            background=True,
        ),
        IndexModel(
            [("sent_at_dt", ASCENDING)],
            name="fleet_notif_dedup_ttl",
            expireAfterSeconds=24 * 60 * 60,       # 24h — safely > 4h window
            background=True,
        ),
    ])

    logger.info(
        "[fleet.indexes] ensured (retention_days=%s)", _retention_days(),
    )
