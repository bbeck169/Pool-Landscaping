"""C2 · Feb-2026 — OpenWeather adapter for Chemical Applications.

Fetches current weather conditions (temperature, humidity, wind speed +
direction, sky conditions) from OpenWeather for the C4 chemical-
application create form. Distinct from the NWS widget's ``/weather/*``
endpoints (``routers/weather_v2.py``): OpenWeather supports
geocode-by-address which the widget's coord-only shape does not, and
NWS coverage is US-only whereas OpenWeather is global — critical for
regulatory chemical-application records that must include weather at
the time of spray regardless of jurisdiction.

Contract
────────
    adapter = OpenWeatherAdapter(api_key="...", http_client=None)
    snap    = await adapter.current_by_coords(lat, lon)
    snap    = await adapter.current_by_address("123 Main St, Austin TX")

Error taxonomy (all inherit ``WeatherError``):
    * ``WeatherConfigError``         — 401 from OpenWeather (bad or
                                        missing key).
    * ``WeatherRateLimitError``      — 429 from OpenWeather.
    * ``WeatherServiceUnavailable``  — network / timeout / 5xx / any
                                        other httpx transport failure.
    * ``WeatherAddressNotFoundError``— geocoder returned 0 results.

Caching
───────
In-memory TTL cache per worker. Trade-off vs Mongo ``weather_cache``
(used by NWS widget): no cross-worker sharing + resets on redeploy,
but zero DB round-trip on hit. Revisit if regulatory-grade hit rates
demand cross-worker sharing.

Cache-key normalization:
    * address → ``.lower().strip()`` + collapse internal whitespace.
    * coords  → ``(round(lat, 3), round(lon, 3))`` — ~110 m precision,
                boosts hit rate for nearby jobs on the same property.
TTL: 600 s (10 min) per C2 ruling on chem-app weather freshness.
"""
from __future__ import annotations

import asyncio
import re
import time
from datetime import datetime, timezone
from typing import Literal, Optional

import httpx
from cachetools import TTLCache
from pydantic import BaseModel


# ─────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────
_CURRENT_URL = "https://api.openweathermap.org/data/2.5/weather"
_GEOCODE_URL = "https://api.openweathermap.org/geo/1.0/direct"
_TIMEOUT = httpx.Timeout(connect=10.0, read=10.0, write=10.0, pool=10.0)
_CACHE_TTL_S = 600
_CACHE_MAX = 1024

# 16-point cardinal wheel would over-engineer regulatory records; 8
# points (N, NE, E, SE, S, SW, W, NW) matches how field techs record
# wind on paper forms + how EPA WPS labels reference wind direction.
_CARDINAL_8 = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")


# ─────────────────────────────────────────────────────────────────────
# Exceptions
# ─────────────────────────────────────────────────────────────────────
class WeatherError(Exception):
    """Base class for OpenWeather adapter failures."""


class WeatherConfigError(WeatherError):
    """OPENWEATHER_API_KEY is missing or invalid (upstream 401)."""


class WeatherRateLimitError(WeatherError):
    """OpenWeather rate limit hit (upstream 429)."""


class WeatherServiceUnavailable(WeatherError):
    """Network / timeout / 5xx / any other transport failure."""


class WeatherAddressNotFoundError(WeatherError):
    """Geocoder returned zero results for the supplied address."""


# ─────────────────────────────────────────────────────────────────────
# Response model
# ─────────────────────────────────────────────────────────────────────
class WeatherSnapshot(BaseModel):
    temp_f: float
    humidity_pct: float
    wind_mph: float
    wind_direction: str          # 8-point cardinal
    conditions: str              # e.g. "Clear", "Rain"
    fetched_at: datetime         # UTC
    source: Literal["openweather"] = "openweather"
    lat: float
    lon: float
    resolved_address: Optional[str] = None  # geocoder echo, debugging


# ─────────────────────────────────────────────────────────────────────
# Cache helpers
# ─────────────────────────────────────────────────────────────────────
_WHITESPACE_RUN = re.compile(r"\s+")


def _normalize_address(address: str) -> str:
    """Lowercase + strip + collapse internal whitespace runs to single space."""
    return _WHITESPACE_RUN.sub(" ", address.lower().strip())


def _round_coord(v: float) -> float:
    return round(v, 3)


