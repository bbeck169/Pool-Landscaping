"""Phase 20B.4 · Tiered referral rewards + polished analytics.

Layered on top of Phase 19 (`routers/referrals.py`) without altering the
existing approve/reject flow's contract. Adds:

- Tier settings (`referral_program_settings`) — the admin can define reward
  tier bands (`conversion_min`..`conversion_max`) keyed on the referrer's
  cumulative approved count. Approve helper reads these bands and issues
  the matching credit.
- Advanced analytics: funnel, revenue attribution, cohort curve, paginated
  leaderboard.
"""
from datetime import datetime
from typing import List, Optional, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from config import db, logger
from utils import now_iso, new_id, get_current_user, require_admin
from routers.tenants import get_current_tenant

router = APIRouter()


class Tier(BaseModel):
    conversion_min: int = Field(..., ge=1)
    conversion_max: int = Field(..., ge=1)   # inclusive; 999 → open-ended top
    credit_pct: float = Field(..., gt=0, le=100)
    credit_months: int = Field(1, ge=1, le=12)


class SettingsIn(BaseModel):
    tiers: List[Tier]


# Default (single-tier, matches Phase 19 legacy behavior).
_DEFAULT_TIERS: List[Dict[str, Any]] = [
    {"conversion_min": 1, "conversion_max": 999,
     "credit_pct": 50.0, "credit_months": 1},
]


async def get_settings(tenant_id: str) -> Dict[str, Any]:
    doc = await db.referral_program_settings.find_one(
        {"tenant_id": tenant_id}, {"_id": 0}
    )
    if not doc:
        doc = {
            "id": new_id(),
            "tenant_id": tenant_id,
            "tiers": _DEFAULT_TIERS,
            "created_at": now_iso(),
            "updated_at": now_iso(),
        }
        await db.referral_program_settings.insert_one(dict(doc))
        doc.pop("_id", None)
    return doc


def pick_tier(settings: dict, nth_conversion: int) -> Dict[str, Any]:
    """Return the tier matching the referrer's Nth approved conversion (1-based)."""
    tiers = sorted(settings.get("tiers") or _DEFAULT_TIERS,
                   key=lambda t: int(t.get("conversion_min", 1)))
    for t in tiers:
        lo, hi = int(t["conversion_min"]), int(t["conversion_max"])
        if lo <= nth_conversion <= hi:
            return t
    return tiers[-1] if tiers else _DEFAULT_TIERS[0]


@router.get("/referrals/settings")
async def read_settings(user: dict = Depends(require_admin),
                         tenant: dict = Depends(get_current_tenant)):
    return await get_settings(tenant["id"])


@router.put("/referrals/settings")
async def write_settings(body: SettingsIn,
                          user: dict = Depends(require_admin),
                          tenant: dict = Depends(get_current_tenant)):
    if not body.tiers:
        raise HTTPException(400, "At least one tier required")
    # Validate ranges are non-overlapping and ordered.
    tiers = sorted([t.dict() for t in body.tiers], key=lambda t: t["conversion_min"])
    for i, t in enumerate(tiers):
        if t["conversion_min"] > t["conversion_max"]:
            raise HTTPException(400, f"Tier {i}: conversion_min > conversion_max")
        if i > 0 and t["conversion_min"] <= tiers[i - 1]["conversion_max"]:
            raise HTTPException(400, f"Tier {i}: overlapping range with previous tier")
    doc = await db.referral_program_settings.find_one(
        {"tenant_id": tenant["id"]}, {"_id": 0}
    )
    if doc:
        await db.referral_program_settings.update_one(
            {"tenant_id": tenant["id"]},
            {"$set": {"tiers": tiers, "updated_at": now_iso()}},
        )
    else:
        await db.referral_program_settings.insert_one({
            "id": new_id(), "tenant_id": tenant["id"],
            "tiers": tiers, "created_at": now_iso(), "updated_at": now_iso(),
        })
    return await get_settings(tenant["id"])


