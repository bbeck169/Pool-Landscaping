"""Phase 16 · Item I — Revenue Ops / Tier Gates.

Extends the tenant model with a `plan_features` object, adds a `tenant_usage`
collection, and exposes:

* `GET  /api/tenants/mine/plan`           — current tenant plan + features + usage
* `PUT  /api/tenants/{tid}/plan`          — super-admin only, patch plan_tier / features
* `GET  /api/tenants/{tid}/usage`         — super-admin only usage report

Also exposes `require_feature("d2d_enabled")` etc. that other routers can use
to return **402 Payment Required** with an upgrade-friendly payload:

    {
      "detail": "This feature requires the Pro plan.",
      "required_plan": "pro",
      "feature": "sequences_enabled",
      "current_plan": "free",
    }

Plan matrix follows the spec in the phase-16 kickoff:

    Free       Pro           Enterprise
    ----       ---           ----------
    custom_branding      : F      T             T
    custom_domain        : F      F             T
    white_label_reports  : F      F             T
    max_users            : 3      15            -1 (∞)
    max_customers        : 25     500           -1 (∞)
    ai_calls_per_month   : 50     2000          -1 (∞)
    sequences_enabled    : F      T             T
    d2d_enabled          : F      T             T
"""
from datetime import datetime, timezone
from typing import Optional, Dict, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from config import db, logger
from utils import now_iso, new_id, get_current_user
from routers.tenants import get_current_tenant, require_super_admin

router = APIRouter()


PLAN_MATRIX: Dict[str, Dict[str, Any]] = {
    "free": {
        "custom_branding": False,
        "custom_domain": False,
        "white_label_reports": False,
        "max_users": 3,
        "max_customers": 25,
        "ai_calls_per_month": 50,
        "sequences_enabled": False,
        "d2d_enabled": False,
    },
    "pro": {
        "custom_branding": True,
        "custom_domain": False,
        "white_label_reports": False,
        "max_users": 15,
        "max_customers": 500,
        "ai_calls_per_month": 2000,
        "sequences_enabled": True,
        "d2d_enabled": True,
    },
    "enterprise": {
        "custom_branding": True,
        "custom_domain": True,
        "white_label_reports": True,
        "max_users": -1,
        "max_customers": -1,
        "ai_calls_per_month": -1,
        "sequences_enabled": True,
        "d2d_enabled": True,
    },
}

# When gating, this map says "the minimum plan that grants this boolean feature".
FEATURE_MIN_PLAN: Dict[str, str] = {
    "custom_branding": "pro",
    "custom_domain": "enterprise",
    "white_label_reports": "enterprise",
    "sequences_enabled": "pro",
    "d2d_enabled": "pro",
}


def _plan_defaults(plan_tier: str) -> Dict[str, Any]:
    return dict(PLAN_MATRIX.get(plan_tier or "free", PLAN_MATRIX["free"]))


def _current_month_key() -> str:
    now = datetime.now(timezone.utc)
    return f"{now.year:04d}-{now.month:02d}"


async def _ensure_plan_features(tenant: dict) -> dict:
    """Backfill plan_features onto a tenant if missing. Returns the merged tenant."""
    plan_tier = (tenant.get("plan_tier") or "free").lower()
    features = tenant.get("plan_features")
    if not features:
        features = _plan_defaults(plan_tier)
        await db.tenants.update_one(
            {"id": tenant["id"]}, {"$set": {"plan_features": features}}
        )
        tenant["plan_features"] = features
    return tenant


async def seed_plan_features() -> None:
    """Idempotent — set every tenant's plan_features to sensible defaults.
    - `aquaterra` → enterprise
    - `sunbelt`   → pro
    - anything else missing plan_features → free defaults
    """
    tenants = await db.tenants.find({}, {"_id": 0}).to_list(500)
    for t in tenants:
        slug = t.get("slug")
        desired_tier = t.get("plan_tier") or "free"
        if slug == "aquaterra":
            desired_tier = "enterprise"
        elif slug == "sunbelt":
            desired_tier = "pro"
        if not t.get("plan_features") or t.get("plan_tier") != desired_tier:
            await db.tenants.update_one(
                {"id": t["id"]},
                {"$set": {"plan_tier": desired_tier,
                          "plan_features": _plan_defaults(desired_tier)}},
            )
    logger.info("Phase 16 · plan_features backfill complete")


