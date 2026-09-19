"""Feb-2026 · Proposal Analytics — per-tenant IP-salt backfill.

Idempotent one-shot migration that generates + writes
``settings.analytics.ip_salt`` on every ``tenants`` doc missing it.
The salt is 32 hex chars (16 random bytes) used to SHA-256 client
IPs at analytics ingest time so cross-tenant enumeration is
impossible and no raw IPs are ever stored.

Also exposed as an admin-only endpoint via
``routers/admin_migrations.py::analytics_ip_salt_backfill``.

CLI usage:
    python /app/backend/migrations/backfill_analytics_ip_salt.py
"""
from __future__ import annotations
import asyncio
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402
from dotenv import dotenv_values  # noqa: E402


async def backfill_analytics_ip_salt(db, *, dry_run: bool = False) -> dict:
    """Set a per-tenant IP salt on every tenant doc missing it.

    Returns ``{"matched": N, "modified": M, "dry_run": bool}``.
    Idempotent — re-running against a fully-migrated DB reports
    ``matched=0, modified=0``.
    """
    query = {
        "$or": [
            {"settings.analytics.ip_salt": {"$exists": False}},
            {"settings.analytics.ip_salt": None},
            {"settings.analytics.ip_salt": ""},
        ]
    }
    if dry_run:
        matched = await db.tenants.count_documents(query)
        return {"matched": matched, "modified": 0, "dry_run": True}

    # Real run — one tenant at a time so each gets an INDEPENDENT
    # cryptographic random. A bulk ``$set`` with a single generated
    # salt would defeat the whole point. Target by the physical
    # ``_id`` (not the app-level ``id``) so duplicate tenant rows
    # sharing the same ``id`` (a legacy data-integrity artifact seen
    # in dev pods) each get their own salt written instead of only
    # the first ``id`` match being patched repeatedly.
    matched = 0
    modified = 0
    async for row in db.tenants.find(query, {"_id": 1}):
        matched += 1
        salt = secrets.token_hex(16)  # 32 hex chars
        res = await db.tenants.update_one(
            {"_id": row["_id"]},
            {"$set": {"settings.analytics.ip_salt": salt}},
        )
        modified += int(res.modified_count or 0)
    return {"matched": matched, "modified": modified, "dry_run": False}


async def _cli() -> None:
    env = dotenv_values(str(Path(__file__).resolve().parents[1] / ".env"))
    mongo_url = env.get("MONGO_URL") or ""
    db_name = env.get("DB_NAME") or ""
    if not mongo_url or not db_name:
        print("MONGO_URL / DB_NAME missing from backend/.env", file=sys.stderr)
        sys.exit(2)
    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]
    print("== analytics ip_salt backfill · dry-run ==")
    dry = await backfill_analytics_ip_salt(db, dry_run=True)
    print(f"tenants needing salt: {dry['matched']}")
    if dry["matched"] == 0:
        print("Nothing to migrate — already idempotent.")
        return
    print("== analytics ip_salt backfill · real-run ==")
    real = await backfill_analytics_ip_salt(db, dry_run=False)
    print(f"matched={real['matched']}  modified={real['modified']}")
    print("Re-running dry to confirm idempotence...")
    dry2 = await backfill_analytics_ip_salt(db, dry_run=True)
    assert dry2["matched"] == 0, (
        f"post-run dry showed matched={dry2['matched']} — not idempotent!")
    print("Idempotent OK ✓")


if __name__ == "__main__":
    asyncio.run(_cli())
