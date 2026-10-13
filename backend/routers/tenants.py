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
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional, List

from fastapi import APIRouter, Depends, Header, HTTPException, Request, UploadFile, File
from pydantic import BaseModel, Field, field_validator

from config import db, logger
from utils import now_iso, new_id, get_current_user, hash_password

router = APIRouter()

DEFAULT_TENANT_SLUG = "aquaterra"  # canonical slug — kept for backward compat with existing FKs / links / NFC URLs
DEFAULT_TENANT_SLUG_ALIASES = ["plofv"]  # Phase 21 · Feb 2026 — new brand aliases resolve to same tenant

# ═════════════════════════════════════════════════════════════════════
# Phase P15 · Feb-2026 — Permanent Tenant Timezone Setting.
#
# Curated whitelist of allowed IANA timezones with human-readable
# labels.  Exposed by ``GET /api/tenants/timezones`` and enforced by
# the ``PATCH /api/tenants/mine/settings`` validator.  Order matters
# — the frontend picker renders in this exact order (US-East → West
# → Alaska → Arizona → Hawaii).
#
# READ-side compat: existing tenants with a legacy value (``UTC``,
# ``America/Denver`` without label, etc.) still round-trip on GET.
# The whitelist ONLY gates WRITE via PATCH — no data migration on
# read, no forced re-save.  BusinessSettings renders a synthetic
# disabled "(legacy)" option for tenants whose stored value isn't
# in this list.
#
# Keep in sync with:
#   * frontend/src/components/settings/TimezoneSelect.jsx :: TIMEZONE_OPTIONS
# ═════════════════════════════════════════════════════════════════════
TIMEZONE_OPTIONS: List[dict] = [
    {"value": "America/New_York",    "label": "Eastern Time (ET)"},
    {"value": "America/Chicago",     "label": "Central Time (CT)"},
    {"value": "America/Denver",      "label": "Mountain Time (MT)"},
    {"value": "America/Los_Angeles", "label": "Pacific Time (PT)"},
    {"value": "America/Anchorage",   "label": "Alaska Time"},
    {"value": "America/Phoenix",     "label": "Arizona (No DST)"},
    {"value": "Pacific/Honolulu",    "label": "Hawaii (No DST)"},
]
_ALLOWED_TIMEZONE_VALUES = frozenset(o["value"] for o in TIMEZONE_OPTIONS)

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

    Phase 21 · Feb 2026 — slug lookups also honour ``slug_aliases`` so
    the Vistancia rebrand can accept ``plofv`` in addition to the
    canonical ``aquaterra`` slug without a data migration on foreign
    keys.
    """
    tenant = None
    # Phase T1.2 · Feb-2026 — JWT-signed ``active_tenant_id`` claim
    # for multi-tenant users takes precedence over ``user.tenant_id``.
    # ``services.user_tenants.token_active_tenant_id`` raises 403
    # ``stale_tenant_membership`` when the claim references a tenant
    # the user is no longer in (defensive posture requested by user).
    from services.user_tenants import token_active_tenant_id
    _atid = token_active_tenant_id(
        user, claim=user.get("_active_tenant_id_claim"))
    if _atid:
        tenant = await db.tenants.find_one(
            {"id": _atid, "active": True}, {"_id": 0})
    # 1. Super admin explicit cross-tenant override.
    if not tenant and x_tenant_slug and user.get("role") == "super_admin":
        tenant = await _find_tenant_by_slug_or_alias(x_tenant_slug, active_only=True)
    # 2. User's own tenant.
    if not tenant and user.get("tenant_id"):
        tenant = await db.tenants.find_one({"id": user["tenant_id"], "active": True}, {"_id": 0})
    # 3. Anonymous header fallback.
    if not tenant and x_tenant_slug:
        tenant = await _find_tenant_by_slug_or_alias(x_tenant_slug, active_only=True)
    # 4. Custom domain.
    if not tenant:
        host = (request.headers.get("host") or "").split(":")[0].lower()
        if host:
            tenant = await db.tenants.find_one({"custom_domain": host, "active": True}, {"_id": 0})
    # 5. Default.
    if not tenant:
        tenant = await _ensure_default_tenant()
    return tenant


async def _find_tenant_by_slug_or_alias(slug: str, active_only: bool = True) -> Optional[dict]:
    """Phase 21 — tenant lookup that tolerates ``slug_aliases``.

    Prefers the canonical ``slug`` match; falls back to ``slug_aliases``
    array membership. Returns ``None`` when nothing matches.
    """
    if not slug:
        return None
    q: dict = {"$or": [{"slug": slug}, {"slug_aliases": slug}]}
    if active_only:
        q["active"] = True
    return await db.tenants.find_one(q, {"_id": 0})


# ─── Endpoints ───────────────────────────────────────────────────────────────
@router.get("/tenants/current")
async def current_tenant(request: Request,
                         tenant: dict = Depends(get_current_tenant),
                         user: dict = Depends(get_current_user)):
    resolved_via = "user-record" if user.get("tenant_id") == tenant["id"] else \
                   ("header" if request.headers.get("x-tenant-slug") else "default")
    # Phase 16C add-on: pricing tiers removed — every tenant gets every feature.
    # Feb-2026 UI Polish Addendum — surface tenant branding on this
    # canonical GET so the web shell's `<BrandLogo>` can honour a
    # per-tenant override without a second round-trip. The `branding`
    # object is the forward-facing shape (matches spec
    # ``tenant?.branding?.logo_url``); the top-level ``logo_url`` is
    # kept for legacy callers that predate the object shape.
    _logo_url = tenant.get("logo_url") or (
        (tenant.get("settings") or {}).get("business_card", {}).get("logo_url")
    )
    return {
        "id": tenant["id"],
        "slug": tenant["slug"],
        "name": tenant["name"],
        "brand_primary": tenant.get("brand_primary"),
        "brand_secondary": tenant.get("brand_secondary"),
        "custom_domain": tenant.get("custom_domain"),
        "plan_tier": tenant.get("plan_tier"),
        "logo_url": _logo_url,
        "branding": {
            "logo_url": _logo_url,
            "brand_primary": tenant.get("brand_primary"),
            "brand_secondary": tenant.get("brand_secondary"),
        },
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
        # Feb-2026 enhancement — the same audit-stamp pair for the
        # brand-logo file (populated on POST /tenants/branding/logo).
        # BrandLogoSettings renders "Last changed <relative> by
        # <actor>" beneath the preview when both fields are present;
        # otherwise the line hides entirely.
        "logo_updated_at": tenant.get("logo_updated_at"),
        "logo_updated_by": tenant.get("logo_updated_by_user_id"),
        "logo_updated_by_name": await _resolve_actor_name(
            tenant.get("logo_updated_by_user_id")),
        # Feb-2026 · K9 Enhancement B — expose the two config fields
        # the Admin Customer Inbox reads to decide whether to show the
        # "SMS notifications aren't wired up" banner.  Both are safe to
        # surface to any admin user (already editable via
        # ``PATCH /tenants/{id}`` from NotificationPrefs).  Missing
        # values return null so the FE can trigger the hint.
        "admin_sms_notify_to": tenant.get("admin_sms_notify_to") or None,
        "rc_sms_from_number": tenant.get("rc_sms_from_number") or None,
        # Feb-2026 · Multi-industry Phase A — the set of verticals
        # this tenant serves. Populated by boot migration; unset
        # tenants surface an empty list until the migration runs.
        "industries": list(tenant.get("industries") or []),
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
    # Phase K9 · Feb-2026 — admin SMS phone to receive portal-chat pings.
    # E.164 (e.g. ``+16028874400``) or null to clear. Top-level tenant
    # field (mirrors ``rc_sms_from_number``), NOT under settings.*.
    admin_sms_notify_to: Optional[str] = None

    @field_validator("admin_sms_notify_to")
    @classmethod
    def _validate_admin_sms_e164(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        v = v.strip()
        if not v:
            # Explicit "" clears the field — treat as null.
            return None
        import re as _re
        if not _re.match(r"^\+\d{10,15}$", v):
            raise ValueError(
                "admin_sms_notify_to must be an E.164 phone number "
                "(e.g. +16028874400), or null to clear."
            )
        return v


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
        # Feb-2026 · Source-of-truth flip. Was ``brian@plofv.com`` —
        # user confirmed outbound emails should use the customer-
        # service alias. Kept in code so fresh tenants + fallback
        # paths always land on the correct address.
        "email": "cs@plofv.com",
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

    # Phase 34 · Task GG · Feb 2026 — server-side validation of the
    # Google review URL. Must be https and look like a Google Business
    # review link. We intentionally accept both the ``g.page/r/XYZ/review``
    # short-code form AND the longer ``google.com/maps/…/review``
    # canonical form since tenants copy whichever their GBP dashboard
    # gives them.
    google_url = patch.get("google_review_url")
    if google_url is not None and google_url != "":
        gu = str(google_url).strip()
        if not gu.startswith("https://"):
            raise HTTPException(422, "google_review_url must start with https://")
        lower = gu.lower()
        allowed_hosts = (
            "https://g.page/r/",
            "https://www.google.com/maps",
            "https://google.com/maps",
            "https://maps.app.goo.gl/",
            "https://search.google.com/local/writereview",
        )
        if not any(lower.startswith(prefix) for prefix in allowed_hosts):
            raise HTTPException(
                422,
                "google_review_url must be a Google Business Profile review link "
                "(g.page/r/…/review, google.com/maps/…/review, "
                "search.google.com/local/writereview, or maps.app.goo.gl/…)",
            )
        patch["google_review_url"] = gu

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


# Feb-2026 · Item 8 — lightweight review summary for the BusinessCard
# rating pill. Aggregates only ``is_public=true`` reviews so pending
# private feedback never inflates the average.
@router.get("/tenants/reviews-summary", tags=["tenants"],
             operation_id="tenants.reviewsSummary")
async def tenants_reviews_summary(
    tenant: dict = Depends(get_current_tenant),
):
    """Public-ish (still auth-gated) rollup: {avg, count} for a
    tenant's public reviews. Callers must render conditionally on
    ``count >= 5`` per Item 8 spec so the pill only shows once
    there's a meaningful sample."""
    pipeline = [
        {"$match": {"tenant_id": tenant["id"], "is_public": True,
                     "star_rating": {"$gte": 1, "$lte": 5}}},
        {"$group": {"_id": None,
                     "count": {"$sum": 1},
                     "avg": {"$avg": "$star_rating"}}},
    ]
    rows = await db.reviews.aggregate(pipeline).to_list(1)
    if not rows:
        return {"count": 0, "avg": None}
    r = rows[0]
    return {"count": int(r.get("count") or 0),
             "avg": round(float(r.get("avg") or 0.0), 2)}


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
    # Feb 2026 · Task B — seed the 3 canonical system-template
    # sequences on every new tenant. Idempotent — the helper checks
    # per (tenant_id, system_template_id) before inserting so a
    # re-run doesn't double-seed. Errors don't block tenant creation.
    try:
        from services.migrations.seed_system_templates import (
            seed_system_templates_for_tenant,
        )
        _seed_report = await seed_system_templates_for_tenant(doc["id"])
        logger.info(
            "[tenant.provision] seeded system templates for %s: %s",
            doc["id"], _seed_report,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "[tenant.provision] system-template seed failed for %s: %s",
            doc["id"], e,
        )
    # Feb-2026 · Quote/Estimate email — idempotent per-tenant seed of
    # the ``quote_estimate_email`` system template. Fail-soft so a
    # seed error here cannot block tenant provisioning.
    try:
        from services.migrations.seed_quote_estimate_template import (
            seed_for_tenant as _seed_quote_tpl,
        )
        _quote_report = await _seed_quote_tpl(doc["id"])
        logger.info(
            "[tenant.provision] seeded quote_estimate_email for %s: %s",
            doc["id"], _quote_report,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "[tenant.provision] quote_estimate_email seed failed for %s: %s",
            doc["id"], e,
        )
    return doc


