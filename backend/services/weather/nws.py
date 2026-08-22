"""Feb-2026 · P39a — National Weather Service (api.weather.gov) adapter.

Replaces the WeatherAPI.com upstream used by ``routers/weather_v2.py``
with NWS's public JSON API. Same envelope shape the frontend already
consumes so the P39b widget refactor is scoped to adding an alerts
banner + expanding 5-day → 7-day; every existing field access on the
web + mobile widgets keeps working verbatim.

Contract:
    * ``get_current(lat, lon)``  → current conditions envelope.
    * ``get_daily(lat, lon, days=7)`` → 7-day forecast envelope (NWS
      returns 12 half-day periods; we fold them into daily rows).
    * ``get_hourly(lat, lon, hours=24)`` → next-N-hours envelope.
    * ``get_alerts(lat, lon)`` → active alerts, normalized to a
      compact shape ``{event, severity, headline, expires_at, url}``.

Every helper returns ``{ok: True, ...}`` on success or
``{ok: False, reason: "..."}`` on any failure. Reason codes:
    * ``no_coords``     — caller passed missing/None lat or lon.
    * ``out_of_us``     — NWS 404 on the /points lookup.
    * ``upstream_error`` — transport error / 5xx / non-4xx-404 4xx.
    * ``bad_response``  — 200 but JSON parse failed / shape unexpected.

The router layer never converts these into HTTP 4xx/5xx: the widget
must self-hide on ``ok:false`` (established fail-safe pattern in the
codebase; see the WeatherAPI-era comment block in ``weather_v2.py``).
"""
from __future__ import annotations

from typing import Any, Optional

import httpx

from config import logger

# ─────────────────────────────────────────────────────────────────────
# Constants — the single source of truth for the NWS identifier.
# ─────────────────────────────────────────────────────────────────────
NWS_USER_AGENT = "PoolLandscapeCRM (app.plofv.com contact@plofv.com)"
NWS_ACCEPT = "application/geo+json"
NWS_BASE = "https://api.weather.gov"
_TIMEOUT_S = 15.0


def _headers() -> dict[str, str]:
    """NWS mandates a real User-Agent; requests without one get 403."""
    return {"User-Agent": NWS_USER_AGENT, "Accept": NWS_ACCEPT}


# ─────────────────────────────────────────────────────────────────────
# Unit conversion — NWS observations come as SI by default; forecast +
# hourly endpoints accept ``?units=us`` to return Fahrenheit / mph, so
# only observations need explicit conversion here.
# ─────────────────────────────────────────────────────────────────────
def _c_to_f(c: Optional[float]) -> Optional[float]:
    if c is None:
        return None
    try:
        return round(float(c) * 9.0 / 5.0 + 32.0, 1)
    except (TypeError, ValueError):
        return None


def _kmh_to_mph(kmh: Optional[float]) -> Optional[float]:
    if kmh is None:
        return None
    try:
        return round(float(kmh) * 0.6213711922, 1)
    except (TypeError, ValueError):
        return None


def _mm_to_in(mm: Optional[float]) -> Optional[float]:
    if mm is None:
        return None
    try:
        return round(float(mm) / 25.4, 3)
    except (TypeError, ValueError):
        return None


def _prop_value(obj: Any, key: str) -> Optional[float]:
    """Read ``obj[key]["value"]`` defensively. NWS observation
    properties are wrapped in ``{value, unitCode, qualityControl}``."""
    if not isinstance(obj, dict):
        return None
    node = obj.get(key)
    if not isinstance(node, dict):
        return None
    v = node.get("value")
    return v


# ─────────────────────────────────────────────────────────────────────
# Transport — a single async httpx call site so the UA header + timeout
# + failure envelope can't drift between helpers.
# ─────────────────────────────────────────────────────────────────────
async def _nws_get(url: str, *,
                    client: Optional[httpx.AsyncClient] = None) -> dict:
    """Return ``{ok, data|reason, status}``. Never raises."""
    async def _do(c: httpx.AsyncClient) -> dict:
        try:
            r = await c.get(url, headers=_headers(), timeout=_TIMEOUT_S)
        except httpx.HTTPError as e:
            logger.warning(f"[p39a] nws transport error {url}: {e}")
            return {"ok": False, "reason": "upstream_error", "status": 0}
        if r.status_code == 404:
            return {"ok": False, "reason": "out_of_us", "status": 404}
        if r.status_code >= 500:
            return {"ok": False, "reason": "upstream_error",
                      "status": r.status_code}
        if r.status_code >= 400:
            return {"ok": False, "reason": "upstream_error",
                      "status": r.status_code}
        try:
            return {"ok": True, "data": r.json(), "status": r.status_code}
        except Exception:
            return {"ok": False, "reason": "bad_response",
                      "status": r.status_code}

    if client is not None:
        return await _do(client)
    async with httpx.AsyncClient() as c:
        return await _do(c)


def _no_coords(lat: Any, lon: Any) -> bool:
    return lat is None or lon is None


