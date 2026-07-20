"""QuoteIQ Phase Q2 · Backend router — AI Estimator drafts +
Options Estimates.

Exposes:

* ``POST /api/ai-estimator/generate`` — creates a draft, debits credits,
  invokes the LLM, persists the result.
* ``GET  /api/ai-estimator/drafts`` (paginated).
* ``GET  /api/ai-estimator/drafts/{id}``.
* ``PATCH /api/ai-estimator/drafts/{id}`` — user refinements.
* ``POST /api/ai-estimator/drafts/{id}/promote`` — draft → real estimate.
* ``POST /api/estimates/{eid}/enable-options`` — toggle options mode
  on an existing estimate; body carries the tier block.
* ``POST /api/estimates/{eid}/select-option`` (admin).
* ``POST /api/public/estimates/{token}/select-option`` (unauthenticated).
* ``POST /api/estimates/{eid}/convert-to-job`` — respects the currently
  selected tier when ``options.enabled=true``.
"""
from __future__ import annotations

import hmac
import hashlib
import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from config import db, logger
from utils import (get_current_user, require_admin, new_id, now_iso)
from routers.tenants import get_current_tenant
from services.ai_credits import debit_credits
from services.ai_estimator import generate_estimate


router = APIRouter(tags=["AI Estimator"])


# ═════════════════════════════════════════════════════════════════════
# AI Estimator drafts
# ═════════════════════════════════════════════════════════════════════

class EstimatorGenerateIn(BaseModel):
    photo_urls: List[str] = Field(default_factory=list, max_length=12)
    job_description: str = Field(..., min_length=3, max_length=4000)
    customer_id: Optional[str] = None
    service_area_sqft: Optional[float] = None
    pool_size_gallons: Optional[int] = None
    options_mode: bool = False


class DraftPatchIn(BaseModel):
    line_items: Optional[List[Dict[str, Any]]] = None
    tiers: Optional[List[Dict[str, Any]]] = None
    job_description: Optional[str] = None


class PromoteIn(BaseModel):
    customer_id: Optional[str] = Field(
        None,
        description="Required at promote time — falls back to the draft's customer_id. Estimates must attach to a customer.",
    )
    title: Optional[str] = None
    tier_id: Optional[str] = None  # options-mode: which tier to promote as-selected


def _draft_credit_cost(options_mode: bool) -> int:
    return 10 + (10 if options_mode else 0)  # 10 base, +10 for 3 tiers


@router.post("/ai-estimator/generate")
async def generate(body: EstimatorGenerateIn,
                     user: dict = Depends(require_admin),
                     tenant: dict = Depends(get_current_tenant)):
    draft_id = new_id()
    cost = _draft_credit_cost(body.options_mode)
    # Debit first — feature-cost auditing is more important than pre-check.
    debit = await debit_credits(
        tenant["id"], cost, feature="estimator",
        ref_id=draft_id, ref_type="ai_estimate_draft",
        reason="ai_estimator_generate", actor_user_id=user.get("id"),
    )
    doc: Dict[str, Any] = {
        "id": draft_id,
        "tenant_id": tenant["id"],
        "created_by": user.get("id"),
        "source": "photos" if body.photo_urls else "manual",
        "photo_urls": body.photo_urls,
        "job_description": body.job_description,
        "customer_id": body.customer_id,
        "service_area_sqft": body.service_area_sqft,
        "pool_size_gallons": body.pool_size_gallons,
        "options_mode": body.options_mode,
        "status": "pending",
        "credits_debited": cost,
        "line_items": [],
        "tiers": [],
        "suggested_total_cents": 0,
        "model": "claude-sonnet-4-5",
        "credit_warning": bool(debit.get("warning")),
        "created_at": now_iso(),
        "completed_at": None,
        "error": None,
    }
    result = await generate_estimate(
        tenant_id=tenant["id"],
        photo_urls=body.photo_urls,
        job_description=body.job_description,
        options_mode=body.options_mode,
        extras={"customer_id": body.customer_id,
                 "service_area_sqft": body.service_area_sqft,
                 "pool_size_gallons": body.pool_size_gallons},
    )
    if result.get("error"):
        doc["status"] = "error"
        doc["error"] = result["error"]
    else:
        doc["status"] = "complete"
        doc["completed_at"] = now_iso()
        if body.options_mode:
            doc["tiers"] = result.get("tiers") or []
            default = next((t for t in doc["tiers"] if t.get("is_default")),
                             doc["tiers"][0] if doc["tiers"] else None)
            doc["suggested_total_cents"] = int((default or {}).get("total_cents") or 0)
        else:
            doc["line_items"] = result.get("line_items") or []
            doc["suggested_total_cents"] = sum(
                int(li.get("subtotal_cents") or 0)
                for li in doc["line_items"])
        doc["notes"] = result.get("notes", "")
    await db.ai_estimate_drafts.insert_one(doc)
    doc.pop("_id", None)
    return {"draft": doc,
            "credits_balance_after": debit.get("balance_after"),
            "credit_warning": bool(debit.get("warning"))}


