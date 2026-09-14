"""Feb-2026 · Phase — Recommended Schedule (auto-assign v1).

Route-proximity auto-assignment for freshly-created recurring
job templates. Fires ONLY when the caller left BOTH
``assigned_tech_id`` and ``day_of_week`` unset on
``POST /api/recurring-jobs`` — any manual field wins cleanly.

Algorithm (centroid v1, in-memory, no external API calls):

  1. Ensure the new customer has coords. If not, skip with
     reason ``no_geocode``.
  2. Query existing active recurring templates that share
     ``(tenant_id, service_type, frequency, is_active=True)``.
     If none exist → ``no_existing_routes``.
  3. Group results into route slots keyed on
     ``(day_of_week, assigned_tech_id)``. Slots with a null
     ``day_of_week`` OR a null ``assigned_tech_id`` are skipped
     (they contribute nothing usable to a "recommend a slot"
     decision).
  4. Compute the centroid (avg lat, avg lng) of each slot from
     the coords of every customer bound to any template in that
     slot. Slots where every customer lacks coords are skipped
     with a warning log.
  5. Compute Haversine distance (metres) from the new customer
     to each surviving centroid.
  6. Pick the minimum-distance slot; stamp its ``day_of_week``
     and ``assigned_tech_id`` on the new record.

The extra-drive-time estimate assumes 45 km/h average urban
speed → 750 m per minute. ``extra_minutes = round(distance_m / 750)``.
This is a v1 heuristic — the Google Routes API upgrade behind a
feature flag will replace it with real drive-time estimates.

See ``memory/FEATURE_RECOMMEND_SCHEDULE_AUTO_ASSIGN.md`` for the
UX contract + payload shape + future upgrade path.
"""
from __future__ import annotations

import logging
import math
from typing import Any, Dict, List, Optional, Tuple

from config import db

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────
# Average urban drive speed → seconds-to-metres conversion.
# 45 km/h * 1000 / 3600 = 12.5 m/s → 750 m/min.
_METERS_PER_MINUTE = 750.0
_EARTH_RADIUS_M = 6_371_000.0


def _haversine_m(lat1: float, lng1: float,
                   lat2: float, lng2: float) -> float:
    """Great-circle distance in metres between two lat/lng points.
    Standard Haversine formula — accurate enough for the ~50 km
    urban service-area radius we care about here (< 0.5 % error
    over that range vs. Vincenty)."""
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return _EARTH_RADIUS_M * 2 * math.asin(math.sqrt(a))


def _customer_coords(cust: Dict[str, Any]
                       ) -> Optional[Tuple[float, float]]:
    """Return the canonical ``(lat, lng)`` tuple off a customer
    doc, or None if the customer lacks any usable coord pair.

    Priority: ``latitude/longitude`` (canonical Feb-2026 field
    pair) → ``service_lat/service_lng`` (legacy pre-P37a).
    """
    lat = cust.get("latitude") if cust.get("latitude") is not None \
        else cust.get("service_lat")
    lng = cust.get("longitude") if cust.get("longitude") is not None \
        else cust.get("service_lng")
    if lat is None or lng is None:
        return None
    try:
        return float(lat), float(lng)
    except (TypeError, ValueError):
        return None


async def _lookup_customer_coords(tenant_id: str, customer_id: str
                                     ) -> Optional[Tuple[float, float]]:
    cust = await db.customers.find_one(
        {"id": customer_id, "tenant_id": tenant_id},
        {"_id": 0, "latitude": 1, "longitude": 1,
         "service_lat": 1, "service_lng": 1},
    )
    if not cust:
        return None
    return _customer_coords(cust)


async def _tech_name(tenant_id: str, tech_id: Optional[str]) -> Optional[str]:
    if not tech_id:
        return None
    # Prefer the dedicated ``technicians`` collection, fall back
    # to the shared ``users`` doc — different tenants seed the
    # tech under one or the other depending on their onboarding
    # path.
    for coll in ("technicians", "users"):
        row = await db[coll].find_one(
            {"id": tech_id, "tenant_id": tenant_id},
            {"_id": 0, "name": 1},
        )
        if row and row.get("name"):
            return row["name"]
    return None


