"""Feb-2026 · Ticket #3 + #4 · Idempotent default-block migration.

Backfills ``tenants.settings.notifications.*`` and ``tenants.settings.
ai.*`` for tenants that pre-date the tickets. Every field defaults to
the ticket-locked value (all notifications ON, both AI toggles ON,
persona_name unset so the FE fallback kicks in).

Idempotent: a second run backfills zero rows. Safe to invoke ad hoc
from an ops shell; NOT auto-run at boot.

Usage:
    python -m services.migrations.ticket3_ticket4_org_settings_defaults
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Dict

from motor.motor_asyncio import AsyncIOMotorClient


log = logging.getLogger("migrations.ticket3_ticket4")

NOTIFICATION_KEYS = (
    "lead_confirmation",
    "tech_on_my_way",
    "job_completion_summary",
    "warranty_expiration",
)


def _default_notifications() -> Dict[str, bool]:
    return {k: True for k in NOTIFICATION_KEYS}


def _default_ai() -> Dict[str, Any]:
    return {"kb_uploads_enabled": True, "analytics_enabled": True}


async def backfill(db) -> Dict[str, int]:
    """Set missing defaults on every tenant row. Uses per-key
    ``$exists: false`` guards so pre-existing custom values are
    never overwritten."""
    notif_updated = 0
    ai_updated = 0

    # Notifications block — one $set per missing key so partial
    # pre-existing blocks are preserved.
    for k, default in _default_notifications().items():
        path = f"settings.notifications.{k}"
        res = await db.tenants.update_many(
            {path: {"$exists": False}},
            {"$set": {path: default}},
        )
        notif_updated += res.modified_count

    # AI block — same per-key strategy. Persona_name is deliberately
    # NOT seeded (FE fallback resolves it at read time).
    for k, default in _default_ai().items():
        path = f"settings.ai.{k}"
        res = await db.tenants.update_many(
            {path: {"$exists": False}},
            {"$set": {path: default}},
        )
        ai_updated += res.modified_count

    log.info(
        "[ticket3_ticket4.backfill] notifications=%d ai=%d",
        notif_updated, ai_updated,
    )
    return {"notifications_updated": notif_updated,
            "ai_updated": ai_updated}


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
