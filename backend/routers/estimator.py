"""Phase 21 · Field Estimator (SimplyWise-inspired).

AI-powered on-the-spot cost estimation for pool / landscape / hardscape /
repair work. Uses vision-enabled Claude (via EMERGENT_LLM_KEY) to identify
line items + quantities from photos + description (+ optional LiDAR room
scan). Applies the tenant's rate catalog where item codes match, else
labels the price as an AI estimate the admin must confirm.

Endpoints (14) mounted under `/api/estimator/*`:
    POST /estimates                        create draft
    POST /estimates/{id}/generate          run AI pipeline (Claude vision)
    GET  /estimates                        list (filterable)
    GET  /estimates/{id}                   detail
    PATCH /estimates/{id}                  edit
    POST /estimates/{id}/regenerate-upsells
    POST /estimates/{id}/add-line-item
    DELETE /estimates/{id}/line-items/{iid}
    POST /estimates/{id}/convert-to-quote
    POST /estimates/{id}/pdf               generate branded PDF
    POST /estimates/{id}/send-to-customer  email PDF via Resend
    GET  /rate-catalog                     tenant rates
    PUT  /rate-catalog                     admin update
    POST /rate-catalog/reset-defaults      re-seed starter catalog
    GET  /settings                         estimator tenant settings
    PUT  /settings                         admin update settings

All endpoints tenant-scoped. Admin + technician can create estimates;
customer → 403. Convert-to-quote is admin-only.
"""
import base64
import io
import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from config import db, logger, EMERGENT_LLM_KEY
from utils import (
    now_iso, new_id, require_admin, get_current_user,
)
from routers.tenants import get_current_tenant

router = APIRouter()


# ═══════════════════════════════════════════════════════════════════════
# Auth helpers — admin OR technician for creation; admin-only for convert
# ═══════════════════════════════════════════════════════════════════════

async def require_admin_or_tech(user: dict = Depends(get_current_user)) -> dict:
    # Phase 5A · Feb 2026 — Field Estimator is admin/manager only. Techs
    # (pool_tech / landscape_tech / role=technician) get 403; the tile
    # is also removed from every tech nav surface (see roleNav.js +
    # ToolsHub.jsx). Keeping the function name for compat with the
    # 60+ existing @Depends() decorators below.
    role = user.get("role") or ""
    if role in {"admin", "super_admin", "manager"}:
        return user
    raise HTTPException(403, "Field Estimator is admin/manager only")


# ═══════════════════════════════════════════════════════════════════════
# Rate catalog — starter seed + CRUD
# ═══════════════════════════════════════════════════════════════════════

STARTER_RATE_CATALOG: List[Dict[str, Any]] = [
    # Labor
    {"code": "pool_tech_hourly", "description": "Pool technician (hourly)",
      "category": "labor", "unit": "hr", "default_price": 75.0},
    {"code": "landscape_crew_hourly", "description": "Landscape crew (hourly)",
      "category": "labor", "unit": "hr", "default_price": 65.0},
    {"code": "foreman_hourly", "description": "Foreman (hourly)",
      "category": "labor", "unit": "hr", "default_price": 95.0},
    {"code": "equipment_operator_hourly",
      "description": "Equipment operator (hourly)",
      "category": "labor", "unit": "hr", "default_price": 85.0},
    # Materials
    {"code": "pool_tile", "description": "Pool tile",
      "category": "material", "unit": "sqft", "default_price": 8.0},
    {"code": "coping", "description": "Coping",
      "category": "material", "unit": "linft", "default_price": 18.0},
    {"code": "pool_paver", "description": "Pool paver",
      "category": "material", "unit": "sqft", "default_price": 12.0},
    {"code": "turf", "description": "Artificial turf",
      "category": "material", "unit": "sqft", "default_price": 6.0},
    {"code": "mulch", "description": "Mulch",
      "category": "material", "unit": "yd", "default_price": 45.0},
    {"code": "retaining_wall_block",
      "description": "Retaining wall block",
      "category": "material", "unit": "sqft", "default_price": 22.0},
    {"code": "fence", "description": "Fence",
      "category": "material", "unit": "linft", "default_price": 30.0},
    {"code": "sod", "description": "Sod",
      "category": "material", "unit": "sqft", "default_price": 1.25},
    {"code": "pool_light", "description": "Pool light",
      "category": "material", "unit": "ea", "default_price": 350.0},
    {"code": "drip_line", "description": "Drip line",
      "category": "material", "unit": "linft", "default_price": 3.0},
    {"code": "irrigation_head", "description": "Irrigation head",
      "category": "material", "unit": "ea", "default_price": 45.0},
    # Equipment
    {"code": "skid_steer_rental",
      "description": "Skid steer rental (daily)",
      "category": "equipment", "unit": "ea", "default_price": 350.0},
    {"code": "auger_rental",
      "description": "Auger rental (daily)",
      "category": "equipment", "unit": "ea", "default_price": 150.0},
    # Permits
    {"code": "hoa_review", "description": "HOA review",
      "category": "permit", "unit": "ea", "default_price": 75.0},
    {"code": "city_permit_small",
      "description": "City permit (small)",
      "category": "permit", "unit": "ea", "default_price": 150.0},
    {"code": "pool_permit", "description": "Pool permit",
      "category": "permit", "unit": "ea", "default_price": 400.0},
]