async def compute_route_proximity_assignment(
    *, tenant_id: str, body: Dict[str, Any],
) -> Dict[str, Any]:
    """Run the auto-assign step for one ``POST /api/recurring-jobs``
    payload. Returns a dict shaped like:

    ::

        {"auto_assigned": bool,
         "reason": "manual_override" | "no_geocode"
                    | "no_existing_routes" | "route_proximity",
         "assigned_tech_id": str? , "day_of_week": int?,
         "technician_name": str?,
         "extra_minutes": int, "source_meters": int}

    Never raises — a bookkeeping failure MUST NOT break the
    create path. The caller merges the returned tech/day back
    into the doc it's about to persist.
    """
    result: Dict[str, Any] = {
        "auto_assigned": False,
        "reason": "manual_override",
        "assigned_tech_id": None,
        "day_of_week": None,
        "technician_name": None,
        "extra_minutes": 0,
        "source_meters": 0,
    }

    # Trigger gate — any manual field wins.
    if body.get("assigned_tech_id") or body.get("day_of_week") is not None:
        return result
    # A crew-assigned template counts as manual — auto-assign
    # can't reason about crew load in v1.
    if body.get("crew_id"):
        return result

    # 1. Geocode probe.
    coords = await _lookup_customer_coords(
        tenant_id, body.get("customer_id") or "")
    if not coords:
        result["reason"] = "no_geocode"
        return result

    # 2. Peer templates for the same service+frequency.
    service_type = (body.get("service_type") or "").strip()
    frequency = (body.get("frequency") or "").strip()
    peer_cursor = db.recurring_job_templates.find(
        {"tenant_id": tenant_id,
         "service_type": service_type,
         "frequency": frequency,
         "is_active": True},
        {"_id": 0, "customer_id": 1, "assigned_tech_id": 1,
          "day_of_week": 1},
    )
    peers = [r async for r in peer_cursor]
    # Slots without BOTH a tech and a day_of_week are useless —
    # this is what we're recommending, so we can't infer from
    # peers that lack either. Drop them.
    peers = [p for p in peers
                 if p.get("assigned_tech_id")
                 and p.get("day_of_week") is not None]
    if not peers:
        result["reason"] = "no_existing_routes"
        return result

    # 3. Bulk-load customer coords for every peer in one round-trip.
    peer_customer_ids = list({p.get("customer_id") for p in peers
                                  if p.get("customer_id")})
    coord_map: Dict[str, Tuple[float, float]] = {}
    if peer_customer_ids:
        async for c in db.customers.find(
            {"tenant_id": tenant_id,
             "id": {"$in": peer_customer_ids}},
            {"_id": 0, "id": 1, "latitude": 1, "longitude": 1,
              "service_lat": 1, "service_lng": 1},
        ):
            pc = _customer_coords(c)
            if pc:
                coord_map[c["id"]] = pc

    # 4. Group by (day_of_week, assigned_tech_id) → centroid.
    slot_bucket: Dict[Tuple[int, str], List[Tuple[float, float]]] = {}
    for p in peers:
        cid = p.get("customer_id")
        pc = coord_map.get(cid)
        if not pc:
            logger.warning(
                "[auto-assign] peer customer=%s missing coords, "
                "skipping slot contribution", cid,
            )
            continue
        key = (int(p["day_of_week"]), str(p["assigned_tech_id"]))
        slot_bucket.setdefault(key, []).append(pc)

    if not slot_bucket:
        # Every peer customer lacks coords → treat as "no routes"
        # rather than fabricate a centroid.
        result["reason"] = "no_existing_routes"
        return result

    # 5. Compute distance to each centroid, pick the minimum.
    best: Optional[Tuple[float, Tuple[int, str]]] = None
    for (dow, tech_id), pts in slot_bucket.items():
        avg_lat = sum(p[0] for p in pts) / len(pts)
        avg_lng = sum(p[1] for p in pts) / len(pts)
        dist = _haversine_m(coords[0], coords[1], avg_lat, avg_lng)
        if best is None or dist < best[0]:
            best = (dist, (dow, tech_id))

    assert best is not None                                     # slot_bucket check above
    dist_m, (chosen_dow, chosen_tech) = best

    # 6. Stamp result.
    extra_minutes = int(round(dist_m / _METERS_PER_MINUTE))
    result.update({
        "auto_assigned": True,
        "reason": "route_proximity",
        "assigned_tech_id": chosen_tech,
        "day_of_week": chosen_dow,
        "technician_name": await _tech_name(tenant_id, chosen_tech),
        "extra_minutes": extra_minutes,
        "source_meters": int(round(dist_m)),
    })
    return result
