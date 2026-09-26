"""C2 · Feb-2026 — OpenWeather HTTP endpoint for Chemical Applications.

Distinct from ``routers/weather.py`` (Open-Meteo forecast) and
``routers/weather_v2.py`` (NWS current widget). This router owns
``GET /weather/openweather/current`` — the endpoint the C4 chemical-
application create form will call to snapshot weather at the moment
of spray for regulatory records.

Path collision policy: this router MUST NOT register a handler on
``/weather/current`` (owned by ``weather_v2.py``) or
``/weather/forecast`` (owned by ``weather.py``). Enforced by
``tests/test_weather_adapter.py::test_openweather_router_does_not_shadow_nws_current``.

Auth: ``require_tech_or_above`` — techs record sprays, admins audit,
managers run compliance reviews. (Behaviorally identical to
``require_tech_or_admin`` today; naming redundancy logged for a
follow-up cleanup task, per C2 discussion.)

Error mapping:
    * ``WeatherConfigError``          → HTTP 500 with ``WEATHER_CONFIG_ERROR``
    * ``WeatherRateLimitError``       → HTTP 503
    * ``WeatherServiceUnavailable``   → HTTP 502
    * ``WeatherAddressNotFoundError`` → HTTP 404
"""
from __future__ import annotations

import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from routers.pool_calculators import require_tech_or_above
from services.weather.openweather_adapter import (
    OpenWeatherAdapter,
    WeatherAddressNotFoundError,
    WeatherConfigError,
    WeatherRateLimitError,
    WeatherServiceUnavailable,
    WeatherSnapshot,
)

router = APIRouter()


# ─────────────────────────────────────────────────────────────────────
# Adapter provider — process-wide singleton so the TTL cache is
# actually shared across requests on the same worker.
# ─────────────────────────────────────────────────────────────────────
_ADAPTER: Optional[OpenWeatherAdapter] = None


def _load_openweather_adapter() -> OpenWeatherAdapter:
    """Return the process-singleton adapter (constructs on first call).

    Raises ``WeatherConfigError`` if ``OPENWEATHER_API_KEY`` is unset.
    Callers (the FastAPI dep below) translate that to HTTP 500 with a
    stable machine-readable code (``WEATHER_CONFIG_ERROR``).
    """
    global _ADAPTER
    if _ADAPTER is not None:
        return _ADAPTER
    api_key = (os.environ.get("OPENWEATHER_API_KEY") or "").strip()
    if not api_key:
        raise WeatherConfigError(
            "OPENWEATHER_API_KEY is not set in the environment"
        )
    _ADAPTER = OpenWeatherAdapter(api_key=api_key)
    return _ADAPTER


def get_openweather_adapter() -> OpenWeatherAdapter:
    """FastAPI dep — wraps ``_load_openweather_adapter`` with HTTP mapping.

    Overridable via ``app.dependency_overrides`` in tests to inject a
    fake adapter without hitting real OpenWeather.
    """
    try:
        return _load_openweather_adapter()
    except WeatherConfigError as exc:
        raise HTTPException(
            status_code=500,
            detail={"code": "WEATHER_CONFIG_ERROR", "message": str(exc)},
        ) from exc


# ─────────────────────────────────────────────────────────────────────
# GET /weather/openweather/current
# ─────────────────────────────────────────────────────────────────────
@router.get("/weather/openweather/current", response_model=WeatherSnapshot)
async def openweather_current(
    address: Optional[str] = Query(
        default=None,
        description="Full postal address; mutually exclusive with lat+lon.",
    ),
    lat: Optional[float] = Query(
        default=None,
        description="Latitude; requires ``lon``. Mutually exclusive with ``address``.",
    ),
    lon: Optional[float] = Query(
        default=None,
        description="Longitude; requires ``lat``. Mutually exclusive with ``address``.",
    ),
    _user: dict = Depends(require_tech_or_above),
    adapter: OpenWeatherAdapter = Depends(get_openweather_adapter),
) -> WeatherSnapshot:
    """Fetch current weather from OpenWeather.

    Exactly one of ``address`` OR (``lat`` AND ``lon``) is required.
    Any other combination → 422.

    Response is the ``WeatherSnapshot`` model — see the adapter module
    for field docs. All results are cached in-memory for 10 min per
    normalized key.
    """
    have_address = bool(address and address.strip())
    have_coords = lat is not None and lon is not None
    have_partial_coords = (lat is None) != (lon is None)

    if have_partial_coords:
        raise HTTPException(
            status_code=422,
            detail="`lat` and `lon` must be provided together",
        )
    if have_address and have_coords:
        raise HTTPException(
            status_code=422,
            detail="Provide either `address` OR (`lat`+`lon`), not both",
        )
    if not have_address and not have_coords:
        raise HTTPException(
            status_code=422,
            detail="Provide either `address` OR (`lat`+`lon`)",
        )

    try:
        if have_address:
            return await adapter.current_by_address(address)  # type: ignore[arg-type]
        # have_coords is True at this point
        return await adapter.current_by_coords(lat, lon)  # type: ignore[arg-type]
    except WeatherConfigError as exc:
        raise HTTPException(
            status_code=500,
            detail={"code": "WEATHER_CONFIG_ERROR", "message": str(exc)},
        ) from exc
    except WeatherRateLimitError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except WeatherAddressNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except WeatherServiceUnavailable as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
