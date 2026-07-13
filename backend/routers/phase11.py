"""Phase 11 additions — virtual-bid AI narrative, weather risk score,
public digital business card + .vcf download."""
import os
from datetime import datetime, timezone
from typing import Optional, List

import httpx
from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.responses import Response
from pydantic import BaseModel

from config import db, logger, EMERGENT_LLM_KEY
from utils import now_iso, new_id, get_current_user, require_admin

router = APIRouter()

OPEN_METEO = "https://api.open-meteo.com/v1/forecast"


# ─── /virtual-bid/generate ─────────────────────────────────────────────────
class VirtualBidIn(BaseModel):
    address: str
    lot_size_sqft: Optional[float] = None
    home_sqft: Optional[float] = None
    year_built: Optional[int] = None
    beds: Optional[int] = None
    baths: Optional[float] = None
    zestimate: Optional[float] = None
    customer_id: Optional[str] = None
    lead_id: Optional[str] = None


def _pool_volume_estimate(lot_size: Optional[float], home_sqft: Optional[float]) -> int:
    if lot_size and lot_size > 6000:
        return 22000
    if lot_size and lot_size > 4500:
        return 16000
    if home_sqft and home_sqft > 3500:
        return 20000
    return 14000


@router.post("/virtual-bid/generate")
async def virtual_bid_generate(body: VirtualBidIn, user: dict = Depends(require_admin)):
    est_gal = _pool_volume_estimate(body.lot_size_sqft, body.home_sqft)
    weekly_price = 149 if est_gal <= 16000 else 179 if est_gal <= 22000 else 209
    cleanup_price = 385 if est_gal <= 16000 else 485 if est_gal <= 22000 else 585
    narrative = (
        f"Estimated pool volume ~{est_gal:,} gal · Recommended weekly service. "
        "Configure EMERGENT_LLM_KEY for AI-generated bid narrative."
    )
    if EMERGENT_LLM_KEY:
        try:
            from emergentintegrations.llm.chat import LlmChat, UserMessage
            facts = ", ".join([
                f"lot {int(body.lot_size_sqft):,} sqft" if body.lot_size_sqft else "",
                f"home {int(body.home_sqft):,} sqft" if body.home_sqft else "",
                f"built {body.year_built}" if body.year_built else "",
                f"{body.beds} bd / {body.baths} ba" if body.beds else "",
                f"Zestimate ${int(body.zestimate):,}" if body.zestimate else "",
            ]).strip(", ")
            chat = LlmChat(api_key=EMERGENT_LLM_KEY, session_id=f"vbid-{new_id()[:8]}",
                           system_message="You write concise, persuasive property-specific pool + landscape service proposals. Return plaintext, 120-160 words.")
            prompt = (
                f"Property: {body.address}. {facts}. Estimated pool volume: {est_gal:,} gallons. "
                f"Recommended weekly service price: ${weekly_price}/mo. One-time cleanup: ${cleanup_price}. "
                "Write a warm, professional bid narrative that explains what's included in weekly service, "
                "why the price makes sense for this property, and one seasonal recommendation for Peoria AZ climate. "
                "Do not repeat the address or facts verbatim — reference them naturally."
            )
            raw = await chat.send_message(UserMessage(text=prompt))
            narrative = raw if isinstance(raw, str) else str(raw)
        except Exception as e:
            logger.warning(f"virtual-bid LLM fallback: {e}")

    doc = {
        "id": new_id(),
        "created_by": user["id"],
        "customer_id": body.customer_id, "lead_id": body.lead_id,
        "address": body.address,
        "lot_size_sqft": body.lot_size_sqft, "home_sqft": body.home_sqft,
        "year_built": body.year_built, "beds": body.beds, "baths": body.baths,
        "zestimate": body.zestimate,
        "estimated_pool_gallons": est_gal,
        "weekly_service_price": weekly_price,
        "one_time_cleanup_price": cleanup_price,
        "narrative": narrative,
        "created_at": now_iso(),
    }
    await db.virtual_bids.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.get("/virtual-bid")
async def list_virtual_bids(customer_id: Optional[str] = None, user: dict = Depends(require_admin)):
    q = {"customer_id": customer_id} if customer_id else {}
    return await db.virtual_bids.find(q, {"_id": 0}).sort("created_at", -1).to_list(200)


