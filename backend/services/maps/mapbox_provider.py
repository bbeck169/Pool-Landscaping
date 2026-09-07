"""Phase I1.7.c.2 · Feb-2026 — Mapbox BYO provider.

Mapbox equivalents of the operations exposed by ``MapsProvider``:

  * Geocoding v5: /geocoding/v5/mapbox.places/{query}.json
  * Directions v5: /directions/v5/{profile}/{coordinates}
  * Static Maps v1: /styles/v1/{style}/static/{overlays}/{center}/{size}

Endpoint parameters and response shapes differ from Google's; the
normalised ``MapsGeocodeResult`` / ``MapsRouteResult`` / ``MapsStaticMapURL``
returned here mean callers never have to switch on provider.
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


log = logging.getLogger("maps.mapbox")

_GEO_BASE = "https://api.mapbox.com/geocoding/v5/mapbox.places"
_DIR_BASE = "https://api.mapbox.com/directions/v5/mapbox"
_STATIC_BASE = "https://api.mapbox.com/styles/v1"
_DEFAULT_STYLE = "mapbox/streets-v12"


class MapboxProvider(MapsProvider):
    provider_key = "maps_mapbox"
    short_name = "mapbox"
    primary_secret_field = "api_key"

    config_fields: Dict[str, Dict[str, Any]] = {
        "api_key": {"required": True, "secret": True, "label": "Mapbox Access Token"},
        "style":   {"required": False, "secret": False,
                     "label": "Static Map style (e.g. mapbox/streets-v12)"},
    }

    def __init__(self, http_client: Optional[httpx.AsyncClient] = None) -> None:
        self._http = http_client

    async def _client(self) -> httpx.AsyncClient:
        return self._http or httpx.AsyncClient(timeout=15.0)

    async def _cfg(self, tenant_id: str) -> Dict[str, Any]:
        cfg = await load_provider_config(tenant_id=tenant_id, provider_key=self.provider_key)
        if not cfg:
            raise TenantMapsNotConnected(f"Tenant {tenant_id} has no Mapbox config")
        return cfg

    async def geocode(
        self, *, tenant_id: str, address: str,
        options: Optional[Dict[str, Any]] = None,
    ) -> MapsGeocodeResult:
        cfg = await self._cfg(tenant_id)
        if maps_testmode_mock():
            return MapsGeocodeResult(
                address=address, lat=37.7749, lng=-122.4194,
                formatted_address=f"[mock mapbox] {address}",
                provider_response_id=f"mb_mock_{uuid.uuid4().hex[:12]}",
                provider_key=self.provider_key,
                provider_used=f"tenant:{self.short_name}",
                tenant_id=tenant_id,
                raw={"mock": True, "at": now_iso()},
            )
        key = cfg.get("api_key", "")
        query = urllib.parse.quote(address)
        client = await self._client()
        try:
            r = await client.get(
                f"{_GEO_BASE}/{query}.json",
                params={"access_token": key, "limit": 1},
            )
            j = r.json() if r.content else {}
            if r.status_code >= 400:
                await log_secret_error(
                    tenant_id, self.provider_key,
                    code=f"MAPBOX_GEOCODE_{r.status_code}",
                    message=f"geocode HTTP {r.status_code}",
                )
                raise MapsError(f"mapbox geocode HTTP {r.status_code}")
            await mark_used(tenant_id, self.provider_key)
            feats = j.get("features") or []
            if not feats:
                return MapsGeocodeResult(
                    address=address, lat=0.0, lng=0.0,
                    formatted_address=None, provider_response_id=None,
                    provider_key=self.provider_key,
                    provider_used=f"tenant:{self.short_name}",
                    tenant_id=tenant_id, raw=j,
                )
            top = feats[0]
            center = top.get("center") or [0.0, 0.0]  # [lng, lat]
            return MapsGeocodeResult(
                address=address,
                lat=float(center[1] if len(center) > 1 else 0.0),
                lng=float(center[0] if len(center) > 0 else 0.0),
                formatted_address=top.get("place_name"),
                provider_response_id=top.get("id"),
                provider_key=self.provider_key,
                provider_used=f"tenant:{self.short_name}",
                tenant_id=tenant_id,
                raw=j,
            )
        finally:
            if self._http is None:
                await client.aclose()

    async def route(
        self, *, tenant_id: str,
        origin: Tuple[float, float],
        destinations: List[Tuple[float, float]],
        options: Optional[Dict[str, Any]] = None,
    ) -> MapsRouteResult:
        cfg = await self._cfg(tenant_id)
        if maps_testmode_mock():
            return MapsRouteResult(
                legs=[MapsRouteLeg(distance_m=800, duration_s=90) for _ in destinations],
                total_distance_m=800 * len(destinations),
                total_duration_s=90 * len(destinations),
                polyline="mock_polyline_mb",
                ordered_indices=list(range(len(destinations))),
                provider_key=self.provider_key,
                provider_used=f"tenant:{self.short_name}",
                tenant_id=tenant_id,
                raw={"mock": True, "at": now_iso()},
            )
        key = cfg.get("api_key", "")
        profile = (options or {}).get("profile", "driving")
        coords = [origin] + list(destinations)
        # Mapbox format: "lng,lat;lng,lat;..." (yes, lng first).
        coord_str = ";".join(f"{lo},{la}" for la, lo in coords)
        client = await self._client()
        try:
            r = await client.get(
                f"{_DIR_BASE}/{profile}/{coord_str}",
                params={
                    "access_token": key,
                    "geometries": "polyline",
                    "overview": "full",
                    "steps": "false",
                },
            )
            j = r.json() if r.content else {}
            if r.status_code >= 400 or not (j.get("routes") or []):
                await log_secret_error(
                    tenant_id, self.provider_key,
                    code=f"MAPBOX_DIRECTIONS_{r.status_code}",
                    message=f"directions HTTP {r.status_code}",
                )
                raise MapsError(f"mapbox directions HTTP {r.status_code}")
            await mark_used(tenant_id, self.provider_key)
            route0 = j["routes"][0]
            legs = route0.get("legs") or []
            return MapsRouteResult(
                legs=[MapsRouteLeg(
                    distance_m=int(leg.get("distance") or 0),
                    duration_s=int(leg.get("duration") or 0),
                ) for leg in legs],
                total_distance_m=int(route0.get("distance") or 0),
                total_duration_s=int(route0.get("duration") or 0),
                polyline=route0.get("geometry") or None,
                ordered_indices=list(range(len(destinations))),
                provider_key=self.provider_key,
                provider_used=f"tenant:{self.short_name}",
                tenant_id=tenant_id,
                raw=j,
            )
        finally:
            if self._http is None:
                await client.aclose()

    async def static_map_url(
        self, *, tenant_id: str,
        center: Optional[Tuple[float, float]] = None,
        path: Optional[List[Tuple[float, float]]] = None,
        size: Tuple[int, int] = (600, 400),
        markers: Optional[List[Tuple[float, float]]] = None,
    ) -> MapsStaticMapURL:
        cfg = await self._cfg(tenant_id)
        key = cfg.get("api_key", "")
        style = cfg.get("style") or _DEFAULT_STYLE
        overlays: List[str] = []
        for m in (markers or []):
            overlays.append(f"pin-s+ff0000({m[1]},{m[0]})")
        if path:
            path_str = "polyline(" + urllib.parse.quote(
                ";".join(f"{lo},{la}" for la, lo in path), safe=""
            ) + ")"
            overlays.append(f"path-3+ff0000-0.7({path_str})")
        overlays_str = ",".join(overlays)
        if center:
            centre_str = f"{center[1]},{center[0]},14"
        elif path:
            centre_str = "auto"
        else:
            centre_str = "0,0,1"
        overlays_seg = f"/{overlays_str}" if overlays_str else ""
        url = (
            f"{_STATIC_BASE}/{style}/static"
            f"{overlays_seg}/{centre_str}/{int(size[0])}x{int(size[1])}"
            f"?access_token={urllib.parse.quote(key or 'MOCK')}"
        )
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
                ok=False, message="No Mapbox config saved for this tenant.",
                checked_at=now_iso(),
            )
        if maps_testmode_mock():
            return ConnectionHealth(
                provider_key=self.provider_key, tenant_id=tenant_id,
                ok=True, message="mock", checked_at=now_iso(),
            )
        key = cfg.get("api_key", "")
        client = await self._client()
        try:
            r = await client.get(
                f"{_GEO_BASE}/test.json",
                params={"access_token": key, "limit": 1},
            )
            ok = r.status_code == 200
            return ConnectionHealth(
                provider_key=self.provider_key, tenant_id=tenant_id,
                ok=ok,
                message=("Mapbox geocode probe OK" if ok
                          else f"probe HTTP {r.status_code}"),
                checked_at=now_iso(),
            )
        except Exception as e:
            return ConnectionHealth(
                provider_key=self.provider_key, tenant_id=tenant_id,
                ok=False, message=f"Mapbox probe failed: {type(e).__name__}",
                checked_at=now_iso(),
            )
        finally:
            if self._http is None:
                await client.aclose()
