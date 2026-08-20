"""Phase 4 · Feb-2026 — Drag-drop / auto-insert an unscheduled job.

Endpoints (Admin / Super Admin / Manager / Dispatcher via
``require_gps_read`` wrap at include_router() time — Tech + Customer
→ 403):

  GET  /api/dispatch/route/unscheduled-jobs
       Return tenant jobs that have NO tech and NO scheduled_date.
       Used by the Dispatch Board's Unscheduled Jobs panel.

  POST /api/dispatch/route/insert
       Body: {tech_user_id, route_date, job_id}
       Auto-assigns the job to (tech, date) and slots it at the
       cheapest position in the existing route (min added Haversine
       leg distance). Shifts subsequent jobs' route_index by +1.
"""
from __future__ import annotations

import math
import re
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from config import db
from utils import get_current_user
from utils import not_deleted_filter as _nd

# Reuse Phase 3 helpers so the math stays identical.
from routers.dispatch_route_optimize import (  # noqa: F401
    _hav, _job_coords, _tech_origin,
)

router = APIRouter()


class InsertBody(BaseModel):
    tech_user_id: str = Field(..., min_length=1)
    route_date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    job_id: str = Field(..., min_length=1)


def _tenant_of(user: Dict[str, Any]) -> str:
    tid = user.get("tenant_id") or ""
    if not tid:
        raise HTTPException(400, detail="tenant scope required")
    return tid


def _is_unscheduled(j: Dict[str, Any]) -> bool:
    """A job is 'unscheduled' iff it has no tech AND no scheduled_date."""
    has_tech = bool(j.get("tech_user_id") or j.get("assigned_to")
                     or j.get("technician_id"))
    has_date = bool(j.get("scheduled_date"))
    return not has_tech and not has_date


def _cheapest_slot(origin: Tuple[float, float],
                    existing: List[Tuple[float, float]],
                    new_pt: Tuple[float, float]) -> Tuple[int, float]:
    """Return (best_index, added_km).

    For each candidate insertion position ``i`` in ``0..len(existing)``:
        - prev = origin if i == 0 else existing[i-1]
        - next_ = existing[i] if i < len(existing) else None (end-of-route)
        - added = d(prev,new) + d(new,next_) - d(prev,next_)
          For end-of-route insertion (no ``next_``): added = d(prev,new).
    Argmin on ``added``; ties broken by lowest ``i``.
    """
    n = len(existing)
    best_i = 0
    best_add = float("inf")
    for i in range(n + 1):
        prev = origin if i == 0 else existing[i - 1]
        d_pn = _hav(prev[0], prev[1], new_pt[0], new_pt[1])
        if i == n:
            added = d_pn
        else:
            nxt = existing[i]
            d_nn = _hav(new_pt[0], new_pt[1], nxt[0], nxt[1])
            d_pn_next = _hav(prev[0], prev[1], nxt[0], nxt[1])
            added = d_pn + d_nn - d_pn_next
        if added < best_add - 1e-9:
            best_add = added
            best_i = i
    return best_i, round(max(best_add, 0.0), 3)


def _route_total_km(origin: Tuple[float, float],
                     pts: List[Tuple[float, float]]) -> float:
    tot = 0.0
    cur = origin
    for p in pts:
        tot += _hav(cur[0], cur[1], p[0], p[1])
        cur = p
    return round(tot, 3)


@router.get("/dispatch/route/unscheduled-jobs",
             operation_id="dispatchRoute.listUnscheduledJobs",
             tags=["dispatch-route"])
