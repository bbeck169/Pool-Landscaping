"""Phase G5a · Feb-2026 — Geofences CRUD + crossing events."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from config import db, logger
from services.geofence_engine import compute_bbox, point_in_fence
from utils import get_current_user, new_id, now_iso

router = APIRouter()
_MOD_ROLES = {"admin", "super_admin", "manager"}
_MAX_FENCES_PER_TENANT = 500


def _require_mod(u): 
    if (u or {}).get("role") not in _MOD_ROLES:
        raise HTTPException(403, {"error": "forbidden"})


def _tid(u):
    t = (u or {}).get("tenant_id") or ""
    if not t: raise HTTPException(400, {"error":"missing_tenant"})
    return t


class Pt(BaseModel):
    lat: float; lon: float


class FenceIn(BaseModel):
    name: str = Field(..., min_length=1)
    kind: str = "custom"
    shape: str
    center_lat: Optional[float] = None
    center_lon: Optional[float] = None
    radius_m: Optional[int] = Field(None, ge=5, le=100_000)
    points: Optional[List[Pt]] = None
    linked_customer_id: Optional[str] = None
    linked_job_id: Optional[str] = None
    alert_on_enter: bool = True
    alert_on_exit: bool = False
    active: bool = True
    tags: List[str] = Field(default_factory=list)


class FencePatch(BaseModel):
    name: Optional[str] = None
    kind: Optional[str] = None
    shape: Optional[str] = None
    center_lat: Optional[float] = None
    center_lon: Optional[float] = None
    radius_m: Optional[int] = None
    points: Optional[List[Pt]] = None
    linked_customer_id: Optional[str] = None
    linked_job_id: Optional[str] = None
    alert_on_enter: Optional[bool] = None
    alert_on_exit: Optional[bool] = None
    active: Optional[bool] = None
    tags: Optional[List[str]] = None


def _mk_doc(caller: Dict[str, Any], tenant_id: str,
                body: FenceIn) -> Dict[str, Any]:
    if body.shape == "circle":
        if body.center_lat is None or body.center_lon is None or not body.radius_m:
            raise HTTPException(422, {"error":"missing_circle_fields"})
    elif body.shape == "polygon":
        pts = body.points or []
        if len(pts) < 3 or len(pts) > 500:
            raise HTTPException(422, {"error":"polygon_needs_3_to_500_points"})
    else:
        raise HTTPException(422, {"error":"invalid_shape"})
    d = body.model_dump()
    d["points"] = [p.model_dump() if hasattr(p,"model_dump") else p
                    for p in (d.get("points") or [])]
    d["id"] = new_id()
    d["tenant_id"] = tenant_id
    d["created_by_user_id"] = caller["id"]
    d["created_at"] = now_iso()
    d["updated_at"] = now_iso()
    d["bbox"] = compute_bbox(d)
    return d


@router.post("/geofences", operation_id="geofences.create")
async def create_fence(body: FenceIn,
                          caller: Dict[str,Any] = Depends(get_current_user)):
    _require_mod(caller); t = _tid(caller)
    doc = _mk_doc(caller, t, body)
    await db.geofences.insert_one({**doc})
    doc.pop("_id", None); return doc


@router.get("/geofences", operation_id="geofences.list")
async def list_fences(kind: Optional[str] = None,
                          active: Optional[bool] = None,
                          linked_customer_id: Optional[str] = None,
                          linked_job_id: Optional[str] = None,
                          caller: Dict[str,Any] = Depends(get_current_user)):
    _require_mod(caller); t = _tid(caller)
    q: Dict[str,Any] = {"tenant_id": t}
    if kind: q["kind"] = kind
    if active is not None: q["active"] = active
    if linked_customer_id: q["linked_customer_id"] = linked_customer_id
    if linked_job_id: q["linked_job_id"] = linked_job_id
    items: List[Dict[str,Any]] = []
    async for r in db.geofences.find(q, {"_id":0}).sort("created_at", -1):
        items.append(r)
    return {"items": items, "total": len(items)}


@router.get("/geofences/{fid}", operation_id="geofences.get")
async def get_fence(fid: str,
                       caller: Dict[str,Any] = Depends(get_current_user)):
    _require_mod(caller); t = _tid(caller)
    row = await db.geofences.find_one({"id": fid, "tenant_id": t}, {"_id":0})
    if not row: raise HTTPException(404, {"error":"not_found"})
    events: List[Dict[str,Any]] = []
    async for e in db.geofence_events.find(
            {"tenant_id": t, "geofence_id": fid}, {"_id":0}
            ).sort("detected_at", -1).limit(20):
        events.append(e)
    row["recent_events"] = events
    return row


@router.patch("/geofences/{fid}", operation_id="geofences.patch")
async def patch_fence(fid: str, body: FencePatch,
                        caller: Dict[str,Any] = Depends(get_current_user)):
    _require_mod(caller); t = _tid(caller)
    row = await db.geofences.find_one({"id": fid, "tenant_id": t}, {"_id":0})
    if not row: raise HTTPException(404, {"error":"not_found"})
    upd = {k:v for k,v in body.model_dump(exclude_none=True).items()}
    if "points" in upd:
        upd["points"] = [p if isinstance(p, dict) else p.model_dump()
                          for p in upd["points"]]
    if any(k in upd for k in ("shape","center_lat","center_lon","radius_m","points")):
        merged = {**row, **upd}
        upd["bbox"] = compute_bbox(merged)
    upd["updated_at"] = now_iso()
    await db.geofences.update_one({"id": fid, "tenant_id": t}, {"$set": upd})
    fresh = await db.geofences.find_one({"id": fid, "tenant_id": t}, {"_id":0})
    return fresh


@router.delete("/geofences/{fid}", operation_id="geofences.delete")
async def delete_fence(fid: str,
                          caller: Dict[str,Any] = Depends(get_current_user)):
    _require_mod(caller); t = _tid(caller)
    r = await db.geofences.update_one(
        {"id": fid, "tenant_id": t},
        {"$set": {"active": False, "updated_at": now_iso()}})
    if r.matched_count == 0:
        raise HTTPException(404, {"error":"not_found"})
    return {"archived": True, "id": fid}


@router.post("/geofences/{fid}/test-point",
              operation_id="geofences.testPoint")
async def test_point(fid: str, body: Pt,
                        caller: Dict[str,Any] = Depends(get_current_user)):
    _require_mod(caller); t = _tid(caller)
    row = await db.geofences.find_one({"id": fid, "tenant_id": t}, {"_id":0})
    if not row: raise HTTPException(404, {"error":"not_found"})
    inside = point_in_fence(body.lat, body.lon, row)
    out: Dict[str,Any] = {"inside": inside}
    if row.get("shape") == "circle":
        from services.geofence_engine import haversine_m
        out["distance_m"] = round(haversine_m(
            body.lat, body.lon,
            float(row["center_lat"]), float(row["center_lon"])), 2)
    return out


@router.get("/geofence-events", operation_id="geofences.events")
async def list_events(user_id: Optional[str] = None,
                          geofence_id: Optional[str] = None,
                          crossing: Optional[str] = None,
                          acknowledged: Optional[bool] = None,
                          from_: Optional[str] = Query(None, alias="from"),
                          to: Optional[str] = None,
                          limit: int = Query(200, ge=1, le=1000),
                          caller: Dict[str,Any] = Depends(get_current_user)):
    _require_mod(caller); t = _tid(caller)
    q: Dict[str,Any] = {"tenant_id": t}
    if user_id: q["user_id"] = user_id
    if geofence_id: q["geofence_id"] = geofence_id
    if crossing: q["crossing"] = crossing
    if acknowledged is not None: q["acknowledged"] = acknowledged
    if from_ or to:
        rr: Dict[str,Any] = {}
        if from_: rr["$gte"] = from_.replace("Z","+00:00")
        if to:    rr["$lte"] = to.replace("Z","+00:00")
        q["detected_at"] = rr
    items: List[Dict[str,Any]] = []
    async for e in db.geofence_events.find(q, {"_id":0}
                ).sort("detected_at", -1).limit(limit):
        items.append(e)
    return {"items": items, "total": len(items)}


@router.post("/geofence-events/{eid}/acknowledge",
              operation_id="geofences.acknowledgeEvent")
async def ack_event(eid: str,
                       caller: Dict[str,Any] = Depends(get_current_user)):
    _require_mod(caller); t = _tid(caller)
    r = await db.geofence_events.update_one(
        {"id": eid, "tenant_id": t},
        {"$set": {"acknowledged": True,
                    "acknowledged_by_user_id": caller["id"],
                    "acknowledged_at": now_iso()}})
    if r.matched_count == 0:
        raise HTTPException(404, {"error":"not_found"})
    return {"ok": True, "id": eid}


# ═══════════════════════ Ingest hook helper ════════════════════════

async def evaluate_ping_against_fences(*,
    tenant_id: str, user_id: str, user_name: str,
    lat: float, lon: float, captured_at: str,
    ping_id: Optional[str] = None,
) -> int:
    """Evaluate a single ping against ALL active fences for the tenant
    and emit crossing events. Returns count of new crossings inserted.
    Cap: 500 active fences per tenant per evaluation."""
    fences: List[Dict[str,Any]] = []
    async for f in db.geofences.find(
            {"tenant_id": tenant_id, "active": True}, {"_id":0}
            ).limit(_MAX_FENCES_PER_TENANT + 1):
        fences.append(f)
    if len(fences) > _MAX_FENCES_PER_TENANT:
        logger.warning("[geofences] tenant=%s active fences > cap=%s "
                        "— extra fences skipped",
                        tenant_id, _MAX_FENCES_PER_TENANT)
        fences = fences[:_MAX_FENCES_PER_TENANT]

    new_events = 0
    for f in fences:
        try:
            inside_now = point_in_fence(lat, lon, f)
        except Exception:                                                # noqa: BLE001
            continue
        state = await db.geofence_state.find_one(
            {"tenant_id": tenant_id, "user_id": user_id,
              "geofence_id": f["id"]}, {"_id":0, "inside":1})
        was_inside = bool(state and state.get("inside"))
        if inside_now == was_inside:
            # Still just refresh last_evaluated_at.
            await db.geofence_state.update_one(
                {"tenant_id": tenant_id, "user_id": user_id,
                  "geofence_id": f["id"]},
                {"$set": {"tenant_id": tenant_id, "user_id": user_id,
                            "geofence_id": f["id"],
                            "inside": inside_now,
                            "last_evaluated_at": now_iso()}},
                upsert=True)
            continue
        # Edge — emit event.
        crossing = "enter" if (inside_now and not was_inside) else "exit"
        should_emit = ((crossing == "enter" and f.get("alert_on_enter"))
                        or (crossing == "exit" and f.get("alert_on_exit")))
        # Flip state regardless — even suppressed events still change state.
        await db.geofence_state.update_one(
            {"tenant_id": tenant_id, "user_id": user_id,
              "geofence_id": f["id"]},
            {"$set": {"tenant_id": tenant_id, "user_id": user_id,
                        "geofence_id": f["id"],
                        "inside": inside_now,
                        "last_evaluated_at": now_iso()}},
            upsert=True)
        if not should_emit:
            continue
        await db.geofence_events.insert_one({
            "id": new_id(),
            "tenant_id": tenant_id,
            "geofence_id": f["id"],
            "geofence_name": f.get("name"),
            "user_id": user_id, "user_name": user_name,
            "crossing": crossing,
            "captured_at": captured_at,
            "detected_at": now_iso(),
            "lat": lat, "lon": lon,
            "ping_id": ping_id,
            "acknowledged": False,
        })
        new_events += 1
    return new_events
