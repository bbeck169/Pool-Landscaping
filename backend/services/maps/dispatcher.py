"""Phase I1.7.c.2 · Feb-2026 — ``dispatch_maps_*`` wrappers.

Routes a Maps operation through the tenant's BYO provider if
configured, else falls back to the platform-default provider (env
keys under ``GOOGLE_MAPS_API_KEY`` / ``MAPBOX_ACCESS_TOKEN`` — same
services the app has used all along, kept intact for now).

Fallback rules (identical to AI):
  1. No BYO row for this tenant → fallback to platform default.
  2. BYO row exists but its ``monthly_request_cap`` is reached →
     HARD BLOCK; raise ``TenantMapsRequestCapExceeded``. NO fallback.
  3. BYO row exists and cap ok → dispatch, record usage on success.

**This module deliberately does NOT rewire any existing app maps
call-sites** — that migration is scoped to phase I1.7.e alongside
the AI callsite migration.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional, Tuple

from ._helpers import maps_testmode_mock, now_iso
from .models import (
    MapsError,
    MapsGeocodeResult,
    MapsRouteLeg,
    MapsRouteResult,
    MapsStaticMapURL,
    TenantMapsRequestCapExceeded,
)
from .registry import get_tenant_maps_provider, short_name_for
from .usage import enforce_cap_or_raise, record_usage


log = logging.getLogger("maps.dispatch")


# ── Platform-default fallback path ───────────────────────────────
def _platform_provider_key() -> str:
    """The env-based platform default. Currently ``maps_google`` when
    ``GOOGLE_MAPS_API_KEY`` is set, else ``maps_mapbox`` when
    ``MAPBOX_ACCESS_TOKEN`` is set, else ``maps_platform``."""
    if (os.environ.get("GOOGLE_MAPS_API_KEY") or "").strip():
        return "platform:google"
    if (os.environ.get("MAPBOX_ACCESS_TOKEN") or "").strip():
        return "platform:mapbox"
    return "platform:none"


async def _platform_geocode(
    *, tenant_id: str, address: str,
    options: Optional[Dict[str, Any]] = None,
) -> MapsGeocodeResult:
    """Delegate to the existing ``services.google_maps.geocoding``
    wrapper (env-keyed). Kept simple — the platform default is
    whatever's already wired into the app today."""
    used = _platform_provider_key()
    if maps_testmode_mock() or used == "platform:none":
        return MapsGeocodeResult(
            address=address, lat=0.0, lng=0.0,
            formatted_address=f"[platform fallback] {address}",
            provider_response_id=None,
            provider_key="maps_platform",
            provider_used=used,
            tenant_id=tenant_id,
            raw={"platform": True, "at": now_iso()},
        )
    try:
        from services.google_maps.geocoding import geocode_address
        res = await geocode_address(address)
    except Exception as e:  # pragma: no cover — defensive
        log.warning("[maps.dispatch] platform geocode error: %s", e)
        res = None
    if not res:
        return MapsGeocodeResult(
            address=address, lat=0.0, lng=0.0,
            formatted_address=None, provider_response_id=None,
            provider_key="maps_platform", provider_used=used,
            tenant_id=tenant_id, raw={"platform_no_result": True},
        )
    return MapsGeocodeResult(
        address=address,
        lat=float(res.get("lat") or 0.0),
        lng=float(res.get("lng") or 0.0),
        formatted_address=res.get("formatted_address"),
        provider_response_id=res.get("place_id"),
        provider_key="maps_platform",
        provider_used=used,
        tenant_id=tenant_id,
        raw=res,
    )


async def _platform_route(
    *, tenant_id: str,
    origin: Tuple[float, float],
    destinations: List[Tuple[float, float]],
    options: Optional[Dict[str, Any]] = None,
) -> MapsRouteResult:
    used = _platform_provider_key()
    if maps_testmode_mock() or used == "platform:none":
        return MapsRouteResult(
            legs=[MapsRouteLeg(distance_m=0, duration_s=0) for _ in destinations],
            total_distance_m=0, total_duration_s=0, polyline=None,
            ordered_indices=list(range(len(destinations))),
            provider_key="maps_platform",
            provider_used=used,
            tenant_id=tenant_id,
            raw={"platform": True, "at": now_iso()},
        )
    if not destinations:
        raise MapsError("route: destinations must be non-empty")
    final = destinations[-1]
    intermediates = destinations[:-1]
    try:
        from services.google_maps.directions import compute_route_no_optimize
        res = await compute_route_no_optimize(origin, intermediates, final)
    except Exception as e:  # pragma: no cover — defensive
        log.warning("[maps.dispatch] platform route error: %s", e)
        res = None
    if not res:
        return MapsRouteResult(
            legs=[], total_distance_m=0, total_duration_s=0,
            polyline=None, ordered_indices=[],
            provider_key="maps_platform", provider_used=used,
            tenant_id=tenant_id, raw={"platform_no_result": True},
        )
    return MapsRouteResult(
        legs=[MapsRouteLeg(
            distance_m=int(leg.get("distance_m") or 0),
            duration_s=int(leg.get("duration_s") or 0),
        ) for leg in (res.get("legs") or [])],
        total_distance_m=int(res.get("total_distance_m") or 0),
        total_duration_s=int(res.get("total_duration_s") or 0),
        polyline=res.get("polyline"),
        ordered_indices=res.get("ordered_indices") or [],
        provider_key="maps_platform",
        provider_used=used,
        tenant_id=tenant_id,
        raw=res,
    )


