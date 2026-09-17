"""Feb-2026 · Business Signup SP1 — public signup + email-verify routes.

Routes registered under ``/api``:

  * ``POST /api/signup``                        — public self-serve signup.
  * ``POST /api/signup/verify?token=…``         — public token redemption.
  * ``POST /api/signup/resend-verification``    — admin-scoped resend.
  * ``POST /api/billing/cancel-subscription``   — tenant-admin scoped.

Everything is READ-ONLY-safe: existing tenants are unaffected — the
new ``email_verified`` and ``onboarding_step`` fields default to
truthy for pre-signup tenants via the SP1 backfill migration.
"""
from __future__ import annotations

import logging
import os
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from typing import Any, Deque, Dict, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr

from config import db
from routers.tenants import get_current_tenant
from services.i18n_notifications import (
    MissingMergeVarError,
    TemplateNotFoundError,
    resolve_notification_body,
    resolve_recipient_locale,
)
from services.signup_verify_tokens import (
    mint_signup_verify_token,
    verify_signup_verify_token,
)
from services.tenant_billing_stripe import (
    BILLING_STATUS_CANCELED,
    BILLING_STATUS_PENDING,
    cancel_tenant_subscription,
    create_tenant_billing,
)
from utils import hash_password, new_id, now_iso, require_admin

# SP3 · Feb-2026 — single source of truth for the canonical 23-industry
# set is ``routers/industry_checklists.INDUSTRY_SLUGS``. SP1 was
# shipping a parallel set that drifted (used ``"pools"`` (plural)
# where canonical uses ``"pool"`` (singular) and named 4 non-canonical
# slugs like ``"carpentry"``/``"moving"`` while missing 5 canonical
# ones like ``"garage_door"``/``"irrigation"``). Fixed by importing.
from routers.industry_checklists import INDUSTRY_SLUGS  # noqa: E402

logger = logging.getLogger("signup")
router = APIRouter(tags=["signup"])


# ── Constants ──────────────────────────────────────────────────────
CANONICAL_INDUSTRY_SLUGS = frozenset(INDUSTRY_SLUGS)
# SP3 · Feb-2026 — legacy client alias. Frontends built before D1
# emitted ``"pools"`` (plural) for the pool industry. Normalize to
# the canonical singular ``"pool"`` and log an INFO warning so ops
# can identify stale clients still emitting the alias.
INDUSTRY_ALIASES = {"pools": "pool"}
COUNTRY_ALPHA2 = frozenset({
    "US", "CA", "GB", "AU", "IE", "NZ", "DE", "FR", "ES", "MX",
    "IN", "BR", "ZA", "SG", "HK", "JP", "KR", "AE", "SA", "PH",
    "PT", "IT", "NL", "SE", "NO",
})


def _validate_password(pw: str) -> None:
    """Min 12 chars, at least one letter + one digit. No arbitrary
    complexity rules — bad UX per the SP1 spec."""
    if not isinstance(pw, str) or len(pw) < 12:
        raise HTTPException(400, detail={
            "code": "weak_password",
            "message": "Password must be at least 12 characters.",
        })
    has_letter = any(c.isalpha() for c in pw)
    has_digit = any(c.isdigit() for c in pw)
    if not (has_letter and has_digit):
        raise HTTPException(400, detail={
            "code": "weak_password",
            "message": "Password must include at least one letter and one digit.",
        })


def _validate_industry(slug: str) -> str:
    s = (slug or "").strip().lower().replace("-", "_").replace(" ", "_")
    # SP3 · Feb-2026 — alias-normalize legacy plural forms before the
    # canonical membership check so stale clients that still emit
    # ``"pools"`` keep working. Log the alias hit at INFO so ops can
    # spot the callers and eventually retire the plural form.
    if s in INDUSTRY_ALIASES:
        canonical = INDUSTRY_ALIASES[s]
        logger.info(
            "[signup] industry alias normalized: received=%r → stored=%r",
            s, canonical,
        )
        s = canonical
    if s not in CANONICAL_INDUSTRY_SLUGS:
        raise HTTPException(400, detail={
            "code": "invalid_industry",
            "supported": sorted(CANONICAL_INDUSTRY_SLUGS)[:5] + ["..."],
            "received": slug,
        })
    return s


