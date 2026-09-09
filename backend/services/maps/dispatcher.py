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

Phase I1.7.e Chunk 3 additions (Feb-2026):
  * ``dispatch_maps_reverse_geocode`` op with a dedicated cap key
    (``reverse_geocode``). Platform-fallback backend is Mapbox (via
    :mod:`services.reverse_geocoder`).
  * ``MAPS_TESTMODE_MOCK`` short-circuits every op — both BYO and
    platform branches — with a deterministic mock envelope. Enforced
    boot-time via :func:`services.maps.testmode._assert_boot_safe`.
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
# Feb-2026 · P1 parallel fix — Maps BYO empty-credentials fallback.
# Mirrors the comms + AI hotfixes. When the tenant's BYO row is
# ``connected=True`` on paper but every required credential field
# is blank / whitespace, fall through to the platform default
# (Google Maps / Mapbox env keys). Cap-exceeded semantics remain a
# HARD BLOCK per the phase-I1.7.c.2 lock.
from services.byo_common import (
    byo_required_fields_present,
    looks_like_credential_failure,
)


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
    if maps_testmode_mock():
        # Chunk 3 · Feb-2026 — deterministic mock envelope short-circuit.
        from .testmode import mock_geocode_result
        return mock_geocode_result(
            tenant_id=tenant_id, address=address,
            provider_used="platform:testmode_mock",
        )
    if used == "platform:none":
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
        # Chunk 3 · Feb-2026 — reach for the raw-httpx implementation
        # that lives INSIDE the legacy module. When Chunk 3 flag is
        # ON, callers reach us via the shim; the shim skips us and we
        # call the raw httpx directly (no recursion). We import
        # lazily so the legacy module can be a thin shim with the
        # raw-httpx impl gated on ``_dispatcher_platform_call=True``.
        from services.google_maps.geocoding import _platform_geocode_http
        res = await _platform_geocode_http(address)
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


async def _platform_reverse_geocode(
    *, tenant_id: str, lat: float, lng: float,
    options: Optional[Dict[str, Any]] = None,
) -> MapsGeocodeResult:
    """Chunk 3 · Feb-2026 — reverse-geocode platform-fallback path.
    Backed by Mapbox via :mod:`services.reverse_geocoder`."""
    used = "platform:mapbox" if (
        os.environ.get("MAPBOX_ACCESS_TOKEN") or ""
    ).strip() else "platform:none"
    if maps_testmode_mock():
        from .testmode import mock_reverse_geocode_result
        return mock_reverse_geocode_result(
            tenant_id=tenant_id, lat=lat, lng=lng,
            provider_used="platform:testmode_mock",
        )
    if used == "platform:none":
        return MapsGeocodeResult(
            address=f"reverse:{lat},{lng}", lat=float(lat), lng=float(lng),
            formatted_address=None, provider_response_id=None,
            provider_key="maps_platform", provider_used=used,
            tenant_id=tenant_id,
            raw={"platform_no_token": True, "at": now_iso()},
        )
    try:
        from services.reverse_geocoder import _platform_reverse_geocode_http
        res = await _platform_reverse_geocode_http(
            lat=lat, lng=lng, tenant_id=tenant_id,
        )
    except Exception as e:  # pragma: no cover — defensive
        log.warning("[maps.dispatch] platform reverse-geocode error: %s", e)
        res = None
    if not res or res.get("status") != "resolved":
        return MapsGeocodeResult(
            address=f"reverse:{lat},{lng}",
            lat=float(lat), lng=float(lng),
            formatted_address=None, provider_response_id=None,
            provider_key="maps_platform", provider_used=used,
            tenant_id=tenant_id,
            raw={"platform_no_result": True, "status": (res or {}).get("status")},
        )
    parsed = res.get("address") or {}
    return MapsGeocodeResult(
        address=f"reverse:{lat},{lng}",
        lat=float(lat), lng=float(lng),
        formatted_address=parsed.get("formatted"),
        provider_response_id=None,
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
    if maps_testmode_mock():
        from .testmode import mock_route_result
        return mock_route_result(
            tenant_id=tenant_id, origin=origin, destinations=destinations,
            provider_used="platform:testmode_mock",
        )
    if used == "platform:none":
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
        from services.google_maps.directions import (
            _platform_compute_route_no_optimize_http,
        )
        res = await _platform_compute_route_no_optimize_http(
            origin, intermediates, final,
        )
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
    if maps_testmode_mock():
        from .testmode import mock_static_map_url
        return mock_static_map_url(
            tenant_id=tenant_id, center=center, path=path, size=size,
            markers=markers, provider_used="platform:testmode_mock",
        )
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
    # Feb-2026 · P1 parallel fix — BYO empty-credentials guard.
    # Runs BEFORE the cap check so a mis-typed / blanked row never
    # consumes the tenant's monthly quota either.
    from ._helpers import load_provider_config as _maps_load_cfg
    if not await byo_required_fields_present(
        provider, tenant_id, config_loader=_maps_load_cfg, db=db,
    ):
        log.warning(
            "[byo] tenant=%s provider=%s credential fallback → platform",
            tenant_id, getattr(provider, "provider_key", "?"),
        )
        return await call_platform()
    short = short_name_for(provider.provider_key) or provider.provider_key
    await enforce_cap_or_raise(tenant_id=tenant_id, provider=short, db=db)
    try:
        result = await call_tenant(provider)
    except TenantMapsRequestCapExceeded:
        # Cap-exceeded stays HARD BLOCK.
        raise
    except Exception as exc:
        err = f"{type(exc).__name__}: {exc}"
        # Credential-shaped failures fall through to platform.
        if looks_like_credential_failure(err):
            log.warning(
                "[byo] tenant=%s provider=%s op=%s credential-shaped "
                "failure → platform: %s",
                tenant_id, short, operation, err,
            )
            return await call_platform()
        raise
    # Chunk 3, Feb-2026 — reverse_geocode adapters may return None
    # when the provider doesn't implement it → fall back to platform
    # WITHOUT recording usage on the tenant's BYO row.
    if result is None:
        log.info("[maps.dispatch] tenant=%s op=%s BYO returned None — "
                 "falling back to platform", tenant_id, operation)
        return await call_platform()
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


async def dispatch_maps_reverse_geocode(
    *, tenant_id: str, lat: float, lng: float,
    options: Optional[Dict[str, Any]] = None,
    db=None,
) -> MapsGeocodeResult:
    """Chunk 3 · Feb-2026 — reverse-geocode dispatcher op with a
    dedicated cap key (``reverse_geocode``). Providers that don't
    implement :meth:`MapsProvider.reverse_geocode` return ``None`` →
    dispatcher falls back to the platform Mapbox path without
    charging the tenant's BYO cap."""
    return await _dispatch_op(
        tenant_id=tenant_id, operation="reverse_geocode", db=db,
        call_tenant=lambda p: p.reverse_geocode(
            tenant_id=tenant_id, lat=lat, lng=lng, options=options,
        ),
        call_platform=lambda: _platform_reverse_geocode(
            tenant_id=tenant_id, lat=lat, lng=lng, options=options,
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
    "dispatch_maps_reverse_geocode",
    "dispatch_maps_route",
    "dispatch_maps_static_map_url",
    "TenantMapsRequestCapExceeded",
]
