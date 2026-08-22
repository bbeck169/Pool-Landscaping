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
    "radar": 300,
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
# /weather/radar — UNCHANGED in P39a. P39c swaps to NWS ridge/standard
# GIF.
# ─────────────────────────────────────────────────────────────────────
@router.get("/weather/radar")
async def weather_radar(
    lat: float = Query(...),
    lon: float = Query(...),
    _user: dict = Depends(require_tech_or_admin),
):
    """Return a radar embed URL anchored on the tech's location.

    Kept on Windy in P39a so the migration lands in a testable
    slice; P39c will swap this to the NWS ridge/standard animated
    GIF anchored on ``radarStation`` from the /points lookup.
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
