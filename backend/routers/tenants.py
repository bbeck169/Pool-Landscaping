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
import time
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
from utils import get_current_user  # noqa: F811


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
        # Phase 12 · Feb 2026 — expose the "require card on file"
        # tenant default so admin UI can render the toggle w/o an
        # extra fetch. Field is populated by boot migration on any
        # tenant that predates the phase.
        "require_card_on_file_default": bool(
            tenant.get("require_card_on_file_default", True)),
        # Batch 12C · Feb 2026 — tenant timezone + add-card-on-create
        # exposure so the settings UI can render the picker and toggle
        # without an extra fetch.
        "timezone": tenant.get("timezone") or "America/Phoenix",
        "auto_send_card_add_on_create": bool(
            tenant.get("auto_send_card_add_on_create", False)),
        "stripe_sync_last_run_at": tenant.get("stripe_sync_last_run_at"),
        "last_stripe_customer_sync_at": tenant.get("last_stripe_customer_sync_at"),
        # Feb-2026 follow-up — audit stamps so the settings UI can
        # render a "Last changed <relative> by <actor>" banner without
        # a second round-trip. ``settings_updated_by_name`` is best-
        # effort resolved from the users collection; missing/deleted
        # actor falls through as null so the UI degrades gracefully.
        "settings_updated_at": tenant.get("settings_updated_at"),
        "settings_updated_by": tenant.get("settings_updated_by"),
        "settings_updated_by_name": await _resolve_actor_name(
            tenant.get("settings_updated_by")),
    }


async def _resolve_actor_name(uid):
    """Best-effort lookup of the display name for a user id used by
    the ``settings_updated_by`` audit stamp. Returns the user's name
    (fallback: email, then id) or ``None`` when unresolvable."""
    if not uid:
        return None
    try:
        u = await db.users.find_one({"id": uid}, {"_id": 0, "name": 1, "email": 1})
    except Exception:
        return None
    if not u:
        return None
    return u.get("name") or u.get("email") or uid


# ─── Stage 2 — Super-admin role ────────────────────────────────────────────
def require_super_admin(user: dict = Depends(get_current_user)) -> dict:
    if user.get("role") != "super_admin":
        raise HTTPException(status_code=403, detail="Super-admin access required")
    return user


async def _seed_super_admin() -> None:
    """Idempotent seed of super@aquaterra.com. Uses the default tenant so
    the account can also manage aquaterra directly.

    SEC-001 hotfix: gated on `SEED_DEMO_USERS=1`. When the flag is off (the
    production default), this function short-circuits with a warning and
    does NOT create the account. Rotation of the password on an existing
    row is handled by `backend/scripts/rotate_demo_passwords.py`.
    """
    if os.environ.get("SEED_DEMO_USERS", "0") != "1":
        existing = await db.users.find_one({"email": "super@aquaterra.com"}, {"_id": 0, "id": 1})
        if not existing:
            logger.warning("SEED_DEMO_USERS=0 — skipping super_admin demo seed. "
                            "Set SEED_DEMO_USERS=1 to enable in dev/preview.")
        return
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


# ══════════════════════════════════════════════════════════════
# Feb-2026 · Item 6 — Business Card (digital vCard) — helpers
# defined BEFORE the parameterized ``/tenants/{tid}`` routes so
# ``/tenants/business-card`` doesn't get swallowed by the ``{tid}``
# matcher.
# ══════════════════════════════════════════════════════════════
_BUSINESS_CARD_DEFAULTS = {
    "aquaterra": {
        "company_name": "Pool & Landscaping of Vistancia",
        "tagline": "Your trusted local pool & landscaping pros in Vistancia.",
        "service_area": "Peoria & Vistancia, Arizona",
        "phone": "602-887-4400",
        "email": "brian@plofv.com",
        "website_url": "https://www.poolandlandscapingofvistancia.com/",
        "google_review_url": None,
        "gradient_from": "#0EA5E9",
        "gradient_to":   "#16A34A",
        "logo_url":      None,
    },
}


