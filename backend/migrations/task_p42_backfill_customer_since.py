"""Feb-2026 · P42 — Backfill ``customer_since`` for existing customers.

Idempotent, safe to re-run. Dry-run by default; pass ``--commit`` to
write.

For every ACTIVE customer without ``customer_since``, find their
earliest job's ``created_at`` and stamp ``customer_since`` = that
timestamp. Customers without jobs are left untouched (they haven't
crossed the P42 "converted" threshold yet). Inactive customers are
skipped entirely — the field only stamps on the first crossing of
BOTH active + ≥1 job, and rows that were archived before ever having
a job never should have been counted as converted.

Usage:
    python /app/backend/migrations/task_p42_backfill_customer_since.py
    python /app/backend/migrations/task_p42_backfill_customer_since.py --commit
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from datetime import datetime, timezone  # noqa: E402

from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402
from dotenv import dotenv_values  # noqa: E402


_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")


async def run(commit: bool = False) -> dict:
    client = AsyncIOMotorClient(_ENV["MONGO_URL"])
    db = client[_ENV["DB_NAME"]]
    now_iso = datetime.now(timezone.utc).isoformat()

    # Pull every customer that is (a) active AND (b) doesn't already
    # have a ``customer_since`` value. Missing ``is_active`` on legacy
    # rows means active, matching the runtime default.
    cursor = db.customers.find({
        "$and": [
            {"$or": [{"is_active": True},
                        {"is_active": {"$exists": False}}]},
            {"$or": [{"customer_since": None},
                        {"customer_since": {"$exists": False}}]},
            # Preserve soft-delete semantics — deleted rows aren't
            # candidates for backfill.
            {"$or": [{"deleted_at": None},
                        {"deleted_at": {"$exists": False}}]},
        ],
    }, {"_id": 0, "id": 1, "tenant_id": 1})

    stamped = 0
    skipped_no_jobs = 0
    scanned = 0
    async for c in cursor:
        scanned += 1
        cid = c["id"]
        tid = c["tenant_id"]
        earliest = await db.jobs.find({
            "customer_id": cid, "tenant_id": tid,
            "$or": [{"deleted_at": None},
                        {"deleted_at": {"$exists": False}}],
        }, {"_id": 0, "created_at": 1}).sort("created_at", 1).limit(1).to_list(1)
        if not earliest:
            skipped_no_jobs += 1
            continue
        stamp = earliest[0].get("created_at") or now_iso
        if commit:
            r = await db.customers.update_one(
                # Preserve immutability under a race — only write if
                # the field is still blank.
                {"id": cid, "tenant_id": tid,
                  "$or": [{"customer_since": None},
                              {"customer_since": {"$exists": False}}]},
                {"$set": {"customer_since": stamp}},
            )
            if r.modified_count:
                stamped += 1
        else:
            stamped += 1

    summary = {
        "scanned": scanned,
        "stamped": stamped,
        "skipped_no_jobs": skipped_no_jobs,
        "committed": commit,
    }
    print(summary)
    client.close()
    return summary


if __name__ == "__main__":
    commit = "--commit" in sys.argv
    asyncio.run(run(commit=commit))
