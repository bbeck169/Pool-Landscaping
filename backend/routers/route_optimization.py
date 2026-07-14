"""Phase 20A.1 · Route optimization for a tech's daily job list.

Nearest-neighbor Haversine ordering, cached per-day per-user, ready to be
upgraded to Google Directions/Distance-Matrix later without changing the
public contract. Emits a `route_optimized` WS event so the schedule UI can
reorder cards without a manual reload.
"""
import hashlib
from datetime import datetime, timezone
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from config import db, logger
from utils import now_iso, new_id, get_current_user
from routers.tenants import get_current_tenant

# Reuse the existing Haversine + settings helpers.
from routers.workforce import _haversine_m, _settings  # type: ignore

router = APIRouter()


class OptimizeIn(BaseModel):
    date: Optional[str] = None      # YYYY-MM-DD (defaults today)
    start_lat: Optional[float] = None
    start_lng: Optional[float] = None


def _waypoints_hash(job_ids: List[str], start_lat, start_lng) -> str:
    payload = "|".join(sorted(job_ids)) + f"|{start_lat}|{start_lng}"
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def _estimate_duration_s(distance_m: float) -> int:
    """~35 km/h neighborhood-average driving. Good enough for card badges."""
    if distance_m <= 0:
        return 0
    return int(distance_m / (35 * 1000 / 3600))


@router.post("/schedule/optimize-route")
async def optimize_route(
    body: OptimizeIn = OptimizeIn(),
    user_id: Optional[str] = Query(None),
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    """Optimize the driving order for a tech's today (or `date`) job list."""
    if user.get("role") == "customer":
        raise HTTPException(403, "Not allowed")
    # Only admins can override which user to optimize for.
    target_uid = user["id"]
    if user_id and user.get("role") in ("admin", "super_admin"):
        target_uid = user_id
    elif user_id and user_id != user["id"]:
        raise HTTPException(403, "Cannot optimize another user's route")

    # Hard cross-tenant guard: if the caller is planning for someone else,
    # that user must exist and belong to the caller's current tenant.
    if target_uid != user["id"]:
        other = await db.users.find_one({"id": target_uid},
                                        {"_id": 0, "id": 1, "tenant_id": 1})
        if not other:
            raise HTTPException(404, "user_id not found")
        if other.get("tenant_id") != tenant["id"]:
            raise HTTPException(403, "user_id not in current tenant")

    date_str = body.date or datetime.now(timezone.utc).date().isoformat()
    day_start = f"{date_str}T00:00:00+00:00"
    day_end   = f"{date_str}T23:59:59+00:00"

    # Load the target user's assigned jobs for the day.
    target_user = await db.users.find_one({"id": target_uid, "tenant_id": tenant["id"]},
                                          {"_id": 0})
    tech_id = (target_user or {}).get("technician_id") or target_uid
    query = {
        "tenant_id": tenant["id"],
        "$or": [
            {"technician_id": target_uid},
            {"technician_id": tech_id},
            {"assigned_technician_id": target_uid},
        ],
        "status": {"$nin": ["completed", "cancelled"]},
        "scheduled_start": {"$gte": day_start, "$lte": day_end},
    }
    jobs = await db.jobs.find(query, {"_id": 0}).to_list(100)
    jobs_with_geo = [
        j for j in jobs
        if (j.get("site_lat") is not None or j.get("lat") is not None)
        and (j.get("site_lng") is not None or j.get("lng") is not None)
    ]
    if len(jobs_with_geo) < 2:
        return {
            "ordered_job_ids": [j["id"] for j in jobs_with_geo],
            "total_distance_m": 0, "total_duration_s": 0,
            "legs": [], "cached": False, "algorithm": "trivial",
        }

    job_ids = [j["id"] for j in jobs_with_geo]
    whash = _waypoints_hash(job_ids, body.start_lat, body.start_lng)
    cached = await db.route_optimizations.find_one(
        {"tenant_id": tenant["id"], "user_id": target_uid,
         "date": date_str, "waypoints_hash": whash},
        {"_id": 0},
    )
    if cached:
        cached["cached"] = True
        return cached

    # Nearest-neighbor from the start (or first job).
    start = (body.start_lat, body.start_lng) if body.start_lat and body.start_lng else None
    remaining = list(jobs_with_geo)
    ordered: list = []
    legs: list = []
    total_m = 0.0
    prev_lat, prev_lng = start if start else (None, None)
    while remaining:
        if prev_lat is None:
            nxt = remaining[0]
        else:
            nxt = min(remaining, key=lambda j: _haversine_m(
                prev_lat, prev_lng,
                j.get("site_lat") or j.get("lat"),
                j.get("site_lng") or j.get("lng"),
            ))
            d = _haversine_m(
                prev_lat, prev_lng,
                nxt.get("site_lat") or nxt.get("lat"),
                nxt.get("site_lng") or nxt.get("lng"),
            )
            legs.append({
                "from_job_id": ordered[-1]["id"] if ordered else None,
                "to_job_id": nxt["id"],
                "distance_m": round(d, 1),
                "duration_s": _estimate_duration_s(d),
                "polyline": None,
            })
            total_m += d
        ordered.append(nxt)
        prev_lat = nxt.get("site_lat") or nxt.get("lat")
        prev_lng = nxt.get("site_lng") or nxt.get("lng")
        remaining.remove(nxt)

    out = {
        "ordered_job_ids": [j["id"] for j in ordered],
        "total_distance_m": round(total_m, 1),
        "total_duration_s": _estimate_duration_s(total_m),
        "legs": legs,
        "cached": False,
        "algorithm": "nearest_neighbor",
        "date": date_str,
        "waypoints_hash": whash,
        "tenant_id": tenant["id"],
        "user_id": target_uid,
        "computed_at": now_iso(),
    }
    await db.route_optimizations.insert_one(dict(out))
    # WS notify — best-effort.
    try:
        from routers.realtime import bus
        await bus.broadcast(target_uid, {
            "type": "route_optimized",
            "payload": {"ordered_job_ids": out["ordered_job_ids"],
                        "total_distance_m": out["total_distance_m"]},
        })
    except Exception as e:
        logger.warning(f"WS notify (route_optimized) failed: {e}")
    return out