async def _get_catalog(tenant_id: str) -> Dict[str, Any]:
    doc = await db.estimator_rate_catalog.find_one(
        {"tenant_id": tenant_id}, {"_id": 0}
    )
    if not doc:
        doc = {
            "tenant_id": tenant_id,
            "items": [dict(x) for x in STARTER_RATE_CATALOG],
            "created_at": now_iso(),
            "updated_at": now_iso(),
        }
        await db.estimator_rate_catalog.insert_one(dict(doc))
        doc.pop("_id", None)
    return doc


async def _get_settings(tenant_id: str) -> Dict[str, Any]:
    t = await db.tenants.find_one({"id": tenant_id}, {"_id": 0})
    s = ((t or {}).get("settings") or {}).get("estimator") or {}
    return {
        "default_markup_pct": float(s.get("default_markup_pct", 20.0)),
        "tax_rate_pct": float(s.get("tax_rate_pct", 0.0)),
        "include_upsells": bool(s.get("include_upsells", True)),
    }


class RateItem(BaseModel):
    code: str
    description: str
    category: str = Field(..., pattern="^(labor|material|equipment|permit|misc)$")
    unit: str = Field(..., pattern="^(hr|sqft|linft|ea|lb|gal|ton|yd)$")
    default_price: float


class RateCatalogIn(BaseModel):
    items: List[RateItem]


@router.get("/estimator/rate-catalog")
async def get_rate_catalog(user: dict = Depends(require_admin_or_tech),
                             tenant: dict = Depends(get_current_tenant)):
    doc = await _get_catalog(tenant["id"])
    return doc


@router.put("/estimator/rate-catalog")
async def put_rate_catalog(body: RateCatalogIn,
                             user: dict = Depends(require_admin),
                             tenant: dict = Depends(get_current_tenant)):
    """Merge-by-code upsert. Existing rows with a matching `code` have
    their fields updated; new codes are appended; codes NOT in the
    payload are left alone. Use POST /rate-catalog/replace-all for the
    destructive path or DELETE /rate-catalog/items/{code} to remove a
    single row.
    """
    doc = await _get_catalog(tenant["id"])
    by_code = {i.get("code"): dict(i)
                for i in (doc.get("items") or []) if i.get("code")}
    for incoming in body.items:
        payload = incoming.model_dump() | {"updated_by": user["id"],
                                              "updated_at": now_iso()}
        by_code[payload["code"]] = {**by_code.get(payload["code"], {}),
                                       **payload}
    merged = list(by_code.values())
    await db.estimator_rate_catalog.update_one(
        {"tenant_id": tenant["id"]},
        {"$set": {"items": merged, "updated_at": now_iso()},
         "$setOnInsert": {"tenant_id": tenant["id"],
                           "created_at": now_iso()}},
        upsert=True,
    )
    return await _get_catalog(tenant["id"])


@router.post("/estimator/rate-catalog/replace-all")
async def replace_rate_catalog(body: RateCatalogIn,
                                  user: dict = Depends(require_admin),
                                  tenant: dict = Depends(get_current_tenant)):
    """Explicit destructive replace — wipes the existing catalog and
    installs exactly the items in the payload."""
    items = [i.model_dump() | {"updated_by": user["id"],
                                 "updated_at": now_iso()}
             for i in body.items]
    await db.estimator_rate_catalog.update_one(
        {"tenant_id": tenant["id"]},
        {"$set": {"items": items, "updated_at": now_iso()},
         "$setOnInsert": {"tenant_id": tenant["id"],
                           "created_at": now_iso()}},
        upsert=True,
    )
    return await _get_catalog(tenant["id"])


@router.delete("/estimator/rate-catalog/items/{code}")
async def delete_rate_catalog_item(code: str,
                                       user: dict = Depends(require_admin),
                                       tenant: dict = Depends(get_current_tenant)):
    doc = await _get_catalog(tenant["id"])
    items = [i for i in (doc.get("items") or []) if i.get("code") != code]
    await db.estimator_rate_catalog.update_one(
        {"tenant_id": tenant["id"]},
        {"$set": {"items": items, "updated_at": now_iso()}},
    )
    return await _get_catalog(tenant["id"])


@router.post("/estimator/rate-catalog/reset-defaults")
async def reset_rate_catalog(user: dict = Depends(require_admin),
                                tenant: dict = Depends(get_current_tenant)):
    await db.estimator_rate_catalog.update_one(
        {"tenant_id": tenant["id"]},
        {"$set": {"items": [dict(x) for x in STARTER_RATE_CATALOG],
                    "updated_at": now_iso()},
         "$setOnInsert": {"tenant_id": tenant["id"],
                           "created_at": now_iso()}},
        upsert=True,
    )
    return await _get_catalog(tenant["id"])


@router.get("/estimator/settings")
async def get_estimator_settings(user: dict = Depends(require_admin_or_tech),
                                    tenant: dict = Depends(get_current_tenant)):
    return await _get_settings(tenant["id"])


class SettingsIn(BaseModel):
    default_markup_pct: Optional[float] = None
    tax_rate_pct: Optional[float] = None
    include_upsells: Optional[bool] = None


@router.put("/estimator/settings")
async def put_estimator_settings(body: SettingsIn,
                                    user: dict = Depends(require_admin),
                                    tenant: dict = Depends(get_current_tenant)):
    updates: Dict[str, Any] = {}
    for k in ("default_markup_pct", "tax_rate_pct", "include_upsells"):
        v = getattr(body, k)
        if v is not None:
            updates[f"settings.estimator.{k}"] = v
    if updates:
        await db.tenants.update_one({"id": tenant["id"]}, {"$set": updates})
    return await _get_settings(tenant["id"])


# ═══════════════════════════════════════════════════════════════════════
# Estimate CRUD
# ═══════════════════════════════════════════════════════════════════════

