from fastapi import APIRouter, HTTPException, Depends
from typing import List, Optional

from config import db
from utils import now_iso, new_id, get_current_user, require_admin, notify_customer
from routers.tenants import get_current_tenant
from models import EstimateIn, EstimateSettingsIn, EstimateTemplateIn

router = APIRouter()

SETTINGS_ID = "estimate_settings"


def compute_estimate(line_items: List[dict], overhead_pct: float, margin_pct: float) -> dict:
    """Gross-margin pricing with overhead recovery."""
    direct_cost = round(sum((li.get("quantity") or 0) * (li.get("unit_cost") or 0) for li in line_items), 2)
    overhead_pct = max(0.0, float(overhead_pct or 0))
    m = min(max(0.0, float(margin_pct or 0)), 99.0) / 100.0
    overhead_amount = round(direct_cost * overhead_pct / 100.0, 2)
    burdened_cost = round(direct_cost + overhead_amount, 2)
    sell_price = round(burdened_cost / (1 - m), 2) if m < 1 else burdened_cost
    profit_amount = round(sell_price - burdened_cost, 2)
    gross_margin_pct = round((profit_amount / sell_price * 100), 2) if sell_price else 0.0
    return {
        "direct_cost": direct_cost,
        "overhead_amount": overhead_amount,
        "total_cost": burdened_cost,
        "profit_amount": profit_amount,
        "sell_price": sell_price,
        "gross_margin_pct": gross_margin_pct,
    }


# ----------------------- Settings (company defaults) -----------------------
@router.get("/estimates/settings")
async def get_estimate_settings(user: dict = Depends(require_admin),
                                tenant: dict = Depends(get_current_tenant)):
    s = await db.settings.find_one(
        {"id": SETTINGS_ID, "tenant_id": tenant["id"]}, {"_id": 0}
    )
    if not s:
        s = {"id": SETTINGS_ID, "tenant_id": tenant["id"],
             "overhead_pct": 15.0, "margin_pct": 30.0}
        await db.settings.insert_one(dict(s))
    return {"overhead_pct": s.get("overhead_pct", 15.0), "margin_pct": s.get("margin_pct", 30.0)}


@router.put("/estimates/settings")
async def put_estimate_settings(body: EstimateSettingsIn,
                                user: dict = Depends(require_admin),
                                tenant: dict = Depends(get_current_tenant)):
    upd = {k: v for k, v in body.dict().items() if v is not None}
    await db.settings.update_one(
        {"id": SETTINGS_ID, "tenant_id": tenant["id"]},
        {"$set": {"id": SETTINGS_ID, "tenant_id": tenant["id"], **upd}},
        upsert=True,
    )
    return await get_estimate_settings(user, tenant)


# ----------------------- Templates -----------------------
PREBUILT_TEMPLATES = [
    {
        "name": "Weekly Pool Cleaning (Monthly)",
        "overhead_pct": 15.0, "margin_pct": 35.0,
        "line_items": [
            {"category": "Labor", "description": "Weekly service labor (4 visits)", "quantity": 4, "unit_cost": 22.0},
            {"category": "Material", "description": "Chlorine & balancing chemicals", "quantity": 1, "unit_cost": 45.0},
            {"category": "Equipment", "description": "Vehicle / fuel allocation", "quantity": 1, "unit_cost": 20.0},
        ],
    },
    {
        "name": "Pump & Filter Equipment Install",
        "overhead_pct": 15.0, "margin_pct": 30.0,
        "line_items": [
            {"category": "Material", "description": "Variable-speed pump", "quantity": 1, "unit_cost": 650.0},
            {"category": "Material", "description": "Cartridge filter + plumbing", "quantity": 1, "unit_cost": 280.0},
            {"category": "Labor", "description": "Install labor (hrs)", "quantity": 4, "unit_cost": 45.0},
        ],
    },
    {
        "name": "Pool Resurfacing (Plaster)",
        "overhead_pct": 18.0, "margin_pct": 28.0,
        "line_items": [
            {"category": "Subcontractor", "description": "Plaster crew", "quantity": 1, "unit_cost": 3200.0},
            {"category": "Material", "description": "Plaster / tile materials", "quantity": 1, "unit_cost": 1400.0},
            {"category": "Labor", "description": "Prep & startup labor (hrs)", "quantity": 8, "unit_cost": 40.0},
        ],
    },
]


