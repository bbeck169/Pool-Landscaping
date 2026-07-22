"""Feb 2026 · Slice O.2 — Referral rewards loop + Slice L.j alias.

Adds:
    * ``GET /api/customer-portal/referrals/my``         — read-back w/ rewards summary
    * ``POST /api/admin/referrals/{id}/revoke-reward``  — clawback path
    * ``PATCH /api/tenants/mine/referral-rewards``      — super-admin config
    * ``GET  /api/tenants/mine/referral-rewards``       — read config
    * :func:`fire_referral_conversion_hook` — invoked from
      ``/api/leads/{lid}/convert`` (existing router) whenever a lead
      sourced from a referral becomes a customer.

Idempotency:
    * ``reward_applied_at`` is checked BEFORE applying; a re-conversion
      of the same lead is a no-op.

Credit ledger:
    * Uses the existing ``customer_credits`` collection (Slice 3B).
      A conversion inserts a positive delta; a revoke inserts a
      negative delta. Both rows carry ``source="referral_reward"`` +
      ``referral_id`` so admin reports can trace back.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, validator

from config import db, logger
from utils import get_current_user, new_id, now_iso, require_admin
from routers.tenants import get_current_tenant

router = APIRouter()

DEFAULT_REWARD_AMOUNT = 25.00
MAX_REWARD_AMOUNT = 1000.00


# ══════════════════════════════════════════════════════════════════════
# Tenant referral-rewards config
# ══════════════════════════════════════════════════════════════════════
class RewardsPatch(BaseModel):
    referral_reward_enabled: Optional[bool] = None
    referral_reward_amount: Optional[float] = Field(None, ge=0, le=MAX_REWARD_AMOUNT)
    referral_reward_currency: Optional[str] = Field(None, max_length=3)


def _rewards_config(tenant: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "referral_reward_enabled": bool(
            tenant.get("referral_reward_enabled", True)
        ),
        "referral_reward_amount": float(
            tenant.get("referral_reward_amount", DEFAULT_REWARD_AMOUNT)
        ),
        "referral_reward_currency": tenant.get("referral_reward_currency") or "USD",
    }


@router.get("/tenants/mine/referral-rewards")
async def get_rewards_config(user: dict = Depends(get_current_user),
                                tenant: dict = Depends(get_current_tenant)):
    if user.get("role") not in ("admin", "super_admin"):
        raise HTTPException(403, "Admin only")
    return _rewards_config(tenant)


@router.patch("/tenants/mine/referral-rewards")
async def patch_rewards_config(body: RewardsPatch,
                                 user: dict = Depends(get_current_user),
                                 tenant: dict = Depends(get_current_tenant)):
    if user.get("role") != "super_admin":
        raise HTTPException(403, "Super-admin only")
    patch: Dict[str, Any] = {}
    if body.referral_reward_enabled is not None:
        patch["referral_reward_enabled"] = bool(body.referral_reward_enabled)
    if body.referral_reward_amount is not None:
        patch["referral_reward_amount"] = round(float(body.referral_reward_amount), 2)
    if body.referral_reward_currency is not None:
        patch["referral_reward_currency"] = body.referral_reward_currency.upper()
    if not patch:
        return _rewards_config(tenant)
    patch["updated_at"] = now_iso()
    await db.tenants.update_one({"id": tenant["id"]}, {"$set": patch})
    fresh = await db.tenants.find_one({"id": tenant["id"]}, {"_id": 0}) or {}
    return _rewards_config(fresh)


# ══════════════════════════════════════════════════════════════════════
# Customer portal — my referrals (with rewards summary)
# ══════════════════════════════════════════════════════════════════════
@router.get("/customer-portal/referrals/my")
async def my_referrals(user: dict = Depends(get_current_user)):
    if user.get("role") != "customer":
        raise HTTPException(403, "Customers only")
    tenant_id = user.get("tenant_id")
    cid = user.get("customer_id") or user.get("id")
    rows = await db.referrals.find(
        {"tenant_id": tenant_id, "referrer_customer_id": cid},
        {"_id": 0},
    ).sort("created_at", -1).to_list(200)
    total = len(rows)
    conversions = sum(1 for r in rows if r.get("status") == "converted")
    rewards = round(sum(float(r.get("reward_amount") or 0)
                         for r in rows if r.get("reward_applied_at")), 2)
    return {
        "referrals": rows,
        "summary": {
            "total_referrals": total,
            "conversions": conversions,
            "rewards_earned": rewards,
        },
    }


# ══════════════════════════════════════════════════════════════════════
# Conversion hook — called from routers/leads.convert_lead
# ══════════════════════════════════════════════════════════════════════
async def fire_referral_conversion_hook(*, tenant_id: str, lead: Dict[str, Any],
                                          new_customer_id: str) -> Dict[str, Any]:
    """Invoked whenever a lead is converted into a customer.  Silently
    returns ``{"applied": False, "reason": ...}`` when the lead was not
    referral-sourced or the referral row is missing.

    Never raises — this hook must not block the outer convert flow.
    """
    source = lead.get("source") or ""
    if not source.startswith("referral_from_customer:"):
        return {"applied": False, "reason": "not-a-referral"}
    referral = await db.referrals.find_one(
        {"tenant_id": tenant_id, "lead_id": lead.get("id")}, {"_id": 0},
    )
    if not referral:
        return {"applied": False, "reason": "referral-row-missing"}
    if referral.get("reward_applied_at"):
        return {"applied": False, "reason": "already-applied",
                "referral_id": referral["id"]}

    tenant = await db.tenants.find_one({"id": tenant_id}, {"_id": 0}) or {}
    cfg = _rewards_config(tenant)

    now = now_iso()
    # Phase 10 · Feb 2026 — the immediate-credit branch below is now
    # GATED by the tenant-scoped legacy flag ``legacy_immediate_referral_credit``
    # (default False). With the flag OFF, we set the referral to
    # ``pending_paid_window`` instead so the daily watcher can credit
    # after the 30-day paid-window guard clears. Tenants that
    # explicitly opt back into the pre-Phase-10 behavior (rare — only
    # while running the back-migration) may set the flag to True.
    legacy_immediate = bool(tenant.get("legacy_immediate_referral_credit", False))
    upd: Dict[str, Any] = {
        "status": (
            "converted" if legacy_immediate else "pending_paid_window"
        ),
        "converted_to_customer_id": new_customer_id,
        "converted_at": now,
        "updated_at": now,
    }
    reward_tx_id: Optional[str] = None
    reward_amount = 0.0

    if legacy_immediate and cfg["referral_reward_enabled"] and cfg["referral_reward_amount"] > 0:
        reward_amount = cfg["referral_reward_amount"]
        # Ledger row — idempotency guarded by the ``reward_applied_at``
        # short-circuit above, but we also namespace the row via
        # ``referral_id`` for reporting.
        reward_tx_id = new_id()
        await db.customer_credits.insert_one({
            "id": reward_tx_id,
            "tenant_id": tenant_id,
            "customer_id": referral["referrer_customer_id"],
            "delta": reward_amount,
            "currency": cfg["referral_reward_currency"],
            "source": "referral_reward",
            "referral_id": referral["id"],
            "note": f"Referral reward — {referral.get('friend_name') or 'friend'} converted",
            "created_at": now,
            "created_by": "referral_hook",
        })
        # Roll balance forward on the ``customer_credits_balance`` row
        # if present (some tenants keep a rolled cache). Non-fatal.
        try:
            await db.customer_credits_balance.update_one(
                {"tenant_id": tenant_id,
                 "customer_id": referral["referrer_customer_id"]},
                {"$inc": {"balance": reward_amount},
                 "$set": {"updated_at": now}},
                upsert=True,
            )
        except Exception as exc:  # pragma: no cover
            logger.warning("[o2] balance rollup failed: %s", exc)
        upd["reward_amount"] = reward_amount
        upd["reward_applied_at"] = now
        upd["reward_transaction_id"] = reward_tx_id
        upd["reward_currency"] = cfg["referral_reward_currency"]

    await db.referrals.update_one(
        {"id": referral["id"]}, {"$set": upd},
    )

    # Bell notification to the referrer (customer portal notification).
    try:
        # The referrer is a customer — resolve their user_id.
        u = await db.users.find_one(
            {"tenant_id": tenant_id, "role": "customer",
             "customer_id": referral["referrer_customer_id"]},
            {"_id": 0, "id": 1},
        )
        if u:
            from services.notifications import emit as _emit
            friend = referral.get("friend_name") or "your friend"
            if reward_amount > 0:
                title = f"Your referral of {friend} became a customer!"
                body = (f"${reward_amount:.2f} credit applied to your account. "
                        "Thanks for spreading the word.")
            else:
                title = f"Your referral of {friend} became a customer!"
                body = "Thanks for the introduction."
            await _emit(
                [u["id"]], kind="general", title=title, body=body,
                source_ref={"kind": "referral", "id": referral["id"]},
                href="/portal", tenant_id=tenant_id,
                customer_id=referral["referrer_customer_id"],
                audience="customer",
            )
    except Exception as exc:  # pragma: no cover
        logger.warning("[o2] referrer bell failed: %s", exc)

    # Phase-3 · transactional email + SMS to the referrer via real
    # adapters.  Suppression skipped for account-critical notifications
    # unless the tenant explicitly disabled that policy.
    try:
        allow_over_suppression = bool(
            tenant.get("allow_transactional_over_suppression", True)
        )
        cat = "transactional" if allow_over_suppression else "marketing"
        referrer = await db.customers.find_one(
            {"id": referral["referrer_customer_id"], "tenant_id": tenant_id},
            {"_id": 0, "name": 1, "email": 1, "phone": 1},
        ) or {}
        friend = referral.get("friend_name") or "your friend"
        first = (referrer.get("name") or "").split(" ")[0] or "there"
        subject = f"Your referral of {friend} became a customer!"
        html = (
            f"<p>Hi {first},</p>"
            f"<p>Great news — <b>{friend}</b> just became a customer with "
            f"{tenant.get('name') or 'us'}.</p>"
        )
        sms_body = subject
        if reward_amount > 0:
            html += (
                f"<p>We've added a <b>${reward_amount:.2f}</b> credit to your "
                "account as a thank-you. It will apply automatically on your "
                "next invoice.</p>"
            )
            sms_body += f" ${reward_amount:.2f} credit applied."
        html += "<p>Thanks for spreading the word!</p>"

        if referrer.get("email"):
            try:
                from services.email.resend_adapter import send as _resend_send
                res = await _resend_send(
                    to=referrer["email"], subject=subject, html=html,
                    category=cat, tenant_id=tenant_id,
                    customer_id=referral["referrer_customer_id"],
                    idempotency_key=f"referral-conv:{referral['id']}",
                )
                await db.marketing_deliveries.insert_one({
                    "id": new_id(), "tenant_id": tenant_id,
                    "kind": "transactional",
                    "trigger_entity": {"kind": "referral",
                                        "id": referral["id"]},
                    "customer_id": referral["referrer_customer_id"],
                    "channel": "email", "recipient_email": referrer["email"],
                    "subject_rendered": subject, "body_rendered": html,
                    "provider": res.get("provider"),
                    "provider_status": res.get("provider_status"),
                    "provider_response_id": res.get("provider_response_id"),
                    "attempts": res.get("attempts") or 0,
                    "mock": res.get("provider") == "mock",
                    "sent_at": now_iso(),
                })
            except Exception as exc:  # pragma: no cover
                logger.warning("[o2] referral email failed: %s", exc)

        if referrer.get("phone"):
            try:
                from services.sms.rc_adapter import send as _sms_send
                res = await _sms_send(
                    to=referrer["phone"], body=sms_body,
                    category=cat, tenant_id=tenant_id,
                    customer_id=referral["referrer_customer_id"],
                    idempotency_key=f"referral-conv:{referral['id']}",
                )
                await db.marketing_deliveries.insert_one({
                    "id": new_id(), "tenant_id": tenant_id,
                    "kind": "transactional",
                    "trigger_entity": {"kind": "referral",
                                        "id": referral["id"]},
                    "customer_id": referral["referrer_customer_id"],
                    "channel": "sms", "recipient_phone": referrer["phone"],
                    "body_rendered": sms_body,
                    "provider": res.get("provider"),
                    "provider_status": res.get("provider_status"),
                    "provider_response_id": res.get("provider_response_id"),
                    "attempts": res.get("attempts") or 0,
                    "mock": res.get("provider") == "mock",
                    "sent_at": now_iso(),
                })
            except Exception as exc:  # pragma: no cover
                logger.warning("[o2] referral SMS failed: %s", exc)
    except Exception as exc:  # pragma: no cover
        logger.warning("[o2] referral transactional send crashed: %s", exc)

    return {
        "applied": bool(reward_amount > 0),
        "referral_id": referral["id"],
        "reward_amount": reward_amount,
        "reward_transaction_id": reward_tx_id,
    }


# ══════════════════════════════════════════════════════════════════════
# Admin — revoke reward (clawback)
# ══════════════════════════════════════════════════════════════════════
@router.post("/admin/referrals/{rid}/revoke-reward")
async def revoke_reward(rid: str,
                          user: dict = Depends(require_admin),
                          tenant: dict = Depends(get_current_tenant)):
    referral = await db.referrals.find_one(
        {"id": rid, "tenant_id": tenant["id"]}, {"_id": 0},
    )
    if not referral:
        raise HTTPException(404, "Referral not found")
    if not referral.get("reward_applied_at"):
        raise HTTPException(409, "No reward applied to this referral")
    if referral.get("reward_revoked_at"):
        raise HTTPException(409, "Reward already revoked")
    amount = float(referral.get("reward_amount") or 0)
    tx_id = new_id()
    now = now_iso()
    await db.customer_credits.insert_one({
        "id": tx_id,
        "tenant_id": tenant["id"],
        "customer_id": referral["referrer_customer_id"],
        "delta": -amount,
        "currency": referral.get("reward_currency") or "USD",
        "source": "referral_reward_revoke",
        "referral_id": referral["id"],
        "note": f"Referral reward revoked by {user.get('email')}",
        "created_at": now,
        "created_by": user.get("id"),
    })
    try:
        await db.customer_credits_balance.update_one(
            {"tenant_id": tenant["id"],
             "customer_id": referral["referrer_customer_id"]},
            {"$inc": {"balance": -amount}, "$set": {"updated_at": now}},
            upsert=True,
        )
    except Exception as exc:  # pragma: no cover
        logger.warning("[o2] balance rollback failed: %s", exc)
    await db.referrals.update_one(
        {"id": rid, "tenant_id": tenant["id"]},
        {"$set": {"reward_revoked_at": now, "reward_revoked_tx_id": tx_id,
                    "reward_revoked_by": user.get("id"), "updated_at": now}},
    )
    return {"revoked": True, "amount": amount, "transaction_id": tx_id}