# ─────────────────────────────────────────────────────────────────────
# /points — bootstrap for every other call. Cached at the router layer
# under endpoint ``"nws_points"`` with a 24h TTL because points-metadata
# rarely changes and skipping this hop saves ~200ms on downstream calls.
# ─────────────────────────────────────────────────────────────────────
async def get_points(lat: float, lon: float, *,
                       client: Optional[httpx.AsyncClient] = None) -> dict:
    if _no_coords(lat, lon):
        return {"ok": False, "reason": "no_coords"}
    url = f"{NWS_BASE}/points/{lat},{lon}"
    resp = await _nws_get(url, client=client)
    if not resp["ok"]:
        return {"ok": False, "reason": resp["reason"]}
    props = ((resp.get("data") or {}).get("properties") or {})
    return {
        "ok": True,
        "forecast_url": props.get("forecast"),
        "forecast_hourly_url": props.get("forecastHourly"),
        "observation_stations_url": props.get("observationStations"),
        "radar_station": props.get("radarStation"),
        "cwa": props.get("cwa"),
        "time_zone": props.get("timeZone"),
        "grid_id": props.get("gridId"),
        "grid_x": props.get("gridX"),
        "grid_y": props.get("gridY"),
    }


# ─────────────────────────────────────────────────────────────────────
# /stations/{id}/observations/latest — current conditions. Two-hop:
#   1. /points → observation_stations_url
#   2. GET stations list → first station id
#   3. GET latest observation
# ─────────────────────────────────────────────────────────────────────
async def get_current(lat: float, lon: float, *,
                        client: Optional[httpx.AsyncClient] = None) -> dict:
    if _no_coords(lat, lon):
        return {"ok": False, "reason": "no_coords"}
    pts = await get_points(lat, lon, client=client)
    if not pts.get("ok"):
        return {"ok": False, "reason": pts.get("reason", "upstream_error")}
    stations_url = pts.get("observation_stations_url")
    if not stations_url:
        return {"ok": False, "reason": "bad_response"}
    stations_resp = await _nws_get(stations_url, client=client)
    if not stations_resp["ok"]:
        return {"ok": False, "reason": stations_resp["reason"]}
    features = ((stations_resp.get("data") or {}).get("features") or [])
    if not features:
        return {"ok": False, "reason": "bad_response"}
    # Prefer the first station — NWS returns them ordered by proximity
    # to the requested point. Some feature entries carry ``id``
    # (station URL) on the feature root; others put the station id
    # under ``properties.stationIdentifier``.
    first = features[0] if isinstance(features[0], dict) else {}
    station_url = first.get("id") or ""
    station_id = ""
    if isinstance(first.get("properties"), dict):
        station_id = first["properties"].get("stationIdentifier") or ""
    if station_id and not station_url:
        station_url = f"{NWS_BASE}/stations/{station_id}"
    if not station_url:
        return {"ok": False, "reason": "bad_response"}
    obs_url = f"{station_url}/observations/latest"
    obs_resp = await _nws_get(obs_url, client=client)
    if not obs_resp["ok"]:
        return {"ok": False, "reason": obs_resp["reason"]}
    obs_props = ((obs_resp.get("data") or {}).get("properties") or {})

    temp_c = _prop_value(obs_props, "temperature")
    temp_f = _c_to_f(temp_c)
    heat_c = _prop_value(obs_props, "heatIndex")
    chill_c = _prop_value(obs_props, "windChill")
    feels_c = heat_c if heat_c is not None else chill_c
    feels_f = _c_to_f(feels_c) if feels_c is not None else temp_f
    wind_kmh = _prop_value(obs_props, "windSpeed")
    wind_mph = _kmh_to_mph(wind_kmh)
    humidity = _prop_value(obs_props, "relativeHumidity")
    condition_text = obs_props.get("textDescription")
    icon = obs_props.get("icon")

    payload = {
        "ok": True,
        "location": {
            "name": station_id or None,
            "lat": lat, "lon": lon,
            "tz_id": pts.get("time_zone"),
            "localtime": obs_props.get("timestamp"),
        },
        "current": {
            "temp_f": temp_f,
            "temp_c": round(float(temp_c), 1) if temp_c is not None else None,
            "feelslike_f": feels_f,
            "feelslike_c": (round(float(feels_c), 1)
                                if feels_c is not None else None),
            "humidity": (round(float(humidity))
                            if humidity is not None else None),
            "wind_mph": wind_mph,
            "wind_dir": None,  # NWS returns windDirection as degrees;
                                  # kept null to preserve the widget's
                                  # WeatherAPI-era string-based renderer.
            "uv": None,  # NWS does not publish UV; frontend renders "—".
            "is_day": None,
            "condition_text": condition_text,
            "condition_icon": icon,
            "last_updated": obs_props.get("timestamp"),
        },
    }
    return payload


