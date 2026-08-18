"""Phase 3 · Feb-2026 · Bulk manual-override pricing for pricebook items.

Endpoints
---------

* ``PATCH /api/pricebook/items/{item_id}/supplier-price`` — upsert a
  single ``supplier_prices`` row keyed on ``(supplier_id, effective_date)``.
* ``POST  /api/pricebook/items/bulk-supplier-price``       — atomic-per-item
  bulk edit (cap 500).
* ``GET   /api/pricebook/items``                            — bucketed list
  for the manual-pricing UI (``no_source_blob``, ``all_costs_zero``, ``any``).

Role gate: ``super_admin | admin | manager``. Tenant-scoped every query.
Never touches ``homeworks_costs`` — the raw import source is preserved.
Appends to a per-item ``supplier_price_edits`` audit trail (last-50 cap).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from config import db
from utils import get_current_user, now_iso
from routers.tenants import get_current_tenant

router = APIRouter()

MANUAL_PRICING_ROLES = {"super_admin", "admin", "manager", "owner"}
BUCKET_ANY = "any"
BUCKET_NO_SOURCE = "no_source_blob"
BUCKET_ALL_ZERO = "all_costs_zero"
VALID_BUCKETS = {BUCKET_ANY, BUCKET_NO_SOURCE, BUCKET_ALL_ZERO}


def require_pricing_editor(user: dict = Depends(get_current_user)) -> dict:
    """super_admin | admin | manager | owner. 403 otherwise."""
    if user.get("role") not in MANUAL_PRICING_ROLES:
        raise HTTPException(status_code=403,
                              detail="Pricebook pricing edit access required")
    return user


class SupplierPriceEdit(BaseModel):
    supplier_id: str = Field(..., min_length=1)
    unit_cost: float = Field(..., gt=0)
    effective_date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    notes: Optional[str] = None
    markup_pct: Optional[float] = Field(None, ge=0)
    sale_price: Optional[float] = Field(None, ge=0)


class BulkSupplierPriceEdit(SupplierPriceEdit):
    item_id: str = Field(..., min_length=1)


class BulkSupplierPriceBody(BaseModel):
    edits: List[BulkSupplierPriceEdit] = Field(..., min_items=1, max_items=500)


def _compute_sale_price(edit: SupplierPriceEdit) -> float:
    """Resolve the effective sale_price for an edit.

    - When both provided: trust the caller but require
      ``sale_price >= unit_cost`` (invalid margins are almost always a
      data-entry error).
    - When only ``markup_pct`` provided: compute
      ``unit_cost * (1 + markup_pct/100)``.
    - When neither provided: default to ``unit_cost`` (no margin).
    """
    if edit.sale_price is not None:
        if edit.sale_price < edit.unit_cost:
            raise HTTPException(
                status_code=400,
                detail="sale_price must be >= unit_cost",
            )
        return edit.sale_price
    if edit.markup_pct is not None:
        return round(edit.unit_cost * (1.0 + edit.markup_pct / 100.0), 2)
    return edit.unit_cost


def _upsert_supplier_price(
    existing: List[dict],
    *,
    supplier_id: str,
    effective_date: str,
    unit_cost: float,
    sale_price: float,
    markup_pct: Optional[float],
    notes: Optional[str],
    actor_user_id: str,
    actor_email: Optional[str],
) -> tuple[List[dict], Optional[dict], dict]:
    """Return ``(next_prices, before_row_or_None, after_row)``.

    Upsert keyed on ``(supplier_id, effective_date)``. Callers use the
    ``before/after`` tuple to write the audit trail.
    """
    at = now_iso()
    after = {
        "supplier_id": supplier_id,
        "supplier_slug": supplier_id,  # legacy consumers key on ``supplier_slug``
        "effective_date": effective_date,
        "unit_cost": unit_cost,
        "cost_cents": int(round(unit_cost * 100)),
        "sale_price": sale_price,
        "retail_cents": int(round(sale_price * 100)),
        "markup_pct": markup_pct,
        "notes": notes,
        "currency": "USD",
        "source": "manual",
        "updated_at": at,
        "updated_by": actor_user_id,
        "updated_by_email": actor_email,
    }
    next_prices = list(existing or [])
    before: Optional[dict] = None
    for i, row in enumerate(next_prices):
        row_supplier = row.get("supplier_id") or row.get("supplier_slug")
        if row_supplier == supplier_id and row.get("effective_date") == effective_date:
            before = dict(row)
            next_prices[i] = after
            return next_prices, before, after
    next_prices.append(after)
    return next_prices, None, after


def _append_edit_audit(item: dict, *, actor_user_id: str,
                        actor_email: Optional[str],
                        supplier_id: str, effective_date: str,
                        before: Optional[dict], after: dict) -> list[dict]:
    trail = list(item.get("supplier_price_edits") or [])
    trail.append({
        "actor_user_id": actor_user_id,
        "actor_email": actor_email,
        "at": now_iso(),
        "supplier_id": supplier_id,
        "effective_date": effective_date,
        "before": before,
        "after": after,
    })
    # Keep only the most recent 50 entries so item docs don't grow
    # unbounded on high-frequency edits.
    if len(trail) > 50:
        trail = trail[-50:]
    return trail


async def _apply_single_edit(
    edit: SupplierPriceEdit,
    *,
    item_id: str,
    tenant_id: str,
    actor: dict,
) -> dict:
    """Fetch → mutate → persist a single edit atomically. Raises
    ``HTTPException`` on validation or lookup failure. Returns the
    updated ``supplier_prices`` array."""
    item = await db.items.find_one(
        {"id": item_id, "tenant_id": tenant_id},
        {"_id": 0},
    )
    if not item:
        raise HTTPException(404, "Pricebook item not found")

    sale_price = _compute_sale_price(edit)

    next_prices, before, after = _upsert_supplier_price(
        item.get("supplier_prices") or [],
        supplier_id=edit.supplier_id,
        effective_date=edit.effective_date,
        unit_cost=edit.unit_cost,
        sale_price=sale_price,
        markup_pct=edit.markup_pct,
        notes=edit.notes,
        actor_user_id=actor.get("id") or "",
        actor_email=actor.get("email"),
    )
    trail = _append_edit_audit(
        item,
        actor_user_id=actor.get("id") or "",
        actor_email=actor.get("email"),
        supplier_id=edit.supplier_id,
        effective_date=edit.effective_date,
        before=before,
        after=after,
    )
    res = await db.items.update_one(
        {"id": item_id, "tenant_id": tenant_id},
        {"$set": {
            "supplier_prices": next_prices,
            "supplier_price_edits": trail,
            "updated_at": now_iso(),
        }},
    )
    if res.matched_count == 0:
        # Race: item was deleted between find and update.
        raise HTTPException(404, "Pricebook item not found")
    return {
        "item_id": item_id,
        "supplier_prices": next_prices,
        "supplier_price_edits_count": len(trail),
    }


# ═══ PATCH single ═══════════════════════════════════════════════════
@router.patch("/pricebook/items/{item_id}/supplier-price")
async def patch_supplier_price(
    item_id: str,
    body: SupplierPriceEdit,
    user: dict = Depends(require_pricing_editor),
    tenant: dict = Depends(get_current_tenant),
) -> dict:
    return await _apply_single_edit(
        body, item_id=item_id, tenant_id=tenant["id"], actor=user,
    )


# ═══ POST bulk ══════════════════════════════════════════════════════
@router.post("/pricebook/items/bulk-supplier-price")
async def bulk_supplier_price(
    body: BulkSupplierPriceBody,
    user: dict = Depends(require_pricing_editor),
    tenant: dict = Depends(get_current_tenant),
) -> dict:
    """Atomic per item. A single bad row does not abort the batch;
    each row reports ``ok`` or ``error`` with detail. Cap 500 rows
    (enforced by the Pydantic ``max_items``)."""
    results: list[dict] = []
    for edit in body.edits:
        try:
            single = SupplierPriceEdit(**edit.dict(exclude={"item_id"}))
            r = await _apply_single_edit(
                single,
                item_id=edit.item_id,
                tenant_id=tenant["id"],
                actor=user,
            )
            results.append({"item_id": edit.item_id, "status": "ok",
                              "supplier_prices": r["supplier_prices"]})
        except HTTPException as e:
            results.append({"item_id": edit.item_id, "status": "error",
                              "detail": e.detail, "status_code": e.status_code})
        except Exception as e:  # pragma: no cover — defensive
            results.append({"item_id": edit.item_id, "status": "error",
                              "detail": str(e), "status_code": 500})
    ok_count = sum(1 for r in results if r["status"] == "ok")
    return {"total": len(results), "ok": ok_count,
            "errors": len(results) - ok_count, "results": results}


# ═══ GET bucketed list ═════════════════════════════════════════════
def _hw_has_any_signal(hw: Any) -> bool:
    if not hw:
        return False
    for k in ("wholesaleCost", "materialCost", "equipmentCost", "subcontractCost"):
        try:
            if float(hw.get(k) or 0) > 0:
                return True
        except (TypeError, ValueError):
            continue
    return False


def _classify_bucket(item: dict) -> str:
    if item.get("supplier_prices"):
        return "already_populated"
    hw = item.get("homeworks_costs")
    if not hw:
        return BUCKET_NO_SOURCE
    if not _hw_has_any_signal(hw):
        return BUCKET_ALL_ZERO
    return "hydratable"


def _hw_summary(hw: Any) -> Optional[dict]:
    if not hw or not isinstance(hw, dict):
        return None
    return {
        "materialCost": hw.get("materialCost"),
        "wholesaleCost": hw.get("wholesaleCost"),
        "equipmentCost": hw.get("equipmentCost"),
        "subcontractCost": hw.get("subcontractCost"),
        "markup": hw.get("markup"),
    }


@router.get("/pricebook/items")
async def list_pricebook_items(
    user: dict = Depends(require_pricing_editor),
    tenant: dict = Depends(get_current_tenant),
    missing_supplier_prices: bool = Query(False),
    bucket: str = Query(BUCKET_ANY),
    search: str = Query(""),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
) -> dict:
    if bucket not in VALID_BUCKETS:
        raise HTTPException(
            422, f"bucket must be one of {sorted(VALID_BUCKETS)}"
        )

    q: dict = {
        "tenant_id": tenant["id"],
        "$or": [
            {"deleted_at": None},
            {"deleted_at": {"$exists": False}},
        ],
    }
    if missing_supplier_prices:
        q["$and"] = q.get("$and", []) + [{"$or": [
            {"supplier_prices": {"$exists": False}},
            {"supplier_prices": None},
            {"supplier_prices": []},
        ]}]
    if search:
        q["name"] = {"$regex": search, "$options": "i"}

    # Bucket filter — apply at Python level because ``all_costs_zero``
    # depends on the sum of four numeric fields (partial-only in
    # Mongo aggregation, complicated for little payoff at 518 rows).
    projection = {
        "_id": 0, "id": 1, "name": 1, "sku": 1, "unit": 1,
        "unit_price": 1, "supplier_prices": 1, "homeworks_costs": 1,
        "imported_from": 1,
    }
    raw = await db.items.find(q, projection).sort("name", 1).to_list(5000)

    bucketed: list[dict] = []
    for it in raw:
        b = _classify_bucket(it)
        if bucket != BUCKET_ANY and b != bucket:
            continue
        bucketed.append({
            "id": it.get("id"),
            "_id": it.get("id"),  # UI convenience
            "name": it.get("name"),
            "sku": it.get("sku"),
            "unit": it.get("unit"),
            "unit_price": it.get("unit_price"),
            "current_supplier_prices": it.get("supplier_prices") or [],
            "homeworks_costs_summary": _hw_summary(it.get("homeworks_costs")),
            "imported_from": it.get("imported_from"),
            "bucket": b,
        })
    total = len(bucketed)
    start = (page - 1) * limit
    end = start + limit
    return {
        "items": bucketed[start:end],
        "total": total,
        "page": page,
        "limit": limit,
        "bucket": bucket,
    }
