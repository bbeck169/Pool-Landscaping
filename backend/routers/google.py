"""Phase 10.5 — Google Maps integration (address geocoding backfill + settings toggles).

Exposes:
- POST /api/admin/geocode-addresses     — backfill customer/job lat/lng from Google Geocoding
- GET/PUT /api/settings/maps            — map provider + autocomplete toggles
- GET  /api/settings/integrations       — masked view of all wired API keys
"""
import asyncio
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from config import (
    db, logger,
    GOOGLE_API_KEY, EMERGENT_LLM_KEY, RESEND_API_KEY,
    OPENWEB_NINJA_API_KEY,
)
from utils import now_iso, require_admin

router = APIRouter()

GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"


def _mask(value: str, keep: int = 4) -> str:
    if not value:
        return ""
    if len(value) <= keep * 2:
        return "*" * len(value)
    return f"{value[:keep]}…{value[-keep:]}"


async def _geocode_one(client: httpx.AsyncClient, address: str) -> Optional[dict]:
    try:
        r = await client.get(GEOCODE_URL, params={"address": address, "key": GOOGLE_API_KEY})
        if r.status_code != 200:
            return None
        j = r.json()
        if j.get("status") != "OK" or not j.get("results"):
            return None
        top = j["results"][0]
        loc = top.get("geometry", {}).get("location", {})
        return {
            "lat": loc.get("lat"), "lng": loc.get("lng"),
            "formatted": top.get("formatted_address"),
            "place_id": top.get("place_id"),
        }
    except Exception as e:
        logger.warning(f"geocode failed for '{address}': {e}")
        return None


@router.post("/admin/geocode-addresses")
async def geocode_addresses(admin: dict = Depends(require_admin)):
    """Backfill lat/lng on customers + jobs that have an address but no coordinates.
    Rate-limited at ~8 req/sec to stay well under Google's default 50 QPS."""
    if not GOOGLE_API_KEY:
        raise HTTPException(424, "GOOGLE_API_KEY not configured")

    processed = 0
    updated = 0
    skipped = 0
    errors: list[str] = []

    async with httpx.AsyncClient(timeout=15) as client:
        # ── customers ──
        q = {
            "address": {"$exists": True, "$nin": [None, ""]},
            "$or": [{"lat": {"$in": [None, 0]}}, {"lat": {"$exists": False}}],
        }
        async for c in db.customers.find(q, {"_id": 0}):
            processed += 1
            addr = c.get("address")
            if not addr:
                skipped += 1
                continue
            geo = await _geocode_one(client, addr)
            if geo and geo.get("lat"):
                await db.customers.update_one({"id": c["id"]}, {"$set": {
                    "lat": geo["lat"], "lng": geo["lng"],
                    "geocoded_address": geo.get("formatted"),
                    "geocoded_place_id": geo.get("place_id"),
                    "geocoded_at": now_iso(),
                }})
                updated += 1
            else:
                errors.append(c.get("name") or c["id"])
            await asyncio.sleep(0.12)  # ~8 QPS

        # ── jobs (service_address / address fields) ──
        jq = {
            "$or": [
                {"address": {"$exists": True, "$nin": [None, ""]}},
                {"service_address": {"$exists": True, "$nin": [None, ""]}},
            ],
            "$and": [{"$or": [{"lat": {"$in": [None, 0]}}, {"lat": {"$exists": False}}]}],
        }
        async for j in db.jobs.find(jq, {"_id": 0}):
            processed += 1
            addr = j.get("service_address") or j.get("address")
            if not addr:
                skipped += 1
                continue
            geo = await _geocode_one(client, addr)
            if geo and geo.get("lat"):
                await db.jobs.update_one({"id": j["id"]}, {"$set": {
                    "lat": geo["lat"], "lng": geo["lng"],
                    "geocoded_address": geo.get("formatted"),
                    "geocoded_at": now_iso(),
                }})
                updated += 1
            else:
                errors.append(j.get("title") or j["id"])
            await asyncio.sleep(0.12)

    return {
        "processed": processed, "updated": updated, "skipped": skipped,
        "errors": errors[:20], "error_count": len(errors),
    }


