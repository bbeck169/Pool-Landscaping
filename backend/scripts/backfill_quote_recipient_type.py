"""Phase 2 · Feb-2026 · Quote-to-Lead Recipient — backfill (dry-run)."""
from __future__ import annotations
import argparse, asyncio, os, sys
from pathlib import Path

try:
    from dotenv import dotenv_values
except Exception:
    dotenv_values = None
from motor.motor_asyncio import AsyncIOMotorClient


def _load_env() -> dict:
    env_path = Path(__file__).resolve().parents[1] / ".env"
    if dotenv_values is None:
        return {"MONGO_URL": os.environ["MONGO_URL"], "DB_NAME": os.environ["DB_NAME"]}
    raw = dotenv_values(env_path) or {}
    return {k: (v.strip().strip('"').strip("'") if isinstance(v, str) else v)
            for k, v in raw.items()}


async def _run(apply: bool) -> int:
    env = _load_env()
    cl = AsyncIOMotorClient(env["MONGO_URL"])
    db = cl[env["DB_NAME"]]
    target_filter = {"$or": [
        {"recipient_type": {"$exists": False}},
        {"recipient_type": None},
        {"recipient_type": ""},
    ]}
    pipeline = [
        {"$match": target_filter},
        {"$group": {
            "_id": "$tenant_id",
            "with_customer_id":
                {"$sum": {"$cond": [{"$ifNull": ["$customer_id", False]}, 1, 0]}},
            "orphan_no_customer":
                {"$sum": {"$cond": [{"$ifNull": ["$customer_id", False]}, 0, 1]}},
        }},
        {"$sort": {"_id": 1}},
    ]
    buckets = await db.quotes.aggregate(pipeline).to_list(10000)
    total_will_update = 0
    total_orphans = 0
    print("=" * 68)
    print("Phase 2 · Quote-to-Lead Recipient — backfill DRY-RUN")
    print(f"MONGO_URL={env.get('MONGO_URL')!r}  DB_NAME={env.get('DB_NAME')!r}")
    print(f"mode={'APPLY' if apply else 'DRY-RUN'}")
    print("-" * 68)
    for row in buckets:
        tid = row["_id"]
        will = int(row["with_customer_id"])
        orph = int(row["orphan_no_customer"])
        total_will_update += will
        total_orphans += orph
        print(f"  tenant={str(tid)!r:44s}  rows_to_update={will:>6d}  "
              f"orphan_no_customer_id={orph:>4d}")
    print("-" * 68)
    print(f"TOTAL rows_to_update   = {total_will_update}")
    print(f"TOTAL orphans_skipped  = {total_orphans}")
    print("=" * 68)
    if apply:
        res = await db.quotes.update_many(
            {"$and": [target_filter,
                       {"customer_id": {"$exists": True, "$nin": [None, ""]}}]},
            [{"$set": {"recipient_type": "customer",
                         "recipient_id": "$customer_id"}}],
        )
        print(f"APPLY: matched={res.matched_count} modified={res.modified_count}")
    cl.close()
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    return asyncio.run(_run(apply=args.apply))


if __name__ == "__main__":
    sys.exit(main())
