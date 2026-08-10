from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime, timezone, timedelta

from config import db, logger, EMERGENT_LLM_KEY
from utils import (now_iso, new_id, hash_password, verify_password, create_token,
                   get_current_user, require_admin, send_sms, notify_customer, auth_response)
# Bucket A2 · Feb-2026 — explicit model imports (was ``from models import *``).
from models import ItemIn

router = APIRouter()


# ----------------------- Price Book -----------------------
@router.get("/items")
async def list_items(user: dict = Depends(require_admin)):
    # BUG B fix (Feb-2026) — filter out soft-deleted rows.
    return await db.items.find(
        {"$or": [{"deleted_at": None}, {"deleted_at": {"$exists": False}}]},
        {"_id": 0},
    ).sort("name", 1).to_list(1000)


@router.post("/items")
async def create_item(body: ItemIn, user: dict = Depends(require_admin)):
    doc = body.dict()
    # Feb-2026 · Service category enforcement on pricebook write.
    from routers.service_categories import validate_service_category
    tenant_id = user.get("tenant_id") or ""
    await validate_service_category(tenant_id, doc.get("service_category_id"))
    # Phase 56-b · Aug-2026 — Multi-supplier pricing validation.
    doc["supplier_prices"] = await _validate_supplier_prices(
        tenant_id, doc.get("income_category_id"), doc.get("supplier_prices"),
    )
    doc.update({"id": new_id(), "created_at": now_iso()})
    if tenant_id:
        doc["tenant_id"] = tenant_id
    await db.items.insert_one(doc)
    doc.pop("_id", None)
    return doc


async def _soft_delete_item(iid: str, actor_id: Optional[str], tenant_id: Optional[str] = None) -> dict:
    q: dict = {"id": iid}
    if tenant_id:
        q["tenant_id"] = tenant_id
    row = await db.items.find_one(q, {"_id": 0})
    if not row:
        raise HTTPException(404, "Item not found")
    if row.get("deleted_at"):
        return {"ok": True, "id": iid, "already_deleted": True}
    # Phase 34 · Task KK · locked-state — refuse hard delete if the
    # item is referenced by an active invoice / estimate / autobilling
    # plan in the tenant. Deactivate is still allowed via PATCH.
    linked = 0
    try:
        for coll, key in [("quotes", "line_items.item_id"),
                            ("estimates", "line_items.item_id"),
                            ("billing_plans", "item_id")]:
            linked += await db[coll].count_documents({
                key: iid,
                "$or": [{"deleted_at": None}, {"deleted_at": {"$exists": False}}],
            })
            if linked:
                break
    except Exception:                                            # noqa: BLE001
        pass
    if linked:
        raise HTTPException(
            409,
            f"Item is used on {linked} active document(s) — deactivate via PATCH instead of deleting",
        )
    await db.items.update_one(
        {"id": iid},
        {"$set": {"deleted_at": now_iso(),
                    "deleted_by_user_id": actor_id}},
    )
    return {"ok": True, "id": iid, "soft_deleted": True}


class ItemPatch(BaseModel):
    name: Optional[str] = None
    category: Optional[str] = None
    unit: Optional[str] = None
    unit_price: Optional[float] = None
    cost: Optional[float] = None
    tax_rate: Optional[float] = None
    description: Optional[str] = None
    active: Optional[bool] = None
    sku: Optional[str] = None
    # Feb-2026 · Service category — patchable, validated below.
    service_category_id: Optional[str] = None
    # Feb-2026 · PB1 · Internal-only cost fields.
    #   ``wholesale_price``     — supplier cost per unit (COGS).
    #   ``labor_cost_default``  — labor cost per unit; used as the
    #                             per-line snapshot default when the
    #                             item is added to a new quote / invoice.
    # Both admin-gated and NEVER surfaced on customer-facing views.
    wholesale_price: Optional[float] = None
    labor_cost_default: Optional[float] = None
    # Phase 56-b · Aug-2026 — Multi-supplier pricing patch.
    income_category_id: Optional[str] = None
    supplier_prices: Optional[List[dict]] = None