async def list_unscheduled_jobs(
    caller: Dict[str, Any] = Depends(get_current_user),
    limit: int = 100,
):
    tenant_id = _tenant_of(caller)
    q = {"tenant_id": tenant_id,
         "$and": [
             {"$or": [{"scheduled_date": None},
                       {"scheduled_date": {"$exists": False}},
                       {"scheduled_date": ""}]},
             {"$nor": [
                 {"tech_user_id": {"$exists": True, "$nin": [None, ""]}},
                 {"assigned_to": {"$exists": True, "$nin": [None, ""]}},
                 {"technician_id": {"$exists": True, "$nin": [None, ""]}},
             ]},
         ]}
    items: List[Dict[str, Any]] = []
    q = {**q, **_nd()}
    cursor = db.jobs.find(q, {"_id": 0, "id": 1, "title": 1, "address": 1,
                                "customer_id": 1, "customer_name": 1,
                                "service_type": 1, "lat": 1, "lon": 1}).limit(limit)
    async for j in cursor:
        # Best-effort coord signal for the UI (server does the real check
        # again at insert time).
        has_coords = isinstance(j.get("lat"), (int, float)) and isinstance(j.get("lon"), (int, float))
        items.append({
            "id": j["id"],
            "title": j.get("title") or "(untitled)",
            "address": j.get("address") or "",
            "customer_id": j.get("customer_id"),
            "customer_name": j.get("customer_name") or "",
            "service_type": j.get("service_type") or "",
            "has_coords": has_coords,
        })
    return {"items": items, "count": len(items)}


@router.post("/dispatch/route/insert",
              operation_id="dispatchRoute.insert",
              tags=["dispatch-route"])
async def insert_route_job(body: InsertBody,
                            caller: Dict[str, Any] = Depends(get_current_user)):
    tenant_id = _tenant_of(caller)
    tech_id = body.tech_user_id
    date = body.route_date

    job = await db.jobs.find_one({"id": body.job_id, "tenant_id": tenant_id},
                                  {"_id": 0})
    if not job:
        raise HTTPException(404, detail="job_not_found")

    if not _is_unscheduled(job):
        raise HTTPException(409, detail="job_already_scheduled")

    new_coords = await _job_coords(job)
    if not new_coords:
        raise HTTPException(422, detail="job_missing_coords")

    # Load existing route for that (tech, date) in current order.
    date_prefix = re.escape(date)
    q = {"tenant_id": tenant_id,
         "scheduled_date": {"$regex": f"^{date_prefix}"},
         "$or": [{"tech_user_id": tech_id},
                  {"assigned_to": tech_id},
                  {"technician_id": tech_id}]}
    existing: List[Dict[str, Any]] = []
    q = {**q, **_nd()}
    async for j in db.jobs.find(q, {"_id": 0}).sort("route_index", 1):
        existing.append(j)

    # Resolve each existing job's coords; drop any that can't geocode
    # (they stay in the DB unchanged but are ignored for insertion math).
    existing_pts: List[Tuple[float, float]] = []
    existing_ids: List[str] = []
    existing_addrs: List[str] = []
    for j in existing:
        c = await _job_coords(j)
        if c:
            existing_pts.append(c)
            existing_ids.append(j["id"])
            existing_addrs.append(j.get("address") or "")

    origin, _origin_source = await _tech_origin(tenant_id, tech_id, date)
    if origin is None:
        origin = existing_pts[0] if existing_pts else new_coords

    best_i, added_km = _cheapest_slot(origin, existing_pts, new_coords)

    # Persist: assign the dropped job, then shift subsequent route_index.
    # Use bulk update. Compound index gets created lazily by Phase 3 apply
    # but we don't rely on it — plain filter works.
    #
    # 1) Shift existing[best_i:] up by +1.
    for idx in range(len(existing) - 1, -1, -1):
        cur = existing[idx]
        cur_ri = cur.get("route_index")
        if cur_ri is None:
            # If any existing job has no route_index, treat it as its ordinal
            # so we still preserve relative order after the shift.
            cur_ri = idx
        if idx >= best_i:
            await db.jobs.update_one(
                {"id": cur["id"], "tenant_id": tenant_id},
                {"$set": {"route_index": cur_ri + 1}},
            )
    # 2) Write the dropped job (tech + date + route_index = best_i).
    set_payload = {"tech_user_id": tech_id,
                   "technician_id": tech_id,
                   "scheduled_date": date,
                   "route_index": best_i}
    await db.jobs.update_one({"id": body.job_id, "tenant_id": tenant_id},
                              {"$set": set_payload})

    # Build response payload — reload the final ordered list.
    final: List[Dict[str, Any]] = []
    q = {**q, **_nd()}
    async for j in db.jobs.find(q, {"_id": 0}).sort("route_index", 1):
        c = await _job_coords(j)
        final.append({"job_id": j["id"], "address": j.get("address") or "",
                       "lat": c[0] if c else None,
                       "lon": c[1] if c else None,
                       "sequence": len(final)})
    # Fill leg distances.
    prev = origin
    for row in final:
        if row["lat"] is None:
            row["leg_distance_km"] = None
            continue
        row["leg_distance_km"] = round(
            _hav(prev[0], prev[1], row["lat"], row["lon"]), 3)
        prev = (row["lat"], row["lon"])

    total_pts = [(r["lat"], r["lon"]) for r in final if r["lat"] is not None]
    new_total = _route_total_km(origin, total_pts)

    # Phase 10 · sub-item F — event log for KPI aggregation.
    try:
        from services.route_events import log_event
        await log_event(tenant_id=tenant_id, kind="insert",
                          tech_user_id=tech_id, route_date=date,
                          savings_km=0.0,
                          added_distance_km=added_km,
                          stop_count=len(final),
                          executed_by=(caller.get("id") or caller.get("email") or ""))
    except Exception:
        pass

    return {
        "ok": True,
        "inserted_at": best_i,
        "total_stops": len(final),
        "added_distance_km": added_km,
        "new_total_distance_km": new_total,
        "ordered_jobs": final,
    }




