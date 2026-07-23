"""Feb-2026 · Phase 20 P4 — GBP completeness checklist.

Merges auto-computed items (from business_card / reviews-summary /
latest seo_scan) with admin-attested toggles persisted at
``tenant.settings.local_seo_checklist``. Returns a normalized list
so the frontend can render a progress bar + per-item action.
"""
from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from config import db
from utils import get_current_user
from routers.tenants import get_current_tenant

router = APIRouter(tags=["Local SEO"])

CHECKLIST_ITEMS = [
    # key, label, kind ("auto" | "toggle"), guidance
    ("business_name",         "Business name set",                   "auto",   "business_card.company_name"),
    ("description",           "Description on GBP",                  "toggle", "Add a 750-char description on Google Business Profile."),
    ("primary_category",      "Primary category selected",           "toggle", "Choose ONE primary category in GBP."),
    ("secondary_categories",  "≥2 secondary categories",             "toggle", "Add secondary categories to widen reach."),
    ("hours",                 "Business hours set",                  "toggle", "Set weekly hours + holiday hours in GBP."),
    ("holiday_hours",         "Holiday hours reviewed this quarter", "toggle", "Update seasonal / holiday hours."),
    ("service_area",          "Service area listed",                 "auto",   "business_card.service_area"),
    ("phone",                 "Phone number set",                    "auto",   "business_card.phone"),
    ("website",               "Website URL set",                     "auto",   "business_card.website_url"),
    ("review_count_10",       "≥10 Google reviews",                  "derived",""),
    ("avg_rating_45",         "Avg rating ≥ 4.5★",                   "derived",""),
    ("photos_5",              "≥5 photos on GBP",                    "toggle", "Upload storefront, team, work-in-progress photos."),
    ("post_last_30_days",     "≥1 GBP post in last 30 days",         "derived",""),
    ("qa_3_seeded",           "≥3 Q&A seeded",                       "toggle", "Seed common Q&A so Google shows them."),
    ("appointment_url",       "Appointment/booking URL set",         "toggle", "Add a booking URL in GBP."),
    ("mobile_viewport",       "Website mobile-viewport meta",        "derived",""),
    ("https_enforced",        "Website served over HTTPS",           "derived",""),
]


def _require_admin(user: Dict[str, Any]) -> None:
    if user.get("role") not in {"admin", "super_admin"}:
        raise HTTPException(403, "Admin only")


async def _compute_derived(tenant: Dict[str, Any]) -> Dict[str, bool]:
    tid = tenant["id"]
    # Review count + avg from public reviews collection.
    review_stats = await db.reviews.aggregate([
        {"$match": {"tenant_id": tid, "is_public": True,
                     "star_rating": {"$gte": 1, "$lte": 5}}},
        {"$group": {"_id": None, "count": {"$sum": 1},
                     "avg": {"$avg": "$star_rating"}}},
    ]).to_list(1)
    review_count = int((review_stats[0].get("count") if review_stats else 0) or 0)
    avg_rating = float((review_stats[0].get("avg") if review_stats else 0) or 0.0)

    # GBP posts in last 30 days.
    from datetime import datetime, timedelta, timezone as _tz
    since = (datetime.now(_tz.utc) - timedelta(days=30)).isoformat()
    gbp_recent = await db.gbp_post_drafts.count_documents(
        {"tenant_id": tid, "status": "posted", "posted_at": {"$gte": since}},
    )

    # Latest SEO scan.
    scan = await db.seo_scans.find_one(
        {"tenant_id": tid}, {"_id": 0, "result": 1},
        sort=[("run_at", -1)],
    )
    result = (scan or {}).get("result") or {}
    checks = {c.get("key"): bool(c.get("ok")) for c in (result.get("checks") or [])}

    return {
        "review_count_10":  review_count >= 10,
        "avg_rating_45":    avg_rating >= 4.5,
        "post_last_30_days": gbp_recent >= 1,
        "mobile_viewport":  bool(checks.get("mobile_viewport", False)),
        "https_enforced":   bool(checks.get("https", True) or result.get("https_enforced", True)),
    }


@router.get("/local-seo/checklist",
             operation_id="localSeoChecklist.get")
async def get_checklist(user: Dict[str, Any] = Depends(get_current_user),
                         tenant: Dict[str, Any] = Depends(get_current_tenant)):
    _require_admin(user)
    settings = tenant.get("settings") or {}
    card = settings.get("business_card") or {}
    toggles = settings.get("local_seo_checklist") or {}
    derived = await _compute_derived(tenant)

    def _state(key: str, kind: str) -> bool:
        if kind == "auto":
            if key == "business_name":  return bool(card.get("company_name"))
            if key == "service_area":   return bool(card.get("service_area"))
            if key == "phone":          return bool(card.get("phone"))
            if key == "website":        return bool(card.get("website_url"))
            return False
        if kind == "derived":
            return bool(derived.get(key, False))
        return bool(toggles.get(key, False))

    items = []
    passed = 0
    for key, label, kind, guidance in CHECKLIST_ITEMS:
        ok = _state(key, kind)
        if ok: passed += 1
        items.append({
            "key": key, "label": label, "kind": kind,
            "ok": ok, "guidance": guidance,
        })
    return {
        "items": items, "total": len(CHECKLIST_ITEMS),
        "passed": passed,
        "progress_pct": round(100 * passed / max(1, len(CHECKLIST_ITEMS))),
    }


class ChecklistPatchIn(BaseModel):
    toggles: Dict[str, bool]


@router.patch("/local-seo/checklist",
                operation_id="localSeoChecklist.patch")
async def patch_checklist(body: ChecklistPatchIn,
                            user: Dict[str, Any] = Depends(get_current_user),
                            tenant: Dict[str, Any] = Depends(get_current_tenant)):
    _require_admin(user)
    # Only accept keys that are 'toggle' kind.
    toggle_keys = {k for k, _l, kind, _g in CHECKLIST_ITEMS if kind == "toggle"}
    cleaned = {k: bool(v) for k, v in (body.toggles or {}).items() if k in toggle_keys}
    existing = (tenant.get("settings") or {}).get("local_seo_checklist") or {}
    merged = {**existing, **cleaned}
    await db.tenants.update_one(
        {"id": tenant["id"]},
        {"$set": {"settings.local_seo_checklist": merged}},
    )
    return {"ok": True, "toggles": merged}