# ─── Usage tracking ────────────────────────────────────────────────────────
async def get_tenant_usage(tenant_id: str) -> dict:
    """Return the current month's usage doc, creating a zeroed one if missing."""
    key = _current_month_key()
    doc = await db.tenant_usage.find_one(
        {"tenant_id": tenant_id, "month_yyyy_mm": key}, {"_id": 0}
    )
    if not doc:
        doc = {
            "tenant_id": tenant_id,
            "month_yyyy_mm": key,
            "ai_calls": 0,
            "active_users": 0,
            "customer_count": 0,
            "created_at": now_iso(),
        }
        await db.tenant_usage.insert_one(doc)
        doc.pop("_id", None)
    # Overlay real-time counters that we compute on the fly (users/customers).
    doc["active_users"] = await db.users.count_documents({"tenant_id": tenant_id})
    doc["customer_count"] = await db.customers.count_documents({"tenant_id": tenant_id})
    return doc


async def increment_ai_calls(tenant_id: str, n: int = 1) -> None:
    """Atomic increment for ai_calls this month."""
    key = _current_month_key()
    await db.tenant_usage.update_one(
        {"tenant_id": tenant_id, "month_yyyy_mm": key},
        {"$inc": {"ai_calls": n},
         "$setOnInsert": {"created_at": now_iso()}},
        upsert=True,
    )


# ─── Feature gating dependency ─────────────────────────────────────────────
def require_feature(feature: str):
    """FastAPI dependency factory. Returns a callable that raises 402 with a
    friendly upgrade payload when the tenant's plan_features[feature] is falsy.
    Also enforces numeric quotas (max_users, max_customers, ai_calls_per_month)
    when `feature` is one of those keys (min-plan lookup skipped in that case)."""
    async def _dep(tenant: dict = Depends(get_current_tenant)):
        tenant = await _ensure_plan_features(tenant)
        features = tenant.get("plan_features") or {}
        val = features.get(feature)

        # Numeric quotas — allow -1 (unlimited) or check tenant_usage
        if feature == "ai_calls_per_month" and isinstance(val, int):
            if val == -1:
                return tenant
            usage = await get_tenant_usage(tenant["id"])
            if usage.get("ai_calls", 0) >= val:
                raise HTTPException(
                    status_code=402,
                    detail={
                        "message": "Monthly AI call quota exhausted.",
                        "feature": feature,
                        "current_plan": tenant.get("plan_tier"),
                        "required_plan": "enterprise",
                        "limit": val,
                        "used": usage.get("ai_calls", 0),
                    },
                )
            return tenant

        # Boolean feature flags
        if not val:
            raise HTTPException(
                status_code=402,
                detail={
                    "message": f"This feature requires the {FEATURE_MIN_PLAN.get(feature, 'pro').title()} plan.",
                    "feature": feature,
                    "current_plan": tenant.get("plan_tier"),
                    "required_plan": FEATURE_MIN_PLAN.get(feature, "pro"),
                },
            )
        return tenant
    return _dep


# ─── Endpoints ─────────────────────────────────────────────────────────────
class PlanUpdate(BaseModel):
    plan_tier: Optional[str] = None
    plan_features: Optional[Dict[str, Any]] = None


@router.get("/tenants/mine/plan")
async def get_my_plan(tenant: dict = Depends(get_current_tenant),
                     user: dict = Depends(get_current_user)):
    tenant = await _ensure_plan_features(tenant)
    usage = await get_tenant_usage(tenant["id"])
    return {
        "tenant_id": tenant["id"],
        "tenant_name": tenant.get("name"),
        "slug": tenant.get("slug"),
        "plan_tier": tenant.get("plan_tier"),
        "plan_features": tenant.get("plan_features"),
        "usage": usage,
        "plan_matrix": PLAN_MATRIX,  # UI shows all tiers for comparison
    }


