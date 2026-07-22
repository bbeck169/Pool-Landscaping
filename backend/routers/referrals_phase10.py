"""Phase 10 · Feb 2026 — Referral endpoints + admin re-eligible/void.

Layered on top of the existing referrals collection. The pre-Phase-10
routers (``referrals.py``, ``referral_rewards.py``, ``portal_referrals.py``)
still expose their legacy surfaces; this file adds NEW admin
endpoints for the paid-window watcher lifecycle:

  * ``GET  /api/referrals/summary``       — tenant KPIs
  * ``POST /api/referrals/{rid}/re-eligible`` — admin action
  * ``POST /api/referrals/{rid}/void``    — admin action
  * ``GET  /api/customers/{cid}/credits`` — balance + ledger (self OR admin)
  * ``POST /api/admin/referral-watcher/run`` — manual trigger for tenant

Also exposes the Phase-10 status enum for consistency and centralises
the conversion-hook rewire so ``fire_referral_conversion_hook`` no
longer immediately credits — it now sets ``status="pending_paid_window"``
and stashes the timestamps the watcher needs.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from config import db, logger
from utils import get_current_user, new_id, now_iso, require_admin
from routers.tenants import get_current_tenant

router = APIRouter()


PHASE10_STATUSES = (
    "pending_conversion", "pending_paid_window",
    "crediting_in_progress", "credited", "voided",
)


class VoidBody(BaseModel):
    reason: Optional[str] = "manual"


# ═══════════════════════════ Summary ══════════════════════════════════
@router.get("/referrals/summary")
async def referrals_summary(
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    pipeline = [
        {"$match": {"tenant_id": tenant["id"]}},
        {"$group": {"_id": "$status", "n": {"$sum": 1}}},
    ]
    counts: Dict[str, int] = {s: 0 for s in PHASE10_STATUSES}
    async for r in db.referrals.aggregate(pipeline):
        s = r["_id"] or ""
        if s in counts:
            counts[s] = int(r["n"])
        else:
            counts.setdefault(s, int(r["n"]))
    total_credited_cents = 0
    async for r in db.referrals.find(
        {"tenant_id": tenant["id"], "status": "credited"},
        {"_id": 0, "credit_amount_cents": 1},
    ):
        total_credited_cents += int(r.get("credit_amount_cents") or 0)
    return {
        "counts_by_status": counts,
        "total_credited_cents": total_credited_cents,
        "total_credited_formatted": f"${total_credited_cents / 100:,.2f}",
    }


# ═══════════════════════════ Admin actions ═════════════════════════════
@router.post("/referrals/{rid}/re-eligible")
async def make_referral_re_eligible(
    rid: str,
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    row = await db.referrals.find_one(
        {"id": rid, "tenant_id": tenant["id"]}, {"_id": 0},
    )
    if not row:
        raise HTTPException(404, "Referral not found")
    if row.get("status") == "credited":
        raise HTTPException(
            400, "Already credited — cannot re-eligible without manual reversal.",
        )
    await db.referrals.update_one(
        {"id": rid},
        {"$set": {
            "status": "pending_paid_window",
            "voided_reason": None,
            "voided_at": None,
            "updated_at": now_iso(),
            "re_eligible_by": user.get("id"),
            "re_eligible_at": now_iso(),
        }},
    )
    return {"ok": True, "referral_id": rid, "status": "pending_paid_window"}


@router.post("/referrals/{rid}/void")
async def void_referral(
    rid: str, body: VoidBody,
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    row = await db.referrals.find_one(
        {"id": rid, "tenant_id": tenant["id"]}, {"_id": 0},
    )
    if not row:
        raise HTTPException(404, "Referral not found")
    if row.get("status") == "credited":
        raise HTTPException(
            400, "Already credited — void the credit via ledger first.",
        )
    await db.referrals.update_one(
        {"id": rid},
        {"$set": {
            "status": "voided",
            "voided_reason": body.reason or "manual",
            "voided_at": now_iso(),
            "voided_by": user.get("id"),
            "updated_at": now_iso(),
        }},
    )
    return {"ok": True, "referral_id": rid, "status": "voided"}


# ═══════════════════════════ Customer credits view ═════════════════════
@router.get("/customers/{cid}/credits")
async def get_customer_credits(
    cid: str,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    # Self OR admin.
    role = user.get("role") or ""
    if role not in ("admin", "super_admin", "manager"):
        if user.get("customer_id") != cid:
            raise HTTPException(403, "Not allowed")
    balance_row = await db.customer_credits_balance.find_one(
        {"tenant_id": tenant["id"], "customer_id": cid},
        {"_id": 0},
    ) or {}
    balance_cents = int(
        balance_row.get("balance_cents")
        or int(float(balance_row.get("balance") or 0) * 100)
    )
    ledger = await db.customer_credits.find(
        {"tenant_id": tenant["id"], "customer_id": cid},
        {"_id": 0},
    ).sort([("created_at", -1)]).to_list(50)
    return {
        "customer_id": cid,
        "balance_cents": balance_cents,
        "balance_formatted": f"${balance_cents / 100:,.2f}",
        "ledger": ledger,
    }


# ═══════════════════════════ Manual watcher trigger ═══════════════════
@router.post("/admin/referral-watcher/run")
async def manual_watcher_run(
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    from services.referral_watcher import run_referral_watcher
    res = await run_referral_watcher(tenant)
    return res


# ═══════════════════════════ Conversion hook rewire ═══════════════════
async def gate_conversion_at_paid_window(
    *, tenant_id: str, referral_row_id: str, new_customer_id: str,
) -> None:
    """Called from ``routers/leads.close-won`` conversion path AFTER
    the legacy ``fire_referral_conversion_hook`` has run. If the
    referral was set to ``status="converted"`` with a
    ``reward_applied_at`` (immediate credit fired), Phase-10 leaves
    it alone — the back-migration will finalise it. If the referral
    is fresh (no ``reward_applied_at``), we gate it here.
    """
    row = await db.referrals.find_one(
        {"id": referral_row_id, "tenant_id": tenant_id}, {"_id": 0},
    )
    if not row:
        return
    if row.get("reward_applied_at"):
        return  # immediate-credit path already ran — leave for back-migration
    await db.referrals.update_one(
        {"id": referral_row_id},
        {"$set": {
            "status": "pending_paid_window",
            "converted_to_customer_id": new_customer_id,
            "converted_at": row.get("converted_at") or now_iso(),
            "updated_at": now_iso(),
        }},
    )
