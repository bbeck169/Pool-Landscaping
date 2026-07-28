"""Task RR/SS Phase 2 follow-on · Feb 2026 — one-time backfill of
``avatar_url`` on every ``ai_employees`` doc across all tenants.

Idempotent — skips docs whose ``avatar_url`` already matches the
expected canonical value. Safe to re-run.

Usage
-----
    python /app/backend/scripts/backfill_persona_avatar_urls.py

Reports ``updated / skipped / errored / unknown_key`` counts.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

# Allow running from CLI without the project on PYTHONPATH.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

CANONICAL_KEYS = {
    "casey", "emmie", "buddy", "vizzy", "dexter",
    "soshie", "scouty", "commet", "skedra", "billy",
}


def expected_url(key: str) -> str:
    return f"/avatars/personas/{key}.jpg"


async def main() -> None:
    load_dotenv("/app/backend/.env")
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]

    updated = 0
    skipped = 0
    unknown_key = 0
    errored = 0
    total = 0

    cursor = db.ai_employees.find({}, {"_id": 0, "id": 1, "key": 1,
                                          "avatar_url": 1, "tenant_id": 1})
    async for doc in cursor:
        total += 1
        key = doc.get("key")
        if key not in CANONICAL_KEYS:
            unknown_key += 1
            continue
        want = expected_url(key)
        have = doc.get("avatar_url")
        if have == want:
            skipped += 1
            continue
        try:
            r = await db.ai_employees.update_one(
                {"id": doc["id"]}, {"$set": {"avatar_url": want}},
            )
            if r.modified_count == 1:
                updated += 1
            else:
                # matched=1, modified=0 shouldn't happen (we already
                # checked `have != want`), but be defensive.
                skipped += 1
        except Exception as e:                                                       # pragma: no cover
            errored += 1
            print(f"[error] tenant={doc.get('tenant_id')} key={key}: {e}")

    print("─" * 60)
    print(f"total docs scanned : {total}")
    print(f"updated            : {updated}")
    print(f"skipped (up-to-date): {skipped}")
    print(f"unknown persona key: {unknown_key}")
    print(f"errored            : {errored}")


if __name__ == "__main__":
    asyncio.run(main())
