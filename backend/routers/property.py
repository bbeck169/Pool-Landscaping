import httpx
from fastapi import APIRouter, HTTPException, Depends, Query
from typing import Optional, List, Any
from pydantic import BaseModel, Field

from config import db, OPENWEB_NINJA_API_KEY
from utils import now_iso, new_id, require_admin
from routers.tenants import get_current_tenant

router = APIRouter()

OWN_BASE = "https://api.openwebninja.com/realtime-zillow-data"


def _extract_photos(data: dict) -> List[str]:
    photos = data.get("photos") or data.get("images") or data.get("originalPhotos") or []
    out: List[str] = []
    for p in photos:
        if isinstance(p, str):
            out.append(p)
        elif isinstance(p, dict):
            url = None
            ms = p.get("mixedSources") or {}
            for key in ("jpeg", "webp"):
                arr = ms.get(key)
                if isinstance(arr, list) and arr:
                    last = arr[-1]
                    if isinstance(last, dict) and last.get("url"):
                        url = last["url"]
                        break
            url = url or p.get("url") or p.get("href") or p.get("src")
            if url:
                out.append(url)
    if not out and data.get("imgSrc"):
        out.append(data["imgSrc"])
    # dedupe, cap
    seen, uniq = set(), []
    for u in out:
        if u not in seen:
            seen.add(u)
            uniq.append(u)
    return uniq[:40]


def _norm_detail(data: dict) -> dict:
    reso = data.get("resoFacts") or {}
    hdp = data.get("hdpUrl")
    return {
        "zpid": str(data.get("zpid") or ""),
        "address": data.get("streetAddress") or data.get("address") or data.get("abbreviatedAddress") or "",
        "city": data.get("city"),
        "state": data.get("state"),
        "zipcode": data.get("zipcode"),
        "price": data.get("price"),
        "zestimate": data.get("zestimate"),
        "beds": data.get("bedrooms"),
        "baths": data.get("bathrooms"),
        "sqft": data.get("livingArea") or data.get("livingAreaValue"),
        "lot_size": data.get("lotSize") or reso.get("lotSize"),
        "year_built": data.get("yearBuilt") or reso.get("yearBuilt"),
        "home_type": data.get("homeType"),
        "status": data.get("homeStatus"),
        "description": data.get("description"),
        "lat": data.get("latitude"),
        "lng": data.get("longitude"),
        "detail_url": (f"https://www.zillow.com{hdp}" if hdp else data.get("url")),
        "photos": _extract_photos(data),
    }


@router.get("/property/lookup")
async def lookup(address: str = Query(...), user: dict = Depends(require_admin)):
    """Pull a Zillow listing (photos + facts) by full street address for virtual bidding."""
    address = (address or "").strip()
    if len(address) < 5:
        raise HTTPException(400, "Enter a full property address")
    if not OPENWEB_NINJA_API_KEY:
        raise HTTPException(424, "Zillow data provider not configured")
    try:
        async with httpx.AsyncClient(timeout=25) as c:
            r = await c.get(
                f"{OWN_BASE}/property-details-address",
                params={"address": address},
                headers={"x-api-key": OPENWEB_NINJA_API_KEY},
            )
    except httpx.HTTPError:
        raise HTTPException(424, "Could not reach the Zillow data provider")
    if r.status_code == 429:
        raise HTTPException(429, "Zillow provider rate limit reached — try again shortly")
    if r.status_code == 404:
        raise HTTPException(404, "No Zillow listing found for that address")
    if r.status_code >= 400:
        raise HTTPException(424, "Zillow data provider error")
    payload = r.json() or {}
    data = payload.get("data") or payload
    if not isinstance(data, dict) or not (data.get("zpid") or data.get("streetAddress") or data.get("address")):
        raise HTTPException(404, "No Zillow listing found for that address")
    return _norm_detail(data)


class SaveIn(BaseModel):
    address: str
    zpid: Optional[str] = None
    detail_url: Optional[str] = None
    price: Optional[float] = None
    zestimate: Optional[float] = None
    beds: Optional[float] = None
    baths: Optional[float] = None
    sqft: Optional[float] = None
    lot_size: Optional[Any] = None
    year_built: Optional[int] = None
    home_type: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    photos: List[str] = Field(default_factory=list)
    customer_id: Optional[str] = None
    lead_id: Optional[str] = None
    create_lead: bool = False


@router.post("/property/save")
async def save_property(body: SaveIn,
                        user: dict = Depends(require_admin),
                        tenant: dict = Depends(get_current_tenant)):
    now = now_iso()
    lead_id = body.lead_id
    lead_created = False
    if body.create_lead and not lead_id:
        facts = " · ".join(
            [x for x in [
                f"{body.beds} bd" if body.beds else None,
                f"{body.baths} ba" if body.baths else None,
                f"{int(body.sqft):,} sqft" if body.sqft else None,
                f"Zillow ${int(body.price):,}" if body.price else None,
            ] if x]
        )
        lead = {
            "id": new_id(),
            "tenant_id": tenant["id"],
            "name": body.address,
            "phone": "",
            "email": "",
            "source": "Virtual Bid",
            "status": "new",
            "est_value": float(body.price or 0),
            "address": body.address,
            "notes": f"Virtual bid target. {facts}".strip(),
            "created_at": now,
            "created_by": user.get("id"),
        }
        await db.leads.insert_one(lead)
        lead_id = lead["id"]
        lead_created = True

    doc = {
        "id": new_id(),
        "tenant_id": tenant["id"],
        "created_by": user["id"],
        "created_by_name": user.get("name", ""),
        "address": body.address,
        "zpid": body.zpid,
        "detail_url": body.detail_url,
        "price": body.price,
        "zestimate": body.zestimate,
        "beds": body.beds,
        "baths": body.baths,
        "sqft": body.sqft,
        "lot_size": body.lot_size,
        "year_built": body.year_built,
        "home_type": body.home_type,
        "lat": body.lat,
        "lng": body.lng,
        "photos": (body.photos or [])[:40],
        "customer_id": body.customer_id,
        "lead_id": lead_id,
        "created_at": now,
    }
    await db.saved_properties.insert_one(doc)
    doc.pop("_id", None)
    return {"property": doc, "lead_id": lead_id, "lead_created": lead_created}


@router.get("/property/saved")
async def list_saved(customer_id: Optional[str] = Query(None), lead_id: Optional[str] = Query(None),
                     user: dict = Depends(require_admin),
                     tenant: dict = Depends(get_current_tenant)):
    q: dict = {"tenant_id": tenant["id"]}
    if customer_id:
        q["customer_id"] = customer_id
    if lead_id:
        q["lead_id"] = lead_id
    return await db.saved_properties.find(q, {"_id": 0}).sort("created_at", -1).to_list(300)


@router.delete("/property/saved/{pid}")
async def delete_saved(pid: str,
                       user: dict = Depends(require_admin),
                       tenant: dict = Depends(get_current_tenant)):
    await db.saved_properties.delete_one({"id": pid, "tenant_id": tenant["id"]})
    return {"ok": True}
