"""F4 · verify pin payload shape + PII invariants against a temporary
approved public_checkins row (seeded then deleted)."""
import asyncio
import json
import re

import requests
from dotenv import dotenv_values
from motor.motor_asyncio import AsyncIOMotorClient

BE = dotenv_values("/app/backend/.env")
BASE = dotenv_values("/app/frontend/.env")["REACT_APP_BACKEND_URL"].rstrip("/")
ROW_ID = "TEST_f4_pin_shape_row"
FORBIDDEN = ("customer_name", "customer_id", "job_id", "raw_lat", "raw_lng",
             "raw_address", "masked_address", "lat_public", "lng_public",
             "completed_at", "tenant_id", "id", "state")
ALLOWED = {"lat", "lng", "service_type", "completed_at_month_year", "area_label"}


async def seed(db):
    tenant = await db.tenants.find_one({"slug": "aquaterra"}, {"_id": 0, "id": 1})
    assert tenant, "aquaterra tenant missing"
    await db.public_checkins.delete_one({"id": ROW_ID})
    await db.public_checkins.insert_one({
        "id": ROW_ID, "tenant_id": tenant["id"], "state": "approved",
        # non-null to dodge the non-sparse tenant_source_unique index
        "source_checkin_id": ROW_ID, "source_job_id": ROW_ID,
        "source": "auto", "service_name": "TEST_Pool Cleaning",
        "customer_name": "TEST Jane Doe", "customer_id": "TEST_cust_1",
        "job_id": "TEST_job_1", "raw_address": "123 TEST St, Peoria AZ",
        "lat": 33.7001, "lng": -112.3001,
        "lat_public": 33.702, "lng_public": -112.298,
        "area_label": "TEST_Vistancia, Peoria",
        "completed_at_month_year": "July 2026",
        "completed_at": "2026-07-10T15:04:05+00:00",
        "approved_at": "2026-07-10T16:00:00+00:00",
        "submitted_at": "2026-07-10T15:30:00+00:00",
    })
    return tenant["id"]


async def cleanup(db):
    await db.public_checkins.delete_one({"id": ROW_ID})


def run_http():
    fails = []
    r = requests.get(f"{BASE}/api/public/checkins/aquaterra/pins", timeout=60)
    print("pins status", r.status_code)
    body = r.json()
    raw = r.text
    print("count =", body.get("count"))
    pins = body.get("pins") or []
    if not pins:
        fails.append("pins still empty after seeding approved row")
    else:
        p = next((x for x in pins if x.get("service_type") == "TEST_Pool Cleaning"), None)
        if not p:
            fails.append("seeded row not returned in pins")
        else:
            print("pin =", json.dumps(p))
            extra = set(p) - ALLOWED
            missing = ALLOWED - set(p)
            if extra:
                fails.append(f"pin has extra keys: {extra}")
            if missing:
                fails.append(f"pin missing keys: {missing}")
            if p.get("lat") == 33.7001 or p.get("lng") == -112.3001:
                fails.append("RAW coords leaked into pin (not obfuscated)")
            if p.get("completed_at_month_year") != "July 2026":
                fails.append(f"bad month_year {p.get('completed_at_month_year')}")
    for k in FORBIDDEN:
        if f'"{k}"' in raw:
            fails.append(f"PII/internal key '{k}' present in pins body")
    if "TEST Jane Doe" in raw or "123 TEST St" in raw:
        fails.append("customer name/address value leaked in pins body")

    # map.html must also carry the pin but no PII
    h = requests.get(f"{BASE}/api/public/checkins/aquaterra/map.html", timeout=60)
    print("map.html status", h.status_code, len(h.text), "bytes")
    ht = h.text
    if "TEST_Pool Cleaning" not in ht:
        fails.append("seeded pin not rendered into map.html")
    for bad in ("TEST Jane Doe", "TEST_cust_1", "TEST_job_1", "123 TEST St",
                "33.7001", "-112.3001"):
        if bad in ht:
            fails.append(f"PII/raw value '{bad}' leaked in map.html")
    m = re.search(r'<script type="application/ld\+json"[^>]*>(.*?)</script>', ht, re.S)
    ld = json.loads(m.group(1))
    print("ld @type", ld.get("@type"), "areaServed", len(ld.get("areaServed") or []),
          "makesOffer", len(ld.get("makesOffer") or []))
    if ld.get("@type") != "LocalBusiness":
        fails.append("JSON-LD @type != LocalBusiness")
    if not ld.get("areaServed"):
        fails.append("JSON-LD areaServed empty despite a pin with area_label")
    if not ld.get("makesOffer"):
        fails.append("JSON-LD makesOffer empty despite a pin with service_type")
    return fails


async def main():
    c = AsyncIOMotorClient(BE["MONGO_URL"])
    db = c[BE["DB_NAME"]]
    try:
        await seed(db)
        fails = await asyncio.get_event_loop().run_in_executor(None, run_http)
    finally:
        await cleanup(db)
        print("cleanup done (TEST row deleted)")
    print("=" * 50)
    if fails:
        for f in fails:
            print("FAIL:", f)
    else:
        print("ALL PIN-SHAPE / PII CHECKS PASSED")


asyncio.run(main())
