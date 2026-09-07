"""Phase I1.7.c.2 · Feb-2026 — Google Maps BYO provider.

Uses tenant-owned API key against Google's public REST endpoints:
  * Geocoding API: /maps/api/geocode/json
  * Routes API v2: /directions/v2:computeRoutes
  * Static Maps API: /maps/api/staticmap  (URL builder, no HTTP call)

The existing platform-default services under ``services.google_maps.*``
remain in place — this class is called via the tenant registry when
a tenant has ``maps_google`` configured.
"""
from __future__ import annotations

import logging
import urllib.parse
import uuid
from typing import Any, Dict, List, Optional, Tuple

import httpx

from services.secrets import log_error as log_secret_error, mark_used

from ._helpers import (
    load_provider_config,
    maps_testmode_mock,
    now_iso,
)
from .models import (
    ConnectionHealth,
    MapsError,
    MapsGeocodeResult,
    MapsRouteLeg,
    MapsRouteResult,
    MapsStaticMapURL,
    TenantMapsNotConnected,
)
from .tenant_base import MapsProvider


log = logging.getLogger("maps.google")

_GEO_ENDPOINT = "https://maps.googleapis.com/maps/api/geocode/json"
_ROUTES_ENDPOINT = "https://routes.googleapis.com/directions/v2:computeRoutes"
_STATIC_MAP_ENDPOINT = "https://maps.googleapis.com/maps/api/staticmap"
_ROUTES_FIELD_MASK = (
    "routes.duration,routes.distanceMeters,routes.polyline.encodedPolyline,"
    "routes.legs.duration,routes.legs.distanceMeters,"
    "routes.legs.startLocation,routes.legs.endLocation,"
    "routes.optimizedIntermediateWaypointIndex"
)


