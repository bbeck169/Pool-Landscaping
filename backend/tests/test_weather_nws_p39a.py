"""Feb-2026 · P39a — NWS (api.weather.gov) adapter tests.

Contract pins for ``services.weather.nws`` and the router endpoints
that consume it. NWS is mocked at the httpx transport layer so we
never hit the real API from CI.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

from services.weather import nws
from services.weather.nws import NWS_USER_AGENT, NWS_ACCEPT

_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = MongoClient(_ENV["MONGO_URL"])[_ENV["DB_NAME"]]
API = "http://localhost:8001/api"


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


# ─── Auth helpers ────────────────────────────────────────────────────
def _login(email: str, pw: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login",
                        json={"email": email, "password": pw}, timeout=15)
    r.raise_for_status()
    return r.json()["access_token"]


@pytest.fixture
def admin_h():
    return {"Authorization": f"Bearer {_login('admin@aquaterra.com')}"}


# ─── httpx mock helpers ──────────────────────────────────────────────
class _FakeResp:
    def __init__(self, status_code=200, json_data=None, raise_on_json=False):
        self.status_code = status_code
        self._json = json_data or {}
        self._raise = raise_on_json

    def json(self):
        if self._raise:
            raise ValueError("bad json")
        return self._json


def _points_payload():
    return {
        "properties": {
            "forecast": "https://api.weather.gov/gridpoints/PSR/155,60/forecast",
            "forecastHourly": "https://api.weather.gov/gridpoints/PSR/155,60/forecast/hourly",
            "observationStations": "https://api.weather.gov/gridpoints/PSR/155,60/stations",
            "radarStation": "KIWA",
            "cwa": "PSR",
            "timeZone": "America/Phoenix",
            "gridId": "PSR", "gridX": 155, "gridY": 60,
        },
    }


def _stations_payload():
    return {
        "features": [
            {"id": "https://api.weather.gov/stations/KDVT",
             "properties": {"stationIdentifier": "KDVT"}},
        ],
    }


def _observation_payload():
    return {
        "properties": {
            "timestamp": "2026-06-01T15:00:00+00:00",
            "temperature": {"value": 20.0, "unitCode": "wmoUnit:degC"},
            "heatIndex": {"value": 22.0, "unitCode": "wmoUnit:degC"},
            "windChill": {"value": None, "unitCode": "wmoUnit:degC"},
            "windSpeed": {"value": 16.0, "unitCode": "km_h-1"},
            "relativeHumidity": {"value": 45.0, "unitCode": "wmoUnit:percent"},
            "textDescription": "Sunny",
            "icon": "https://api.weather.gov/icons/land/day/skc?size=medium",
        },
    }


def _daily_payload_12_periods():
    periods = []
    dates = ["2026-06-01", "2026-06-02", "2026-06-03",
              "2026-06-04", "2026-06-05", "2026-06-06"]
    for i, d in enumerate(dates):
        periods.append({
            "startTime": f"{d}T06:00:00-07:00",
            "isDaytime": True,
            "temperature": 100 + i,
            "shortForecast": "Sunny",
            "icon": f"https://icon/{d}-day",
            "probabilityOfPrecipitation": {"value": 10 + i},
        })
        periods.append({
            "startTime": f"{d}T18:00:00-07:00",
            "isDaytime": False,
            "temperature": 75 + i,
            "shortForecast": "Clear",
            "icon": f"https://icon/{d}-night",
            "probabilityOfPrecipitation": {"value": None},
        })
    return {"properties": {"periods": periods}}


def _hourly_payload():
    return {"properties": {"periods": [
        {"startTime": "2026-06-01T15:00:00-07:00",
         "temperature": 92, "shortForecast": "Sunny",
         "icon": "https://icon/1",
         "probabilityOfPrecipitation": {"value": 10}},
        {"startTime": "2026-06-01T16:00:00-07:00",
         "temperature": 93, "shortForecast": "Sunny",
         "icon": "https://icon/2",
         "probabilityOfPrecipitation": {"value": 60}},
        {"startTime": "2026-06-01T17:00:00-07:00",
         "temperature": 90, "shortForecast": "Cloudy",
         "icon": "https://icon/3",
         "probabilityOfPrecipitation": {"value": 49}},
        {"startTime": "2026-06-01T18:00:00-07:00",
         "temperature": 88, "shortForecast": "Cloudy",
         "icon": "https://icon/4",
         "probabilityOfPrecipitation": {"value": None}},
    ]}}


def _alerts_payload_with_freeze():
    return {"features": [{
        "properties": {
            "event": "Freeze Warning",
            "severity": "Moderate",
            "headline": "Freeze Warning in effect until 9 AM MST",
            "expires": "2026-11-15T16:00:00+00:00",
            "id": "https://api.weather.gov/alerts/urn:oid:2.49.0.1.840",
        },
    }]}


def _alerts_empty():
    return {"features": []}


def _make_client_get(routes: dict):
    recorded: list = []

    async def _get(url, headers=None, timeout=None):
        recorded.append((url, headers or {}))
        for needle, resp in routes.items():
            if needle in url:
                return resp
        return _FakeResp(status_code=404, json_data={})

    _get.recorded = recorded  # type: ignore[attr-defined]
    return _get


class _FakeAsyncClient:
    def __init__(self, get_fn):
        self.get = get_fn

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _install_httpx(routes):
    """Install a mock httpx.AsyncClient into the nws module and return
    a (get_fn, cleanup) pair."""
    get_fn = _make_client_get(routes)
    client = _FakeAsyncClient(get_fn)
    patcher = patch.object(nws.httpx, "AsyncClient",
                                lambda *a, **kw: client)
    patcher.start()
    return get_fn, patcher.stop


# ═════════════════════════════════════════════════════════════════════
# Unit tests — sync wrappers around async helpers via asyncio.run.
# ═════════════════════════════════════════════════════════════════════
def test_get_points_normalizes_fields():
    _, stop = _install_httpx({"/points/": _FakeResp(200, _points_payload())})
    try:
        r = _run(nws.get_points(33.5806, -112.2374))
    finally:
        stop()
    assert r["ok"] is True
    assert r["forecast_url"].endswith("/forecast")
    assert r["forecast_hourly_url"].endswith("/forecast/hourly")
    assert r["observation_stations_url"].endswith("/stations")
    assert r["radar_station"] == "KIWA"
    assert r["time_zone"] == "America/Phoenix"


def test_get_current_si_to_us_conversion():
    _, stop = _install_httpx({
        "/points/": _FakeResp(200, _points_payload()),
        "/gridpoints/PSR/155,60/stations": _FakeResp(200, _stations_payload()),
        "/stations/KDVT/observations/latest": _FakeResp(200, _observation_payload()),
    })
    try:
        r = _run(nws.get_current(33.5806, -112.2374))
    finally:
        stop()
    assert r["ok"] is True
    cur = r["current"]
    assert cur["temp_f"] == 68.0     # 20 °C
    assert cur["temp_c"] == 20.0
    assert cur["feelslike_f"] == 71.6  # 22 °C heatIndex
    assert cur["wind_mph"] == 9.9      # 16 km/h
    assert cur["humidity"] == 45
    assert cur["uv"] is None
    assert cur["condition_text"] == "Sunny"
    assert "api.weather.gov/icons/" in cur["condition_icon"]


def test_get_daily_folds_12_periods_to_seven_rows():
    _, stop = _install_httpx({
        "/points/": _FakeResp(200, _points_payload()),
        "/gridpoints/PSR/155,60/forecast": _FakeResp(
            200, _daily_payload_12_periods()),
    })
    try:
        r = _run(nws.get_daily(33.5806, -112.2374, days=7))
    finally:
        stop()
    assert r["ok"] is True
    assert r["days_returned"] == 6
    first = r["daily"][0]
    assert first["date"] == "2026-06-01"
    assert first["high"] == 100
    assert first["low"] == 75
    assert first["condition_text"] == "Sunny"
    assert first["chance_of_rain"] == 10


def test_get_hourly_will_it_rain_ge_50():
    _, stop = _install_httpx({
        "/points/": _FakeResp(200, _points_payload()),
        "/gridpoints/PSR/155,60/forecast/hourly": _FakeResp(200, _hourly_payload()),
    })
    try:
        r = _run(nws.get_hourly(33.5806, -112.2374, hours=24))
    finally:
        stop()
    assert r["ok"] is True
    rows = r["hourly"]
    assert len(rows) == 4
    flags = [row["will_it_rain"] for row in rows]
    assert flags == [0, 1, 0, 0]
    assert rows[1]["chance_of_rain"] == 60


def test_get_alerts_normalizes_features():
    _, stop = _install_httpx(
        {"/alerts/active": _FakeResp(200, _alerts_payload_with_freeze())})
    try:
        r = _run(nws.get_alerts(33.5806, -112.2374))
    finally:
        stop()
    assert r["ok"] is True
    assert len(r["alerts"]) == 1
    a = r["alerts"][0]
    assert a == {
        "event": "Freeze Warning",
        "severity": "Moderate",
        "headline": "Freeze Warning in effect until 9 AM MST",
        "expires_at": "2026-11-15T16:00:00+00:00",
        "url": "https://api.weather.gov/alerts/urn:oid:2.49.0.1.840",
    }


def test_get_alerts_empty_when_no_active():
    _, stop = _install_httpx({"/alerts/active": _FakeResp(200, _alerts_empty())})
    try:
        r = _run(nws.get_alerts(33.5806, -112.2374))
    finally:
        stop()
    assert r["ok"] is True
    assert r["alerts"] == []


# ═════════════════════════════════════════════════════════════════════
# Failure semantics.
# ═════════════════════════════════════════════════════════════════════
def test_out_of_us_all_helpers():
    _, stop = _install_httpx({"/points/": _FakeResp(404, {})})
    try:
        lat, lon = 51.5074, -0.1278  # London
        assert _run(nws.get_points(lat, lon))["reason"] == "out_of_us"
        assert _run(nws.get_current(lat, lon))["reason"] == "out_of_us"
        assert _run(nws.get_daily(lat, lon))["reason"] == "out_of_us"
        assert _run(nws.get_hourly(lat, lon))["reason"] == "out_of_us"
    finally:
        stop()


def test_transport_error_returns_upstream_error():
    async def _boom(url, headers=None, timeout=None):
        raise httpx.ConnectError("boom")
    client = _FakeAsyncClient(_boom)
    patcher = patch.object(nws.httpx, "AsyncClient",
                                 lambda *a, **kw: client)
    patcher.start()
    try:
        r = _run(nws.get_current(33.5806, -112.2374))
    finally:
        patcher.stop()
    assert r["ok"] is False
    assert r["reason"] == "upstream_error"


def test_5xx_upstream_returns_upstream_error():
    _, stop = _install_httpx({"/points/": _FakeResp(500, {})})
    try:
        r = _run(nws.get_current(33.5806, -112.2374))
    finally:
        stop()
    assert r["ok"] is False
    assert r["reason"] == "upstream_error"


def test_bad_json_returns_bad_response():
    _, stop = _install_httpx(
        {"/points/": _FakeResp(200, raise_on_json=True)})
    try:
        r = _run(nws.get_points(33.5806, -112.2374))
    finally:
        stop()
    assert r["ok"] is False
    assert r["reason"] == "bad_response"


def test_missing_coords_returns_no_coords():
    for fn in (nws.get_points, nws.get_current, nws.get_daily,
                 nws.get_hourly, nws.get_alerts):
        r = _run(fn(None, None))
        assert r["ok"] is False, f"{fn.__name__} should envelope no-coords"
        assert r["reason"] == "no_coords"


def test_user_agent_header_pinned():
    get_fn, stop = _install_httpx(
        {"/points/": _FakeResp(200, _points_payload())})
    try:
        _run(nws.get_points(33.5806, -112.2374))
    finally:
        stop()
    assert len(get_fn.recorded) == 1
    _url, headers = get_fn.recorded[0]
    assert headers.get("User-Agent") == NWS_USER_AGENT
    assert headers.get("Accept") == NWS_ACCEPT


# ═════════════════════════════════════════════════════════════════════
# Endpoint smokes — real-network integration against the running
# backend on localhost:8001. Mocking motor at the test process for
# the TestClient path is fragile (event-loop mismatch with the
# already-initialized async DB client); the running supervisor-managed
# backend is the canonical target. NWS network is stable and cheap.
# ═════════════════════════════════════════════════════════════════════


def test_current_endpoint_smoke(admin_h):
    """Real-network integration — Phoenix coords hit NWS; endpoint
    must return 200 with the envelope shape (ok:true) OR the
    graceful-fail envelope (ok:false with a valid reason)."""
    _sync.weather_cache.delete_many({"endpoint": "nws_current"})
    r = requests.get(
        f"{API}/weather/current?lat=33.5806&lon=-112.2374",
        headers=admin_h, timeout=30)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "ok" in body
    if body["ok"]:
        cur = body.get("current") or {}
        # UV must be null (NWS doesn't publish it — P39a spec).
        assert cur.get("uv") is None
        # Shape guarantees expected by the widget.
        assert "temp_f" in cur
        assert "condition_text" in cur
    else:
        assert body.get("reason") in {"upstream_error", "bad_response",
                                            "out_of_us"}
    assert "cache" in body


def test_current_out_of_us_returns_graceful_envelope(admin_h):
    """London coords → NWS /points 404 → ``{ok:false, reason:"out_of_us"}``.
    Endpoint must return 200 (never 4xx/5xx) so the widget hides."""
    _sync.weather_cache.delete_many({"endpoint": "nws_current"})
    r = requests.get(
        f"{API}/weather/current?lat=51.5074&lon=-0.1278",
        headers=admin_h, timeout=30)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is False
    assert body["reason"] == "out_of_us"


def test_alerts_endpoint_smoke_empty(admin_h):
    """Real-network — /alerts/active for a US point that's typically
    quiet. Envelope shape must be present even when there are 0
    active alerts."""
    _sync.weather_cache.delete_many({"endpoint": "nws_alerts"})
    r = requests.get(
        f"{API}/weather/alerts?lat=33.5806&lon=-112.2374",
        headers=admin_h, timeout=30)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert isinstance(body["alerts"], list)
    # Every alert (if any) must carry the normalized keys.
    for a in body["alerts"]:
        assert set(a.keys()) >= {
            "event", "severity", "headline", "expires_at", "url"}


def test_alerts_endpoint_returns_cached_normalized_shape(admin_h):
    """Seed the ``weather_cache`` with a normalized alerts row and
    verify the endpoint returns it verbatim (proves the router
    consults the cache before touching upstream)."""
    from datetime import datetime, timedelta, timezone
    # Pin unusual coords so no other test contaminates the row.
    lat, lon = 45.001, -95.001
    _sync.weather_cache.delete_many({"endpoint": "nws_alerts",
                                            "lat_r": 45.001, "lon_r": -95.001})
    _sync.weather_cache.insert_one({
        "endpoint": "nws_alerts",
        "lat_r": 45.001, "lon_r": -95.001,
        "cached_at": datetime.now(timezone.utc),
        "expires_at": datetime.now(timezone.utc) + timedelta(seconds=60),
        "payload": {
            "ok": True,
            "location": {"lat": lat, "lon": lon},
            "alerts": [{
                "event": "Freeze Warning",
                "severity": "Moderate",
                "headline": "H",
                "expires_at": "2026-11-15T16:00:00+00:00",
                "url": "https://api.weather.gov/alerts/x",
            }],
        },
    })
    try:
        r = requests.get(
            f"{API}/weather/alerts?lat={lat}&lon={lon}",
            headers=admin_h, timeout=15)
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["cache"] == "hit"
        assert len(body["alerts"]) == 1
        assert body["alerts"][0]["event"] == "Freeze Warning"
    finally:
        _sync.weather_cache.delete_many(
            {"endpoint": "nws_alerts", "lat_r": 45.001, "lon_r": -95.001})


def test_openapi_lists_alerts_endpoint():
    r = requests.get(f"{API}/openapi.json", timeout=15)
    assert r.status_code == 200
    assert "/api/weather/alerts" in (r.json().get("paths") or {})


def test_cache_hits_upstream_only_once(admin_h):
    """Two rapid calls to /weather/current — the first is a miss and
    populates the cache; the second is a hit. Real NWS network is
    fine here since we only care about cache=hit on the second call."""
    # Fresh cache slot.
    _sync.weather_cache.delete_many(
        {"endpoint": "nws_current", "lat_r": 33.581, "lon_r": -112.237})
    r1 = requests.get(
        f"{API}/weather/current?lat=33.581&lon=-112.237",
        headers=admin_h, timeout=30)
    assert r1.status_code == 200
    b1 = r1.json()
    if not b1.get("ok"):
        pytest.skip(f"Upstream NWS unavailable: {b1.get('reason')}")
    assert b1["cache"] == "miss"
    r2 = requests.get(
        f"{API}/weather/current?lat=33.581&lon=-112.237",
        headers=admin_h, timeout=15)
    assert r2.status_code == 200
    assert r2.json()["cache"] == "hit"


# ═════════════════════════════════════════════════════════════════════
# WEATHERAPI_KEY removal audit.
# ═════════════════════════════════════════════════════════════════════
def test_weatherapi_key_removed_from_env():
    import os
    assert os.environ.get("WEATHERAPI_KEY") is None, (
        "WEATHERAPI_KEY should have been removed from .env by P39a")


def test_no_module_reads_weatherapi_key():
    import subprocess
    result = subprocess.run(
        ["grep", "-rn", "WEATHERAPI_KEY", "/app/backend",
         "--include=*.py"],
        capture_output=True, text=True,
    )
    stray = [line for line in result.stdout.splitlines()
                if "test_weather_nws_p39a.py" not in line]
    assert not stray, f"Unexpected WEATHERAPI_KEY reference(s): {stray}"
