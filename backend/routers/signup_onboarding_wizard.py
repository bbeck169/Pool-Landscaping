"""Feb-2026 · Business Signup SP2 — 4-step onboarding wizard endpoints.

Distinct from ``routers/onboarding.py`` (Phase 15B — per-admin
6-step onboarding wizard state, driven by ``db.onboarding_state``).
That surface addresses training-flow onboarding for a NEW admin
who joined an EXISTING tenant; this one addresses the SIGNUP
wizard for a NEW tenant that just completed self-serve signup.
The two wizards coexist — the SP2 wizard drives
``tenant.onboarding_step`` / ``tenant.onboarding_completed_at``.

All routes tenant-admin-scoped. Prerequisite: ``email_verified``
must not be explicitly False (pre-signup tenants that predate
the SP1 backfill pass trivially — the check only fires on tenants
EXPLICITLY marked ``email_verified=False``).

Route prefix: ``/api/signup-onboarding/…`` — avoids collision with
Phase 15B's ``/api/onboarding/…`` surface.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr

from config import db
from routers.tenants import get_current_tenant
from utils import hash_password, new_id, now_iso, require_admin

logger = logging.getLogger("signup_onboarding_wizard")
router = APIRouter(tags=["signup-onboarding"])


CANONICAL_INDUSTRY_SLUGS = frozenset({
    "pools", "landscaping", "hvac", "pest_control", "cleaning",
    "solar", "handyman", "roofing", "plumbing", "electrical",
    "carpentry", "flooring", "painting", "window_cleaning",
    "gutter_cleaning", "pressure_washing", "carpet_cleaning",
    "chimney_sweep", "appliance_repair", "locksmith", "moving",
    "junk_removal", "general_services",
})


async def require_verified_tenant(
    tenant: dict = Depends(get_current_tenant),
) -> dict:
    """Dependency — gate any write endpoint behind email
    verification. Pre-signup tenants (field missing) pass
    trivially; only tenants EXPLICITLY marked
    ``email_verified=False`` are blocked with a 403."""
    if tenant.get("email_verified") is False:
        raise HTTPException(403, detail={
            "code": "email_verification_required",
            "hint": "Please verify your email address before writing data.",
        })
    return tenant


@router.get("/signup-onboarding/state")
async def onboarding_state(
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    step = int(tenant.get("onboarding_step") or 1)
    completed_at = tenant.get("onboarding_completed_at")
    completed = bool(completed_at) or step >= 5
    return {
        "step": step, "completed": completed, "completed_at": completed_at,
        "data": {
            "business_name":     tenant.get("name") or "",
            "phone":             user.get("phone") or "",
            "address":           tenant.get("mailing_address") or "",
            "timezone":          tenant.get("timezone") or "America/Phoenix",
            "country":           tenant.get("country") or "US",
            "primary_industry":  tenant.get("primary_industry") or "",
            "active_industries": tenant.get("industries") or [],
        },
    }


class Step1In(BaseModel):
    business_name: Optional[str] = None
    phone:         Optional[str] = None
    address:       Optional[str] = None


@router.patch("/signup-onboarding/step/1")
async def onboarding_step_1(
    body: Step1In,
    user: dict = Depends(require_admin),
    tenant: dict = Depends(require_verified_tenant),
) -> Dict[str, Any]:
    upd: Dict[str, Any] = {}
    if body.business_name is not None:
        upd["name"] = (body.business_name or "").strip()
    if body.address is not None:
        upd["mailing_address"] = (body.address or "").strip()
    if body.phone is not None:
        await db.users.update_one(
            {"id": user["id"]},
            {"$set": {"phone": (body.phone or "").strip()}},
        )
    upd["onboarding_step"] = max(2, int(tenant.get("onboarding_step") or 1))
    await db.tenants.update_one({"id": tenant["id"]}, {"$set": upd})
    return {"step": upd["onboarding_step"], "advanced_to": 2}


class Step2In(BaseModel):
    timezone: str


@router.patch("/signup-onboarding/step/2")
async def onboarding_step_2(
    body: Step2In,
    tenant: dict = Depends(require_verified_tenant),
) -> Dict[str, Any]:
    try:
        ZoneInfo(body.timezone)
    except ZoneInfoNotFoundError:
        raise HTTPException(400, detail={
            "code": "invalid_timezone", "received": body.timezone,
        })
    next_step = max(3, int(tenant.get("onboarding_step") or 1))
    await db.tenants.update_one(
        {"id": tenant["id"]},
        {"$set": {"timezone": body.timezone,
                    "onboarding_step": next_step}},
    )
    return {"step": next_step, "advanced_to": 3, "timezone": body.timezone}


class Invite(BaseModel):
    email: EmailStr
    role:  str = "tech"


class Step3In(BaseModel):
    invites: List[Invite] = []


@router.patch("/signup-onboarding/step/3")
async def onboarding_step_3(
    body: Step3In,
    user: dict = Depends(require_admin),
    tenant: dict = Depends(require_verified_tenant),
) -> Dict[str, Any]:
    sent = 0
    for inv in body.invites:
        role = (inv.role or "tech").lower()
        if role not in {"tech", "manager", "admin"}:
            role = "tech"
        existing = await db.users.find_one({"email": inv.email.lower()})
        if existing:
            continue
        await db.users.insert_one({
            "id":            new_id(),
            "tenant_id":     tenant["id"],
            "email":         inv.email.lower(),
            "name":          inv.email.split("@")[0],
            "role":          role,
            "password_hash": hash_password(new_id()),
            "invited_by":    user["id"],
            "invited_at":    now_iso(),
            "created_at":    now_iso(),
        })
        sent += 1
    next_step = max(4, int(tenant.get("onboarding_step") or 1))
    await db.tenants.update_one(
        {"id": tenant["id"]},
        {"$set": {"onboarding_step": next_step}},
    )
    return {"step": next_step, "advanced_to": 4, "invites_created": sent}


class Step4In(BaseModel):
    industries: List[str]


@router.patch("/signup-onboarding/step/4")
async def onboarding_step_4(
    body: Step4In,
    tenant: dict = Depends(require_verified_tenant),
) -> Dict[str, Any]:
    slugs = []
    for raw in body.industries or []:
        s = (raw or "").strip().lower().replace("-", "_").replace(" ", "_")
        if s in CANONICAL_INDUSTRY_SLUGS and s not in slugs:
            slugs.append(s)
    if not slugs:
        raise HTTPException(400, detail={
            "code": "no_industries_selected",
            "hint": "Select at least one industry.",
        })
    primary = tenant.get("primary_industry")
    if primary and primary not in slugs:
        raise HTTPException(400, detail={
            "code": "primary_industry_required",
            "hint": "Your signup's primary industry must be in the active list.",
            "primary_industry": primary,
        })
    now_ts = datetime.now(timezone.utc).isoformat()
    await db.tenants.update_one(
        {"id": tenant["id"]},
        {"$set": {"industries": slugs, "onboarding_step": 5,
                    "onboarding_completed_at": now_ts}},
    )
    return {"step": 5, "completed": True,
             "onboarding_completed_at": now_ts,
             "industries": slugs}


@router.post("/signup-onboarding/complete")
async def onboarding_complete(
    tenant: dict = Depends(require_verified_tenant),
) -> Dict[str, Any]:
    now_ts = datetime.now(timezone.utc).isoformat()
    await db.tenants.update_one(
        {"id": tenant["id"]},
        {"$set": {"onboarding_step": 5,
                    "onboarding_completed_at": now_ts}},
    )
    return {"step": 5, "completed": True,
             "onboarding_completed_at": now_ts}
