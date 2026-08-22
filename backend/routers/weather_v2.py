"""Weather widget backend — Feb-2026 · P39a.

Migrated from WeatherAPI.com → NWS (api.weather.gov). The heavy
lifting lives in ``services.weather.nws``; this router is a thin
cache + auth layer. Envelope shapes are preserved verbatim so the
P39b widget refactor is scoped to adding an alerts banner + bumping
5-day → 7-day; every field access on the web + mobile widgets keeps
working.

Endpoints:
    * ``GET /api/weather/current?lat=&lon=``  — current conditions.
    * ``GET /api/weather/hourly?lat=&lon=&hours=24`` — next N hours.
    * ``GET /api/weather/daily?lat=&lon=&days=7`` — 7-day forecast.
    * ``GET /api/weather/radar?lat=&lon=`` — Windy embed URL (unchanged
      in P39a; P39c swaps to NWS ridge/standard GIF).
    * ``GET /api/weather/alerts?lat=&lon=`` — active NWS alerts,
      normalized to a compact shape.

Cache: MongoDB collection ``weather_cache`` with TTL indexes.
Per-endpoint TTL dict per P39a spec:
    * ``nws_current``  → 600s  (10 min)
    * ``nws_daily``    → 3600s (1 hour)
    * ``nws_hourly``   → 900s  (15 min)
    * ``nws_alerts``   → 300s  (5 min)
    * ``nws_points``   → 86400s (24 hours — points-metadata rarely
                                  changes; caching saves the /points
                                  round-trip on every downstream call)
    * ``radar``        → 300s  (5 min — kept from pre-P39a behavior)

Failure semantics: every helper never raises; on any upstream / no-
coords / out-of-US / malformed-JSON case the response is 200 with
``{ok: False, reason: "..."}`` so the widget hides gracefully.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query

from config import db, logger
from services.weather import nws
from utils import require_tech_or_admin

router = APIRouter()


# ─────────────────────────────────────────────────────────────────────
# Cache — per-endpoint TTL dict.
# ─────────────────────────────────────────────────────────────────────
CACHE_COLLECTION = "weather_cache"
CACHE_TTL_S: dict[str, int] = {
    "nws_current": 600,
    "nws_daily": 3600,
    "nws_hourly": 900,
    "nws_alerts": 300,
    "nws_points": 86400,
    # Feb-2026 · P39c — radar deliberately absent from this dict.
    # The NWS ridge/standard GIF is refreshed server-side ~every
    # 10 min; browser cache on the <img src> handles freshness.
}
_DEFAULT_TTL_S = 300
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


async def _cache_put(endpoint: str, lat: float, lon: float,
                       payload: dict) -> None:
    now = datetime.now(timezone.utc)
    ttl = CACHE_TTL_S.get(endpoint, _DEFAULT_TTL_S)
    await db[CACHE_COLLECTION].update_one(
        {"endpoint": endpoint, "lat_r": _round(lat), "lon_r": _round(lon)},
        {"$set": {
            "endpoint": endpoint,
            "lat_r": _round(lat),
            "lon_r": _round(lon),
            "payload": payload,
            "cached_at": now,
            "expires_at": now + timedelta(seconds=ttl),
        }},
        upsert=True,
    )


# ─────────────────────────────────────────────────────────────────────
# /weather/current
# ─────────────────────────────────────────────────────────────────────
@router.get("/weather/current")
async def weather_current(
    lat: float = Query(...),
    lon: float = Query(...),
    _user: dict = Depends(require_tech_or_admin),
):
    await _ensure_index()
    cached = await _cache_get("nws_current", lat, lon)
    if cached is not None:
        return {**cached, "cache": "hit"}
    payload = await nws.get_current(lat, lon)
    if not payload.get("ok"):
        # NEVER cache failures — a transient upstream miss shouldn't
        # freeze the widget for 10 minutes.
        return {**payload, "cache": "miss"}
    await _cache_put("nws_current", lat, lon, payload)
    return {**payload, "cache": "miss"}


# ─────────────────────────────────────────────────────────────────────
# /weather/hourly
# ─────────────────────────────────────────────────────────────────────
@router.get("/weather/hourly")
async def weather_hourly(
    lat: float = Query(...),
    lon: float = Query(...),
    hours: int = Query(24, ge=1, le=48),
    _user: dict = Depends(require_tech_or_admin),
):
    await _ensure_index()
    cache_key = f"nws_hourly_{hours}"
    cached = await _cache_get(cache_key, lat, lon)
    if cached is not None:
        return {**cached, "cache": "hit"}
    payload = await nws.get_hourly(lat, lon, hours=hours)
    if not payload.get("ok"):
        return {**payload, "cache": "miss"}
    # Alias the per-hours cache key onto the shared TTL bucket.
    CACHE_TTL_S.setdefault(cache_key, CACHE_TTL_S["nws_hourly"])
    await _cache_put(cache_key, lat, lon, payload)
    return {**payload, "cache": "miss"}


# ─────────────────────────────────────────────────────────────────────
# /weather/daily
# ─────────────────────────────────────────────────────────────────────
@router.get("/weather/daily")
async def weather_daily(
    lat: float = Query(...),
    lon: float = Query(...),
    days: int = Query(7, ge=1, le=10),
    _user: dict = Depends(require_tech_or_admin),
):
    await _ensure_index()
    cache_key = f"nws_daily_{days}"
    cached = await _cache_get(cache_key, lat, lon)
    if cached is not None:
        return {**cached, "cache": "hit"}
    payload = await nws.get_daily(lat, lon, days=days)
    if not payload.get("ok"):
        return {**payload, "cache": "miss"}
    CACHE_TTL_S.setdefault(cache_key, CACHE_TTL_S["nws_daily"])
    await _cache_put(cache_key, lat, lon, payload)
    return {**payload, "cache": "miss"}


# ─────────────────────────────────────────────────────────────────────
# /weather/alerts — new in P39a.
# ─────────────────────────────────────────────────────────────────────
@router.get("/weather/alerts")
async def weather_alerts(
    lat: float = Query(...),
    lon: float = Query(...),
    _user: dict = Depends(require_tech_or_admin),
):
    await _ensure_index()
    cached = await _cache_get("nws_alerts", lat, lon)
    if cached is not None:
        return {**cached, "cache": "hit"}
    payload = await nws.get_alerts(lat, lon)
    if not payload.get("ok"):
        return {**payload, "cache": "miss"}
    await _cache_put("nws_alerts", lat, lon, payload)
    return {**payload, "cache": "miss"}


# ─────────────────────────────────────────────────────────────────────
# /weather/radar — Feb-2026 · P39c: swap from Windy iframe to NWS
# ridge/standard animated GIF. NWS refreshes the loop GIF server-side
# every ~10 min so we skip our own cache entirely — browser cache on
# the ``<img src>`` handles freshness cheaply. When the /points lookup
# doesn't yield a ``radarStation`` (out-of-US or metadata gap) we
# return the graceful failure envelope so the widget hides the
# radar section without a broken image.
# ─────────────────────────────────────────────────────────────────────
_NWS_RIDGE_STANDARD = "https://radar.weather.gov/ridge/standard"


@router.get("/weather/radar")
async def weather_radar(
    lat: float = Query(...),
    lon: float = Query(...),
    _user: dict = Depends(require_tech_or_admin),
):
    """Return an NWS ridge/standard radar-loop URL anchored on the
    NEXRAD site closest to ``(lat, lon)``.

    Response shape (P39c):
        {
          "ok": true,
          "provider": "nws",
          "radar_station": "KIWA",
          "loop_url":  "https://radar.weather.gov/ridge/standard/KIWA_loop.gif",
          "still_url": "https://radar.weather.gov/ridge/standard/KIWA_0.gif",
          "refreshed_at": "2026-06-01T15:00:00+00:00",
          "lat": ..., "lon": ...
        }

    Failure envelope:
        {"ok": false, "reason": "out_of_us" | "no_radar_station" | ...}
    """
    await _ensure_index()
    pts = await nws.get_points(lat, lon)
    if not pts.get("ok"):
        # Propagate the exact upstream reason (out_of_us / upstream_error
        # / no_coords) so the frontend can render a matching helper
        # message instead of a broken <img>.
        return {"ok": False, "reason": pts.get("reason", "upstream_error"),
                  "lat": lat, "lon": lon}
    station = pts.get("radar_station")
    if not station:
        return {"ok": False, "reason": "no_radar_station",
                  "lat": lat, "lon": lon}
    return {
        "ok": True,
        "provider": "nws",
        "radar_station": station,
        "loop_url": f"{_NWS_RIDGE_STANDARD}/{station}_loop.gif",
        "still_url": f"{_NWS_RIDGE_STANDARD}/{station}_0.gif",
        "refreshed_at": datetime.now(timezone.utc).isoformat(),
        "lat": lat, "lon": lon,
    }
