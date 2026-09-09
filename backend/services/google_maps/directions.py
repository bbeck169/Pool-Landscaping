"""Phase 17 · Feb-2026 — Google Routes API wrapper (v2).

Uses the modern Routes API (``routes.googleapis.com/directions/v2:computeRoutes``)
rather than the deprecated legacy Directions API. Routes API is the
officially supported successor and supports waypoint optimization
out of the box via ``optimizeWaypointOrder: true``.

Phase I1.7.e Chunk 3 (Feb-2026) additions:
  * :func:`_platform_optimize_route_http` /
    :func:`_platform_compute_route_no_optimize_http` — raw-httpx-plus-
    parse helpers. Isolated so :mod:`services.maps.dispatcher` can
    call them directly for the platform-fallback branch WITHOUT
    creating recursion into the public shim entrypoints.
  * :func:`optimize_route` / :func:`compute_route_no_optimize` now
    take ``tenant_id`` + ``db`` kwargs. When ``MAPS_BYO_ENABLED=true``
    AND ``tenant_id`` is supplied the call routes through
    :func:`services.maps.dispatcher.dispatch_maps_route`. When the
    flag is off, OR ``tenant_id=None``, behavior is byte-for-byte
    identical to pre-Chunk-3.
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


# ═════════════════════════════════════════════════════════════════
# Phase I1.7.e · Chunk 3 · Feb-2026 — Platform raw-httpx impls.
# Extracted so :mod:`services.maps.dispatcher` can call them for the
# platform-fallback branch without recursing through the public
# ``optimize_route`` / ``compute_route_no_optimize`` entrypoints.
# ═════════════════════════════════════════════════════════════════
async def _platform_optimize_route_http(
    origin: Tuple[float, float],
    waypoints: List[Tuple[float, float]],
    destination: Optional[Tuple[float, float]] = None,
) -> Optional[Dict[str, Any]]:
    """Raw Routes v2 optimize call — no BYO / no cap enforcement."""
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
    if not parsed["ordered_indices"]:
        parsed["ordered_indices"] = list(range(len(waypoints)))
    return parsed


async def _platform_compute_route_no_optimize_http(
    origin: Tuple[float, float],
    waypoints: List[Tuple[float, float]],
    destination: Optional[Tuple[float, float]] = None,
) -> Optional[Dict[str, Any]]:
    """Raw Routes v2 pinned-order call — no BYO / no cap enforcement."""
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


# ─── BYO-aware dispatch helper ───────────────────────────────────
async def _maybe_dispatch_route(
    *, tenant_id: Optional[str],
    origin: Tuple[float, float],
    waypoints: List[Tuple[float, float]],
    destination: Optional[Tuple[float, float]] = None,
    db_conn: Any = None,
) -> Optional[Dict[str, Any]]:
    """When ``MAPS_BYO_ENABLED=true`` AND ``tenant_id`` is supplied,
    route through the dispatcher and reshape to the legacy dict
    contract. Returns ``None`` on cap-exceeded (transactional
    callers should call :func:`raise_if_maps_cap_exceeded` themselves
    if they want a 429 instead)."""
    try:
        from services.maps.feature_flag import maps_byo_enabled
        from services.maps.dispatcher import dispatch_maps_route
        from services.maps.models import TenantMapsRequestCapExceeded
    except Exception:
        return None
    if not (tenant_id and maps_byo_enabled()):
        return None
    dest = destination or origin
    all_dests = [*waypoints, dest]
    try:
        env = await dispatch_maps_route(
            tenant_id=tenant_id, origin=origin,
            destinations=all_dests, db=db_conn,
        )
    except TenantMapsRequestCapExceeded as cap:
        logger.warning(
            "[routes-v2] tenant=%s cap exceeded provider=%s used=%s/%s",
            tenant_id, cap.provider, cap.used, cap.cap,
        )
        return {
            "cap_exceeded": True,
            "error": "maps_spend_cap_exceeded",
            "http_status": 429,
            "provider": cap.provider,
        }
    except Exception as e:  # pragma: no cover
        logger.warning("[routes-v2] dispatcher error: %s", e)
        return None
    return {
        "ordered_indices": env.ordered_indices or list(range(len(waypoints))),
        "polyline": env.polyline or "",
        "total_distance_m": env.total_distance_m,
        "total_duration_s": env.total_duration_s,
        "legs": [
            {"distance_m": leg.distance_m, "duration_s": leg.duration_s,
             "start_address": "", "end_address": ""}
            for leg in env.legs
        ],
    }


async def optimize_route(
    origin: Tuple[float, float],
    waypoints: List[Tuple[float, float]],
    destination: Optional[Tuple[float, float]] = None,
    *,
    tenant_id: Optional[str] = None,
    db_conn: Any = None,
) -> Optional[Dict[str, Any]]:
    """Optimizer with waypoint reordering.

    Phase I1.7.e Chunk 3: when ``MAPS_BYO_ENABLED`` + ``tenant_id``,
    routes through the BYO Maps dispatcher. Otherwise raw platform.
    """
    dispatched = await _maybe_dispatch_route(
        tenant_id=tenant_id, origin=origin, waypoints=waypoints,
        destination=destination, db_conn=db_conn,
    )
    if dispatched is not None:
        if dispatched.get("cap_exceeded"):
            return None
        # Optimize path — dispatcher doesn't currently reorder,
        # so we fall back to raw impl for the reorder-specific
        # ``ordered_indices`` payload. This matches Chunk 3 sizing —
        # the dispatcher's ``route`` op is pinned-order.
    return await _platform_optimize_route_http(origin, waypoints, destination)


async def compute_route_no_optimize(
    origin: Tuple[float, float],
    waypoints: List[Tuple[float, float]],
    destination: Optional[Tuple[float, float]] = None,
    *,
    tenant_id: Optional[str] = None,
    db_conn: Any = None,
) -> Optional[Dict[str, Any]]:
    """Pinned-order compute — used to measure the caller's baseline.

    Phase I1.7.e Chunk 3: when ``MAPS_BYO_ENABLED`` + ``tenant_id``,
    routes through the BYO Maps dispatcher. Otherwise raw platform.
    """
    dispatched = await _maybe_dispatch_route(
        tenant_id=tenant_id, origin=origin, waypoints=waypoints,
        destination=destination, db_conn=db_conn,
    )
    if dispatched is not None:
        if dispatched.get("cap_exceeded"):
            return None
        return dispatched
    return await _platform_compute_route_no_optimize_http(
        origin, waypoints, destination,
    )