async def _ensure_templates_seeded(tenant_id: str):
    """Seed prebuilt templates once per tenant."""
    if await db.estimate_templates.count_documents({"tenant_id": tenant_id}) == 0:
        for t in PREBUILT_TEMPLATES:
            await db.estimate_templates.insert_one({
                "id": new_id(), "tenant_id": tenant_id,
                "name": t["name"], "line_items": t["line_items"],
                "overhead_pct": t["overhead_pct"], "margin_pct": t["margin_pct"],
                "prebuilt": True, "created_at": now_iso(),
            })


@router.get("/estimate-templates")
async def list_templates(user: dict = Depends(require_admin),
                         tenant: dict = Depends(get_current_tenant)):
    await _ensure_templates_seeded(tenant["id"])
    return await db.estimate_templates.find(
        {"tenant_id": tenant["id"]}, {"_id": 0}
    ).sort("name", 1).to_list(500)


@router.post("/estimate-templates")
async def create_template(body: EstimateTemplateIn,
                          user: dict = Depends(require_admin),
                          tenant: dict = Depends(get_current_tenant)):
    doc = {
        "id": new_id(), "tenant_id": tenant["id"], "name": body.name,
        "line_items": [li.dict() for li in body.line_items],
        "overhead_pct": body.overhead_pct, "margin_pct": body.margin_pct,
        "prebuilt": False, "created_at": now_iso(),
    }
    await db.estimate_templates.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.delete("/estimate-templates/{tid}")
async def delete_template(tid: str,
                          user: dict = Depends(require_admin),
                          tenant: dict = Depends(get_current_tenant)):
    await db.estimate_templates.delete_one(
        {"id": tid, "tenant_id": tenant["id"], "prebuilt": {"$ne": True}}
    )
    return {"ok": True}


# ----------------------- Estimates -----------------------
@router.get("/estimates")
async def list_estimates(user: dict = Depends(require_admin),
                         tenant: dict = Depends(get_current_tenant),
                         include_deleted: bool = False):
    q: dict = {"tenant_id": tenant["id"]}
    # Phase 34 · Task BB — hide soft-deleted rows unless super_admin opts in.
    if not (include_deleted and (user.get("role") or "").lower() == "super_admin"):
        q["$or"] = [{"deleted_at": None}, {"deleted_at": {"$exists": False}}]
    return await db.estimates.find(
        q, {"_id": 0}
    ).sort("created_at", -1).to_list(1000)


@router.post("/estimates")
async def create_estimate(body: EstimateIn,
                          user: dict = Depends(require_admin),
                          tenant: dict = Depends(get_current_tenant)):
    customer = await db.customers.find_one(
        {"id": body.customer_id, "tenant_id": tenant["id"]}, {"_id": 0}
    )
    if not customer:
        raise HTTPException(400, "Customer not found")
    # Feb-2026 MP1.5 — property_id validation + single-property auto-assign.
    property_id = body.property_id
    if property_id:
        prop = await db.properties.find_one(
            {"id": property_id, "tenant_id": tenant["id"],
              "customer_id": body.customer_id},
            {"_id": 0, "id": 1, "active": 1},
        )
        if not prop:
            raise HTTPException(400, "property_id not found for this customer")
        if prop.get("active") is False:
            raise HTTPException(400, "property_id refers to an inactive property")
    else:
        active_props = await db.properties.find(
            {"tenant_id": tenant["id"], "customer_id": body.customer_id,
              "active": {"$ne": False}},
            {"_id": 0, "id": 1},
        ).to_list(10)
        if len(active_props) == 1:
            property_id = active_props[0]["id"]
    items = [li.dict() for li in body.line_items]
    calc = compute_estimate(items, body.overhead_pct, body.margin_pct)
    terms = body.terms
    if terms is None:
        from routers.finances import get_terms_defaults
        terms = (await get_terms_defaults())["default_quote_terms"]
    doc = {
        "id": new_id(), "tenant_id": tenant["id"],
        "customer_id": body.customer_id, "customer_name": customer["name"],
        "property_id": property_id,
        "title": body.title, "line_items": items,
        "overhead_pct": body.overhead_pct, "margin_pct": body.margin_pct,
        "notes": body.notes or "", "terms": terms, "status": "draft",
        "converted_quote_id": None, "created_at": now_iso(), "updated_at": now_iso(), **calc,
    }
    await db.estimates.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.get("/estimates/{eid}")
async def get_estimate(eid: str,
                       user: dict = Depends(require_admin),
                       tenant: dict = Depends(get_current_tenant)):
    doc = await db.estimates.find_one(
        {"id": eid, "tenant_id": tenant["id"]}, {"_id": 0}
    )
    if not doc:
        raise HTTPException(404, "Estimate not found")
    return doc


