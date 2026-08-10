"""Phase 56-a · Aug-2026 — Pricebook supplier seed migration.

Idempotent per-tenant seed of 13 default pricing suppliers (4 pool + 9
landscape). Runs once on server startup for each tenant that has ZERO
docs in ``pricebook_suppliers``. Never re-seeds — respects user deletes.

Slug 'epoolsupply' chosen to match the existing scraper 'suppliers'
collection convention (single-word compact). Multi-word slugs use
lower_snake_case (e.g. 'moon_valley_nursery', 'sprinkler_world') where
compact would be unreadable.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Dict, Any
import uuid

from config import db, logger


POOL_SEED = [
    {"slug": "scp",         "display_name": "SCP"},
    {"slug": "epoolsupply", "display_name": "ePoolSupply"},
    {"slug": "heritage",    "display_name": "Heritage"},
    {"slug": "pwp",         "display_name": "PWP"},
]
LANDSCAPE_SEED = [
    {"slug": "home_depot",           "display_name": "Home Depot"},
    {"slug": "horizon",              "display_name": "Horizon"},
    {"slug": "siteone",              "display_name": "SiteOne"},
    {"slug": "ewing",                "display_name": "Ewing"},
    {"slug": "apache_stone",         "display_name": "Apache Stone"},
    {"slug": "sprinkler_world",      "display_name": "Sprinkler World"},
    {"slug": "moon_valley_nursery",  "display_name": "Moon Valley Nursery"},
    {"slug": "dream_in_colors",      "display_name": "Dream in Colors"},
    {"slug": "az_wholesale",         "display_name": "AZ Wholesale"},
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _resolve_category_id(tenant_id: str, name: str) -> str | None:
    row = await db.income_categories.find_one(
        {"tenant_id": tenant_id, "name": name},
        {"_id": 0, "id": 1},
    )
    return row.get("id") if row else None


async def seed_pricebook_suppliers_for_tenant(tenant_id: str) -> int:
    """Insert the 13 seed rows for a tenant if the collection is empty
    for that tenant. Returns the number of rows inserted (0 if already
    seeded or user has since populated their own suppliers)."""
    existing = await db.pricebook_suppliers.count_documents(
        {"tenant_id": tenant_id},
    )
    if existing > 0:
        return 0

    pool_id = await _resolve_category_id(tenant_id, "Pool")
    landscape_id = await _resolve_category_id(tenant_id, "Landscaping")
    if not pool_id or not landscape_id:
        logger.warning(
            f"[pricebook_suppliers_seed] tenant={tenant_id[:8]} missing "
            f"Pool={bool(pool_id)} / Landscaping={bool(landscape_id)} "
            f"income_categories — skipping seed",
        )
        return 0

    now = _now_iso()
    docs: List[Dict[str, Any]] = []
    for row in POOL_SEED:
        docs.append({
            "id": str(uuid.uuid4()), "tenant_id": tenant_id,
            "slug": row["slug"], "display_name": row["display_name"],
            "income_category_id": pool_id,
            "is_active": True, "is_seed": True,
            "deleted_at": None, "created_at": now,
            "created_by_user_id": None,
        })
    for row in LANDSCAPE_SEED:
        docs.append({
            "id": str(uuid.uuid4()), "tenant_id": tenant_id,
            "slug": row["slug"], "display_name": row["display_name"],
            "income_category_id": landscape_id,
            "is_active": True, "is_seed": True,
            "deleted_at": None, "created_at": now,
            "created_by_user_id": None,
        })
    await db.pricebook_suppliers.insert_many(docs)
    logger.info(
        f"[pricebook_suppliers_seed] tenant={tenant_id[:8]} seeded "
        f"{len(docs)} rows (4 pool + 9 landscape)",
    )
    return len(docs)


async def seed_all_tenants() -> None:
    """Sweep every tenant on startup. Safe to call multiple times."""
    async for t in db.tenants.find({}, {"_id": 0, "id": 1}):
        try:
            await seed_pricebook_suppliers_for_tenant(t["id"])
        except Exception as e:                                    # noqa: BLE001
            logger.warning(
                f"[pricebook_suppliers_seed] tenant={t['id'][:8]} "
                f"seed failed: {e}",
            )
