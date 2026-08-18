"""Phase 20A.1 · Route optimization for a tech's daily job list.

Nearest-neighbor Haversine ordering, cached per-day per-user, ready to be
upgraded to Google Directions/Distance-Matrix later without changing the
public contract. Emits a `route_optimized` WS event so the schedule UI can
reorder cards without a manual reload.

Feb-2026 · Slice 4 (MP1.6) — stops with ``property_id`` set now route on
the property's coords + address instead of the customer default. See
``services.stop_geo.resolve_stop_geo``.
"""
import hashlib
from datetime import datetime, timezone
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from config import db, logger
from utils import now_iso, new_id, get_current_user
from routers.tenants import get_current_tenant
from services.stop_geo import resolve_stop_geo

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
    # Feb-2026 · Slice 4 (MP1.6) — resolve every stop through the
    # shared stop-geo resolver so a job with ``property_id`` set uses
    # the property's coords (lazy-geocoding the property once when
    # its geocode cache is cold). The resolved coords land back on
    # the working job dict as ``site_lat/site_lng`` so the existing
    # nearest-neighbour loop below (which reads those keys) is
    # unchanged. Also cache ``address_source`` so the WS payload can
    # surface it for the UI.
    for j in jobs:
        geo = await resolve_stop_geo(j, tenant["id"], geocode_if_missing=True)
        if geo.get("lat") is not None and geo.get("lng") is not None:
            j["site_lat"] = geo["lat"]
            j["site_lng"] = geo["lng"]
        j["address_source"] = geo.get("address_source", "customer")
        if geo.get("address"):
            j["stop_address"] = geo["address"]
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


# ═══════════════════════════════════════════════════════════════════════
# Feb-2026 · Slice 4 (MP1.6) — Route stops read endpoint
# ═══════════════════════════════════════════════════════════════════════
@router.get("/routes/{tech_id}/stops")
async def get_route_stops(
    tech_id: str,
    date: Optional[str] = Query(None),
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    """List a tech's route stops for a date, resolved property-first.

    Each stop's ``address`` + ``lat`` + ``lng`` come from the
    property doc when ``property_id`` is set (falling back to the
    customer-scoped coords otherwise). ``address_source`` is
    ``"property"`` or ``"customer"`` for debuggability.

    Admin can query any tech in the tenant; a tech can only query
    themselves; customers are 403'd (unchanged with the optimizer).
    """
    if user.get("role") == "customer":
        raise HTTPException(403, "Not allowed")
    if user.get("role") not in ("admin", "super_admin"):
        # A technician can only fetch their own route stops. Both the
        # ``id`` (user row) and ``technician_id`` (technicians table)
        # forms are accepted so older seeds still resolve.
        if tech_id not in (user.get("id"), user.get("technician_id")):
            raise HTTPException(403, "Cannot read another user's route")

    date_str = date or datetime.now(timezone.utc).date().isoformat()
    day_start = f"{date_str}T00:00:00+00:00"
    day_end = f"{date_str}T23:59:59+00:00"

    # Load the tech row so we can match either user_id or technician_id
    # on the jobs collection (mirrors ``optimize_route``).
    # Feb-2026 · Routes enrichment — also read ``name`` and
    # ``display_color_hex`` in the same round-trip so the UI can show
    # the tech's name + color chip without an N+1 fetch.
    tech_user = await db.users.find_one(
        {"id": tech_id, "tenant_id": tenant["id"]},
        {"_id": 0, "id": 1, "technician_id": 1,
         "name": 1, "display_color_hex": 1},
    ) or {}
    tid = tech_user.get("technician_id") or tech_id

    q = {
        "tenant_id": tenant["id"],
        "$or": [
            {"technician_id": tech_id},
            {"technician_id": tid},
            {"assigned_technician_id": tech_id},
        ],
        "status": {"$nin": ["completed", "cancelled"]},
        "scheduled_start": {"$gte": day_start, "$lte": day_end},
    }
    jobs = await db.jobs.find(q, {"_id": 0}).sort(
        [("route_order", 1), ("scheduled_start", 1)]
    ).to_list(200)

    stops: List[dict] = []
    for j in jobs:
        geo = await resolve_stop_geo(j, tenant["id"], geocode_if_missing=False)
        # Feb-2026 · Routes enrichment · deleted-customer fallback.
        # ``customer_name`` on the job is denormalised at create-time;
        # if the customer row was later deleted (or the job was
        # imported without a name), fall back to the resolved address
        # so the UI never renders a blank primary line.
        display_name = (
            (j.get("customer_name") or "").strip()
            or (geo.get("address") or "").strip()
            or (j.get("title") or "").strip()
            or "(unknown customer)"
        )
        stops.append({
            "job_id": j.get("id"),
            "title": j.get("title"),
            "service_type": j.get("service_type") or j.get("job_type"),
            "customer_id": j.get("customer_id"),
            "customer_name": j.get("customer_name"),
            "customer_display_name": display_name,
            "property_id": j.get("property_id"),
            "property_label": j.get("property_label"),
            "scheduled_start": j.get("scheduled_start"),
            "scheduled_end": j.get("scheduled_end"),
            "status": j.get("status"),
            "route_order": j.get("route_order"),
            "address": geo.get("address"),
            "lat": geo.get("lat"),
            "lng": geo.get("lng"),
            "address_source": geo.get("address_source"),
        })

    return {
        "tech_id": tech_id,
        "tech_name": tech_user.get("name"),
        "tech_color_hex": tech_user.get("display_color_hex"),
        "date": date_str,
        "count": len(stops),
        "stops": stops,
    }
