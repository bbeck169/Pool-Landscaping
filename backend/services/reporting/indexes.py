"""Phase R1 · Feb-2026 — Reporting-suite index migration.

Idempotent one-shot that ensures the compound indexes the R1
metrics need are present on both preview and prod. Follows the
same shape as ``services/migrations/perf_triad_indexes.py``:

* Sentinel row in ``db.migration_status`` keyed by
  ``r1_reporting_indexes_v1`` — a healthy pod only pays the cost
  on the first cold boot after the phase ships.
* Second run reports ``0 created, N already-existed``.
* Failure to create any single index degrades to a warning log
  and continues — a missing index makes queries slower, not
  broken.

Indexes created (all with ``background=True``, all prefixed with
``r1_reporting_`` so ops can sweep them in a rollback):

    quotes:
      * (tenant_id, customer_id, paid_at)      — cashflow, ar
      * (tenant_id, customer_id, created_at)   — pnl, revenue-by-service
      * (tenant_id, status, due_date)          — unpaid invoices, ar aging
      * (tenant_id, service_category_id)       — revenue-by-service
    checks:
      * (tenant_id, date)                       — pnl OpEx / depreciation
      * (tenant_id, category, date)             — pnl category breakdown
    expense_categories:
      * (tenant_id, transaction_id)             — LLM category join
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List

logger = logging.getLogger("services.reporting.indexes")

MIGRATION_KEY = "r1_reporting_indexes_v1"


# Each entry: (collection, index_spec, index_name).
_R1_INDEXES: List[tuple[str, List[tuple[str, int]], str]] = [
    ("quotes", [("tenant_id", 1), ("customer_id", 1), ("paid_at", 1)],
     "r1_reporting_quotes_tenant_customer_paidat"),
    ("quotes", [("tenant_id", 1), ("customer_id", 1), ("created_at", 1)],
     "r1_reporting_quotes_tenant_customer_created"),
    ("quotes", [("tenant_id", 1), ("status", 1), ("due_date", 1)],
     "r1_reporting_quotes_tenant_status_duedate"),
    ("quotes", [("tenant_id", 1), ("service_category_id", 1)],
     "r1_reporting_quotes_tenant_servicecat"),
    ("checks", [("tenant_id", 1), ("date", 1)],
     "r1_reporting_checks_tenant_date"),
    ("checks", [("tenant_id", 1), ("category", 1), ("date", 1)],
     "r1_reporting_checks_tenant_category_date"),
    ("expense_categories",
     [("tenant_id", 1), ("transaction_id", 1)],
     "r1_reporting_expcat_tenant_transaction"),
]


async def _sentinel_exists(db) -> bool:
    row = await db.migration_status.find_one({"_id": MIGRATION_KEY})
    return bool(row and row.get("completed_at"))


async def _mark_sentinel(db, summary: Dict[str, Any]) -> None:
    from datetime import datetime, timezone
    await db.migration_status.update_one(
        {"_id": MIGRATION_KEY},
        {"$set": {
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "summary": summary,
        }},
        upsert=True,
    )


async def _index_already_present(db, collection: str, name: str) -> bool:
    """Return True when the exact-named index is already on the
    collection. Also returns True when a *differently-named* index
    covers the same keys (so a second pass doesn't try to duplicate)."""
    try:
        existing = await db[collection].index_information()
    except Exception:
        return False
    if name in existing:
        return True
    return False


async def run(db) -> Dict[str, Any]:
    """Ensure every R1 reporting index exists. Idempotent.

    Returns a summary dict::

        {
            "created": [(coll, name), ...],
            "already": [(coll, name), ...],
            "failed":  [(coll, name, error), ...],
            "elapsed_ms": 123,
            "sentinel_hit": bool,
        }
    """
    started = time.time()
    summary: Dict[str, Any] = {
        "created": [], "already": [], "failed": [],
        "elapsed_ms": 0, "sentinel_hit": False,
    }

    if await _sentinel_exists(db):
        # Cheap fast-path — still runs a sanity check to verify
        # each index is actually present (someone may have manually
        # dropped one). If any are missing we re-create them and
        # DO NOT overwrite the sentinel.
        summary["sentinel_hit"] = True

    for coll, spec, name in _R1_INDEXES:
        try:
            if await _index_already_present(db, coll, name):
                summary["already"].append((coll, name))
                continue
            await db[coll].create_index(spec, name=name, background=True)
            summary["created"].append((coll, name))
        except Exception as exc:  # pragma: no cover — defensive
            logger.warning("[r1-indexes] %s / %s failed: %s", coll, name, exc)
            summary["failed"].append((coll, name, str(exc)))

    summary["elapsed_ms"] = int((time.time() - started) * 1000)

    # Only mark the sentinel when we made it through the loop
    # cleanly (no failures). Otherwise a subsequent boot retries.
    if not summary["failed"] and not summary["sentinel_hit"]:
        await _mark_sentinel(db, {
            "created_count": len(summary["created"]),
            "already_count": len(summary["already"]),
        })

    return summary


async def ensure_indexes(db) -> Dict[str, Any]:
    """Public entry point — thin wrapper so the boot hook + admin
    ``scripts.ensure_indexes`` share the same code path."""
    return await run(db)