# ═════════════════════════════════════════════════════════════════════════
# Phase 56-b · Aug-2026 — Multi-supplier pricing validators.
#
# Rules (locked in preflight §4):
#   1. Every ``supplier_prices[i].supplier_slug`` must reference a
#      non-deleted row in ``db.pricebook_suppliers`` on this tenant.
#      Unknown slugs → 400 ``unknown_supplier``.
#   2. Every supplier's ``income_category_id`` must equal the item's
#      ``income_category_id``. Mismatch → 400
#      ``supplier_income_category_mismatch``.
#   3. Empty ``supplier_prices=[]`` is legal (item has no prices).
#   4. Duplicates on the same slug → 400 ``duplicate_supplier_slug``
#      (defensive — prevents shadow-row bugs downstream).
#   5. ``cost_cents`` must be an int ≥ 0.
#
# Soft-deleted suppliers are IGNORED at validation time on WRITES —
# they'd be a mismatch (deleted row can't match a category). But
# EXISTING supplier_prices on an item are preserved on READS even if
# the supplier is later soft-deleted; the frontend renders a
# "(deleted supplier)" pill.
# ═════════════════════════════════════════════════════════════════════════
async def _validate_supplier_prices(
    tenant_id: str,
    income_category_id: Optional[str],
    supplier_prices: Optional[List[dict]],
) -> List[dict]:
    """Return a normalized list of ``{supplier_slug, cost_cents}`` docs
    or raise HTTPException(400) with a friendly ``detail`` payload."""
    if not supplier_prices:
        return []
    if not income_category_id:
        # Silent guard — items without an income_category cannot carry
        # supplier_prices. Reject early with a friendly detail rather
        # than half-persisting.
        raise HTTPException(400, {
            "error": "supplier_prices_without_income_category",
            "message": ("supplier_prices requires income_category_id "
                         "to be set on the item"),
        })

    seen: set = set()
    out: List[dict] = []
    for row in supplier_prices:
        slug = str((row or {}).get("supplier_slug") or "").strip().lower()
        if not slug:
            raise HTTPException(400, {"error": "invalid_supplier_slug",
                                        "message": "supplier_slug required"})
        if slug in seen:
            raise HTTPException(400, {"error": "duplicate_supplier_slug",
                                        "supplier_slug": slug})
        seen.add(slug)
        try:
            cents = int((row or {}).get("cost_cents") or 0)
        except (TypeError, ValueError) as e:
            raise HTTPException(400, {"error": "invalid_cost_cents",
                                        "supplier_slug": slug}) from e
        if cents < 0:
            raise HTTPException(422, {"error": "invalid_cost_cents",
                                        "supplier_slug": slug,
                                        "message": "cost_cents must be ≥ 0"})

        sup = await db.pricebook_suppliers.find_one(
            {"tenant_id": tenant_id, "slug": slug,
              "deleted_at": {"$in": [None, ""]}},
            {"_id": 0, "slug": 1, "income_category_id": 1},
        )
        if not sup:
            raise HTTPException(400, {"error": "unknown_supplier",
                                        "supplier_slug": slug})
        if sup.get("income_category_id") != income_category_id:
            # Look up the expected category name to make the friendly
            # detail actionable (matches preflight lock).
            cat = await db.income_categories.find_one(
                {"tenant_id": tenant_id, "id": sup["income_category_id"]},
                {"_id": 0, "name": 1},
            ) or {}
            raise HTTPException(400, {
                "error": "supplier_income_category_mismatch",
                "supplier_slug": slug,
                "expected_category": cat.get("name") or sup["income_category_id"],
            })
        out.append({"supplier_slug": slug, "cost_cents": cents})
    return out


@router.patch("/items/{iid}", operation_id="pricebook.patch")
async def patch_item(iid: str, body: ItemPatch,
                       user: dict = Depends(require_admin)):
    """Phase 34 · Task KK · Feb 2026 — partial update of a pricebook
    item. Validates numeric ranges (unit_price ≥ 0, cost ≥ 0,
    tax_rate 0-100). Emits an ``audit_log`` row with the changed
    field set for later auditing."""
    row = await db.items.find_one({"id": iid}, {"_id": 0})
    if not row:
        raise HTTPException(404, "Item not found")
    if row.get("deleted_at"):
        raise HTTPException(409, "Item is archived — restore it first")
    upd = {k: v for k, v in body.dict(exclude_none=True).items()}
    if not upd:
        raise HTTPException(400, "No fields to update")
    if "unit_price" in upd and upd["unit_price"] < 0:
        raise HTTPException(422, "unit_price must be ≥ 0")
    if "cost" in upd and upd["cost"] < 0:
        raise HTTPException(422, "cost must be ≥ 0")
    if "tax_rate" in upd and (upd["tax_rate"] < 0 or upd["tax_rate"] > 100):
        raise HTTPException(422, "tax_rate must be between 0 and 100")
    # PB1 · Feb-2026 — wholesale + labor cost validation.
    if "wholesale_price" in upd:
        try:
            wp = float(upd["wholesale_price"])
        except (TypeError, ValueError) as e:
            raise HTTPException(422, "wholesale_price must be numeric") from e
        if wp < 0:
            raise HTTPException(422, "wholesale_price must be ≥ 0")
        upd["wholesale_price"] = wp
    if "labor_cost_default" in upd:
        try:
            lc = float(upd["labor_cost_default"])
        except (TypeError, ValueError) as e:
            raise HTTPException(422, "labor_cost_default must be numeric") from e
        if lc < 0:
            raise HTTPException(422, "labor_cost_default must be ≥ 0")
        upd["labor_cost_default"] = lc
    # Feb-2026 · Service category — if the patch touches it, validate.
    if "service_category_id" in upd:
        from routers.service_categories import validate_service_category
        await validate_service_category(row.get("tenant_id") or user.get("tenant_id") or "",
                                          upd["service_category_id"])
    # Phase 56-b · Aug-2026 — Multi-supplier pricing patch validation.
    # If the caller sends supplier_prices, validate against the
    # income_category the item is (or is becoming) attached to. If
    # the patch also flips income_category_id, use the NEW value —
    # otherwise fall back to the row's existing value.
    if "supplier_prices" in upd:
        effective_cat = upd.get("income_category_id",
                                  row.get("income_category_id"))
        upd["supplier_prices"] = await _validate_supplier_prices(
            row.get("tenant_id") or user.get("tenant_id") or "",
            effective_cat, upd["supplier_prices"],
        )
    upd["updated_at"] = now_iso()
    upd["updated_by_user_id"] = user.get("id")
    await db.items.update_one({"id": iid}, {"$set": upd})
    try:
        await db.audit_log.insert_one({
            "id": new_id(),
            "actor_user_id": user.get("id"),
            "actor_email": user.get("email"),
            "action": "pricebook.patch",
            "target_id": iid,
            "changed_fields": sorted(upd.keys()),
            "at": now_iso(),
        })
    except Exception as e:                                        # noqa: BLE001
        logger.warning(f"pricebook.patch audit failed: {e}")
    return await db.items.find_one({"id": iid}, {"_id": 0})


