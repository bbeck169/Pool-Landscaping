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
    resend_from = os.environ.get("EMAIL_FROM", "")
    stripe_wh = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
    wp_url = os.environ.get("WORDPRESS_URL", "")
    gbp_client = os.environ.get("GBP_CLIENT_ID", "")
    ring_key = ""
    ring_doc = await db.settings.find_one({"id": "ringcentral"}, {"_id": 0}) or {}
    if ring_doc.get("api_key"):
        ring_key = ring_doc["api_key"]
    return {
        "emergent_llm":    {"configured": bool(EMERGENT_LLM_KEY),        "preview": _mask(EMERGENT_LLM_KEY),      "note": "OpenAI / Claude / Gemini via Emergent"},
        "google":          {"configured": bool(GOOGLE_API_KEY),          "preview": _mask(GOOGLE_API_KEY),        "note": "Places autocomplete · Geocoding · Maps tiles"},
        "openweb_ninja":   {"configured": bool(OPENWEB_NINJA_API_KEY),   "preview": _mask(OPENWEB_NINJA_API_KEY), "note": "Zillow sold-lead data for D2D"},
        "resend":          {"configured": bool(RESEND_API_KEY),          "preview": _mask(RESEND_API_KEY),        "note": f"Transactional email · from {resend_from}"},
        "stripe":          {"configured": bool(stripe_key),              "preview": _mask(stripe_key),            "note": "Card payments (test mode)"},
        "stripe_webhook":  {"configured": bool(stripe_wh),               "preview": _mask(stripe_wh),             "note": "Webhook signing secret · unsigned fallback active if missing"},
        "twilio":          {"configured": bool(twilio_sid),              "preview": _mask(twilio_sid),            "note": "SMS delivery"},
        "wordpress":       {"configured": bool(wp_url),                  "preview": _mask(wp_url),                "note": "SEO article publishing"},
        "gbp":             {"configured": bool(gbp_client),              "preview": _mask(gbp_client),            "note": "Google Business Profile OAuth (Client ID)"},
        "ringcentral":     {"configured": bool(ring_key),                "preview": _mask(ring_key),              "note": "Inbound call tracking"},
    }


@router.get("/settings/integrations/health/{integration}")
async def integration_health(integration: str, admin: dict = Depends(require_admin)):
    """Lightweight liveness check for the specified integration."""
    import os
    try:
        if integration == "google":
            if not GOOGLE_API_KEY: return {"ok": False, "message": "GOOGLE_API_KEY unset"}
            async with httpx.AsyncClient(timeout=8) as c:
                r = await c.get(GEOCODE_URL, params={"address": "10840 W Saddlehorn Rd, Peoria AZ", "key": GOOGLE_API_KEY})
                j = r.json() if r.status_code == 200 else {}
            return {"ok": j.get("status") == "OK", "message": j.get("status", f"HTTP {r.status_code}")}
        if integration == "openweb_ninja":
            if not OPENWEB_NINJA_API_KEY: return {"ok": False, "message": "OPENWEB_NINJA_API_KEY unset"}
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.get("https://api.openwebninja.com/realtime-zillow-data/search_zip",
                                params={"zip": "85383"}, headers={"x-api-key": OPENWEB_NINJA_API_KEY})
            return {"ok": r.status_code == 200, "message": f"HTTP {r.status_code}"}
        if integration == "resend":
            key = os.environ.get("RESEND_API_KEY", "")
            if not key: return {"ok": False, "message": "RESEND_API_KEY unset"}
            async with httpx.AsyncClient(timeout=8) as c:
                r = await c.get("https://api.resend.com/domains", headers={"Authorization": f"Bearer {key}"})
            return {"ok": r.status_code == 200, "message": f"HTTP {r.status_code}"}
        if integration == "stripe":
            key = os.environ.get("STRIPE_API_KEY", "") or os.environ.get("STRIPE_SECRET_KEY", "")
            if not key: return {"ok": False, "message": "STRIPE_API_KEY unset"}
            async with httpx.AsyncClient(timeout=8) as c:
                r = await c.get("https://api.stripe.com/v1/payment_intents?limit=1", headers={"Authorization": f"Bearer {key}"})
            return {"ok": r.status_code == 200, "message": f"HTTP {r.status_code}"}
        if integration == "emergent_llm":
            return {"ok": bool(EMERGENT_LLM_KEY), "message": "Key present" if EMERGENT_LLM_KEY else "unset"}
        if integration == "wordpress":
            # Feb-2026 · real reachability probe against
            # ``/wp-json/wp/v2/users/me`` using Basic Auth with the
            # Application Password. Returns:
            #   * ok=true, HTTP 200 + user name — fully wired
            #   * ok=false, HTTP 401 — creds wrong
            #   * ok=false, HTTP 202 + text/html — WAF interstitial
            #     (SiteGround SG-Optimizer, Cloudflare bot manager,
            #     etc.) — user must whitelist our egress IP
            #   * ok=false, unset — no env config
            wp_url = os.environ.get("WORDPRESS_URL", "").strip().rstrip("/")
            wp_user = (os.environ.get("WORDPRESS_USERNAME")
                         or os.environ.get("WORDPRESS_USER") or "").strip()
            wp_pw = os.environ.get("WORDPRESS_APP_PASSWORD", "").strip()
            if not (wp_url and wp_user and wp_pw):
                return {"ok": False,
                          "message": "WORDPRESS_URL / WORDPRESS_USERNAME / WORDPRESS_APP_PASSWORD unset"}
            try:
                async with httpx.AsyncClient(timeout=10) as c:
                    r = await c.get(
                        f"{wp_url}/wp-json/wp/v2/users/me",
                        auth=(wp_user, wp_pw),
                        headers={"Accept": "application/json",
                                   "User-Agent": "PlofvCRM/1.0 (+wp-health-check)"},
                    )
            except Exception as e:
                return {"ok": False, "message": f"unreachable: {e}"[:200]}
            ct = (r.headers.get("content-type") or "").lower()
            if r.status_code == 200 and "json" in ct:
                try:
                    name = (r.json() or {}).get("name") or wp_user
                except Exception:
                    name = wp_user
                return {"ok": True, "message": f"HTTP 200 · authed as {name}"}
            if r.status_code == 401:
                return {"ok": False,
                          "message": "HTTP 401 — Application Password rejected"}
            if r.status_code == 202 or ("html" in ct and "sgcaptcha" in r.text.lower()):
                return {"ok": False,
                          "message": "Blocked by SiteGround SG-Optimizer WAF — "
                                       "whitelist the pod egress IP or disable "
                                       "SG bot protection for /wp-json/*"}
            return {"ok": False,
                      "message": f"HTTP {r.status_code} ({ct[:40] or 'unknown ct'})"}
        if integration in {"twilio", "gbp", "ringcentral", "stripe_webhook"}:
            # Not enough config wired yet to actually ping — report presence only.
            keymap = {
                "twilio": "TWILIO_ACCOUNT_SID", "gbp": "GBP_CLIENT_ID",
                "wordpress": "WORDPRESS_URL", "ringcentral": "RINGCENTRAL_API_KEY",
                "stripe_webhook": "STRIPE_WEBHOOK_SECRET",
            }
            v = os.environ.get(keymap[integration], "")
            return {"ok": bool(v), "message": "Key present" if v else "unset"}
        raise HTTPException(404, "Unknown integration")
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"integration health {integration} failed: {e}")
        return {"ok": False, "message": str(e)[:200]}
