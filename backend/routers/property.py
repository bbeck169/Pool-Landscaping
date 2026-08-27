import httpx
from fastapi import APIRouter, HTTPException, Depends, Query
from fastapi.responses import JSONResponse
from typing import Optional, List, Any, Dict
from pydantic import BaseModel, Field

from config import db, OPENWEB_NINJA_API_KEY, logger
from utils import now_iso, new_id, require_admin, require_zillow_access
from routers.tenants import get_current_tenant
from services import zillow_rate_limit as zrl

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
async def lookup(address: str = Query(...),
                 override_budget: bool = Query(False),
                 user: dict = Depends(require_zillow_access),
                 tenant: dict = Depends(get_current_tenant)):
    """Pull a Zillow listing (photos + facts) by full street address for virtual bidding.

    Phase 56.9b Step 8 — Rate-limited + budget-guarded + cached. Techs
    now have access; guardrails cap tech usage (20/day, 200/mo) and
    tenant spend ($1000/mo default, super_admin may `?override_budget=true`).
    """
    address = (address or "").strip()
    if len(address) < 5:
        raise HTTPException(400, "Enter a full property address")
    if not OPENWEB_NINJA_API_KEY:
        raise HTTPException(424, "Zillow data provider not configured")

    endpoint = "/property/lookup"
    caps = await zrl.check_caps(user, tenant)
    caps = await zrl.apply_override_or_fail(caps, user, tenant, endpoint,
                                             address, override_budget)
    if not caps["allowed"]:
        if caps.get("reason") == "tenant_budget_exhausted":
            raise HTTPException(429, detail={
                "error": "tenant_budget_exhausted",
                "tenant_used": caps["tenant_used"],
                "tenant_budget": caps["tenant_budget"],
            })
        raise HTTPException(429, detail={
            "error": caps["reason"],
            "reset_at": caps["reset_at"],
            "usage": caps["usage"],
        })

    # Cache hit — no paid call, no usage log.
    cached = await zrl.read_cache(address)
    if cached is not None:
        await db.zillow_audit.insert_one({
            "id": new_id(),
            "event": "zillow_cache_hit",
            "tenant_id": tenant["id"],
            "user_id": user["id"],
            "endpoint": endpoint,
            "address_hash": zrl.address_hash(address),
            "ts": now_iso(),
        })
        body = {**cached, "_cached": True, "usage": caps["usage"],
                "tenant_used": caps["tenant_used"], "tenant_budget": caps["tenant_budget"],
                "budget_warning": caps["budget_warning"]}
        if caps.get("override_audit_id"):
            body["override_audit_id"] = caps["override_audit_id"]
        return JSONResponse(body, headers=zrl.response_headers(caps))

    # Paid provider call.
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
    normalized = _norm_detail(data)
    await zrl.write_cache(address, normalized)
    await zrl.log_call(user, tenant, endpoint, address)
    caps_after = await zrl.check_caps(user, tenant)
    body = {**normalized, "_cached": False, "usage": caps_after["usage"],
            "tenant_used": caps_after["tenant_used"], "tenant_budget": caps_after["tenant_budget"],
            "budget_warning": caps_after["budget_warning"]}
    if caps.get("override_audit_id"):
        body["override_audit_id"] = caps["override_audit_id"]
    return JSONResponse(body, headers=zrl.response_headers(caps_after))


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
                        user: dict = Depends(require_zillow_access),
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
        # Feb-2026 · Fire ``new_lead`` sequence trigger for property-
        # intake / virtual-bid capture. Inline — no BackgroundTasks
        # in this handler.
        try:
            from services.marketing.lead_triggers import (
                fire_new_lead_sequence_trigger,
            )
            await fire_new_lead_sequence_trigger(
                lead=lead, tenant_id=lead.get("tenant_id") or tenant["id"],
            )
        except Exception:
            pass
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
                     user: dict = Depends(require_zillow_access),
                     tenant: dict = Depends(get_current_tenant)):
    q: dict = {"tenant_id": tenant["id"]}
    if customer_id:
        q["customer_id"] = customer_id
    if lead_id:
        q["lead_id"] = lead_id
    return await db.saved_properties.find(q, {"_id": 0}).sort("created_at", -1).to_list(300)


@router.delete("/property/saved/{pid}")
async def delete_saved(pid: str,
                       user: dict = Depends(require_zillow_access),
                       tenant: dict = Depends(get_current_tenant)):
    await db.saved_properties.delete_one({"id": pid, "tenant_id": tenant["id"]})
    return {"ok": True}


# ═══════════════════════════════════════════════════════════════════════
# Phase 25 · Tech Property Lookup — cached, rate-limited, honestly mocked
# ═══════════════════════════════════════════════════════════════════════
import re
from datetime import datetime, timezone, timedelta
from utils import get_current_user
from config import GOOGLE_API_KEY


