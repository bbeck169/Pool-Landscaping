"""Phase G3 · Feb-2026 — Server-side reverse geocoding via Mapbox.

Design goals:
* Free-tier friendly: 600 calls/min hard-cap from Mapbox; we cap
  ourselves at 30 calls/second and lean heavily on cache-first.
* Graceful degradation: when ``MAPBOX_ACCESS_TOKEN`` is empty or unset
  every function returns ``{status: "no_token", address: None}`` and
  performs NO network calls. Nothing crashes.
* Tenant-scoped cache: ``db.reverse_geocode_cache`` deduped on
  ``(tenant_id, lat_rounded, lon_rounded)`` where lat/lon are rounded
  to 5 decimals (~1m).
* TTL: 90 days matching ping retention. Negative results cached 1h.
"""
from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import httpx

from config import db, logger
from utils import new_id, now_iso

_TIMEOUT = 10.0
_MAPBOX_URL = "https://api.mapbox.com/geocoding/v5/mapbox.places"
_CACHE_TTL_DAYS = 90
_NEG_CACHE_TTL_SECONDS = 3600  # 1h
_ROUND_DIGITS = 5
_CONCURRENCY = 30

_sem = asyncio.Semaphore(_CONCURRENCY)


def _make_client() -> httpx.AsyncClient:
    """Factory hook — tests override this to inject a MockTransport."""
    return httpx.AsyncClient()


def mapbox_token_configured() -> bool:
    """True iff ``MAPBOX_ACCESS_TOKEN`` is set to a non-empty value."""
    return bool((os.environ.get("MAPBOX_ACCESS_TOKEN") or "").strip())


