"""Phase 17 · Feb-2026 — Google Geocoding wrapper with 30-day cache.

Google's ToS forbids indefinite address→latlng caching but allows up
to 30 days, which is what we honor. Cache keyed by normalized address
in ``db.geocode_cache`` so every call is idempotent + bounded.
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Optional

import httpx

from config import db, logger

_API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY", "")
_CACHE_TTL_DAYS = 30
_ENDPOINT = "https://maps.googleapis.com/maps/api/geocode/json"


def _normalize(addr: str) -> str:
    return re.sub(r"\s+", " ", (addr or "").strip().lower())


async def geocode_address(address: str) -> Optional[Dict[str, Any]]:
    """Return ``{lat, lng, formatted_address, place_id, precision}`` or
    None on ZERO_RESULTS / error. Never raises."""
    if not address or not _API_KEY:
        return None
    norm = _normalize(address)
    now = datetime.now(timezone.utc)

    cached = await db.geocode_cache.find_one({"key": norm}, {"_id": 0})
    if cached:
        try:
            cached_at = datetime.fromisoformat(
                cached["cached_at"].replace("Z", "+00:00")
            )
            if now - cached_at < timedelta(days=_CACHE_TTL_DAYS):
                return cached.get("result")
        except Exception:
            pass

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(_ENDPOINT, params={
                "address": address, "key": _API_KEY,
            })
            data = r.json()
    except Exception as exc:
        logger.warning("[geocode] http error for %r: %s", address, exc)
        return None
    if data.get("status") == "REQUEST_DENIED":
        logger.error("[geocode] REQUEST_DENIED — check GOOGLE_MAPS_API_KEY + Geocoding API enabled: %s", data.get("error_message"))
        return None
    results = data.get("results") or []
    if not results:
        result = None
    else:
        top = results[0]
        loc = top["geometry"]["location"]
        result = {
            "lat": loc["lat"], "lng": loc["lng"],
            "formatted_address": top.get("formatted_address"),
            "place_id": top.get("place_id"),
            "precision": top["geometry"].get("location_type"),
        }
    await db.geocode_cache.update_one(
        {"key": norm},
        {"$set": {"key": norm, "result": result,
                  "cached_at": now.isoformat()}},
        upsert=True,
    )
    return result


async def geocode_and_persist_customer(customer_id: str, tenant_id: str) -> bool:
    """Compose the customer's canonical address from either
    ``service_address`` (free-form) or the structured street/city/state/
    zip fields, geocode it, and write lat/lng + GeoJSON to the doc.
    Idempotent — skips if ``geocoded_at`` < 30d old."""
    cust = await db.customers.find_one(
        {"id": customer_id, "tenant_id": tenant_id}, {"_id": 0},
    )
    if not cust:
        return False
    if cust.get("geocoded_at"):
        try:
            g = datetime.fromisoformat(cust["geocoded_at"].replace("Z", "+00:00"))
            if datetime.now(timezone.utc) - g < timedelta(days=_CACHE_TTL_DAYS):
                return False
        except Exception:
            pass
    addr = cust.get("service_address") or " ".join(filter(None, [
        cust.get("service_street") or cust.get("street"),
        cust.get("service_city") or cust.get("city"),
        cust.get("service_state") or cust.get("state"),
        cust.get("service_zip") or cust.get("zip"),
    ]))
    if not addr.strip():
        return False
    hit = await geocode_address(addr)
    if not hit:
        return False
    await db.customers.update_one(
        {"id": customer_id, "tenant_id": tenant_id},
        {"$set": {
            "service_lat": hit["lat"], "service_lng": hit["lng"],
            "geocode_precision": hit.get("precision"),
            "geocoded_at": datetime.now(timezone.utc).isoformat(),
            "geocode_source": "google",
            "service_location": {"type": "Point",
                                   "coordinates": [hit["lng"], hit["lat"]]},
        }},
    )
    return True
