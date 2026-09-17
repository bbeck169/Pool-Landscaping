"""Feb-2026 · Global Custom Color Picker · idempotent recent_colors backfill.

Adds an empty ``recent_colors: []`` array to every user row that
doesn't already have the field. Idempotent (a second run does zero
writes). NOT auto-run at boot — ops invokes it manually.

Usage:
    python -m services.migrations.users_recent_colors_defaults
"""
from __future__ import annotations

import asyncio
import logging
import os

from motor.motor_asyncio import AsyncIOMotorClient


log = logging.getLogger("migrations.users_recent_colors")


async def backfill(db) -> dict:
    res = await db.users.update_many(
        {"recent_colors": {"$exists": False}},
        {"$set": {"recent_colors": []}},
    )
    log.info(
        "[users_recent_colors.backfill] users_updated=%d",
        res.modified_count,
    )
    return {"users_updated": res.modified_count}


async def _main() -> None:
    url = os.environ["MONGO_URL"]
    name = os.environ["DB_NAME"]
    client = AsyncIOMotorClient(url)
    try:
        result = await backfill(client[name])
        print(result)
    finally:
        client.close()


if __name__ == "__main__":  # pragma: no cover
    asyncio.run(_main())
