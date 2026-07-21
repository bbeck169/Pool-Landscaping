"""Feb-2026 · Marketing Slice F — Customer preferences + suppression list.

Ships:

* Customer-facing preferences center (``GET/PATCH /customer-portal/preferences``)
* One-click magic-link unsubscribe (``/portal/preferences/token/verify`` +
  ``/portal/preferences/via-token`` — public, no auth)
* Suppression list CRUD (admin) at ``/marketing/suppressions``
* Shared enforcement helper :func:`is_suppressed` consumed by M5 tick,
  M6 tick and M2 campaign send paths

Compliance rule locked in code: transactional channels
(``email_transactional`` / ``sms_transactional``) can NEVER be flipped
off.  The PATCH endpoints raise 422 if a caller tries.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import jwt
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from config import db, JWT_SECRET, JWT_ALGO, logger
from utils import (
    new_id, now_iso, require_admin, get_current_user,
)
from routers.tenants import get_current_tenant

router = APIRouter()

TOKEN_SUB = "unsub"

_DEFAULT_CHANNEL_OPT_IN = {
    "email_marketing": True,
    "email_transactional": True,
    "sms_marketing": True,
    "sms_transactional": True,
}
_DEFAULT_CATEGORY_OPT_IN = {
    "review_requests": True,
    "sequences": True,
    "campaigns": True,
}


def _merge_defaults(cust: Dict[str, Any]) -> Dict[str, Any]:
    """Lazy backfill — legacy customer docs without opt-in fields are
    treated as fully opted-in on read.  Never writes back; the first
    PATCH persists the merged shape."""
    channel = dict(_DEFAULT_CHANNEL_OPT_IN)
    channel.update(cust.get("channel_opt_in") or {})
    # Transactional flags are compliance-locked to True — we never
    # honour a stored ``false`` on those.
    channel["email_transactional"] = True
    channel["sms_transactional"] = True
    category = dict(_DEFAULT_CATEGORY_OPT_IN)
    category.update(cust.get("category_opt_in") or {})
    return {"channel_opt_in": channel, "category_opt_in": category}


# ── Models ───────────────────────────────────────────────────────────
class PreferencesPatch(BaseModel):
    channel_opt_in: Optional[Dict[str, bool]] = None
    category_opt_in: Optional[Dict[str, bool]] = None


class ViaTokenPreferencesPatch(BaseModel):
    token: str
    channel_opt_in: Optional[Dict[str, bool]] = None
    category_opt_in: Optional[Dict[str, bool]] = None


class SuppressionIn(BaseModel):
    channel: str = Field(..., pattern="^(email|sms)$")
    address: str = Field(..., min_length=3)
    reason: str = "manual_admin"
    category: Optional[str] = None
    customer_id: Optional[str] = None


# ── Magic-link (unsubscribe) helpers ─────────────────────────────────
def _sign_unsub_token(customer_id: str, tenant_id: str,
                      expire_days: int = 90) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": TOKEN_SUB,
        "cid": customer_id,
        "tid": tenant_id,
        "iat": int(now.timestamp()),
        "exp": now + timedelta(days=expire_days),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)


def _verify_unsub_token(tok: str) -> Dict[str, Any]:
    try:
        payload = jwt.decode(tok, JWT_SECRET, algorithms=[JWT_ALGO])
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "Unsubscribe link expired")
    except jwt.PyJWTError:
        raise HTTPException(401, "Invalid unsubscribe link")
    if payload.get("sub") != TOKEN_SUB:
        raise HTTPException(401, "Invalid unsubscribe link")
    return payload


def build_unsubscribe_url(customer_id: str, tenant_id: str) -> str:
    """Per-recipient link injected into every marketing send.  Consumed
    by M5c ``_deliver_step`` and M6 ``_deliver`` before rendering the
    template body.  Uses the public ``/r/preferences`` route so a
    logged-out recipient can update preferences without signing in."""
    tok = _sign_unsub_token(customer_id, tenant_id, expire_days=90)
    return f"/r/preferences?token={tok}"


# ═══════════════════════════════════════════════════════════════════════
# Customer-side preferences (portal, logged-in customer)
# ═══════════════════════════════════════════════════════════════════════
def _guard_transactional(payload: Dict[str, bool]) -> None:
    for key in ("email_transactional", "sms_transactional"):
        if key in payload and payload[key] is False:
            raise HTTPException(
                422,
                f"{key} is compliance-locked to true and cannot be disabled",
            )


async def _apply_preferences(tenant_id: str, customer: Dict[str, Any],
                             channel_patch: Optional[Dict[str, bool]],
                             category_patch: Optional[Dict[str, bool]],
                             actor_id: str = "customer") -> Dict[str, Any]:
    """Merge patch → save → reconcile suppression rows."""
    merged = _merge_defaults(customer)
    new_channel = dict(merged["channel_opt_in"])
    new_category = dict(merged["category_opt_in"])
    if channel_patch:
        _guard_transactional(channel_patch)
        for k, v in channel_patch.items():
            if k in new_channel:
                new_channel[k] = bool(v)
    if category_patch:
        for k, v in category_patch.items():
            if k in new_category:
                new_category[k] = bool(v)
    # Compliance-lock transactional flags no matter what.
    new_channel["email_transactional"] = True
    new_channel["sms_transactional"] = True
    await db.customers.update_one(
        {"id": customer["id"], "tenant_id": tenant_id},
        {"$set": {"channel_opt_in": new_channel,
                    "category_opt_in": new_category,
                    "preferences_updated_at": now_iso()}},
    )
    await _reconcile_suppressions(tenant_id, customer,
                                   new_channel, new_category, actor_id)
    return {"channel_opt_in": new_channel, "category_opt_in": new_category}


async def _reconcile_suppressions(
    tenant_id: str, customer: Dict[str, Any],
    channel: Dict[str, bool], category: Dict[str, bool],
    actor_id: str,
) -> None:
    """When any opt-in is False → ensure a matching active suppression
    row exists.  When flipped True → soft-delete matching rows so live
    provider send paths stop suppressing next time."""
    email = (customer.get("email") or "").strip().lower()
    phone = (customer.get("phone") or "").strip()
    now = now_iso()
    async def _ensure(address, ch, cat):
        if not address:
            return
        existing = await db.marketing_suppressions.find_one({
            "tenant_id": tenant_id, "channel": ch, "address": address,
            "category": cat, "deleted_at": None,
        }, {"_id": 0, "id": 1})
        if existing:
            return
        await db.marketing_suppressions.insert_one({
            "id": new_id(), "tenant_id": tenant_id,
            "channel": ch, "address": address,
            "reason": "user_unsubscribe",
            "category": cat,
            "customer_id": customer["id"],
            "created_at": now, "created_by": actor_id,
            "deleted_at": None,
        })
    async def _revoke(address, ch, cat):
        if not address:
            return
        await db.marketing_suppressions.update_many(
            {"tenant_id": tenant_id, "channel": ch, "address": address,
             "category": cat, "deleted_at": None},
            {"$set": {"deleted_at": now}},
        )

    # Channel-level (category = "all") — email/sms marketing opt-outs.
    for ch, key in (("email", "email_marketing"), ("sms", "sms_marketing")):
        addr = email if ch == "email" else phone
        if channel.get(key) is False:
            await _ensure(addr, ch, "all")
        else:
            await _revoke(addr, ch, "all")
    # Category-level — per-topic opt-outs.  We treat these as
    # cross-channel; the tick handler checks both category="all" AND
    # the specific category before sending.
    for cat_key in ("review_requests", "sequences", "campaigns"):
        for ch in ("email", "sms"):
            addr = email if ch == "email" else phone
            if category.get(cat_key) is False:
                await _ensure(addr, ch, cat_key)
            else:
                await _revoke(addr, ch, cat_key)


@router.get("/customer-portal/preferences")
async def get_customer_preferences(user: dict = Depends(get_current_user)):
    if user.get("role") != "customer":
        raise HTTPException(403, "Customers only")
    cust = await db.customers.find_one(
        {"id": user.get("customer_id") or user.get("id"),
         "tenant_id": user["tenant_id"]},
        {"_id": 0},
    )
    if not cust:
        raise HTTPException(404, "Customer not found")
    return _merge_defaults(cust)


@router.patch("/customer-portal/preferences")
async def patch_customer_preferences(
    body: PreferencesPatch,
    user: dict = Depends(get_current_user),
):
    if user.get("role") != "customer":
        raise HTTPException(403, "Customers only")
    cust = await db.customers.find_one(
        {"id": user.get("customer_id") or user.get("id"),
         "tenant_id": user["tenant_id"]},
        {"_id": 0},
    )
    if not cust:
        raise HTTPException(404, "Customer not found")
    return await _apply_preferences(
        user["tenant_id"], cust, body.channel_opt_in, body.category_opt_in,
        actor_id=user["id"],
    )


# ═══════════════════════════════════════════════════════════════════════
# Magic-link unsubscribe (public, no auth)
# ═══════════════════════════════════════════════════════════════════════
@router.get("/portal/preferences/token/verify")
async def verify_preferences_token(token: str = Query(...)):
    payload = _verify_unsub_token(token)
    cust = await db.customers.find_one(
        {"id": payload["cid"], "tenant_id": payload["tid"]},
        {"_id": 0},
    )
    if not cust:
        raise HTTPException(401, "Invalid unsubscribe link")
    prefs = _merge_defaults(cust)
    return {
        "customer_id": cust["id"],
        "tenant_id": cust["tenant_id"],
        "customer_name": cust.get("name"),
        **prefs,
    }


@router.post("/portal/preferences/via-token")
async def patch_preferences_via_token(body: ViaTokenPreferencesPatch):
    payload = _verify_unsub_token(body.token)
    cust = await db.customers.find_one(
        {"id": payload["cid"], "tenant_id": payload["tid"]}, {"_id": 0},
    )
    if not cust:
        raise HTTPException(401, "Invalid unsubscribe link")
    return await _apply_preferences(
        payload["tid"], cust, body.channel_opt_in, body.category_opt_in,
        actor_id=f"token:{payload['cid']}",
    )


# ═══════════════════════════════════════════════════════════════════════
# Suppression list (admin CRUD)
# ═══════════════════════════════════════════════════════════════════════
@router.get("/marketing/suppressions")
async def list_suppressions(
    channel: Optional[str] = Query(None),
    reason: Optional[str] = Query(None),
    limit: int = Query(200, ge=1, le=500), offset: int = Query(0, ge=0),
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    q: Dict[str, Any] = {"tenant_id": tenant["id"], "deleted_at": None}
    if channel: q["channel"] = channel
    if reason: q["reason"] = reason
    total = await db.marketing_suppressions.count_documents(q)
    rows = await db.marketing_suppressions.find(q, {"_id": 0}).sort(
        "created_at", -1,
    ).skip(offset).limit(limit).to_list(limit)
    return {"suppressions": rows, "total": total}


@router.post("/marketing/suppressions", status_code=201)
async def add_suppression(
    body: SuppressionIn,
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    addr = body.address.strip()
    if body.channel == "email":
        addr = addr.lower()
    row = {
        "id": new_id(), "tenant_id": tenant["id"],
        "channel": body.channel, "address": addr,
        "reason": body.reason, "category": body.category,
        "customer_id": body.customer_id,
        "created_at": now_iso(), "created_by": user["id"],
        "deleted_at": None,
    }
    await db.marketing_suppressions.insert_one(row)
    row.pop("_id", None)
    return row


@router.delete("/marketing/suppressions/{sid}", status_code=204)
async def delete_suppression(
    sid: str,
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    r = await db.marketing_suppressions.update_one(
        {"id": sid, "tenant_id": tenant["id"], "deleted_at": None},
        {"$set": {"deleted_at": now_iso()}},
    )
    if r.matched_count == 0:
        raise HTTPException(404, "Suppression not found")


# ═══════════════════════════════════════════════════════════════════════
# Shared enforcement helper — consumed by M5c / M6 tick + M2 send path
# ═══════════════════════════════════════════════════════════════════════
async def is_suppressed(
    tenant_id: str,
    customer: Dict[str, Any],
    *,
    channel: str,
    category: str,
) -> bool:
    """Return True when the recipient's address+channel is on the
    active suppression list either for the specific ``category`` OR
    for ``"all"`` (a full-channel opt-out).  Transactional callers
    should NOT call this function; only marketing/review/sequence
    send paths."""
    addr = ((customer.get("email") if channel == "email" else customer.get("phone")) or "").strip()
    if channel == "email":
        addr = addr.lower()
    if not addr:
        return False
    hit = await db.marketing_suppressions.find_one({
        "tenant_id": tenant_id, "channel": channel, "address": addr,
        "category": {"$in": ["all", category]},
        "deleted_at": None,
    }, {"_id": 0, "id": 1})
    return hit is not None
