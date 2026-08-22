"""Feb-2026 · P39c — NWS radar (ridge/standard GIF) tests.

Pins the swap from Windy iframe → NWS animated GIF loop URL, plus
the failure-envelope taxonomy (out_of_us, no_radar_station,
upstream_error, no_coords).
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import patch

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

from services.weather import nws

_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = MongoClient(_ENV["MONGO_URL"])[_ENV["DB_NAME"]]
API = "http://localhost:8001/api"


def _login(email="admin@aquaterra.com", pw="password123"):
    r = requests.post(f"{API}/auth/login",
                        json={"email": email, "password": pw}, timeout=15)
    r.raise_for_status()
    return r.json()["access_token"]


@pytest.fixture
def admin_h():
    return {"Authorization": f"Bearer {_login()}"}


# ═════════════════════════════════════════════════════════════════════
# Live smoke — hit the running backend with real NWS.
# ═════════════════════════════════════════════════════════════════════
def test_phoenix_returns_nws_provider_with_station(admin_h):
    """Real /points lookup against Phoenix → NWS provider + radar
    station code + both URL forms."""
    r = requests.get(
        f"{API}/weather/radar?lat=33.5806&lon=-112.2374",
        headers=admin_h, timeout=30)
    assert r.status_code == 200, r.text
    body = r.json()
    if not body.get("ok"):
        pytest.skip(f"Upstream NWS unavailable: {body.get('reason')}")
    assert body["provider"] == "nws"
    station = body["radar_station"]
    assert isinstance(station, str) and len(station) == 4, station
    assert body["loop_url"] == (
        f"https://radar.weather.gov/ridge/standard/{station}_loop.gif")
    assert body["still_url"] == (
        f"https://radar.weather.gov/ridge/standard/{station}_0.gif")
    assert "refreshed_at" in body


def test_london_returns_out_of_us_envelope(admin_h):
    """Real /points lookup against London → 404 → ``out_of_us``."""
    r = requests.get(
        f"{API}/weather/radar?lat=51.5074&lon=-0.1278",
        headers=admin_h, timeout=30)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is False
    assert body["reason"] == "out_of_us"


def test_endpoint_still_registered_in_openapi():
    r = requests.get(f"{API}/openapi.json", timeout=15)
    assert r.status_code == 200
    assert "/api/weather/radar" in (r.json().get("paths") or {})


# ═════════════════════════════════════════════════════════════════════
# Unit-level pins — mock get_points to force the two branch outcomes
# that real network can't cheaply exercise (metadata missing
# radar_station + successful-with-station).
# ═════════════════════════════════════════════════════════════════════
def test_no_radar_station_when_metadata_missing(admin_h):
    """``get_points`` succeeds but the response has no ``radar_station``
    — router must return ``{ok:false, reason:"no_radar_station"}``."""
    async def _fake_points(lat, lon):
        return {
            "ok": True,
            "forecast_url": "https://api.weather.gov/f",
            "forecast_hourly_url": "https://api.weather.gov/fh",
            "observation_stations_url": "https://api.weather.gov/os",
            "radar_station": None,  # ← the branch under test
            "cwa": "PSR", "time_zone": "America/Phoenix",
            "grid_id": "PSR", "grid_x": 0, "grid_y": 0,
        }

    with patch.object(nws, "get_points", _fake_points):
        # Hit the running backend directly — monkeypatching there
        # won't reach the supervisor-managed process, so use
        # `patch.object` scoped to imports inside the router by
        # patching the shared module reference. The router does
        # ``from services.weather import nws`` and calls
        # ``nws.get_points(...)`` — patching the module attribute
        # affects the running process only when we reach the code
        # in-process. Since we can't, we exercise this branch via
        # `_run` around the router coroutine directly.
        from routers.weather_v2 import weather_radar

        async def _call():
            # Bypass the auth dep by calling the coroutine directly
            # — we only care about the branch's return value.
            return await weather_radar(lat=33.5806, lon=-112.2374,
                                              _user={"role": "admin"})

        body = asyncio.new_event_loop().run_until_complete(_call())
    assert body["ok"] is False
    assert body["reason"] == "no_radar_station"


def test_out_of_us_when_points_returns_404_branch():
    """``get_points`` returns ``{ok:false, reason:"out_of_us"}`` →
    router forwards the same reason."""
    async def _fake_points(lat, lon):
        return {"ok": False, "reason": "out_of_us"}

    with patch.object(nws, "get_points", _fake_points):
        from routers.weather_v2 import weather_radar

        async def _call():
            return await weather_radar(lat=51.5074, lon=-0.1278,
                                              _user={"role": "admin"})
        body = asyncio.new_event_loop().run_until_complete(_call())
    assert body["ok"] is False
    assert body["reason"] == "out_of_us"


def test_upstream_error_propagates():
    async def _fake_points(lat, lon):
        return {"ok": False, "reason": "upstream_error"}

    with patch.object(nws, "get_points", _fake_points):
        from routers.weather_v2 import weather_radar

        async def _call():
            return await weather_radar(lat=33.5806, lon=-112.2374,
                                              _user={"role": "admin"})
        body = asyncio.new_event_loop().run_until_complete(_call())
    assert body["ok"] is False
    assert body["reason"] == "upstream_error"


def test_successful_branch_shape_pinned():
    """Full happy-path shape assertion (unit-level, no real network)."""
    async def _fake_points(lat, lon):
        return {
            "ok": True,
            "forecast_url": "https://api.weather.gov/f",
            "forecast_hourly_url": "https://api.weather.gov/fh",
            "observation_stations_url": "https://api.weather.gov/os",
            "radar_station": "KIWA",
            "cwa": "PSR", "time_zone": "America/Phoenix",
            "grid_id": "PSR", "grid_x": 0, "grid_y": 0,
        }

    with patch.object(nws, "get_points", _fake_points):
        from routers.weather_v2 import weather_radar

        async def _call():
            return await weather_radar(lat=33.5806, lon=-112.2374,
                                              _user={"role": "admin"})
        body = asyncio.new_event_loop().run_until_complete(_call())

    assert body["ok"] is True
    assert body["provider"] == "nws"
    assert body["radar_station"] == "KIWA"
    assert body["loop_url"] == (
        "https://radar.weather.gov/ridge/standard/KIWA_loop.gif")
    assert body["still_url"] == (
        "https://radar.weather.gov/ridge/standard/KIWA_0.gif")
    assert "refreshed_at" in body
    # Cache key deliberately absent from the response — the router
    # doesn't consult ``weather_cache`` for radar per P39c spec.
    assert "cache" not in body


def test_no_radar_ttl_key_in_cache_dict():
    """P39c spec — the TTL dict must NOT include a ``radar`` /
    ``nws_radar`` entry. Radar is browser-cached only."""
    from routers.weather_v2 import CACHE_TTL_S
    assert "radar" not in CACHE_TTL_S
    assert "nws_radar" not in CACHE_TTL_S