@router.get(
    "/tenants/timezones",
    tags=["tenants"],
    operation_id="tenants.listTimezones",
    summary="List curated allowed IANA timezones for the tenant picker.",
)
async def list_timezones(user: dict = Depends(get_current_user)):
    """Phase P15 · Feb-2026 — return the curated 7-entry timezone
    whitelist that the Business Settings picker consumes.  Read-only,
    no admin gate — any authenticated tenant user (including
    technicians) can fetch this so mobile / read-only shells can
    stay in sync.  The order returned matches the render order the
    picker uses (US-East → West → Alaska → Arizona → Hawaii).
    """
    return {"timezones": TIMEZONE_OPTIONS}


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
    # Phase H2 · Feb-2026 (F5 Wave 2) — audit tenant deactivations so
    # ops has a trail of who turned a tenant offline. Only fires on
    # the active=True → False transition; reactivations are logged
    # by the pre-existing update timestamp and are non-destructive.
    _pre_active = None
    if "active" in upd and upd["active"] is False:
        _pre = await db.tenants.find_one(
            {"id": tid}, {"_id": 0, "active": 1, "slug": 1},
        )
        _pre_active = (_pre or {}).get("active")
    r = await db.tenants.update_one({"id": tid}, {"$set": upd})
    if not r.matched_count:
        raise HTTPException(404, "Tenant not found")
    if _pre_active is True and upd.get("active") is False:
        try:
            await db.audit_events.insert_one({
                "id": new_id(),
                "event_type": "tenant_deactivate",
                "tenant_id": tid,
                "tenant_slug": (_pre or {}).get("slug"),
                "actor_user_id": (admin or {}).get("id"),
                "actor_email": (admin or {}).get("email"),
                "timestamp": now_iso(),
            })
        except Exception as _ae:
            logger.warning(f"[h2] tenant_deactivate audit failed: {_ae}")
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


# ══════════════════════════════════════════════════════════════
# Feb-2026 · TD-08 promoted — Admin logo upload UI.
#
# Two multipart endpoints that let admins swap the app-shell brand
# logo without a manual file drop:
#
#   * POST   /api/tenants/branding/logo   — upload + stamp
#     ``tenant.logo_url`` (top-level, matches the shape read by
#     ``useTenantBrand`` and the ``GET /tenants/current`` response).
#   * DELETE /api/tenants/branding/logo   — clear ``tenant.logo_url``
#     back to null. Object-storage GC is best-effort — a storage
#     failure never blocks the delete.
#
# Both endpoints are admin/super_admin gated (techs + customers see
# 403). Uploads are validated for MIME (png/svg/webp/jpeg), max
# size 2 MB. The stored path lives under Emergent Object Storage
# scoped to the caller's tenant so cross-tenant reads never happen.
# ══════════════════════════════════════════════════════════════
_LOGO_MAX_BYTES = 2 * 1024 * 1024  # 2 MB — matches spec.
_LOGO_ALLOWED_MIME = {
    "image/png": "png",
    "image/svg+xml": "svg",
    "image/webp": "webp",
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
}


def _extension_for(content_type: str, filename: Optional[str]) -> Optional[str]:
    """Resolve a canonical file extension from MIME first, name fallback."""
    ct = (content_type or "").strip().lower().split(";")[0]
    ext = _LOGO_ALLOWED_MIME.get(ct)
    if ext:
        return ext
    if filename and "." in filename:
        tail = filename.rsplit(".", 1)[-1].lower()
        if tail in {"png", "svg", "webp", "jpg", "jpeg"}:
            return "jpg" if tail == "jpeg" else tail
    return None