@router.get("/ai-estimator/drafts")
async def list_drafts(user: dict = Depends(require_admin),
                        tenant: dict = Depends(get_current_tenant),
                        status: Optional[str] = Query(None),
                        limit: int = Query(20, ge=1, le=200),
                        cursor: Optional[str] = Query(None)):
    q: Dict[str, Any] = {"tenant_id": tenant["id"]}
    if status:
        q["status"] = status
    if cursor:
        q["created_at"] = {"$lt": cursor}
    rows = await db.ai_estimate_drafts.find(q, {"_id": 0}) \
        .sort("created_at", -1).to_list(limit)
    return {"count": len(rows), "drafts": rows,
            "next_cursor": rows[-1]["created_at"] if len(rows) == limit else None}


@router.get("/ai-estimator/drafts/{did}")
async def get_draft(did: str,
                      user: dict = Depends(require_admin),
                      tenant: dict = Depends(get_current_tenant)):
    row = await db.ai_estimate_drafts.find_one(
        {"id": did, "tenant_id": tenant["id"]}, {"_id": 0})
    if not row:
        raise HTTPException(404, "draft not found")
    return row


@router.patch("/ai-estimator/drafts/{did}")
async def patch_draft(did: str, body: DraftPatchIn,
                        user: dict = Depends(require_admin),
                        tenant: dict = Depends(get_current_tenant)):
    row = await db.ai_estimate_drafts.find_one(
        {"id": did, "tenant_id": tenant["id"]}, {"_id": 0})
    if not row:
        raise HTTPException(404, "draft not found")
    upd: Dict[str, Any] = {"updated_at": now_iso()}
    if body.line_items is not None:
        upd["line_items"] = body.line_items
        upd["suggested_total_cents"] = sum(
            int(li.get("subtotal_cents") or 0) for li in body.line_items)
    if body.tiers is not None:
        upd["tiers"] = body.tiers
        for t in body.tiers:
            t["total_cents"] = sum(
                int(li.get("subtotal_cents") or 0)
                for li in (t.get("line_items") or []))
        default = next((t for t in body.tiers if t.get("is_default")),
                         body.tiers[0] if body.tiers else None)
        upd["suggested_total_cents"] = int((default or {}).get("total_cents") or 0)
    if body.job_description is not None:
        upd["job_description"] = body.job_description
    await db.ai_estimate_drafts.update_one(
        {"id": did, "tenant_id": tenant["id"]}, {"$set": upd})
    return await db.ai_estimate_drafts.find_one(
        {"id": did, "tenant_id": tenant["id"]}, {"_id": 0})


@router.delete("/ai-estimator/drafts/{did}", status_code=204)
async def delete_draft(did: str,
                         user: dict = Depends(require_admin),
                         tenant: dict = Depends(get_current_tenant)):
    r = await db.ai_estimate_drafts.delete_one(
        {"id": did, "tenant_id": tenant["id"]})
    if not r.deleted_count:
        raise HTTPException(404, "draft not found")
    return None


def _line_to_estimate_line(li: Dict[str, Any]) -> Dict[str, Any]:
    """Convert an AI-draft line item to an Estimate line item shape."""
    return {
        "category": "Material",
        "description": li.get("description") or li.get("sku") or "",
        "quantity": float(li.get("qty") or 0),
        "unit_cost": (int(li.get("unit_price_cents") or 0) / 100.0),
        "item_id": li.get("sku") or li.get("service_slug"),
    }


