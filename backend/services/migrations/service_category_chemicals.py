"""Feb-2026 · Backlog #1 Part 2 — Canonical "Chemicals" service
category enforcement.

Idempotent + sentinel-guarded. Two responsibilities:

  1. Ensure every onboarded tenant has a "Chemicals" service_category
     (lower-case-insensitive against user-defined equivalents like
     "Pool Chemicals" — those satisfy the invariant and are left
     alone).
  2. Backfill pricebook items where Taxonomy-A ``category ~ chemical``
     but ``service_category_id`` is null/missing → link to the
     tenant's "Chemicals" service_category.

The taxonomy separation is intentional:
  * Taxonomy A (``items.category``) is the item-type string
    ("Service", "Part", "chemical", …). Free-form.
  * Taxonomy B (``service_categories`` collection +
    ``items.service_category_id``) drives the "Income by Service
    Category" dashboard tile.

Sentinel: ``service_category_chemicals_v1``.

Onboarded tenants are those with any existing ``service_categories``
row (avoids touching tenants that haven't been seeded yet — those
get "Chemicals" auto-seeded via
``routers.service_categories.ensure_defaults_for_tenant`` on first
access).
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from config import db
from utils import now_iso


logger = logging.getLogger("service_category_chemicals_migration")


_SENTINEL_ID = "service_category_chemicals_v1"


async def _sentinel_row() -> Optional[Dict[str, Any]]:
    return await db.migrations.find_one({"id": _SENTINEL_ID}, {"_id": 0})


async def _write_sentinel(summary: Dict[str, Any]) -> None:
    await db.migrations.update_one(
        {"id": _SENTINEL_ID},
        {"$set": {
            "id": _SENTINEL_ID,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "summary": summary,
        }},
        upsert=True,
    )


def _auto_color(name: str) -> str:
    """Match the color helper used by ``routers.service_categories``
    so the migration-seeded row is visually consistent with the
    user-seeded rows.
    """
    import hashlib, colorsys
    h = int(hashlib.sha256(name.encode("utf-8")).hexdigest()[:8], 16)
    hue = (h % 360) / 360.0
    r, g, b = colorsys.hls_to_rgb(hue, 0.55, 0.65)
    return "#" + "".join(f"{int(round(x * 255)):02x}" for x in (r, g, b))


async def _ensure_chemicals_for_tenant(
    tenant_id: str,
) -> Optional[str]:
    """Return the tenant's Chemicals service_category id, seeding one
    if absent. Case-insensitive against ``^chemical`` so a pre-existing
    "Pool Chemicals" satisfies the invariant.
    """
    existing = await db.service_categories.find_one(
        {"tenant_id": tenant_id,
          "name": {"$regex": r"^\s*chemical", "$options": "i"},
          "$or": [{"is_archived": False},
                   {"is_archived": {"$exists": False}}]},
        {"_id": 0, "id": 1},
    )
    if existing:
        return existing["id"]
    max_row = await db.service_categories.find_one(
        {"tenant_id": tenant_id},
        {"_id": 0, "sort_order": 1},
        sort=[("sort_order", -1)],
    )
    next_sort = int((max_row or {}).get("sort_order") or 0) + 1
    new_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    await db.service_categories.insert_one({
        "id": new_id,
        "name": "Chemicals",
        "description": "System-managed. Auto-linked to pricebook "
                          "chemicals for revenue attribution.",
        "color": _auto_color("Chemicals"),
        "is_archived": False,
        "sort_order": next_sort,
        "tenant_id": tenant_id,
        "created_at": now,
        "created_by_user_id": "system:migration",
        "updated_at": now,
    })
    return new_id


async def run_service_category_chemicals_migration(
    *, force: bool = False,
) -> Dict[str, Any]:
    """Full-fleet migration entry point.

    ``force=True`` bypasses the sentinel — used by the super_admin
    admin endpoint for on-demand re-runs. Idempotent: seeds only
    when no case-insensitive "chemical*" row exists per tenant, and
    only backfills items missing ``service_category_id``.
    """
    if not force:
        sentinel = await _sentinel_row()
        if sentinel:
            logger.info(
                "[service_category_chemicals] sentinel present · skipping",
            )
            return {
                "status": "skipped",
                "reason": "sentinel_present",
                "sentinel": sentinel,
            }

    # Onboarded tenants only — those with >= 1 service_categories row.
    onboarded_tenants: List[str] = [
        t for t in await db.service_categories.distinct("tenant_id") if t
    ]
    scanned_tenants = 0
    created_categories = 0
    linked_items = 0
    already_linked = 0
    errors: List[Dict[str, Any]] = []
    per_tenant: List[Dict[str, Any]] = []

    for tid in onboarded_tenants:
        scanned_tenants += 1
        try:
            pre_exists = await db.service_categories.find_one(
                {"tenant_id": tid,
                  "name": {"$regex": r"^\s*chemical", "$options": "i"}},
                {"_id": 0, "id": 1},
            )
            chem_id = await _ensure_chemicals_for_tenant(tid)
            if not pre_exists and chem_id:
                created_categories += 1

            # Backfill items — Taxonomy A ``category ~ chemical`` AND
            # missing ``service_category_id``.
            r = await db.items.update_many(
                {"tenant_id": tid,
                  "category": {"$regex": r"^\s*chemical", "$options": "i"},
                  "$or": [
                    {"service_category_id": {"$exists": False}},
                    {"service_category_id": None},
                    {"service_category_id": ""},
                  ]},
                {"$set": {
                    "service_category_id": chem_id,
                    "service_category_backfilled_at": now_iso(),
                }},
            )
            linked_items += r.modified_count

            # Also count items already linked correctly (for audit).
            already = await db.items.count_documents({
                "tenant_id": tid,
                "category": {"$regex": r"^\s*chemical", "$options": "i"},
                "service_category_id": chem_id,
            })
            already_linked += max(0, already - r.modified_count)

            per_tenant.append({
                "tenant_id": tid,
                "chemicals_service_category_id": chem_id,
                "created_new": not bool(pre_exists),
                "items_linked_now": r.modified_count,
            })
        except Exception as exc:                                # noqa: BLE001
            errors.append({"tenant_id": tid, "error": str(exc)})
            logger.warning(
                f"[service_category_chemicals] tenant={tid} failed: {exc}",
            )

    summary = {
        "scanned_tenants": scanned_tenants,
        "created_categories": created_categories,
        "linked_items": linked_items,
        "already_linked": already_linked,
        "errors_count": len(errors),
        "errors": errors,
        "per_tenant": per_tenant,
    }
    await _write_sentinel(summary)
    logger.info(
        f"[service_category_chemicals] scanned_tenants={scanned_tenants} "
        f"created_categories={created_categories} linked_items={linked_items} "
        f"already_linked={already_linked} errors={len(errors)}",
    )
    return {"status": "ok", "summary": summary}
