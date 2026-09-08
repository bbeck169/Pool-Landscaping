"""Feb-2026 · Task 5 · one-shot dedup for the ``distance_matrix_cache``
collection.

Context
-------
Task 5 added a **unique** index ``dmc_key_unique`` on
``distance_matrix_cache.key`` (see ``backend/db_indexes.py``).  The
collection historically had ZERO indexes on production so it's
plausible that concurrent leg-cache writes from
``services.distance_matrix`` landed multiple rows with the same
``key``.  If any duplicate exists, ``createIndex`` will fail with a
``DuplicateKey`` error and the boot audit will halt.

This script safely reconciles the collection BEFORE the index is
created (or after a failed creation):

* Groups every row by ``key``.
* Keeps the row with the newest ``updated_at`` (falling back to the
  MongoDB ``_id`` timestamp when ``updated_at`` is missing).
* Deletes the others.

Idempotent — running it twice on a clean collection is a no-op.

Usage
-----
Dry-run (default; reports without mutating)::

    python -m backend.scripts.dedup_distance_matrix_cache

Apply (deletes older duplicates)::

    python -m backend.scripts.dedup_distance_matrix_cache --apply

Run this once **before** restarting the backend if the boot-time index
creation surfaces a ``DuplicateKey`` error on
``distance_matrix_cache``.  Safe to re-run.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# Allow ``python backend/scripts/…`` invocation from repo root.
_HERE = Path(__file__).resolve()
_BACKEND = _HERE.parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from dotenv import load_dotenv
load_dotenv(_BACKEND / ".env")

from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402


logger = logging.getLogger("dedup_dmc")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)


def _row_sort_key(row: Dict[str, Any]) -> Any:
    """Sort tuple: newest first.

    Prefers ``updated_at`` (ISO string sorts lexically for UTC ISO
    timestamps).  Falls back to the row's ``_id`` object which is
    monotonically increasing when Mongo generates it.
    """
    return (row.get("updated_at") or "", str(row.get("_id") or ""))


async def dedup(coll, *, apply: bool = False) -> Dict[str, int]:
    """Group by ``key``, keep newest, remove older duplicates.

    Returns a summary dict::

        {"scanned": N, "duplicate_keys": K, "rows_removed": R,
         "applied": bool}
    """
    # $group → keys with more than one row.
    pipeline = [
        {"$group": {"_id": "$key",
                     "count": {"$sum": 1},
                     "ids": {"$push": "$_id"}}},
        {"$match": {"count": {"$gt": 1}}},
    ]
    dup_keys: List[Dict[str, Any]] = []
    async for row in coll.aggregate(pipeline):
        dup_keys.append(row)

    scanned = await coll.estimated_document_count()
    if not dup_keys:
        logger.info("no duplicates found (scanned≈%d rows) — nothing to do",
                     scanned)
        return {"scanned": scanned, "duplicate_keys": 0,
                "rows_removed": 0, "applied": apply}

    logger.info("found %d duplicate key group(s) across %d rows",
                 len(dup_keys), sum(g["count"] for g in dup_keys))

    total_removed = 0
    for group in dup_keys:
        key_value = group["_id"]
        # Fetch full docs for this key so we can pick the newest.
        rows = await coll.find({"key": key_value}).to_list(length=None)
        rows.sort(key=_row_sort_key, reverse=True)
        keep, drop = rows[0], rows[1:]
        logger.info(
            "  key=%s  n=%d  keeping _id=%s  removing %d older row(s)",
            key_value, len(rows), keep.get("_id"), len(drop),
        )
        if apply and drop:
            ids_to_drop = [r["_id"] for r in drop]
            res = await coll.delete_many({"_id": {"$in": ids_to_drop}})
            total_removed += int(res.deleted_count or 0)

    return {"scanned": scanned, "duplicate_keys": len(dup_keys),
            "rows_removed": total_removed, "applied": apply}


async def _main(apply: bool) -> int:
    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME")
    if not mongo_url or not db_name:
        logger.error("MONGO_URL and DB_NAME must be set in backend/.env")
        return 2

    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]
    coll = db.distance_matrix_cache

    if apply:
        logger.info("APPLY mode — older duplicate rows will be DELETED")
    else:
        logger.info("DRY-RUN mode — no rows will be modified. "
                    "Pass --apply to actually delete duplicates.")

    summary = await dedup(coll, apply=apply)
    logger.info("done — %s", summary)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Dedup distance_matrix_cache before applying its "
                    "unique index (dmc_key_unique).",
    )
    parser.add_argument(
        "--apply", action="store_true",
        help="Actually delete older duplicate rows.  Omit for dry-run.",
    )
    args = parser.parse_args()
    return asyncio.run(_main(apply=args.apply))


if __name__ == "__main__":
    sys.exit(main())
