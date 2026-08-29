"""Feb-2026 · Recurring-template active-customer aggregation index.

Sentinel: ``recurring_templates_active_customer_idx_v1``. Idempotent
+ sentinel-guarded.

The admin dashboard endpoint runs an ``active_customer_ids = distinct
customer_id in recurring_job_templates where tenant_id + active=True``
aggregation on every hit. Ships a compound index
``(tenant_id, active, customer_id)`` so the query uses a covering
distinct-scan instead of a collection scan.

Cheap belt-and-suspenders — the current template row count per tenant
is small (< 10k in production), so the aggregation is milliseconds
without the index. This index keeps it that way as the template count
grows.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from config import db


logger = logging.getLogger("recurring_templates_active_customer_idx_migration")


_SENTINEL_ID = "recurring_templates_active_customer_idx_v1"
_INDEX_NAME = "rjt_tenant_active_customer_idx"


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


async def run_recurring_templates_active_customer_idx_migration(
    *, force: bool = False,
) -> Dict[str, Any]:
    """Create the compound index if missing. Idempotent.

    Returns::

        {"status": "ok" | "skipped",
         "summary": {
             "index_name":  _INDEX_NAME,
             "created":     bool,
             "already_present": bool,
         }}
    """
    if not force:
        sentinel = await _sentinel_row()
        if sentinel:
            return {"status": "skipped",
                    "reason": "sentinel_present",
                    "sentinel": sentinel}

    summary: Dict[str, Any] = {
        "index_name": _INDEX_NAME,
        "created": False,
        "already_present": False,
        "errors": [],
    }
    try:
        existing = set()
        async for idx in db.recurring_job_templates.list_indexes():
            existing.add(idx.get("name") or "")
        if _INDEX_NAME in existing:
            summary["already_present"] = True
        else:
            await db.recurring_job_templates.create_index(
                [("tenant_id", 1), ("active", 1), ("customer_id", 1)],
                name=_INDEX_NAME,
            )
            summary["created"] = True
    except Exception as exc:                                      # noqa: BLE001
        summary["errors"].append(str(exc))
        logger.warning(
            "[recurring_templates_active_customer_idx] index create failed: %s",
            exc,
        )

    await _write_sentinel(summary)
    logger.info(
        "[recurring_templates_active_customer_idx] created=%s "
        "already_present=%s errors=%s",
        summary["created"], summary["already_present"],
        len(summary["errors"]),
    )
    return {"status": "ok", "summary": summary}