@router.post("/ai-estimator/drafts/{did}/promote")
async def promote_draft(did: str, body: PromoteIn,
                          user: dict = Depends(require_admin),
                          tenant: dict = Depends(get_current_tenant)):
    row = await db.ai_estimate_drafts.find_one(
        {"id": did, "tenant_id": tenant["id"]}, {"_id": 0})
    if not row:
        raise HTTPException(404, "draft not found")
    if row.get("status") != "complete":
        raise HTTPException(400, f"draft is {row.get('status')}, cannot promote")
    customer_id = body.customer_id or row.get("customer_id")
    if not customer_id:
        raise HTTPException(422, "customer_id required to promote to estimate")

    est_id = new_id()
    title = body.title or (row.get("job_description") or "AI-generated estimate")[:120]
    now = now_iso()
    doc: Dict[str, Any] = {
        "id": est_id,
        "tenant_id": tenant["id"],
        "customer_id": customer_id,
        "title": title,
        "line_items": [],
        "overhead_pct": 0.0,
        "margin_pct": 0.0,
        "notes": row.get("notes") or "",
        "terms": None,
        "status": "draft",
        "source": "ai",
        "ai_draft_id": did,
        "created_by": user.get("id"),
        "created_at": now,
        "updated_at": now,
    }
    if row.get("options_mode") and row.get("tiers"):
        tiers = []
        for t in row["tiers"]:
            tier_lines = [_line_to_estimate_line(li) for li in t.get("line_items") or []]
            tiers.append({
                "id": t.get("id") or new_id(),
                "name": t.get("name") or "Tier",
                "description": t.get("description") or "",
                "line_items": tier_lines,
                "total_cents": int(t.get("total_cents") or 0),
                "is_default": bool(t.get("is_default")),
            })
        # Ensure exactly one default.
        if not any(x["is_default"] for x in tiers) and tiers:
            tiers[min(len(tiers) - 1, 1)]["is_default"] = True
        default_tier = next(t for t in tiers if t["is_default"])
        doc["options"] = {"enabled": True, "tiers": tiers,
                            "selected_tier_id": (body.tier_id or default_tier["id"])}
        selected = next((t for t in tiers if t["id"] == doc["options"]["selected_tier_id"]),
                          default_tier)
        doc["line_items"] = selected["line_items"]
        doc["total_cents"] = int(selected.get("total_cents") or 0)
    else:
        doc["line_items"] = [_line_to_estimate_line(li)
                               for li in row.get("line_items") or []]
        doc["total_cents"] = int(row.get("suggested_total_cents") or 0)
        doc["options"] = {"enabled": False}
    await db.estimates.insert_one(doc)
    doc.pop("_id", None)
    return {"ok": True, "estimate_id": est_id, "estimate": doc}


# ═════════════════════════════════════════════════════════════════════
# Options Estimates (Good/Better/Best)
# ═════════════════════════════════════════════════════════════════════

class TierIn(BaseModel):
    id: Optional[str] = None
    name: str
    description: Optional[str] = ""
    line_items: List[Dict[str, Any]] = Field(default_factory=list)
    is_default: Optional[bool] = False


class EnableOptionsIn(BaseModel):
    tiers: List[TierIn] = Field(..., min_length=1, max_length=5)


class SelectOptionIn(BaseModel):
    tier_id: str


def _tier_total_cents(tier: Dict[str, Any]) -> int:
    total = 0
    for li in tier.get("line_items") or []:
        try:
            qty = float(li.get("quantity") or li.get("qty") or 0)
        except (TypeError, ValueError):
            qty = 0.0
        try:
            unit = float(li.get("unit_cost") or 0)
        except (TypeError, ValueError):
            unit = 0.0
        unit_cents = int(round(unit * 100)) if unit > 0 else int(
            li.get("unit_price_cents") or 0)
        try:
            sub = int(li.get("subtotal_cents") or round(qty * unit_cents))
        except (TypeError, ValueError):
            sub = 0
        total += sub
    return total


@router.post("/estimates/{eid}/enable-options")
async def enable_options(eid: str, body: EnableOptionsIn,
                           user: dict = Depends(require_admin),
                           tenant: dict = Depends(get_current_tenant)):
    est = await db.estimates.find_one(
        {"id": eid, "tenant_id": tenant["id"]}, {"_id": 0})
    if not est:
        raise HTTPException(404, "estimate not found")
    tiers = []
    for t in body.tiers:
        tier_id = t.id or new_id()
        li = t.line_items or []
        tiers.append({
            "id": tier_id, "name": t.name, "description": t.description or "",
            "line_items": li, "is_default": bool(t.is_default),
            "total_cents": _tier_total_cents({"line_items": li}),
        })
    if not any(t["is_default"] for t in tiers):
        tiers[min(len(tiers) - 1, 1)]["is_default"] = True
    default = next(t for t in tiers if t["is_default"])
    upd = {
        "options": {"enabled": True, "tiers": tiers,
                    "selected_tier_id": default["id"]},
        "line_items": default["line_items"],
        "total_cents": default["total_cents"],
        "updated_at": now_iso(),
    }
    await db.estimates.update_one(
        {"id": eid, "tenant_id": tenant["id"]}, {"$set": upd})
    return await db.estimates.find_one(
        {"id": eid, "tenant_id": tenant["id"]}, {"_id": 0})