@router.put("/estimates/{eid}")
async def update_estimate(eid: str, body: EstimateIn,
                          user: dict = Depends(require_admin),
                          tenant: dict = Depends(get_current_tenant)):
    existing = await db.estimates.find_one(
        {"id": eid, "tenant_id": tenant["id"]}, {"_id": 0}
    )
    if not existing:
        raise HTTPException(404, "Estimate not found")
    customer = await db.customers.find_one(
        {"id": body.customer_id, "tenant_id": tenant["id"]}, {"_id": 0}
    )
    if not customer:
        raise HTTPException(400, "Customer not found")
    items = [li.dict() for li in body.line_items]
    calc = compute_estimate(items, body.overhead_pct, body.margin_pct)
    # Feb-2026 MP1.5 — property_id patch validation. If the caller
    # explicitly sent a value, verify it belongs to this customer +
    # tenant AND is still active. If body.property_id is null, we
    # leave the existing value untouched (PUT is not a full replace
    # for this field — callers should use PATCH-style intent).
    property_id = existing.get("property_id")
    if body.property_id is not None:
        prop = await db.properties.find_one(
            {"id": body.property_id, "tenant_id": tenant["id"],
              "customer_id": body.customer_id},
            {"_id": 0, "id": 1, "active": 1},
        )
        if not prop:
            raise HTTPException(400, "property_id not found for this customer")
        if prop.get("active") is False:
            raise HTTPException(400, "property_id refers to an inactive property")
        property_id = body.property_id
    upd = {
        "customer_id": body.customer_id, "customer_name": customer["name"], "title": body.title,
        "line_items": items, "overhead_pct": body.overhead_pct, "margin_pct": body.margin_pct,
        "property_id": property_id,
        "notes": body.notes or "", "updated_at": now_iso(), **calc,
    }
    if body.terms is not None:
        upd["terms"] = body.terms
    await db.estimates.update_one(
        {"id": eid, "tenant_id": tenant["id"]}, {"$set": upd}
    )
    return await db.estimates.find_one(
        {"id": eid, "tenant_id": tenant["id"]}, {"_id": 0}
    )


@router.delete("/estimates/{eid}")
async def delete_estimate(eid: str,
                          user: dict = Depends(require_admin),
                          tenant: dict = Depends(get_current_tenant)):
    await db.estimates.delete_one({"id": eid, "tenant_id": tenant["id"]})
    return {"ok": True}


@router.post("/estimates/{eid}/convert")
async def convert_estimate_to_quote(eid: str,
                                    user: dict = Depends(require_admin),
                                    tenant: dict = Depends(get_current_tenant)):
    """Turn an estimate into a customer-facing quote showing only the final sell price."""
    est = await db.estimates.find_one(
        {"id": eid, "tenant_id": tenant["id"]}, {"_id": 0}
    )
    if not est:
        raise HTTPException(404, "Estimate not found")
    if est.get("converted_quote_id"):
        raise HTTPException(400, "This estimate is already converted")
    sell = float(est.get("sell_price") or 0)
    if sell <= 0:
        raise HTTPException(400, "Add line items before converting")
    terms = est.get("terms")
    if not terms:
        from routers.finances import get_terms_defaults
        terms = (await get_terms_defaults())["default_quote_terms"]
    quote = {
        "id": new_id(), "tenant_id": tenant["id"],
        "customer_id": est["customer_id"], "customer_name": est.get("customer_name", ""),
        # MP1.5 — carry property_id through the estimate → quote conversion.
        "property_id": est.get("property_id"),
        "title": est.get("title", "Estimate"), "doc_type": "quote",
        "line_items": [{"description": est.get("title", "Project"), "quantity": 1, "unit_price": sell}],
        "tax_rate": 0.0, "subtotal": sell, "tax": 0.0, "total": sell,
        "amount_paid": 0.0, "due_date": None, "status": "draft", "payment_status": "unpaid",
        "notes": est.get("notes", ""), "terms": terms,
        "from_estimate_id": eid, "created_at": now_iso(),
    }
    await db.quotes.insert_one(quote)
    quote.pop("_id", None)
    await db.estimates.update_one(
        {"id": eid, "tenant_id": tenant["id"]},
        {"$set": {"converted_quote_id": quote["id"], "status": "converted"}},
    )
    return quote


