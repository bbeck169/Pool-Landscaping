"""Phase 15D — Multi-tenant foundation (Stage 1: substrate only).

Stage 1 goals:
1. `tenants` collection with a default `aquaterra` tenant seeded on startup.
2. Backfill `tenant_id` on every existing document across every collection.
3. `TenantContext` dependency resolving from JWT `tenant_id` claim → `X-Tenant-Slug`
   header → default tenant.
4. `GET /api/tenants/current` returning the resolved tenant.

**Stage 1 does NOT refactor any query to filter by tenant.** Existing endpoints
continue working exactly as they do today. Stage 2-5 will layer isolation on top.
"""
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request

from config import db, logger
from utils import now_iso, new_id, get_current_user

router = APIRouter()

DEFAULT_TENANT_SLUG = "aquaterra"

# Every collection that stores tenant-owned entities. Additive-only — new
# collections should be added here as they land.
_TENANT_COLLECTIONS = [
    "users", "customers", "technicians", "jobs", "quotes", "leads", "tasks",
    "notifications", "messages", "communications", "payments", "billing_plans",
    "signatures", "csat_surveys", "csat_pending", "forms", "form_submissions",
    "sequences", "sequence_enrollments", "marketing_campaigns", "marketing_queue",
    "marketing_posts", "marketing_threads", "marketing_brand",
    "activity_log", "d2d_routes", "d2d_visits", "d2d_leads",
    "landscape_renders", "measurements", "properties",
    "onboarding_state", "lead_request_dispatches", "mobile_tokens",
    "settings", "chemicals", "items", "coverage_areas", "attendance",
    "estimates", "documents", "reviews",
]


async def _ensure_default_tenant() -> dict:
    """Idempotent seed of the default tenant + return the record."""
    existing = await db.tenants.find_one({"slug": DEFAULT_TENANT_SLUG}, {"_id": 0})
    if existing:
        return existing
    doc = {
        "id": new_id(),
        "name": "AquaTerra",
        "slug": DEFAULT_TENANT_SLUG,
        "brand_primary": "#0284C7",
        "brand_secondary": "#16A34A",
        "custom_domain": None,
        "plan_tier": "enterprise",
        "active": True,
        "created_at": now_iso(),
    }
    await db.tenants.insert_one(doc)
    return doc


async def run_tenant_backfill() -> dict:
    """One-time-ish backfill of `tenant_id` across every whitelisted collection.
    Idempotent: only rows missing the field are updated. Safe to call on every
    startup — subsequent runs are near-instant (only new documents get touched)."""
    tenant = await _ensure_default_tenant()
    tid = tenant["id"]
    report = {}
    for coll_name in _TENANT_COLLECTIONS:
        try:
            r = await db[coll_name].update_many(
                {"tenant_id": {"$exists": False}},
                {"$set": {"tenant_id": tid}},
            )
            if r.modified_count:
                report[coll_name] = r.modified_count
        except Exception as e:
            logger.warning(f"tenant backfill skipped {coll_name}: {e}")
    if report:
        logger.info(f"tenant backfill touched: {report}")
    return {"tenant_id": tid, "touched": report}


# ─── Dependency ──────────────────────────────────────────────────────────────
from utils import get_current_user


async def get_current_tenant(
    request: Request,
    user: dict = Depends(get_current_user),
    x_tenant_slug: Optional[str] = Header(None, alias="X-Tenant-Slug"),
) -> dict:
    """Resolve tenant from:
      1. User document's `tenant_id` (backfilled in Stage 1)
      2. `X-Tenant-Slug` header (for cross-tenant super-admin scenarios later)
      3. Custom domain matching `Host` header
      4. Fallback → default tenant
    """
    tenant = None
    # 1. User's tenant_id (populated by backfill).
    if user.get("tenant_id"):
        tenant = await db.tenants.find_one({"id": user["tenant_id"], "active": True}, {"_id": 0})
    # 2. Header override.
    if not tenant and x_tenant_slug:
        tenant = await db.tenants.find_one({"slug": x_tenant_slug, "active": True}, {"_id": 0})
    # 3. Custom domain.
    if not tenant:
        host = (request.headers.get("host") or "").split(":")[0].lower()
        if host:
            tenant = await db.tenants.find_one({"custom_domain": host, "active": True}, {"_id": 0})
    # 4. Default.
    if not tenant:
        tenant = await _ensure_default_tenant()
    return tenant


# ─── Endpoints ───────────────────────────────────────────────────────────────
@router.get("/tenants/current")
async def current_tenant(request: Request,
                         tenant: dict = Depends(get_current_tenant),
                         user: dict = Depends(get_current_user)):
    resolved_via = "user-record" if user.get("tenant_id") == tenant["id"] else \
                   ("header" if request.headers.get("x-tenant-slug") else "default")
    return {
        "id": tenant["id"],
        "slug": tenant["slug"],
        "name": tenant["name"],
        "brand_primary": tenant.get("brand_primary"),
        "brand_secondary": tenant.get("brand_secondary"),
        "custom_domain": tenant.get("custom_domain"),
        "plan_tier": tenant.get("plan_tier"),
        "resolved_via": resolved_via,
    }