class BusinessCardPatch(BaseModel):
    company_name: Optional[str] = None
    tagline: Optional[str] = None
    service_area: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    website_url: Optional[str] = None
    google_review_url: Optional[str] = None
    gradient_from: Optional[str] = None
    gradient_to: Optional[str] = None
    logo_url: Optional[str] = None


async def _read_business_card(tenant: dict) -> dict:
    settings = (tenant.get("settings") or {})
    card = settings.get("business_card") or {}
    defaults = _BUSINESS_CARD_DEFAULTS.get(tenant.get("slug"), {})
    merged = {**defaults, **card}
    merged["tenant_slug"] = tenant.get("slug")
    return merged


def _admin_or_403(user: dict):
    if (user or {}).get("role") not in {"admin", "super_admin"}:
        raise HTTPException(403, "Admin only")


def _build_vcard(card: dict) -> str:
    """RFC 6350 vCard 3.0 text."""
    name = card.get("company_name") or "Business"
    phone = card.get("phone") or ""
    email = card.get("email") or ""
    url = card.get("website_url") or ""
    note = card.get("tagline") or ""
    area = card.get("service_area") or ""
    city, state = area, ""
    if "," in area:
        left, right = area.split(",", 1)
        city, state = left.strip(), right.strip()
    lines_ = [
        "BEGIN:VCARD", "VERSION:3.0",
        f"FN:{name}", f"ORG:{name}",
        f"TEL;TYPE=WORK,VOICE:{phone}" if phone else None,
        f"EMAIL;TYPE=WORK:{email}" if email else None,
        f"URL:{url}" if url else None,
        f"ADR;TYPE=WORK:;;;{city};{state};;USA" if area else None,
        f"NOTE:{note}" if note else None,
        "END:VCARD",
    ]
    return "\r\n".join([ln for ln in lines_ if ln]) + "\r\n"


@router.get("/tenants/business-card", tags=["tenants"],
             operation_id="tenants.getBusinessCard")