# ── Advanced analytics ──────────────────────────────────────────────────
@router.get("/referrals/admin/analytics/v2")
async def analytics_v2(
    leaderboard_page: int = Query(1, ge=1),
    leaderboard_size: int = Query(10, ge=1, le=100),
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    tid = tenant["id"]

    # ── Funnel ───────────────────────────────────────────────────────
    invites = await db.referral_invites.count_documents({"tenant_id": tid})
    unique_referred_signups = await db.referral_conversions.count_documents(
        {"tenant_id": tid}
    )
    converted = await db.referral_conversions.count_documents(
        {"tenant_id": tid, "status": "approved"}
    )
    # Credits redeemed = service_credits with source=referral that have redeemed_at set.
    redeemed = await db.service_credits.count_documents(
        {"tenant_id": tid, "source": "referral", "redeemed_at": {"$ne": None}}
    )
    funnel = {
        "invites": invites,
        "signups": unique_referred_signups,
        "converted": converted,
        "credits_redeemed": redeemed,
    }

    # ── Revenue attribution (sum of invoice totals for customers acquired via referral) ─
    referred_customer_ids = [
        c["referred_customer_id"]
        async for c in db.referral_conversions.find(
            {"tenant_id": tid, "status": "approved",
             "referred_customer_id": {"$ne": None}},
            {"_id": 0, "referred_customer_id": 1},
        )
    ]
    revenue = 0.0
    by_referrer: Dict[str, float] = {}
    if referred_customer_ids:
        pipe = db.quotes.aggregate([
            {"$match": {"tenant_id": tid,
                         "doc_type": "invoice",
                         "customer_id": {"$in": referred_customer_ids}}},
            {"$group": {"_id": "$customer_id",
                         "total_billed": {"$sum": "$total"}}},
        ])
        totals_by_customer = {row["_id"]: float(row["total_billed"] or 0)
                              async for row in pipe}
        # Fold each referred customer's revenue back to its referrer.
        async for c in db.referral_conversions.find(
            {"tenant_id": tid, "status": "approved",
             "referred_customer_id": {"$in": list(totals_by_customer.keys())}},
            {"_id": 0, "referrer_customer_id": 1, "referred_customer_id": 1},
        ):
            amt = totals_by_customer.get(c["referred_customer_id"], 0.0)
            by_referrer[c["referrer_customer_id"]] = (
                by_referrer.get(c["referrer_customer_id"], 0.0) + amt
            )
            revenue += amt

    # ── Cohort curve (referrer's first invite month → cumulative conversion count) ─
    first_invite: Dict[str, str] = {}
    async for iv in db.referral_invites.find(
        {"tenant_id": tid}, {"_id": 0, "referrer_customer_id": 1, "created_at": 1}
    ).sort("created_at", 1):
        rid = iv.get("referrer_customer_id")
        if rid and rid not in first_invite:
            ca = iv.get("created_at") or ""
            first_invite[rid] = ca[:7]
    cohort_counts: Dict[str, Dict[str, int]] = {}
    async for cv in db.referral_conversions.find(
        {"tenant_id": tid, "status": "approved"},
        {"_id": 0, "referrer_customer_id": 1, "created_at": 1},
    ):
        cohort = first_invite.get(cv.get("referrer_customer_id"))
        month = cv.get("created_at", "")[:7]
        if not cohort or not month: continue
        cohort_counts.setdefault(cohort, {}).setdefault(month, 0)
        cohort_counts[cohort][month] += 1
    cohort_curve = [
        {"cohort": c, "months": [{"month": m, "conversions": v}
                                  for m, v in sorted(mo.items())]}
        for c, mo in sorted(cohort_counts.items())
    ]

    # ── Leaderboard (paginated) ─────────────────────────────────────
    total_referrers = len(
        await db.referral_conversions.distinct(
            "referrer_customer_id",
            {"tenant_id": tid, "status": "approved"},
        )
    )
    top_cursor = db.referral_conversions.aggregate([
        {"$match": {"tenant_id": tid, "status": "approved"}},
        {"$group": {"_id": "$referrer_customer_id",
                     "converted_count": {"$sum": 1}}},
        {"$sort": {"converted_count": -1}},
        {"$skip": (leaderboard_page - 1) * leaderboard_size},
        {"$limit": leaderboard_size},
    ])
    leaderboard = []
    async for row in top_cursor:
        cust = await db.customers.find_one(
            {"id": row["_id"], "tenant_id": tid}, {"_id": 0, "name": 1, "email": 1}
        ) or {}
        leaderboard.append({
            "customer_id": row["_id"],
            "name": cust.get("name") or cust.get("email") or "—",
            "converted_count": row["converted_count"],
            "revenue_attributed": round(by_referrer.get(row["_id"], 0.0), 2),
        })

    return {
        "funnel": funnel,
        "revenue_attribution": {
            "total_usd": round(revenue, 2),
            "by_referrer_top10": [
                {"customer_id": k, "revenue_usd": round(v, 2)}
                for k, v in sorted(by_referrer.items(), key=lambda x: -x[1])[:10]
            ],
        },
        "cohort_curve": cohort_curve,
        "leaderboard": {
            "page": leaderboard_page,
            "size": leaderboard_size,
            "total_referrers": total_referrers,
            "rows": leaderboard,
        },
    }
