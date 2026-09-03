"""K21 · Feb-2026 — Perf indexes for the customer + schedule web hot paths.

Sentinel: ``k21_perf_indexes_v1``. Idempotent + sentinel-guarded.
Creates the 10 K21 indexes across seven collections that power the
customer-list, customer-detail, communication-timeline, and per-
customer invoice reads. See ``scripts.k21_seed_perf_indexes`` for
the standalone ops equivalent and the RCA background.

The two indexes that would have duplicated an existing compound
prefix are hard-skipped in this migration (matching the standalone
script's ``_SKIPPED`` list):

  * ``properties.k21_properties_tenant_customer`` — covered by
    ``perf_customers_properties_tenant_customer``.
  * ``payment_methods.k21_pm_tenant_customer_deleted`` — covered by
    ``payment_methods_tenant_customer_default_idx`` prefix.

K33 · Feb-2026 — boot-wired counterpart to
``scripts.k21_seed_perf_indexes``. Both paths co-exist safely:
``create_index`` is idempotent at the driver level, and this
migration is additionally sentinel-guarded so a second boot after
a successful first run is an early-return no-op.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from config import db


logger = logging.getLogger("k21_perf_indexes_migration")

_SENTINEL_ID = "k21_perf_indexes_v1"

# Each entry: (collection, index_name, key_spec).  Creation order
# is stable so the log output is deterministic.
_INDEXES: List[Tuple[str, str, List[Tuple[str, int]]]] = [
    ("customers", "k21_customers_id",
     [("id", 1)]),
    ("customers", "k21_customers_tenant_id_lookup",
     [("tenant_id", 1), ("id", 1)]),
    ("jobs", "k21_jobs_id",
     [("id", 1)]),
    ("jobs", "k21_jobs_tenant_customer_sched",
     [("tenant_id", 1), ("customer_id", 1), ("scheduled_date", -1)]),
    ("quotes", "k21_quotes_id",
     [("id", 1)]),
    ("quotes", "k21_quotes_tenant_customer_doctype_created",
     [("tenant_id", 1), ("customer_id", 1),
      ("doc_type", 1), ("created_at", -1)]),
    ("properties", "k21_properties_id",
     [("id", 1)]),
    ("chat_messages", "k21_chat_msgs_tenant_customer_time",
     [("tenant_id", 1), ("customer_id", 1), ("created_at", -1)]),
    ("communications", "k21_comms_tenant_customer_time",
     [("tenant_id", 1), ("customer_id", 1), ("created_at", -1)]),
    ("payment_methods", "k21_pm_id",
     [("id", 1)]),
]


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


async def run_k21_perf_indexes_migration(
    *, force: bool = False,
) -> Dict[str, Any]:
    """Create the K21 perf indexes if missing.

    Returns::

        {"status": "ok" | "skipped",
         "summary": {
             "created": <int>,
             "already_present": <int>,
             "errors": [...],
             "targets": [...],
         }}
    """
    if not force:
        sentinel = await _sentinel_row()
        if sentinel:
            return {"status": "skipped",
                    "reason": "sentinel_present",
                    "sentinel": sentinel}

    summary: Dict[str, Any] = {
        "created": 0,
        "already_present": 0,
        "errors": [],
        "targets": [],
    }

    # Cache per-collection index-name sets so we don't re-scan the
    # same collection more than once when multiple K21 indexes live
    # on the same collection.
    cache: Dict[str, set] = {}

    for coll_name, idx_name, keys in _INDEXES:
        target_result: Dict[str, Any] = {
            "collection": coll_name, "index": idx_name,
        }
        try:
            if coll_name not in cache:
                names = set()
                async for idx in db[coll_name].list_indexes():
                    names.add(idx.get("name") or "")
                cache[coll_name] = names
            if idx_name in cache[coll_name]:
                target_result["status"] = "already_present"
                summary["already_present"] += 1
            else:
                await db[coll_name].create_index(
                    keys, name=idx_name, background=True,
                )
                cache[coll_name].add(idx_name)
                target_result["status"] = "created"
                summary["created"] += 1
        except Exception as exc:  # noqa: BLE001
            target_result["status"] = "error"
            target_result["error"] = str(exc)
            summary["errors"].append(target_result)
            logger.warning(
                "[k21] index %s.%s failed: %s",
                coll_name, idx_name, exc,
            )
        summary["targets"].append(target_result)

    if not summary["errors"]:
        await _write_sentinel(summary)

    logger.info(
        "[k21] created=%s already_present=%s errors=%s",
        summary["created"], summary["already_present"],
        len(summary["errors"]),
    )
    return {"status": "ok", "summary": summary}
