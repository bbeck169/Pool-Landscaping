"""Phase 56.18 — Backfill existing invoices with human-readable
`invoice_number` / `master_invoice_number` fields.

Idempotent: already-numbered docs are skipped. Ordering: `created_at`
ASC (fallback to `_id` when missing). Per-tenant, per-year sequence.
Never mutates `created_at` or any field other than the two number
fields. After assignment, bumps `invoice_number_sequences.next_seq`
to `max_assigned_this_year + 1` so future generation continues from
the right point.

Usage:
    python /app/backend/migrations/backfill_invoice_numbers.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402
from dotenv import dotenv_values  # noqa: E402
from datetime import datetime  # noqa: E402
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError  # noqa: E402


def _year_of(created_at: str, tz_name: str) -> int:
    try:
        tz = ZoneInfo(tz_name or "America/Phoenix")
    except ZoneInfoNotFoundError:
        tz = ZoneInfo("UTC")
    try:
        return datetime.fromisoformat(created_at).astimezone(tz).year
    except Exception:
        return datetime.now(tz).year


async def _backfill_collection(db, coll_name: str, prefix: str, field: str) -> dict:
    """Return {tenant_id: {"assigned": N, "skipped": M, "year_max": {...}}}."""
    results: dict = {}
    tenants = await db.tenants.find({}, {"_id": 0, "id": 1, "timezone": 1}).to_list(2000)
    for tenant in tenants:
        tid = tenant["id"]
        tz = tenant.get("timezone") or "America/Phoenix"
        cursor = db[coll_name].find(
            {"tenant_id": tid, "doc_type": {"$in": [None, "invoice"]}}
            if coll_name == "quotes"
            else {"tenant_id": tid},
            {"_id": 1, "id": 1, "created_at": 1, field: 1, "doc_type": 1},
        ).sort([("created_at", 1)])
        assigned = 0
        skipped = 0
        year_max: dict = {}  # year -> highest sequence assigned
        async for doc in cursor:
            # quotes coll holds both quotes and invoices — skip quotes.
            if coll_name == "quotes" and doc.get("doc_type") not in (None, "invoice"):
                skipped += 1
                continue
            if doc.get(field):
                skipped += 1
                # Track max already-assigned per year so we don't collide.
                try:
                    parts = doc[field].split("-")
                    if len(parts) == 3:
                        y = int(parts[1]); n = int(parts[2])
                        year_max[y] = max(year_max.get(y, 0), n)
                except Exception:
                    pass
                continue
            y = _year_of(doc.get("created_at") or "", tz)
            n = year_max.get(y, 0) + 1
            year_max[y] = n
            number = f"{prefix}-{y}-{n:06d}"
            await db[coll_name].update_one(
                {"_id": doc["_id"]}, {"$set": {field: number}}
            )
            assigned += 1

        # Reset counters so future generation continues correctly.
        for y, n in year_max.items():
            await db.invoice_number_sequences.update_one(
                {"tenant_id": tid, "year": y, "prefix": prefix},
                {"$max": {"next_seq": n}, "$setOnInsert": {}},
                upsert=True,
            )
        results[tid] = {"assigned": assigned, "skipped": skipped, "year_max": year_max}
    return results


async def main():
    env = dotenv_values("/app/backend/.env")
    client = AsyncIOMotorClient(env["MONGO_URL"])
    db = client[env["DB_NAME"]]

    # Ensure indexes first (partial + unique).
    sys.path.insert(0, "/app/backend")
    from services.invoice_numbering import ensure_uniqueness_indexes
    # Rebind config db in the service to this client for stand-alone run.
    import config
    config.db = db
    await ensure_uniqueness_indexes()

    print("=== Backfilling invoices (INV-YYYY-NNNNNN) ===")
    inv = await _backfill_collection(db, "quotes", "INV", "invoice_number")
    for tid, stats in inv.items():
        print(f"  tenant={tid}: assigned={stats['assigned']}, skipped={stats['skipped']}, "
              f"years={list(stats['year_max'].keys())}")

    print("=== Backfilling master invoices (MINV-YYYY-NNNNNN) ===")
    mi = await _backfill_collection(db, "master_invoices", "MINV", "master_invoice_number")
    for tid, stats in mi.items():
        print(f"  tenant={tid}: assigned={stats['assigned']}, skipped={stats['skipped']}, "
              f"years={list(stats['year_max'].keys())}")

    total_inv = sum(s["assigned"] for s in inv.values())
    total_mi = sum(s["assigned"] for s in mi.values())
    print(f"=== TOTAL: {total_inv} invoices + {total_mi} master invoices assigned ===")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