def _round(lat: float, lon: float) -> tuple[float, float]:
    return round(float(lat), _ROUND_DIGITS), round(float(lon), _ROUND_DIGITS)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(v: Any) -> Optional[datetime]:
    if not v:
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    try:
        dt = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _parse_mapbox(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Extract our normalized address shape from a Mapbox v5 response."""
    features = payload.get("features") or []
    if not features:
        return {"formatted": None}
    f = features[0] if isinstance(features[0], dict) else {}
    formatted = f.get("place_name") or None
    parts: Dict[str, Any] = {"formatted": formatted}
    # Street: place_type=address has address (number) + text (street name).
    place_types = f.get("place_type") or []
    if isinstance(place_types, list) and "address" in place_types:
        number = f.get("address")
        street = f.get("text")
        if number and street:
            parts["street"] = f"{number} {street}"
        elif street:
            parts["street"] = street
    for ctx in (f.get("context") or []):
        cid = ctx.get("id") or ""
        text = ctx.get("text")
        short = ctx.get("short_code") or ""
        if cid.startswith("place"):
            parts["city"] = text
        elif cid.startswith("region"):
            # short_code looks like "US-AZ" — keep just AZ if present.
            code = short.split("-")[-1] if short else None
            parts["state"] = code or text
        elif cid.startswith("postcode"):
            parts["postcode"] = text
        elif cid.startswith("country"):
            parts["country"] = short.upper() if short else text
    return parts


async def _cache_lookup(tenant_id: str,
                            lat_r: float, lon_r: float) -> Optional[Dict[str, Any]]:
    row = await db.reverse_geocode_cache.find_one(
        {"tenant_id": tenant_id,
         "lat_rounded": lat_r, "lon_rounded": lon_r},
        {"_id": 0})
    if not row:
        return None
    expires = _parse_iso(row.get("expires_at"))
    if expires and expires < _now():
        return None
    return row


async def _cache_write(tenant_id: str, lat_r: float, lon_r: float,
                          *, address: Optional[Dict[str, Any]],
                          status: str,
                          ttl_seconds: int) -> None:
    now = _now()
    expires = (now + timedelta(seconds=ttl_seconds)).isoformat()
    await db.reverse_geocode_cache.update_one(
        {"tenant_id": tenant_id,
          "lat_rounded": lat_r, "lon_rounded": lon_r},
        {"$set": {
            "tenant_id": tenant_id,
            "lat_rounded": lat_r, "lon_rounded": lon_r,
            "address": address,
            "status": status,
            "source": "mapbox",
            "fetched_at": now.isoformat(),
            "expires_at": expires,
        }},
        upsert=True,
    )


async def reverse_geocode(lat: float, lon: float,
                              tenant_id: str) -> Dict[str, Any]:
    """Return ``{status, address}``. Never raises.

    * ``status="no_token"`` — env var absent, no network call.
    * ``status="resolved"`` — cache hit or fresh Mapbox result.
    * ``status="error"``   — Mapbox non-2xx or transport failure.
    """
    if lat is None or lon is None:
        return {"status": "error", "address": None,
                "error": "missing_coords"}
    lat_r, lon_r = _round(lat, lon)

    cached = await _cache_lookup(tenant_id, lat_r, lon_r)
    if cached:
        # Never re-hit the network for a live cache entry, even for
        # cached errors within their negative-TTL window.
        return {"status": cached.get("status") or "resolved",
                "address": cached.get("address"),
                "cached": True}

    if not mapbox_token_configured():
        return {"status": "no_token", "address": None}

    token = os.environ["MAPBOX_ACCESS_TOKEN"].strip()
    url = f"{_MAPBOX_URL}/{lon_r},{lat_r}.json"
    params = {"access_token": token,
              "types": "address,neighborhood,locality",
              "limit": 1}
    try:
        async with _sem:
            async with _make_client() as client:
                r = await client.get(url, params=params, timeout=_TIMEOUT)
    except Exception as e:                                              # noqa: BLE001
        logger.info("[reverse_geocoder] transport error: %s", e)
        await _cache_write(tenant_id, lat_r, lon_r,
                              address=None, status="error",
                              ttl_seconds=_NEG_CACHE_TTL_SECONDS)
        return {"status": "error", "address": None,
                "error": f"transport:{e}"}

    if r.status_code != 200:
        await _cache_write(tenant_id, lat_r, lon_r,
                              address=None, status="error",
                              ttl_seconds=_NEG_CACHE_TTL_SECONDS)
        return {"status": "error", "address": None,
                "error": f"http_{r.status_code}"}

    try:
        payload = r.json()
    except Exception:                                                    # noqa: BLE001
        await _cache_write(tenant_id, lat_r, lon_r,
                              address=None, status="error",
                              ttl_seconds=_NEG_CACHE_TTL_SECONDS)
        return {"status": "error", "address": None,
                "error": "invalid_json"}

    parsed = _parse_mapbox(payload)
    if not parsed.get("formatted"):
        # Mapbox returned zero features — treat as negative cache.
        await _cache_write(tenant_id, lat_r, lon_r,
                              address=None, status="error",
                              ttl_seconds=_NEG_CACHE_TTL_SECONDS)
        return {"status": "error", "address": None,
                "error": "no_features"}

    await _cache_write(tenant_id, lat_r, lon_r,
                          address=parsed, status="resolved",
                          ttl_seconds=_CACHE_TTL_DAYS * 86400)
    return {"status": "resolved", "address": parsed, "cached": False}


async def purge_expired_geocode_cache() -> Dict[str, int]:
    """Drop rows where ``expires_at`` is in the past. Idempotent."""
    now = _now().isoformat()
    try:
        r = await db.reverse_geocode_cache.delete_many(
            {"expires_at": {"$lt": now}})
        purged = int(r.deleted_count or 0)
    except Exception as e:                                              # noqa: BLE001
        logger.warning("[reverse_geocoder] purge error: %s", e)
        purged = 0
    logger.info("[reverse_geocoder] purged=%s expired cache rows",
                purged)
    return {"purged": purged}


async def ensure_indexes() -> None:
    try:
        await db.reverse_geocode_cache.create_index(
            [("tenant_id", 1), ("lat_rounded", 1), ("lon_rounded", 1)],
            unique=True)
        await db.reverse_geocode_cache.create_index("expires_at")
    except Exception as e:                                              # noqa: BLE001
        logger.debug("[reverse_geocoder] index setup skipped: %s", e)
