"""Phase G5a · Feb-2026 — Geofence geometry engine.

Pure functions — no DB, no network. Small enough to be exhaustively
unit-tested. Haversine + ray-casting on lat/lon degrees; precision
degrades past ~50km fences at high latitudes (documented, not
critical for our field-service use case).
"""
from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List, Optional

_EARTH_M = 6_371_000.0


def haversine_m(lat1: float, lon1: float,
                    lat2: float, lon2: float) -> float:
    p1 = math.radians(lat1); p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1); dl = math.radians(lon2 - lon1)
    a = (math.sin(dp / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2)
    return _EARTH_M * 2 * math.asin(min(1.0, math.sqrt(a)))


def point_in_circle(lat: float, lon: float,
                        c_lat: float, c_lon: float,
                        radius_m: float) -> bool:
    return haversine_m(lat, lon, c_lat, c_lon) <= float(radius_m)


def point_in_polygon(lat: float, lon: float,
                         points: List[Dict[str, float]]) -> bool:
    """Ray-casting on (lon, lat) as (x, y). Edge case: on-edge is not
    guaranteed inclusive/exclusive — good enough for our use case."""
    if not points or len(points) < 3:
        return False
    inside = False
    n = len(points)
    j = n - 1
    for i in range(n):
        xi = points[i]["lon"]; yi = points[i]["lat"]
        xj = points[j]["lon"]; yj = points[j]["lat"]
        intersect = ((yi > lat) != (yj > lat)) and (
            lon < (xj - xi) * (lat - yi) / ((yj - yi) or 1e-12) + xi)
        if intersect:
            inside = not inside
        j = i
    return inside


def compute_bbox(fence: Dict[str, Any]) -> Dict[str, float]:
    shape = fence.get("shape")
    if shape == "circle":
        c_lat = float(fence["center_lat"])
        c_lon = float(fence["center_lon"])
        r = float(fence["radius_m"])
        # Degrees per meter — good approximation at moderate latitudes.
        d_lat = r / 111_000.0
        d_lon = r / (111_000.0 * max(0.01,
                                         math.cos(math.radians(c_lat))))
        return {
            "min_lat": c_lat - d_lat, "max_lat": c_lat + d_lat,
            "min_lon": c_lon - d_lon, "max_lon": c_lon + d_lon,
        }
    if shape == "polygon":
        pts = fence.get("points") or []
        lats = [p["lat"] for p in pts]
        lons = [p["lon"] for p in pts]
        return {
            "min_lat": min(lats), "max_lat": max(lats),
            "min_lon": min(lons), "max_lon": max(lons),
        }
    return {"min_lat": 0.0, "max_lat": 0.0,
             "min_lon": 0.0, "max_lon": 0.0}


def bbox_hit(lat: float, lon: float, bbox: Dict[str, float]) -> bool:
    return (bbox["min_lat"] <= lat <= bbox["max_lat"]
            and bbox["min_lon"] <= lon <= bbox["max_lon"])


def point_in_fence(lat: float, lon: float,
                       fence: Dict[str, Any]) -> bool:
    bbox = fence.get("bbox") or compute_bbox(fence)
    if not bbox_hit(lat, lon, bbox):
        return False
    if fence.get("shape") == "circle":
        return point_in_circle(
            lat, lon,
            float(fence["center_lat"]), float(fence["center_lon"]),
            float(fence["radius_m"]))
    if fence.get("shape") == "polygon":
        return point_in_polygon(lat, lon, fence.get("points") or [])
    return False