# ─── /weather/risk ─────────────────────────────────────────────────────────
@router.get("/weather/risk")
async def weather_risk(lat: float = 33.7897, lng: float = -112.3226,
                       days: int = 3, user: dict = Depends(get_current_user)):
    """Service-risk read for the next N days — combines precip + wind + temp signals."""
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(OPEN_METEO, params={
                "latitude": lat, "longitude": lng,
                "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,wind_speed_10m_max,uv_index_max,weather_code",
                "temperature_unit": "fahrenheit",
                "wind_speed_unit": "mph",
                "timezone": "auto",
                "forecast_days": days,
            })
    except httpx.HTTPError:
        raise HTTPException(424, "Could not reach the weather service")
    if r.status_code >= 400:
        raise HTTPException(424, "Weather service error")
    d = (r.json() or {}).get("daily") or {}
    out = []
    for i, day in enumerate(d.get("time") or []):
        precip = (d.get("precipitation_probability_max") or [None])[i] or 0
        wind = (d.get("wind_speed_10m_max") or [None])[i] or 0
        uv = (d.get("uv_index_max") or [None])[i] or 0
        code = (d.get("weather_code") or [None])[i] or 0
        reasons = []
        score = 0
        if precip >= 50: score += 40; reasons.append(f"{precip}% precip risk")
        elif precip >= 30: score += 20; reasons.append(f"{precip}% precip risk")
        if wind >= 25: score += 30; reasons.append(f"{int(wind)} mph winds")
        elif wind >= 15: score += 10
        if uv >= 10: score += 5; reasons.append(f"UV {int(uv)}")
        if code in (95, 96, 99): score += 40; reasons.append("Thunderstorms")
        rating = "poor" if score >= 50 else "fair" if score >= 25 else "good"
        out.append({
            "date": day,
            "high": (d.get("temperature_2m_max") or [None])[i],
            "low": (d.get("temperature_2m_min") or [None])[i],
            "precip": precip,
            "wind_mph": wind,
            "uv": uv,
            "weather_code": code,
            "service_risk_score": score,
            "service_risk_rating": rating,
            "risk_reasons": reasons,
        })
    return {"days": out}


@router.get("/weather/reschedule-recommendations")
async def reschedule_recs(user: dict = Depends(require_admin)):
    """Return jobs scheduled in the next 3 days that fall on 'poor' weather days."""
    risk = await weather_risk(user=user)  # type: ignore
    poor_days = {d["date"] for d in risk["days"] if d["service_risk_rating"] == "poor"}
    if not poor_days:
        return {"suggested": [], "poor_days": []}
    jobs = await db.jobs.find(
        {"scheduled_date": {"$exists": True, "$ne": None}, "status": {"$nin": ["completed", "canceled"]}},
        {"_id": 0},
    ).to_list(500)
    suggested = [j for j in jobs if (j.get("scheduled_date") or "")[:10] in poor_days]
    return {"suggested": suggested, "poor_days": sorted(poor_days)}


# ─── public digital card + vcard ───────────────────────────────────────────
class CardCreateIn(BaseModel):
    slug: str
    name: str
    title: Optional[str] = ""
    phone: Optional[str] = ""
    email: Optional[str] = ""
    website: Optional[str] = ""
    photo_url: Optional[str] = ""
    logo_url: Optional[str] = ""
    brand_color: Optional[str] = "#0284C7"
    service_zips: Optional[List[str]] = None
    booking_url: Optional[str] = ""
    company_name: Optional[str] = ""


@router.get("/cards")
async def list_cards(admin: dict = Depends(require_admin)):
    return await db.digital_cards.find({}, {"_id": 0}).sort("name", 1).to_list(500)


@router.post("/cards")
async def upsert_card(body: CardCreateIn, admin: dict = Depends(require_admin)):
    slug = (body.slug or "").strip().lower().replace(" ", "-")
    if not slug:
        raise HTTPException(400, "slug required")
    doc = {**body.dict(), "slug": slug, "id": new_id(), "updated_at": now_iso()}
    await db.digital_cards.update_one({"slug": slug}, {"$set": doc}, upsert=True)
    return await db.digital_cards.find_one({"slug": slug}, {"_id": 0})


@router.delete("/cards/{slug}")
async def delete_card(slug: str, admin: dict = Depends(require_admin)):
    await db.digital_cards.delete_one({"slug": slug})
    return {"ok": True}


@router.get("/public/cards/{slug}")
async def get_public_card(slug: str):
    doc = await db.digital_cards.find_one({"slug": slug}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Card not found")
    return doc


@router.get("/public/cards/{slug}/vcard")
async def download_vcard(slug: str):
    doc = await db.digital_cards.find_one({"slug": slug}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Card not found")
    lines = [
        "BEGIN:VCARD", "VERSION:3.0",
        f"FN:{doc.get('name', '')}",
        f"ORG:{doc.get('company_name', '')}",
        f"TITLE:{doc.get('title', '')}",
    ]
    if doc.get("phone"): lines.append(f"TEL;TYPE=WORK,VOICE:{doc['phone']}")
    if doc.get("email"): lines.append(f"EMAIL;TYPE=INTERNET:{doc['email']}")
    if doc.get("website"): lines.append(f"URL:{doc['website']}")
    lines.append("END:VCARD")
    body = "\r\n".join(lines) + "\r\n"
    return Response(
        content=body,
        media_type="text/vcard",
        headers={"Content-Disposition": f'attachment; filename="{slug}.vcf"'},
    )