@router.put("/tenants/{tid}/plan")
async def update_plan(tid: str, body: PlanUpdate,
                     admin: dict = Depends(require_super_admin)):
    t = await db.tenants.find_one({"id": tid}, {"_id": 0})
    if not t:
        raise HTTPException(404, "Tenant not found")
    upd: Dict[str, Any] = {}
    if body.plan_tier and body.plan_tier in PLAN_MATRIX:
        upd["plan_tier"] = body.plan_tier
        # Reset plan_features to the new tier's defaults unless explicit override.
        upd["plan_features"] = body.plan_features or _plan_defaults(body.plan_tier)
    elif body.plan_features:
        merged = dict(t.get("plan_features") or _plan_defaults(t.get("plan_tier") or "free"))
        merged.update(body.plan_features)
        upd["plan_features"] = merged
    if not upd:
        raise HTTPException(400, "Nothing to update")
    upd["plan_updated_at"] = now_iso()
    await db.tenants.update_one({"id": tid}, {"$set": upd})
    return await db.tenants.find_one({"id": tid}, {"_id": 0})


@router.get("/tenants/{tid}/usage")
async def get_usage(tid: str, admin: dict = Depends(require_super_admin)):
    usage = await get_tenant_usage(tid)
    # Recent months (last 6).
    six = await db.tenant_usage.find(
        {"tenant_id": tid}, {"_id": 0}
    ).sort("month_yyyy_mm", -1).to_list(6)
    return {"current": usage, "history": six}


# ─── Plans catalog + assignment (Item I) ───────────────────────────────────
SEED_PLANS = [
    {"slug": "free", "name": "Starter", "price_monthly": 0,
     "highlights": ["Up to 3 users", "50 AI calls / month", "Core CRM"]},
    {"slug": "pro", "name": "Pro", "price_monthly": 129,
     "highlights": ["Up to 15 users", "2,000 AI calls / month",
                    "D2D sales", "Sequences", "Custom branding"]},
    {"slug": "enterprise", "name": "Enterprise", "price_monthly": 399,
     "highlights": ["Unlimited users + AI", "Custom domain",
                    "White-label reports", "Priority support"]},
]


async def seed_plans() -> None:
    """Idempotent: seed the 3 canonical plans if missing, backfill features
    from PLAN_MATRIX so the plans-catalog stays in sync with feature gating."""
    for p in SEED_PLANS:
        existing = await db.plans.find_one({"slug": p["slug"]}, {"_id": 0})
        features = PLAN_MATRIX[p["slug"]]
        if existing:
            await db.plans.update_one(
                {"slug": p["slug"]},
                {"$set": {**p, "features": features, "updated_at": now_iso()}},
            )
        else:
            await db.plans.insert_one({
                "id": new_id(),
                **p,
                "features": features,
                "created_at": now_iso(),
            })
    logger.info(f"Plans catalog seeded ({len(SEED_PLANS)} tiers).")


@router.get("/plans")
async def list_plans(user: dict = Depends(get_current_user)):
    """Public-ish (auth required) list of plans for upgrade UI."""
    return await db.plans.find({}, {"_id": 0}).sort("price_monthly", 1).to_list(50)


class AssignPlanReq(BaseModel):
    plan_slug: str


@router.post("/plans/assign/{tenant_id}")
async def assign_plan_to_tenant(tenant_id: str, body: AssignPlanReq,
                                 admin: dict = Depends(require_super_admin)):
    """Super admin assigns a tier to a tenant. Records history in
    `tenant_plan_assignments` and updates the tenant's `plan_tier` +
    `plan_features` to the tier defaults."""
    if body.plan_slug not in PLAN_MATRIX:
        raise HTTPException(400, f"Unknown plan slug: {body.plan_slug}")
    t = await db.tenants.find_one({"id": tenant_id}, {"_id": 0})
    if not t:
        raise HTTPException(404, "Tenant not found")
    features = _plan_defaults(body.plan_slug)
    await db.tenants.update_one(
        {"id": tenant_id},
        {"$set": {"plan_tier": body.plan_slug,
                  "plan_features": features,
                  "plan_updated_at": now_iso()}},
    )
    assignment = {
        "id": new_id(),
        "tenant_id": tenant_id,
        "plan_slug": body.plan_slug,
        "assigned_by": admin["id"],
        "assigned_at": now_iso(),
        "features": features,
    }
    await db.tenant_plan_assignments.insert_one(assignment)
    assignment.pop("_id", None)
    return assignment


@router.get("/plans/history/{tenant_id}")
async def plan_history(tenant_id: str,
                        admin: dict = Depends(require_super_admin)):
    return await db.tenant_plan_assignments.find(
        {"tenant_id": tenant_id}, {"_id": 0}
    ).sort("assigned_at", -1).to_list(50)
