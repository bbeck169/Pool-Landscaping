"""Phase 4 · Batch C / D7 — Weekly digest admin endpoints."""
from __future__ import annotations
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from utils import get_current_user
from routers.tenants import get_current_tenant
from services.weekly_digest import (
    _aggregate_tenant_week, render_html, send_weekly_digest_for_tenant,
)


router = APIRouter()


def _require_admin(user: dict = Depends(get_current_user)) -> dict:
    if user.get("role") not in ("admin", "super_admin"):
        raise HTTPException(403, "Admin access required")
    return user


def _require_super_admin(user: dict = Depends(get_current_user)) -> dict:
    if user.get("role") != "super_admin":
        raise HTTPException(403, "Super-admin access required")
    return user


class PreviewIn(BaseModel):
    as_of_date: Optional[str] = None  # YYYY-MM-DD


@router.post("/admin/weekly-digest/preview")
async def preview_weekly_digest(body: Optional[PreviewIn] = None,
                                 user: dict = Depends(_require_admin),
                                 tenant: dict = Depends(get_current_tenant)):
    as_of = None
    if body and body.as_of_date:
        try:
            as_of = datetime.fromisoformat(body.as_of_date)
        except Exception:
            raise HTTPException(400, "as_of_date must be ISO 8601 date")
    payload = await _aggregate_tenant_week(tenant, as_of=as_of)
    html = render_html(payload)
    return {"payload": payload, "html": html,
            "subject": f"[{payload['tenant_name']}] Weekly Digest · Week of {payload['week_of']}"}


class SendNowIn(BaseModel):
    to: str


@router.post("/admin/weekly-digest/send-now")
async def send_weekly_digest_now(body: SendNowIn,
                                   user: dict = Depends(_require_super_admin),
                                   tenant: dict = Depends(get_current_tenant)):
    if "@" not in body.to:
        raise HTTPException(400, "Invalid email")
    # SEC-P3-5 hotfix — recipient allowlist. Accept:
    #   1. any admin/super_admin email in this tenant, or
    #   2. an email whose domain matches an admin email's domain in this tenant.
    to_lc = body.to.lower().strip()
    admins = await __import__("services.weekly_digest", fromlist=["_tenant_admin_recipients"])\
        ._tenant_admin_recipients(tenant["id"])
    admin_emails = {(u.get("email") or "").lower() for u in admins if u.get("email")}
    admin_domains = {e.split("@", 1)[1] for e in admin_emails if "@" in e}
    domain = to_lc.split("@", 1)[1] if "@" in to_lc else ""
    if to_lc not in admin_emails and domain not in admin_domains:
        raise HTTPException(400, "Recipient must be a tenant admin or match a tenant admin's email domain.")
    return await send_weekly_digest_for_tenant(
        tenant, kind="weekly_digest_manual", override_to=body.to)