def _validate_timezone(tz: str) -> str:
    s = (tz or "").strip()
    if not s:
        raise HTTPException(400, detail={
            "code": "invalid_timezone", "received": tz,
        })
    try:
        ZoneInfo(s)
    except ZoneInfoNotFoundError:
        raise HTTPException(400, detail={
            "code": "invalid_timezone",
            "hint": "Use an IANA identifier (e.g. America/Los_Angeles).",
            "received": tz,
        })
    return s


def _validate_country(cc: str) -> str:
    s = (cc or "").strip().upper()
    if s not in COUNTRY_ALPHA2:
        raise HTTPException(400, detail={
            "code": "invalid_country",
            "hint": "Use an ISO 3166-1 alpha-2 code from the supported list.",
            "received": cc,
        })
    return s


# ── Rate limit (in-memory, per-IP) ────────────────────────────────
# 5 signups per hour per IP by default; bump via ``SIGNUP_RATE_LIMIT_CAP``
# for pytest / CI runs that need headroom. In-memory is fine for a
# single-worker uvicorn — a multi-worker deploy would want Redis.
_SIGNUP_WINDOW_SEC = 3600
_SIGNUP_CAP = int(os.environ.get("SIGNUP_RATE_LIMIT_CAP", "5"))
_RESEND_WINDOW_SEC = 3600
_RESEND_CAP = int(os.environ.get("SIGNUP_RESEND_RATE_LIMIT_CAP", "3"))
_signup_hits: Dict[str, Deque[float]] = defaultdict(deque)
_resend_hits: Dict[str, Deque[float]] = defaultdict(deque)


def _rate_limit(hits: Dict[str, Deque[float]], key: str,
                    window_sec: int, cap: int) -> None:
    # Test hook — the CI/regression harness makes many signups per
    # run. Never active in production (see ``ALLOW_TEST_HOOKS`` docs).
    if os.environ.get("ALLOW_TEST_HOOKS") == "1":
        return
    now = time.monotonic()
    q = hits[key]
    while q and (now - q[0]) > window_sec:
        q.popleft()
    if len(q) >= cap:
        raise HTTPException(429, detail={
            "code": "rate_limited",
            "hint": f"Too many attempts. Try again in ~{window_sec // 60} min.",
        })
    q.append(now)


def _client_ip(request: Request) -> str:
    # Kubernetes ingress puts the real client IP in X-Forwarded-For.
    xff = request.headers.get("x-forwarded-for") or ""
    if xff:
        return xff.split(",")[0].strip()
    return (request.client.host if request.client else "unknown")


def _base_url_from_env() -> str:
    return (
        os.environ.get("FRONTEND_BASE_URL")
        or os.environ.get("APP_BASE_URL")
        or "https://app.example.com"
    ).rstrip("/")