@router.post(
    "/tenants/branding/logo",
    tags=["tenants"],
    operation_id="tenants.branding.uploadLogo",
    summary="Upload a new brand logo for the caller's tenant.",
    responses={
        200: {"description": "Logo persisted and tenant record updated."},
        403: {"description": "Not admin / super_admin."},
        413: {"description": "File exceeds 2 MB."},
        415: {"description": "Unsupported MIME type."},
        503: {"description": "Object storage unavailable."},
    },
)
async def upload_branding_logo(
    logo: UploadFile = File(..., description="PNG / SVG / WEBP / JPEG under 2 MB"),
    user: dict = Depends(get_current_user),
):
    """Persist ``logo`` to Emergent Object Storage under
    ``poolcrm/<tenant_id>/branding/logo/<uuid>.<ext>`` and stamp
    ``tenant.logo_url`` with the resolvable ``/api/objects/<path>``
    URL so ``useTenantBrand`` picks it up on next fetch.
    """
    _admin_or_403(user)
    tid = user.get("tenant_id")
    if not tid:
        raise HTTPException(400, "User has no tenant")

    # ── Validate MIME + extension.
    ext = _extension_for(logo.content_type or "", logo.filename)
    if not ext:
        raise HTTPException(415, {
            "error": "unsupported_media_type",
            "error_code": "unsupported_media_type",
            "content_type": logo.content_type,
            "message": "Logo must be PNG, SVG, WEBP, or JPEG.",
        })

    # ── Read + enforce max size.
    data = await logo.read()
    size = len(data or b"")
    if size == 0:
        raise HTTPException(400, {
            "error": "empty_file",
            "error_code": "empty_file",
            "message": "Uploaded file is empty.",
        })
    if size > _LOGO_MAX_BYTES:
        raise HTTPException(413, {
            "error": "file_too_large",
            "error_code": "file_too_large",
            "size_bytes": size,
            "max_bytes": _LOGO_MAX_BYTES,
            "message": f"Logo file exceeds the {_LOGO_MAX_BYTES // (1024 * 1024)} MB limit.",
        })

    # ── Persist to Emergent Object Storage.
    try:
        from services import object_storage as _obj
    except Exception as exc:                                        # noqa: BLE001
        raise HTTPException(503, f"object_storage_import_failed: {exc}")
    if not _obj.is_ready():
        try:
            _obj.init_storage()
        except Exception:                                            # noqa: BLE001
            pass
    if not _obj.is_ready():
        raise HTTPException(503, {
            "error": "object_storage_not_initialised",
            "error_code": "object_storage_unavailable",
            "message": "Object storage is not available right now — retry in a minute.",
        })

    filename = f"{uuid.uuid4().hex}.{ext}"
    storage_path = _obj.build_path(
        tenant_id=tid, entity_kind="branding",
        entity_id="logo", filename=filename,
    )
    content_type = logo.content_type or f"image/{'svg+xml' if ext == 'svg' else ext}"
    try:
        _obj.put_object(storage_path, data, content_type)
    except Exception as exc:                                        # noqa: BLE001
        raise HTTPException(502, f"object_storage_put_failed: {exc}")

    logo_url = f"/api/objects/{storage_path}"
    updated_at = now_iso()

    # ── Look up the prior logo path so we can attempt to GC it.
    prior = await db.tenants.find_one(
        {"id": tid}, {"_id": 0, "logo_url": 1, "logo_object_path": 1},
    ) or {}
    prior_path = prior.get("logo_object_path")

    # ── Stamp the tenant. Store both the public URL (consumed by the
    #    frontend) and the underlying object path (used by the DELETE
    #    endpoint below to GC the blob).
    await db.tenants.update_one(
        {"id": tid},
        {"$set": {
            "logo_url": logo_url,
            "logo_object_path": storage_path,
            "logo_content_type": content_type,
            "logo_size_bytes": size,
            "logo_updated_at": updated_at,
            "logo_updated_by_user_id": user.get("id"),
            "updated_at": updated_at,
        }},
    )

    # ── Best-effort GC of the previous blob so we don't accumulate
    #    orphans. Never fail the request on a delete miss.
    if prior_path and prior_path != storage_path:
        try:
            _obj.delete_object(prior_path)
        except Exception as exc:                                    # noqa: BLE001
            logger.warning(
                "[branding.logo] prior blob GC failed for tenant=%s path=%s: %s",
                tid, prior_path, exc,
            )

    logger.info(
        "[branding.logo] tenant=%s uploaded logo (%d bytes, %s) by %s",
        tid, size, content_type, user.get("email") or user.get("id"),
    )
    return {
        "logo_url": logo_url,
        "size_bytes": size,
        "content_type": content_type,
        "updated_at": updated_at,
    }


@router.delete(
    "/tenants/branding/logo",
    tags=["tenants"],
    operation_id="tenants.branding.clearLogo",
    summary="Clear the tenant brand logo (revert to placeholder).",
)
async def clear_branding_logo(user: dict = Depends(get_current_user)):
    """Set ``tenant.logo_url`` to null. Object-storage cleanup is
    best-effort — the tenant record clears regardless of GC success.
    """
    _admin_or_403(user)
    tid = user.get("tenant_id")
    if not tid:
        raise HTTPException(400, "User has no tenant")

    row = await db.tenants.find_one(
        {"id": tid}, {"_id": 0, "logo_url": 1, "logo_object_path": 1},
    ) or {}
    prior_path = row.get("logo_object_path")
    updated_at = now_iso()

    await db.tenants.update_one(
        {"id": tid},
        {
            "$set": {
                "logo_url": None,
                "logo_object_path": None,
                "logo_content_type": None,
                "logo_size_bytes": None,
                "logo_updated_at": updated_at,
                "logo_updated_by_user_id": user.get("id"),
                "updated_at": updated_at,
            },
        },
    )

    if prior_path:
        try:
            from services import object_storage as _obj
            if _obj.is_ready():
                _obj.delete_object(prior_path)
        except Exception as exc:                                    # noqa: BLE001
            logger.warning(
                "[branding.logo] delete: prior blob GC failed for tenant=%s "
                "path=%s: %s", tid, prior_path, exc,
            )

    logger.info(
        "[branding.logo] tenant=%s cleared logo by %s",
        tid, user.get("email") or user.get("id"),
    )
    return {"cleared": True, "logo_url": None, "updated_at": updated_at}


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
    # Feb-2026 · Phase B — email + SMS fanout gate for top-level
    # decline. Default True (nothing set on the tenant doc counts as
    # True too via ``.get("notify_admin_on_decline", True)`` on the
    # read path).
    notify_admin_on_decline: Optional[bool] = None
    # Feb-2026 · Phase C — signature-before-approve gate. When True,
    # customers cannot approve a quote/estimate until they've signed
    # (``signature_status == "signed"``). Default False — unset
    # tenants preserve legacy behaviour where Approve does not
    # require a signature.
    require_signature_before_approve: Optional[bool] = None
    # Feb-2026 · Multi-industry Phase A — the set of verticals this
    # tenant serves. Each entry must appear in
    # ``services.industries.INDUSTRIES``. Empty list keeps the
    # tenant on the default single-industry pipeline; the Phase A
    # migration seeds ``["pools"]`` on any tenant missing the field.
    industries: Optional[List[str]] = None
    # Phase D5 · Feb-2026 — tenant-wide default locale for outbound
    # customer email + SMS bodies. Whitelisted to the D5 set
    # (``en`` / ``es`` / ``fr``); passing ``None`` clears the
    # override so the ultimate ``en`` fallback kicks in.
    # Admin notifications ALWAYS remain English regardless of this
    # value — see ``services.i18n_notifications.resolve_recipient_locale``.
    default_locale: Optional[str] = None
    # WELCOME-EMAIL-ON-FIRST-ACCEPTED-QUOTE · Feb-2026 — tenant-wide
    # kill switch for the one-off welcome email fired when a
    # customer accepts their first quote.  Default True (unset
    # tenants send the welcome).  Mirror of the ``notify_admin_on_decline``
    # pattern above.
    welcome_email_on_first_accepted_quote_enabled: Optional[bool] = None
    # P2 #10d · Feb-2026 — tenant-wide kill switches for the four
    # P2 #10 scope automations. All default True (unset tenants
    # preserve legacy behavior — opt-out, not opt-in). Mirror the
    # ``notify_admin_on_decline`` / ``welcome_email_on_first_accepted_quote_enabled``
    # pattern. Pair with the Commit-3 ``TransactionalTemplates``
    # editor — a tenant can both customize the body AND disable the
    # fire from Settings → Notifications.
    lead_conversion_welcome_enabled: Optional[bool] = None
    completion_followup_sms_enabled: Optional[bool] = None
    invoice_past_due_enabled: Optional[bool] = None
    estimate_reminder_enabled: Optional[bool] = None


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
        # Feb-2026 · Phase B — top-level decline email + SMS fanout
        # gate. Default True; only False when the tenant admin
        # explicitly flipped the toggle in Settings → Notifications.
        "notify_admin_on_decline": bool(
            tenant.get("notify_admin_on_decline", True)),
        # Feb-2026 · Phase C — signature-before-approve gate.
        # Default False; unset tenants preserve legacy Approve
        # behaviour (no signature required).
        "require_signature_before_approve": bool(
            tenant.get("require_signature_before_approve", False)),
        # WELCOME-EMAIL-ON-FIRST-ACCEPTED-QUOTE · Feb-2026 —
        # tenant-wide kill switch for the first-accept welcome
        # email.  Default True (unset tenants send the welcome).
        "welcome_email_on_first_accepted_quote_enabled": bool(
            tenant.get(
                "welcome_email_on_first_accepted_quote_enabled",
                True,
            )),
        # P2 #10d · Feb-2026 — 4 automation kill switches, all
        # defaulting True on unset (opt-out posture, mirrors the
        # welcome + decline flags above).
        "lead_conversion_welcome_enabled": bool(
            tenant.get("lead_conversion_welcome_enabled", True)),
        "completion_followup_sms_enabled": bool(
            tenant.get("completion_followup_sms_enabled", True)),
        "invoice_past_due_enabled": bool(
            tenant.get("invoice_past_due_enabled", True)),
        "estimate_reminder_enabled": bool(
            tenant.get("estimate_reminder_enabled", True)),
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
        # Feb-2026 · Multi-industry Phase A — mirror the array on the
        # canonical settings READ so the admin surface (Phase B) can
        # render its multi-select in a single round-trip.
        "industries": list(tenant.get("industries") or []),
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
    # Phase P15 · Feb-2026 — Permanent Tenant Timezone Setting.
    # Validate against the curated 7-entry whitelist (was: any IANA
    # name from ``available_timezones()``).  Keep the same 400 detail
    # shape as before for existing FE consumers, plus surface the
    # allowed values so admins can see what to pick.
    if "timezone" in upd:
        if upd["timezone"] not in _ALLOWED_TIMEZONE_VALUES:
            raise HTTPException(400, detail={
                "code": "INVALID_TIMEZONE",
                "value": upd["timezone"],
                "message": (
                    "Timezone must be one of the allowed IANA values."
                ),
                "allowed": [o["value"] for o in TIMEZONE_OPTIONS],
            })
    # Feb-2026 · Multi-industry Phase A — validate the industries
    # array before persisting. First invalid slug wins the error
    # message so clients can highlight the offending checkbox.
    if "industries" in upd:
        from services.industries import normalize_industries
        raw = upd["industries"]
        if not isinstance(raw, list):
            raise HTTPException(422, detail={
                "code": "invalid_industries_shape",
                "message": "industries must be a list of strings",
            })
        valid, invalid = normalize_industries(raw)
        if invalid:
            raise HTTPException(422, detail={
                "code": f"invalid_industry: {invalid[0]}",
                "invalid": invalid,
            })
        upd["industries"] = valid
    # Phase D5 · Feb-2026 — validate default_locale against the D5
    # whitelist. ``None`` is allowed (clears the override).
    if "default_locale" in upd:
        from services.i18n_notifications import SUPPORTED_LOCALES
        raw = upd["default_locale"]
        if raw is not None:
            loc = str(raw).strip().lower()
            if loc not in SUPPORTED_LOCALES:
                raise HTTPException(422, detail={
                    "code": "invalid_default_locale",
                    "supported": sorted(SUPPORTED_LOCALES),
                    "received": raw,
                })
            upd["default_locale"] = loc
    upd["settings_updated_at"] = now_iso()
    upd["settings_updated_by"] = user.get("id")
    await db.tenants.update_one({"id": tid}, {"$set": upd})
    doc = await db.tenants.find_one({"id": tid}, {"_id": 0})
    return doc


