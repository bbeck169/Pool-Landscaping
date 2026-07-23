"""Phase 17 · Feb-2026 — Google Routes API wrapper (v2).

Uses the modern Routes API (``routes.googleapis.com/directions/v2:computeRoutes``)
rather than the deprecated legacy Directions API, which Google
disables by default for new projects. Routes API is the officially
supported successor and supports waypoint optimization out of the
box via ``optimizeWaypointOrder: true``.

The wrapper exposes two entry points:

* ``optimize_route(origin, waypoints, destination=None)`` — asks
  Google to reorder the intermediates for shortest total duration
  and returns ``{ordered_indices, polyline, total_distance_m,
  total_duration_s, legs}``. Never raises; returns ``None`` on any
  failure so the caller falls back to the caller-supplied order.

* ``compute_route_no_optimize(origin, waypoints, destination=None)``
  — same shape but without waypoint reordering. Used to compute
  the caller's baseline drive time so the router can report a
  savings delta.

Auth: ``X-Goog-Api-Key`` header + ``X-Goog-FieldMask`` limiting the
response payload to the fields we consume (Google bills by fields
returned).
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Tuple

import httpx

from config import logger

_API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY", "")
_ENDPOINT = "https://routes.googleapis.com/directions/v2:computeRoutes"
_FIELD_MASK = (
    "routes.duration,routes.distanceMeters,routes.polyline.encodedPolyline,"
    "routes.legs.duration,routes.legs.distanceMeters,"
    "routes.legs.startLocation,routes.legs.endLocation,"
    "routes.optimizedIntermediateWaypointIndex"
)


def _pt(lat: float, lng: float) -> Dict[str, Any]:
    return {"location": {"latLng": {"latitude": lat, "longitude": lng}}}


def _duration_to_seconds(dur: Any) -> int:
    """Routes API returns duration as ``"123s"`` string. Parse defensively."""
    if isinstance(dur, (int, float)):
        return int(dur)
    if isinstance(dur, str):
        s = dur.rstrip("s")
        try:
            return int(float(s))
        except ValueError:
            return 0
    return 0


async def _post(body: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not _API_KEY:
        return None
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": _API_KEY,
        "X-Goog-FieldMask": _FIELD_MASK,
    }
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(_ENDPOINT, json=body, headers=headers)
            data = r.json()
    except Exception as exc:
        logger.warning("[routes-v2] http error: %s", exc)
        return None
    if not data or not isinstance(data, dict) or not data.get("routes"):
        logger.warning("[routes-v2] empty/invalid response: %s", data)
        return None
    return data


def _parse_route(data: Dict[str, Any]) -> Dict[str, Any]:
    route = (data.get("routes") or [{}])[0]
    legs = route.get("legs") or []
    total_dist_m = int(route.get("distanceMeters") or 0)
    total_dur_s = _duration_to_seconds(route.get("duration"))
    polyline = ((route.get("polyline") or {}).get("encodedPolyline")) or ""
    return {
        "ordered_indices": route.get("optimizedIntermediateWaypointIndex") or [],
        "polyline": polyline,
        "total_distance_m": total_dist_m,
        "total_duration_s": total_dur_s,
        "legs": [
            {
                "distance_m": int(leg.get("distanceMeters") or 0),
                "duration_s": _duration_to_seconds(leg.get("duration")),
                "start_address": "",
                "end_address": "",
            }
            for leg in legs
        ],
    }


async def optimize_route(
    origin: Tuple[float, float],
    waypoints: List[Tuple[float, float]],
    destination: Optional[Tuple[float, float]] = None,
) -> Optional[Dict[str, Any]]:
    """Optimizer with waypoint reordering."""
    if not waypoints:
        return None
    dest = destination or origin
    body = {
        "origin": _pt(*origin),
        "destination": _pt(*dest),
        "intermediates": [_pt(lat, lng) for lat, lng in waypoints],
        "travelMode": "DRIVE",
        "routingPreference": "TRAFFIC_UNAWARE",
        "optimizeWaypointOrder": True,
    }
    data = await _post(body)
    if not data:
        return None
    parsed = _parse_route(data)
    # If Google didn't return an optimized index list (e.g. only 1
    # intermediate), synthesize the passthrough sequence so callers
    # can always index into the waypoints array.
    if not parsed["ordered_indices"]:
        parsed["ordered_indices"] = list(range(len(waypoints)))
    return parsed


async def compute_route_no_optimize(
    origin: Tuple[float, float],
    waypoints: List[Tuple[float, float]],
    destination: Optional[Tuple[float, float]] = None,
) -> Optional[Dict[str, Any]]:
    """Pinned-order compute — used to measure the caller's baseline."""
    if not waypoints:
        return None
    dest = destination or origin
    body = {
        "origin": _pt(*origin),
        "destination": _pt(*dest),
        "intermediates": [_pt(lat, lng) for lat, lng in waypoints],
        "travelMode": "DRIVE",
        "routingPreference": "TRAFFIC_UNAWARE",
        "optimizeWaypointOrder": False,
    }
    data = await _post(body)
    return _parse_route(data) if data else None
