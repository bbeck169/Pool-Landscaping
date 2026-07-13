from fastapi import APIRouter, HTTPException, Depends
from typing import Optional
import time
import re
import httpx

from config import db, OPENWEB_NINJA_API_KEY
from utils import now_iso, new_id, get_current_user, require_admin
from models import D2DKnockIn, D2DKnockUpdate

router = APIRouter()

DISPOSITIONS = {"not_home", "not_interested", "callback", "interested", "sold"}
OWN_BASE = "https://api.openwebninja.com/realtime-zillow-data"
LEAD_DISPOS = {"interested", "sold"}  # dispositions that create a sales lead


def _rep(user: dict):
    """Attribution identity for the sales rep (technician_id when present, else user id)."""
    return user.get("technician_id") or user.get("id"), user.get("name", "")


def _require_sales(user: dict):
    if user.get("role") not in ("admin", "technician"):
        raise HTTPException(403, "Not allowed")


async def _sync_lead(knock: dict):
    """Mirror interested/sold knocks into the shared Leads pipeline (source Door-to-door)."""
    if knock.get("disposition") not in LEAD_DISPOS:
        return knock.get("lead_id")
    lead_id = knock.get("lead_id")
    fields = {
        "name": knock.get("name") or f"Prospect @ {knock.get('address') or 'door'}",
        "phone": knock.get("phone", ""), "notes": knock.get("notes", ""),
        "source": "Door-to-door", "disposition": knock.get("disposition"),
        "knock_id": knock["id"], "tech_id": knock.get("tech_id"), "tech_name": knock.get("tech_name"),
        "address": knock.get("address", ""), "lat": knock.get("lat"), "lng": knock.get("lng"),
    }
    if lead_id and await db.leads.find_one({"id": lead_id}):
        await db.leads.update_one({"id": lead_id}, {"$set": fields})
        return lead_id
    lead_id = new_id()
    await db.leads.insert_one({**fields, "id": lead_id, "status": "new", "est_value": 0.0,
                               "created_at": now_iso(), "created_by": knock.get("tech_id")})
    await db.d2d_knocks.update_one({"id": knock["id"]}, {"$set": {"lead_id": lead_id}})
    return lead_id


@router.post("/d2d/knocks")
async def create_knock(body: D2DKnockIn, user: dict = Depends(get_current_user)):
    _require_sales(user)
    if body.disposition not in DISPOSITIONS:
        raise HTTPException(400, "Invalid disposition")
    tech_id, tech_name = _rep(user)
    knock = body.dict()
    knock.update({"id": new_id(), "tech_id": tech_id, "tech_name": tech_name,
                  "converted": False, "customer_id": None, "lead_id": None,
                  "created_at": now_iso(), "updated_at": now_iso()})
    await db.d2d_knocks.insert_one(knock)
    knock.pop("_id", None)
    knock["lead_id"] = await _sync_lead(knock)
    return knock


@router.get("/d2d/knocks")
async def list_knocks(user: dict = Depends(get_current_user), tech_id: Optional[str] = None):
    _require_sales(user)
    q = {}
    if user.get("role") == "technician":
        q["tech_id"] = user.get("technician_id") or user.get("id")  # techs see only their own
    elif tech_id:
        q["tech_id"] = tech_id
    return await db.d2d_knocks.find(q, {"_id": 0}).sort("created_at", -1).to_list(2000)


@router.get("/d2d/open-leads")
async def open_leads(user: dict = Depends(get_current_user)):
    """Open CRM leads (not won/lost) as D2D map pins."""
    _require_sales(user)
    leads = await db.leads.find({"status": {"$nin": ["won", "lost"]}}, {"_id": 0}).to_list(3000)
    out = [{
        "id": l["id"],
        "name": l.get("name", ""),
        "address": l.get("address", ""),
        "lat": l.get("lat"),
        "lng": l.get("lng"),
        "phone": l.get("phone", ""),
        "status": l.get("status", "new"),
        "source": l.get("source", ""),
        "est_value": l.get("est_value", 0),
        "notes": l.get("notes", ""),
    } for l in leads]
    return {"count": len(out), "leads": out}


def _norm_sold(p: dict) -> dict:
    ds = p.get("dateSold")
    return {
        "zpid": str(p.get("zpid") or p.get("id") or ""),
        "address": p.get("address") or p.get("streetAddress") or "",
        "lat": p.get("latitude"),
        "lng": p.get("longitude"),
        "price": p.get("price"),
        "zestimate": p.get("zestimate"),
        "beds": p.get("bedrooms"),
        "baths": p.get("bathrooms"),
        "sqft": p.get("livingArea"),
        "home_type": p.get("homeType"),
        "date_sold": int(ds) if isinstance(ds, (int, float)) else None,
        "image": p.get("imgSrc"),
        "detail_url": p.get("detailUrl"),
    }


