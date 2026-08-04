"""Phase 50 · Feb-2026 — Idempotent AI-employee activation backfill.

Flips any ``ai_employees`` row with ``active in [false, null, missing]``
to ``active=true``. Idempotent: a second run flips zero rows.

Usage::

    python3 backend/scripts/phase50_activate_ai_employees.py

Also importable as an async helper for CI / smoke-tests.
"""
from __future__ import annotations

import asyncio
import os
import sys


async def activate_all_ai_employees(db) -> int:
    """Flip any not-yet-active AI employee row to active. Returns the
    count of rows modified (0 on the idempotent second run)."""
    r = await db.ai_employees.update_many(
        {"$or": [{"active": {"$ne": True}}, {"active": {"$exists": False}}]},
        {"$set": {"active": True}},
    )
    return int(r.modified_count)


async def _run() -> int:
    from motor.motor_asyncio import AsyncIOMotorClient
    mongo_url = os.environ["MONGO_URL"]
    db_name = os.environ["DB_NAME"]
    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]
    n = await activate_all_ai_employees(db)
    print(f"[phase50] flipped {n} ai_employees row(s) to active=True")
    return n


if __name__ == "__main__":
    sys.exit(0 if asyncio.run(_run()) >= 0 else 1)