# ─── Phase 10 · sub-item E — Batch preview-insert ─────────────────
class PreviewBatchBody(BaseModel):
    tech_user_id: str = Field(..., min_length=1)
    route_date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    job_ids: List[str] = Field(..., max_length=50)


@router.post("/dispatch/route/preview-insert-batch",
              operation_id="dispatchRoute.previewInsertBatch",
              tags=["dispatch-route"])
async def preview_insert_batch(body: PreviewBatchBody,
                                  caller: Dict[str, Any] = Depends(get_current_user)):
    """Compute cheapest-slot `added_distance_km` for each candidate job
    WITHOUT modifying anything. Reuses `_cheapest_slot()` exactly so the
    numbers match what a real drop would produce."""
    tenant_id = _tenant_of(caller)
    if not body.job_ids:
        return {"previews": []}

    # Load the currently-assigned route.
    date_prefix = re.escape(body.route_date)
    q = {"tenant_id": tenant_id,
          "scheduled_date": {"$regex": f"^{date_prefix}"},
          "$or": [{"tech_user_id": body.tech_user_id},
                    {"assigned_to": body.tech_user_id},
                    {"technician_id": body.tech_user_id}]}
    existing_pts: List[Tuple[float, float]] = []
    q = {**q, **_nd()}
    async for j in db.jobs.find(q, {"_id": 0}).sort("route_index", 1):
        c = await _job_coords(j)
        if c:
            existing_pts.append(c)
    origin, _src = await _tech_origin(tenant_id, body.tech_user_id,
                                          body.route_date)

    previews: List[Dict[str, Any]] = []
    for jid in body.job_ids[:50]:
        j = await db.jobs.find_one({"id": jid, "tenant_id": tenant_id},
                                      {"_id": 0})
        if not j:
            previews.append({"job_id": jid, "added_distance_km": None,
                              "best_position": None,
                              "currently_missing_coords": True})
            continue
        c = await _job_coords(j)
        if not c:
            previews.append({"job_id": jid, "added_distance_km": None,
                              "best_position": None,
                              "currently_missing_coords": True})
            continue
        # If tech has no route and no origin → use the candidate as its own
        # origin, which yields 0 km — a truthful "first-stop" preview.
        eff_origin = origin or (existing_pts[0] if existing_pts else c)
        best_i, added_km = _cheapest_slot(eff_origin, existing_pts, c)
        previews.append({"job_id": jid,
                          "added_distance_km": added_km,
                          "best_position": best_i,
                          "currently_missing_coords": False})
    return {"previews": previews}
