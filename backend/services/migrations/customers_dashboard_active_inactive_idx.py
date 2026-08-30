"""Feb-2026 · Customers dashboard Active/Inactive tile index.

Sentinel: ``customers_dashboard_active_inactive_idx_v1``. Idempotent
+ sentinel-guarded.

Shipped alongside the Active/Inactive Customers tile REDEFINITION
(Feb-2026, second pass). The dashboard endpoint's admin/super_admin
branch now runs two ``db.customers.count_documents`` queries per
hit:

    * active   = ``is_active != False`` + not soft-deleted
                 (matches True, missing, and null so legacy rows
                 that never had ``is_active`` stamped still count
                 as active — the same read semantics as
                 ``models.py:96`` and ``ActivationControl.jsx:33``).
    * inactive = ``is_active == False`` + not muted + not
                 soft-deleted.

Ships a compound index ``(tenant_id, is_active, is_muted,
deleted_at)`` so both queries use a covering index scan instead of
a collection scan.

Why this shape:
    * ``tenant_id`` first — every dashboard query is single-tenant.
    * ``is_active`` second — the primary discriminator between the
      two buckets; equality-selective.
    * ``is_muted`` third — only touches the inactive query but
      cheap to include for the bucket that filters on it.
    * ``deleted_at`` fourth — both queries filter on it; kept last
      because the ``{$exists: false}`` predicate is
      range-scan-selective, not equality.

Cheap belt-and-suspenders — the customers row count per tenant is
low four digits in production, so both queries are milliseconds
without the index. This keeps them that way as the count grows.

Deferred cleanup — the old ``rjt_tenant_active_customer_idx`` on
``recurring_job_templates`` is now orphaned by this dashboard
change (the cross-tenant recurring-job cron in
``routers/recurring_jobs.py:641`` uses ``find({"active": True})``
without ``tenant_id`` so it can't leverage the compound). Logged
as TD-06 in ``/app/memory/TECH_DEBT.md`` — index drop is scoped
to a separate cleanup phase, not folded into this semantic fix.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from config import db


logger = logging.getLogger("customers_dashboard_active_inactive_idx_migration")


_SENTINEL_ID = "customers_dashboard_active_inactive_idx_v1"
_INDEX_NAME = "customers_dashboard_active_inactive_idx"


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


async def run_customers_dashboard_active_inactive_idx_migration(
    *, force: bool = False,
) -> Dict[str, Any]:
    """Create the compound index if missing. Idempotent.

    Returns::

        {"status": "ok" | "skipped",
         "summary": {
             "index_name":  _INDEX_NAME,
             "created":     bool,
             "already_present": bool,
             "errors":      [str, ...],
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
        async for idx in db.customers.list_indexes():
            existing.add(idx.get("name") or "")
        if _INDEX_NAME in existing:
            summary["already_present"] = True
        else:
            await db.customers.create_index(
                [("tenant_id", 1), ("is_active", 1),
                  ("is_muted", 1), ("deleted_at", 1)],
                name=_INDEX_NAME,
            )
            summary["created"] = True
    except Exception as exc:                                      # noqa: BLE001
        summary["errors"].append(str(exc))
        logger.warning(
            "[customers_dashboard_active_inactive_idx] index create failed: %s",
            exc,
        )

    await _write_sentinel(summary)
    logger.info(
        "[customers_dashboard_active_inactive_idx] created=%s "
        "already_present=%s errors=%s",
        summary["created"], summary["already_present"],
        len(summary["errors"]),
    )
    return {"status": "ok", "summary": summary}