# ═════════════════════════════════════════════════════════════════════════
# Phase 34 · Task BB · Feb 2026 — Estimates bulk-select soft-delete.
# Mirrors the invoice bulk-delete helper in routers/quotes.py. Keeps the
# existing hard-delete route intact for backward compat (some scripts
# and older admin tools still call DELETE /api/estimates/{eid}).
# ═════════════════════════════════════════════════════════════════════════
from pydantic import BaseModel as _BulkBaseModel
from config import logger as _bulk_logger


class _EstimateBulkDeleteIn(_BulkBaseModel):
    ids: Optional[List[str]] = None
    query_selector: Optional[dict] = None
    exclude_ids: Optional[List[str]] = None


_ESTIMATE_BULK_DELETE_CAP = 400  # Phase 34 · Task DD · raised 100 → 400
_ESTIMATE_SELECTOR_KEYS = {"search", "customer_id"}


async def _resolve_estimate_ids(selector: dict, exclude: List[str], tenant_id: str) -> List[str]:
    q: dict = {"tenant_id": tenant_id,
                "$or": [{"deleted_at": None},
                            {"deleted_at": {"$exists": False}}]}
    clean = {k: v for k, v in (selector or {}).items()
              if k in _ESTIMATE_SELECTOR_KEYS}
    if clean.get("customer_id"):
        q["customer_id"] = clean["customer_id"]
    if clean.get("search"):
        s = str(clean["search"]).strip()
        if s:
            q["title"] = {"$regex": s, "$options": "i"}
    excl = set(exclude or [])
    ids: List[str] = []
    async for row in db.estimates.find(q, {"_id": 0, "id": 1}).limit(_ESTIMATE_BULK_DELETE_CAP + 1):
        rid = row.get("id")
        if rid and rid not in excl:
            ids.append(rid)
    return ids


async def _perform_soft_delete_estimate(eid: str, user: dict, tenant: dict) -> dict:
    doc = await db.estimates.find_one(
        {"id": eid, "tenant_id": tenant["id"]},
        {"_id": 0, "id": 1, "deleted_at": 1},
    )
    if not doc:
        raise HTTPException(404, "Estimate not found")
    if doc.get("deleted_at"):
        return {"ok": True, "id": eid, "already_deleted": True}
    deleted_at = now_iso()
    await db.estimates.update_one(
        {"id": eid, "tenant_id": tenant["id"]},
        {"$set": {"deleted_at": deleted_at,
                    "deleted_by_user_id": user.get("id")}},
    )
    try:
        await db.audit_log.insert_one({
            "id": new_id(),
            "tenant_id": tenant["id"],
            "actor_user_id": user.get("id"),
            "actor_email": user.get("email"),
            "action": "estimate.soft_delete",
            "target_id": eid,
            "at": deleted_at,
        })
    except Exception as e:
        _bulk_logger.warning(f"estimate.soft_delete audit failed: {e}")
    return {"ok": True, "id": eid, "deleted_at": deleted_at}


@router.post("/estimates/{eid}/soft-delete",
              operation_id="estimates.softDelete")
async def soft_delete_estimate(eid: str,
                                  user: dict = Depends(require_admin),
                                  tenant: dict = Depends(get_current_tenant)):
    return await _perform_soft_delete_estimate(eid, user, tenant)


@router.post("/estimates/bulk-delete",
              operation_id="estimates.bulkDelete")
async def bulk_delete_estimates(body: _EstimateBulkDeleteIn,
                                   user: dict = Depends(require_admin),
                                   tenant: dict = Depends(get_current_tenant)):
    if body.query_selector is not None:
        ids = await _resolve_estimate_ids(
            body.query_selector, body.exclude_ids or [], tenant["id"],
        )
    else:
        ids = list(body.ids or [])
    if not ids:
        raise HTTPException(400, "ids is empty")
    if len(ids) > _ESTIMATE_BULK_DELETE_CAP:
        raise HTTPException(400, f"bulk-delete capped at {_ESTIMATE_BULK_DELETE_CAP} rows per call")
    ids = list(dict.fromkeys(ids))  # idempotency
    deleted: List[str] = []
    failed: List[dict] = []
    for eid in ids:
        try:
            r = await _perform_soft_delete_estimate(eid, user, tenant)
            deleted.append(r["id"])
        except HTTPException as e:
            failed.append({"id": eid, "reason": str(e.detail),
                              "status_code": e.status_code})
        except Exception as e:                                # noqa: BLE001
            failed.append({"id": eid, "reason": str(e), "status_code": 500})
    return {"ok": True, "deleted_count": len(deleted),
              "deleted": deleted, "failed": failed}
