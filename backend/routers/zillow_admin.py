"""Phase 52 · Zillow healthcheck + Phase 56.9b usage widget.

The healthcheck stays admin-only. The Step 4 usage widget adds an
admin dashboard endpoint that summarizes tenant Zillow spend for the
current month + a cache-hit rate. Purely read-only; never touches
the paid API.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends

from utils import require_admin
from routers.tenants import get_current_tenant
from config import OPENWEB_NINJA_API_KEY, db
from services.zillow_rate_limit import (
    _month_key, _tenant_budget, BUDGET_WARN_THRESHOLD,
)

router = APIRouter(prefix="/zillow", tags=["zillow"])


@router.get("/health")
async def zillow_health(user: dict = Depends(require_admin)):
    return {"configured": bool(OPENWEB_NINJA_API_KEY)}


@router.get("/usage/this-month")
async def zillow_usage_this_month(
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    """Admin-only Step 4 widget backend. Returns total lookups, top 5
    users by lookup count, budget % consumed, and cache-hit rate for
    the tenant this calendar month."""
    tenant_id = tenant["id"]
    month = _month_key()
    month_start = f"{month}-01T00:00:00+00:00"

    # Total counted lookups this month (cache hits are NOT logged to
    # zillow_usage per Step 3 spec — cache doesn't decrement).
    total = await db.zillow_usage.count_documents(
        {"tenant_id": tenant_id, "ts": {"$gte": month_start}}
    )

    # Top 5 users by call count this month.
    top_users_cursor = db.zillow_usage.aggregate([
        {"$match": {"tenant_id": tenant_id, "ts": {"$gte": month_start}}},
        {"$group": {"_id": "$user_id", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}}, {"$limit": 5},
    ])
    top = [{"user_id": r["_id"], "lookups": r["count"]}
           async for r in top_users_cursor]
    # Enrich with names.
    uids = [t["user_id"] for t in top if t["user_id"]]
    users = {}
    if uids:
        async for u in db.users.find(
            {"id": {"$in": uids}}, {"_id": 0, "id": 1, "name": 1, "email": 1},
        ):
            users[u["id"]] = u
    for t in top:
        u = users.get(t["user_id"]) or {}
        t["name"] = u.get("name") or u.get("email") or "—"

    # Cache hit rate is measured against the total of (counted calls +
    # cache-attributed calls); we don't log cache hits, so a
    # conservative estimate uses a monthly counter kept only if it
    # exists in zillow_audit as `event: "zillow_cache_hit"`. Until
    # that instrumentation lands (Step 6/7), fall back to 0 so the
    # widget never lies.
    hits = await db.zillow_audit.count_documents(
        {"tenant_id": tenant_id, "event": "zillow_cache_hit",
         "ts": {"$gte": month_start}}
    )
    denom = total + hits
    cache_hit_rate = round(hits / denom, 4) if denom else 0.0

    budget = await _tenant_budget(tenant)
    pct = round(total / budget, 4) if budget else 0.0
    return {
        "month": month,
        "tenant_id": tenant_id,
        "total_lookups": total,
        "top_users": top,
        "tenant_budget": budget,
        "tenant_used": total,
        "tenant_pct": pct,
        "budget_warning": pct >= BUDGET_WARN_THRESHOLD,
        "cache_hits": hits,
        "cache_hit_rate": cache_hit_rate,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