@router.delete("/items/{iid}")
async def delete_item(iid: str, user: dict = Depends(require_admin)):
    # BUG B fix — switched from hard delete to soft delete so history
    # rows (invoices/quotes referencing the item) stay intact.
    return await _soft_delete_item(iid, user.get("id"))


# Alias per the Item 8 spec — same collection, different URL surface.
@router.delete("/pricebook/{iid}",
                operation_id="pricebook.delete")
async def delete_pricebook_item(iid: str, user: dict = Depends(require_admin)):
    return await _soft_delete_item(iid, user.get("id"))


# ═════════════════════════════════════════════════════════════════════════
# Phase 34 · Task KK · Feb 2026 — Pricebook bulk soft-delete + Task EE
# query_selector filter shape. Same admin gate / 400-cap / audit rows.
# Locked-state: items referenced by active invoices/estimates/autobilling
# plans return in ``failed[]`` with a friendly reason.
# ═════════════════════════════════════════════════════════════════════════


class _PricebookBulkDeleteIn(BaseModel):
    ids: Optional[List[str]] = None
    query_selector: Optional[dict] = None
    exclude_ids: Optional[List[str]] = None


_PRICEBOOK_BULK_CAP = 400
_PRICEBOOK_SELECTOR_KEYS = {"category", "search", "active"}


async def _resolve_pricebook_ids(selector: dict, exclude: List[str]) -> List[str]:
    q: dict = {"$or": [{"deleted_at": None}, {"deleted_at": {"$exists": False}}]}
    clean = {k: v for k, v in (selector or {}).items()
              if k in _PRICEBOOK_SELECTOR_KEYS}
    if clean.get("category"):
        q["category"] = clean["category"]
    if clean.get("active") is not None:
        q["active"] = bool(clean["active"])
    if clean.get("search"):
        s = str(clean["search"]).strip()
        if s:
            q["name"] = {"$regex": s, "$options": "i"}
    excl = set(exclude or [])
    ids: List[str] = []
    async for row in db.items.find(q, {"_id": 0, "id": 1}).limit(_PRICEBOOK_BULK_CAP + 1):
        rid = row.get("id")
        if rid and rid not in excl:
            ids.append(rid)
    return ids


@router.post("/pricebook/bulk-delete",
              operation_id="pricebook.bulkDelete")
async def bulk_delete_pricebook(body: _PricebookBulkDeleteIn,
                                  user: dict = Depends(require_admin)):
    if body.query_selector is not None:
        ids = await _resolve_pricebook_ids(
            body.query_selector, body.exclude_ids or [],
        )
    else:
        ids = list(body.ids or [])
    if not ids:
        raise HTTPException(400, "ids is empty")
    if len(ids) > _PRICEBOOK_BULK_CAP:
        raise HTTPException(400, f"bulk-delete capped at {_PRICEBOOK_BULK_CAP} rows per call")
    # Idempotency guard — collapse duplicate ids in the payload.
    ids = list(dict.fromkeys(ids))
    deleted: List[str] = []
    failed: List[dict] = []
    for iid in ids:
        try:
            r = await _soft_delete_item(iid, user.get("id"))
            deleted.append(r["id"])
        except HTTPException as e:
            failed.append({"id": iid, "reason": str(e.detail),
                              "status_code": e.status_code})
        except Exception as e:                                    # noqa: BLE001
            failed.append({"id": iid, "reason": str(e), "status_code": 500})
    return {"ok": True, "deleted_count": len(deleted),
              "deleted": deleted, "failed": failed}

