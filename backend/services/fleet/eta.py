"""FLEET-A · ETA computer with layered fallback.

Provider chain (highest priority first):
  1. Google Distance Matrix — when ``GOOGLE_MAPS_API_KEY`` env is set.
  2. OSRM — when ``OSRM_BASE_URL`` env is set (or fallback to the
     public demo server; log a warning that the demo host is not
     production-safe).
  3. Crow-flies — Haversine great-circle + a fixed 40 km/h city-
     driving assumption. Always available; last-resort.

Never raises: on any HTTP failure it falls through to the next
provider. The board must render even if the network is dead.

Snapshot cache: ``fleet_eta_snapshots`` holds a ``computed_at``
timestamp and a ``stale_at = computed_at + 60s``. Callers may
inspect a snapshot before invoking ``compute_eta`` to skip the
provider call. The router surface layers that on top; this module
only exposes the compute primitive + a dataclass result.
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass
from typing import Optional

import httpx

from config import logger

# Constants shared across providers.
_EARTH_RADIUS_KM = 6371.0088
_CROWFLIES_KMH = 40.0
_HTTP_TIMEOUT = 6.0
_OSRM_DEFAULT = "http://router.project-osrm.org"


@dataclass(frozen=True)
class ETAResult:
    provider: str            # "google" | "osrm" | "crowflies"
    distance_m: int
    duration_s: int


# ─── Provider #3 — Crow-flies (Haversine) ───────────────────────────

def _haversine_m(lat1: float, lon1: float,
                   lat2: float, lon2: float) -> float:
    """Great-circle distance between two lat/lon pairs, in meters."""
    lat1_r, lat2_r = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(lat1_r) * math.cos(lat2_r) * math.sin(dlon / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return _EARTH_RADIUS_KM * 1000 * c


def compute_eta_crowflies(from_lat: float, from_lng: float,
                            to_lat: float, to_lng: float) -> ETAResult:
    distance_m = int(round(_haversine_m(from_lat, from_lng, to_lat, to_lng)))
    duration_s = int(round((distance_m / 1000.0) / _CROWFLIES_KMH * 3600.0))
    return ETAResult(provider="crowflies",
                      distance_m=distance_m, duration_s=duration_s)


# ─── Provider #2 — OSRM ─────────────────────────────────────────────

async def compute_eta_osrm(from_lat: float, from_lng: float,
                             to_lat: float, to_lng: float,
                             *, base_url: Optional[str] = None,
                             client: Optional[httpx.AsyncClient] = None,
                             ) -> Optional[ETAResult]:
    """OSRM ``/route/v1/driving`` — free public demo server or a
    self-hosted URL.  Returns ``None`` on any failure so callers can
    fall through cleanly.
    """
    url_base = base_url or os.environ.get("OSRM_BASE_URL") or _OSRM_DEFAULT
    if url_base == _OSRM_DEFAULT and not os.environ.get("OSRM_BASE_URL"):
        logger.warning(
            "[fleet.eta.osrm] using public demo server %s — not production-safe",
            _OSRM_DEFAULT,
        )
    url = (
        f"{url_base.rstrip('/')}/route/v1/driving/"
        f"{from_lng},{from_lat};{to_lng},{to_lat}"
        f"?overview=false&alternatives=false"
    )
    try:
        _client = client or httpx.AsyncClient(timeout=_HTTP_TIMEOUT)
        async with _client if client is None else _ClientNoOp(_client):
            resp = await _client.get(url)
            if resp.status_code >= 400:
                logger.warning(
                    "[fleet.eta.osrm] http %s from %s", resp.status_code, url,
                )
                return None
            payload = resp.json()
            routes = payload.get("routes") or []
            if not routes:
                return None
            route = routes[0]
            return ETAResult(
                provider="osrm",
                distance_m=int(route.get("distance") or 0),
                duration_s=int(route.get("duration") or 0),
            )
    except Exception as exc:                                       # noqa: BLE001
        logger.warning("[fleet.eta.osrm] request failed: %s", exc)
        return None


class _ClientNoOp:
    """Context-manager wrapper that keeps a shared ``client`` alive
    across a helper call — the caller owns its lifecycle."""
    def __init__(self, client): self.client = client
    async def __aenter__(self): return self.client
    async def __aexit__(self, *_): return None


# ─── Provider #1 — Google Distance Matrix ───────────────────────────

async def compute_eta_google(from_lat: float, from_lng: float,
                                to_lat: float, to_lng: float,
                                *, api_key: Optional[str] = None,
                                client: Optional[httpx.AsyncClient] = None,
                                ) -> Optional[ETAResult]:
    """Google Distance Matrix — returns ``None`` on failure so the
    caller can fall through to OSRM.
    """
    key = api_key or os.environ.get("GOOGLE_MAPS_API_KEY", "")
    if not key:
        return None
    url = (
        "https://maps.googleapis.com/maps/api/distancematrix/json"
        f"?origins={from_lat},{from_lng}"
        f"&destinations={to_lat},{to_lng}"
        f"&units=metric&key={key}"
    )
    try:
        _client = client or httpx.AsyncClient(timeout=_HTTP_TIMEOUT)
        async with _client if client is None else _ClientNoOp(_client):
            resp = await _client.get(url)
            if resp.status_code >= 400:
                logger.warning(
                    "[fleet.eta.google] http %s", resp.status_code,
                )
                return None
            data = resp.json()
            if (data.get("status") or "") != "OK":
                logger.warning(
                    "[fleet.eta.google] status=%s", data.get("status"),
                )
                return None
            rows = data.get("rows") or []
            if not rows:
                return None
            elements = rows[0].get("elements") or []
            if not elements:
                return None
            el = elements[0]
            if el.get("status") != "OK":
                return None
            return ETAResult(
                provider="google",
                distance_m=int((el.get("distance") or {}).get("value") or 0),
                duration_s=int((el.get("duration") or {}).get("value") or 0),
            )
    except Exception as exc:                                       # noqa: BLE001
        logger.warning("[fleet.eta.google] request failed: %s", exc)
        return None


# ─── Public entrypoint — fallback chain ─────────────────────────────

async def compute_eta(from_lat: float, from_lng: float,
                        to_lat: float, to_lng: float,
                        *, client: Optional[httpx.AsyncClient] = None,
                        ) -> ETAResult:
    """Try Google → OSRM → crow-flies. Guaranteed to return an
    ``ETAResult`` (crow-flies is deterministic + local).

    ``client`` is a shared ``httpx.AsyncClient`` for callers that
    want to reuse a connection pool across many computes.
    """
    if os.environ.get("GOOGLE_MAPS_API_KEY"):
        res = await compute_eta_google(
            from_lat, from_lng, to_lat, to_lng, client=client,
        )
        if res is not None:
            return res
        logger.info("[fleet.eta] google failed → falling through to osrm")

    if os.environ.get("OSRM_BASE_URL") or True:                    # noqa: PLR2004
        # OSRM demo is on by default per user brief §3 (with the
        # warning already emitted inside the helper).
        res = await compute_eta_osrm(
            from_lat, from_lng, to_lat, to_lng, client=client,
        )
        if res is not None:
            return res
        logger.info("[fleet.eta] osrm failed → falling through to crowflies")

    return compute_eta_crowflies(from_lat, from_lng, to_lat, to_lng)
