"""Phase K79 · Feb-2026 — Backward-compat migration.

Every quote/estimate that pre-dates K79 must render the itemized
customer view (its author designed it that way). We opt in the new
grouped view only for docs birthed after K79 ships.

This migration:
    * Iterates ``db.quotes`` where ``customer_group_display`` is
      unset OR null (Mongo can't distinguish "missing key" from
      "explicit null" without an ``$exists`` filter — we use both).
    * Sets ``customer_group_display=false`` on those docs.
    * Idempotent — re-running finds zero matches and exits clean.
    * Writes a single ``migration_runs`` audit doc with the count.

Run:
    python /app/backend/scripts/k79_customer_group_display_migration.py

Skips docs that already carry an explicit ``true``/``false`` value
(operator-set or previously migrated).
"""
from __future__ import annotations

import asyncio
import os
import sys
import uuid
from datetime import datetime, timezone

# Ensure backend module resolution when invoked from /app.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import db  # noqa: E402


MIGRATION_KEY = "k79_customer_group_display_default_false"


async def run() -> dict:
    filt = {
        "$or": [
            {"customer_group_display": {"$exists": False}},
            {"customer_group_display": None},
        ],
    }
    to_update = await db.quotes.count_documents(filt)
    if to_update == 0:
        audit = {
            "id": str(uuid.uuid4()),
            "migration": MIGRATION_KEY,
            "matched": 0,
            "modified": 0,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "status": "noop",
        }
        await db.migration_runs.insert_one(dict(audit))
        audit.pop("_id", None)
        return audit

    started = datetime.now(timezone.utc).isoformat()
    res = await db.quotes.update_many(
        filt,
        {"$set": {"customer_group_display": False}},
    )
    finished = datetime.now(timezone.utc).isoformat()
    audit = {
        "id": str(uuid.uuid4()),
        "migration": MIGRATION_KEY,
        "matched": to_update,
        "modified": res.modified_count,
        "started_at": started,
        "finished_at": finished,
        "status": "ok",
    }
    await db.migration_runs.insert_one(dict(audit))
    audit.pop("_id", None)
    return audit


def main() -> None:
    result = asyncio.get_event_loop().run_until_complete(run())
    print("[k79-migration]", result)


if __name__ == "__main__":
    main()