class PhotoIn(BaseModel):
    url: str
    width: Optional[int] = None
    height: Optional[int] = None


class RoomScanWall(BaseModel):
    start: Dict[str, float]
    end: Dict[str, float]
    height: Optional[float] = None


class RoomScanIn(BaseModel):
    walls: List[RoomScanWall] = []
    floor_area_m2: Optional[float] = None
    ceiling_height_m: Optional[float] = None


class EstimateIn(BaseModel):
    title: str
    customer_id: Optional[str] = None
    address: Optional[str] = ""
    description: str
    photos: List[PhotoIn] = []
    service_type: str = Field(..., pattern="^(pool|landscape|hardscape|repair|other)$")
    room_scan: Optional[RoomScanIn] = None
    notes: Optional[str] = ""


class LineItemIn(BaseModel):
    description: str
    quantity: float = Field(..., gt=0)
    unit: str = Field(..., pattern="^(hr|sqft|linft|ea|lb|gal|ton|yd)$")
    unit_price: float = Field(..., ge=0)
    category: str = Field(..., pattern="^(labor|material|equipment|permit|misc)$")
    code: Optional[str] = None


class EstimatePatch(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    notes: Optional[str] = None
    address: Optional[str] = None
    customer_id: Optional[str] = None
    line_items: Optional[List[Dict[str, Any]]] = None
    upsells: Optional[List[Dict[str, Any]]] = None
    markup_pct: Optional[float] = None
    tax_rate_pct: Optional[float] = None


def _compute_totals(line_items: List[Dict[str, Any]],
                     markup_pct: float, tax_rate_pct: float) -> Dict[str, float]:
    subtotal = 0.0
    for li in line_items:
        ext = float(li.get("quantity", 0)) * float(li.get("unit_price", 0))
        li["extended_price"] = round(ext, 2)
        subtotal += ext
    markup_amount = subtotal * (markup_pct / 100.0)
    taxable = subtotal + markup_amount
    tax_amount = taxable * (tax_rate_pct / 100.0)
    return {
        "subtotal": round(subtotal, 2),
        "markup_amount": round(markup_amount, 2),
        "tax_amount": round(tax_amount, 2),
        "total": round(taxable + tax_amount, 2),
    }


@router.post("/estimator/estimates")
async def create_estimate(body: EstimateIn,
                            user: dict = Depends(require_admin_or_tech),
                            tenant: dict = Depends(get_current_tenant)):
    if body.customer_id:
        cust = await db.customers.find_one(
            {"id": body.customer_id, "tenant_id": tenant["id"]},
            {"_id": 0, "id": 1, "name": 1},
        )
        if not cust:
            raise HTTPException(404, "Customer not found in tenant")
    doc: Dict[str, Any] = {
        "id": new_id(),
        "tenant_id": tenant["id"],
        "created_by": user["id"],
        "title": body.title,
        "customer_id": body.customer_id,
        "address": body.address or "",
        "description": body.description,
        "photos": [p.model_dump() for p in body.photos],
        "room_scan": body.room_scan.model_dump() if body.room_scan else None,
        "service_type": body.service_type,
        "line_items": [],
        "upsells": [],
        "subtotal": 0.0,
        "markup_pct": 20.0,
        "markup_amount": 0.0,
        "tax_rate_pct": 0.0,
        "tax_amount": 0.0,
        "total": 0.0,
        "status": "draft",
        "quote_id": None,
        "pdf_url": None,
        "notes": body.notes or "",
        "mocked": False,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "generated_at": None,
        "converted_at": None,
        "sent_at": None,
    }
    # Phase 47.2 — Apply the current year's budget markup on creation and
    # audit the source. Draft/sent estimates get re-flagged whenever the
    # budget is saved (see routers/budgets._recalc_open_estimates).
    try:
        from routers.budgets import get_current_markup
        markup_pct, from_budget = await get_current_markup(tenant["id"])
        doc["budget_markup_pct"] = markup_pct
        doc["budget_markup_source"] = "budget" if from_budget else "default"
        doc["budget_markup_applied_at"] = now_iso()
        # Also set the estimator's own markup_pct so calc math immediately
        # reflects the budget-driven number until the user overrides.
        doc["markup_pct"] = markup_pct
    except Exception as _e:
        logger.warning(f"budget markup apply skipped: {_e}")
    await db.estimator_estimates.insert_one(dict(doc))
    doc.pop("_id", None)
    return {"estimate_id": doc["id"], "estimate": doc}


async def _fetch_estimate(eid: str, tenant_id: str) -> Dict[str, Any]:
    e = await db.estimator_estimates.find_one(
        {"id": eid, "tenant_id": tenant_id}, {"_id": 0}
    )
    if not e:
        raise HTTPException(404, "Estimate not found")
    return e


@router.get("/estimator/estimates")
async def list_estimates(status: Optional[str] = None,
                           customer_id: Optional[str] = None,
                           service_type: Optional[str] = None,
                           user: dict = Depends(require_admin_or_tech),
                           tenant: dict = Depends(get_current_tenant)):
    q: Dict[str, Any] = {"tenant_id": tenant["id"]}
    if status: q["status"] = status
    if customer_id: q["customer_id"] = customer_id
    if service_type: q["service_type"] = service_type
    rows = await db.estimator_estimates.find(
        q, {"_id": 0, "photos": 0, "room_scan": 0},
    ).sort("created_at", -1).to_list(500)
    return {"items": rows, "total": len(rows)}


@router.get("/estimator/estimates/{eid}")
async def get_estimate(eid: str,
                         user: dict = Depends(require_admin_or_tech),
                         tenant: dict = Depends(get_current_tenant)):
    return await _fetch_estimate(eid, tenant["id"])


@router.patch("/estimator/estimates/{eid}")
async def patch_estimate(eid: str, body: EstimatePatch,
                           user: dict = Depends(require_admin_or_tech),
                           tenant: dict = Depends(get_current_tenant)):
    e = await _fetch_estimate(eid, tenant["id"])
    upd: Dict[str, Any] = {"updated_at": now_iso()}
    for k in ("title", "description", "notes", "address", "customer_id"):
        v = getattr(body, k)
        if v is not None: upd[k] = v
    for k in ("markup_pct", "tax_rate_pct"):
        v = getattr(body, k)
        if v is not None: upd[k] = float(v)
    if body.line_items is not None:
        upd["line_items"] = body.line_items
    if body.upsells is not None:
        upd["upsells"] = body.upsells

    merged = {**e, **upd}
    totals = _compute_totals(
        merged.get("line_items") or [],
        float(merged.get("markup_pct", 20.0)),
        float(merged.get("tax_rate_pct", 0.0)),
    )
    upd.update(totals)
    if e.get("status") in {"generated", "edited"}:
        upd["status"] = "edited"
    await db.estimator_estimates.update_one(
        {"id": eid, "tenant_id": tenant["id"]}, {"$set": upd}
    )
    return await _fetch_estimate(eid, tenant["id"])


@router.post("/estimator/estimates/{eid}/add-line-item")
async def add_line_item(eid: str, body: LineItemIn,
                          user: dict = Depends(require_admin_or_tech),
                          tenant: dict = Depends(get_current_tenant)):
    e = await _fetch_estimate(eid, tenant["id"])
    item = body.model_dump()
    item["id"] = new_id()
    item["unit_price_source"] = "manual"
    item["extended_price"] = round(item["quantity"] * item["unit_price"], 2)
    line_items = list(e.get("line_items") or []) + [item]
    totals = _compute_totals(
        line_items, float(e.get("markup_pct", 20.0)),
        float(e.get("tax_rate_pct", 0.0)),
    )
    await db.estimator_estimates.update_one(
        {"id": eid, "tenant_id": tenant["id"]},
        {"$set": {"line_items": line_items, "updated_at": now_iso(),
                    "status": "edited", **totals}},
    )
    return await _fetch_estimate(eid, tenant["id"])


@router.delete("/estimator/estimates/{eid}/line-items/{iid}")
async def delete_line_item(eid: str, iid: str,
                              user: dict = Depends(require_admin_or_tech),
                              tenant: dict = Depends(get_current_tenant)):
    e = await _fetch_estimate(eid, tenant["id"])
    line_items = [li for li in (e.get("line_items") or [])
                    if li.get("id") != iid]
    totals = _compute_totals(
        line_items, float(e.get("markup_pct", 20.0)),
        float(e.get("tax_rate_pct", 0.0)),
    )
    await db.estimator_estimates.update_one(
        {"id": eid, "tenant_id": tenant["id"]},
        {"$set": {"line_items": line_items, "updated_at": now_iso(),
                    "status": "edited", **totals}},
    )
    return await _fetch_estimate(eid, tenant["id"])


# ═══════════════════════════════════════════════════════════════════════
# AI pipeline — vision Claude → line items + upsells
# ═══════════════════════════════════════════════════════════════════════

_GENERATE_SYSTEM = (
    "You are a cost estimator for a pool & landscape contractor. Given "
    "the scope description, photos, and (optionally) a room scan, produce "
    "a JSON object with two keys:\n"
    "  line_items: array of "
    "    {code, description, category, quantity, unit, unit_price, confidence}\n"
    "  upsells: array of "
    "    {title, description, estimated_add_price_usd, rationale}\n"
    "Rules:\n"
    " - code: short snake_case identifier that matches common trade codes "
    "(e.g. pool_tech_hourly, pool_tile, mulch).\n"
    " - category: labor | material | equipment | permit | misc.\n"
    " - unit: hr | sqft | linft | ea | lb | gal | ton | yd.\n"
    " - quantity: positive number.\n"
    " - unit_price: USD, best estimate for AZ market.\n"
    " - confidence: 0-1 float — how sure you are of the estimate.\n"
    " - Produce AT LEAST 4 line items and AT LEAST 3 upsells.\n"
    "Return STRICT JSON only, no prose."
)


async def _call_generate(scope: Dict[str, Any]) -> Dict[str, Any]:
    if not EMERGENT_LLM_KEY:
        return {"mocked": True, "reason": "EMERGENT_LLM_KEY not configured",
                 "line_items": [], "upsells": []}
    try:
        from emergentintegrations.llm.chat import (
            LlmChat, UserMessage, ImageContent,
        )
    except Exception as e:
        return {"mocked": True, "reason": f"llm import failed: {e}",
                 "line_items": [], "upsells": []}
    prompt_lines = [
        f"Service type: {scope.get('service_type')}",
        f"Title: {scope.get('title')}",
        f"Scope: {scope.get('description')}",
    ]
    rs = scope.get("room_scan")
    if rs:
        prompt_lines.append(
            f"LiDAR room scan: floor_area_m2={rs.get('floor_area_m2')}, "
            f"ceiling_height_m={rs.get('ceiling_height_m')}, "
            f"walls={len(rs.get('walls') or [])}"
        )
    photos = scope.get("photos") or []
    if photos:
        prompt_lines.append(f"({len(photos)} photo(s) attached)")
    prompt = "\n".join(prompt_lines)

    try:
        chat = (LlmChat(api_key=EMERGENT_LLM_KEY, session_id=new_id(),
                         system_message=_GENERATE_SYSTEM)
                .with_model("anthropic", "claude-sonnet-4-6"))
        # Fetch each photo URL and base64-encode — the current
        # `emergentintegrations` SDK requires `ImageContent(image_base64=...)`.
        # Individual URL failures (404, timeout) are logged but do not crash
        # the whole generate call.
        file_contents = []
        skipped_photos: List[Dict[str, Any]] = []
        import base64 as _b64
        import httpx as _httpx
        async with _httpx.AsyncClient(timeout=15,
                                            follow_redirects=True) as _c:
            for p in photos[:6]:  # cap to 6 to stay within request size
                url = p.get("url") or ""
                if not url.startswith("http"):
                    continue
                try:
                    r = await _c.get(url)
                    if r.status_code != 200:
                        raise RuntimeError(f"http {r.status_code}")
                    b64 = _b64.b64encode(r.content).decode("ascii")
                    file_contents.append(ImageContent(image_base64=b64))
                except Exception as _ex:
                    logger.warning(
                        f"Estimator photo fetch failed for {url}: {_ex}")
                    skipped_photos.append({"url": url, "reason": str(_ex)})
        msg = UserMessage(text=prompt, file_contents=file_contents or None)
        raw = await chat.send_message(msg)
        text = raw if isinstance(raw, str) else str(raw)
        text = text.strip()
        if text.startswith("```"):
            text = re.sub(r"^```[a-zA-Z]*\n?|\n?```$", "", text).strip()
        try:
            data = json.loads(text)
        except Exception:
            m = re.search(r"(\{.*\})", text, re.S)
            data = json.loads(m.group(1)) if m else {}
        return {"mocked": False, "line_items": data.get("line_items") or [],
                 "upsells": data.get("upsells") or [],
                 "skipped_photos": skipped_photos}
    except Exception as e:
        logger.warning(f"Estimator generate failed: {e}")
        return {"mocked": True, "reason": f"llm error: {e}",
                 "line_items": [], "upsells": []}


def _apply_catalog(ai_items: List[Dict[str, Any]],
                    catalog_items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_code = {c["code"]: c for c in catalog_items if c.get("code")}
    out = []
    for it in ai_items:
        code = (it.get("code") or "").strip()
        cat_entry = by_code.get(code)
        qty = float(it.get("quantity", 1) or 1)
        unit = it.get("unit") or (cat_entry or {}).get("unit") or "ea"
        category = it.get("category") or (cat_entry or {}).get("category") or "misc"
        description = (it.get("description")
                        or (cat_entry or {}).get("description")
                        or code or "Item")
        if cat_entry:
            unit_price = float(cat_entry["default_price"])
            source = "tenant_rate"
            confidence = 1.0
        else:
            unit_price = float(it.get("unit_price", 0) or 0)
            source = "ai_estimate"
            try:
                confidence = float(it.get("confidence", 0.5))
            except Exception:
                confidence = 0.5
        out.append({
            "id": new_id(),
            "code": code, "description": description,
            "category": category, "quantity": round(qty, 2),
            "unit": unit,
            "unit_price": round(unit_price, 2),
            "unit_price_source": source,
            "confidence": round(confidence, 2),
            "extended_price": round(qty * unit_price, 2),
        })
    return out


@router.post("/estimator/estimates/{eid}/generate")
async def generate_estimate(eid: str,
                              user: dict = Depends(require_admin_or_tech),
                              tenant: dict = Depends(get_current_tenant)):
    e = await _fetch_estimate(eid, tenant["id"])
    catalog = await _get_catalog(tenant["id"])
    settings = await _get_settings(tenant["id"])
    ai = await _call_generate(e)
    line_items = _apply_catalog(ai.get("line_items") or [],
                                  catalog.get("items") or [])
    upsells = []
    if settings["include_upsells"]:
        for u in (ai.get("upsells") or []):
            upsells.append({
                "id": new_id(),
                "title": u.get("title") or "Upgrade",
                "description": u.get("description") or "",
                "estimated_add_price": float(
                    u.get("estimated_add_price_usd", 0) or 0),
                "rationale": u.get("rationale") or "",
            })
    markup_pct = float(settings["default_markup_pct"])
    tax_rate_pct = float(settings["tax_rate_pct"])
    totals = _compute_totals(line_items, markup_pct, tax_rate_pct)
    updates = {
        "line_items": line_items,
        "upsells": upsells,
        "markup_pct": markup_pct,
        "tax_rate_pct": tax_rate_pct,
        **totals,
        "status": "generated" if line_items else e.get("status") or "draft",
        "generated_at": now_iso(),
        "updated_at": now_iso(),
        "mocked": bool(ai.get("mocked")),
        "mocked_reason": ai.get("reason") if ai.get("mocked") else None,
    }
    await db.estimator_estimates.update_one(
        {"id": eid, "tenant_id": tenant["id"]}, {"$set": updates}
    )
    return await _fetch_estimate(eid, tenant["id"])


@router.post("/estimator/estimates/{eid}/regenerate-upsells")
async def regenerate_upsells(eid: str,
                                user: dict = Depends(require_admin_or_tech),
                                tenant: dict = Depends(get_current_tenant)):
    e = await _fetch_estimate(eid, tenant["id"])
    ai = await _call_generate(e)
    upsells = []
    for u in (ai.get("upsells") or []):
        upsells.append({
            "id": new_id(),
            "title": u.get("title") or "Upgrade",
            "description": u.get("description") or "",
            "estimated_add_price": float(
                u.get("estimated_add_price_usd", 0) or 0),
            "rationale": u.get("rationale") or "",
        })
    await db.estimator_estimates.update_one(
        {"id": eid, "tenant_id": tenant["id"]},
        {"$set": {"upsells": upsells, "updated_at": now_iso(),
                    "mocked": bool(ai.get("mocked"))}},
    )
    return {"upsells": upsells, "mocked": bool(ai.get("mocked"))}


# ═══════════════════════════════════════════════════════════════════════
# Convert to quote
# ═══════════════════════════════════════════════════════════════════════

@router.post("/estimator/estimates/{eid}/convert-to-quote")
async def convert_to_quote(eid: str,
                              user: dict = Depends(require_admin),
                              tenant: dict = Depends(get_current_tenant)):
    e = await _fetch_estimate(eid, tenant["id"])
    if e.get("status") == "converted" and e.get("quote_id"):
        return {"quote_id": e["quote_id"], "already_converted": True}
    if not e.get("customer_id"):
        raise HTTPException(400,
            "Set a customer on the estimate before converting to a quote.")
    cust = await db.customers.find_one(
        {"id": e["customer_id"], "tenant_id": tenant["id"]},
        {"_id": 0, "id": 1, "name": 1},
    )
    if not cust:
        raise HTTPException(400, "Customer not found in tenant")

    # Fold markup into per-line prices so the resulting quote total matches.
    markup_pct = float(e.get("markup_pct", 20.0))
    factor = 1.0 + (markup_pct / 100.0)
    quote_items: List[Dict[str, Any]] = []
    for li in (e.get("line_items") or []):
        quote_items.append({
            "description": li.get("description") or li.get("code") or "Item",
            "quantity": float(li.get("quantity", 1) or 1),
            "unit_price": round(float(li.get("unit_price", 0) or 0) * factor, 2),
            "category": li.get("category") or "misc",
            "unit": li.get("unit") or "ea",
        })
    tax_rate = float(e.get("tax_rate_pct", 0.0)) / 100.0
    subtotal = sum(li["quantity"] * li["unit_price"] for li in quote_items)
    tax = round(subtotal * tax_rate, 2)
    total = round(subtotal + tax, 2)
    quote_doc = {
        "id": new_id(),
        "tenant_id": tenant["id"],
        "customer_id": e["customer_id"],
        "customer_name": cust["name"],
        "title": e.get("title") or "Estimate",
        "doc_type": "quote",
        "line_items": quote_items,
        "tax_rate": tax_rate,
        "subtotal": round(subtotal, 2),
        "tax": tax,
        "total": total,
        "amount_paid": 0.0,
        "status": "draft",
        "payment_status": "unpaid",
        "notes": e.get("notes") or "",
        "terms": None,
        "source_estimate_id": e["id"],
        "created_at": now_iso(),
    }
    await db.quotes.insert_one(dict(quote_doc))
    await db.estimator_estimates.update_one(
        {"id": eid, "tenant_id": tenant["id"]},
        {"$set": {"status": "converted", "quote_id": quote_doc["id"],
                    "converted_at": now_iso(), "updated_at": now_iso()}},
    )
    return {"quote_id": quote_doc["id"], "estimate_id": eid}


# ═══════════════════════════════════════════════════════════════════════
# PDF + Email
# ═══════════════════════════════════════════════════════════════════════

def _estimate_html(e: Dict[str, Any], tenant: Dict[str, Any]) -> str:
    brand = tenant.get("name") or "Your Business"
    color = ((tenant.get("brand") or {}).get("primary_color")
              or "#0284C7")
    # Phase 33 · Feb 2026 — brand logo header. Reads the tenant's
    # public logo URL; falls back to the shared "logo-full.png" served
    # by the frontend so estimates delivered as PDFs / emails always
    # carry brand identity even for tenants that haven't set their own.
    logo_url = (((tenant.get("settings") or {}).get("business_card")
                 or {}).get("logo_url")
                or tenant.get("logo_url")
                or "https://app.plofv.com/logo-full.png")
    logo_html = (
        f'<div style="text-align:center;margin-bottom:16px;">'
        f'<img src="{logo_url}" alt="Pool &amp; Landscaping of Vistancia" '
        f'style="height:120px;max-width:60%;object-fit:contain;"/></div>'
    )
    items_html = "".join(
        f'<tr><td>{li.get("description","")}</td>'
        f'<td>{li.get("quantity","")} {li.get("unit","")}</td>'
        f'<td>${float(li.get("unit_price",0)):.2f}'
        f'<span class="src">{li.get("unit_price_source","")}</span></td>'
        f'<td class="r">${float(li.get("extended_price",0)):.2f}</td></tr>'
        for li in (e.get("line_items") or [])
    )
    upsell_html = "".join(
        f'<div class="up"><b>{u.get("title","")}</b>'
        f'<span class="up-p">+${float(u.get("estimated_add_price",0)):.0f}</span>'
        f'<p>{u.get("description","")}</p>'
        f'<em>{u.get("rationale","")}</em></div>'
        for u in (e.get("upsells") or [])
    )
    css = (
        "body{font-family:-apple-system,'Inter',sans-serif;color:#0F172A;"
        "margin:0;padding:32px;background:#FFF}"
        f".hdr{{background:{color};color:#fff;padding:24px 32px;"
        "border-radius:16px;margin-bottom:24px}}"
        ".hdr h1{margin:0;font-size:26px}"
        ".hdr .brand{font-size:12px;opacity:.9}"
        "table{width:100%;border-collapse:collapse;margin:16px 0}"
        "th,td{padding:8px;border-bottom:1px solid #E2E8F0;font-size:12px;"
        "text-align:left}"
        "th{background:#F1F5F9;text-transform:uppercase;font-size:10px}"
        ".r{text-align:right}"
        ".src{font-size:9px;background:#EFF6FF;color:#1E40AF;"
        "padding:1px 6px;border-radius:99px;margin-left:6px}"
        ".totals{margin-top:16px;padding:16px;background:#F1F5F9;"
        "border-radius:12px;font-size:13px}"
        ".totals .l{display:flex;justify-content:space-between;padding:4px 0}"
        ".totals .tot{font-weight:700;font-size:18px;"
        "border-top:2px solid #0F172A;margin-top:8px;padding-top:8px}"
        ".up{border:1px solid #E2E8F0;border-radius:10px;padding:12px;"
        "margin:8px 0;font-size:12px}"
        ".up-p{float:right;color:#059669;font-weight:700}"
        ".up p{margin:4px 0;color:#475569}"
        ".up em{font-size:11px;color:#94A3B8}"
    )
    return (
        f'<!doctype html><html><head><meta charset="utf-8">'
        f'<title>Estimate · {e.get("title","")}</title>'
        f'<style>{css}</style></head><body>'
        f'{logo_html}'
        f'<div class="hdr"><h1>{e.get("title","")}</h1>'
        f'<div class="brand">{brand} · Estimate #{e["id"][:8]}</div></div>'
        f'<p><b>Scope:</b> {e.get("description","")}</p>'
        f'<table><thead><tr><th>Description</th><th>Qty</th>'
        f'<th>Unit price</th><th class="r">Total</th></tr></thead>'
        f'<tbody>{items_html}</tbody></table>'
        f'<div class="totals">'
        f'<div class="l"><span>Subtotal</span>'
        f'<span>${e.get("subtotal",0):.2f}</span></div>'
        f'<div class="l"><span>Markup ({e.get("markup_pct",0):.1f}%)</span>'
        f'<span>${e.get("markup_amount",0):.2f}</span></div>'
        f'<div class="l"><span>Tax ({e.get("tax_rate_pct",0):.1f}%)</span>'
        f'<span>${e.get("tax_amount",0):.2f}</span></div>'
        f'<div class="l tot"><span>Total</span>'
        f'<span>${e.get("total",0):.2f}</span></div></div>'
        + (f'<h2>Suggested add-ons</h2>{upsell_html}' if upsell_html else "")
        + f'<p class="src" style="margin-top:24px">Prices shown are estimates. '
        f'AI-estimated items should be reviewed for your specific market.</p>'
        f'</body></html>'
    )


def _estimate_pdf(e: Dict[str, Any], tenant: Dict[str, Any]) -> Optional[bytes]:
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.lib import colors as rlc
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import inch
        from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer,
                                          Table, TableStyle)
        buf = io.BytesIO()
        doc = SimpleDocTemplate(buf, pagesize=letter,
                                  leftMargin=0.6*inch, rightMargin=0.6*inch,
                                  topMargin=0.6*inch, bottomMargin=0.6*inch)
        styles = getSampleStyleSheet()
        color_hex = (((tenant.get("brand") or {}).get("primary_color")
                       or "#0284C7").lstrip("#"))
        try:
            brand_color = rlc.HexColor("#" + color_hex)
        except Exception:
            brand_color = rlc.HexColor("#0284C7")
        title_style = ParagraphStyle("t", parent=styles["Title"],
                                       fontSize=22, textColor=brand_color)
        h2 = ParagraphStyle("h2", parent=styles["Heading2"],
                              textColor=brand_color, spaceAfter=6)
        body = styles["BodyText"]
        flow = []
        brand = tenant.get("name") or "Your Business"
        flow.append(Paragraph(e.get("title") or "Estimate", title_style))
        flow.append(Paragraph(f"{brand} · Estimate #{e['id'][:8]}",
                               styles["Italic"]))
        flow.append(Spacer(1, 10))
        if e.get("description"):
            flow.append(Paragraph(f"<b>Scope:</b> {e['description']}", body))
            flow.append(Spacer(1, 8))
        rows = [["Description", "Qty", "Unit price", "Source", "Total"]]
        for li in (e.get("line_items") or []):
            rows.append([
                li.get("description", "")[:60],
                f'{li.get("quantity","")} {li.get("unit","")}',
                f'${float(li.get("unit_price",0)):.2f}',
                (li.get("unit_price_source") or "")[:8],
                f'${float(li.get("extended_price",0)):.2f}',
            ])
        tbl = Table(rows, hAlign="LEFT",
                     colWidths=[2.8*inch, 0.9*inch, 1.0*inch, 0.9*inch, 1.0*inch])
        tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), brand_color),
            ("TEXTCOLOR", (0, 0), (-1, 0), rlc.white),
            ("GRID", (0, 0), (-1, -1), 0.25, rlc.lightgrey),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("ALIGN", (2, 1), (-1, -1), "RIGHT"),
        ]))
        flow.append(tbl)
        flow.append(Spacer(1, 12))
        flow.append(Paragraph(
            f"Subtotal: ${e.get('subtotal',0):.2f} · "
            f"Markup ({e.get('markup_pct',0):.1f}%): ${e.get('markup_amount',0):.2f} · "
            f"Tax: ${e.get('tax_amount',0):.2f} · "
            f"<b>Total: ${e.get('total',0):.2f}</b>", body,
        ))
        if e.get("upsells"):
            flow.append(Spacer(1, 12))
            flow.append(Paragraph("Suggested add-ons", h2))
            for u in e["upsells"]:
                flow.append(Paragraph(
                    f"<b>{u.get('title','')}</b> · "
                    f"+${float(u.get('estimated_add_price',0)):.0f}",
                    body,
                ))
                flow.append(Paragraph(u.get("description", ""), body))
                flow.append(Spacer(1, 4))
        flow.append(Spacer(1, 20))
        flow.append(Paragraph(
            "<i>Prices shown are estimates. AI-estimated items should be "
            "reviewed for your specific market.</i>", body,
        ))
        doc.build(flow)
        return buf.getvalue()
    except Exception as ex:
        logger.warning(f"Estimate PDF failed: {ex}")
        return None


