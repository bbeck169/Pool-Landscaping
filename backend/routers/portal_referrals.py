"""Feb 2026 · Slice O — Portal Call Now + Referral form.

Two additions to the customer portal surface:

* ``GET /api/tenants/mine/public-config`` — a small, unauthed-safe
  bundle of the tenant identity + Slice O ``support_phone_number``.
  Consumed by the portal Call Now button.  Available to logged-in
  customers only (403 for anonymous callers to avoid leaking tenant
  metadata by slug enumeration).

* ``POST /api/customer-portal/referrals`` — logged-in customer
  submits a friend's contact details.  Creates a lead, a referral
  row, and pings admins via the notifications bell.  Includes
  self-referral guard + per-day rate limit + duplicate-of-existing
  detection.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field, validator

from config import db, logger
from utils import get_current_user, new_id, now_iso, require_admin
from routers.tenants import get_current_tenant

router = APIRouter()

RATE_LIMIT_PER_DAY = 5
DUP_LOOKBACK_DAYS = 30

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
# Extremely tolerant phone check — normalise before storing.
_PHONE_DIGITS_RE = re.compile(r"[^\d+]")


def _normalise_phone(raw: Optional[str]) -> str:
    if not raw:
        return ""
    return _PHONE_DIGITS_RE.sub("", raw)


def _normalise_email(raw: Optional[str]) -> str:
    return (raw or "").strip().lower()


# ══════════════════════════════════════════════════════════════════════
# GET /api/tenants/mine/public-config  (customer + staff readable)
# ══════════════════════════════════════════════════════════════════════
@router.get("/tenants/mine/public-config")
async def get_tenant_public_config(user: dict = Depends(get_current_user)):
    """Returns the bits of the tenant doc safe to expose on the customer
    portal + tech shells: name, brand colours, support phone number.
    Never leaks integration keys, HQ address details, or internal
    settings."""
    tid = user.get("tenant_id")
    if not tid:
        raise HTTPException(400, "User has no tenant")
    t = await db.tenants.find_one({"id": tid}, {"_id": 0}) or {}
    return {
        "tenant_id": t.get("id"),
        "tenant_name": t.get("name"),
        "brand_primary": t.get("brand_primary"),
        "brand_secondary": t.get("brand_secondary"),
        "support_phone_number": t.get("support_phone_number") or None,
        "support_email": t.get("support_email") or None,
    }


class SupportPhonePatch(BaseModel):
    support_phone_number: Optional[str] = None

    @validator("support_phone_number")
    def _looks_like_phone(cls, v):
        if v in (None, ""):
            return v
        digits = _PHONE_DIGITS_RE.sub("", v)
        if len(digits) < 10:
            raise ValueError("Enter at least 10 digits (US number).")
        return v.strip()


@router.patch("/tenants/mine/support-phone")
async def patch_support_phone(
    body: SupportPhonePatch,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    """Super-admin edit for the Slice O ``support_phone_number`` field."""
    if user.get("role") != "super_admin":
        raise HTTPException(403, "Super-admin only")
    patch = {
        "support_phone_number": body.support_phone_number or None,
        "updated_at": now_iso(),
    }
    await db.tenants.update_one({"id": tenant["id"]}, {"$set": patch})
    return {"support_phone_number": patch["support_phone_number"]}


# ══════════════════════════════════════════════════════════════════════
# POST /api/customer-portal/referrals
# ══════════════════════════════════════════════════════════════════════
class ReferralIn(BaseModel):
    friend_name: str = Field(..., min_length=1, max_length=120)
    friend_phone: Optional[str] = ""
    friend_email: Optional[str] = ""
    friend_address: Optional[str] = ""
    service_of_interest: Optional[str] = ""
    notes: Optional[str] = ""

    @validator("friend_email")
    def _email_ok(cls, v):
        v = _normalise_email(v)
        if v and not _EMAIL_RE.match(v):
            raise ValueError("Invalid email format")
        return v


async def _find_admin_user_ids(tenant_id: str) -> List[str]:
    rows = await db.users.find(
        {"tenant_id": tenant_id, "role": {"$in": ["admin", "super_admin"]}},
        {"_id": 0, "id": 1},
    ).to_list(50)
    return [r["id"] for r in rows]


async def _duplicate_lookup(tenant_id: str, phone: str, email: str) -> bool:
    """True when the friend's phone/email already exists as a customer
    OR as a lead created in the last 30 days.  Never blocks the
    submission — the flag is just surfaced back for admin visibility."""
    if not (phone or email):
        return False
    since = (datetime.now(timezone.utc) - timedelta(days=DUP_LOOKBACK_DAYS)).isoformat()
    or_clauses: List[Dict[str, Any]] = []
    if email:
        or_clauses.append({"email": email})
    if phone:
        or_clauses.append({"phone": phone})
    if not or_clauses:
        return False
    hit = await db.customers.find_one(
        {"tenant_id": tenant_id, "$or": or_clauses}, {"_id": 0, "id": 1},
    )
    if hit:
        return True
    hit = await db.leads.find_one(
        {"tenant_id": tenant_id, "$or": or_clauses,
         "created_at": {"$gte": since}},
        {"_id": 0, "id": 1},
    )
    return hit is not None


@router.post("/customer-portal/referrals", status_code=201)
async def create_customer_referral(
    body: ReferralIn,
    background_tasks: BackgroundTasks,
    user: dict = Depends(get_current_user),
):
    if user.get("role") != "customer":
        raise HTTPException(403, "Customers only")
    tenant_id = user.get("tenant_id")
    if not tenant_id:
        raise HTTPException(400, "User has no tenant")
    customer_id = user.get("customer_id") or user.get("id")
    referrer = await db.customers.find_one(
        {"id": customer_id, "tenant_id": tenant_id},
        {"_id": 0, "id": 1, "name": 1, "email": 1, "phone": 1},
    )
    if not referrer:
        raise HTTPException(404, "Customer record not found")

    friend_email = _normalise_email(body.friend_email)
    friend_phone = _normalise_phone(body.friend_phone)
    if not (friend_email or friend_phone):
        raise HTTPException(422, "Provide a phone number or email for your friend.")

    # Self-referral guard.
    referrer_email = _normalise_email(referrer.get("email"))
    referrer_phone = _normalise_phone(referrer.get("phone"))
    if friend_email and referrer_email and friend_email == referrer_email:
        raise HTTPException(422, "Please enter a friend's info, not your own.")
    if friend_phone and referrer_phone and friend_phone == referrer_phone:
        raise HTTPException(422, "Please enter a friend's info, not your own.")

    # Rate limit: 5 per rolling 24h.
    day_ago = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    recent = await db.referrals.count_documents({
        "tenant_id": tenant_id,
        "referrer_customer_id": customer_id,
        "created_at": {"$gte": day_ago},
    })
    if recent >= RATE_LIMIT_PER_DAY:
        raise HTTPException(
            429,
            f"You've reached the daily referral limit of {RATE_LIMIT_PER_DAY}. "
            "Please try again tomorrow.",
        )

    dup = await _duplicate_lookup(tenant_id, friend_phone, friend_email)

    lead_id = new_id()
    referral_id = new_id()
    now = now_iso()

    lead_doc = {
        "id": lead_id,
        "tenant_id": tenant_id,
        "name": body.friend_name.strip(),
        "phone": friend_phone,
        "email": friend_email,
        "address": (body.friend_address or "").strip(),
        "source": f"referral_from_customer:{customer_id}",
        "referrer_customer_id": customer_id,
        "referrer_customer_name": referrer.get("name"),
        "duplicate_of_existing_contact": dup,
        "status": "new",
        "notes": (body.notes or "").strip(),
        "service_of_interest": (body.service_of_interest or "").strip(),
        "created_at": now,
        "created_by": customer_id,
    }
    await db.leads.insert_one(lead_doc)
    # Feb-2026 · Fire ``new_lead`` sequence trigger for portal
    # referral inbound (customer-referred-a-friend flow). No
    # ``BackgroundTasks`` in this handler — enrolment is fast enough
    # inline.
    try:
        from services.marketing.lead_triggers import (
            fire_new_lead_sequence_trigger,
        )
        await fire_new_lead_sequence_trigger(
            lead=lead_doc, tenant_id=tenant_id,
        )
    except Exception:
        pass
    # Phase K63.finalize · Feb-2026 — customer-portal referrals are
    # a live inbound path (customer submitted a friend's contact),
    # so they qualify for the K63 SMS + email fan-out just like the
    # widget-form ingresses. Fire-and-forget via BackgroundTasks.
    try:
        tenant_doc = await db.tenants.find_one(
            {"id": tenant_id}, {"_id": 0},
        ) or {}
        from services.lead_notifications import send_lead_alert_notifications
        await send_lead_alert_notifications(
            lead=lead_doc, tenant=tenant_doc,
            background_tasks=background_tasks,
        )
    except Exception as _e:
        logger.warning(f"[k63] portal-referral dispatch failed: {_e}")

    referral_doc = {
        "id": referral_id,
        "tenant_id": tenant_id,
        "referrer_customer_id": customer_id,
        "lead_id": lead_id,
        "friend_name": body.friend_name.strip(),
        "friend_phone": friend_phone,
        "friend_email": friend_email,
        "friend_address": (body.friend_address or "").strip(),
        "service_of_interest": (body.service_of_interest or "").strip(),
        "notes": (body.notes or "").strip(),
        "duplicate_of_existing_contact": dup,
        "status": "new",
        "created_at": now,
        "converted_to_customer_id": None,
        "converted_at": None,
    }
    await db.referrals.insert_one(referral_doc)

    # Bell notification to every admin in the tenant.
    admin_ids = await _find_admin_user_ids(tenant_id)
    try:
        from services.notifications import emit as _emit
        title = f"Referral from {referrer.get('name') or 'a customer'}: {body.friend_name.strip()}"
        friend_reach = friend_email or friend_phone or ""
        body_txt = f"{body.friend_name.strip()}"
        if friend_reach:
            body_txt += f" · {friend_reach}"
        if body.service_of_interest:
            body_txt += f" · interested in {body.service_of_interest}"
        if dup:
            body_txt += " · (matches an existing contact)"
        await _emit(
            admin_ids, kind="lead_new", title=title, body=body_txt,
            source_ref={"kind": "referral", "id": referral_id, "lead_id": lead_id},
            href=f"/leads/{lead_id}",
            tenant_id=tenant_id, customer_id=customer_id,
        )
    except Exception as exc:  # pragma: no cover — non-fatal
        logger.warning("[slice-o] referral bell emit failed: %s", exc)

    referral_doc.pop("_id", None)
    return {
        "referral": referral_doc,
        "lead_id": lead_id,
        "duplicate_of_existing_contact": dup,
        "message": f"Thanks! We'll reach out to {body.friend_name.strip()} soon.",
    }


@router.get("/customer-portal/referrals")
async def list_my_referrals(user: dict = Depends(get_current_user)):
    """Optional read-back so the portal can show 'your recent referrals'."""
    if user.get("role") != "customer":
        raise HTTPException(403, "Customers only")
    cid = user.get("customer_id") or user.get("id")
    rows = await db.referrals.find(
        {"tenant_id": user["tenant_id"], "referrer_customer_id": cid},
        {"_id": 0},
    ).sort("created_at", -1).to_list(50)
    return {"referrals": rows}


# ══════════════════════════════════════════════════════════════════════
# Admin — list + filter referrals (mirrors leads dashboard)
# ══════════════════════════════════════════════════════════════════════
@router.get("/admin/referrals")
async def admin_list_referrals(
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    rows = await db.referrals.find(
        {"tenant_id": tenant["id"]}, {"_id": 0},
    ).sort("created_at", -1).to_list(500)
    return {"referrals": rows}
