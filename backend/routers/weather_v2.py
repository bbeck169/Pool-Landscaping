"""Weather widget backend — Feb-2026.

Proxies WeatherAPI.com (paid tier) through FastAPI so the API key
never leaves the server. Three endpoints:

* ``GET /api/weather/current?lat=&lon=`` — current conditions.
* ``GET /api/weather/hourly?lat=&lon=&hours=24`` — next N hours.
  Uses ``/hourly`` (not ``/forecast``) to avoid colliding with the
  pre-existing keyless Open-Meteo daily-forecast endpoint on
  ``routers/weather.py``.
* ``GET /api/weather/radar?lat=&lon=`` — returns a Windy embed URL
  for the animated radar overlay (WeatherAPI itself does not ship
  radar tiles, so we fall back to the free Windy embed anchored on
  the same lat/lon; the tech-facing widget doesn't need auth for
  the iframe).

All three cache per ``(endpoint, lat_rounded, lon_rounded)`` in the
``weather_cache`` Mongo collection for 5 minutes via a TTL index on
``expires_at``. Cache hit/miss is exposed in the response body so
the front-end and tests can observe it.

Upstream failure returns ``{"ok": False, "reason": "..."}`` with
HTTP 200 so the widget hides gracefully without dumping a red
banner onto the tech dashboard.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, Query

from config import db, logger
from utils import require_tech_or_admin

router = APIRouter()

WEATHERAPI_BASE = "https://api.weatherapi.com/v1"
CACHE_TTL_SECONDS = 300  # 5 minutes
CACHE_COLLECTION = "weather_cache"
_INDEX_ENSURED = False


async def _ensure_index() -> None:
    """Create the TTL index on ``expires_at`` once per process."""
    global _INDEX_ENSURED
    if _INDEX_ENSURED:
        return
    try:
        await db[CACHE_COLLECTION].create_index(
            "expires_at", expireAfterSeconds=0,
        )
        await db[CACHE_COLLECTION].create_index(
            [("endpoint", 1), ("lat_r", 1), ("lon_r", 1)],
        )
    except Exception as e:
        logger.warning(f"weather_cache index setup failed: {e}")
    _INDEX_ENSURED = True


def _round(v: float) -> float:
    return round(float(v), 3)


async def _cache_get(endpoint: str, lat: float, lon: float) -> Optional[dict]:
    row = await db[CACHE_COLLECTION].find_one(
        {"endpoint": endpoint, "lat_r": _round(lat), "lon_r": _round(lon)},
        {"_id": 0},
    )
    if not row:
        return None
    exp = row.get("expires_at")
    if isinstance(exp, datetime):
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if exp <= datetime.now(timezone.utc):
            return None
    return row.get("payload")


async def _cache_put(endpoint: str, lat: float, lon: float, payload: dict) -> None:
    now = datetime.now(timezone.utc)
    await db[CACHE_COLLECTION].update_one(
        {"endpoint": endpoint, "lat_r": _round(lat), "lon_r": _round(lon)},
        {"$set": {
            "endpoint": endpoint,
            "lat_r": _round(lat),
            "lon_r": _round(lon),
            "payload": payload,
            "cached_at": now,
            "expires_at": now + timedelta(seconds=CACHE_TTL_SECONDS),
        }},
        upsert=True,
    )


async def _weatherapi_get(path: str, params: dict) -> dict:
    key = os.environ.get("WEATHERAPI_KEY")
    if not key:
        return {"ok": False, "reason": "provider_key_missing"}
    q = dict(params)
    q["key"] = key
    url = f"{WEATHERAPI_BASE}{path}"
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(url, params=q)
    except httpx.HTTPError as e:
        logger.warning(f"weatherapi transport error {path}: {e}")
        return {"ok": False, "reason": "provider_unavailable"}
    if r.status_code >= 500:
        return {"ok": False, "reason": "provider_unavailable"}
    if r.status_code >= 400:
        return {"ok": False, "reason": f"provider_error_{r.status_code}"}
    try:
        return {"ok": True, "data": r.json()}
    except Exception:
        return {"ok": False, "reason": "provider_bad_json"}


# ─── /weather/current ─────────────────────────────────────────────────

@router.get("/weather/current")
async def weather_current(
    lat: float = Query(...),
    lon: float = Query(...),
    _user: dict = Depends(require_tech_or_admin),
):
    await _ensure_index()
    cached = await _cache_get("current", lat, lon)
    if cached is not None:
        return {**cached, "cache": "hit"}

    resp = await _weatherapi_get("/current.json", {"q": f"{lat},{lon}"})
    if not resp.get("ok"):
        return {"ok": False, "reason": resp.get("reason"), "cache": "miss"}
    j = resp["data"]
    cur = j.get("current") or {}
    loc = j.get("location") or {}
    cond = cur.get("condition") or {}
    payload = {
        "ok": True,
        "location": {
            "name": loc.get("name"),
            "region": loc.get("region"),
            "country": loc.get("country"),
            "lat": loc.get("lat"),
            "lon": loc.get("lon"),
            "tz_id": loc.get("tz_id"),
            "localtime": loc.get("localtime"),
        },
        "current": {
            "temp_f": cur.get("temp_f"),
            "temp_c": cur.get("temp_c"),
            "feelslike_f": cur.get("feelslike_f"),
            "feelslike_c": cur.get("feelslike_c"),
            "humidity": cur.get("humidity"),
            "wind_mph": cur.get("wind_mph"),
            "wind_dir": cur.get("wind_dir"),
            "uv": cur.get("uv"),
            "is_day": cur.get("is_day"),
            "condition_text": cond.get("text"),
            "condition_icon": (
                f"https:{cond.get('icon')}"
                if cond.get("icon", "").startswith("//")
                else cond.get("icon")
            ),
            "last_updated": cur.get("last_updated"),
        },
    }
    await _cache_put("current", lat, lon, payload)
    return {**payload, "cache": "miss"}


# ─── /weather/hourly ──────────────────────────────────────────────────

@router.get("/weather/hourly")
async def weather_hourly(
    lat: float = Query(...),
    lon: float = Query(...),
    hours: int = Query(24, ge=1, le=48),
    _user: dict = Depends(require_tech_or_admin),
):
    await _ensure_index()
    cache_key = f"hourly_{hours}"
    cached = await _cache_get(cache_key, lat, lon)
    if cached is not None:
        return {**cached, "cache": "hit"}

    # WeatherAPI's ``forecast.json`` returns per-day objects with
    # ``hour`` arrays. We need enough days to cover ``hours`` from
    # the CURRENT local hour — always pull 2 days so a late-in-day
    # call still returns a full 24-hour horizon.
    days_needed = 3 if hours > 24 else 2
    resp = await _weatherapi_get(
        "/forecast.json",
        {"q": f"{lat},{lon}", "days": days_needed, "aqi": "no", "alerts": "no"},
    )
    if not resp.get("ok"):
        return {"ok": False, "reason": resp.get("reason"), "cache": "miss"}
    j = resp["data"]
    loc = j.get("location") or {}
    forecast_days = ((j.get("forecast") or {}).get("forecastday") or [])
    all_hours = []
    for day in forecast_days:
        for h in (day.get("hour") or []):
            all_hours.append(h)

    # Slice from the current local hour forward.
    localtime = (loc.get("localtime") or "").split(" ")
    now_iso_prefix = localtime[0] + " " + (localtime[1] or "00:00")[:3] \
        if len(localtime) == 2 else None
    start_idx = 0
    if now_iso_prefix:
        for i, h in enumerate(all_hours):
            if (h.get("time") or "") >= now_iso_prefix:
                start_idx = i
                break

    sliced = all_hours[start_idx:start_idx + hours]

    def _row(h: dict) -> dict:
        cond = h.get("condition") or {}
        icon = cond.get("icon") or ""
        return {
            "time": h.get("time"),
            "temp_f": h.get("temp_f"),
            "temp_c": h.get("temp_c"),
            "chance_of_rain": h.get("chance_of_rain"),
            "precip_mm": h.get("precip_mm"),
            "wind_mph": h.get("wind_mph"),
            "condition_text": cond.get("text"),
            "condition_icon": (
                f"https:{icon}" if icon.startswith("//") else icon
            ),
            "will_it_rain": h.get("will_it_rain"),
        }

    payload = {
        "ok": True,
        "location": {
            "name": loc.get("name"),
            "lat": loc.get("lat"),
            "lon": loc.get("lon"),
            "tz_id": loc.get("tz_id"),
            "localtime": loc.get("localtime"),
        },
        "hours_requested": hours,
        "hours_returned": len(sliced),
        "hourly": [_row(h) for h in sliced],
    }
    await _cache_put(cache_key, lat, lon, payload)
    return {**payload, "cache": "miss"}


# ─── /weather/daily ───────────────────────────────────────────────────

@router.get("/weather/daily")
async def weather_daily(
    lat: float = Query(...),
    lon: float = Query(...),
    days: int = Query(5, ge=1, le=10),
    _user: dict = Depends(require_tech_or_admin),
):
    """Multi-day daily forecast strip (5 days default).

    WeatherAPI's free tier caps forecast horizon at ~3 days — we
    ask for what the caller wants and pass through whatever the
    upstream returns via ``days_returned``. The frontend renders
    only the delivered cells, no fake data.
    """
    await _ensure_index()
    cache_key = f"daily_{days}"
    cached = await _cache_get(cache_key, lat, lon)
    if cached is not None:
        return {**cached, "cache": "hit"}

    resp = await _weatherapi_get(
        "/forecast.json",
        {"q": f"{lat},{lon}", "days": days, "aqi": "no", "alerts": "no"},
    )
    if not resp.get("ok"):
        return {"ok": False, "reason": resp.get("reason"), "cache": "miss"}
    j = resp["data"]
    loc = j.get("location") or {}
    forecast_days = ((j.get("forecast") or {}).get("forecastday") or [])

    def _day(d: dict) -> dict:
        day = d.get("day") or {}
        cond = day.get("condition") or {}
        icon = cond.get("icon") or ""
        return {
            "date": d.get("date"),
            "high": day.get("maxtemp_f"),
            "low": day.get("mintemp_f"),
            "high_c": day.get("maxtemp_c"),
            "low_c": day.get("mintemp_c"),
            "chance_of_rain": day.get("daily_chance_of_rain"),
            "precip_mm": day.get("totalprecip_mm"),
            "condition_text": cond.get("text"),
            "condition_icon": (
                f"https:{icon}" if icon.startswith("//") else icon
            ),
        }

    daily_rows = [_day(d) for d in forecast_days[:days]]

    payload = {
        "ok": True,
        "location": {
            "name": loc.get("name"),
            "lat": loc.get("lat"),
            "lon": loc.get("lon"),
            "tz_id": loc.get("tz_id"),
            "localtime": loc.get("localtime"),
        },
        "days_requested": days,
        "days_returned": len(daily_rows),
        "daily": daily_rows,
    }
    await _cache_put(cache_key, lat, lon, payload)
    return {**payload, "cache": "miss"}


# ─── /weather/radar ───────────────────────────────────────────────────

@router.get("/weather/radar")
async def weather_radar(
    lat: float = Query(...),
    lon: float = Query(...),
    _user: dict = Depends(require_tech_or_admin),
):
    """Return a radar embed URL anchored on the tech's location.

    WeatherAPI.com doesn't ship a public radar-tile endpoint on the
    free tier, so the widget falls back to the free Windy embed
    (widely used by field-service apps). The URL is deterministic
    and doesn't leak any secret — but we still gate the endpoint on
    tech/admin because the location itself is per-tenant.
    """
    await _ensure_index()
    cached = await _cache_get("radar", lat, lon)
    if cached is not None:
        return {**cached, "cache": "hit"}

    embed = (
        "https://embed.windy.com/embed2.html"
        f"?lat={lat:.4f}&lon={lon:.4f}&detailLat={lat:.4f}&detailLon={lon:.4f}"
        "&zoom=8&level=surface&overlay=radar&product=radar"
        "&menu=&message=true&marker=&calendar=now&pressure=&type=map"
        "&location=coordinates&detail=&metricWind=mph&metricTemp=%C2%B0F&radarRange=-1"
    )
    payload = {
        "ok": True,
        "provider": "windy",
        "embed_url": embed,
        "lat": lat,
        "lon": lon,
    }
    await _cache_put("radar", lat, lon, payload)
    return {**payload, "cache": "miss"}