# ─────────────────────────────────────────────────────────────────────
# 7-day forecast — NWS returns 12 half-day periods. Fold isDaytime=True
# → ``high``; isDaytime=False → ``low``. Rows keyed by date.
# ─────────────────────────────────────────────────────────────────────
async def get_daily(lat: float, lon: float, days: int = 7, *,
                      client: Optional[httpx.AsyncClient] = None) -> dict:
    if _no_coords(lat, lon):
        return {"ok": False, "reason": "no_coords"}
    pts = await get_points(lat, lon, client=client)
    if not pts.get("ok"):
        return {"ok": False, "reason": pts.get("reason", "upstream_error")}
    forecast_url = pts.get("forecast_url")
    if not forecast_url:
        return {"ok": False, "reason": "bad_response"}
    # NWS defaults to SI; ?units=us returns °F + mph.
    sep = "&" if "?" in forecast_url else "?"
    url = f"{forecast_url}{sep}units=us"
    resp = await _nws_get(url, client=client)
    if not resp["ok"]:
        return {"ok": False, "reason": resp["reason"]}
    periods = (((resp.get("data") or {}).get("properties") or {})
                 .get("periods") or [])
    # Fold periods → per-date rows.
    rows: dict[str, dict] = {}
    order: list[str] = []
    for p in periods:
        if not isinstance(p, dict):
            continue
        start = str(p.get("startTime") or "")
        date = start[:10] if len(start) >= 10 else ""
        if not date:
            continue
        row = rows.setdefault(date, {
            "date": date,
            "high": None, "low": None,
            "chance_of_rain": None,
            "condition_text": None,
            "condition_icon": None,
        })
        if date not in order:
            order.append(date)
        temp = p.get("temperature")
        if p.get("isDaytime"):
            row["high"] = temp
            # Daytime period drives the day's headline text + icon.
            row["condition_text"] = p.get("shortForecast")
            row["condition_icon"] = p.get("icon")
        else:
            row["low"] = temp
        pop = ((p.get("probabilityOfPrecipitation") or {}).get("value"))
        if pop is not None:
            cur = row["chance_of_rain"]
            row["chance_of_rain"] = pop if cur is None else max(cur, pop)
    daily_rows = [rows[d] for d in order][:days]
    return {
        "ok": True,
        "location": {"lat": lat, "lon": lon,
                       "tz_id": pts.get("time_zone")},
        "days_requested": days,
        "days_returned": len(daily_rows),
        "daily": daily_rows,
    }


# ─────────────────────────────────────────────────────────────────────
# Hourly forecast.
# ─────────────────────────────────────────────────────────────────────
async def get_hourly(lat: float, lon: float, hours: int = 24, *,
                       client: Optional[httpx.AsyncClient] = None) -> dict:
    if _no_coords(lat, lon):
        return {"ok": False, "reason": "no_coords"}
    pts = await get_points(lat, lon, client=client)
    if not pts.get("ok"):
        return {"ok": False, "reason": pts.get("reason", "upstream_error")}
    hourly_url = pts.get("forecast_hourly_url")
    if not hourly_url:
        return {"ok": False, "reason": "bad_response"}
    sep = "&" if "?" in hourly_url else "?"
    url = f"{hourly_url}{sep}units=us"
    resp = await _nws_get(url, client=client)
    if not resp["ok"]:
        return {"ok": False, "reason": resp["reason"]}
    periods = (((resp.get("data") or {}).get("properties") or {})
                 .get("periods") or [])
    rows: list[dict] = []
    for p in periods[:hours]:
        if not isinstance(p, dict):
            continue
        pop = ((p.get("probabilityOfPrecipitation") or {}).get("value"))
        rows.append({
            "time": p.get("startTime"),
            "temp_f": p.get("temperature"),
            "temp_c": None,
            "chance_of_rain": pop,
            "precip_mm": None,
            "wind_mph": None,
            "condition_text": p.get("shortForecast"),
            "condition_icon": p.get("icon"),
            "will_it_rain": 1 if (isinstance(pop, (int, float))
                                       and pop >= 50) else 0,
        })
    return {
        "ok": True,
        "location": {"lat": lat, "lon": lon,
                       "tz_id": pts.get("time_zone")},
        "hours_requested": hours,
        "hours_returned": len(rows),
        "hourly": rows,
    }


# ─────────────────────────────────────────────────────────────────────
# Active alerts — normalized to the compact shape the widget renders.
# ─────────────────────────────────────────────────────────────────────
async def get_alerts(lat: float, lon: float, *,
                       client: Optional[httpx.AsyncClient] = None) -> dict:
    if _no_coords(lat, lon):
        return {"ok": False, "reason": "no_coords"}
    url = f"{NWS_BASE}/alerts/active?point={lat},{lon}"
    resp = await _nws_get(url, client=client)
    if not resp["ok"]:
        return {"ok": False, "reason": resp["reason"]}
    features = ((resp.get("data") or {}).get("features") or [])
    out: list[dict] = []
    for f in features:
        if not isinstance(f, dict):
            continue
        props = f.get("properties") or {}
        out.append({
            "event": props.get("event"),
            "severity": props.get("severity") or "Unknown",
            "headline": props.get("headline"),
            "expires_at": props.get("expires"),
            "url": props.get("id") or props.get("@id"),
        })
    return {
        "ok": True,
        "location": {"lat": lat, "lon": lon},
        "alerts": out,
    }
