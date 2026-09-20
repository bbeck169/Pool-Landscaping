"""Phase T1.2 · Feb-2026 — one-time user-membership backfill.

For every user without a ``tenant_memberships`` list, seed a
single-item membership derived from their existing ``tenant_id`` +
``role``.  Idempotent — running twice does nothing on the second
pass.

Usage
-----
::

    python -m scripts.backfill_user_memberships
    python -m scripts.backfill_user_memberships --dry-run
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import datetime, timezone

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from dotenv import load_dotenv                                # noqa: E402
from motor.motor_asyncio import AsyncIOMotorClient            # noqa: E402

load_dotenv(os.path.join(_ROOT, ".env"))


async def _run(args: argparse.Namespace) -> None:
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]

    cursor = db.users.find(
        {"tenant_memberships": {"$in": [None, []]}},
        {"_id": 0, "id": 1, "tenant_id": 1, "role": 1,
         "created_at": 1},
    )
    seeded, skipped = 0, 0
    async for u in cursor:
        if not u.get("tenant_id"):
            skipped += 1
            continue
        membership = {
            "tenant_id":  u["tenant_id"],
            "role":       u.get("role", "customer"),
            "joined_at":  u.get("created_at") or
                            datetime.now(timezone.utc).isoformat(),
        }
        if args.dry_run:
            seeded += 1
            continue
        await db.users.update_one(
            {"id": u["id"]},
            {"$set": {"tenant_memberships": [membership]}},
        )
        seeded += 1

    # Second pass — users with an existing memberships array stay
    # untouched. Print a friendly summary.
    already = await db.users.count_documents(
        {"tenant_memberships": {"$exists": True,
                                  "$not": {"$size": 0}}},
    )
    print(f"[backfill] seeded={seeded} skipped_no_tenant={skipped} "
          f"already_multi={already} dry_run={args.dry_run}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    asyncio.run(_run(parser.parse_args()))


if __name__ == "__main__":
    main()
