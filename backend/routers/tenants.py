"""Phase 15D — Multi-tenant foundation (Stage 1 + Stage 2).

Stage 1 (shipped): substrate — tenants collection, tenant_id backfill,
`get_current_tenant` dependency, `GET /api/tenants/current`.

Stage 2 (this file, additive):
- `super_admin` role (seat above `admin`)
- Idempotent seed of `super@aquaterra.com` on startup
- Super-admin-only CRUD: `GET/POST /api/tenants`, `GET/PATCH /api/tenants/{id}`
- Admin-only brand editor: `PATCH /api/tenants/mine/brand`
- Optional `tenant_memberships` collection for multi-tenant users

**Stage 2 does NOT refactor entity queries.** Isolation ships in Stage 3.
"""
import os
from typing import Optional, List

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

from config import db, logger
from utils import now_iso, new_id, get_current_user, hash_password

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
        "name": "Pool & Landscaping",
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
      1. `X-Tenant-Slug` header — SUPER_ADMIN ONLY may use this to cross tenants.
      2. User document's `tenant_id` (backfilled in Stage 1)
      3. `X-Tenant-Slug` header (for anonymous / non-super callers)
      4. Custom domain matching `Host` header
      5. Fallback → default tenant
    """
    tenant = None
    # 1. Super admin explicit cross-tenant override.
    if x_tenant_slug and user.get("role") == "super_admin":
        tenant = await db.tenants.find_one({"slug": x_tenant_slug, "active": True}, {"_id": 0})
    # 2. User's own tenant.
    if not tenant and user.get("tenant_id"):
        tenant = await db.tenants.find_one({"id": user["tenant_id"], "active": True}, {"_id": 0})
    # 3. Anonymous header fallback.
    if not tenant and x_tenant_slug:
        tenant = await db.tenants.find_one({"slug": x_tenant_slug, "active": True}, {"_id": 0})
    # 4. Custom domain.
    if not tenant:
        host = (request.headers.get("host") or "").split(":")[0].lower()
        if host:
            tenant = await db.tenants.find_one({"custom_domain": host, "active": True}, {"_id": 0})
    # 5. Default.
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
    # Phase 16C add-on: pricing tiers removed — every tenant gets every feature.
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


# ─── Stage 2 — Super-admin role ────────────────────────────────────────────
def require_super_admin(user: dict = Depends(get_current_user)) -> dict:
    if user.get("role") != "super_admin":
        raise HTTPException(status_code=403, detail="Super-admin access required")
    return user


async def _seed_super_admin() -> None:
    """Idempotent seed of super@aquaterra.com. Uses the default tenant so
    the account can also manage aquaterra directly."""
    existing = await db.users.find_one({"email": "super@aquaterra.com"}, {"_id": 0})
    if existing:
        # Upgrade role if seed was created before super_admin existed.
        if existing.get("role") != "super_admin":
            await db.users.update_one({"id": existing["id"]}, {"$set": {"role": "super_admin"}})
        return
    tenant = await _ensure_default_tenant()
    await db.users.insert_one({
        "id": new_id(),
        "name": "Super Admin",
        "email": "super@aquaterra.com",
        "password_hash": hash_password("password123"),
        "role": "super_admin",
        "tenant_id": tenant["id"],
        "created_at": now_iso(),
    })


# ─── Stage 2 — Tenant CRUD (super-admin only) ──────────────────────────────
class TenantCreate(BaseModel):
    name: str
    slug: str = Field(..., pattern=r"^[a-z0-9][a-z0-9-]{1,40}$")
    brand_primary: Optional[str] = "#0284C7"
    brand_secondary: Optional[str] = "#16A34A"
    custom_domain: Optional[str] = None
    plan_tier: Optional[str] = "free"


class TenantUpdate(BaseModel):
    name: Optional[str] = None
    brand_primary: Optional[str] = None
    brand_secondary: Optional[str] = None
    custom_domain: Optional[str] = None
    plan_tier: Optional[str] = None
    active: Optional[bool] = None


@router.get("/tenants")
async def list_tenants(admin: dict = Depends(require_super_admin)):
    rows = await db.tenants.find({}, {"_id": 0}).sort("created_at", -1).to_list(500)
    return rows


@router.post("/tenants")
async def create_tenant(body: TenantCreate, admin: dict = Depends(require_super_admin)):
    if await db.tenants.find_one({"slug": body.slug}, {"_id": 0}):
        raise HTTPException(400, "slug already taken")
    doc = {
        "id": new_id(),
        "name": body.name,
        "slug": body.slug,
        "brand_primary": body.brand_primary,
        "brand_secondary": body.brand_secondary,
        "custom_domain": body.custom_domain,
        "plan_tier": body.plan_tier,
        "active": True,
        "created_at": now_iso(),
    }
    await db.tenants.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.get("/tenants/{tid}")
async def get_tenant(tid: str, admin: dict = Depends(require_super_admin)):
    t = await db.tenants.find_one({"id": tid}, {"_id": 0})
    if not t:
        raise HTTPException(404, "Tenant not found")
    return t


@router.patch("/tenants/{tid}")
async def patch_tenant(tid: str, body: TenantUpdate,
                        admin: dict = Depends(require_super_admin)):
    upd = {k: v for k, v in body.dict().items() if v is not None}
    if not upd:
        raise HTTPException(400, "Nothing to update")
    if "custom_domain" in upd and upd["custom_domain"]:
        # Ensure custom_domain uniqueness.
        clash = await db.tenants.find_one(
            {"custom_domain": upd["custom_domain"], "id": {"$ne": tid}}, {"_id": 0}
        )
        if clash:
            raise HTTPException(400, "custom_domain already assigned to another tenant")
    upd["updated_at"] = now_iso()
    r = await db.tenants.update_one({"id": tid}, {"$set": upd})
    if not r.matched_count:
        raise HTTPException(404, "Tenant not found")
    return await db.tenants.find_one({"id": tid}, {"_id": 0})


# ─── Stage 2 — Admin-only brand editor (their own tenant) ─────────────────
class BrandUpdate(BaseModel):
    brand_primary: Optional[str] = None
    brand_secondary: Optional[str] = None
    logo_url: Optional[str] = None


@router.patch("/tenants/mine/brand")
async def patch_own_brand(body: BrandUpdate, user: dict = Depends(get_current_user)):
    if user.get("role") not in ("admin", "super_admin"):
        raise HTTPException(403, "Admin access required")
    tid = user.get("tenant_id")
    if not tid:
        raise HTTPException(400, "User has no tenant")
    upd = {k: v for k, v in body.dict().items() if v is not None}
    if not upd:
        raise HTTPException(400, "Nothing to update")
    upd["updated_at"] = now_iso()
    await db.tenants.update_one({"id": tid}, {"$set": upd})
    return await db.tenants.find_one({"id": tid}, {"_id": 0})


# ─── Stage 2 — Membership listing (multi-tenant users) ────────────────────
@router.get("/tenants/memberships/mine")
async def my_memberships(user: dict = Depends(get_current_user)):
    """Return every tenant this user can act on. Includes their primary
    tenant (from user.tenant_id) plus any rows in `tenant_memberships`.
    Super admins see all active tenants."""
    if user.get("role") == "super_admin":
        rows = await db.tenants.find({"active": True}, {"_id": 0}).to_list(500)
        return [{"tenant_id": r["id"], "slug": r["slug"], "name": r["name"], "role": "super_admin"} for r in rows]
    out = []
    if user.get("tenant_id"):
        t = await db.tenants.find_one({"id": user["tenant_id"]}, {"_id": 0})
        if t:
            out.append({"tenant_id": t["id"], "slug": t["slug"], "name": t["name"], "role": user.get("role")})
    memberships = await db.tenant_memberships.find({"user_id": user["id"]}, {"_id": 0}).to_list(50)
    for m in memberships:
        if any(o["tenant_id"] == m.get("tenant_id") for o in out):
            continue
        t = await db.tenants.find_one({"id": m["tenant_id"]}, {"_id": 0})
        if t:
            out.append({"tenant_id": t["id"], "slug": t["slug"], "name": t["name"], "role": m.get("role")})
    return out
