"""Phase D1 · Feb 2026 — seed 16 new industry checklist templates.

Extends the MI1 seed set (7 industries) to 23 industries and
augments the ``pest_control`` template with two legally-critical
rows (EPA reg # + amount, re-entry time).

Idempotency
-----------
* Per-industry upsert keyed on ``(industry, is_default=True)`` —
  re-running the migration does NOT duplicate rows.
* Sentinel doc in ``db.migrations`` with
  ``id = phase_d1_industry_templates_v1`` — first successful run
  stamps the sentinel; subsequent runs short-circuit.
* Naturally rerunnable per-tenant: the seeder writes tenant-
  agnostic defaults only. Tenant overrides in
  ``tenant_checklist_overrides`` are untouched.

Invocation
----------
Callable from three places:

1. Boot-time via ``server.py`` alongside the existing MI1 seeder
   (the MI1 seeder already picks up the extended
   :data:`INDUSTRY_SLUGS` automatically — this dedicated migration
   is kept as an explicit, admin-invokable command for ops so a
   partial-migration crash can be re-driven without a full pod
   restart).
2. The migration admin endpoint (mirrors how ``seed_system_templates``
   is invoked — see ``services/migrations/seed_system_templates.py``).
3. Pytest for the ``test_phase_d_seeder_idempotent`` regression.
"""
from __future__ import annotations

from typing import Dict

from config import db, logger
from routers.industry_checklists import (
    DEFAULT_TEMPLATES, INDUSTRY_SLUGS,
)
from utils import new_id, now_iso


MIGRATION_ID = "phase_d1_industry_templates_v1"


async def run_phase_d1_industry_template_seed(*, force: bool = False) -> Dict[str, int]:
    """Idempotently upsert one ``industry_checklist_templates`` row
    per canonical industry.

    Parameters
    ----------
    force
        When True, ignore the sentinel and re-upsert every row. Used
        by ops when the underlying default template wording needs to
        be re-pushed to production.

    Returns
    -------
    dict
        ``{"upserted": N, "matched": M, "sentinel_stamped": bool}``.
        ``upserted`` = new inserts + template-body updates;
        ``matched`` = rows already at the target state.
    """
    if not force:
        sentinel = await db.migrations.find_one(
            {"id": MIGRATION_ID}, {"_id": 0, "id": 1},
        )
        if sentinel:
            logger.info(
                f"[phase-d1] sentinel {MIGRATION_ID} present — skipping"
            )
            return {"upserted": 0, "matched": 0, "sentinel_stamped": False,
                     "skipped": True}

    upserted = 0
    matched = 0
    for slug in INDUSTRY_SLUGS:
        items = DEFAULT_TEMPLATES.get(slug) or []
        if not items:
            logger.warning(f"[phase-d1] no items for slug={slug} — skipping")
            continue
        payload = {
            "industry": slug,
            "version": 1,
            "items": items,
            "is_default": True,
            "updated_at": now_iso(),
        }
        # Idempotency: upsert keyed on the (industry, is_default) pair
        # — the pre-Phase-D collection stored one default doc per
        # industry, so this collapses to a single canonical row per
        # slug regardless of how many boot cycles have executed.
        existing = await db.industry_checklist_templates.find_one(
            {"industry": slug, "is_default": True},
            {"_id": 0, "id": 1, "items": 1},
        )
        if existing:
            same = (existing.get("items") == items)
            await db.industry_checklist_templates.update_one(
                {"industry": slug, "is_default": True},
                {"$set": payload},
            )
            if same:
                matched += 1
            else:
                upserted += 1
        else:
            payload["id"] = new_id()
            await db.industry_checklist_templates.insert_one(payload)
            upserted += 1

    stamped = False
    try:
        await db.migrations.update_one(
            {"id": MIGRATION_ID},
            {"$set": {
                "id": MIGRATION_ID,
                "completed_at": now_iso(),
                "upserted": upserted,
                "matched": matched,
                "slug_count": len(INDUSTRY_SLUGS),
            }},
            upsert=True,
        )
        stamped = True
    except Exception as e:                                        # noqa: BLE001
        logger.warning(f"[phase-d1] sentinel stamp failed: {e}")
    logger.info(
        f"[phase-d1] industry template seed: upserted={upserted} "
        f"matched={matched} slugs={len(INDUSTRY_SLUGS)}"
    )
    return {
        "upserted": upserted, "matched": matched,
        "sentinel_stamped": stamped,
    }
