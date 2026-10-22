"""TD-seo-phase1 · Oct-2026 — admin API for tenant portal-SEO metadata.

Extends ``tenants.settings.business_card.seo`` nested sub-doc (operator
decision #3: additive-nullable, zero migration, backward-compatible
with existing docs that lack the ``seo`` key).

Endpoints:
  * ``GET  /api/admin/portal-seo/{tenant_id}`` — fetch SEO sub-doc.
  * ``PATCH /api/admin/portal-seo/{tenant_id}`` — update SEO sub-doc.

RBAC:
  * ``require_admin`` gate (admin / super_admin / owner per Phase 34
    Task X widening) + explicit tenant-id match check: an admin of
    tenant A cannot touch tenant B's SEO. ``super_admin`` crosses
    tenants freely (matches existing cross-tenant admin pattern).

Audit:
  * ``PATCH`` emits a ``portal_seo_updated`` audit event matching the
    pattern established by other admin settings endpoints.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, validator

from config import db
from utils import new_id, require_admin


router = APIRouter(tags=["admin-portal-seo"])


# ─── Field length caps + URL validator (lightweight, no third-party) ──
_URL_PREFIXES = ("https://", "http://")
_TWITTER_CARD_TYPES = ("summary", "summary_large_image", "app", "player")


def _check_url(v: Optional[str], field: str) -> Optional[str]:
    if v in (None, ""):
        return v
    s = str(v).strip()
    if not s.startswith(_URL_PREFIXES):
        raise ValueError(f"{field} must be an http(s) URL")
    if len(s) > 2048:
        raise ValueError(f"{field} too long (max 2048)")
    return s


class PortalSeoPatch(BaseModel):
    """TD-seo-phase1 · additive-nullable SEO sub-doc. All fields
    optional; ``exclude_none=True`` strips unset keys so a PATCH that
    only sets ``og_title`` doesn't clobber other keys."""
    og_title: Optional[str] = Field(default=None, max_length=200)
    og_description: Optional[str] = Field(default=None, max_length=400)
    og_image_url: Optional[str] = Field(default=None)
    twitter_card: Optional[str] = Field(default=None)
    twitter_site: Optional[str] = Field(default=None, max_length=50)
    canonical_base_url: Optional[str] = Field(default=None)
    meta_description_override: Optional[str] = Field(
        default=None, max_length=400)
    service_areas: Optional[List[str]] = Field(default=None)
    json_ld_overrides: Optional[Dict[str, Any]] = Field(default=None)

    @validator("og_image_url", "canonical_base_url")
    def _v_url(cls, v):
        return _check_url(v, "url")

    @validator("twitter_card")
    def _v_card(cls, v):
        if v in (None, ""):
            return v
        if v not in _TWITTER_CARD_TYPES:
            raise ValueError(
                f"twitter_card must be one of {_TWITTER_CARD_TYPES}")
        return v

    @validator("service_areas")
    def _v_areas(cls, v):
        if v is None:
            return v
        if not isinstance(v, list):
            raise ValueError("service_areas must be a list of strings")
        if len(v) > 50:
            raise ValueError("service_areas capped at 50 entries")
        for s in v:
            if not isinstance(s, str) or len(s) > 120:
                raise ValueError(
                    "service_areas entries must be strings ≤120 chars")
        return v

    @validator("json_ld_overrides")
    def _v_overrides(cls, v):
        if v is None:
            return v
        if not isinstance(v, dict):
            raise ValueError("json_ld_overrides must be a dict")
        # Shallow serializability check.
        import json as _json
        try:
            _json.dumps(v)
        except (TypeError, ValueError):
            raise ValueError(
                "json_ld_overrides must be JSON-serializable")
        return v


async def _assert_tenant_scope(user: dict, tenant_id: str) -> None:
    """Admin/owner may only touch their own tenant; super_admin crosses."""
    role = (user or {}).get("role") or ""
    if role == "super_admin":
        return
    if (user or {}).get("tenant_id") != tenant_id:
        raise HTTPException(
            403, "Admin can only manage their own tenant's portal SEO")


async def _read_seo(tenant_id: str) -> Dict[str, Any]:
    t = await db.tenants.find_one({"id": tenant_id}, {"_id": 0})
    if not t:
        raise HTTPException(404, "Tenant not found")
    settings = t.get("settings") or {}
    card = settings.get("business_card") or {}
    seo = card.get("seo") or {}
    # Lightweight fallbacks so GET surfaces something sensible even
    # when the admin hasn't filled anything yet.
    return {
        "tenant_id":                 tenant_id,
        "og_title":                  seo.get("og_title") or card.get("company_name"),
        "og_description":            seo.get("og_description") or card.get("tagline"),
        "og_image_url":              seo.get("og_image_url") or card.get("logo_url"),
        "twitter_card":              seo.get("twitter_card") or "summary_large_image",
        "twitter_site":              seo.get("twitter_site"),
        "canonical_base_url":        seo.get("canonical_base_url"),
        "meta_description_override": seo.get("meta_description_override"),
        "service_areas":             seo.get("service_areas") or [],
        "json_ld_overrides":         seo.get("json_ld_overrides") or {},
        "updated_at":                seo.get("updated_at"),
        "updated_by_user_id":        seo.get("updated_by_user_id"),
    }


@router.get("/admin/portal-seo/{tenant_id}",
             operation_id="adminPortalSeo.get")
async def get_portal_seo(tenant_id: str,
                           user: dict = Depends(require_admin)):
    await _assert_tenant_scope(user, tenant_id)
    return await _read_seo(tenant_id)


@router.patch("/admin/portal-seo/{tenant_id}",
                operation_id="adminPortalSeo.update")
async def update_portal_seo(tenant_id: str,
                              body: PortalSeoPatch,
                              user: dict = Depends(require_admin)):
    await _assert_tenant_scope(user, tenant_id)
    patch = {k: v for k, v in body.dict(exclude_none=True).items()}
    if not patch:
        raise HTTPException(400, "No fields to update")
    now = datetime.now(timezone.utc).isoformat()
    set_ops = {
        f"settings.business_card.seo.{k}": v for k, v in patch.items()
    }
    set_ops["settings.business_card.seo.updated_at"] = now
    set_ops["settings.business_card.seo.updated_by_user_id"] = (
        user.get("id") or "")
    r = await db.tenants.update_one(
        {"id": tenant_id}, {"$set": set_ops})
    if not r.matched_count:
        raise HTTPException(404, "Tenant not found")
    # Audit event — matches the pattern used by other admin settings
    # endpoints (e.g. tenants.py:653).
    try:
        await db.audit_events.insert_one({
            "id":            new_id(),
            "tenant_id":     tenant_id,
            "event_type":    "portal_seo_updated",
            "actor_user_id": user.get("id"),
            "actor_email":   user.get("email"),
            "payload":       {"fields_changed": sorted(patch.keys())},
            "timestamp":     now,
            "via_impersonation": bool(user.get("via_impersonation")),
        })
    except Exception:
        # Audit insert must never block the mutation; log and continue.
        from config import logger
        logger.warning(
            "portal_seo_updated audit insert failed", exc_info=True)
    return await _read_seo(tenant_id)