@router.get("/d2d/sold-leads")
async def sold_leads(zip: str, days: int = 30, page: int = 1,
                     min_price: Optional[float] = None, max_price: Optional[float] = None,
                     min_beds: Optional[int] = None, user: dict = Depends(get_current_user)):
    """Recently-sold homes in a ZIP (Zillow via OpenWeb Ninja) as canvassing targets."""
    _require_sales(user)
    zip = (zip or "").strip()
    if not re.fullmatch(r"\d{5}", zip):
        raise HTTPException(400, "Enter a valid 5-digit ZIP code")
    if not OPENWEB_NINJA_API_KEY:
        raise HTTPException(424, "Zillow data provider not configured")
    params = {"location": zip, "home_status": "RECENTLY_SOLD", "sort": "DEFAULT", "page": max(1, page)}
    try:
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.get(f"{OWN_BASE}/search", params=params, headers={"x-api-key": OPENWEB_NINJA_API_KEY})
    except httpx.HTTPError:
        raise HTTPException(424, "Could not reach the Zillow data provider")
    if r.status_code == 429:
        raise HTTPException(429, "Zillow provider rate limit reached — try again shortly")
    if r.status_code >= 400:
        raise HTTPException(424, "Zillow data provider error")
    data = (r.json() or {}).get("data") or []
    cutoff_ms = (time.time() - days * 86400) * 1000 if days else 0
    props = []
    for p in data:
        if not (p.get("latitude") and p.get("longitude")):
            continue
        ds = p.get("dateSold")
        if cutoff_ms and isinstance(ds, (int, float)) and ds < cutoff_ms:
            continue
        price = p.get("price")
        if min_price is not None and (price is None or price < min_price):
            continue
        if max_price is not None and (price is None or price > max_price):
            continue
        if min_beds is not None and (p.get("bedrooms") is None or p.get("bedrooms") < min_beds):
            continue
        props.append(_norm_sold(p))
    # Flag zpids already logged as knocks so the UI can dedupe pins
    zpids = [p["zpid"] for p in props if p["zpid"]]
    logged = set()
    skipped = set()
    me = _rep(user)[0]
    if zpids:
        async for k in db.d2d_knocks.find({"zpid": {"$in": zpids}}, {"_id": 0, "zpid": 1}):
            if k.get("zpid"):
                logged.add(k["zpid"])
        async for s in db.d2d_skips.find({"zpid": {"$in": zpids}, "tech_id": me}, {"_id": 0, "zpid": 1}):
            if s.get("zpid"):
                skipped.add(s["zpid"])
    for p in props:
        p["logged"] = p["zpid"] in logged
        p["skipped"] = p["zpid"] in skipped
    props.sort(key=lambda x: x.get("date_sold") or float("inf"))  # oldest sold first
    return {"zip": zip, "days": days, "count": len(props), "properties": props,
            "filters": {"min_price": min_price, "max_price": max_price, "min_beds": min_beds}}


@router.post("/d2d/skip/{zpid}")
async def skip_sold(zpid: str, user: dict = Depends(get_current_user)):
    """Mark a recently-sold home as 'walked/passed' for this rep (greys it out on the map)."""
    _require_sales(user)
    me = _rep(user)[0]
    await db.d2d_skips.update_one(
        {"zpid": zpid, "tech_id": me},
        {"$setOnInsert": {"zpid": zpid, "tech_id": me, "created_at": now_iso()}},
        upsert=True,
    )
    return {"zpid": zpid, "skipped": True}


@router.delete("/d2d/skip/{zpid}")
async def unskip_sold(zpid: str, user: dict = Depends(get_current_user)):
    _require_sales(user)
    me = _rep(user)[0]
    await db.d2d_skips.delete_one({"zpid": zpid, "tech_id": me})
    return {"zpid": zpid, "skipped": False}


async def _get_owned_knock(kid: str, user: dict):
    knock = await db.d2d_knocks.find_one({"id": kid}, {"_id": 0})
    if not knock:
        raise HTTPException(404, "Knock not found")
    if user.get("role") == "technician" and knock.get("tech_id") not in (user.get("technician_id"), user.get("id")):
        raise HTTPException(403, "Not your knock")
    return knock


