"""Reviews Phase 1 · Feb 2026 — seed platforms + sample reviews.

Idempotent. Called from ``server.py::_background_seed`` on startup so
demo tenants have something the widget can render immediately. Uses the
same upsert-safe pattern as ``comms_seed/seed_comms.py``.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List

from config import db, logger
from utils import new_id


DEMO_TENANT_SLUG = "aquaterra"


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


PLATFORM_SEED: List[Dict[str, Any]] = [
    {"platform": "google",   "display_name": "Google", "sort_order": 1,
     "review_url": "https://search.google.com/local/writereview?placeid=demo-aquaterra"},
    {"platform": "facebook", "display_name": "Facebook", "sort_order": 2,
     "review_url": "https://www.facebook.com/demo.aquaterra/reviews"},
    {"platform": "yelp",     "display_name": "Yelp", "sort_order": 3,
     "review_url": "https://www.yelp.com/writeareview/biz/demo-aquaterra"},
    {"platform": "bbb",      "display_name": "BBB", "sort_order": 4,
     "review_url": "https://www.bbb.org/us/az/peoria/profile/demo-aquaterra/customer-reviews"},
]


# In-house original copy — reviewed against the marketing_studio.py
# blacklist scan on save (see tests).
SAMPLE_REVIEWS: List[Dict[str, Any]] = [
    {
        "star_rating": 5,
        "review_text": ("Third season with them and I keep telling neighbours. "
                        "Weekly reports come with photos, the tech texts if he "
                        "spots anything, and the pool has never looked better."),
        "reviewer_name": "Priya M.",
        "platform": "google",
        "tech_email": "mike@aquaterra.com",
    },
    {
        "star_rating": 5,
        "review_text": ("Landscape team redid our front yard on a tight timeline "
                        "before we hosted family. Careful with the irrigation "
                        "lines, honest about what they replaced, and left the "
                        "worksite spotless."),
        "reviewer_name": "Dan R.",
        "platform": "facebook",
        "tech_email": "carlos@aquaterra.com",
    },
    {
        "star_rating": 5,
        "review_text": ("Switched over after our previous company let things "
                        "slide. Onboarding call caught two panel issues nobody "
                        "had mentioned in years — fixed in the same visit."),
        "reviewer_name": "Sam T.",
        "platform": "google",
        "tech_email": "mike@aquaterra.com",
    },
    {
        "star_rating": 4,
        "review_text": ("Solid service. One missed visit last month bumped us "
                        "from a 5 to a 4, but they credited the month without "
                        "us having to ask."),
        "reviewer_name": "Elena V.",
        "platform": "yelp",
        "tech_email": "mike@aquaterra.com",
    },
]


async def _upsert_platform(tenant_id: str, p: Dict[str, Any]) -> str:
    key = {"tenant_id": tenant_id, "platform": p["platform"],
           "custom_slug": p.get("custom_slug")}
    existing = await db.tenant_review_platforms.find_one(key, {"_id": 1, "id": 1})
    now_s = _iso(datetime.now(timezone.utc))
    doc = {
        "tenant_id": tenant_id,
        "platform": p["platform"],
        "display_name": p["display_name"],
        "review_url": p["review_url"],
        "is_active": p.get("is_active", True),
        "sort_order": p.get("sort_order", 0),
        "custom_slug": p.get("custom_slug"),
        "updated_at": now_s,
    }
    if existing:
        await db.tenant_review_platforms.update_one({"_id": existing["_id"]}, {"$set": doc})
        return "updated"
    doc["id"] = new_id()
    doc["created_at"] = now_s
    await db.tenant_review_platforms.insert_one(doc)
    return "inserted"


async def _upsert_sample_review(tenant_id: str, tech_email_to_id: Dict[str, str],
                                 idx: int, r: Dict[str, Any]) -> str:
    """Sample reviews are keyed by (tenant_id, reviewer_name,
    review_text[:40]) so re-seeding doesn't duplicate them."""
    text_key = (r.get("review_text") or "")[:40]
    key = {"tenant_id": tenant_id, "source": "manual_entry",
           "reviewer_name": r["reviewer_name"], "_seed_key": text_key}
    existing = await db.reviews.find_one(key, {"_id": 1})
    now_s = _iso(datetime.now(timezone.utc) - timedelta(days=idx * 4))
    tech_id = tech_email_to_id.get(r.get("tech_email") or "", None)
    doc = {
        "tenant_id": tenant_id,
        "source": "manual_entry",
        "source_review_id": None,
        "review_request_id": None,
        "customer_id": None,
        "technician_id": tech_id,
        "star_rating": r["star_rating"],
        "review_text": r["review_text"],
        "reviewer_name": r["reviewer_name"],
        "platform": r["platform"],
        "is_public": True,
        "visible_on_widget": r["star_rating"] >= 4,
        "admin_response": None,
        "admin_response_at": None,
        "created_at": now_s,
        "_seed_key": text_key,
    }
    if existing:
        await db.reviews.update_one({"_id": existing["_id"]}, {"$set": doc})
        return "updated"
    doc["id"] = new_id()
    await db.reviews.insert_one(doc)
    return "inserted"


async def _find_tech_id_for_email(email: str) -> str:
    """Resolve a technician by their user's email address."""
    user = await db.users.find_one({"email": email.lower()}, {"_id": 0, "id": 1})
    if not user:
        return ""
    tech = await db.technicians.find_one({"user_id": user["id"]}, {"_id": 0, "id": 1})
    if tech:
        return tech["id"]
    # Fall back to name-match (older seeds stored the tech without a user_id link).
    tech = await db.technicians.find_one(
        {"$or": [{"email": email.lower()}, {"name": {"$regex": email.split("@")[0], "$options": "i"}}]},
        {"_id": 0, "id": 1},
    )
    return (tech or {}).get("id") or ""


async def seed_reviews() -> Dict[str, Any]:
    """Idempotent seed. Runs against every active tenant whose slug is in
    ``DEMO_TENANT_SLUG``; skips silently if the demo tenant is absent."""
    tenants = await db.tenants.find(
        {"slug": DEMO_TENANT_SLUG, "active": True}, {"_id": 0},
    ).to_list(5)
    if not tenants:
        logger.info("[reviews_seed] demo tenant absent; skipping")
        return {"platforms": 0, "reviews": 0}

    tech_map: Dict[str, str] = {}
    for email in {r.get("tech_email") for r in SAMPLE_REVIEWS if r.get("tech_email")}:
        tid = await _find_tech_id_for_email(email or "")
        if tid:
            tech_map[email or ""] = tid

    platforms_touched = reviews_touched = 0
    for tenant in tenants:
        tid = tenant["id"]
        for p in PLATFORM_SEED:
            await _upsert_platform(tid, p)
            platforms_touched += 1
        for idx, r in enumerate(SAMPLE_REVIEWS):
            await _upsert_sample_review(tid, tech_map, idx, r)
            reviews_touched += 1

    logger.info(f"[reviews_seed] platforms touched={platforms_touched} "
                f"sample_reviews touched={reviews_touched}")
    return {"platforms": platforms_touched, "reviews": reviews_touched}


if __name__ == "__main__":
    import asyncio
    from dotenv import load_dotenv
    from pathlib import Path
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    print(asyncio.run(seed_reviews()))
