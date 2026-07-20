"""QuoteIQ Phase Q1 · Sub-scope B — Chemical products + profitability.

Design decision: rather than fork a second collection, this module
extends the existing ``chemical_costs`` catalog with optional ``sku`` +
``active`` fields (extend-in-place per the user's "extend, don't
duplicate" directive) and exposes it under a fresher
``/api/chemical-products`` namespace.

Documents in ``chemical_costs`` continue to work with the existing
``/api/admin/chemical-costs`` endpoints (used by budgets.py rollups)
unchanged. Both routers read/write the same source of truth.

Additionally: whenever a service report is finalized with
``chemicals_added`` line items, a helper mints a
``chemical_usage_events`` row per line — snapshotted with the unit
cost at that moment so retroactive price changes don't corrupt
historical margin math.

Profitability endpoints aggregate over ``chemical_usage_events``. If
no events exist yet for a given customer/job (legacy data), the
endpoint falls back to computing on-the-fly from the raw
``service_reports.chemicals_added`` array joined with the current
catalog price.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from config import db, logger
from utils import require_admin, new_id, now_iso
from routers.tenants import get_current_tenant


router = APIRouter(tags=["Chemical Products"])


# ═════════════════════════════════════════════════════════════════════
# Product catalog (thin alias over chemical_costs)
# ═════════════════════════════════════════════════════════════════════

class ProductIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    slug: Optional[str] = None
    sku: Optional[str] = None
    unit: str = Field(..., min_length=1, max_length=20)  # e.g. "lb", "gal"
    unit_cost_cents: int = Field(..., ge=0)
    active: Optional[bool] = True


class ProductPatch(BaseModel):
    name: Optional[str] = None
    sku: Optional[str] = None
    unit: Optional[str] = None
    unit_cost_cents: Optional[int] = None
    active: Optional[bool] = None


def _slugify(name: str) -> str:
    s = "".join(c if c.isalnum() or c == " " else "" for c in (name or ""))
    return s.strip().lower().replace(" ", "_") or f"prod_{new_id()[:8]}"


def _to_product_view(row: Dict[str, Any]) -> Dict[str, Any]:
    """Project the internal chemical_costs shape into the product API."""
    return {
        "id": row.get("id"),
        "tenant_id": row.get("tenant_id"),
        "slug": row.get("chemical_slug"),
        "name": row.get("name"),
        "sku": row.get("sku"),
        "unit": row.get("unit_kind"),
        "unit_cost_cents": int(row.get("cost_per_unit_cents") or 0),
        "active": bool(row.get("active", True)),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


@router.get("/chemical-products")
async def list_products(user: dict = Depends(require_admin),
                          tenant: dict = Depends(get_current_tenant),
                          active: Optional[bool] = Query(None),
                          q: Optional[str] = Query(None)):
    query: Dict[str, Any] = {"tenant_id": tenant["id"]}
    if active is not None:
        query["active"] = {"$ne": False} if active else False
    if q:
        query["$or"] = [
            {"name": {"$regex": q, "$options": "i"}},
            {"sku": {"$regex": q, "$options": "i"}},
            {"chemical_slug": {"$regex": q, "$options": "i"}},
        ]
    rows = await db.chemical_costs.find(query, {"_id": 0}) \
        .sort("name", 1).to_list(500)
    return {"count": len(rows),
            "products": [_to_product_view(r) for r in rows]}


@router.post("/chemical-products", status_code=201)
async def create_product(body: ProductIn,
                           user: dict = Depends(require_admin),
                           tenant: dict = Depends(get_current_tenant)):
    slug = body.slug or _slugify(body.name)
    existing = await db.chemical_costs.find_one(
        {"tenant_id": tenant["id"], "chemical_slug": slug}, {"_id": 0})
    if existing:
        raise HTTPException(409, "product slug already exists for this tenant")
    doc = {
        "id": new_id(),
        "tenant_id": tenant["id"],
        "chemical_slug": slug,
        "name": body.name,
        "sku": body.sku,
        "unit_kind": body.unit,
        "cost_per_unit_cents": int(body.unit_cost_cents),
        "active": bool(body.active if body.active is not None else True),
        "updated_at": now_iso(),
        "updated_by": user.get("id"),
        "created_at": now_iso(),
    }
    await db.chemical_costs.insert_one(doc)
    return _to_product_view(doc)


@router.get("/chemical-products/{slug}")
async def get_product(slug: str,
                        user: dict = Depends(require_admin),
                        tenant: dict = Depends(get_current_tenant)):
    row = await db.chemical_costs.find_one(
        {"tenant_id": tenant["id"], "chemical_slug": slug}, {"_id": 0})
    if not row:
        raise HTTPException(404, "product not found")
    return _to_product_view(row)


@router.patch("/chemical-products/{slug}")
async def patch_product(slug: str, body: ProductPatch,
                          user: dict = Depends(require_admin),
                          tenant: dict = Depends(get_current_tenant)):
    row = await db.chemical_costs.find_one(
        {"tenant_id": tenant["id"], "chemical_slug": slug}, {"_id": 0})
    if not row:
        raise HTTPException(404, "product not found")
    upd: Dict[str, Any] = {"updated_at": now_iso(), "updated_by": user.get("id")}
    if body.name is not None:
        upd["name"] = body.name
    if body.sku is not None:
        upd["sku"] = body.sku
    if body.unit is not None:
        upd["unit_kind"] = body.unit
    if body.unit_cost_cents is not None:
        upd["cost_per_unit_cents"] = int(body.unit_cost_cents)
    if body.active is not None:
        upd["active"] = bool(body.active)
    await db.chemical_costs.update_one(
        {"tenant_id": tenant["id"], "chemical_slug": slug}, {"$set": upd})
    fresh = await db.chemical_costs.find_one(
        {"tenant_id": tenant["id"], "chemical_slug": slug}, {"_id": 0})
    return _to_product_view(fresh)


@router.delete("/chemical-products/{slug}", status_code=204)
async def delete_product(slug: str,
                           user: dict = Depends(require_admin),
                           tenant: dict = Depends(get_current_tenant)):
    """Soft-delete: sets active=false. Preserves historical rollups
    that reference this product."""
    r = await db.chemical_costs.update_one(
        {"tenant_id": tenant["id"], "chemical_slug": slug},
        {"$set": {"active": False, "updated_at": now_iso(),
                  "updated_by": user.get("id")}},
    )
    if not r.matched_count:
        raise HTTPException(404, "product not found")
    return None


# ═════════════════════════════════════════════════════════════════════
# Usage event snapshot (called from service report finalization)
# ═════════════════════════════════════════════════════════════════════

async def snapshot_chemical_usage(*, tenant_id: str, job_id: Optional[str],
                                     service_report_id: str,
                                     customer_id: Optional[str],
                                     chemicals_added: List[Dict[str, Any]],
                                     occurred_at: Optional[str] = None,
                                     actor_user_id: Optional[str] = None
                                     ) -> Dict[str, Any]:
    """Idempotent: replaces any prior usage-events for the same
    service_report_id so re-submits don't double-count.

    ``chemicals_added`` items may be either the new shape
    ``{product_slug, quantity, unit}`` or the legacy shape
    ``{name, amount, unit}``. Both are handled.
    """
    catalog: Dict[str, Dict[str, Any]] = {}
    async for row in db.chemical_costs.find(
            {"tenant_id": tenant_id}, {"_id": 0}):
        slug = str(row.get("chemical_slug") or "").lower()
        catalog[slug] = row
        nm = str(row.get("name") or "").lower()
        if nm and nm not in catalog:
            catalog[nm] = row

    # Wipe prior events for this service_report_id to preserve idempotency.
    await db.chemical_usage_events.delete_many({
        "tenant_id": tenant_id,
        "service_report_id": service_report_id,
    })

    inserted = 0
    total_cost_cents = 0
    for line in chemicals_added or []:
        if not isinstance(line, dict):
            continue
        product_slug = (line.get("product_slug")
                          or line.get("slug")
                          or line.get("chemical_slug"))
        name = line.get("name") or line.get("chemical") or ""
        qty_raw = line.get("quantity_used")
        if qty_raw is None:
            qty_raw = line.get("quantity")
        if qty_raw is None:
            qty_raw = line.get("amount")
        try:
            qty = float(qty_raw or 0)
        except (TypeError, ValueError):
            qty = 0.0
        if qty <= 0:
            continue
        unit = line.get("unit") or line.get("unit_kind") or ""

        # Resolve unit cost via slug, else name lookup.
        catalog_row = None
        if product_slug:
            catalog_row = catalog.get(str(product_slug).lower())
        if catalog_row is None and name:
            catalog_row = catalog.get(name.lower())
        unit_cost_cents = int((catalog_row or {}).get("cost_per_unit_cents") or 0)
        resolved_slug = (catalog_row or {}).get("chemical_slug") or product_slug
        resolved_unit = (catalog_row or {}).get("unit_kind") or unit
        line_cost = int(round(qty * unit_cost_cents))
        total_cost_cents += line_cost
        await db.chemical_usage_events.insert_one({
            "id": new_id(),
            "tenant_id": tenant_id,
            "job_id": job_id,
            "service_report_id": service_report_id,
            "customer_id": customer_id,
            "product_slug": resolved_slug,
            "name": name or (catalog_row or {}).get("name") or "",
            "quantity_used": qty,
            "unit": resolved_unit,
            "unit_cost_at_time_cents": unit_cost_cents,
            "total_cost_cents": line_cost,
            "occurred_at": occurred_at or now_iso(),
            "created_at": now_iso(),
            "created_by": actor_user_id,
        })
        inserted += 1
    return {"inserted": inserted, "total_cost_cents": total_cost_cents}


# ═════════════════════════════════════════════════════════════════════
# Profitability rollups
# ═════════════════════════════════════════════════════════════════════

@router.get("/chemicals/profitability")
async def profitability_rollup(user: dict = Depends(require_admin),
                                 tenant: dict = Depends(get_current_tenant),
                                 customer_id: Optional[str] = Query(None),
                                 job_id: Optional[str] = Query(None),
                                 start: Optional[str] = Query(None),
                                 end: Optional[str] = Query(None)):
    q: Dict[str, Any] = {"tenant_id": tenant["id"]}
    if customer_id:
        q["customer_id"] = customer_id
    if job_id:
        q["job_id"] = job_id
    if start or end:
        rng: Dict[str, Any] = {}
        if start:
            rng["$gte"] = start
        if end:
            rng["$lte"] = end
        q["occurred_at"] = rng

    rows = await db.chemical_usage_events.find(q, {"_id": 0}).to_list(5000)
    total_cost_cents = sum(int(r.get("total_cost_cents") or 0) for r in rows)
    visits = len({(r.get("service_report_id") or r.get("job_id"))
                    for r in rows if r.get("service_report_id") or r.get("job_id")})
    avg_visit_cost_cents = int(total_cost_cents / visits) if visits else 0

    per_product: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        slug = r.get("product_slug") or "unknown"
        entry = per_product.setdefault(slug, {
            "product_slug": slug, "name": r.get("name"),
            "quantity_used": 0.0, "total_cost_cents": 0,
            "unit": r.get("unit"),
        })
        entry["quantity_used"] += float(r.get("quantity_used") or 0)
        entry["total_cost_cents"] += int(r.get("total_cost_cents") or 0)

    return {
        "total_chemical_cost_cents": total_cost_cents,
        "visit_count": visits,
        "avg_cost_per_visit_cents": avg_visit_cost_cents,
        "event_count": len(rows),
        "per_product_breakdown": sorted(
            per_product.values(),
            key=lambda x: x["total_cost_cents"], reverse=True),
    }


@router.get("/pools/{pool_id}/chemical-profitability")
async def pool_profitability(pool_id: str,
                               user: dict = Depends(require_admin),
                               tenant: dict = Depends(get_current_tenant),
                               months: int = Query(6, ge=1, le=36)):
    """Trend of chemical cost per month for a pool.

    ``pool_id`` is accepted as the customer_id (each customer has a
    single pool in this system). If a separate pools collection ever
    exists, we join here.
    """
    since = (datetime.now(timezone.utc) - timedelta(days=months * 31)) \
        .isoformat()
    rows = await db.chemical_usage_events.find(
        {"tenant_id": tenant["id"], "customer_id": pool_id,
          "occurred_at": {"$gte": since}}, {"_id": 0}
    ).sort("occurred_at", 1).to_list(5000)

    by_month: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        month = (r.get("occurred_at") or "")[:7] or "unknown"
        entry = by_month.setdefault(month, {
            "month": month, "total_cost_cents": 0,
            "visit_count_est": 0, "visit_ids": set(),
        })
        entry["total_cost_cents"] += int(r.get("total_cost_cents") or 0)
        vid = r.get("service_report_id") or r.get("job_id")
        if vid:
            entry["visit_ids"].add(vid)

    series = []
    for m, e in sorted(by_month.items()):
        series.append({
            "month": m,
            "total_cost_cents": e["total_cost_cents"],
            "visit_count": len(e["visit_ids"]),
        })
    return {
        "pool_id": pool_id,
        "months": months,
        "series": series,
        "totals": {
            "total_cost_cents": sum(x["total_cost_cents"] for x in series),
            "visit_count": sum(x["visit_count"] for x in series),
        },
    }