async def _apply_selection(est: Dict[str, Any], tier_id: str) -> Dict[str, Any]:
    opts = est.get("options") or {}
    tiers = opts.get("tiers") or []
    target = next((t for t in tiers if t.get("id") == tier_id), None)
    if not target:
        raise HTTPException(422, "tier_id not on this estimate")
    upd = {
        "options.selected_tier_id": tier_id,
        "line_items": target.get("line_items") or [],
        "total_cents": int(target.get("total_cents") or 0),
        "updated_at": now_iso(),
    }
    await db.estimates.update_one(
        {"id": est["id"], "tenant_id": est["tenant_id"]}, {"$set": upd})
    return await db.estimates.find_one(
        {"id": est["id"], "tenant_id": est["tenant_id"]}, {"_id": 0})


@router.post("/estimates/{eid}/select-option")
async def select_option(eid: str, body: SelectOptionIn,
                          user: dict = Depends(require_admin),
                          tenant: dict = Depends(get_current_tenant)):
    est = await db.estimates.find_one(
        {"id": eid, "tenant_id": tenant["id"]}, {"_id": 0})
    if not est:
        raise HTTPException(404, "estimate not found")
    if not (est.get("options") or {}).get("enabled"):
        raise HTTPException(400, "estimate is not options-enabled")
    return await _apply_selection(est, body.tier_id)


def _sign_estimate_token(tenant_id: str, estimate_id: str) -> str:
    secret = os.environ.get("JWT_SECRET") or "dev"
    payload = f"{tenant_id}|{estimate_id}|estimate_public".encode("utf-8")
    return hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()[:32]


def _verify_estimate_token(tenant_id: str, estimate_id: str, tok: str) -> bool:
    return hmac.compare_digest(_sign_estimate_token(tenant_id, estimate_id), tok)


@router.get("/estimates/{eid}/public-link")
async def public_link(eid: str,
                        user: dict = Depends(require_admin),
                        tenant: dict = Depends(get_current_tenant)):
    est = await db.estimates.find_one(
        {"id": eid, "tenant_id": tenant["id"]}, {"_id": 0})
    if not est:
        raise HTTPException(404, "estimate not found")
    return {"token": _sign_estimate_token(tenant["id"], eid),
            "estimate_id": eid, "tenant_id": tenant["id"]}


@router.post("/public/estimates/{token}/select-option")
async def public_select_option(token: str, body: SelectOptionIn,
                                 estimate_id: str = Query(...),
                                 tenant_id: str = Query(...)):
    if not _verify_estimate_token(tenant_id, estimate_id, token):
        raise HTTPException(403, "invalid or expired token")
    est = await db.estimates.find_one(
        {"id": estimate_id, "tenant_id": tenant_id}, {"_id": 0})
    if not est:
        raise HTTPException(404, "estimate not found")
    if not (est.get("options") or {}).get("enabled"):
        raise HTTPException(400, "estimate is not options-enabled")
    return await _apply_selection(est, body.tier_id)


@router.post("/estimates/{eid}/convert-to-job")
async def estimate_convert_to_job(eid: str,
                                     user: dict = Depends(require_admin),
                                     tenant: dict = Depends(get_current_tenant)):
    est = await db.estimates.find_one(
        {"id": eid, "tenant_id": tenant["id"]}, {"_id": 0})
    if not est:
        raise HTTPException(404, "estimate not found")
    # If options-enabled, use the selected-tier line_items (already
    # materialized onto the top level by enable/select handlers).
    now = now_iso()
    job_id = new_id()
    job = {
        "id": job_id, "tenant_id": tenant["id"],
        "customer_id": est.get("customer_id"),
        "title": est.get("title") or "Converted estimate",
        "notes": est.get("notes") or "",
        "estimated_value_cents": int(est.get("total_cents") or 0),
        "status": "scheduled",
        "source_estimate_id": eid,
        "created_at": now, "updated_at": now,
    }
    if (est.get("options") or {}).get("enabled"):
        job["selected_tier_id"] = est["options"].get("selected_tier_id")
        selected_tier = next(
            (t for t in est["options"].get("tiers") or []
              if t.get("id") == job["selected_tier_id"]), None)
        if selected_tier:
            job["title"] = f"{job['title']} — {selected_tier.get('name')}"
    await db.jobs.insert_one(job)
    await db.estimates.update_one(
        {"id": eid, "tenant_id": tenant["id"]},
        {"$set": {"status": "converted", "converted_job_id": job_id,
                  "updated_at": now}},
    )
    return {"ok": True, "job_id": job_id}
