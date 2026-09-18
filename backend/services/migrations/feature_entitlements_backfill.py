"""Sprint 3c · Feb-2026 — Feature entitlements defaults backfill.

Seeds every tenant with one ``feature_entitlements`` row per
feature (``enabled=false``, ``billing_status=None``) so the
marketplace GET returns a complete grid on day zero. Idempotent —
per-(tenant, feature_key) `$exists: false` guard.

Usage:
    python -m services.migrations.feature_entitlements_backfill --dry-run
    python -m services.migrations.feature_entitlements_backfill

Or via the admin endpoint:
    POST /api/admin/entitlements/backfill-feature-defaults
        (super_admin-only; body: ``?dry_run=true|false``)
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict

from motor.motor_asyncio import AsyncIOMotorClient

from services.entitlements.registry import FEATURE_KEYS


log = logging.getLogger("migrations.feature_entitlements")


async def backfill(db, *, dry_run: bool = False) -> Dict[str, Any]:
    """Insert one ``feature_entitlements`` row per (tenant, feature)
    pair that doesn't already have one. Returns per-feature counts.
    """
    counts: Dict[str, int] = {}
    now = datetime.now(timezone.utc).isoformat()
    tenants = await db.tenants.find({}, {"_id": 0, "id": 1}).to_list(length=None)
    for feature_key in FEATURE_KEYS:
        n = 0
        for t in tenants:
            tid = t.get("id")
            if not tid:
                continue
            existing = await db.feature_entitlements.find_one(
                {"tenant_id": tid, "feature_key": feature_key},
                {"_id": 0, "id": 1},
            )
            if existing:
                continue
            n += 1
            if dry_run:
                continue
            await db.feature_entitlements.insert_one({
                "id":              str(uuid.uuid4()),
                "tenant_id":       tid,
                "feature_key":     feature_key,
                "enabled":         False,
                "billing_status":  None,
                "cancels_at":      None,
                "created_at":      now,
                "updated_at":      now,
            })
        counts[feature_key] = n
    total = sum(counts.values())
    log.info(
        "[feature_entitlements_backfill] dry_run=%s counts=%s total=%d",
        dry_run, counts, total,
    )
    return {"dry_run": dry_run, "counts": counts, "total_writes": total}


async def _main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true",
                    help="Count rows that would be inserted without persisting")
    args = p.parse_args()
    url = os.environ["MONGO_URL"]
    name = os.environ["DB_NAME"]
    client = AsyncIOMotorClient(url)
    try:
        result = await backfill(client[name], dry_run=args.dry_run)
        print(result)
    finally:
        client.close()


if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.INFO)
    asyncio.run(_main())
