"""Phase 3 · Feb-2026 — Nearest-neighbor route optimizer for Dispatch.

Endpoints (Admin / Super Admin / Manager / Dispatcher — enforced via
``require_gps_read`` wrap at include_router() time):
    POST /api/dispatch/route/optimize   (DRY-RUN preview)
    POST /api/dispatch/route/apply      (persists route_index 0..N-1)

Algorithm: strict nearest-neighbor from a tech origin. Origin selection
order:
    1) user.home_base_lat/home_base_lon
    2) earliest gps_pings row on the route date
    3) first job's coords (tour has n-1 legs)
    4) origin_source = "none" — endpoint returns 422 to avoid silently
       picking an arbitrary tour.

Distance: Haversine great-circle (same helper style as gps_route).
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from config import db
from utils import get_current_user, require_gps_read  # noqa: F401

router = APIRouter()

_EARTH_KM = 6371.0088


def _hav(a_lat: float, a_lon: float, b_lat: float, b_lon: float) -> float:
    """Great-circle distance in km."""
    la1, la2 = math.radians(a_lat), math.radians(b_lat)
    dla, dlo = math.radians(b_lat - a_lat), math.radians(b_lon - a_lon)
    h = math.sin(dla / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin(dlo / 2) ** 2
    return 2 * _EARTH_KM * math.asin(math.sqrt(h))


async def _job_coords(job: Dict[str, Any]) -> Optional[Tuple[float, float]]:
    """Attempt to resolve (lat, lon) for a job.

    Order: direct lat/lon on job → customer's lat/lon → None. Mapbox
    reverse-geocode is skipped here because the reverse geocoder in
    this codebase resolves *coordinates → address*, not address →
    coords (forward geocoding). If the codebase gains a forward
    geocoder later, add it as the last fallback.
    """
    for lat_k, lon_k in [("lat", "lon"), ("latitude", "longitude"),
                          ("center_lat", "center_lon")]:
        lat, lon = job.get(lat_k), job.get(lon_k)
        if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
            return float(lat), float(lon)
    cid = job.get("customer_id")
    if cid:
        c = await db.customers.find_one(
            {"id": cid}, {"_id": 0, "lat": 1, "lon": 1,
                           "latitude": 1, "longitude": 1,
                           "service_lat": 1, "service_lon": 1})
        if c:
            for a, b in [("lat", "lon"), ("latitude", "longitude"),
                          ("service_lat", "service_lon")]:
                if isinstance(c.get(a), (int, float)) and isinstance(c.get(b), (int, float)):
                    return float(c[a]), float(c[b])
    return None


async def _tech_origin(tenant_id: str, tech_user_id: str, date: str) -> Tuple[Optional[Tuple[float, float]], str]:
    """Return ((lat,lon), source) or (None, 'none')."""
    u = await db.users.find_one(
        {"id": tech_user_id, "tenant_id": tenant_id},
        {"_id": 0, "home_base_lat": 1, "home_base_lon": 1})
    if u and isinstance(u.get("home_base_lat"), (int, float)) and isinstance(u.get("home_base_lon"), (int, float)):
        return (float(u["home_base_lat"]), float(u["home_base_lon"])), "home_base"

    day_start = f"{date}T00:00:00+00:00"
    day_end = f"{date}T23:59:59+00:00"
    ping = await db.gps_pings.find_one(
        {"tenant_id": tenant_id, "user_id": tech_user_id,
          "captured_at": {"$gte": day_start, "$lte": day_end}},
        {"_id": 0, "lat": 1, "lon": 1},
        sort=[("captured_at", 1)],
    )
    if ping and isinstance(ping.get("lat"), (int, float)):
        return (float(ping["lat"]), float(ping["lon"])), "first_ping"

    return None, "none"


def _nearest_neighbor(origin: Tuple[float, float],
                       points: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Reorder ``points`` (each has 'lat','lon') by nearest-neighbor from
    origin. Returns a NEW list with 'sequence', 'leg_distance_km',
    'cumulative_distance_km' filled in."""
    remaining = list(points)
    tour: List[Dict[str, Any]] = []
    cur = origin
    cum = 0.0
    while remaining:
        idx = min(range(len(remaining)),
                    key=lambda i: _hav(cur[0], cur[1],
                                        remaining[i]["lat"], remaining[i]["lon"]))
        nxt = remaining.pop(idx)
        leg = _hav(cur[0], cur[1], nxt["lat"], nxt["lon"])
        cum += leg
        tour.append({**nxt,
                      "sequence": len(tour),
                      "leg_distance_km": round(leg, 3),
                      "cumulative_distance_km": round(cum, 3)})
        cur = (nxt["lat"], nxt["lon"])
    return tour