@router.post("/estimator/estimates/{eid}/pdf")
async def estimate_pdf(eid: str,
                         user: dict = Depends(require_admin_or_tech),
                         tenant: dict = Depends(get_current_tenant)):
    e = await _fetch_estimate(eid, tenant["id"])
    file_url = f"/api/estimator/estimates/{eid}/pdf.file"
    await db.estimator_estimates.update_one(
        {"id": eid, "tenant_id": tenant["id"]},
        {"$set": {"pdf_url": file_url, "updated_at": now_iso()}},
    )
    return {"pdf_url": file_url, "file_url": file_url}


@router.get("/estimator/estimates/{eid}/pdf.file")
async def estimate_pdf_file(eid: str,
                              user: dict = Depends(require_admin_or_tech),
                              tenant: dict = Depends(get_current_tenant)):
    e = await _fetch_estimate(eid, tenant["id"])
    t = await db.tenants.find_one({"id": tenant["id"]}, {"_id": 0}) or {}
    pdf = _estimate_pdf(e, t)
    if pdf:
        return StreamingResponse(
            io.BytesIO(pdf), media_type="application/pdf",
            headers={"Content-Disposition":
                       f'attachment; filename="estimate-{eid[:8]}.pdf"'},
        )
    content = _estimate_html(e, t).encode("utf-8")
    return StreamingResponse(
        io.BytesIO(content), media_type="text/html; charset=utf-8",
        headers={"Content-Disposition":
                   f'attachment; filename="estimate-{eid[:8]}.html"',
                 "X-Pdf-Fallback": "true"},
    )


