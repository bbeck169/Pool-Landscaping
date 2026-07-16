"""Phase 50.A · Chemical Cost Seeding + Admin CRUD.

Endpoints (all admin+super_admin only):
    GET  /api/admin/chemical-costs                — list this tenant's chemical cost catalog
    PUT  /api/admin/chemical-costs/{slug}         — update one row's cost/unit
    POST /api/admin/chemical-costs/reseed          — idempotent re-seed of defaults

Storage collection `chemical_costs` (tenant-scoped, unique index on
(tenant_id, chemical_slug)):
    { id, tenant_id, chemical_slug, name, unit_kind, cost_per_unit_cents,
      updated_at, updated_by, created_at }

Also read by `routers/budgets.py::job_costing()` — replaces the previous
$5/unit fallback for materials cost. Backwards-compatible: budgets.py
was extended to look up the `chemical_slug` field.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from config import db, logger
from utils import get_current_user, new_id, now_iso, require_admin
from routers.tenants import get_current_tenant

router = APIRouter(tags=["chemical_costs"])


# Default chemical catalog per Phase 50.A brief. All costs in INTEGER cents.
DEFAULT_CHEMICAL_COSTS: List[Dict[str, Any]] = [
    {"chemical_slug": "chlorine_tabs",       "name": "Chlorine Tablets",   "unit_kind": "tab", "cost_per_unit_cents":   75},
    {"chemical_slug": "liquid_chlorine",     "name": "Liquid Chlorine",    "unit_kind": "gal", "cost_per_unit_cents":  450},
    {"chemical_slug": "muriatic_acid",       "name": "Muriatic Acid",      "unit_kind": "gal", "cost_per_unit_cents":  600},
    {"chemical_slug": "soda_ash",            "name": "Soda Ash",           "unit_kind": "lbs", "cost_per_unit_cents":  200},
    {"chemical_slug": "shock",               "name": "Shock (Cal-Hypo)",   "unit_kind": "lbs", "cost_per_unit_cents":  350},
    {"chemical_slug": "clarifier",           "name": "Clarifier",          "unit_kind": "oz",  "cost_per_unit_cents":   75},
    {"chemical_slug": "phosphate_remover",   "name": "Phosphate Remover",  "unit_kind": "oz",  "cost_per_unit_cents":  125},
    {"chemical_slug": "salt",                "name": "Salt (40lb bag)",    "unit_kind": "bag", "cost_per_unit_cents": 1200},
    {"chemical_slug": "enzymes",             "name": "Enzymes",            "unit_kind": "oz",  "cost_per_unit_cents":   90},
]


async def seed_chemical_costs() -> Dict[str, int]:
    """Idempotent — inserts missing rows for every tenant. Never overwrites
    an admin-adjusted price. Called from server.py background seed."""
    try:
        await db.chemical_costs.create_index(
            [("tenant_id", 1), ("chemical_slug", 1)], unique=True
        )
    except Exception:
        pass
    inserted = 0
    tenants = await db.tenants.find({}, {"_id": 0, "id": 1}).to_list(1000)
    for t in tenants:
        tid = t["id"]
        for row in DEFAULT_CHEMICAL_COSTS:
            existing = await db.chemical_costs.find_one(
                {"tenant_id": tid, "chemical_slug": row["chemical_slug"]},
                {"_id": 0, "id": 1},
            )
            if existing:
                continue
            doc = {
                "id": new_id(),
                "tenant_id": tid,
                "chemical_slug": row["chemical_slug"],
                "name": row["name"],
                "unit_kind": row["unit_kind"],
                "cost_per_unit_cents": int(row["cost_per_unit_cents"]),
                "updated_at": now_iso(),
                "updated_by": None,
                "created_at": now_iso(),
            }
            try:
                await db.chemical_costs.insert_one(doc)
                inserted += 1
            except Exception as e:
                logger.warning(f"chemical_costs seed skip: {e}")
    return {"inserted": inserted, "tenants": len(tenants)}


class ChemCostIn(BaseModel):
    cost_per_unit_cents: int = Field(ge=0)
    unit_kind: Optional[str] = None
    name: Optional[str] = None


@router.get("/admin/chemical-costs")
async def list_chemical_costs(user: dict = Depends(require_admin),
                                tenant: dict = Depends(get_current_tenant)):
    """List this tenant's chemical cost catalog, seeding missing defaults."""
    # Idempotent per-tenant seed on first read (protects against tenants
    # created after startup seed ran).
    rows = await db.chemical_costs.find(
        {"tenant_id": tenant["id"]}, {"_id": 0}
    ).to_list(200)
    have = {r.get("chemical_slug") for r in rows}
    added = False
    for d in DEFAULT_CHEMICAL_COSTS:
        if d["chemical_slug"] in have:
            continue
        try:
            await db.chemical_costs.insert_one({
                "id": new_id(),
                "tenant_id": tenant["id"],
                "chemical_slug": d["chemical_slug"],
                "name": d["name"],
                "unit_kind": d["unit_kind"],
                "cost_per_unit_cents": int(d["cost_per_unit_cents"]),
                "updated_at": now_iso(),
                "updated_by": None,
                "created_at": now_iso(),
            })
            added = True
        except Exception:
            pass
    if added:
        rows = await db.chemical_costs.find(
            {"tenant_id": tenant["id"]}, {"_id": 0}
        ).to_list(200)
    rows.sort(key=lambda r: r.get("name") or "")
    return {"items": rows, "count": len(rows)}


