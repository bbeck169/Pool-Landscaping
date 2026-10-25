"""Feb-2026 · Business Settings — admin + public branding router.

Ships five endpoints on top of ``db.tenants``:

    GET    /api/tenants/me/business-settings       (admin/super_admin)
    PATCH  /api/tenants/me/business-settings       (admin/super_admin)
    POST   /api/tenants/me/logo                    (admin/super_admin)
    DELETE /api/tenants/me/logo                    (admin/super_admin)
    GET    /api/portal/tenant/branding?token=…     (magic-link public)

The two ``/logo`` routes delegate to the existing branding-logo
upload/delete handlers in ``routers/tenants.py`` so the S3 pipeline,
size cap, mime allow-list, and blob-GC guarantees stay in one place.

See /app/memory/FEATURE_BUSINESS_SETTINGS.md.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field, validator

from config import db, logger
from utils import get_current_user, new_id, now_iso
from services.tenants.business_settings import (
    HEX_RE,
    build_business_settings_view,
    to_public_branding,
)

router = APIRouter()


# ── Auth guards ─────────────────────────────────────────────────────
def _admin_or_403(user: Optional[dict]) -> dict:
    if not user or (user.get("role") not in {"admin", "super_admin"}):
        raise HTTPException(403, "Admin only")
    return user


EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


class BusinessSettingsPatch(BaseModel):
    company_display_name: Optional[str] = Field(default=None, max_length=200)
    mailing_address: Optional[str] = Field(default=None, max_length=1000)
    phone: Optional[str] = Field(default=None, max_length=60)
    website: Optional[str] = Field(default=None, max_length=300)
    email: Optional[str] = Field(default=None, max_length=200)
    brand_primary_hex: Optional[str] = Field(default=None)
    brand_secondary_hex: Optional[str] = Field(default=None)
    # TD-email-template-header-bg-white · Feb-2026 — per-tenant
    # email-header styling. Hex-validated on write; defaults applied
    # in ``build_business_settings_view``. Nullable so a clear-out
    # PATCH (``null``) restores the default on next render.
    email_header_bg: Optional[str] = Field(default=None)
    email_header_text: Optional[str] = Field(default=None)
    footer_note: Optional[str] = Field(default=None, max_length=300)
    tax_id: Optional[str] = Field(default=None, max_length=100)
    # Feb-2026 · Routing Traffic-Aware phase — nullable bool. Callers
    # that omit the field must not have the existing value blanked;
    # ``exclude_unset=True`` in the PATCH handler already guarantees
    # this. Coercion to explicit ``False`` for the effective view
    # lives in ``build_business_settings_view``.
    routing_traffic_aware: Optional[bool] = None

    @validator("brand_primary_hex", "brand_secondary_hex",
                "email_header_bg", "email_header_text")
    def _hex_ok(cls, v):
        if v in (None, ""):
            return v
        if not HEX_RE.match(v):
            raise ValueError("Must be #RRGGBB")
        return v.lower()

    @validator("email")
    def _email_ok(cls, v):
        if v in (None, ""):
            return v
        if not EMAIL_RE.match(v):
            raise ValueError("Invalid email")
        return v

    @validator("website")
    def _website_norm(cls, v):
        # Auto-prepend https:// when the caller supplied a bare
        # domain. Empty stays empty so a clear-out PATCH works.
        if v in (None, ""):
            return v
        s = v.strip()
        if not s:
            return None
        if not s.lower().startswith(("http://", "https://")):
            s = "https://" + s
        return s


# ── Helpers ─────────────────────────────────────────────────────────
async def _load_tenant(user: dict) -> Dict[str, Any]:
    tid = user.get("tenant_id")
    if not tid:
        raise HTTPException(400, "User has no tenant")
    t = await db.tenants.find_one({"id": tid}, {"_id": 0})
    if not t:
        raise HTTPException(404, "Tenant not found")
    return t


async def _audit(event: str, tenant_id: str, actor_id: str,
                  extra: Optional[Dict[str, Any]] = None) -> None:
    """Best-effort audit row — never blocks the mutation."""
    row = {
        "id": new_id(),
        "event": event,
        "tenant_id": tenant_id,
        "actor_id": actor_id,
        "at": now_iso(),
    }
    if extra:
        row.update(extra)
    try:
        await db.audit_logs.insert_one(row)
    except Exception as exc:  # pragma: no cover
        logger.warning("business_settings_audit_failed: %s", exc)


# ── Admin GET / PATCH ───────────────────────────────────────────────
@router.get(
    "/tenants/me/business-settings",
    tags=["business-settings"],
    operation_id="businessSettings.get",
)
async def get_business_settings(user: dict = Depends(get_current_user)):
    _admin_or_403(user)
    tenant = await _load_tenant(user)
    view = build_business_settings_view(tenant)
    return {
        "tenant_id": tenant["id"],
        "stored": view["stored"],
        "effective": view["effective"],
    }


@router.patch(
    "/tenants/me/business-settings",
    tags=["business-settings"],
    operation_id="businessSettings.patch",
)
async def patch_business_settings(
    body: BusinessSettingsPatch,
    user: dict = Depends(get_current_user),
):
    _admin_or_403(user)
    tenant = await _load_tenant(user)

    # Only include fields the caller sent (exclude_unset) so a PATCH
    # with a single field doesn't blank the rest.
    patch = body.dict(exclude_unset=True)
    if not patch:
        # No-op — return the current view.
        return await get_business_settings(user=user)

    # Diff against the current tenant doc so the audit row can list
    # exactly which fields changed.
    changed = [k for k, v in patch.items() if tenant.get(k) != v]
    patch["updated_at"] = now_iso()
    await db.tenants.update_one({"id": tenant["id"]}, {"$set": patch})

    await _audit(
        event="business_settings.updated",
        tenant_id=tenant["id"],
        actor_id=user.get("id") or "",
        extra={"changed_fields": changed},
    )
    return await get_business_settings(user=user)


# ── Logo POST / DELETE (delegate to the existing branding handler) ──
@router.post(
    "/tenants/me/logo",
    tags=["business-settings"],
    operation_id="businessSettings.uploadLogo",
    summary="Upload the tenant brand logo (Business Settings alias).",
)
async def upload_logo_alias(
    logo: UploadFile = File(...),
    user: dict = Depends(get_current_user),
):
    _admin_or_403(user)
    from routers.tenants import upload_branding_logo
    result = await upload_branding_logo(logo=logo, user=user)
    await _audit(
        event="business_settings.logo_uploaded",
        tenant_id=user.get("tenant_id") or "",
        actor_id=user.get("id") or "",
        extra={
            "logo_url": result.get("logo_url"),
            "size_bytes": result.get("size_bytes"),
            "content_type": result.get("content_type"),
        },
    )
    return result


@router.delete(
    "/tenants/me/logo",
    tags=["business-settings"],
    operation_id="businessSettings.deleteLogo",
    summary="Clear the tenant brand logo without deleting the object.",
)
async def delete_logo_alias(user: dict = Depends(get_current_user)):
    _admin_or_403(user)
    tid = user.get("tenant_id")
    if not tid:
        raise HTTPException(400, "User has no tenant")
    # We intentionally DO NOT call the existing tenants branding
    # DELETE (which GCs the S3 blob). Business Settings deletes clear
    # the FIELD only, so a prior logo can be recovered from S3 if the
    # tenant wants to reinstate it via a direct URL patch.
    prior = await db.tenants.find_one(
        {"id": tid}, {"_id": 0, "logo_url": 1, "logo_object_path": 1},
    ) or {}
    await db.tenants.update_one(
        {"id": tid},
        {"$set": {
            "logo_url": None,
            "logo_updated_at": now_iso(),
            "logo_updated_by_user_id": user.get("id"),
            "updated_at": now_iso(),
        }},
    )
    await _audit(
        event="business_settings.logo_deleted",
        tenant_id=tid,
        actor_id=user.get("id") or "",
        extra={
            "prior_logo_url": prior.get("logo_url"),
            "prior_object_path": prior.get("logo_object_path"),
        },
    )
    return {"cleared": True, "logo_url": None}


# ── Public magic-link branding ─────────────────────────────────────
@router.get(
    "/portal/tenant/branding",
    tags=["business-settings"],
    operation_id="portal.tenantBranding",
    summary="Public branding subset (magic-link authed).",
)
async def portal_tenant_branding(
    token: str = Query(..., min_length=8),
):
    """Return the customer-safe branding subset for the tenant the
    magic-link ``token`` belongs to. No admin fields, no ``tax_id``,
    no audit — this is the same header data every customer-facing
    surface (web share, portal, PDF cover) already exposes.
    """
    # Reuse the estimate-token verifier so this endpoint doesn't
    # invent a new token surface.
    from routers.estimate_viewer import _verify_estimate_token
    payload = _verify_estimate_token(token)
    tid = payload.get("tid")
    if not tid:
        raise HTTPException(401, "Invalid token")
    t = await db.tenants.find_one({"id": tid}, {"_id": 0}) or {}
    view = build_business_settings_view(t)
    return {
        "tenant_id": tid,
        "branding": to_public_branding(view["effective"]),
    }


__all__ = ["router"]
