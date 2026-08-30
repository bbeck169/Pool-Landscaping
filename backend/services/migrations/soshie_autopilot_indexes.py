"""Phase S1.5 · Feb-2026 — indexes for the autopilot collections.

Adds:

* ``soshie_autopilot_config`` — unique on
  ``(tenant_id, platform)`` so per-tenant seeding is idempotent
  and the update-config PATCH endpoint can upsert safely.
* ``soshie_ai_generated_media`` — ``(tenant_id, generated_at)``
  compound for the "recent AI media" library view + a lookup on
  ``action_id`` so the autopilot tick can find the last-generated
  image for a given action row.

Idempotent — writes a sentinel row on ``migrations`` so subsequent
boots short-circuit.
"""
from __future__ import annotations

from config import db, logger
from utils import now_iso


MIGRATION_ID = "soshie_autopilot_indexes_v1"


async def ensure_indexes() -> None:
    sentinel = await db.migrations.find_one({"id": MIGRATION_ID})
    if sentinel:
        logger.info(f"[{MIGRATION_ID}] sentinel present · skipping")
        return
    try:
        await db.soshie_autopilot_config.create_index(
            [("tenant_id", 1), ("platform", 1)],
            name="soshie_autopilot_config_uniq",
            unique=True,
        )
        await db.soshie_autopilot_config.create_index(
            [("enabled", 1)],
            name="soshie_autopilot_config_by_enabled",
        )
        await db.soshie_ai_generated_media.create_index(
            [("tenant_id", 1), ("generated_at", -1)],
            name="soshie_ai_media_by_tenant_gen",
        )
        await db.soshie_ai_generated_media.create_index(
            [("action_id", 1)],
            name="soshie_ai_media_by_action",
        )
        await db.migrations.insert_one({
            "id": MIGRATION_ID, "applied_at": now_iso(),
        })
        logger.info(f"[{MIGRATION_ID}] indexes created + sentinel written")
    except Exception as exc:                                    # noqa: BLE001
        logger.warning(f"[{MIGRATION_ID}] index bootstrap skipped: {exc}")
