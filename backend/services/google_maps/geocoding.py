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
            # Feb-2026 · P37a — canonical lat/lng fields mirrored
            # alongside the legacy ``service_lat/lng`` so every
            # downstream caller can read a single field pair.
            "latitude": hit["lat"], "longitude": hit["lng"],
            "geocode_precision": hit.get("precision"),
            "geocoded_at": datetime.now(timezone.utc).isoformat(),
            "geocode_source": "google",
            "service_location": {"type": "Point",
                                   "coordinates": [hit["lng"], hit["lat"]]},
        }},
    )
    return True


# ═════════════════════════════════════════════════════════════════
# Feb-2026 · P37a — Job + Property geocode helpers.
# Same 30-day cache + on-write persistence pattern as customers.
# Persist to BOTH the legacy field pair (``site_lat/lng`` for jobs;
# properties get canonical ``latitude/longitude``) AND the unified
# ``latitude/longitude`` field pair so downstream callers can pick.
# ═════════════════════════════════════════════════════════════════

async def geocode_and_persist_job(job_id: str, tenant_id: str) -> bool:
    """Compose the job's address from its own ``service_address`` /
    structured fields OR from its linked customer, geocode it, and
    write ``site_lat/lng`` + ``latitude/longitude`` + ``geocoded_at``.
    Idempotent — skips if ``geocoded_at`` < 30d old. Silent on
    missing key / ZERO_RESULTS."""
    job = await db.jobs.find_one(
        {"id": job_id, "tenant_id": tenant_id}, {"_id": 0},
    )
    if not job:
        return False
    if job.get("geocoded_at"):
        try:
            g = datetime.fromisoformat(job["geocoded_at"].replace("Z", "+00:00"))
            if datetime.now(timezone.utc) - g < timedelta(days=_CACHE_TTL_DAYS):
                return False
        except Exception:
            pass

    addr = (job.get("service_address") or "").strip()
    if not addr:
        addr = " ".join(filter(None, [
            job.get("service_street"), job.get("service_city"),
            job.get("service_state"), job.get("service_zip"),
        ])).strip()
    if not addr and job.get("customer_id"):
        # Fall back to the customer's address.
        cust = await db.customers.find_one(
            {"id": job["customer_id"], "tenant_id": tenant_id},
            {"_id": 0, "service_address": 1, "address": 1,
              "service_street": 1, "service_city": 1,
              "service_state": 1, "service_zip": 1,
              "latitude": 1, "longitude": 1,
              "service_lat": 1, "service_lng": 1},
        ) or {}
        # If the customer is already geocoded, inherit the fix
        # directly rather than re-geocode.
        c_lat = cust.get("latitude") or cust.get("service_lat")
        c_lng = cust.get("longitude") or cust.get("service_lng")
        if c_lat is not None and c_lng is not None:
            await db.jobs.update_one(
                {"id": job_id, "tenant_id": tenant_id},
                {"$set": {
                    "site_lat": c_lat, "site_lng": c_lng,
                    "latitude": c_lat, "longitude": c_lng,
                    "geocoded_at": datetime.now(timezone.utc).isoformat(),
                    "geocode_source": "inherited_from_customer",
                }},
            )
            return True
        addr = (cust.get("service_address") or cust.get("address")
                    or " ".join(filter(None, [
                        cust.get("service_street"), cust.get("service_city"),
                        cust.get("service_state"), cust.get("service_zip"),
                    ]))).strip()
    if not addr:
        return False
    hit = await geocode_address(addr)
    if not hit:
        return False
    await db.jobs.update_one(
        {"id": job_id, "tenant_id": tenant_id},
        {"$set": {
            "site_lat": hit["lat"], "site_lng": hit["lng"],
            "latitude": hit["lat"], "longitude": hit["lng"],
            "geocode_precision": hit.get("precision"),
            "geocoded_at": datetime.now(timezone.utc).isoformat(),
            "geocode_source": "google",
        }},
    )
    return True


async def geocode_and_persist_property(property_id: str,
                                              tenant_id: str) -> bool:
    """Property version of the customer helper. Persists to the
    canonical ``latitude/longitude`` + ``geocoded_at``."""
    prop = await db.properties.find_one(
        {"id": property_id, "tenant_id": tenant_id}, {"_id": 0},
    )
    if not prop:
        return False
    if prop.get("geocoded_at"):
        try:
            g = datetime.fromisoformat(prop["geocoded_at"].replace("Z", "+00:00"))
            if datetime.now(timezone.utc) - g < timedelta(days=_CACHE_TTL_DAYS):
                return False
        except Exception:
            pass
    address_doc = prop.get("address") or {}
    addr = " ".join(filter(None, [
        address_doc.get("address_line1"), address_doc.get("address_line2"),
        address_doc.get("city"), address_doc.get("state"),
        address_doc.get("zip"),
    ])).strip()
    if not addr:
        return False
    hit = await geocode_address(addr)
    if not hit:
        return False
    await db.properties.update_one(
        {"id": property_id, "tenant_id": tenant_id},
        {"$set": {
            "latitude": hit["lat"], "longitude": hit["lng"],
            "geocode_precision": hit.get("precision"),
            "geocoded_at": datetime.now(timezone.utc).isoformat(),
            "geocode_source": "google",
        }},
    )
    return True