@router.put("/admin/chemical-costs/{slug}")
async def update_chemical_cost(slug: str, body: ChemCostIn,
                                 user: dict = Depends(require_admin),
                                 tenant: dict = Depends(get_current_tenant)):
    updates: Dict[str, Any] = {
        "cost_per_unit_cents": int(body.cost_per_unit_cents),
        "updated_at": now_iso(),
        "updated_by": user["id"],
    }
    if body.unit_kind:
        updates["unit_kind"] = body.unit_kind
    if body.name:
        updates["name"] = body.name

    existing = await db.chemical_costs.find_one(
        {"tenant_id": tenant["id"], "chemical_slug": slug}, {"_id": 0}
    )
    if not existing:
        # Auto-create if the slug matches a default entry.
        default = next((d for d in DEFAULT_CHEMICAL_COSTS
                          if d["chemical_slug"] == slug), None)
        if not default:
            raise HTTPException(404, "unknown chemical_slug")
        doc = {
            "id": new_id(),
            "tenant_id": tenant["id"],
            "chemical_slug": slug,
            "name": updates.get("name") or default["name"],
            "unit_kind": updates.get("unit_kind") or default["unit_kind"],
            "cost_per_unit_cents": updates["cost_per_unit_cents"],
            "updated_at": updates["updated_at"],
            "updated_by": user["id"],
            "created_at": now_iso(),
        }
        await db.chemical_costs.insert_one(doc)
        doc.pop("_id", None)
        return doc

    await db.chemical_costs.update_one(
        {"tenant_id": tenant["id"], "chemical_slug": slug},
        {"$set": updates},
    )
    return await db.chemical_costs.find_one(
        {"tenant_id": tenant["id"], "chemical_slug": slug}, {"_id": 0}
    )


@router.post("/admin/chemical-costs/reseed")
async def reseed_chemical_costs(user: dict = Depends(require_admin),
                                  tenant: dict = Depends(get_current_tenant)):
    """Insert any missing default rows for THIS tenant only. Does NOT
    reset admin-adjusted prices — insert-only semantics."""
    rows = await db.chemical_costs.find(
        {"tenant_id": tenant["id"]}, {"_id": 0, "chemical_slug": 1}
    ).to_list(200)
    have = {r["chemical_slug"] for r in rows}
    inserted = 0
    for d in DEFAULT_CHEMICAL_COSTS:
        if d["chemical_slug"] in have:
            continue
        try:
            await db.chemical_costs.insert_one({
                "id": new_id(),
                "tenant_id": tenant["id"],
                "chemical_slug": d["chemical_slug"],
                "name": d["name"],
                "unit_kind": d["unit_kind"],
                "cost_per_unit_cents": int(d["cost_per_unit_cents"]),
                "updated_at": now_iso(),
                "updated_by": user["id"],
                "created_at": now_iso(),
            })
            inserted += 1
        except Exception:
            pass
    return {"inserted": inserted}


# ── Lookup helper (used by budgets.py job_costing) ─────────────────────
async def lookup_costs_by_slug(tenant_id: str) -> Dict[str, Dict[str, Any]]:
    """Return `{slug: {cost_per_unit_cents, unit_kind, name}}` plus
    per-name lookups for fuzzy matching (legacy service reports store
    chemical rows by human name)."""
    out: Dict[str, Dict[str, Any]] = {}
    async for row in db.chemical_costs.find(
        {"tenant_id": tenant_id}, {"_id": 0}
    ):
        entry = {
            "cost_per_unit_cents": int(row.get("cost_per_unit_cents") or 0),
            "unit_kind": row.get("unit_kind"),
            "name": row.get("name"),
            "chemical_slug": row.get("chemical_slug"),
        }
        slug = str(row.get("chemical_slug") or "").lower()
        if slug:
            out[slug] = entry
        # Also index by lowercased name for fuzzy matches from
        # legacy chemicals_added rows.
        nm = str(row.get("name") or "").lower()
        if nm and nm not in out:
            out[nm] = entry
    return out
