"""Phase 17 · Feb-2026 — Smart route suggestions.

Cheapest-insertion heuristic + haversine distance to recommend
where an unrouted customer should be added. We deliberately do NOT
call the Directions API here — with 100s of unrouted rows the API
cost would balloon. Haversine gives us a fast ordinal ranking; the
frontend can call the existing optimize endpoint after the admin
commits the assignment for millimeter-accurate scheduling.

Confidence tiers:

    high    added_seconds < 600  AND day has ≥4 existing stops
    medium  added_seconds < 1200 OR  day has 2–3 stops
    low     otherwise
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

from config import db

# Rough drive-time constants for haversine → seconds conversion.
_AVG_DRIVE_MPS = 12.0   # ~27 mph urban avg
_DAY_ORDER = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance in meters."""
    R = 6371008.8   # Earth radius, meters
    phi1 = math.radians(lat1); phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1); dl = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def _cheapest_insertion(
    lat: float, lng: float, stops: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Return ``{insertion_index, added_meters, added_seconds}`` for
    inserting a new point into an ordered list of stops."""
    n = len(stops)
    if n == 0:
        return {"insertion_index": 0, "added_meters": 0.0, "added_seconds": 0.0}
    best_idx = 0
    best_add_m = math.inf
    # Try every gap: before stop[0], between i and i+1, after last.
    for i in range(n + 1):
        prev = stops[i - 1] if i > 0 else None
        nxt = stops[i] if i < n else None
        if prev is None:
            # Insert at start — cost is distance from new stop to first.
            add_m = haversine_m(lat, lng, nxt["lat"], nxt["lng"])
        elif nxt is None:
            # Insert at end — cost is distance from last to new stop.
            add_m = haversine_m(prev["lat"], prev["lng"], lat, lng)
        else:
            # Insert between prev and nxt.
            old = haversine_m(prev["lat"], prev["lng"], nxt["lat"], nxt["lng"])
            new = (haversine_m(prev["lat"], prev["lng"], lat, lng)
                   + haversine_m(lat, lng, nxt["lat"], nxt["lng"]))
            add_m = new - old
        if add_m < best_add_m:
            best_add_m = add_m
            best_idx = i
    return {
        "insertion_index": best_idx,
        "added_meters": max(0.0, best_add_m),
        "added_seconds": max(0.0, best_add_m) / _AVG_DRIVE_MPS,
    }


def _confidence(added_s: float, stop_count: int) -> str:
    if added_s < 600 and stop_count >= 4:
        return "high"
    if added_s < 1200 or 2 <= stop_count <= 3:
        return "medium"
    return "low"


async def build_candidate_day_routes(
    tenant_id: str,
    allowed_days: Optional[List[str]] = None,
    preferred_techs: Optional[List[str]] = None,
) -> Dict[str, List[Dict[str, Any]]]:
    """Return ``{"<tech_id>::<day>": [ordered_stops]}`` for every
    geocoded route the tenant currently has. Reads from
    ``dispatch_route_orders`` for the sequence, falls back to the
    denormalized ``service_days`` + ``assigned_tech_ids`` order
    when no explicit sequence is persisted."""
    days_filter = allowed_days or _DAY_ORDER
    tech_filter = set(preferred_techs) if preferred_techs else None

    # 1) Pull explicit route orders.
    order_rows = await db.dispatch_route_orders.find(
        {"tenant_id": tenant_id, "day": {"$in": days_filter}},
        {"_id": 0},
    ).to_list(500)

    # 2) Load all geocoded active customers so we can materialize
    #    their lat/lng for both explicit orders and fallback routes.
    #    Feb-2026 · P27 — explicit ``is_muted != True`` filter for
    #    defense-in-depth (muted rows already carry ``is_active=False``
    #    which the existing branch below excludes, but a future patch
    #    that reintroduces ``is_active=True`` on a muted row must
    #    still be excluded from route optimization).
    cust_rows = await db.customers.find(
        {"tenant_id": tenant_id,
          "service_lat": {"$exists": True, "$ne": None},
          "is_muted": {"$ne": True},
          "$or": [{"is_active": {"$ne": False}}, {"is_active": {"$exists": False}}]},
        {"_id": 0, "id": 1, "name": 1, "service_lat": 1, "service_lng": 1,
          "service_days": 1, "assigned_tech_ids": 1},
    ).to_list(4000)
    by_id = {c["id"]: c for c in cust_rows}

    routes: Dict[str, List[Dict[str, Any]]] = {}
    for row in order_rows:
        tid = row["tech_user_id"]
        if tech_filter and tid not in tech_filter:
            continue
        key = f"{tid}::{row['day']}"
        stops = []
        for cid in row.get("ordered_customer_ids") or []:
            c = by_id.get(cid)
            if c and c.get("service_lat") is not None:
                stops.append({
                    "customer_id": cid, "name": c.get("name") or "",
                    "lat": c["service_lat"], "lng": c["service_lng"],
                })
        if stops:
            routes[key] = stops

    # 3) Fallback — for (tech, day) pairs with no explicit order,
    #    synthesize the route from denorm.
    for c in cust_rows:
        for tid in c.get("assigned_tech_ids") or []:
            if tech_filter and tid not in tech_filter:
                continue
            for d in c.get("service_days") or []:
                if d not in days_filter:
                    continue
                key = f"{tid}::{d}"
                if key in routes:
                    # Already have an explicit ordered route for this
                    # tech+day — don't stomp it with denorm.
                    continue
                routes.setdefault(key, []).append({
                    "customer_id": c["id"], "name": c.get("name") or "",
                    "lat": c["service_lat"], "lng": c["service_lng"],
                })
    return routes


async def suggest_for_customer(
    tenant_id: str,
    customer: Dict[str, Any],
    routes: Dict[str, List[Dict[str, Any]]],
    tech_directory: Dict[str, Dict[str, Any]],
    max_added_seconds: float,
) -> Dict[str, Any]:
    """Compute the top 3 suggestions for a single customer."""
    if customer.get("service_lat") is None:
        return {"customer_id": customer["id"], "suggestion": None,
                "alternatives": []}

    lat, lng = customer["service_lat"], customer["service_lng"]
    scored: List[Dict[str, Any]] = []
    for key, stops in routes.items():
        tid, day = key.split("::", 1)
        ci = _cheapest_insertion(lat, lng, stops)
        if ci["added_seconds"] > max_added_seconds:
            continue
        conf = _confidence(ci["added_seconds"], len(stops))
        tech_info = tech_directory.get(tid) or {}
        rationale = (
            f"Nearest existing stop is "
            f"{ci['added_meters']/1609.344:.1f} mi away on "
            f"{tech_info.get('name') or tid}'s {day.title()} route"
        )
        scored.append({
            "tech_user_id": tid, "tech_name": tech_info.get("name") or tid,
            "tech_color_hex": tech_info.get("color_hex"),
            "service_day": day, "day_label": day.title(),
            "insertion_index": ci["insertion_index"],
            "added_seconds": round(ci["added_seconds"]),
            "added_meters": round(ci["added_meters"]),
            "confidence": conf, "rationale": rationale,
        })
    scored.sort(key=lambda s: s["added_seconds"])

    if scored:
        top = scored[0]
        alts = scored[1:3]
        return {"customer_id": customer["id"], "suggestion": top,
                "alternatives": alts}

    # Fallback — no nearby routes. Recommend the tech with the
    # matching department + their least-loaded day.
    fallback = await _department_fallback(tenant_id, customer, tech_directory)
    return {"customer_id": customer["id"], "suggestion": fallback,
            "alternatives": []}


async def _department_fallback(
    tenant_id: str,
    customer: Dict[str, Any],
    tech_directory: Dict[str, Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Recommend a tech whose department matches one of the
    customer's category names, on that tech's least-loaded day."""
    cats = [c.lower() for c in (customer.get("category_ids") or [])]
    # Pull the tenant's categories to translate ids → names.
    cat_docs = await db.customer_categories.find(
        {"tenant_id": tenant_id, "id": {"$in": customer.get("category_ids") or []}},
        {"_id": 0, "name": 1},
    ).to_list(20)
    cat_names = [d.get("name", "").lower() for d in cat_docs] + cats

    matching_techs = []
    for tid, info in tech_directory.items():
        dept = (info.get("department") or "").lower()
        if any(dept and dept in name for name in cat_names):
            matching_techs.append(tid)

    if not matching_techs:
        # Give up.
        return None

    # Pick the least-loaded tech's least-loaded day.
    best_tid, best_day, best_load = None, "mon", math.inf
    for tid in matching_techs:
        for day in _DAY_ORDER:
            load = await db.customers.count_documents({
                "tenant_id": tenant_id, "assigned_tech_ids": tid,
                "service_days": day,
            })
            if load < best_load:
                best_load = load; best_tid = tid; best_day = day
    info = tech_directory.get(best_tid) or {}
    return {
        "tech_user_id": best_tid,
        "tech_name": info.get("name") or best_tid,
        "tech_color_hex": info.get("color_hex"),
        "service_day": best_day,
        "day_label": best_day.title(),
        "insertion_index": 0,
        "added_seconds": 0, "added_meters": 0,
        "confidence": "low",
        "rationale": "No nearby existing stops — assigned by department match and lightest day.",
    }
