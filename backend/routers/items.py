# ruff: noqa: F403,F405
from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime, timezone, timedelta

from config import db, logger, EMERGENT_LLM_KEY
from utils import (now_iso, new_id, hash_password, verify_password, create_token,
                   get_current_user, require_admin, send_sms, notify_customer, auth_response)
from models import *  # noqa: F403,F405

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
    doc.update({"id": new_id(), "created_at": now_iso()})
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

