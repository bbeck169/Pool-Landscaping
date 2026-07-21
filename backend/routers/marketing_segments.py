"""Feb-2026 · Marketing Slice M4 — Segments admin router."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel

from config import db, logger
from utils import new_id, now_iso, require_admin
from routers.tenants import get_current_tenant
from services.marketing.segments import (
    FIELD_SCHEMA, evaluate_conditions, validate_conditions,
)

router = APIRouter()


class SegmentIn(BaseModel):
    name: str
    description: Optional[str] = ""
    conditions: List[Dict[str, Any]] = []
    active: bool = True


class SegmentPatch(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    conditions: Optional[List[Dict[str, Any]]] = None
    active: Optional[bool] = None


class AdhocPreview(BaseModel):
    conditions: List[Dict[str, Any]]


# ── Static-path routes FIRST ───────────────────────────────────────────────
@router.get("/marketing/audience-segments/schema")
async def get_schema(user: dict = Depends(require_admin)):
    return {"fields": FIELD_SCHEMA}


@router.post("/marketing/audience-segments/preview-adhoc")
async def preview_adhoc(
    body: AdhocPreview,
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    try:
        r = await evaluate_conditions(body.conditions, tenant["id"])
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    return {"count": r["count"], "sample": r["sample"]}


@router.get("/marketing/audience-segments")
async def list_segments(
    active: Optional[bool] = Query(None),
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    q: Dict[str, Any] = {"tenant_id": tenant["id"]}
    if active is not None:
        q["active"] = active
    rows = await db.marketing_audience_segments.find(q, {"_id": 0}).sort(
        [("system", -1), ("updated_at", -1)],
    ).to_list(500)
    return {"segments": rows, "count": len(rows)}


@router.post("/marketing/audience-segments", status_code=201)
async def create_segment(
    body: SegmentIn,
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    try:
        validate_conditions(body.conditions)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    doc = {
        "id": new_id(), "tenant_id": tenant["id"],
        "name": body.name.strip(),
        "description": (body.description or "").strip(),
        "conditions": body.conditions,
        "match_count_cached": None, "match_count_cached_at": None,
        "active": bool(body.active), "system": False,
        "created_at": now_iso(), "updated_at": now_iso(),
        "created_by": user.get("id"),
    }
    await db.marketing_audience_segments.insert_one(doc)
    doc.pop("_id", None)
    return doc


# ── {sid}-scoped routes ────────────────────────────────────────────────────
@router.get("/marketing/audience-segments/{sid}")
async def get_segment(sid: str, user: dict = Depends(require_admin),
                       tenant: dict = Depends(get_current_tenant)):
    row = await db.marketing_audience_segments.find_one(
        {"id": sid, "tenant_id": tenant["id"]}, {"_id": 0},
    )
    if not row: raise HTTPException(404, "Segment not found")
    return row


@router.patch("/marketing/audience-segments/{sid}")
async def patch_segment(sid: str, body: SegmentPatch,
                         user: dict = Depends(require_admin),
                         tenant: dict = Depends(get_current_tenant)):
    row = await db.marketing_audience_segments.find_one(
        {"id": sid, "tenant_id": tenant["id"]}, {"_id": 0},
    )
    if not row: raise HTTPException(404, "Segment not found")
    patch: Dict[str, Any] = {}
    for field in ("name", "description", "conditions", "active"):
        val = getattr(body, field)
        if val is not None:
            patch[field] = val
    if "conditions" in patch:
        try: validate_conditions(patch["conditions"])
        except ValueError as exc: raise HTTPException(422, str(exc))
    if not patch: return row
    patch["updated_at"] = now_iso()
    await db.marketing_audience_segments.update_one({"id": sid}, {"$set": patch})
    row.update(patch)
    return row


@router.delete("/marketing/audience-segments/{sid}", status_code=204)
async def delete_segment(sid: str, user: dict = Depends(require_admin),
                          tenant: dict = Depends(get_current_tenant)):
    row = await db.marketing_audience_segments.find_one(
        {"id": sid, "tenant_id": tenant["id"]}, {"_id": 0},
    )
    if not row: raise HTTPException(404, "Segment not found")
    live_campaigns = await db.marketing_campaigns.count_documents({
        "tenant_id": tenant["id"], "segment_id": sid,
        "status": {"$in": ["scheduled", "running"]},
    })
    live_drips = await db.marketing_drips.count_documents({
        "tenant_id": tenant["id"], "segment_id": sid, "active": True,
    })
    if live_campaigns or live_drips:
        raise HTTPException(
            409,
            f"Segment referenced by {live_campaigns} live campaign(s) "
            f"and {live_drips} active drip(s) — pause them first.",
        )
    await db.marketing_audience_segments.update_one(
        {"id": sid}, {"$set": {"active": False, "updated_at": now_iso()}},
    )
    return Response(status_code=204)


@router.post("/marketing/audience-segments/{sid}/preview")
async def preview_segment(
    sid: str, refresh: bool = Query(False),
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    row = await db.marketing_audience_segments.find_one(
        {"id": sid, "tenant_id": tenant["id"]}, {"_id": 0},
    )
    if not row: raise HTTPException(404, "Segment not found")

    # Serve the cached count when we have one and the caller didn't ask
    # for a refresh — this makes the list page snappy without stale
    # zero-counts.
    if (not refresh and row.get("match_count_cached") is not None
            and row.get("match_count_cached_at")):
        return {
            "count": row["match_count_cached"],
            "sample": row.get("sample_cache") or [],
            "cached": True,
            "cached_at": row["match_count_cached_at"],
        }
    try:
        r = await evaluate_conditions(row.get("conditions") or [], tenant["id"])
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    await db.marketing_audience_segments.update_one(
        {"id": sid},
        {"$set": {"match_count_cached": r["count"],
                    "match_count_cached_at": now_iso(),
                    "sample_cache": r["sample"]}},
    )
    return {"count": r["count"], "sample": r["sample"], "cached": False}


# ── Seed ───────────────────────────────────────────────────────────────────
_SEED_SEGMENTS = [
    {"name": "VIP customers", "description": "Customers flagged as VIP.",
     "conditions": [{"field": "vip", "op": "eq", "value": True}]},
    {"name": "Past-due customers", "description": "Open invoices past their due date.",
     "conditions": [
         {"field": "has_past_due", "op": "eq", "value": True},
         {"field": "balance_due", "op": "gt", "value": 0},
     ]},
    {"name": "Inactive 90+ days", "description": "No completed service in the last 90 days.",
     "conditions": [{"field": "last_service_days_ago", "op": "gt", "value": 90}]},
    {"name": "New customers (last 30 days)", "description": "Customer created in the last 30 days.",
     "conditions": [{"field": "created_days_ago", "op": "lt", "value": 30}]},
]


async def seed_segments_for_tenant(tenant_id: str) -> int:
    count = await db.marketing_audience_segments.count_documents({"tenant_id": tenant_id})
    if count > 0: return 0
    now = now_iso()
    docs = [
        {"id": new_id(), "tenant_id": tenant_id,
         "name": s["name"], "description": s["description"],
         "conditions": s["conditions"],
         "match_count_cached": None, "match_count_cached_at": None,
         "active": True, "system": True,
         "created_at": now, "updated_at": now, "created_by": None}
        for s in _SEED_SEGMENTS
    ]
    await db.marketing_audience_segments.insert_many(docs)
    return len(docs)


async def seed_segments_all_tenants() -> Dict[str, int]:
    total = 0; tenants = 0
    async for t in db.tenants.find({}, {"_id": 0, "id": 1}):
        tenants += 1
        try: total += await seed_segments_for_tenant(t["id"])
        except Exception as exc:  # pragma: no cover
            logger.warning("m4 seed for tenant %s failed: %s", t.get("id"), exc)
    return {"tenants": tenants, "inserted": total}