class SendIn(BaseModel):
    recipient_emails: List[str]
    subject: Optional[str] = None
    body: Optional[str] = None


@router.post("/estimator/estimates/{eid}/send-to-customer")
async def send_estimate(eid: str, body: SendIn,
                          user: dict = Depends(require_admin),
                          tenant: dict = Depends(get_current_tenant)):
    e = await _fetch_estimate(eid, tenant["id"])
    to = [x.strip().lower() for x in (body.recipient_emails or []) if x.strip()]
    if not to:
        raise HTTPException(400, "At least one recipient email required")
    from config import RESEND_API_KEY, EMAIL_FROM
    if not RESEND_API_KEY:
        return {"sent": False, "reason": "resend-not-configured", "to": to}
    t = await db.tenants.find_one({"id": tenant["id"]}, {"_id": 0}) or {}
    pdf = _estimate_pdf(e, t)
    attachment_type = "pdf" if pdf else "html"
    attachment_bytes = pdf if pdf else _estimate_html(e, t).encode("utf-8")
    fname = (f"estimate-{eid[:8]}.pdf" if pdf
              else f"estimate-{eid[:8]}.html")
    # Phase B1 · F2b polish — count F0 attachments linked to this
    # estimate (purpose=invoice_attachment, shared with invoices — see
    # components/quotes/InvoiceAttachments.jsx). Renders "N attachments
    # included" copy above the total when N > 0.
    try:
        attach_n = await db.files.count_documents({
            "purpose": "invoice_attachment",
            "linked_entity_id": eid,
            "deleted_at": None,
        })
    except Exception:                                                # noqa: BLE001
        attach_n = 0
    attach_line = ""
    if attach_n > 0:
        noun = "attachment" if attach_n == 1 else "attachments"
        attach_line = (
            f'<p style="font-size:13px;color:#475569;margin:8px 0 0;">'
            f'📎 {attach_n} {noun} included</p>'
        )
    try:
        import resend
        resend.api_key = RESEND_API_KEY
        resend.Emails.send({
            "from": EMAIL_FROM or "onboarding@resend.dev",
            "to": to,
            "subject": (body.subject
                          or f"Estimate · {e.get('title','')} "
                          f"({t.get('name') or 'Pool & Landscaping'})"),
            "html": (body.body
                       or f"<p>Please find your estimate attached.</p>"
                       f"<p>Total: <b>${e.get('total',0):.2f}</b></p>"
                       f"{attach_line}"),
            "attachments": [{
                "filename": fname,
                "content": base64.b64encode(attachment_bytes).decode("ascii"),
            }],
        })
        await db.estimator_estimates.update_one(
            {"id": eid, "tenant_id": tenant["id"]},
            {"$set": {"sent_at": now_iso(), "status": "sent",
                        "last_sent_to": to, "updated_at": now_iso()}},
        )
        return {"sent": True, "to": to, "attachment_type": attachment_type}
    except Exception as ex:
        logger.warning(f"Estimate send failed: {ex}")
        return {"sent": False, "reason": str(ex), "to": to,
                 "attachment_type": attachment_type}