def _hand_ordered_distance(origin: Tuple[float, float],
                             jobs_in_order: List[Dict[str, Any]]) -> float:
    tot = 0.0
    cur = origin
    for j in jobs_in_order:
        tot += _hav(cur[0], cur[1], j["lat"], j["lon"])
        cur = (j["lat"], j["lon"])
    return round(tot, 3)


class OptimizeBody(BaseModel):
    tech_user_id: str = Field(..., min_length=1)
    route_date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")


class ApplyBody(BaseModel):
    tech_user_id: str = Field(..., min_length=1)
    route_date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    ordered_job_ids: List[str]


def _tenant_of(user: Dict[str, Any]) -> str:
    tid = user.get("tenant_id") or ""
    if not tid:
        raise HTTPException(400, detail="tenant scope required")
    return tid


@router.post("/dispatch/route/optimize",
              operation_id="dispatchRoute.optimize",
              tags=["dispatch-route"])
async def optimize_route(body: OptimizeBody,
                          caller: Dict[str, Any] = Depends(get_current_user)):
    tenant_id = _tenant_of(caller)
    tech_id = body.tech_user_id
    date = body.route_date

    # Pull the tech's jobs for that date. Support `tech_user_id`,
    # `assigned_to`, and `technician_id` — seed & production data
    # historically use `technician_id`; newer flows write `tech_user_id`.
    # `scheduled_date` may be stored as either "YYYY-MM-DD" or a full
    # ISO datetime "YYYY-MM-DDTHH:MM:SS+00:00"; match both via regex.
    import re as _re
    date_prefix = _re.escape(date)
    q = {"tenant_id": tenant_id,
         "scheduled_date": {"$regex": f"^{date_prefix}"},
         "$or": [{"tech_user_id": tech_id},
                  {"assigned_to": tech_id},
                  {"technician_id": tech_id}]}
    jobs: List[Dict[str, Any]] = []
    async for j in db.jobs.find(q, {"_id": 0}).sort("route_index", 1):
        jobs.append(j)
    if not jobs:
        raise HTTPException(404, detail="no_jobs_for_tech_on_date")

    origin, origin_source = await _tech_origin(tenant_id, tech_id, date)
    ordered: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    for j in jobs:
        coords = await _job_coords(j)
        if not coords:
            skipped.append({"job_id": j["id"], "reason": "no_coords"})
            continue
        ordered.append({"job_id": j["id"], "lat": coords[0], "lon": coords[1],
                         "address": j.get("address") or ""})

    if not ordered:
        raise HTTPException(422, detail="no_geocodable_jobs")

    # Fallback #3 — first job's coords as origin.
    if origin is None:
        origin = (ordered[0]["lat"], ordered[0]["lon"])
        origin_source = "first_job"

    if origin is None:
        raise HTTPException(422, detail="no_origin_available")

    # Hand-ordered baseline = jobs in the order they came back from
    # find(sort route_index) → i.e. the current manual sequence.
    hand_dist = _hand_ordered_distance(origin, ordered)
    tour = _nearest_neighbor(origin, ordered)
    total = round(sum(p["leg_distance_km"] for p in tour), 3)
    savings = round(hand_dist - total, 3)

    return {
        "tech_user_id": tech_id,
        "route_date": date,
        "origin": {"lat": origin[0], "lon": origin[1], "source": origin_source},
        "ordered_jobs": tour,
        "skipped": skipped,
        "total_distance_km": total,
        "hand_ordered_distance_km": hand_dist,
        "savings_km": savings,
    }


@router.post("/dispatch/route/apply",
              operation_id="dispatchRoute.apply",
              tags=["dispatch-route"])
async def apply_route(body: ApplyBody,
                       caller: Dict[str, Any] = Depends(get_current_user)):
    tenant_id = _tenant_of(caller)
    updated = 0
    # Ensure the compound index exists (idempotent).
    await db.jobs.create_index([("tenant_id", 1), ("tech_user_id", 1),
                                  ("scheduled_date", 1), ("route_index", 1)])
    for i, jid in enumerate(body.ordered_job_ids):
        import re as _re
        date_prefix = _re.escape(body.route_date)
        r = await db.jobs.update_one(
            {"id": jid, "tenant_id": tenant_id,
              "scheduled_date": {"$regex": f"^{date_prefix}"},
              "$or": [{"tech_user_id": body.tech_user_id},
                       {"assigned_to": body.tech_user_id},
                       {"technician_id": body.tech_user_id}]},
            {"$set": {"route_index": i}},
        )
        if r.matched_count:
            updated += 1
    return {"ok": True, "updated": updated,
            "tech_user_id": body.tech_user_id,
            "route_date": body.route_date}