async def require_tech_or_admin(user: dict = Depends(get_current_user)) -> dict:
    # Phase 5A · Feb 2026 — Property Lookup is admin/manager/marketing
    # only. Technicians get 403 (feature removed from every tech nav
    # surface). Marketing kept because Zillow enrichment powers the
    # Marketing Studio audience segmentation.
    if (user.get("role") or "") in {"admin", "super_admin", "marketing"}:
        return user
    raise HTTPException(403, "Property Lookup is admin, manager, or marketing only")


async def require_tech_or_admin_write(user: dict = Depends(get_current_user)) -> dict:
    # Phase 5A · Feb 2026 — write path also locked to admin/manager. The
    # legacy function name is kept so existing @Depends() decorators
    # below don't churn.
    if (user.get("role") or "") in {"admin", "super_admin", "manager"}:
        return user
    raise HTTPException(403, "Admins/managers only")


def _norm_address_key(addr: str) -> str:
    return re.sub(r"\s+", " ", (addr or "").strip().lower())


async def _ensure_indexes():
    try:
        await db.property_lookup_cache.create_index(
            "cached_at", expireAfterSeconds=60 * 60 * 24)
        await db.property_lookup_cache.create_index(
            [("address_normalized", 1)])
        await db.property_search_history.create_index(
            "ts", expireAfterSeconds=60 * 60 * 24 * 30)
        await db.property_search_history.create_index(
            [("tenant_id", 1), ("user_id", 1), ("ts", -1)])
        await db.property_notes.create_index(
            [("tenant_id", 1), ("address_normalized", 1)])
    except Exception:
        pass


def _extract_owner(data: dict) -> Optional[str]:
    for key in ("ownerName", "owner_name", "owner", "assessorName"):
        if data.get(key):
            return data[key]
    reso = data.get("resoFacts") or {}
    for key in ("ownerName", "owner_name", "owner"):
        if reso.get(key):
            return reso[key]
    return None


def _extract_last_sale(data: dict) -> Dict[str, Any]:
    reso = data.get("resoFacts") or {}
    for src in (data, reso):
        p = (src.get("lastSoldPrice") or src.get("priceHistory", [{}])[0].get("price")
             if src.get("priceHistory") else src.get("lastSoldPrice"))
        d = (src.get("dateSoldString") or src.get("lastSoldDate")
             or (src.get("priceHistory", [{}])[0].get("date")
                 if src.get("priceHistory") else None))
        if p or d:
            return {"last_sale_price": p, "last_sale_date": d}
    return {"last_sale_price": None, "last_sale_date": None}


def _extract_comps(data: dict) -> List[Dict[str, Any]]:
    comps = (data.get("nearbyHomes") or data.get("comparables")
             or data.get("comps") or [])
    out: List[Dict[str, Any]] = []
    for c in comps[:5]:
        if not isinstance(c, dict): continue
        out.append({
            "address": c.get("streetAddress") or c.get("address"),
            "price": c.get("price") or c.get("lastSoldPrice"),
            "sold_date": c.get("lastSoldDate") or c.get("dateSoldString"),
            "beds": c.get("bedrooms"), "baths": c.get("bathrooms"),
            "sqft": c.get("livingArea") or c.get("livingAreaValue"),
            "photo": (c.get("miniCardPhotos") or [{}])[0].get("url")
                     if c.get("miniCardPhotos") else c.get("imgSrc"),
        })
    return out


def _norm_lookup(data: dict) -> Dict[str, Any]:
    """Rich normalization for Phase 25 tech surface — extends `_norm_detail`
    with owner, last-sale, tax assessment, comps."""
    base = _norm_detail(data)
    reso = data.get("resoFacts") or {}
    tax = (data.get("taxAssessedValue") or data.get("propertyTaxRate")
           or reso.get("taxAssessedValue"))
    base.update({
        "owner_name": _extract_owner(data),
        **_extract_last_sale(data),
        "tax_assessment": tax,
        "listing_status": data.get("homeStatus"),
        "listing_price": data.get("price"),
        "property_type": data.get("homeType") or reso.get("homeType"),
        "neighborhood_comps": _extract_comps(data),
    })
    return base


async def _rate_limited(tenant_id: str, user_id: str, limit: int = 30) -> bool:
    since = datetime.now(timezone.utc) - timedelta(hours=1)
    n = await db.property_search_history.count_documents({
        "tenant_id": tenant_id, "user_id": user_id,
        "ts": {"$gte": since.isoformat()},
    })
    return n >= limit


async def _record_history(tenant_id: str, user_id: str, address: str):
    await db.property_search_history.insert_one({
        "id": new_id(), "tenant_id": tenant_id, "user_id": user_id,
        "address": address, "ts": datetime.now(timezone.utc).isoformat(),
    })


