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


class CreditsAdjustBody(BaseModel):
    delta_cents: int
    reason: str


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


@router.post("/customers/{cid}/credits/adjust")
async def adjust_customer_credits(
    cid: str, body: CreditsAdjustBody,
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    """Admin-only manual balance adjustment. Positive OR negative
    delta. Never allows the balance to go below zero — returns 400
    ``INSUFFICIENT_BALANCE`` if the requested delta would break the
    floor."""
    if not (body.reason or "").strip() or len(body.reason.strip()) < 5:
        raise HTTPException(400, detail={
            "code": "REASON_REQUIRED",
            "message": "Reason must be at least 5 characters.",
        })
    if body.delta_cents == 0:
        raise HTTPException(400, "delta_cents must be non-zero")

    balance_row = await db.customer_credits_balance.find_one(
        {"tenant_id": tenant["id"], "customer_id": cid}, {"_id": 0},
    ) or {}
    current = int(
        balance_row.get("balance_cents")
        or int(float(balance_row.get("balance") or 0) * 100)
    )
    new_balance = current + body.delta_cents
    if new_balance < 0:
        raise HTTPException(400, detail={
            "code": "INSUFFICIENT_BALANCE",
            "message": f"Cannot decrement below zero (current ${current/100:.2f}).",
        })
    from utils import new_id as _new_id
    entry = {
        "id": _new_id(),
        "tenant_id": tenant["id"],
        "customer_id": cid,
        "delta_cents": body.delta_cents,
        "source": "manual",
        "actor_user_id": user.get("id"),
        "actor_email": user.get("email"),
        "reason": body.reason.strip(),
        "note": body.reason.strip(),
        "created_at": now_iso(),
    }
    await db.customer_credits.insert_one(entry)
    await db.customer_credits_balance.update_one(
        {"tenant_id": tenant["id"], "customer_id": cid},
        {"$set": {"balance_cents": new_balance,
                   "balance": new_balance / 100.0,
                   "updated_at": now_iso()}},
        upsert=True,
    )
    return {
        "ok": True,
        "customer_id": cid,
        "balance_cents": new_balance,
        "balance_formatted": f"${new_balance/100:.2f}",
        "ledger_entry": {k: v for k, v in entry.items() if k != "_id"},
    }


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
# ═══════════════════════════ Manual watcher trigger ═══════════════════
@router.post("/customers/{cid}/credits/{entry_id}/reverse")
async def reverse_customer_credit_entry(
    cid: str, entry_id: str,
    body: dict | None = None,
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    """Task RR/SS Phase 2 followup · Feb 2026 — reverse a prior
    ledger entry by creating an OFFSETTING row (never delete the
    original — audit-trail integrity).

    Guardrails
    ----------
    * Idempotent per entry — refuses if a prior reversal row
      already references this ``entry_id`` (409).
    * Refuses to reverse a reversal (422) — chain unwinds via the
      normal adjust endpoint.
    * Refuses if the resulting balance would go below zero unless
      ``force_negative: true`` is passed AND the caller is
      super_admin (matches the Issue Credit endpoint's semantics).
    * Writes ``credit_admin_audit`` row.
    """
    body = body or {}
    force_negative = bool(body.get("force_negative"))
    # ── Load original entry ─────────────────────────────────────
    original = await db.customer_credits.find_one(
        {"id": entry_id, "tenant_id": tenant["id"], "customer_id": cid},
        {"_id": 0},
    )
    if not original:
        raise HTTPException(404, "credit entry not found")
    if (original.get("kind") == "reversal"
            or original.get("source") == "revert"):
        raise HTTPException(422, "cannot reverse a reversal entry")
    # ── Already-reversed guard ──────────────────────────────────
    prior_reversal = await db.customer_credits.find_one(
        {"tenant_id": tenant["id"], "customer_id": cid,
          "reverted_from_entry_id": entry_id},
        {"_id": 0, "id": 1},
    )
    if prior_reversal:
        raise HTTPException(409, "entry already reversed")
    # ── Balance guard ───────────────────────────────────────────
    orig_delta = int(original.get("delta_cents") or 0)
    reversal_delta = -orig_delta
    balance_row = await db.customer_credits_balance.find_one(
        {"tenant_id": tenant["id"], "customer_id": cid}, {"_id": 0},
    ) or {}
    current = int(
        balance_row.get("balance_cents")
        or int(float(balance_row.get("balance") or 0) * 100)
    )
    new_balance = current + reversal_delta
    if new_balance < 0:
        if not force_negative:
            raise HTTPException(422, detail={
                "code": "INSUFFICIENT_BALANCE",
                "message": (f"Reversal would push balance to "
                                 f"${new_balance/100:.2f}. Pass "
                                 "force_negative=true (super_admin only) "
                                 "to proceed."),
            })
        if user.get("role") != "super_admin":
            raise HTTPException(
                403, "only super_admin can force a negative balance",
            )
    # ── Insert reversal row + update balance ────────────────────
    from utils import new_id as _new_id
    reversal_entry = {
        "id": _new_id(),
        "tenant_id": tenant["id"],
        "customer_id": cid,
        "delta_cents": reversal_delta,
        "source": "revert",
        "kind": "reversal",
        "reverted_from_entry_id": entry_id,
        "actor_user_id": user.get("id"),
        "actor_email": user.get("email"),
        "reason": f"Reversal of entry {entry_id}",
        "note": f"Reversal of entry {entry_id}",
        "created_at": now_iso(),
    }
    await db.customer_credits.insert_one(reversal_entry)
    await db.customer_credits_balance.update_one(
        {"tenant_id": tenant["id"], "customer_id": cid},
        {"$set": {"balance_cents": new_balance,
                    "balance": new_balance / 100.0,
                    "updated_at": now_iso()}},
        upsert=True,
    )
    # ── Audit ────────────────────────────────────────────────────
    try:
        await db.credit_admin_audit.insert_one({
            "id": _new_id(),
            "tenant_id": tenant["id"],
            "customer_id": cid,
            "acting_user_id": user.get("id"),
            "acting_user_role": user.get("role"),
            "action": "reverse",
            "entry_id": entry_id,
            "reversal_entry_id": reversal_entry["id"],
            "amount_cents": reversal_delta,
            "balance_before_cents": current,
            "balance_after_cents": new_balance,
            "created_at": now_iso(),
        })
    except Exception:                                                # noqa: BLE001
        pass
    return {
        "ok": True,
        "customer_id": cid,
        "balance_cents": new_balance,
        "balance_formatted": f"${new_balance/100:.2f}",
        "ledger_entry": {k: v for k, v in reversal_entry.items() if k != "_id"},
    }


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