async def _platform_static_map_url(
    *, tenant_id: str,
    center: Optional[Tuple[float, float]] = None,
    path: Optional[List[Tuple[float, float]]] = None,
    size: Tuple[int, int] = (600, 400),
    markers: Optional[List[Tuple[float, float]]] = None,
) -> MapsStaticMapURL:
    used = _platform_provider_key()
    key = (os.environ.get("GOOGLE_MAPS_API_KEY") or "").strip()
    params: List[str] = [f"size={int(size[0])}x{int(size[1])}"]
    if key:
        params.append(f"key={key}")
    if center:
        params.append(f"center={center[0]},{center[1]}")
    if path:
        joined = "|".join(f"{la},{lo}" for la, lo in path)
        params.append(f"path={joined}")
    for m in (markers or []):
        params.append(f"markers={m[0]},{m[1]}")
    url = f"https://maps.googleapis.com/maps/api/staticmap?{'&'.join(params)}"
    return MapsStaticMapURL(
        url=url, provider_key="maps_platform",
        provider_used=used, tenant_id=tenant_id,
    )


# ── Public dispatch entry points ─────────────────────────────────
async def _dispatch_op(
    *, tenant_id: str, operation: str, db=None,
    call_tenant, call_platform,
):
    provider = await get_tenant_maps_provider(tenant_id, db=db)
    if provider is None:
        log.info("[maps.dispatch] tenant=%s no BYO — using platform default",
                 tenant_id)
        return await call_platform()
    short = short_name_for(provider.provider_key) or provider.provider_key
    await enforce_cap_or_raise(tenant_id=tenant_id, provider=short, db=db)
    result = await call_tenant(provider)
    try:
        await record_usage(
            tenant_id=tenant_id, provider=short, operation=operation, db=db,
        )
    except Exception as e:  # pragma: no cover
        log.warning("[maps.dispatch] record_usage failed: %s", e)
    return result


async def dispatch_maps_geocode(
    *, tenant_id: str, address: str,
    options: Optional[Dict[str, Any]] = None,
    db=None,
) -> MapsGeocodeResult:
    return await _dispatch_op(
        tenant_id=tenant_id, operation="geocode", db=db,
        call_tenant=lambda p: p.geocode(
            tenant_id=tenant_id, address=address, options=options,
        ),
        call_platform=lambda: _platform_geocode(
            tenant_id=tenant_id, address=address, options=options,
        ),
    )


async def dispatch_maps_route(
    *, tenant_id: str,
    origin: Tuple[float, float],
    destinations: List[Tuple[float, float]],
    options: Optional[Dict[str, Any]] = None,
    db=None,
) -> MapsRouteResult:
    return await _dispatch_op(
        tenant_id=tenant_id, operation="route", db=db,
        call_tenant=lambda p: p.route(
            tenant_id=tenant_id, origin=origin,
            destinations=destinations, options=options,
        ),
        call_platform=lambda: _platform_route(
            tenant_id=tenant_id, origin=origin,
            destinations=destinations, options=options,
        ),
    )


async def dispatch_maps_static_map_url(
    *, tenant_id: str,
    center: Optional[Tuple[float, float]] = None,
    path: Optional[List[Tuple[float, float]]] = None,
    size: Tuple[int, int] = (600, 400),
    markers: Optional[List[Tuple[float, float]]] = None,
    db=None,
) -> MapsStaticMapURL:
    return await _dispatch_op(
        tenant_id=tenant_id, operation="static_map", db=db,
        call_tenant=lambda p: p.static_map_url(
            tenant_id=tenant_id, center=center, path=path,
            size=size, markers=markers,
        ),
        call_platform=lambda: _platform_static_map_url(
            tenant_id=tenant_id, center=center, path=path,
            size=size, markers=markers,
        ),
    )


__all__ = [
    "dispatch_maps_geocode",
    "dispatch_maps_route",
    "dispatch_maps_static_map_url",
    "TenantMapsRequestCapExceeded",
]