@router.put("/d2d/knocks/{kid}")
async def update_knock(kid: str, body: D2DKnockUpdate, user: dict = Depends(get_current_user)):
    _require_sales(user)
    await _get_owned_knock(kid, user)
    upd = {k: v for k, v in body.dict().items() if v is not None}
    if "disposition" in upd and upd["disposition"] not in DISPOSITIONS:
        raise HTTPException(400, "Invalid disposition")
    if upd:
        upd["updated_at"] = now_iso()
        await db.d2d_knocks.update_one({"id": kid}, {"$set": upd})
    knock = await db.d2d_knocks.find_one({"id": kid}, {"_id": 0})
    knock["lead_id"] = await _sync_lead(knock)
    return knock


@router.delete("/d2d/knocks/{kid}")
async def delete_knock(kid: str, user: dict = Depends(get_current_user)):
    _require_sales(user)
    knock = await _get_owned_knock(kid, user)
    await db.d2d_knocks.delete_one({"id": kid})
    if knock.get("lead_id"):
        await db.leads.delete_one({"id": knock["lead_id"], "status": {"$ne": "won"}})
    return {"ok": True}


@router.post("/d2d/knocks/{kid}/convert")
async def convert_knock(kid: str, user: dict = Depends(get_current_user)):
    """Turn a door-to-door lead into a customer and mark it converted."""
    from routers.leads import _ensure_customer_from_lead
    _require_sales(user)
    knock = await _get_owned_knock(kid, user)
    if knock.get("disposition") not in LEAD_DISPOS:
        raise HTTPException(400, "Only interested/sold doors can convert to a customer")
    lead_id = await _sync_lead(knock)
    lead = await db.leads.find_one({"id": lead_id}, {"_id": 0})
    cust = await _ensure_customer_from_lead(lead)
    await db.leads.update_one({"id": lead_id}, {"$set": {"status": "won", "converted": {"type": "customer", "id": cust["id"]}}})
    await db.d2d_knocks.update_one({"id": kid}, {"$set": {"converted": True, "customer_id": cust["id"], "updated_at": now_iso()}})
    return cust


async def _aggregate():
    knocks = await db.d2d_knocks.find({}, {"_id": 0}).to_list(5000)
    # A knock counts as converted if flagged, or its linked lead was won/converted.
    lead_ids = [k["lead_id"] for k in knocks if k.get("lead_id")]
    conv_leads = set()
    if lead_ids:
        async for l in db.leads.find({"id": {"$in": lead_ids}, "converted": {"$exists": True}}, {"_id": 0, "id": 1}):
            conv_leads.add(l["id"])
    reps: dict = {}
    for k in knocks:
        r = reps.setdefault(k.get("tech_id"), {
            "tech_id": k.get("tech_id"), "tech_name": k.get("tech_name") or "Unknown",
            "knocks": 0, "not_home": 0, "not_interested": 0, "callback": 0,
            "interested": 0, "sold": 0, "leads": 0, "conversions": 0,
        })
        r["knocks"] += 1
        d = k.get("disposition", "not_home")
        if d in r:
            r[d] += 1
        if d in LEAD_DISPOS:
            r["leads"] += 1
        if k.get("converted") or (k.get("lead_id") in conv_leads):
            r["conversions"] += 1
    for r in reps.values():
        r["conversion_rate"] = round((r["conversions"] / r["leads"] * 100) if r["leads"] else 0, 1)
    return list(reps.values())


@router.get("/d2d/report")
async def d2d_report(admin: dict = Depends(require_admin)):
    reps = await _aggregate()
    reps.sort(key=lambda r: (-r["conversions"], -r["sold"], -r["knocks"]))
    totals = {"knocks": 0, "leads": 0, "sold": 0, "conversions": 0}
    for r in reps:
        for k in totals:
            totals[k] += r[k]
    totals["conversion_rate"] = round((totals["conversions"] / totals["leads"] * 100) if totals["leads"] else 0, 1)
    return {"totals": totals, "reps": reps}


@router.get("/d2d/leaderboard")
async def d2d_leaderboard(user: dict = Depends(get_current_user)):
    _require_sales(user)
    reps = await _aggregate()
    reps.sort(key=lambda r: (-r["sold"], -r["conversions"], -r["knocks"]))
    me = user.get("technician_id") or user.get("id")
    for i, r in enumerate(reps):
        r["rank"] = i + 1
        r["is_me"] = r["tech_id"] == me
    return reps
