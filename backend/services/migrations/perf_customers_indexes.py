"""Phase F3.5 · Feb-2026 — Customer-scoped compound indexes.

Adds ``(tenant_id, customer_id, created_at)`` compound indexes on the
tenant-scoped collections that back the customer profile tabs
(``jobs``, ``invoices``, ``payments``, ``customer_notes``) plus
``(tenant_id, customer_id)`` on ``properties``.  These make the
customer detail tabs and the batched hydrations on the customer
list (properties_count, next_scheduled_at) index-covered so the
Phase F3.5 payload trim doesn't run out of gas at prod scale.

Sentinel key: ``perf_customers_v1``.  Do NOT reuse
``perf_triad_indexes_v1`` — Phase B is single-field-only; this
migration is compound-index only.

Rollback::

    for name in db.jobs.list_indexes():
        if name.startswith("perf_customers_"):
            db.jobs.drop_index(name)

Idempotent — a second run reports 0 created.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Tuple

logger = logging.getLogger("services.migrations.perf_customers_indexes")

MIGRATION_KEY = "perf_customers_v1"

# (collection, [(key, direction), ...], name_suffix)
_INDEXES: List[Tuple[str, List[Tuple[str, int]], str]] = [
    ("jobs",
     [("tenant_id", 1), ("customer_id", 1), ("created_at", -1)],
     "tenant_customer_created"),
    ("invoices",
     [("tenant_id", 1), ("customer_id", 1), ("created_at", -1)],
     "tenant_customer_created"),
    ("payments",
     [("tenant_id", 1), ("customer_id", 1), ("created_at", -1)],
     "tenant_customer_created"),
    ("customer_notes",
     [("tenant_id", 1), ("customer_id", 1), ("created_at", -1)],
     "tenant_customer_created"),
    ("properties",
     [("tenant_id", 1), ("customer_id", 1)],
     "tenant_customer"),
]


async def _has_index_matching_first_two_keys(
    coll: Any, first: str, second: str,
) -> bool:
    """True when the collection already has an index whose FIRST two
    key names are ``(first, second)`` in that order (any direction)."""
    async for idx in coll.list_indexes():
        keys = list((idx.get("key") or {}).items())
        if len(keys) >= 2 and keys[0][0] == first and keys[1][0] == second:
            return True
    return False


async def run(db: Any) -> Dict[str, Any]:
    """Ensure the F3.5 compound indexes exist.  Sentinel-gated."""
    sentinel = await db.migration_status.find_one(
        {"key": MIGRATION_KEY}, {"_id": 0},
    )
    if sentinel and sentinel.get("completed_at"):
        return {
            "ok": True, "skipped": True,
            "reason": "already_ran",
            "created": 0, "already": 0,
            "collections": [],
        }

    created: List[str] = []
    already: List[str] = []
    errors: List[Dict[str, str]] = []
    for coll_name, keys, suffix in _INDEXES:
        coll = db[coll_name]
        try:
            if await _has_index_matching_first_two_keys(
                coll, keys[0][0], keys[1][0],
            ):
                already.append(coll_name)
                continue
            idx_name = f"perf_customers_{coll_name}_{suffix}"
            await coll.create_index(keys, name=idx_name, background=True)
            created.append(coll_name)
            logger.info(
                "[perf_customers_v1] created index %s on %s",
                idx_name, coll_name,
            )
        except Exception as e:  # noqa: BLE001
            errors.append({"collection": coll_name, "error": str(e)})
            logger.warning(
                "[perf_customers_v1] index create failed on %s: %s",
                coll_name, e,
            )

    from datetime import datetime, timezone
    await db.migration_status.update_one(
        {"key": MIGRATION_KEY},
        {"$set": {"key": MIGRATION_KEY,
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                    "created": created, "already": already,
                    "errors": errors}},
        upsert=True,
    )
    return {
        "ok": True, "skipped": False,
        "created": len(created), "already": len(already),
        "collections": created,
        "errors": errors,
    }
