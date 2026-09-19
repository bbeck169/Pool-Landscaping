"""Feb-2026 · Interactive Flipbook Estimate Viewer — backfill.

Idempotent one-shot migration that seeds ``flipbook_enabled=False``
and ``flipbook_background_ids=[]`` on every ``quotes`` doc that is
missing either field. Skips docs that already carry both fields so
re-running is safe (matches the invoice-number backfill convention).

Also exposed as an admin-only endpoint (see
``routers/admin_migrations.py::flipbook_backfill``) so ops can
trigger it against prod without a shell.

CLI usage:
    python /app/backend/migrations/backfill_flipbook_defaults.py

Prints a per-tenant summary and a final total.
"""
from __future__ import annotations
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402
from dotenv import dotenv_values  # noqa: E402


async def backfill_flipbook_defaults(db, *, dry_run: bool = False) -> dict:
    """Set defaults on any ``quotes`` doc missing either flipbook field.

    Returns ``{"matched": N, "modified": M, "tenants": {...}, "dry_run": bool}``.
    Idempotent — re-running against a fully-migrated DB reports
    ``matched=0, modified=0``.
    """
    query = {
        "$or": [
            {"flipbook_enabled": {"$exists": False}},
            {"flipbook_background_ids": {"$exists": False}},
        ]
    }
    if dry_run:
        matched = await db.quotes.count_documents(query)
        # Per-tenant breakdown for a preview.
        pipeline = [
            {"$match": query},
            {"$group": {"_id": "$tenant_id", "n": {"$sum": 1}}},
        ]
        by_tenant = {
            (doc.get("_id") or "<none>"): int(doc.get("n") or 0)
            async for doc in db.quotes.aggregate(pipeline)
        }
        return {"matched": matched, "modified": 0,
                 "tenants": by_tenant, "dry_run": True}
    # Real run — one collection-wide $set. ``flipbook_enabled=false``
    # and ``flipbook_background_ids=[]`` are the safe defaults for
    # every historical estimate (classic render mode).
    res = await db.quotes.update_many(
        query,
        {"$set": {
            "flipbook_enabled": False,
            "flipbook_background_ids": [],
        }},
    )
    return {"matched": int(res.matched_count),
             "modified": int(res.modified_count),
             "tenants": {}, "dry_run": False}


async def _cli() -> None:
    env = dotenv_values(str(Path(__file__).resolve().parents[1] / ".env"))
    mongo_url = env.get("MONGO_URL") or ""
    db_name = env.get("DB_NAME") or ""
    if not mongo_url or not db_name:
        print("MONGO_URL / DB_NAME missing from backend/.env", file=sys.stderr)
        sys.exit(2)
    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]
    print("== flipbook backfill · dry-run ==")
    dry = await backfill_flipbook_defaults(db, dry_run=True)
    print(f"quotes needing migration: {dry['matched']}")
    for tid, n in sorted(dry["tenants"].items(), key=lambda kv: -kv[1]):
        print(f"  tenant={tid!s:<40} n={n}")
    if dry["matched"] == 0:
        print("Nothing to migrate — already idempotent.")
        return
    print("== flipbook backfill · real-run ==")
    real = await backfill_flipbook_defaults(db, dry_run=False)
    print(f"matched={real['matched']}  modified={real['modified']}")
    print("Re-running dry to confirm idempotence...")
    dry2 = await backfill_flipbook_defaults(db, dry_run=True)
    assert dry2["matched"] == 0, (
        f"post-run dry showed matched={dry2['matched']} — not idempotent!")
    print("Idempotent OK ✓")


if __name__ == "__main__":
    asyncio.run(_cli())
