from fastapi import APIRouter, HTTPException, Depends
from typing import List, Optional

from config import db
from utils import now_iso, new_id, get_current_user, require_admin, notify_customer
from models import EstimateIn, EstimateSettingsIn, EstimateTemplateIn

router = APIRouter()

SETTINGS_ID = "estimate_settings"


def compute_estimate(line_items: List[dict], overhead_pct: float, margin_pct: float) -> dict:
    """Gross-margin pricing with overhead recovery.

    direct cost -> + overhead recovery -> burdened cost -> apply target gross margin -> sell price.
    """
    direct_cost = round(sum((li.get("quantity") or 0) * (li.get("unit_cost") or 0) for li in line_items), 2)
    overhead_pct = max(0.0, float(overhead_pct or 0))
    # Margin must be < 100% to avoid an infinite/negative price.
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
async def get_estimate_settings(user: dict = Depends(require_admin)):
    s = await db.settings.find_one({"id": SETTINGS_ID}, {"_id": 0})
    if not s:
        s = {"id": SETTINGS_ID, "overhead_pct": 15.0, "margin_pct": 30.0}
        await db.settings.insert_one(dict(s))
    return {"overhead_pct": s.get("overhead_pct", 15.0), "margin_pct": s.get("margin_pct", 30.0)}


@router.put("/estimates/settings")
async def put_estimate_settings(body: EstimateSettingsIn, user: dict = Depends(require_admin)):
    upd = {k: v for k, v in body.dict().items() if v is not None}
    await db.settings.update_one({"id": SETTINGS_ID}, {"$set": {"id": SETTINGS_ID, **upd}}, upsert=True)
    return await get_estimate_settings(user)


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


async def _ensure_templates_seeded():
    if await db.estimate_templates.count_documents({}) == 0:
        for t in PREBUILT_TEMPLATES:
            await db.estimate_templates.insert_one({
                "id": new_id(), "name": t["name"], "line_items": t["line_items"],
                "overhead_pct": t["overhead_pct"], "margin_pct": t["margin_pct"],
                "prebuilt": True, "created_at": now_iso(),
            })


@router.get("/estimate-templates")
async def list_templates(user: dict = Depends(require_admin)):
    await _ensure_templates_seeded()
    return await db.estimate_templates.find({}, {"_id": 0}).sort("name", 1).to_list(500)


@router.post("/estimate-templates")
async def create_template(body: EstimateTemplateIn, user: dict = Depends(require_admin)):
    doc = {
        "id": new_id(), "name": body.name,
        "line_items": [li.dict() for li in body.line_items],
        "overhead_pct": body.overhead_pct, "margin_pct": body.margin_pct,
        "prebuilt": False, "created_at": now_iso(),
    }
    await db.estimate_templates.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.delete("/estimate-templates/{tid}")
async def delete_template(tid: str, user: dict = Depends(require_admin)):
    await db.estimate_templates.delete_one({"id": tid, "prebuilt": {"$ne": True}})
    return {"ok": True}


# ----------------------- Estimates -----------------------
@router.get("/estimates")
async def list_estimates(user: dict = Depends(require_admin)):
    return await db.estimates.find({}, {"_id": 0}).sort("created_at", -1).to_list(1000)


@router.post("/estimates")
async def create_estimate(body: EstimateIn, user: dict = Depends(require_admin)):
    customer = await db.customers.find_one({"id": body.customer_id}, {"_id": 0})
    if not customer:
        raise HTTPException(400, "Customer not found")
    items = [li.dict() for li in body.line_items]
    calc = compute_estimate(items, body.overhead_pct, body.margin_pct)
    terms = body.terms
    if terms is None:
        from routers.finances import get_terms_defaults
        terms = (await get_terms_defaults())["default_quote_terms"]
    doc = {
        "id": new_id(), "customer_id": body.customer_id, "customer_name": customer["name"],
        "title": body.title, "line_items": items,
        "overhead_pct": body.overhead_pct, "margin_pct": body.margin_pct,
        "notes": body.notes or "", "terms": terms, "status": "draft",
        "converted_quote_id": None, "created_at": now_iso(), "updated_at": now_iso(), **calc,
    }
    await db.estimates.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.get("/estimates/{eid}")
async def get_estimate(eid: str, user: dict = Depends(require_admin)):
    doc = await db.estimates.find_one({"id": eid}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Estimate not found")
    return doc


@router.put("/estimates/{eid}")
async def update_estimate(eid: str, body: EstimateIn, user: dict = Depends(require_admin)):
    existing = await db.estimates.find_one({"id": eid}, {"_id": 0})
    if not existing:
        raise HTTPException(404, "Estimate not found")
    customer = await db.customers.find_one({"id": body.customer_id}, {"_id": 0})
    if not customer:
        raise HTTPException(400, "Customer not found")
    items = [li.dict() for li in body.line_items]
    calc = compute_estimate(items, body.overhead_pct, body.margin_pct)
    upd = {
        "customer_id": body.customer_id, "customer_name": customer["name"], "title": body.title,
        "line_items": items, "overhead_pct": body.overhead_pct, "margin_pct": body.margin_pct,
        "notes": body.notes or "", "updated_at": now_iso(), **calc,
    }
    if body.terms is not None:
        upd["terms"] = body.terms
    await db.estimates.update_one({"id": eid}, {"$set": upd})
    return await db.estimates.find_one({"id": eid}, {"_id": 0})


@router.delete("/estimates/{eid}")
async def delete_estimate(eid: str, user: dict = Depends(require_admin)):
    await db.estimates.delete_one({"id": eid})
    return {"ok": True}


@router.post("/estimates/{eid}/convert")
async def convert_estimate_to_quote(eid: str, user: dict = Depends(require_admin)):
    """Turn an estimate into a customer-facing quote showing only the final sell price."""
    est = await db.estimates.find_one({"id": eid}, {"_id": 0})
    if not est:
        raise HTTPException(404, "Estimate not found")
    if est.get("converted_quote_id"):
        raise HTTPException(400, "This estimate is already converted")
    sell = float(est.get("sell_price") or 0)
    if sell <= 0:
        raise HTTPException(400, "Add line items before converting")
    # Carry over the estimate's terms; if it has none, fall back to the tenant default quote terms.
    terms = est.get("terms")
    if not terms:
        from routers.finances import get_terms_defaults
        terms = (await get_terms_defaults())["default_quote_terms"]
    quote = {
        "id": new_id(), "customer_id": est["customer_id"], "customer_name": est.get("customer_name", ""),
        "title": est.get("title", "Estimate"), "doc_type": "quote",
        "line_items": [{"description": est.get("title", "Project"), "quantity": 1, "unit_price": sell}],
        "tax_rate": 0.0, "subtotal": sell, "tax": 0.0, "total": sell,
        "amount_paid": 0.0, "due_date": None, "status": "draft", "payment_status": "unpaid",
        "notes": est.get("notes", ""), "terms": terms,
        "from_estimate_id": eid, "created_at": now_iso(),
    }
    await db.quotes.insert_one(quote)
    quote.pop("_id", None)
    await db.estimates.update_one({"id": eid}, {"$set": {"converted_quote_id": quote["id"], "status": "converted"}})
    return quote