# ─── settings/maps ─────────────────────────────────────────────────────────
class MapSettingsIn(BaseModel):
    map_provider: Optional[str] = None          # "openstreetmap" | "google"
    autocomplete_enabled: Optional[bool] = None


DEFAULT_MAP_SETTINGS = {
    "map_provider": "openstreetmap",
    "autocomplete_enabled": True,
}


@router.get("/settings/maps")
async def get_map_settings(admin: dict = Depends(require_admin)):
    doc = await db.settings.find_one({"id": "maps"}, {"_id": 0}) or {}
    return {
        "map_provider": doc.get("map_provider") or DEFAULT_MAP_SETTINGS["map_provider"],
        "autocomplete_enabled": doc.get("autocomplete_enabled") if doc.get("autocomplete_enabled") is not None else DEFAULT_MAP_SETTINGS["autocomplete_enabled"],
        "google_configured": bool(GOOGLE_API_KEY),
    }


@router.put("/settings/maps")
async def put_map_settings(body: MapSettingsIn, admin: dict = Depends(require_admin)):
    upd = {k: v for k, v in body.dict().items() if v is not None}
    if upd.get("map_provider") not in (None, "openstreetmap", "google"):
        raise HTTPException(400, "map_provider must be 'openstreetmap' or 'google'")
    await db.settings.update_one(
        {"id": "maps"},
        {"$set": {"id": "maps", **upd, "updated_at": now_iso()}},
        upsert=True,
    )
    return await get_map_settings(admin)


# Public read for frontend so the map provider is available WITHOUT admin token.
@router.get("/public/map-settings")
async def public_map_settings():
    doc = await db.settings.find_one({"id": "maps"}, {"_id": 0}) or {}
    return {
        "map_provider": doc.get("map_provider") or DEFAULT_MAP_SETTINGS["map_provider"],
        "autocomplete_enabled": doc.get("autocomplete_enabled") if doc.get("autocomplete_enabled") is not None else DEFAULT_MAP_SETTINGS["autocomplete_enabled"],
        "google_configured": bool(GOOGLE_API_KEY),
    }


# ─── settings/integrations ─────────────────────────────────────────────────
@router.get("/settings/integrations")
async def get_integrations_status(admin: dict = Depends(require_admin)):
    """Report the wiring status of all third-party integrations. Keys are masked."""
    import os
    stripe_key = os.environ.get("STRIPE_API_KEY", "") or os.environ.get("STRIPE_SECRET_KEY", "")
    twilio_sid = os.environ.get("TWILIO_ACCOUNT_SID", "")
    ring_key = ""
    ring_doc = await db.settings.find_one({"id": "ringcentral"}, {"_id": 0}) or {}
    if ring_doc.get("api_key"):
        ring_key = ring_doc["api_key"]
    return {
        "emergent_llm":    {"configured": bool(EMERGENT_LLM_KEY),        "preview": _mask(EMERGENT_LLM_KEY),      "note": "OpenAI / Claude / Gemini via Emergent"},
        "google":          {"configured": bool(GOOGLE_API_KEY),          "preview": _mask(GOOGLE_API_KEY),        "note": "Places autocomplete · Geocoding · Maps tiles"},
        "openweb_ninja":   {"configured": bool(OPENWEB_NINJA_API_KEY),   "preview": _mask(OPENWEB_NINJA_API_KEY), "note": "Zillow sold-lead data for D2D"},
        "resend":          {"configured": bool(RESEND_API_KEY),          "preview": _mask(RESEND_API_KEY),        "note": "Transactional email (test sender until domain is verified)"},
        "stripe":          {"configured": bool(stripe_key),              "preview": _mask(stripe_key),            "note": "Card payments (test mode)"},
        "twilio":          {"configured": bool(twilio_sid),              "preview": _mask(twilio_sid),            "note": "SMS delivery"},
        "ringcentral":     {"configured": bool(ring_key),                "preview": _mask(ring_key),              "note": "Inbound call tracking"},
    }
