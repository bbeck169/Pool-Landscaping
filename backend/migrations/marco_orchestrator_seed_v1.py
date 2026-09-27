"""Feb-2026 · MARCO orchestrator seed + backfill migration.

Companion to the additive MARCO rebrand (Option Z · Sub-phase A).
Ensures every existing tenant has a MARCO row in ``ai_employees``
AND that every legacy ``ai_employees`` doc carries the new
``orchestrator: bool`` field with the right posture:

  * MARCO rows                  → ``orchestrator=True``
  * All other seeded personas   → ``orchestrator=False``

Why a separate migration when ``seed_ai_employees_all_tenants``
already runs on boot and seeds MARCO?
─────────────────────────────────────────────────────────────
The boot seeder handles NEW rows + a few field backfills already,
but shipping a sentinel-gated migration:

  1. Records completion in ``migration_status`` so
     ``/api/health.init.structural_migrations.marco_orchestrator_seed_v1``
     surfaces the run status for ops.
  2. Guarantees the ``orchestrator`` field is present on EVERY
     row (not just MARCO) so downstream filters can rely on the
     schema without needing ``{"orchestrator": {"$exists": True}}``
     shims.
  3. Gives us a rollback pivot (see below) that doesn't require
     restoring from a snapshot.

Rollback
────────
This migration is a schema-normalization pass on the
``ai_employees`` collection.  A safe rollback un-does exactly
three effects:

  * MARCO rows can be deleted per-tenant:
      ``db.ai_employees.delete_many({"key": "marco_executive"})``
  * The ``orchestrator`` field can be scrubbed:
      ``db.ai_employees.update_many({}, {"$unset": {"orchestrator": ""}})``
  * The sentinel clear:
      ``db.migration_status.delete_one({"key": MIGRATION_KEY})``

The migration is idempotent, so replaying after a sentinel clear
is safe (no duplicate MARCO rows because the seeder short-circuits
on ``{"tenant_id": ..., "key": "marco_executive"}`` uniqueness).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict

logger = logging.getLogger(
    "services.migrations.marco_orchestrator_seed_v1",
)

MIGRATION_KEY = "marco_orchestrator_seed_v1"


async def run(db: Any) -> Dict[str, Any]:
    """Sentinel-gated one-shot backfill.

    Args:
        db: Motor async database handle.

    Returns:
        Migration report dict::

            {
                "ok": bool,
                "skipped": bool,
                "reason": str | absent,
                "tenants_scanned": int,
                "marco_inserted": int,
                "orchestrator_field_added": int,
                "marco_orchestrator_repaired": int,
                "error": str | absent,
            }
    """
    sentinel = await db.migration_status.find_one(
        {"key": MIGRATION_KEY}, {"_id": 0},
    )
    if sentinel and sentinel.get("completed_at"):
        return {
            "ok": True, "skipped": True, "reason": "already_ran",
        }

    # ── Pass 1 · Per-tenant MARCO seed ────────────────────────────
    # Route through the canonical ``seed_ai_employees_for_tenant``
    # so we reuse its idempotency + field-completeness logic.  This
    # is a one-way import (routers → migrations is NOT permitted;
    # migrations → routers IS the standing pattern for one-shot
    # seed passes — see ``task_p18_seed_plofv_lead_alerts.py``).
    from routers.ai_employees import seed_ai_employees_for_tenant

    tenants_scanned = 0
    marco_inserted = 0
    async for t in db.tenants.find({}, {"_id": 0, "id": 1}):
        tenants_scanned += 1
        tid = t.get("id")
        if not tid:
            continue
        # Snapshot MARCO row presence BEFORE the seed so we can
        # accurately count the inserts this migration caused.
        pre = await db.ai_employees.find_one(
            {"tenant_id": tid, "key": "marco_executive"},
            {"_id": 0, "id": 1},
        )
        try:
            await seed_ai_employees_for_tenant(tid)
        except Exception as _seed_exc:                          # noqa: BLE001
            logger.warning(
                "[marco_orchestrator_seed_v1] per-tenant seed error "
                "tenant=%s: %s", tid, _seed_exc,
            )
            continue
        if not pre:
            post = await db.ai_employees.find_one(
                {"tenant_id": tid, "key": "marco_executive"},
                {"_id": 0, "id": 1},
            )
            if post:
                marco_inserted += 1

    # ── Pass 2 · Backfill orchestrator field on every legacy row ─
    # The seed function only touches rows in ``DEFAULT_EMPLOYEES``;
    # a tenant admin may have created custom rows via the create
    # endpoint (or via legacy scripts) that don't carry the new
    # field.  Default them to ``orchestrator=False`` so downstream
    # filters can query the field without existence shims.
    orchestrator_field_added = 0
    res = await db.ai_employees.update_many(
        {"orchestrator": {"$exists": False}},
        {"$set": {
            "orchestrator": False,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }},
    )
    orchestrator_field_added = int(
        getattr(res, "modified_count", 0) or 0,
    )

    # ── Pass 3 · Repair MARCO rows that lost orchestrator=True ────
    # Defensive.  If a legacy MARCO row (e.g. one seeded before
    # this migration existed) has ``orchestrator=False``, repair
    # to the canonical posture.  Custom user prompts / names on
    # the MARCO row are preserved — we only touch the flag.
    res2 = await db.ai_employees.update_many(
        {"key": "marco_executive",
         "$or": [{"orchestrator": False}, {"orchestrator": None}]},
        {"$set": {
            "orchestrator": True,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }},
    )
    marco_orchestrator_repaired = int(
        getattr(res2, "modified_count", 0) or 0,
    )

    # ── Sentinel stamp ────────────────────────────────────────────
    await db.migration_status.update_one(
        {"key": MIGRATION_KEY},
        {"$set": {
            "key": MIGRATION_KEY,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "tenants_scanned": tenants_scanned,
            "marco_inserted": marco_inserted,
            "orchestrator_field_added": orchestrator_field_added,
            "marco_orchestrator_repaired": marco_orchestrator_repaired,
            "must_succeed": False,
        },
         "$unset": {"error": "", "last_attempt_at": ""}},
        upsert=True,
    )
    logger.info(
        "[marco_orchestrator_seed_v1] complete — tenants=%s "
        "marco_inserted=%s orchestrator_field_added=%s "
        "marco_repaired=%s",
        tenants_scanned, marco_inserted, orchestrator_field_added,
        marco_orchestrator_repaired,
    )
    return {
        "ok": True, "skipped": False,
        "tenants_scanned": tenants_scanned,
        "marco_inserted": marco_inserted,
        "orchestrator_field_added": orchestrator_field_added,
        "marco_orchestrator_repaired": marco_orchestrator_repaired,
    }