def _deg_to_cardinal(deg: float) -> str:
    """Convert wind bearing (0-360°) to 8-point cardinal.

    Wheel: N covers 337.5-22.5 (wrap), NE 22.5-67.5, ..., NW 292.5-337.5.
    """
    # Normalize into [0, 360) — OpenWeather returns 0-360 but be defensive.
    d = deg % 360.0
    # Shift by half a bucket (22.5) so N's lower edge becomes 0.
    idx = int((d + 22.5) // 45) % 8
    return _CARDINAL_8[idx]


# ─────────────────────────────────────────────────────────────────────
# Adapter
# ─────────────────────────────────────────────────────────────────────
class OpenWeatherAdapter:
    """Async OpenWeather HTTP adapter with in-memory TTL cache.

    Concurrency: cache mutations are guarded by ``asyncio.Lock`` so
    concurrent requests for the same key don't clobber each other's
    writes. Read-check-write races are still possible but harmless
    (both readers get equivalent snapshots).
    """

    def __init__(
        self,
        api_key: str,
        http_client: Optional[httpx.AsyncClient] = None,
        *,
        cache_ttl_s: int = _CACHE_TTL_S,
        cache_max: int = _CACHE_MAX,
    ) -> None:
        self._api_key = api_key
        self._http = http_client
        # ``timer=lambda: time.time()`` (wall-clock, lazy lookup) instead
        # of TTLCache's default ``time.monotonic`` so ``freezegun.freeze_time``
        # in tests can advance the TTL clock without shipping a
        # separate time-machine dep. The lambda re-derefs ``time.time``
        # on every call so freezegun's module-attribute patch takes
        # effect (a bound reference would capture the pre-patch C fn).
        self._cache: TTLCache = TTLCache(
            maxsize=cache_max, ttl=cache_ttl_s,
            timer=lambda: time.time(),
        )
        self._cache_lock = asyncio.Lock()

    # ── HTTP client lifecycle ──────────────────────────────────────
    async def _client(self) -> httpx.AsyncClient:
        # Match sibling adapters (ai/openai_provider.py, weather/nws.py):
        # DI-injected client wins; fall back to a per-call short-lived
        # client with our timeout policy.
        return self._http or httpx.AsyncClient(timeout=_TIMEOUT)

    async def _http_get(self, url: str, params: dict) -> dict:
        """Wrap httpx GET with our exception taxonomy."""
        client = await self._client()
        owned = self._http is None
        try:
            resp = await client.get(url, params=params)
        except httpx.HTTPError as exc:
            raise WeatherServiceUnavailable(
                f"OpenWeather transport error: {exc}"
            ) from exc
        finally:
            if owned:
                await client.aclose()

        if resp.status_code == 401:
            raise WeatherConfigError(
                "OPENWEATHER_API_KEY invalid or missing"
            )
        if resp.status_code == 429:
            raise WeatherRateLimitError("OpenWeather rate limit exceeded")
        if resp.status_code >= 500:
            raise WeatherServiceUnavailable(
                f"OpenWeather upstream {resp.status_code}"
            )
        if resp.status_code >= 400:
            # Everything else (400/403/404 on a coord we handed it) is
            # treated as service-unavailable rather than mis-classified.
            raise WeatherServiceUnavailable(
                f"OpenWeather returned {resp.status_code}: {resp.text[:200]}"
            )
        try:
            return resp.json()
        except ValueError as exc:  # pragma: no cover — defensive
            raise WeatherServiceUnavailable(
                f"OpenWeather returned non-JSON payload: {exc}"
            ) from exc

    # ── Public API ─────────────────────────────────────────────────
    async def current_by_coords(
        self,
        lat: float,
        lon: float,
        *,
        _resolved_address: Optional[str] = None,
    ) -> WeatherSnapshot:
        key = ("coords", _round_coord(lat), _round_coord(lon))
        cached = self._cache.get(key)
        if cached is not None:
            # Return a copy so callers can't mutate the cached snapshot.
            return cached.model_copy(
                update={"resolved_address": _resolved_address}
                if _resolved_address is not None
                else {}
            )

        data = await self._http_get(
            _CURRENT_URL,
            params={
                "lat": lat,
                "lon": lon,
                "appid": self._api_key,
                "units": "imperial",
            },
        )
        snap = _parse_current(data, lat=lat, lon=lon,
                              resolved_address=_resolved_address)
        async with self._cache_lock:
            self._cache[key] = snap
        return snap

    async def current_by_address(self, address: str) -> WeatherSnapshot:
        key = ("addr", _normalize_address(address))
        cached = self._cache.get(key)
        if cached is not None:
            return cached

        geo = await self._http_get(
            _GEOCODE_URL,
            params={
                "q": address,
                "limit": 1,
                "appid": self._api_key,
            },
        )
        if not isinstance(geo, list) or not geo:
            raise WeatherAddressNotFoundError(
                f"OpenWeather geocoder returned 0 results for {address!r}"
            )
        first = geo[0]
        lat = float(first["lat"])
        lon = float(first["lon"])
        resolved = ", ".join(
            v for v in (
                first.get("name"),
                first.get("state"),
                first.get("country"),
            ) if v
        ) or address
        snap = await self.current_by_coords(
            lat, lon, _resolved_address=resolved
        )
        # Additionally cache the address key so subsequent identical
        # address lookups skip the geocode round-trip entirely.
        async with self._cache_lock:
            self._cache[key] = snap
        return snap


# ─────────────────────────────────────────────────────────────────────
# Response parser
# ─────────────────────────────────────────────────────────────────────
def _parse_current(
    data: dict,
    *,
    lat: float,
    lon: float,
    resolved_address: Optional[str],
) -> WeatherSnapshot:
    """Extract our snapshot fields from OpenWeather's /data/2.5/weather.

    Shape reference:
        {
          "weather":[{"main":"Clear", ...}],
          "main":{"temp":68.2, "humidity":52, ...},
          "wind":{"speed":5.7, "deg":180, ...},
          "coord":{"lat":..., "lon":...},
          "dt": 170...  (unix UTC),
          ...
        }
    Missing keys degrade gracefully to sensible defaults so a partial
    upstream payload doesn't NPE the regulatory record.
    """
    main = data.get("main") or {}
    wind = data.get("wind") or {}
    weather = data.get("weather") or []
    conditions = "Unknown"
    if isinstance(weather, list) and weather:
        first = weather[0] or {}
        conditions = str(first.get("main") or "Unknown")

    return WeatherSnapshot(
        temp_f=float(main.get("temp") or 0.0),
        humidity_pct=float(main.get("humidity") or 0.0),
        wind_mph=float(wind.get("speed") or 0.0),
        wind_direction=_deg_to_cardinal(float(wind.get("deg") or 0.0)),
        conditions=conditions,
        fetched_at=datetime.now(timezone.utc),
        lat=lat,
        lon=lon,
        resolved_address=resolved_address,
    )