async def get_business_card_v2(
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    return await _read_business_card(tenant)


@router.patch("/tenants/business-card", tags=["tenants"],
                operation_id="tenants.updateBusinessCard")
async def update_business_card_v2(
    body: BusinessCardPatch,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    _admin_or_403(user)
    patch = {k: v for k, v in body.dict(exclude_none=True).items()}
    if not patch:
        raise HTTPException(400, "No fields to update")
    set_ops = {f"settings.business_card.{k}": v for k, v in patch.items()}
    await db.tenants.update_one({"id": tenant["id"]}, {"$set": set_ops})
    fresh = await db.tenants.find_one({"id": tenant["id"]}, {"_id": 0})
    return await _read_business_card(fresh)


@router.get("/tenants/business-card.vcf", tags=["tenants"],
             operation_id="tenants.downloadVcf")
async def download_vcf_v2(
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    from fastapi.responses import Response
    card = await _read_business_card(tenant)
    body = _build_vcard(card)
    filename = f"{tenant.get('slug') or 'business-card'}.vcf"
    return Response(
        content=body,
        media_type="text/vcard; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


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


# ─── Phase 12 · Feb 2026 — Tenant Payment Defaults ─────────────────────
class TenantSettingsUpdate(BaseModel):
    """Fields settable via ``PATCH /api/tenants/mine/settings``.

    Phase 12 exposed ``require_card_on_file_default``. Batch 12C adds:

      * ``timezone`` — IANA name, validated against
        ``zoneinfo.available_timezones()`` (400 on invalid).
      * ``auto_send_card_add_on_create`` — opt-in toggle for the
        Phase 12 add-card-on-create hook (default false).
    """
    require_card_on_file_default: Optional[bool] = None
    timezone: Optional[str] = None
    auto_send_card_add_on_create: Optional[bool] = None


@router.get(
    "/tenants/mine/settings",
    tags=["tenants"],
    operation_id="tenants.readSettings",
    summary="Read tenant-wide settings (admin/manager only)",
    responses={200: {"description": (
        "Canonical READ counterpart to ``PATCH /api/tenants/mine/settings`` "
        "(Phase 12 / 12B / 12C). Returns every settings field the mobile + "
        "web admin UIs read on load: card-on-file default, timezone, "
        "auto-send-card-add-on-create, equipment-service tracker toggles, "
        "SMS escalation list, and the most recent Stripe cross-reference "
        "sync stamps. Techs and customers see 403."
    )}},
)
async def get_own_settings(user: dict = Depends(get_current_user),
                            tenant: dict = Depends(get_current_tenant)):
    if user.get("role") not in ("admin", "manager", "super_admin"):
        raise HTTPException(403, "Admin or manager access required")
    return {
        "id": tenant["id"],
        "name": tenant.get("name"),
        # Phase 12 · Feb 2026
        "require_card_on_file_default": bool(
            tenant.get("require_card_on_file_default", True)),
        # Batch 12C · Feb 2026
        "timezone": tenant.get("timezone") or "America/Phoenix",
        "auto_send_card_add_on_create": bool(
            tenant.get("auto_send_card_add_on_create", False)),
        # Phase 11 · equipment tracker digest
        "equipment_service_customer_reminders_enabled": bool(
            tenant.get("equipment_service_customer_reminders_enabled", False)),
        "equipment_service_coming_due_days":
            tenant.get("equipment_service_coming_due_days"),
        # Stripe key-health + ambiguous-digest fanout list
        "sms_escalation_recipients": list(
            tenant.get("sms_escalation_recipients") or []),
        # Phase 12B stamps
        "stripe_sync_last_run_at": tenant.get("stripe_sync_last_run_at"),
        "last_stripe_customer_sync_at":
            tenant.get("last_stripe_customer_sync_at"),
        "last_stripe_customer_sync_summary":
            tenant.get("last_stripe_customer_sync_summary"),
        # Audit stamps from PATCH
        "settings_updated_at": tenant.get("settings_updated_at"),
        "settings_updated_by": tenant.get("settings_updated_by"),
        "settings_updated_by_name": await _resolve_actor_name(
            tenant.get("settings_updated_by")),
    }


@router.patch("/tenants/mine/settings", tags=["tenants"],
                operation_id="tenants.updateSettings")
async def patch_own_settings(body: TenantSettingsUpdate,
                              user: dict = Depends(get_current_user)):
    if user.get("role") not in ("admin", "super_admin"):
        raise HTTPException(403, "Admin access required")
    tid = user.get("tenant_id")
    if not tid:
        raise HTTPException(400, "User has no tenant")
    upd = {k: v for k, v in body.dict(exclude_unset=True).items() if v is not None}
    if not upd:
        raise HTTPException(400, "Nothing to update")
    # Batch 12C · Feb 2026 — validate IANA timezone if provided.
    if "timezone" in upd:
        from zoneinfo import available_timezones
        if upd["timezone"] not in available_timezones():
            raise HTTPException(400, detail={
                "code": "INVALID_TIMEZONE",
                "value": upd["timezone"],
            })
    upd["settings_updated_at"] = now_iso()
    upd["settings_updated_by"] = user.get("id")
    await db.tenants.update_one({"id": tid}, {"$set": upd})
    doc = await db.tenants.find_one({"id": tid}, {"_id": 0})
    return doc


# ─── Feb-2026 — Tenant HQ geocode ─────────────────────────────────────────
# Admin-owned single-row settings for the tenant's headquarters
# address + Google-geocoded lat/lng. Consumed by the web
# ``WeatherWidget`` (falls back to a hardcoded Peoria centroid
# when unset) so multi-tenant deployments stop sharing the same
# forecast anchor.
class HqGeocodeUpdate(BaseModel):
    address: str = Field(..., min_length=3, max_length=200)


def _require_super_admin_local(user: dict = Depends(get_current_user)) -> dict:
    """Local guard so this section doesn't have to depend on the
    forward-declared ``require_super_admin`` above (avoids Pydantic
    schema-build ordering surprises during hot reload)."""
    if user.get("role") != "super_admin":
        raise HTTPException(status_code=403, detail="Super-admin access required")
    return user


@router.get("/tenants/mine/geocode")
async def get_tenant_geocode(user: dict = Depends(_require_super_admin_local)):
    tid = user.get("tenant_id")
    if not tid:
        raise HTTPException(400, "User has no tenant")
    t = await db.tenants.find_one({"id": tid}, {"_id": 0}) or {}
    return {
        "hq_address": t.get("hq_address"),
        "hq_address_formatted": t.get("hq_address_formatted"),
        "hq_lat": t.get("hq_lat"),
        "hq_lng": t.get("hq_lng"),
        "hq_place_id": t.get("hq_place_id"),
        "hq_geocoded_at": t.get("hq_geocoded_at"),
    }


@router.patch("/tenants/mine/geocode")
async def patch_tenant_geocode(body: HqGeocodeUpdate,
                                 user: dict = Depends(_require_super_admin_local)):
    """One-shot Google Geocoding lookup — stores canonical
    ``hq_lat/hq_lng/hq_address_formatted/hq_place_id`` on the
    tenant document."""
    tid = user.get("tenant_id")
    if not tid:
        raise HTTPException(400, "User has no tenant")
    # Local import to keep this router free of a hard dep on the
    # Google router module and its config imports.
    from routers.google import _geocode_one
    import httpx as _httpx
    address = (body.address or "").strip()
    if not address:
        raise HTTPException(400, "address is required")
    async with _httpx.AsyncClient(timeout=15) as c:
        geo = await _geocode_one(c, address)
    if not geo or geo.get("lat") is None or geo.get("lng") is None:
        raise HTTPException(422, "Google could not geocode this address")
    patch = {
        "hq_address": address,
        "hq_address_formatted": geo.get("formatted"),
        "hq_lat": float(geo["lat"]),
        "hq_lng": float(geo["lng"]),
        "hq_place_id": geo.get("place_id"),
        "hq_geocoded_at": now_iso(),
        "updated_at": now_iso(),
    }
    await db.tenants.update_one({"id": tid}, {"$set": patch})
    t = await db.tenants.find_one({"id": tid}, {"_id": 0}) or {}
    return {
        "hq_address": t.get("hq_address"),
        "hq_address_formatted": t.get("hq_address_formatted"),
        "hq_lat": t.get("hq_lat"),
        "hq_lng": t.get("hq_lng"),
        "hq_place_id": t.get("hq_place_id"),
        "hq_geocoded_at": t.get("hq_geocoded_at"),
    }


# ─── Feb-2026 — Tenant HQ read for weather widget ──────────────────────
# Admins + techs need read access to the HQ geocode so the weather
# widget can anchor forecasts on the tenant's location. Only
# lat/lng are exposed here — the address details are super-admin
# only via ``/tenants/mine/geocode`` above.
@router.get("/tenants/mine/location")
async def get_tenant_location(user: dict = Depends(get_current_user)):
    role = user.get("role")
    if role not in ("admin", "super_admin", "technician"):
        raise HTTPException(status_code=403, detail="Not authorised")
    tid = user.get("tenant_id")
    if not tid:
        return {"hq_lat": None, "hq_lng": None}
    t = await db.tenants.find_one({"id": tid}, {"_id": 0}) or {}
    return {
        "hq_lat": t.get("hq_lat"),
        "hq_lng": t.get("hq_lng"),
        "hq_address_formatted": t.get("hq_address_formatted"),
    }


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


# ══════════════════════════════════════════════════════════════
# Feb-2026 · Item 6 — Business Card (digital vCard)
# ══════════════════════════════════════════════════════════════