async def _send_signup_verify_email(
    *, tenant: Dict[str, Any], admin_user: Dict[str, Any], token: str,
) -> None:
    """Render + dispatch the signup_email_verify email. Swallows
    exceptions so a mail-provider blip can't fail signup — the
    resend endpoint remains available."""
    try:
        verify_url = f"{_base_url_from_env()}/signup/verify?token={token}"
        locale = resolve_recipient_locale(
            tenant=tenant, user=admin_user, audience="customer",
        )
        body = resolve_notification_body(
            "signup_email_verify", locale,
            context={
                "admin_name":    admin_user.get("name", "there"),
                "business_name": tenant.get("name", "your business"),
                "verify_url":    verify_url,
            },
        )
    except (TemplateNotFoundError, MissingMergeVarError, KeyError) as exc:
        logger.warning("[signup-verify-email] render failed: %s", exc)
        return

    try:
        from services.email.resend_adapter import send as _send_email
        await _send_email(
            to=admin_user.get("email"),
            subject=body["subject"],
            html=body["body_html"],
            text=body["body_text"],
            tenant_id=tenant.get("id"),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("[signup-verify-email] send failed: %s", exc)


# ── Request / response schemas ────────────────────────────────────
class SignupIn(BaseModel):
    business_name: str
    admin_name: str
    admin_email: EmailStr
    admin_password: str
    admin_phone: str = ""
    primary_industry: str
    timezone: str
    country: str
    stripe_payment_method_id: str = ""


class ResendVerifyIn(BaseModel):
    pass


# ── Handlers ──────────────────────────────────────────────────────
@router.post("/signup", status_code=201)
async def signup(body: SignupIn, request: Request) -> Dict[str, Any]:
    # Validation up-front so a signup that lands a partial DB write
    # is impossible AND so a bad-payload attacker can't drain the
    # legit caller's rate-limit quota by sending garbage.
    _validate_password(body.admin_password)
    industry = _validate_industry(body.primary_industry)
    tz = _validate_timezone(body.timezone)
    country = _validate_country(body.country)
    email = body.admin_email.lower()

    # Rate-limit AFTER validation — bad payloads never consume quota.
    _rate_limit(_signup_hits, _client_ip(request),
                  _SIGNUP_WINDOW_SEC, _SIGNUP_CAP)

    # Idempotency: same email arriving twice while the FIRST tenant
    # is still unverified re-mints the token + re-sends the email
    # (option (b) in the ticket).
    existing_user = await db.users.find_one({"email": email})
    if existing_user:
        existing_tenant = await db.tenants.find_one(
            {"id": existing_user.get("tenant_id")}, {"_id": 0},
        )
        if (existing_tenant
                and existing_tenant.get("email_verified") is False):
            token = mint_signup_verify_token(
                tenant_id=existing_tenant["id"],
                admin_user_id=existing_user["id"],
                admin_email=email,
            )
            await _send_signup_verify_email(
                tenant=existing_tenant, admin_user=existing_user, token=token,
            )
            return {
                "tenant_id":                  existing_tenant["id"],
                "admin_user_id":              existing_user["id"],
                "email_verification_sent_to": email,
                "stripe_customer_id":         existing_tenant.get("stripe_customer_id"),
                "stripe_subscription_id":     existing_tenant.get("stripe_subscription_id"),
                "trial_end_utc":              existing_tenant.get("trial_end_utc"),
                "onboarding_step":            existing_tenant.get("onboarding_step") or 1,
                "resent":                     True,
            }
        # Verified account already — surface a proper 409.
        raise HTTPException(409, detail={
            "code": "email_already_registered",
            "hint": "Try logging in or use the password reset flow.",
        })

    # Tenant slug — derive from business name, guarantee uniqueness.
    base_slug = "".join(
        c.lower() if c.isalnum() else "-"
        for c in (body.business_name or "biz")
    ).strip("-")[:40] or "biz"
    slug = base_slug
    suffix = 1
    while await db.tenants.find_one({"slug": slug}, {"_id": 0}):
        suffix += 1
        slug = f"{base_slug}-{suffix}"

    tenant_id = new_id()
    tenant_doc: Dict[str, Any] = {
        "id":                       tenant_id,
        "name":                     body.business_name.strip(),
        "slug":                     slug,
        "active":                   True,
        "timezone":                 tz,
        "country":                  country,
        "industries":               [industry],
        "primary_industry":         industry,
        "email_verified":           False,
        "onboarding_step":          1,
        "onboarding_completed_at":  None,
        "plan":                     "starter",
        "created_at":               now_iso(),
    }

    # Provision Stripe customer + trial subscription. Never raises —
    # helper returns pending_stripe_config on any Stripe error.
    billing = await create_tenant_billing(
        tenant_id=tenant_id,
        business_name=body.business_name.strip(),
        admin_email=email,
        payment_method_id=body.stripe_payment_method_id,
    )
    tenant_doc.update({
        "stripe_customer_id":     billing["stripe_customer_id"],
        "stripe_subscription_id": billing["stripe_subscription_id"],
        "billing_status":         billing["billing_status"],
        "trial_end_utc":          billing["trial_end_utc"],
        "plan":                   billing.get("plan") or "starter",
    })
    await db.tenants.insert_one(tenant_doc)

    admin_user_id = new_id()
    admin_user = {
        "id":            admin_user_id,
        "tenant_id":     tenant_id,
        "name":          body.admin_name.strip(),
        "email":         email,
        "phone":         (body.admin_phone or "").strip(),
        "password_hash": hash_password(body.admin_password),
        "role":          "admin",
        "avatar":        "",
        "technician_id": None,
        "customer_id":   None,
        "failed_login_attempts": 0,
        "lockout_until": None,
        "created_at":    now_iso(),
    }
    await db.users.insert_one(admin_user)

    token = mint_signup_verify_token(
        tenant_id=tenant_id, admin_user_id=admin_user_id, admin_email=email,
    )
    await _send_signup_verify_email(
        tenant=tenant_doc, admin_user=admin_user, token=token,
    )

    return {
        "tenant_id":                  tenant_id,
        "admin_user_id":              admin_user_id,
        "email_verification_sent_to": email,
        "stripe_customer_id":         billing["stripe_customer_id"],
        "stripe_subscription_id":     billing["stripe_subscription_id"],
        "trial_end_utc":              billing["trial_end_utc"],
        "billing_status":             billing["billing_status"],
        "onboarding_step":            1,
    }


@router.post("/signup/verify")
async def signup_verify(token: str) -> Dict[str, Any]:
    """Public endpoint — redeems the signup-verify token, flips
    ``tenant.email_verified=True`` (idempotent), and returns a
    redirect target the client uses to route into onboarding."""
    claims = verify_signup_verify_token(token)
    tenant = await db.tenants.find_one({"id": claims["tenant_id"]}, {"_id": 0})
    if not tenant:
        raise HTTPException(404, detail={"code": "tenant_not_found"})
    if not tenant.get("email_verified"):
        await db.tenants.update_one(
            {"id": claims["tenant_id"]},
            {"$set": {"email_verified": True,
                        "email_verified_at": now_iso()}},
        )
    return {
        "tenant_id":     claims["tenant_id"],
        "admin_user_id": claims["admin_user_id"],
        "redirect_to":   "/onboarding",
        "verified":      True,
    }


@router.post("/signup/resend-verification")
async def signup_resend_verification(
    request: Request,
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    _rate_limit(_resend_hits, tenant["id"], _RESEND_WINDOW_SEC, _RESEND_CAP)
    if tenant.get("email_verified"):
        return {"already_verified": True, "sent": False}
    token = mint_signup_verify_token(
        tenant_id=tenant["id"],
        admin_user_id=user["id"],
        admin_email=user["email"],
    )
    await _send_signup_verify_email(
        tenant=tenant, admin_user=user, token=token,
    )
    return {"sent": True, "email": user["email"]}


@router.post("/billing/cancel-subscription")
async def billing_cancel_subscription(
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    sub_id = tenant.get("stripe_subscription_id")
    if not sub_id:
        # Sandbox / pending config — flip status locally so the UI
        # matches. No upstream call to make.
        await db.tenants.update_one(
            {"id": tenant["id"]},
            {"$set": {"billing_status": BILLING_STATUS_CANCELED,
                        "billing_canceled_at": now_iso()}},
        )
        return {
            "billing_status": BILLING_STATUS_CANCELED,
            "canceled_at":    now_iso(),
            "sandbox":        True,
        }
    result = await cancel_tenant_subscription(sub_id)
    await db.tenants.update_one(
        {"id": tenant["id"]},
        {"$set": {"billing_status": BILLING_STATUS_CANCELED,
                    "billing_canceled_at": result["canceled_at"]}},
    )
    return result


# ── Testing-hook exports ──────────────────────────────────────────
def _reset_rate_limits_for_tests() -> None:
    """Wipe the in-memory rate-limit windows. Only called by
    fixtures — never at request time."""
    _signup_hits.clear()
    _resend_hits.clear()