# ═════════════════════════════════════════════════════════════════════
# LDM-A · Feb-2026 — Tenant automation rules.
#
# The four fields below feed two downstream services that ship in
# later sub-phases of the AI Live Dispatcher + Predictive Maintenance
# track (see ``memory/SPEC_LIVE_DISPATCHER_AND_MAINTENANCE.md``):
#
#   * ``services/live_dispatcher.py`` — reads
#     ``dispatch_delay_threshold_mins`` +
#     ``dispatch_sms_customer_count`` on every 5-minute scan.
#   * ``services/maintenance_scanner.py`` — reads
#     ``filter_clean_interval_months`` +
#     ``salt_cell_replacement_months`` on every daily scan.
#
# LDM-A only lands the persistence layer + admin edit endpoint.
# LDM-B / LDM-C wire the services themselves.
#
# Persistence lives under ``tenant.settings.automation_rules.{key}``
# (dotted-path mongo write, matching the ``settings.business_card``
# pattern already in this file). The backfill migration is at
# ``backend/migrations/automation_rules_v1.py`` — sentinel-gated
# via ``migration_status[key="automation_rules_v1"]``.
#
# Range bounds enforced at the Pydantic layer per the LDM-A brief:
#   * dispatch_delay_threshold_mins  : 1 – 240   (1 min → 4 hours)
#   * dispatch_sms_customer_count    : 1 – 10
#   * filter_clean_interval_months   : 1 – 24    (1 month → 2 years)
#   * salt_cell_replacement_months   : 12 – 120  (1 year → 10 years)
# ═════════════════════════════════════════════════════════════════════
AUTOMATION_RULE_DEFAULTS: dict = {
    "dispatch_delay_threshold_mins": 20,
    "dispatch_sms_customer_count": 3,
    "filter_clean_interval_months": 6,
    "salt_cell_replacement_months": 36,
}


class AutomationRulesPatch(BaseModel):
    """Partial-update payload for ``PATCH /tenants/mine/automation-rules``.

    All four fields are optional so an admin can nudge one slider at
    a time. Ranges enforced by Pydantic — an out-of-range value gets
    422 at request-body validation before the handler runs.
    """
    dispatch_delay_threshold_mins: Optional[int] = Field(
        None, ge=1, le=240,
        description=(
            "Minutes of projected delay before MARCO fans out "
            "customer SMS. Range 1–240 (up to 4 hours)."
        ),
    )
    dispatch_sms_customer_count: Optional[int] = Field(
        None, ge=1, le=10,
        description=(
            "How many next-in-route customers get the delay SMS "
            "when the threshold is breached. Range 1–10."
        ),
    )
    filter_clean_interval_months: Optional[int] = Field(
        None, ge=1, le=24,
        description=(
            "Months since last filter clean before the predictive-"
            "maintenance scanner drafts a cross-sell action. "
            "Range 1–24."
        ),
    )
    salt_cell_replacement_months: Optional[int] = Field(
        None, ge=12, le=120,
        description=(
            "Months since last salt-cell replacement before the "
            "predictive-maintenance scanner drafts a cross-sell "
            "action. Range 12–120 (1–10 years)."
        ),
    )


def _read_automation_rules(tenant: dict) -> dict:
    """Return the automation-rules block hydrated with defaults.

    Falls back to ``AUTOMATION_RULE_DEFAULTS`` per-field so a pod
    that comes up before the ``automation_rules_v1`` migration
    lands still serves a sane API response. Audit stamps
    (``updated_at`` / ``updated_by``) are surfaced only when the
    field is actually set.
    """
    rules = ((tenant.get("settings") or {}).get("automation_rules") or {})
    out: dict = {**AUTOMATION_RULE_DEFAULTS}
    for k in AUTOMATION_RULE_DEFAULTS:
        if k in rules and rules[k] is not None:
            out[k] = rules[k]
    if "updated_at" in rules:
        out["updated_at"] = rules["updated_at"]
    if "updated_by" in rules:
        out["updated_by"] = rules["updated_by"]
    return out