class GoogleMapsProvider(MapsProvider):
    provider_key = "maps_google"
    short_name = "google"
    primary_secret_field = "api_key"

    config_fields: Dict[str, Dict[str, Any]] = {
        "api_key":     {"required": True,  "secret": True,  "label": "Google Maps API Key"},
        "region_bias": {"required": False, "secret": False, "label": "Region bias (ISO country code, e.g. 'us')"},
    }

    def __init__(self, http_client: Optional[httpx.AsyncClient] = None) -> None:
        self._http = http_client

    async def _client(self) -> httpx.AsyncClient:
        return self._http or httpx.AsyncClient(timeout=15.0)

    async def _cfg(self, tenant_id: str) -> Dict[str, Any]:
        cfg = await load_provider_config(tenant_id=tenant_id, provider_key=self.provider_key)
        if not cfg:
            raise TenantMapsNotConnected(f"Tenant {tenant_id} has no Google Maps config")
        return cfg

    # ── geocode ──────────────────────────────────────────────────
    async def geocode(
        self, *, tenant_id: str, address: str,
        options: Optional[Dict[str, Any]] = None,
    ) -> MapsGeocodeResult:
        cfg = await self._cfg(tenant_id)
        if maps_testmode_mock():
            return MapsGeocodeResult(
                address=address,
                lat=40.7128, lng=-74.0060,
                formatted_address=f"[mock google] {address}",
                provider_response_id=f"gg_mock_{uuid.uuid4().hex[:12]}",
                provider_key=self.provider_key,
                provider_used=f"tenant:{self.short_name}",
                tenant_id=tenant_id,
                raw={"mock": True, "at": now_iso()},
            )
        key = cfg.get("api_key", "")
        params = {"address": address, "key": key}
        region = (options or {}).get("region") or cfg.get("region_bias")
        if region:
            params["region"] = str(region)
        client = await self._client()
        try:
            r = await client.get(_GEO_ENDPOINT, params=params)
            j = r.json() if r.content else {}
            if r.status_code >= 400 or j.get("status") not in ("OK", "ZERO_RESULTS"):
                await log_secret_error(
                    tenant_id, self.provider_key,
                    code=f"GOOGLE_MAPS_GEOCODE_{r.status_code}",
                    message=f"geocode returned {j.get('status')}",
                )
                raise MapsError(f"google-maps geocode HTTP {r.status_code}")
            await mark_used(tenant_id, self.provider_key)
            results = j.get("results") or []
            if not results:
                return MapsGeocodeResult(
                    address=address, lat=0.0, lng=0.0,
                    formatted_address=None, provider_response_id=None,
                    provider_key=self.provider_key,
                    provider_used=f"tenant:{self.short_name}",
                    tenant_id=tenant_id, raw=j,
                )
            top = results[0]
            loc = (top.get("geometry") or {}).get("location") or {}
            return MapsGeocodeResult(
                address=address,
                lat=float(loc.get("lat") or 0.0),
                lng=float(loc.get("lng") or 0.0),
                formatted_address=top.get("formatted_address"),
                provider_response_id=top.get("place_id"),
                provider_key=self.provider_key,
                provider_used=f"tenant:{self.short_name}",
                tenant_id=tenant_id,
                raw=j,
            )
        finally:
            if self._http is None:
                await client.aclose()

    # ── route ────────────────────────────────────────────────────
    async def route(
        self, *, tenant_id: str,
        origin: Tuple[float, float],
        destinations: List[Tuple[float, float]],
        options: Optional[Dict[str, Any]] = None,
    ) -> MapsRouteResult:
        cfg = await self._cfg(tenant_id)
        if maps_testmode_mock():
            return MapsRouteResult(
                legs=[MapsRouteLeg(distance_m=1000, duration_s=120) for _ in destinations],
                total_distance_m=1000 * len(destinations),
                total_duration_s=120 * len(destinations),
                polyline="mock_polyline",
                ordered_indices=list(range(len(destinations))),
                provider_key=self.provider_key,
                provider_used=f"tenant:{self.short_name}",
                tenant_id=tenant_id,
                raw={"mock": True, "at": now_iso()},
            )
        key = cfg.get("api_key", "")
        if not destinations:
            raise MapsError("route: destinations must be non-empty")
        final = destinations[-1]
        intermediates = destinations[:-1]

        def _pt(lat: float, lng: float) -> Dict[str, Any]:
            return {"location": {"latLng": {"latitude": lat, "longitude": lng}}}

        body: Dict[str, Any] = {
            "origin": _pt(*origin),
            "destination": _pt(*final),
            "intermediates": [_pt(la, lo) for la, lo in intermediates],
            "travelMode": (options or {}).get("travelMode", "DRIVE"),
            "routingPreference": (options or {}).get("routingPreference", "TRAFFIC_UNAWARE"),
            "optimizeWaypointOrder": bool((options or {}).get("optimizeWaypointOrder", False)),
        }
        client = await self._client()
        try:
            r = await client.post(
                _ROUTES_ENDPOINT, json=body,
                headers={"X-Goog-Api-Key": key,
                         "X-Goog-FieldMask": _ROUTES_FIELD_MASK,
                         "Content-Type": "application/json"},
            )
            j = r.json() if r.content else {}
            if r.status_code >= 400 or not j.get("routes"):
                await log_secret_error(
                    tenant_id, self.provider_key,
                    code=f"GOOGLE_MAPS_ROUTE_{r.status_code}",
                    message=f"route HTTP {r.status_code}",
                )
                raise MapsError(f"google-maps route HTTP {r.status_code}")
            await mark_used(tenant_id, self.provider_key)
            route0 = (j.get("routes") or [{}])[0]
            legs = route0.get("legs") or []

            def _dur(x: Any) -> int:
                if isinstance(x, (int, float)):
                    return int(x)
                if isinstance(x, str):
                    try:
                        return int(float(x.rstrip("s")))
                    except ValueError:
                        return 0
                return 0

            return MapsRouteResult(
                legs=[MapsRouteLeg(
                    distance_m=int(leg.get("distanceMeters") or 0),
                    duration_s=_dur(leg.get("duration")),
                ) for leg in legs],
                total_distance_m=int(route0.get("distanceMeters") or 0),
                total_duration_s=_dur(route0.get("duration")),
                polyline=((route0.get("polyline") or {}).get("encodedPolyline")) or None,
                ordered_indices=route0.get("optimizedIntermediateWaypointIndex") or [],
                provider_key=self.provider_key,
                provider_used=f"tenant:{self.short_name}",
                tenant_id=tenant_id,
                raw=j,
            )
        finally:
            if self._http is None:
                await client.aclose()

    # ── static map URL builder (no HTTP call) ────────────────────
    async def static_map_url(
        self, *, tenant_id: str,
        center: Optional[Tuple[float, float]] = None,
        path: Optional[List[Tuple[float, float]]] = None,
        size: Tuple[int, int] = (600, 400),
        markers: Optional[List[Tuple[float, float]]] = None,
    ) -> MapsStaticMapURL:
        cfg = await self._cfg(tenant_id)
        key = cfg.get("api_key", "")
        params: List[Tuple[str, str]] = [
            ("size", f"{int(size[0])}x{int(size[1])}"),
            ("key", key or "MOCK"),
        ]
        if center:
            params.append(("center", f"{center[0]},{center[1]}"))
        if path:
            params.append((
                "path", "|".join(f"{la},{lo}" for la, lo in path),
            ))
        for m in (markers or []):
            params.append(("markers", f"{m[0]},{m[1]}"))
        url = f"{_STATIC_MAP_ENDPOINT}?{urllib.parse.urlencode(params)}"
        if not maps_testmode_mock():
            await mark_used(tenant_id, self.provider_key)
        return MapsStaticMapURL(
            url=url,
            provider_key=self.provider_key,
            provider_used=f"tenant:{self.short_name}",
            tenant_id=tenant_id,
        )

    async def test_connection(self, *, tenant_id: str) -> ConnectionHealth:
        cfg = await load_provider_config(tenant_id=tenant_id, provider_key=self.provider_key)
        if not cfg:
            return ConnectionHealth(
                provider_key=self.provider_key, tenant_id=tenant_id,
                ok=False, message="No Google Maps config saved for this tenant.",
                checked_at=now_iso(),
            )
        if maps_testmode_mock():
            return ConnectionHealth(
                provider_key=self.provider_key, tenant_id=tenant_id,
                ok=True, message="mock", checked_at=now_iso(),
            )
        # Cheap probe: geocode a well-known location.
        key = cfg.get("api_key", "")
        client = await self._client()
        try:
            r = await client.get(_GEO_ENDPOINT, params={"address": "Googleplex", "key": key})
            j = r.json() if r.content else {}
            ok = r.status_code == 200 and j.get("status") in ("OK", "ZERO_RESULTS")
            return ConnectionHealth(
                provider_key=self.provider_key, tenant_id=tenant_id,
                ok=ok,
                message=(f"Google Maps geocode probe status={j.get('status')}"
                         if ok else f"probe HTTP {r.status_code} status={j.get('status')}"),
                checked_at=now_iso(),
            )
        except Exception as e:
            return ConnectionHealth(
                provider_key=self.provider_key, tenant_id=tenant_id,
                ok=False, message=f"Google Maps probe failed: {type(e).__name__}",
                checked_at=now_iso(),
            )
        finally:
            if self._http is None:
                await client.aclose()