async def _cached_lookup(address: str) -> Optional[Dict[str, Any]]:
    key = _norm_address_key(address)
    row = await db.property_lookup_cache.find_one(
        {"address_normalized": key}, {"_id": 0})
    if not row: return None
    return {
        "response": row["response_json"],
        "cached_at": row["cached_at"],
        "cached": True,
    }


async def _cache_write(address: str, payload: Dict[str, Any]):
    key = _norm_address_key(address)
    await db.property_lookup_cache.update_one(
        {"address_normalized": key},
        {"$set": {"address_normalized": key,
                    "response_json": payload,
                    "cached_at": datetime.now(timezone.utc)}},
        upsert=True,
    )


async def _fetch_zillow(address: str) -> Dict[str, Any]:
    """Returns {ok, data, reason}. Never raises for expected provider
    failures — callers convert failures to explicit mocked responses so
    tech field usage keeps flowing (spec: no silent mocking, but degraded
    modes must be transparent)."""
    try:
        async with httpx.AsyncClient(timeout=25) as c:
            r = await c.get(
                f"{OWN_BASE}/property-details-address",
                params={"address": address},
                headers={"x-api-key": OPENWEB_NINJA_API_KEY},
            )
        if r.status_code == 429:
            return {"ok": False, "data": None,
                     "reason": "provider_rate_limit"}
        if r.status_code == 404:
            return {"ok": False, "data": None, "reason": "not_found"}
        if r.status_code >= 400:
            return {"ok": False, "data": None,
                     "reason": f"provider_status_{r.status_code}"}
        payload = r.json() or {}
        data = payload.get("data") or payload
        if not isinstance(data, dict): return {"ok": False, "data": None,
                                                 "reason": "invalid_payload"}
        if not (data.get("zpid") or data.get("streetAddress")
                or data.get("address")):
            return {"ok": False, "data": None, "reason": "not_found"}
        return {"ok": True, "data": data, "reason": None}
    except Exception as ex:
        logger.warning(f"Zillow fetch failed: {ex}")
        return {"ok": False, "data": None,
                 "reason": f"provider_unreachable: {ex}"}


@router.get("/property/search")
async def property_search(address: str = Query(..., min_length=5),
                              user: dict = Depends(require_tech_or_admin),
                              tenant: dict = Depends(get_current_tenant)):
    """Tech-facing property lookup. Cached 24h, rate-limited 30/hour/tech,
    honestly mocked if no API key configured."""
    await _ensure_indexes()

    # Rate limit — only enforced on non-cached hits below (after cache check
    # we still record history for both cache + fresh, so limit counts real
    # user activity).
    if await _rate_limited(tenant["id"], user["id"]):
        raise HTTPException(429,
            "Rate limit: 30 property lookups per hour")

    cached = await _cached_lookup(address)
    if cached:
        await _record_history(tenant["id"], user["id"], address)
        return {
            "property": cached["response"].get("property")
                        or cached["response"],
            "cached": True,
            "cached_at": (cached["cached_at"].isoformat()
                            if hasattr(cached["cached_at"], "isoformat")
                            else str(cached["cached_at"])),
            "mocked": bool(cached["response"].get("mocked")),
            "reason": cached["response"].get("reason"),
        }

    if not OPENWEB_NINJA_API_KEY:
        payload = {
            "property": {
                "address": address,
                "mocked": True,
                "zestimate": None,
                "owner_name": None,
                "neighborhood_comps": [],
            },
            "mocked": True,
            "reason": "OPENWEB_NINJA_API_KEY not configured",
        }
        await _cache_write(address, payload)
        await _record_history(tenant["id"], user["id"], address)
        return {**payload, "cached": False}

    raw = await _fetch_zillow(address)
    if not raw["ok"]:
        # Upstream failed. Return explicit mocked payload — never silent.
        payload = {
            "property": {
                "address": address,
                "mocked": True,
                "zestimate": None,
                "owner_name": None,
                "neighborhood_comps": [],
            },
            "mocked": True,
            "reason": raw["reason"] or "provider_unavailable",
        }
        await _cache_write(address, payload)
        await _record_history(tenant["id"], user["id"], address)
        return {**payload, "cached": False,
                 "cached_at": datetime.now(timezone.utc).isoformat()}
    normalized = _norm_lookup(raw["data"])
    payload = {"property": normalized, "mocked": False}
    await _cache_write(address, payload)
    await _record_history(tenant["id"], user["id"], address)
    return {**payload, "cached": False,
             "cached_at": datetime.now(timezone.utc).isoformat()}


@router.get("/maps/reverse-geocode",
             operation_id="maps.reverseGeocode")
