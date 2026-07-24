"""Feb-2026 · Phase 22 — Citation Builder / Local SEO Listings Tracker.

Native alternative to BrightLocal's Citation Builder — tracks a business's
listings across ~50 directories, surfaces NAP (Name/Address/Phone) drift
against the tenant's ``business_card``, and gives admins a weighted
completeness score so they can prioritise which directories to claim
next.

Collections
-----------
* ``citation_directories`` — SYSTEM-WIDE master list of directories.
  Seeded on boot from ``CITATION_DIRECTORY_SEED`` and safe to re-seed
  (upserts by slug so weights / URLs can drift over time without
  duplicating rows).

* ``tenant_citations`` — PER-TENANT PER-DIRECTORY state row. Unique
  compound index on ``(tenant_id, directory_id)``. Holds status,
  listing URL, notes, a frozen ``data_snapshot`` from the last
  verification, and drift flags.

NAP drift
---------
Each verification freezes the current business_card's NAP fields into
``tenant_citations.data_snapshot``. On boot (see
``run_citations_seed_and_drift``) we recompute drift by comparing that
snapshot against the tenant's CURRENT business_card. Any mismatch flips
``nap_drift_detected=True`` and demotes status to ``needs_update`` (only
when the row is currently ``live`` — we never demote ``rejected`` /
``n/a`` etc). A weekly cron can hit the same function.

v1 scope explicitly excludes:
* Auto-submission of citations (needs BrightLocal or paid provider).
* Live crawling to detect if a listing goes offline (rate-limit budget).
Both are called out to the caller in the PRD.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from config import db, logger
from utils import get_current_user, now_iso, new_id

router = APIRouter(tags=["Citation Builder"])


# ─────────────────────────────────────────────────────────────────────
# Master directory seed (~50 entries).
#
# Weights are 1..10 (10 = mandatory / highest SEO signal). Categories:
#   "search" | "maps" | "social" | "local" | "industry" | "reviews"
# ``requires_manual_verification`` is a hint for the UI ("we cannot
# auto-detect if you're listed here") — we treat every directory as
# manual for v1 because no auto-submit provider is wired.
# ─────────────────────────────────────────────────────────────────────
CITATION_DIRECTORY_SEED: List[Dict[str, Any]] = [
    # Search engines (5)
    {"slug": "google-business-profile", "name": "Google Business Profile",
     "url": "https://business.google.com", "category": "search", "weight": 10,
     "industry_tags": []},
    {"slug": "bing-places", "name": "Bing Places for Business",
     "url": "https://www.bingplaces.com", "category": "search", "weight": 9,
     "industry_tags": []},
    {"slug": "apple-maps", "name": "Apple Business Connect",
     "url": "https://businessconnect.apple.com", "category": "search",
     "weight": 9, "industry_tags": []},
    {"slug": "duckduckgo", "name": "DuckDuckGo Business",
     "url": "https://duckduckgo.com", "category": "search", "weight": 6,
     "industry_tags": []},
    {"slug": "yandex", "name": "Yandex Business",
     "url": "https://yandex.com/business", "category": "search", "weight": 5,
     "industry_tags": []},

    # Maps (4)
    {"slug": "google-maps", "name": "Google Maps",
     "url": "https://maps.google.com", "category": "maps", "weight": 10,
     "industry_tags": []},
    {"slug": "waze", "name": "Waze for Business",
     "url": "https://www.waze.com/business", "category": "maps", "weight": 7,
     "industry_tags": []},
    {"slug": "tomtom", "name": "TomTom Places",
     "url": "https://www.tomtom.com", "category": "maps", "weight": 5,
     "industry_tags": []},
    {"slug": "here-maps", "name": "HERE Maps",
     "url": "https://www.here.com", "category": "maps", "weight": 5,
     "industry_tags": []},

    # Social (4)
    {"slug": "facebook-business", "name": "Facebook Business Page",
     "url": "https://business.facebook.com", "category": "social", "weight": 9,
     "industry_tags": []},
    {"slug": "instagram-business", "name": "Instagram Business",
     "url": "https://business.instagram.com", "category": "social", "weight": 8,
     "industry_tags": []},
    {"slug": "linkedin-business", "name": "LinkedIn Company Page",
     "url": "https://www.linkedin.com/company", "category": "social",
     "weight": 7, "industry_tags": []},
    {"slug": "nextdoor", "name": "Nextdoor for Business",
     "url": "https://business.nextdoor.com", "category": "social",
     "weight": 9, "industry_tags": ["local-services"]},

    # Local citations (10)
    {"slug": "yelp", "name": "Yelp for Business",
     "url": "https://biz.yelp.com", "category": "local", "weight": 9,
     "industry_tags": []},
    {"slug": "yellowpages", "name": "YellowPages",
     "url": "https://www.yellowpages.com", "category": "local", "weight": 7,
     "industry_tags": []},
    {"slug": "superpages", "name": "Superpages",
     "url": "https://www.superpages.com", "category": "local", "weight": 6,
     "industry_tags": []},
    {"slug": "manta", "name": "Manta",
     "url": "https://www.manta.com", "category": "local", "weight": 6,
     "industry_tags": []},
    {"slug": "foursquare", "name": "Foursquare for Business",
     "url": "https://business.foursquare.com", "category": "local",
     "weight": 7, "industry_tags": []},
    {"slug": "mapquest", "name": "MapQuest Business",
     "url": "https://www.mapquest.com", "category": "local", "weight": 6,
     "industry_tags": []},
    {"slug": "angies-list", "name": "Angi (Angie's List)",
     "url": "https://www.angi.com", "category": "local", "weight": 9,
     "industry_tags": ["home-services", "landscaping", "pool"]},
    {"slug": "thumbtack", "name": "Thumbtack",
     "url": "https://www.thumbtack.com", "category": "local", "weight": 8,
     "industry_tags": ["home-services", "landscaping", "pool"]},
    {"slug": "homeadvisor", "name": "HomeAdvisor",
     "url": "https://www.homeadvisor.com", "category": "local", "weight": 8,
     "industry_tags": ["home-services", "landscaping", "pool"]},
    {"slug": "porch", "name": "Porch",
     "url": "https://www.porch.com", "category": "local", "weight": 7,
     "industry_tags": ["home-services", "landscaping"]},

    # Industry (pool / landscaping / home services) (14)
    {"slug": "houzz", "name": "Houzz Professional",
     "url": "https://www.houzz.com/professionals", "category": "industry",
     "weight": 8, "industry_tags": ["landscaping", "pool", "home-services"]},
    {"slug": "angi-home-services", "name": "Angi Home Services",
     "url": "https://www.angi.com/pro/", "category": "industry", "weight": 8,
     "industry_tags": ["home-services", "landscaping", "pool"]},
    {"slug": "poolandspa", "name": "PoolAndSpa.com Directory",
     "url": "https://www.poolandspa.com", "category": "industry", "weight": 7,
     "industry_tags": ["pool"]},
    {"slug": "trustpilot", "name": "Trustpilot",
     "url": "https://business.trustpilot.com", "category": "industry",
     "weight": 7, "industry_tags": []},
    {"slug": "bbb", "name": "Better Business Bureau",
     "url": "https://www.bbb.org", "category": "industry", "weight": 8,
     "industry_tags": []},
    {"slug": "chamber-of-commerce", "name": "Local Chamber of Commerce",
     "url": "https://www.chamberofcommerce.com", "category": "industry",
     "weight": 6, "industry_tags": []},
    {"slug": "local-com", "name": "Local.com",
     "url": "https://www.local.com", "category": "industry", "weight": 5,
     "industry_tags": []},
    {"slug": "kudzu", "name": "Kudzu",
     "url": "https://www.kudzu.com", "category": "industry", "weight": 5,
     "industry_tags": ["home-services"]},
    {"slug": "merchant-circle", "name": "Merchant Circle",
     "url": "https://www.merchantcircle.com", "category": "industry",
     "weight": 5, "industry_tags": []},
    {"slug": "cylex", "name": "Cylex US",
     "url": "https://www.cylex.us.com", "category": "industry", "weight": 4,
     "industry_tags": []},
    {"slug": "tupalo-us", "name": "Tupalo US",
     "url": "https://tupalo.com", "category": "industry", "weight": 4,
     "industry_tags": []},
    {"slug": "brownbook", "name": "Brownbook",
     "url": "https://www.brownbook.net", "category": "industry", "weight": 4,
     "industry_tags": []},
    {"slug": "hotfrog", "name": "Hotfrog",
     "url": "https://www.hotfrog.com", "category": "industry", "weight": 5,
     "industry_tags": []},
    {"slug": "ezlocal", "name": "EZLocal",
     "url": "https://www.ezlocal.com", "category": "industry", "weight": 4,
     "industry_tags": []},

    # Reviews aggregation (4 — separate rows from the local/social ones so
    # admins can track "reviews strategy" independently of "citation strategy")
    {"slug": "google-reviews", "name": "Google Reviews (via GBP)",
     "url": "https://www.google.com/maps", "category": "reviews", "weight": 10,
     "industry_tags": []},
    {"slug": "yelp-reviews", "name": "Yelp Reviews",
     "url": "https://www.yelp.com", "category": "reviews", "weight": 8,
     "industry_tags": []},
    {"slug": "facebook-reviews", "name": "Facebook Reviews",
     "url": "https://www.facebook.com", "category": "reviews", "weight": 7,
     "industry_tags": []},
    {"slug": "tripadvisor", "name": "TripAdvisor (if hospitality-adjacent)",
     "url": "https://www.tripadvisor.com", "category": "reviews", "weight": 5,
     "industry_tags": []},

    # Extra local for depth (10) — puts us over 50 easily.
    {"slug": "citysearch", "name": "CitySearch",
     "url": "https://www.citysearch.com", "category": "local", "weight": 5,
     "industry_tags": []},
    {"slug": "insider-pages", "name": "Insider Pages",
     "url": "https://www.insiderpages.com", "category": "local", "weight": 4,
     "industry_tags": []},
    {"slug": "dexknows", "name": "DexKnows",
     "url": "https://www.dexknows.com", "category": "local", "weight": 4,
     "industry_tags": []},
    {"slug": "chamberofcommerce-com", "name": "ChamberofCommerce.com",
     "url": "https://www.chamberofcommerce.com", "category": "local",
     "weight": 5, "industry_tags": []},
    {"slug": "bizjournals", "name": "BizJournals Local",
     "url": "https://www.bizjournals.com", "category": "local", "weight": 5,
     "industry_tags": []},
    {"slug": "elocal", "name": "eLocal",
     "url": "https://www.elocal.com", "category": "local", "weight": 5,
     "industry_tags": ["home-services"]},
    {"slug": "bark", "name": "Bark.com",
     "url": "https://www.bark.com", "category": "local", "weight": 6,
     "industry_tags": ["home-services"]},
    {"slug": "n49", "name": "n49",
     "url": "https://www.n49.com", "category": "local", "weight": 3,
     "industry_tags": []},
    {"slug": "showmelocal", "name": "ShowMeLocal",
     "url": "https://www.showmelocal.com", "category": "local", "weight": 3,
     "industry_tags": []},
    {"slug": "citylocalpro", "name": "CityLocal Pro",
     "url": "https://www.citylocalpro.com", "category": "local", "weight": 3,
     "industry_tags": []},
]


# NAP fields we compare — pulled from tenant.settings.business_card. We
# use ``service_area`` in lieu of a structured address (see
# ``routers/tenants.py`` — that's the only address-shaped field on the
# business card today). ``hours`` and structured street address are
# **not** modelled on the business card yet; when they are added we
# just extend this tuple.
NAP_FIELDS = ("company_name", "service_area", "phone", "website_url")


# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────
def _admin_or_403(user: dict):
    if (user or {}).get("role") not in {"admin", "super_admin"}:
        raise HTTPException(403, "Admin only")


async def _tenant_business_card(tenant_id: str) -> Dict[str, str]:
    t = await db.tenants.find_one({"id": tenant_id},
                                   {"_id": 0, "settings.business_card": 1})
    card = ((t or {}).get("settings") or {}).get("business_card") or {}
    return {k: (card.get(k) or "") for k in NAP_FIELDS}


def _snapshot_matches(snap: Optional[Dict[str, Any]],
                       card: Dict[str, Any]) -> bool:
    if not snap:
        return False
    for k in NAP_FIELDS:
        if (snap.get(k) or "") != (card.get(k) or ""):
            return False
    return True


# ─────────────────────────────────────────────────────────────────────
# Seed + drift boot pass
# ─────────────────────────────────────────────────────────────────────
async def run_citations_seed_and_drift() -> Dict[str, int]:
    """Idempotent seed of the master directory list + a full-sweep NAP
    drift recompute across every tenant's citations.

    Called from ``server._background_seed`` on boot; safe to re-invoke
    from a cron or CLI. Never destroys tenant state — only flips
    ``nap_drift_detected`` and (when a row was ``live``) demotes it to
    ``needs_update``.
    """
    now = now_iso()

    # 1) Upsert every directory in the seed list by slug.
    seeded = 0
    for d in CITATION_DIRECTORY_SEED:
        doc = {
            "slug": d["slug"],
            "name": d["name"],
            "url": d["url"],
            "category": d["category"],
            "weight": int(d["weight"]),
            "industry_tags": d.get("industry_tags") or [],
            "logo_url": d.get("logo_url"),
            "requires_manual_verification": True,
            "auto_submit_supported": False,
            "updated_at": now,
        }
        existing = await db.citation_directories.find_one({"slug": d["slug"]},
                                                            {"_id": 0, "id": 1})
        if existing and existing.get("id"):
            await db.citation_directories.update_one(
                {"slug": d["slug"]}, {"$set": doc},
            )
        else:
            doc["id"] = new_id()
            doc["created_at"] = now
            await db.citation_directories.insert_one(doc)
        seeded += 1

    # 2) Ensure unique compound index on (tenant_id, directory_id).
    try:
        await db.tenant_citations.create_index(
            [("tenant_id", 1), ("directory_id", 1)],
            unique=True, name="tenant_citations_unique",
        )
    except Exception as e:  # pragma: no cover — index create is best-effort
        logger.warning(f"[citations] index create failed: {e}")

    # 3) Sweep every tenant's citations for NAP drift.
    drifted = 0
    tenant_ids: List[str] = []
    async for t in db.tenants.find({}, {"_id": 0, "id": 1}):
        if t.get("id"):
            tenant_ids.append(t["id"])

    for tid in tenant_ids:
        card = await _tenant_business_card(tid)
        cur = db.tenant_citations.find({"tenant_id": tid}, {"_id": 0})
        async for row in cur:
            snap = row.get("data_snapshot")
            has_snap = bool(snap) and any((snap.get(k) or "") for k in NAP_FIELDS)
            matches = _snapshot_matches(snap, card) if has_snap else True
            update: Dict[str, Any] = {}
            if has_snap and not matches:
                if not row.get("nap_drift_detected"):
                    update["nap_drift_detected"] = True
                    # Only demote a currently-live row — don't stomp
                    # rejected / n/a / in_progress statuses.
                    if row.get("status") == "live":
                        update["status"] = "needs_update"
                    drifted += 1
            elif matches and row.get("nap_drift_detected"):
                update["nap_drift_detected"] = False
            if update:
                update["updated_at"] = now
                await db.tenant_citations.update_one(
                    {"id": row["id"]}, {"$set": update},
                )

    return {"directories": seeded, "drifted": drifted,
            "tenants_swept": len(tenant_ids)}


# ─────────────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────────────
@router.get("/citations/directories",
             operation_id="citations.directories.list")
async def list_directories(user: Dict[str, Any] = Depends(get_current_user)):
    """Master directory list, grouped by category, sorted by weight desc."""
    _admin_or_403(user)
    rows = await db.citation_directories.find(
        {}, {"_id": 0},
    ).to_list(length=500)
    rows.sort(key=lambda r: (-int(r.get("weight") or 0), r.get("name") or ""))
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        grouped.setdefault(r.get("category") or "other", []).append(r)
    return {"total": len(rows), "directories": rows, "grouped": grouped}


@router.get("/citations/tenant",
             operation_id="citations.tenant.list")
async def list_tenant_citations(
    user: Dict[str, Any] = Depends(get_current_user),
):
    """Returns every directory joined with this tenant's citation row.

    Directories with no citation row yet come back with
    ``status='not_started'`` and no ``last_verified_at`` — makes the
    UI a single flat list.
    """
    _admin_or_403(user)
    tid = user.get("tenant_id")
    if not tid:
        raise HTTPException(400, "Missing tenant_id on caller")

    dirs = await db.citation_directories.find({}, {"_id": 0}).to_list(500)
    rows = await db.tenant_citations.find({"tenant_id": tid},
                                           {"_id": 0}).to_list(1000)
    by_directory: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        by_directory[r["directory_id"]] = r

    out: List[Dict[str, Any]] = []
    for d in dirs:
        r = by_directory.get(d["id"])
        out.append({
            "directory": d,
            "id": (r or {}).get("id"),
            "directory_id": d["id"],
            "status": (r or {}).get("status", "not_started"),
            "listing_url": (r or {}).get("listing_url"),
            "notes": (r or {}).get("notes"),
            "last_verified_at": (r or {}).get("last_verified_at"),
            "nap_confirmed_at": (r or {}).get("nap_confirmed_at"),
            "nap_drift_detected": bool((r or {}).get("nap_drift_detected")),
            "submitted_at": (r or {}).get("submitted_at"),
            "data_snapshot": (r or {}).get("data_snapshot") or {},
        })
    out.sort(key=lambda x: (-int(x["directory"].get("weight") or 0),
                             x["directory"].get("name") or ""))
    return {"total": len(out), "citations": out}


class CitationPatch(BaseModel):
    status: Optional[str] = None
    listing_url: Optional[str] = None
    notes: Optional[str] = None


async def _upsert_row(tenant_id: str, directory_id: str,
                       updates: Dict[str, Any],
                       user_id: Optional[str] = None) -> Dict[str, Any]:
    """Fetch (or create) the citation row, apply ``updates``, save, return."""
    row = await db.tenant_citations.find_one(
        {"tenant_id": tenant_id, "directory_id": directory_id},
        {"_id": 0},
    )
    now = now_iso()
    if not row:
        row = {
            "id": new_id(),
            "tenant_id": tenant_id,
            "directory_id": directory_id,
            "status": "not_started",
            "listing_url": None,
            "notes": None,
            "data_snapshot": {},
            "nap_drift_detected": False,
            "created_at": now,
            "updated_at": now,
        }
        row.update(updates)
        row["updated_at"] = now
        if user_id and updates.get("status") in {"submitted", "live"}:
            row.setdefault("submitted_by_user_id", user_id)
            row.setdefault("submitted_at", now)
        await db.tenant_citations.insert_one(row)
    else:
        row.update(updates)
        row["updated_at"] = now
        if user_id and updates.get("status") in {"submitted", "live"} \
                and not row.get("submitted_at"):
            row["submitted_by_user_id"] = user_id
            row["submitted_at"] = now
        await db.tenant_citations.update_one(
            {"id": row["id"]}, {"$set": {
                k: v for k, v in row.items() if k not in {"id"}
            }},
        )
    row.pop("_id", None)
    return row


@router.patch("/citations/tenant/{directory_id}",
                operation_id="citations.tenant.update")
async def patch_citation(
    directory_id: str,
    body: CitationPatch,
    user: Dict[str, Any] = Depends(get_current_user),
):
    _admin_or_403(user)
    tid = user.get("tenant_id")
    if not tid:
        raise HTTPException(400, "Missing tenant_id on caller")
    d = await db.citation_directories.find_one({"id": directory_id},
                                                 {"_id": 0, "id": 1})
    if not d:
        raise HTTPException(404, "Unknown directory")

    updates: Dict[str, Any] = {}
    if body.status is not None:
        allowed = {"not_started", "in_progress", "submitted", "live",
                    "needs_update", "rejected", "n/a"}
        if body.status not in allowed:
            raise HTTPException(422, f"Invalid status: {body.status}")
        updates["status"] = body.status
    if body.listing_url is not None:
        updates["listing_url"] = body.listing_url.strip() or None
    if body.notes is not None:
        updates["notes"] = body.notes

    row = await _upsert_row(tid, directory_id, updates, user_id=user.get("id"))
    return row


@router.post("/citations/tenant/{directory_id}/mark-verified",
              operation_id="citations.tenant.markVerified")
async def mark_verified(
    directory_id: str,
    user: Dict[str, Any] = Depends(get_current_user),
):
    _admin_or_403(user)
    tid = user.get("tenant_id")
    if not tid:
        raise HTTPException(400, "Missing tenant_id on caller")
    d = await db.citation_directories.find_one({"id": directory_id},
                                                 {"_id": 0, "id": 1})
    if not d:
        raise HTTPException(404, "Unknown directory")

    card = await _tenant_business_card(tid)
    now = now_iso()
    row = await _upsert_row(tid, directory_id, {
        "data_snapshot": card,
        "last_verified_at": now,
        "nap_confirmed_at": now,
        "nap_drift_detected": False,
    }, user_id=user.get("id"))
    return row


class BulkVerifyBody(BaseModel):
    directory_ids: List[str] = Field(default_factory=list)


@router.post("/citations/tenant/bulk-mark-verified",
              operation_id="citations.tenant.bulkMarkVerified")
async def bulk_mark_verified(
    body: BulkVerifyBody,
    user: Dict[str, Any] = Depends(get_current_user),
):
    _admin_or_403(user)
    tid = user.get("tenant_id")
    if not tid:
        raise HTTPException(400, "Missing tenant_id on caller")
    if not body.directory_ids:
        return {"verified": 0}

    # Filter to real directory ids only — silently drop unknown ones so
    # a stale UI selection never breaks the batch.
    known = await db.citation_directories.find(
        {"id": {"$in": body.directory_ids}}, {"_id": 0, "id": 1},
    ).to_list(len(body.directory_ids))
    known_ids = {k["id"] for k in known}

    card = await _tenant_business_card(tid)
    now = now_iso()
    n = 0
    for did in body.directory_ids:
        if did not in known_ids:
            continue
        await _upsert_row(tid, did, {
            "data_snapshot": card,
            "last_verified_at": now,
            "nap_confirmed_at": now,
            "nap_drift_detected": False,
        }, user_id=user.get("id"))
        n += 1
    return {"verified": n}


@router.get("/citations/tenant/summary",
             operation_id="citations.tenant.summary")
async def tenant_summary(
    user: Dict[str, Any] = Depends(get_current_user),
):
    """KPIs for the Citation Builder header strip.

    ``completeness_score`` is a 0-100 float weighted by directory
    weight: ``sum(weight where status=='live') / sum(all weights) * 100``.
    Non-``live`` statuses (including ``needs_update``) count as
    incomplete.
    """
    _admin_or_403(user)
    tid = user.get("tenant_id")
    if not tid:
        raise HTTPException(400, "Missing tenant_id on caller")

    dirs = await db.citation_directories.find(
        {}, {"_id": 0, "id": 1, "weight": 1},
    ).to_list(500)
    weights: Dict[str, int] = {d["id"]: int(d.get("weight") or 0) for d in dirs}
    total_weight = sum(weights.values()) or 1

    rows = await db.tenant_citations.find(
        {"tenant_id": tid}, {"_id": 0},
    ).to_list(1000)

    by_status: Dict[str, int] = {}
    live_weight = 0
    drift = 0
    total_impressions = 0
    total_clicks = 0
    total_actions = 0
    duplicates_open = 0
    oldest: Optional[str] = None
    for r in rows:
        s = r.get("status") or "not_started"
        by_status[s] = by_status.get(s, 0) + 1
        if s == "live":
            live_weight += weights.get(r.get("directory_id"), 0)
            total_impressions += int(r.get("impressions_last_30d") or 0)
            total_clicks += int(r.get("clicks_last_30d") or 0)
            total_actions += int(r.get("actions_last_30d") or 0)
        if r.get("nap_drift_detected"):
            drift += 1
        for dup in (r.get("duplicate_urls") or []):
            st = (dup.get("status") or "reported").lower()
            if st not in {"suppressed", "confirmed"}:
                duplicates_open += 1
        lv = r.get("last_verified_at")
        if lv and (oldest is None or lv < oldest):
            oldest = lv

    # Directories without a tenant row count as not_started.
    unstarted = len(dirs) - len(rows)
    if unstarted > 0:
        by_status["not_started"] = by_status.get("not_started", 0) + unstarted

    completeness = round(live_weight / total_weight * 100.0, 1)
    return {
        "total_directories": len(dirs),
        "by_status": by_status,
        "live_count": by_status.get("live", 0),
        "needs_update_count": by_status.get("needs_update", 0),
        "nap_drift_count": drift,
        "duplicates_open_count": duplicates_open,
        "total_impressions_last_30d": total_impressions,
        "total_clicks_last_30d": total_clicks,
        "total_actions_last_30d": total_actions,
        "weighted_completeness_score": completeness,
        "oldest_last_verified_at": oldest,
    }


# ─────────────────────────────────────────────────────────────────────
# Yext-inspired extensions · Feb-2026
# ─────────────────────────────────────────────────────────────────────
class AnalyticsBody(BaseModel):
    impressions: int = 0
    clicks: int = 0
    actions: int = 0
    period_start: Optional[str] = None
    period_end: Optional[str] = None


@router.post("/citations/tenant/{directory_id}/analytics",
              operation_id="citations.tenant.recordAnalytics")
async def record_analytics(
    directory_id: str,
    body: AnalyticsBody,
    user: Dict[str, Any] = Depends(get_current_user),
):
    """Persist an admin-entered analytics snapshot (impressions/clicks/
    actions) for the row's directory, plus roll the "last 30 days"
    fields on the citation itself so the row can render them without
    another lookup.
    """
    _admin_or_403(user)
    tid = user.get("tenant_id")
    if not tid:
        raise HTTPException(400, "Missing tenant_id on caller")
    d = await db.citation_directories.find_one({"id": directory_id},
                                                 {"_id": 0, "id": 1})
    if not d:
        raise HTTPException(404, "Unknown directory")
    now = now_iso()
    snap = {
        "id": new_id(),
        "tenant_id": tid,
        "directory_id": directory_id,
        "impressions": int(body.impressions or 0),
        "clicks": int(body.clicks or 0),
        "actions": int(body.actions or 0),
        "period_start": body.period_start,
        "period_end": body.period_end,
        "recorded_at": now,
        "recorded_by_user_id": user.get("id"),
    }
    await db.citation_analytics_snapshots.insert_one(snap)
    row = await _upsert_row(tid, directory_id, {
        "impressions_last_30d": snap["impressions"],
        "clicks_last_30d": snap["clicks"],
        "actions_last_30d": snap["actions"],
        "analytics_updated_at": now,
    })
    snap.pop("_id", None)
    return {"snapshot": snap, "row": row}


@router.get("/citations/tenant/{directory_id}/analytics-history",
             operation_id="citations.tenant.analyticsHistory")
async def analytics_history(
    directory_id: str,
    user: Dict[str, Any] = Depends(get_current_user),
):
    """Return every snapshot for the (tenant, directory) pair, newest first,
    plus the ``trend`` (up/down/flat) comparing the latest two entries."""
    _admin_or_403(user)
    tid = user.get("tenant_id")
    if not tid:
        raise HTTPException(400, "Missing tenant_id on caller")

    snaps = await db.citation_analytics_snapshots.find(
        {"tenant_id": tid, "directory_id": directory_id},
        {"_id": 0},
    ).to_list(200)
    snaps.sort(key=lambda s: s.get("recorded_at") or "", reverse=True)

    trend = "flat"
    if len(snaps) >= 2:
        a = snaps[0]
        b = snaps[1]
        if a.get("impressions", 0) > b.get("impressions", 0):
            trend = "up"
        elif a.get("impressions", 0) < b.get("impressions", 0):
            trend = "down"
    return {"total": len(snaps), "snapshots": snaps, "trend": trend}


# ── Voice search readiness ───────────────────────────────────────────
# Slugs + labels + weight. Sum = 100. `nap_consistency` is a synthetic
# "check every relevant listing has no drift" gate that adds 5 points.
VOICE_SEARCH_RULES = [
    {"slug": "google-business-profile", "label": "Google Business Profile live + description ≥ 200 chars",
     "weight": 30, "requires": "gbp_with_description"},
    {"slug": "apple-maps", "label": "Apple Business Connect live", "weight": 20, "requires": "live"},
    {"slug": "bing-places", "label": "Bing Places live", "weight": 15, "requires": "live"},
    {"slug": "yelp", "label": "Yelp live", "weight": 10, "requires": "live"},
    {"slug": "facebook-business", "label": "Facebook Business live", "weight": 10, "requires": "live"},
    {"slug": "nextdoor", "label": "Nextdoor live", "weight": 10, "requires": "live"},
    {"slug": "__nap__", "label": "NAP consistency (no drift on the above)", "weight": 5,
     "requires": "nap_consistency"},
]


@router.get("/citations/tenant/voice-score",
             operation_id="citations.tenant.voiceScore")
async def voice_score(
    user: Dict[str, Any] = Depends(get_current_user),
):
    _admin_or_403(user)
    tid = user.get("tenant_id")
    if not tid:
        raise HTTPException(400, "Missing tenant_id on caller")

    voice_slugs = [r["slug"] for r in VOICE_SEARCH_RULES if r["slug"] != "__nap__"]
    dirs = await db.citation_directories.find(
        {"slug": {"$in": voice_slugs}}, {"_id": 0, "id": 1, "slug": 1},
    ).to_list(20)
    by_slug: Dict[str, str] = {d["slug"]: d["id"] for d in dirs}
    row_by_slug: Dict[str, Dict[str, Any]] = {}
    for slug, did in by_slug.items():
        r = await db.tenant_citations.find_one(
            {"tenant_id": tid, "directory_id": did}, {"_id": 0},
        )
        if r:
            row_by_slug[slug] = r

    breakdown: List[Dict[str, Any]] = []
    score = 0
    # NAP-consistency gate — every voice directory must be present, live,
    # and drift-free. If any is missing / not-live / drifting, the 5-point
    # bonus is withheld.
    all_voice_live_no_drift = all(
        (row_by_slug.get(s) or {}).get("status") == "live"
        and not (row_by_slug.get(s) or {}).get("nap_drift_detected")
        for s in voice_slugs
    )
    for rule in VOICE_SEARCH_RULES:
        passed = False
        reason = ""
        if rule["requires"] == "gbp_with_description":
            r = row_by_slug.get(rule["slug"])
            desc_len = len((r.get("notes") or "").strip()) if r else 0
            if r and r.get("status") == "live" and desc_len >= 200:
                passed = True
            elif r and r.get("status") == "live" and desc_len < 200:
                reason = f"description only {desc_len} chars (need ≥ 200)"
            else:
                reason = "not yet live"
        elif rule["requires"] == "live":
            r = row_by_slug.get(rule["slug"])
            if r and r.get("status") == "live":
                passed = True
            else:
                reason = "not yet live"
        elif rule["requires"] == "nap_consistency":
            passed = all_voice_live_no_drift
            if not passed:
                reason = "one or more listings above are not live or show NAP drift"
        if passed:
            score += rule["weight"]
        breakdown.append({
            "slug": rule["slug"],
            "label": rule["label"],
            "weight": rule["weight"],
            "passed": passed,
            "reason": reason,
        })
    return {"score": score, "max_score": 100, "breakdown": breakdown}


# ── Duplicate listing management ─────────────────────────────────────
_DUP_STATUSES = {"reported", "suppressed", "confirmed", "pending"}


class DuplicateEntry(BaseModel):
    url: str
    status: Optional[str] = "reported"  # reported | suppressed | confirmed | pending
    note: Optional[str] = None


class DuplicatesPatch(BaseModel):
    duplicate_urls: List[DuplicateEntry] = Field(default_factory=list)


@router.patch("/citations/tenant/{directory_id}/duplicates",
                operation_id="citations.tenant.updateDuplicates")
async def update_duplicates(
    directory_id: str,
    body: DuplicatesPatch,
    user: Dict[str, Any] = Depends(get_current_user),
):
    _admin_or_403(user)
    tid = user.get("tenant_id")
    if not tid:
        raise HTTPException(400, "Missing tenant_id on caller")
    d = await db.citation_directories.find_one({"id": directory_id},
                                                 {"_id": 0, "id": 1})
    if not d:
        raise HTTPException(404, "Unknown directory")

    cleaned: List[Dict[str, Any]] = []
    seen: set = set()
    now = now_iso()
    for entry in body.duplicate_urls:
        url = (entry.url or "").strip()
        if not url:
            continue
        if url in seen:
            continue
        seen.add(url)
        st = (entry.status or "reported").lower()
        if st not in _DUP_STATUSES:
            raise HTTPException(422, f"Invalid duplicate status: {entry.status}")
        cleaned.append({
            "url": url,
            "status": st,
            "note": entry.note or None,
            "updated_at": now,
        })
    row = await _upsert_row(tid, directory_id, {
        "duplicate_urls": cleaned,
    })
    return row


# ── NAP drift preview (for BusinessCard edit modal) ──────────────────
class DriftPreviewBody(BaseModel):
    company_name: Optional[str] = None
    service_area: Optional[str] = None
    phone: Optional[str] = None
    website_url: Optional[str] = None


@router.get("/citations/tenant/nap-drift-preview",
             operation_id="citations.tenant.napDriftPreview")
async def nap_drift_preview(
    company_name: Optional[str] = None,
    service_area: Optional[str] = None,
    phone: Optional[str] = None,
    website_url: Optional[str] = None,
    user: Dict[str, Any] = Depends(get_current_user),
):
    """Preview which live citations will show drift IF the tenant saves
    the given hypothetical business_card values.

    Every query param defaults to the current value on the tenant's
    business_card, so callers can send just the fields they're about to
    change. Returns rows that are currently ``live`` OR ``needs_update``
    whose ``data_snapshot`` would no longer match. Never mutates state.
    """
    _admin_or_403(user)
    tid = user.get("tenant_id")
    if not tid:
        raise HTTPException(400, "Missing tenant_id on caller")

    current = await _tenant_business_card(tid)
    proposed = {
        "company_name":
            company_name if company_name is not None else current.get("company_name") or "",
        "service_area":
            service_area if service_area is not None else current.get("service_area") or "",
        "phone":
            phone if phone is not None else current.get("phone") or "",
        "website_url":
            website_url if website_url is not None else current.get("website_url") or "",
    }
    changed_fields = [k for k in NAP_FIELDS if (current.get(k) or "") != (proposed.get(k) or "")]

    rows = await db.tenant_citations.find(
        {"tenant_id": tid, "status": {"$in": ["live", "needs_update"]}},
        {"_id": 0},
    ).to_list(500)
    dir_ids = list({r.get("directory_id") for r in rows if r.get("directory_id")})
    dirs = await db.citation_directories.find(
        {"id": {"$in": dir_ids}}, {"_id": 0},
    ).to_list(len(dir_ids) or 1)
    dir_by_id = {d["id"]: d for d in dirs}

    affected: List[Dict[str, Any]] = []
    for r in rows:
        snap = r.get("data_snapshot") or {}
        will_drift = any((snap.get(k) or "") != (proposed.get(k) or "") for k in NAP_FIELDS)
        if not will_drift:
            continue
        d = dir_by_id.get(r.get("directory_id")) or {}
        affected.append({
            "directory_id": r.get("directory_id"),
            "directory_name": d.get("name") or "",
            "directory_slug": d.get("slug") or "",
            "directory_url": d.get("url") or "",
            "listing_url": r.get("listing_url"),
            "current_snapshot": {k: snap.get(k) or "" for k in NAP_FIELDS},
        })
    affected.sort(key=lambda x: x["directory_name"])
    return {
        "changed_fields": changed_fields,
        "current": current,
        "proposed": proposed,
        "affected_count": len(affected),
        "affected": affected,
    }