@router.get(
    "/tenants/mine/automation-rules", tags=["tenants"],
    operation_id="tenants.readAutomationRules",
    summary="Read tenant automation rules (admin/manager only)",
)
async def get_own_automation_rules(
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    if user.get("role") not in ("admin", "manager", "super_admin"):
        raise HTTPException(403, "Admin or manager access required")
    return _read_automation_rules(tenant)


@router.patch(
    "/tenants/mine/automation-rules", tags=["tenants"],
    operation_id="tenants.updateAutomationRules",
    summary="Update tenant automation rules (admin only)",
)
async def patch_own_automation_rules(
    request: Request,
    body: AutomationRulesPatch,
    user: dict = Depends(get_current_user),
):
    # Role gate — techs / customers / members can't flip automation.
    if user.get("role") not in ("admin", "super_admin"):
        raise HTTPException(403, "Admin access required")
    tid = user.get("tenant_id")
    if not tid:
        raise HTTPException(400, "User has no tenant")
    # LDM-A cross-tenant safety — body-supplied ``tenant_id`` is a
    # forgery attempt. The JWT session is the only source of truth
    # for tenant scoping; even echoing the caller's own tenant back
    # in the body is rejected loudly so the frontend never grows a
    # habit of sending it. Read raw payload once, check for the
    # forbidden key, then let the Pydantic body finish validation.
    try:
        raw = await request.json()
    except Exception:  # noqa: BLE001
        raw = {}
    if isinstance(raw, dict) and "tenant_id" in raw:
        raise HTTPException(
            403,
            "tenant_id is derived from JWT; body-supplied tenant_id "
            "is forbidden.",
        )
    upd: dict = {}
    for k, v in body.dict(exclude_unset=True).items():
        if v is not None:
            upd[f"settings.automation_rules.{k}"] = v
    if not upd:
        raise HTTPException(400, "Nothing to update")
    upd["settings.automation_rules.updated_at"] = now_iso()
    upd["settings.automation_rules.updated_by"] = user.get("id")
    await db.tenants.update_one({"id": tid}, {"$set": upd})
    doc = await db.tenants.find_one({"id": tid}, {"_id": 0})
    return _read_automation_rules(doc or {})


# ═════════════════════════════════════════════════════════════════════
# LS-A · Feb-2026 — MARCO Lead-Sense tenant field.
#
# Persistence lives directly on the tenant document (top-level fields,
# NOT inside ``settings``) so LS-B's ``/api/lead-sense/track`` intake
# can resolve tenants via a unique index on ``marco_lead_sense_id``
# without descending into a sub-document. The backfill migration at
# ``backend/migrations/marco_lead_sense_id_v1.py`` seeds both fields
# + ensures the unique partial index on first boot.
#
# Two fields:
#   * ``marco_lead_sense_id``       — 12-char URL-safe id, tenant-
#     unique. Auto-generated on first GET if missing so a tenant
#     that predates the migration can still hydrate on-demand.
#   * ``lead_sense_allowed_origins`` — list of scheme://host[:port]
#     origins the LS-B intake will accept. Empty list = no origins
#     allowed (safe default). Wildcards / null / malformed entries
#     are rejected at write time.
#
# Auth ladder (see LS-A rulings #1 / #7):
#   * GET   — admin OR super_admin (readers can see + rotate).
#   * PATCH ``rotate: true``         — admin OR super_admin.
#   * PATCH ``lead_sense_allowed_origins`` — admin OR super_admin.
#   * PATCH ``marco_lead_sense_id: "<explicit>"`` — super_admin ONLY
#     (prevents accidental clobber into a coordination collision).
# ═════════════════════════════════════════════════════════════════════
import re as _ls_re
import secrets as _ls_secrets

_LEAD_SENSE_ID_NBYTES = 9  # → 12 base64url chars
_LEAD_SENSE_ID_LENGTH = 12
_LEAD_SENSE_ID_PATTERN = _ls_re.compile(r"^[A-Za-z0-9_\-]{6,64}$")
# Origin validation — matches
# ``scheme://host[:port]`` with no path, no query, no wildcards.
# Scheme must be http OR https (case-insensitive). Host is any
# non-empty run of letters/digits/hyphens/dots (RFC 1123 domain).
_ORIGIN_RE = _ls_re.compile(
    r"^https?://"                          # scheme
    r"([A-Za-z0-9]([A-Za-z0-9\-]{0,61}[A-Za-z0-9])?)"  # host label
    r"(\.[A-Za-z0-9]([A-Za-z0-9\-]{0,61}[A-Za-z0-9])?)*"  # dot-parts
    r"(:\d{1,5})?$",                       # optional port
    _ls_re.IGNORECASE,
)
_MAX_LEAD_SENSE_ORIGINS = 20
_LEAD_SENSE_ROTATE_MAX_RETRIES = 3


def _new_lead_sense_id() -> str:
    """Return a fresh 12-char URL-safe id. Kept in lockstep with
    ``migrations.marco_lead_sense_id_v1._new_lead_sense_id``."""
    return _ls_secrets.token_urlsafe(_LEAD_SENSE_ID_NBYTES)


def _validate_origin(raw: str) -> Optional[str]:
    """Return a normalised origin string, or ``None`` if invalid.

    Normalisation rules:
      * Strip surrounding whitespace.
      * Strip a single trailing slash.
      * Lowercase the scheme + host (preserve the port digits).
      * Reject empty strings, wildcards (``*`` / ``null``), and
        anything with a path/query/fragment component.
    """
    if not isinstance(raw, str):
        return None
    s = raw.strip()
    if not s:
        return None
    # Explicit wildcard bans — cover both the CORS ``*`` and the
    # RFC-7230 ``null`` sentinel, which some browsers set for
    # ``file://`` / sandboxed iframes and which would otherwise
    # match ``https?://null`` (impossible but locked).
    if s in ("*", "null") or "*" in s:
        return None
    # Strip trailing slash before pattern match — a lot of admins
    # will paste ``https://acme.com/`` and expect it to work.
    if s.endswith("/"):
        s = s[:-1]
    # Any remaining ``/`` implies a path component → reject.
    if "/" in s.split("://", 1)[-1]:
        return None
    # No query / fragment / userinfo allowed.
    if "?" in s or "#" in s or "@" in s:
        return None
    m = _ORIGIN_RE.match(s)
    if not m:
        return None
    # Split scheme + rest so we can lowercase both halves safely.
    try:
        scheme, rest = s.split("://", 1)
    except ValueError:
        return None
    return f"{scheme.lower()}://{rest.lower()}"


class LeadSenseIdPatch(BaseModel):
    """Partial-update payload for
    ``PATCH /api/tenants/mine/lead-sense-id``.

    All three fields are optional so an admin can rotate the id,
    edit the origin list, and (as super_admin) pin a specific id
    each in isolation:

      * ``rotate`` — flip ``true`` to generate a fresh id.
      * ``marco_lead_sense_id`` — pin a specific id (super_admin
        only). Format-validated against
        ``[A-Za-z0-9_\\-]{6,64}``.
      * ``lead_sense_allowed_origins`` — replace the current list.
        Each entry must pass ``_validate_origin``; list capped
        at ``_MAX_LEAD_SENSE_ORIGINS`` entries.
    """
    rotate: Optional[bool] = None
    marco_lead_sense_id: Optional[str] = Field(
        None,
        description=(
            "Super-admin-only. Pin a specific id (12–64 chars, "
            "URL-safe). Reject a body that supplies this field "
            "without super_admin role (403)."
        ),
    )
    lead_sense_allowed_origins: Optional[List[str]] = Field(
        None,
        description=(
            "Replace the tenant's allowed-origins list. Each "
            "entry must be a valid scheme://host[:port] with no "
            "path/query. Wildcards forbidden."
        ),
    )


def _read_lead_sense(tenant: dict) -> dict:
    """Return the lead-sense block hydrated with defaults.

    Empty list for origins when the field is missing (pre-
    migration tenants) so callers never see ``None`` there.
    """
    lead_id = tenant.get("marco_lead_sense_id")
    origins = tenant.get("lead_sense_allowed_origins")
    if not isinstance(origins, list):
        origins = []
    out = {
        "marco_lead_sense_id": lead_id if isinstance(lead_id, str) else None,
        "lead_sense_allowed_origins": list(origins),
    }
    if "lead_sense_updated_at" in tenant:
        out["lead_sense_updated_at"] = tenant["lead_sense_updated_at"]
    if "lead_sense_updated_by" in tenant:
        out["lead_sense_updated_by"] = tenant["lead_sense_updated_by"]
    return out


async def _generate_unique_lead_sense_id(*, exclude_tenant_id: Optional[str] = None) -> str:
    """Generate a lead-sense id that doesn't collide with any
    other tenant's stored id.

    ``exclude_tenant_id`` is passed when the caller is rotating
    their own id — we don't count the caller's current id as a
    collision, but that's a moot point because a rotate replaces
    the value atomically. Kept for callers that want to reserve
    the id in a separate pre-check.
    """
    for _ in range(_LEAD_SENSE_ROTATE_MAX_RETRIES + 1):
        cand = _new_lead_sense_id()
        q: dict = {"marco_lead_sense_id": cand}
        if exclude_tenant_id:
            q["id"] = {"$ne": exclude_tenant_id}
        hit = await db.tenants.find_one(q, {"_id": 0, "id": 1})
        if hit is None:
            return cand
    raise HTTPException(
        500,
        "Failed to generate a collision-free lead-sense id after "
        f"{_LEAD_SENSE_ROTATE_MAX_RETRIES + 1} attempts",
    )


@router.get(
    "/tenants/mine/lead-sense-id", tags=["tenants"],
    operation_id="tenants.readLeadSenseId",
    summary="Read tenant MARCO Lead-Sense id + allowed origins",
)
async def get_own_lead_sense_id(
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    """Return the caller tenant's ``marco_lead_sense_id`` +
    ``lead_sense_allowed_origins``. Auto-generates the id on
    first-read if the tenant lacks one (a pre-migration tenant
    that predates the LS-A backfill sweep). Admin / super_admin
    only — techs / managers / customers get 403."""
    if user.get("role") not in ("admin", "super_admin"):
        raise HTTPException(403, "Admin access required")
    tid = tenant.get("id")
    if not tid:
        raise HTTPException(400, "User has no tenant")
    current = tenant.get("marco_lead_sense_id")
    if not (isinstance(current, str) and current):
        # Auto-generate on first-read. Uniqueness-checked so a
        # concurrent rotate on another tenant can't accidentally
        # collide.
        new_id = await _generate_unique_lead_sense_id()
        await db.tenants.update_one(
            {"id": tid},
            {"$set": {
                "marco_lead_sense_id": new_id,
                "lead_sense_updated_at": now_iso(),
                "lead_sense_updated_by": user.get("id"),
            }},
        )
        tenant = await db.tenants.find_one(
            {"id": tid}, {"_id": 0},
        ) or tenant
    return _read_lead_sense(tenant)


@router.patch(
    "/tenants/mine/lead-sense-id", tags=["tenants"],
    operation_id="tenants.updateLeadSenseId",
    summary=(
        "Update tenant Lead-Sense id / origins "
        "(admin: rotate + origins; super_admin: explicit id)"
    ),
)
async def patch_own_lead_sense_id(
    request: Request,
    body: LeadSenseIdPatch,
    user: dict = Depends(get_current_user),
):
    """Rotate the id, replace the origin allow-list, or pin a
    specific id.

    Role gate summary (ruling LS-A · #1 / #7):
      * ``rotate``                     — admin OR super_admin.
      * ``lead_sense_allowed_origins`` — admin OR super_admin.
      * ``marco_lead_sense_id`` (explicit) — super_admin ONLY.

    Cross-tenant safety mirrors ``patch_own_automation_rules``:
    a body-supplied ``tenant_id`` (even matching the caller's
    own JWT tenant) raises 403 loud so the frontend never grows
    the habit of sending it.
    """
    role = user.get("role")
    if role not in ("admin", "super_admin"):
        raise HTTPException(403, "Admin access required")
    tid = user.get("tenant_id")
    if not tid:
        raise HTTPException(400, "User has no tenant")

    # Cross-tenant guard — body ``tenant_id`` forbidden.
    try:
        raw = await request.json()
    except Exception:  # noqa: BLE001
        raw = {}
    if isinstance(raw, dict) and "tenant_id" in raw:
        raise HTTPException(
            403,
            "tenant_id is derived from JWT; body-supplied tenant_id "
            "is forbidden.",
        )

    # Super-admin gate on the explicit-id write path.
    if body.marco_lead_sense_id is not None and role != "super_admin":
        raise HTTPException(
            403,
            "Only super_admin may pin an explicit marco_lead_sense_id "
            "value; use ``rotate: true`` instead.",
        )

    upd: dict = {}

    # Explicit id path (super_admin only, already gated above).
    if body.marco_lead_sense_id is not None:
        cand = body.marco_lead_sense_id.strip()
        if not _LEAD_SENSE_ID_PATTERN.match(cand):
            raise HTTPException(
                422,
                "marco_lead_sense_id must be 6-64 URL-safe chars "
                "(letters, digits, underscore, hyphen).",
            )
        # Uniqueness check — must not collide with another tenant.
        clash = await db.tenants.find_one(
            {"marco_lead_sense_id": cand, "id": {"$ne": tid}},
            {"_id": 0, "id": 1},
        )
        if clash is not None:
            raise HTTPException(
                409,
                "marco_lead_sense_id is already in use by another "
                "tenant. Choose a different value.",
            )
        upd["marco_lead_sense_id"] = cand

    # Rotate path.
    if body.rotate:
        if "marco_lead_sense_id" in upd:
            # Both ``rotate`` and an explicit ``marco_lead_sense_id``
            # would race — reject the ambiguity.
            raise HTTPException(
                422,
                "Cannot combine rotate=true with an explicit "
                "marco_lead_sense_id value.",
            )
        upd["marco_lead_sense_id"] = await _generate_unique_lead_sense_id(
            exclude_tenant_id=tid,
        )

    # Origins path.
    if body.lead_sense_allowed_origins is not None:
        origins = body.lead_sense_allowed_origins
        if len(origins) > _MAX_LEAD_SENSE_ORIGINS:
            raise HTTPException(
                422,
                f"lead_sense_allowed_origins accepts at most "
                f"{_MAX_LEAD_SENSE_ORIGINS} entries "
                f"(got {len(origins)}).",
            )
        normalised: List[str] = []
        seen: set = set()
        for raw_o in origins:
            norm = _validate_origin(raw_o)
            if norm is None:
                raise HTTPException(
                    422,
                    f"Invalid origin {raw_o!r}. Expected "
                    f"scheme://host[:port] with no path/query, "
                    f"and no wildcards.",
                )
            if norm in seen:
                continue
            seen.add(norm)
            normalised.append(norm)
        upd["lead_sense_allowed_origins"] = normalised

    if not upd:
        raise HTTPException(400, "Nothing to update")

    upd["lead_sense_updated_at"] = now_iso()
    upd["lead_sense_updated_by"] = user.get("id")
    await db.tenants.update_one({"id": tid}, {"$set": upd})
    doc = await db.tenants.find_one({"id": tid}, {"_id": 0})
    return _read_lead_sense(doc or {})




# ─── Feb-2026 · F4 Enhancement — Widget-Embed tenant settings ─────
class WidgetEmbedSettingsUpdate(BaseModel):
    """Fields settable via ``PATCH /api/tenants/settings/widget-embed``.

    Both fields land inside the ``tenant.settings`` sub-document
    because ``services/public_checkin_enqueue.py`` reads the flag
    from ``tenant.settings.auto_enqueue_public_checkins`` (see F4
    ship).

      * ``auto_enqueue_public_checkins`` — flip the F4 auto-enqueue.
      * ``widget_embed_seo_prompt_dismissed_at`` — ISO timestamp
        stamped when an admin dismisses the "Turn on public map for
        local SEO" onboarding banner so it does not reappear.
    """
    auto_enqueue_public_checkins: Optional[bool] = None
    widget_embed_seo_prompt_dismissed_at: Optional[str] = None


@router.get("/tenants/settings/widget-embed", tags=["tenants"],
              operation_id="tenants.readWidgetEmbedSettings")
async def get_widget_embed_settings(
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    """Read the F4 widget-embed tenant settings PLUS a
    server-derived ``should_show_seo_prompt`` flag so the admin UI
    doesn't have to run its own eligibility query.

    ``should_show_seo_prompt`` is TRUE when:
      * ``auto_enqueue_public_checkins`` is falsy (or unset), AND
      * the tenant has ≥ 1 completed job in the last 90 days, AND
      * ``widget_embed_seo_prompt_dismissed_at`` is null / missing.
    """
    if user.get("role") not in ("admin", "manager", "super_admin"):
        raise HTTPException(403, "Admin/manager access required")
    settings = (tenant.get("settings") or {})
    auto_on = bool(settings.get("auto_enqueue_public_checkins"))
    dismissed_at = settings.get("widget_embed_seo_prompt_dismissed_at")

    # Only run the completed-jobs probe if we might actually show
    # the prompt — otherwise the flag is definitely false and the
    # query is a waste.
    has_recent = False
    if not auto_on and not dismissed_at:
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=90)
        ).isoformat()
        probe = await db.jobs.find_one({
            "tenant_id": tenant["id"],
            "status": "completed",
            "completed_at": {"$gte": cutoff},
        }, {"_id": 0, "id": 1})
        has_recent = probe is not None

    return {
        "auto_enqueue_public_checkins": auto_on,
        "widget_embed_seo_prompt_dismissed_at": dismissed_at,
        "has_recent_completed_jobs": has_recent,
        "should_show_seo_prompt": (
            not auto_on and not dismissed_at and has_recent
        ),
    }



@router.patch("/tenants/settings/widget-embed", tags=["tenants"],
                operation_id="tenants.updateWidgetEmbedSettings")
async def patch_widget_embed_settings(
    body: WidgetEmbedSettingsUpdate,
    user: dict = Depends(get_current_user),
):
    """Admin-only PATCH for the F4 widget-embed tenant settings.

    Tenant-scoped: the target tenant is ALWAYS the caller's own
    tenant id — the endpoint cannot be aimed at another tenant even
    with a forged body.
    """
    if user.get("role") not in ("admin", "super_admin"):
        raise HTTPException(403, "Admin access required")
    tid = user.get("tenant_id")
    if not tid:
        raise HTTPException(400, "User has no tenant")
    upd = body.dict(exclude_unset=True)
    if not upd:
        raise HTTPException(400, "Nothing to update")
    # Nest under ``settings.*`` so the F4 enqueue helper sees the flag.
    set_ops = {f"settings.{k}": v for k, v in upd.items()}
    set_ops["settings_updated_at"] = now_iso()
    set_ops["settings_updated_by"] = user.get("id")
    await db.tenants.update_one({"id": tid}, {"$set": set_ops})
    doc = await db.tenants.find_one(
        {"id": tid}, {"_id": 0, "settings": 1,
                       "settings_updated_at": 1,
                       "settings_updated_by": 1},
    )
    settings = (doc or {}).get("settings") or {}
    return {
        "auto_enqueue_public_checkins":
            settings.get("auto_enqueue_public_checkins"),
        "widget_embed_seo_prompt_dismissed_at":
            settings.get("widget_embed_seo_prompt_dismissed_at"),
        "settings_updated_at": (doc or {}).get("settings_updated_at"),
        "settings_updated_by": (doc or {}).get("settings_updated_by"),
    }



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
# Phase 21 · Feb 2026 · Enhancement — Vanity slug editor
# Super-admin self-serve editor for ``tenant.slug_aliases``.
# ══════════════════════════════════════════════════════════════
import re as _slug_re

_SLUG_ALIAS_RE = _slug_re.compile(r"^[a-z0-9][a-z0-9-]{1,30}[a-z0-9]$")
_RESERVED_SLUG_ALIASES = {
    "admin", "api", "public", "app", "static", "assets", "login",
    "logout", "signup", "signin", "auth", "www", "portal", "webhooks",
    "resend", "stripe", "docs", "openapi", "health",
}


class SlugAliasIn(BaseModel):
    alias: str


def _validate_alias_or_raise(alias: str) -> str:
    a = (alias or "").strip().lower()
    if not _SLUG_ALIAS_RE.match(a):
        raise HTTPException(
            400, "alias must match ^[a-z0-9-]{3,32}$ (lowercase, digits, hyphen; 3–32 chars)",
        )
    if a in _RESERVED_SLUG_ALIASES:
        raise HTTPException(400, f"'{a}' is a reserved word and cannot be used as a tenant alias")
    return a


@router.get("/tenants/current/slug-aliases",
             operation_id="tenants.slugAliases.list")
async def list_slug_aliases(actor: dict = Depends(require_super_admin),
                              tenant: dict = Depends(get_current_tenant)):
    """List canonical slug + every alias for the caller's tenant."""
    return {
        "tenant_id": tenant["id"],
        "canonical_slug": tenant.get("slug"),
        "slug_aliases": list(tenant.get("slug_aliases") or []),
    }


@router.post("/tenants/current/slug-aliases",
              operation_id="tenants.slugAliases.add")
async def add_slug_alias(body: SlugAliasIn,
                          actor: dict = Depends(require_super_admin),
                          tenant: dict = Depends(get_current_tenant)):
    """Add a new alias. Rejects invalid regex, reserved words, and
    collisions with ANY existing tenant's slug or slug_aliases (409)."""
    alias = _validate_alias_or_raise(body.alias)

    # Same tenant no-op — return current state.
    if alias == (tenant.get("slug") or "").lower():
        return {"ok": True, "was_canonical": True,
                "slug_aliases": list(tenant.get("slug_aliases") or [])}
    if alias in [a.lower() for a in (tenant.get("slug_aliases") or [])]:
        return {"ok": True, "was_already_alias": True,
                "slug_aliases": list(tenant.get("slug_aliases") or [])}

    # Global uniqueness — cannot collide with ANOTHER tenant's slug/alias.
    collision = await db.tenants.find_one(
        {"$or": [{"slug": alias}, {"slug_aliases": alias}],
         "id": {"$ne": tenant["id"]}},
        {"_id": 0, "id": 1, "slug": 1},
    )
    if collision:
        raise HTTPException(
            409,
            f"alias '{alias}' is already in use by tenant '{collision.get('slug')}'",
        )

    aliases = list(tenant.get("slug_aliases") or []) + [alias]
    await db.tenants.update_one(
        {"id": tenant["id"]},
        {"$set": {"slug_aliases": aliases, "updated_at": now_iso()}},
    )
    logger.info("[vanity-slug] tenant=%s added alias=%r by actor=%s",
                tenant["id"], alias, actor.get("email"))
    return {"ok": True, "slug_aliases": aliases}


@router.delete("/tenants/current/slug-aliases/{alias}",
                operation_id="tenants.slugAliases.remove")
async def remove_slug_alias(alias: str,
                              actor: dict = Depends(require_super_admin),
                              tenant: dict = Depends(get_current_tenant)):
    """Remove an alias. Idempotent — removing a non-existent alias
    returns ok with was_already_absent=True. Removing the canonical
    slug is forbidden (400)."""
    a = (alias or "").strip().lower()
    if a == (tenant.get("slug") or "").lower():
        raise HTTPException(400, "canonical slug cannot be removed")
    current = list(tenant.get("slug_aliases") or [])
    if a not in [x.lower() for x in current]:
        return {"ok": True, "was_already_absent": True,
                "slug_aliases": current}
    new_aliases = [x for x in current if x.lower() != a]
    await db.tenants.update_one(
        {"id": tenant["id"]},
        {"$set": {"slug_aliases": new_aliases, "updated_at": now_iso()}},
    )
    logger.info("[vanity-slug] tenant=%s removed alias=%r by actor=%s",
                tenant["id"], a, actor.get("email"))
    return {"ok": True, "slug_aliases": new_aliases}


# ══════════════════════════════════════════════════════════════
# Phase 21 · Feb 2026 · Smart enhancement — Primary customer-facing URL
# ``tenant.settings.primary_app_domain`` — read by every outbound
# absolute-URL builder (invoice pay link, review request, magic
# login, unsubscribe). Super-admin only.
# ══════════════════════════════════════════════════════════════
_HTTPS_URL_RE = _slug_re.compile(
    r"^https://[a-z0-9]([a-z0-9-]{0,62}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,62}[a-z0-9])?)+(/[^\s]*)?$",
    _slug_re.IGNORECASE,
)


class PrimaryAppDomainIn(BaseModel):
    primary_app_domain: Optional[str] = None


@router.get("/tenants/current/primary-app-domain",
             operation_id="tenants.primaryAppDomain.get")
async def get_primary_app_domain(actor: dict = Depends(require_super_admin),
                                   tenant: dict = Depends(get_current_tenant)):
    settings = tenant.get("settings") or {}
    return {
        "primary_app_domain": settings.get("primary_app_domain"),
        "default": "https://app.plofv.com",
    }


@router.patch("/tenants/current/primary-app-domain",
                operation_id="tenants.primaryAppDomain.update")
async def patch_primary_app_domain(body: PrimaryAppDomainIn,
                                     actor: dict = Depends(require_super_admin),
                                     tenant: dict = Depends(get_current_tenant)):
    """Set / clear the tenant-scoped customer-facing URL. Value must
    be an HTTPS URL; ``None`` / empty string clears the override so
    the URL builder falls back to ``request.base_url`` or the
    ``APP_PUBLIC_URL`` env.
    """
    raw = body.primary_app_domain
    if raw is None or raw == "":
        new_value = None
    else:
        val = raw.strip().rstrip("/")
        if not val.lower().startswith("https://"):
            raise HTTPException(400, "primary_app_domain must start with 'https://'")
        if not _HTTPS_URL_RE.match(val):
            raise HTTPException(400, "primary_app_domain is not a valid HTTPS URL")
        new_value = val
    await db.tenants.update_one(
        {"id": tenant["id"]},
        {"$set": {"settings.primary_app_domain": new_value,
                  "updated_at": now_iso()}},
    )
    logger.info(
        "[primary-app-domain] tenant=%s -> %r by actor=%s",
        tenant["id"], new_value, actor.get("email"),
    )
    return {"ok": True, "primary_app_domain": new_value}


# ══════════════════════════════════════════════════════════════
# Feb-2026 · Item 6 — Business Card (digital vCard)
# ══════════════════════════════════════════════════════════════



# ══════════════════════════════════════════════════════════════
# Phase I1.5.a · Feb-2026 — Tenant Theme Config
#
# Extends ``tenants`` collection with a ``theme`` sub-document of
# shape ``{menu, rail, tiles, buttons, accents, preset}``. Each
# slot is ``{mode: 'solid'|'gradient', solid?, gradient?}``.
#
# Sub-phase scope (I1.5.a): backend storage + API + preset
# registry. Frontend editor UI, live preview + useTenantTheme hook
# land in I1.5.b/c. Backwards compat: existing tenants that never
# PUT a theme read the ``default`` preset expanded from GET without
# an auto-write to Mongo.
# ══════════════════════════════════════════════════════════════
from services.theme import (  # noqa: E402
    PRESETS as _THEME_PRESETS,
    ThemeValidationError,
    expand_default,
    get_preset,
    list_presets,
    preview_theme_payload,
    validate_theme_payload,
)


def _theme_admin_or_403(user: dict) -> None:
    """Theme edits are admin-only (matches the settings/brand
    editors). Managers + techs get 403 to prevent well-meaning-but-
    breaking accidental resets."""
    if user.get("role") not in ("admin", "super_admin"):
        raise HTTPException(403, "Admin access required")


@router.get(
    "/tenants/me/theme",
    tags=["tenants", "theme"],
    operation_id="tenants.theme.read",
    summary="Read the current tenant theme.",
    responses={200: {"description": (
        "Returns the tenant's persisted theme when set. When the "
        "tenant has never called PUT, returns the ``default`` "
        "preset **expanded** — no auto-write. Available to any "
        "authenticated user in the tenant (so the shell can apply "
        "CSS variables without an admin round-trip)."
    )}},
)
async def get_tenant_theme(tenant: dict = Depends(get_current_tenant)):
    theme = tenant.get("theme")
    if not isinstance(theme, dict) or not theme:
        return expand_default()
    return theme


@router.put(
    "/tenants/me/theme",
    tags=["tenants", "theme"],
    operation_id="tenants.theme.replace",
    summary="Replace the tenant theme (admin-only).",
    responses={
        200: {"description": "Theme persisted. Response echoes the "
                              "sanitized theme."},
        400: {"description": "Structural / solid-only / WCAG AA "
                              "contrast violation. ``detail.code`` "
                              "narrows the failure kind so the "
                              "editor can highlight the offending "
                              "slot."},
        403: {"description": "Non-admin caller."},
    },
)
async def put_tenant_theme(payload: dict,
                             user: dict = Depends(get_current_user),
                             tenant: dict = Depends(get_current_tenant)):
    _theme_admin_or_403(user)
    try:
        clean = validate_theme_payload(payload)
    except ThemeValidationError as e:
        raise HTTPException(400, detail=e.as_detail())
    await db.tenants.update_one(
        {"id": tenant["id"]},
        {"$set": {
            "theme": clean,
            "theme_updated_at": now_iso(),
            "theme_updated_by": user.get("id"),
        }},
    )
    return clean


@router.get(
    "/theme-presets",
    tags=["tenants", "theme"],
    operation_id="tenants.theme.listPresets",
    summary="List all available theme presets.",
    responses={200: {"description": (
        "Returns ``{presets: [{key, name, theme}]}`` — 31 entries "
        "(default + 30 verticals). Order is deterministic and "
        "matches the in-code registry. Any authenticated caller "
        "can read (used by the editor's preset picker)."
    )}},
)
async def get_theme_presets(user: dict = Depends(get_current_user)):
    return {"presets": list_presets()}


@router.post(
    "/tenants/me/theme/preview",
    tags=["tenants", "theme"],
    operation_id="tenants.theme.preview",
    summary="Validate a theme payload without persisting (admin-only).",
    responses={
        200: {"description": (
            "Returns ``{valid: bool, errors: [{code, path, message, "
            "computed_ratio?}]}``. Never returns 400 for validation "
            "failures — errors are surfaced in the body so the "
            "editor can highlight every offending slot at once."
        )},
        403: {"description": "Non-admin caller."},
    },
)
async def preview_tenant_theme(payload: dict,
                                 user: dict = Depends(get_current_user)):
    _theme_admin_or_403(user)
    return preview_theme_payload(payload)


class _ApplyPresetIn(BaseModel):
    key: str


@router.post(
    "/tenants/me/theme/apply-preset",
    tags=["tenants", "theme"],
    operation_id="tenants.theme.applyPreset",
    summary="Copy a preset into the tenant theme (admin-only).",
    responses={
        200: {"description": "Preset applied. Response echoes the "
                              "new persisted theme."},
        400: {"description": "Unknown preset key."},
        403: {"description": "Non-admin caller."},
    },
)
async def apply_theme_preset(body: _ApplyPresetIn,
                              user: dict = Depends(get_current_user),
                              tenant: dict = Depends(get_current_tenant)):
    _theme_admin_or_403(user)
    key = (body.key or "").strip()
    if key not in _THEME_PRESETS:
        raise HTTPException(400, detail={
            "code": "UNKNOWN_PRESET",
            "message": f"Preset {key!r} is not in the registry. "
                        "Call GET /api/theme-presets for the "
                        "canonical list.",
            "key": key,
        })
    theme = get_preset(key)
    # Second-pass validate: guards against any future preset edit
    # that would slip past the module-import step.
    try:
        theme = validate_theme_payload(theme)
    except ThemeValidationError as e:  # pragma: no cover — presets
        # are locked by test_i15a_tenant_theme_endpoint.py.
        raise HTTPException(500, detail=e.as_detail())
    await db.tenants.update_one(
        {"id": tenant["id"]},
        {"$set": {
            "theme": theme,
            "theme_updated_at": now_iso(),
            "theme_updated_by": user.get("id"),
        }},
    )
    return theme