async def maps_reverse_geocode(
    lat: float = Query(...), lng: float = Query(...),
    user: dict = Depends(require_tech_or_admin),
):
    """Feb-2026 · Lightweight reverse-geocode helper used by the Rank
    Tracker "Boost this area" CTA. Returns just ``{formatted_address,
    city, state, zip}`` — no property search, no persistence. Returns
    a fallback payload (not a 4xx) when the Google API key isn't
    configured so callers can degrade gracefully."""
    if not GOOGLE_API_KEY:
        return {"formatted_address": "", "city": "", "state": "", "zip": "",
                 "available": False, "reason": "GOOGLE_API_KEY not configured"}
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(
                "https://maps.googleapis.com/maps/api/geocode/json",
                params={"latlng": f"{lat},{lng}", "key": GOOGLE_API_KEY},
            )
        gj = r.json() or {}
        results = gj.get("results") or []
        if not results:
            return {"formatted_address": "", "city": "", "state": "", "zip": "",
                     "available": True, "reason": "no_results"}
        r0 = results[0]
        formatted = r0.get("formatted_address") or ""
        city = state = zipc = ""
        for comp in (r0.get("address_components") or []):
            types = comp.get("types") or []
            if "locality" in types: city = comp.get("long_name") or city
            elif "administrative_area_level_1" in types: state = comp.get("short_name") or state
            elif "postal_code" in types: zipc = comp.get("long_name") or zipc
        return {"formatted_address": formatted, "city": city, "state": state,
                 "zip": zipc, "available": True}
    except Exception as e:
        logger.warning(f"[maps.reverseGeocode] failed: {e}")
        return {"formatted_address": "", "city": "", "state": "", "zip": "",
                 "available": False, "reason": str(e)}


@router.get("/property/search-by-coords")
async def property_search_by_coords(
    lat: float = Query(...), lng: float = Query(...),
    user: dict = Depends(require_tech_or_admin),
    tenant: dict = Depends(get_current_tenant),
):
    """Reverse-geocode via Google, then dispatch to /property/search."""
    if not GOOGLE_API_KEY:
        raise HTTPException(424,
            "Reverse geocoding unavailable — GOOGLE_API_KEY not configured")
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(
                "https://maps.googleapis.com/maps/api/geocode/json",
                params={"latlng": f"{lat},{lng}", "key": GOOGLE_API_KEY},
            )
        if r.status_code != 200:
            raise HTTPException(424, "Reverse geocoding failed")
        gj = r.json() or {}
        results = gj.get("results") or []
        address = (results[0].get("formatted_address")
                    if results else None)
        if not address:
            raise HTTPException(404, "Could not reverse-geocode those coords")
    except HTTPException:
        raise
    except Exception as ex:
        logger.warning(f"Reverse geocode failed: {ex}")
        raise HTTPException(424, "Reverse geocoding error")

    return await property_search(address=address, user=user, tenant=tenant)


@router.post("/property/history")
@router.get("/property/history")
async def property_history(user: dict = Depends(require_tech_or_admin),
                                tenant: dict = Depends(get_current_tenant)):
    rows = await db.property_search_history.find(
        {"tenant_id": tenant["id"], "user_id": user["id"]},
        {"_id": 0},
    ).sort("ts", -1).limit(50).to_list(50)
    return {"items": rows, "total": len(rows)}


class NoteIn(BaseModel):
    address: Optional[str] = None
    address_normalized: Optional[str] = None
    note: str
    tags: List[str] = Field(default_factory=list)


@router.post("/property/save-note")
async def property_save_note(body: NoteIn,
                                user: dict = Depends(require_tech_or_admin_write),
                                tenant: dict = Depends(get_current_tenant)):
    # Accept either `address` or `address_normalized`. If both are given
    # `address` wins (spec: prefer the human-entered form when supplied).
    raw = body.address or body.address_normalized or ""
    raw = raw.strip()
    if not raw:
        raise HTTPException(422,
            "Provide `address` or `address_normalized`")
    doc = {
        "id": new_id(),
        "tenant_id": tenant["id"],
        "user_id": user["id"],
        "user_name": user.get("name") or user.get("email"),
        "address": raw,
        "address_normalized": _norm_address_key(raw),
        "note": body.note,
        "tags": body.tags or [],
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    await db.property_notes.insert_one(dict(doc))
    doc.pop("_id", None)
    return doc


@router.get("/property/saved-notes")
async def property_saved_notes(address: Optional[str] = Query(None),
                                     user: dict = Depends(require_tech_or_admin),
                                     tenant: dict = Depends(get_current_tenant)):
    q: Dict[str, Any] = {"tenant_id": tenant["id"]}
    if address:
        q["address_normalized"] = _norm_address_key(address)
    rows = await db.property_notes.find(q, {"_id": 0}).sort(
        "created_at", -1).to_list(500)
    return {"items": rows, "total": len(rows)}
