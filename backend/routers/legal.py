"""Legal documents CMS (Terms of Service, Privacy, etc.) — served both to
authenticated customers (portal) and public consumers (signup pages).

Documents live in `db.legal_documents` and are seeded on backend startup
(idempotent) via `ensure_seeded()`.
"""
from typing import Optional
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Depends

from config import db, logger
from utils import now_iso, new_id, require_admin, get_current_user
from models import BaseModel

router = APIRouter()


class LegalDocIn(BaseModel):
    title: Optional[str] = None
    body_markdown: Optional[str] = None
    effective_date: Optional[str] = None


class TosAckIn(BaseModel):
    slug: str
    version: int


# ─── seed data ───────────────────────────────────────────────────────────────
POOL_TOS_SLUG = "terms-of-service-pool-maintenance"
POOL_TOS_TITLE = "Pool Maintenance Terms of Service"
POOL_TOS_EFFECTIVE = "2026-07-13"

# Verbatim text from https://poolandlandscapingofvistancia.com/pool-landscaping-of-vistancia/documents/terms-of-service/
POOL_TOS_MARKDOWN = """## Pool Service Terms

### 1. Service
Pool & Landscaping of Vistancia LLC provides weekly and twice-per-week pool/spa maintenance. Rate includes skimming, brushing, emptying baskets, checking chemicals and balancing, and checking equipment. Standard service includes chlorine tabs, liquid chlorine, soda ash, and acid.

**There will be a la carte pricing for shock treatments, algaecides, phosphate treatments, clarifiers, and enzymes as needed.**

Additional time cleaning the pool/spa beyond standard service may result in additional clean-up charges (e.g. Clean Up during Monsoon Season, Landscaping Debris & Fall Season leaves). Service days of the week are not guaranteed and are subject to change to fit our routing needs.

### 2. New Service
When a new account is established, we require a filter inspection/clean at a rate of $125 (unless it is a new build).

### 3. Additional Maintenance

**Blu-Ray XL:** Blu-Ray will be installed for the swim season. The treatment cost is $130 billed in December and installed in March. Blu-Ray XL is a 7-in-1 product and lasts up to 6 months:

- Flocculant
- Oxidation Catalyst
- Phosphate Neutralizer
- pH Stabilizer
- Lignin Neutralizer
- Water Polisher
- (COD) Reducer

**Filter Cleaning and Inspections:** performed quarterly at $125 per service.

**Salt Cell Cleanings:** $55 and performed at the same time as filter cleaning.

If you choose our all-inclusive Premier service plan, Blu-Ray and Filter Cleans are included at no additional charge.

### 4. Billing
We offer 4 billing cycles, and we bill in advance for service. Options for billing dates are:

- 1st Friday
- 2nd Friday
- 3rd Friday
- 4th Friday

We do require a credit card or ACH on file — it will be run once the bill is generated in the system. You can add a card or ACH on file for auto-billing in your client portal. If a bill goes 10 days past due, there is a $10 late fee that will be applied. Service will be interrupted if the billing lapses for more than 30 days. **All prices are subject to change with written notice.**

### 5. Communication
We send out email service reports after every service. This report will contain important information regarding challenges we see and suggested solutions. We also send out a newsletter to keep all clients informed of any important news and customer education. You must have an email on file and a cell phone to make sure you receive these important system notifications to keep you up to date. Email communications will be sent from `brian@plofv.com` — please make sure this address is not blocked on your spam filter.

### 6. Missed Service Calls & Holidays
In the event your service falls on a holiday, service will be rescheduled. In the event of rain or lightning on your service day, the pool/spa may not be serviced on your service day for safety reasons. If service or partial services are rendered, service will not be rescheduled. If you believe that a service call was missed for reasons other than those stated previously, please contact Pool & Landscaping of Vistancia LLC within 24 hours, and your service will be made up. Every year we take our vacation time during non-crucial seasons of the year. We will be on vacation the week of Thanksgiving and Christmas/New Year. Every year 4 months have 5 weeks — we only bill you for 4 weeks in those months to allow for these vacation days. During these off weeks, the customer will be responsible for the pool/spa.

### 7. Repairs
Repairs under $100 will be performed without prior notification. Repairs above $100 will require authorization from the customer via signature. Any equipment purchased will not be refunded if repair is canceled after payment has been made — you will receive an account credit minus labor cost with Pool & Landscaping of Vistancia LLC.

### 8. Termination
You are not entering a service agreement but rather setting the proper expectations and acknowledging you accept all the stated terms of service. Service can be terminated at any time by either party. We strongly believe in our service quality and if you are ever unsatisfied in any way you have the right to terminate service and any charges will be prorated up to the last date serviced.

---

### Disclaimer
Pool & Landscaping of Vistancia LLC will not be responsible for any damage to property due to acts of nature, fire, vandalism, misuse, or abuse. Pool & Landscaping of Vistancia LLC is not responsible for the performance of any chemicals it does not sell. CUSTOMER should be aware of the normal deterioration of equipment that occurs over time due to exposure to chemicals and sunlight. Due to these factors, Pool & Landscaping of Vistancia LLC recommends other annual services (e.g., an annual tune-up of equipment, filter cleanings, etc.) above normal maintenance. The CUSTOMER is responsible for maintaining the correct water level and keeping trees and plants trimmed away from the pool/spa and equipment. Pool & Landscaping of Vistancia LLC is not responsible for any damages or deterioration caused by the failure of CUSTOMER to perform other services recommended by Pool & Landscaping of Vistancia LLC or by the failure of CUSTOMER to properly maintain pool and equipment between visits. If you have any complaints or concerns regarding the frequency or completeness of service, you must call Pool & Landscaping of Vistancia LLC within 24 hours after the service occurred or was scheduled to have occurred.
"""


