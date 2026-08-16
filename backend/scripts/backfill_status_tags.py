#!/usr/bin/env python3
"""Feb-2026 · Backfill Active/Inactive system tags on every customer.

For every tenant + every customer:
  - Seed the two system tags via ``ensure_system_tags`` if missing
  - Ensure the customer carries exactly one of {Active, Inactive}
    matching their current ``status`` (defaults to ``inactive`` when
    ``is_active is False``, else ``active``)
  - Preserves all other tags (Homeworks-imported, user-added, etc.)

Idempotent — a second run reports ``already_correct`` for everyone.

Usage::

    cd /app/backend && python3 -m scripts.backfill_status_tags
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

from dotenv import load_dotenv
load_dotenv("/app/backend/.env")


async def _run() -> dict:
    from config import db
    from routers.customer_tags import (
        SYSTEM_TAG_ACTIVE, SYSTEM_TAG_INACTIVE, ensure_system_tags,
        _recompute_usage,
    )
    report = {"at": datetime.now(timezone.utc).isoformat(),
                "tenants_processed": 0, "customers_scanned": 0,
                "tags_added": 0, "tags_removed": 0,
                "already_correct": 0}

    # Iterate one tenant at a time — cheap on Mongo and keeps the
    # working set bounded even for huge tenant counts.
    tenants = await db.tenants.find({}, {"_id": 0, "id": 1}).to_list(None)
    for t in tenants:
        tid = t["id"]
        report["tenants_processed"] += 1
        await ensure_system_tags(tid)
        async for c in db.customers.find(
            {"tenant_id": tid},
            {"_id": 0, "id": 1, "status": 1, "is_active": 1, "tags": 1},
        ):
            report["customers_scanned"] += 1
            tags = list(c.get("tags") or [])
            # Determine target based on is_active first (primary
            # signal), fall back to status string.
            if c.get("is_active") is False:
                target = "inactive"
            elif c.get("is_active") is True:
                target = "active"
            elif c.get("status") == "inactive":
                target = "inactive"
            else:
                target = "active"
            want_tag = (SYSTEM_TAG_ACTIVE if target == "active"
                          else SYSTEM_TAG_INACTIVE)
            other_tag = (SYSTEM_TAG_INACTIVE if target == "active"
                           else SYSTEM_TAG_ACTIVE)
            has_want = want_tag in tags
            has_other = other_tag in tags
            if has_want and not has_other:
                report["already_correct"] += 1
                continue
            ops: dict = {}
            if has_other:
                ops["$pull"] = {"tags": other_tag}
                report["tags_removed"] += 1
            if not has_want:
                ops["$addToSet"] = {"tags": want_tag}
                report["tags_added"] += 1
            if ops:
                await db.customers.update_one(
                    {"id": c["id"], "tenant_id": tid}, ops)
        # After the tenant sweep, recompute both counters once.
        await _recompute_usage(tid, SYSTEM_TAG_ACTIVE)
        await _recompute_usage(tid, SYSTEM_TAG_INACTIVE)
    return report


def main() -> int:
    print(json.dumps(asyncio.run(_run()), indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