async def ensure_seeded() -> None:
    """Insert the pool-maintenance ToS the first time we boot with an empty collection."""
    existing = await db.legal_documents.find_one({"slug": POOL_TOS_SLUG}, {"_id": 0, "id": 1})
    if existing:
        return
    doc = {
        "id": new_id(),
        "slug": POOL_TOS_SLUG,
        "title": POOL_TOS_TITLE,
        "body_markdown": POOL_TOS_MARKDOWN,
        "effective_date": POOL_TOS_EFFECTIVE,
        "version": 1,
        "updated_at": now_iso(),
        "created_at": now_iso(),
    }
    await db.legal_documents.insert_one(doc)
    logger.info(f"Seeded legal document {POOL_TOS_SLUG!r} v1")


def _public(doc: dict) -> dict:
    d = dict(doc)
    d.pop("_id", None)
    return d


# ─── public read ─────────────────────────────────────────────────────────────
@router.get("/legal/{slug}")
async def get_legal_doc(slug: str):
    """Public — anyone can read the current version of a legal document."""
    doc = await db.legal_documents.find_one({"slug": slug}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Not found")
    return _public(doc)


# ─── admin CRUD ─────────────────────────────────────────────────────────────
@router.get("/legal")
async def list_legal_docs(admin: dict = Depends(require_admin)):
    docs = await db.legal_documents.find({}, {"_id": 0}).sort("slug", 1).to_list(200)
    return docs


@router.put("/legal/{slug}")
async def update_legal_doc(slug: str, body: LegalDocIn, admin: dict = Depends(require_admin)):
    existing = await db.legal_documents.find_one({"slug": slug}, {"_id": 0})
    if not existing:
        raise HTTPException(404, "Not found")
    upd = {k: v for k, v in body.dict().items() if v is not None}
    upd["version"] = int(existing.get("version", 1)) + 1
    upd["updated_at"] = now_iso()
    await db.legal_documents.update_one({"slug": slug}, {"$set": upd})
    doc = await db.legal_documents.find_one({"slug": slug}, {"_id": 0})
    return _public(doc)


# ─── customer acknowledgement ─────────────────────────────────────────────────
@router.post("/portal/terms/acknowledge")
async def acknowledge_terms(body: TosAckIn, user: dict = Depends(get_current_user)):
    if user.get("role") != "customer":
        raise HTTPException(403, "Customers only")
    cid = user.get("customer_id")
    if not cid:
        raise HTTPException(400, "No customer profile linked to user")
    doc = await db.legal_documents.find_one({"slug": body.slug}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Legal doc not found")
    entry = {
        "slug": body.slug,
        "version": int(body.version),
        "acked_at": now_iso(),
    }
    # Idempotent — replace any earlier ack for this slug so latest ack wins.
    await db.customers.update_one(
        {"id": cid},
        {"$pull": {"tos_acknowledgements": {"slug": body.slug}}},
    )
    await db.customers.update_one(
        {"id": cid},
        {"$push": {"tos_acknowledgements": entry}},
    )
    return {"ok": True, "ack": entry}


@router.get("/portal/terms/status")
async def terms_status(user: dict = Depends(get_current_user), slug: str = POOL_TOS_SLUG):
    """Portal-side check — does the current customer have an ack for the latest version?"""
    if user.get("role") != "customer":
        return {"acknowledged": False, "current_version": None}
    doc = await db.legal_documents.find_one({"slug": slug}, {"_id": 0}) or {}
    current_version = int(doc.get("version", 0))
    cid = user.get("customer_id")
    if not cid:
        return {"acknowledged": False, "current_version": current_version, "slug": slug}
    customer = await db.customers.find_one({"id": cid}, {"_id": 0, "tos_acknowledgements": 1}) or {}
    for ack in customer.get("tos_acknowledgements") or []:
        if ack.get("slug") == slug and int(ack.get("version", 0)) >= current_version:
            return {
                "acknowledged": True,
                "current_version": current_version,
                "acked_at": ack.get("acked_at"),
                "slug": slug,
            }
    return {"acknowledged": False, "current_version": current_version, "slug": slug}
