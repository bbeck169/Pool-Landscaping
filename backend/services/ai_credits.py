"""QuoteIQ Phase Q1 · Sub-scope A — AI Credits ledger + soft enforcement.

The credits ledger is the foundation for every downstream QuoteIQ AI
feature (Q2 Estimator, Q3 Autopilot copy, Q4 Before/After, Q5 Virtual
Call Team, Q6 more). Debits are **soft** — the helper always allows
the operation and returns a warning flag when the balance is low or
negative. The router layer surfaces that warning in its response.

Tenant fields:
    ai_credits_balance           int
    ai_credits_monthly_grant     int   (defaults from plan)
    ai_credits_last_reset_at     ISO string
    ai_credits_plan              str   ("essentials"|"beginner"|"pro"|"elite"|"max")

Plan grants:
    essentials → 500, beginner → 1500, pro → 3000, elite → 5000, max → 8000

Ledger collection ``ai_credit_transactions``:
    {id, tenant_id, delta (signed), reason, feature, ref_id, ref_type,
     balance_after, created_at, created_by}
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from config import db, logger
from utils import new_id, now_iso


PLAN_GRANTS: Dict[str, int] = {
    "essentials": 500,
    "beginner": 1500,
    "pro": 3000,
    "elite": 5000,
    "max": 8000,
}
DEFAULT_PLAN = "essentials"

ALLOWED_FEATURES = {
    "estimator", "autopilot", "before_after", "virtual_call", "other",
}

# Balance falls below this fraction of monthly_grant → warning flag.
WARN_FRACTION = 0.20


def grant_for(plan: str) -> int:
    return PLAN_GRANTS.get((plan or "").lower(), PLAN_GRANTS[DEFAULT_PLAN])


async def ensure_tenant_credits_initialized(tenant_id: str) -> Dict[str, Any]:
    """Lazy-initialize AI credits fields on the tenant doc. Idempotent."""
    t = await db.tenants.find_one({"id": tenant_id}, {"_id": 0})
    if not t:
        raise ValueError(f"tenant {tenant_id!r} not found")
    if "ai_credits_plan" in t and "ai_credits_balance" in t:
        return t
    plan = t.get("ai_credits_plan") or DEFAULT_PLAN
    grant = grant_for(plan)
    upd = {
        "ai_credits_plan": plan,
        "ai_credits_monthly_grant": grant,
        "ai_credits_balance": t.get("ai_credits_balance", grant),
        "ai_credits_last_reset_at": t.get("ai_credits_last_reset_at") or now_iso(),
    }
    await db.tenants.update_one({"id": tenant_id}, {"$set": upd})
    # Log the initial grant so the ledger has provenance.
    await _record_transaction(
        tenant_id=tenant_id, delta=upd["ai_credits_balance"],
        reason="initial_grant", feature="other", ref_id=None,
        ref_type="init", balance_after=upd["ai_credits_balance"],
        created_by=None,
    )
    t.update(upd)
    return t


async def _record_transaction(*, tenant_id: str, delta: int, reason: str,
                                feature: str, ref_id: Optional[str],
                                ref_type: Optional[str],
                                balance_after: int,
                                created_by: Optional[str]) -> Dict[str, Any]:
    doc = {
        "id": new_id(),
        "tenant_id": tenant_id,
        "delta": int(delta),
        "reason": reason,
        "feature": feature if feature in ALLOWED_FEATURES else "other",
        "ref_id": ref_id,
        "ref_type": ref_type,
        "balance_after": int(balance_after),
        "created_by": created_by,
        "created_at": now_iso(),
    }
    await db.ai_credit_transactions.insert_one(doc)
    return doc


async def debit_credits(tenant_id: str, amount: int, *,
                         feature: str = "other",
                         ref_id: Optional[str] = None,
                         ref_type: Optional[str] = None,
                         reason: str = "debit",
                         actor_user_id: Optional[str] = None) -> Dict[str, Any]:
    """SOFT enforcement — never blocks the caller.

    Returns:
        {ok: bool, balance_after: int, warning: bool, plan: str}
    """
    if amount < 0:
        raise ValueError("amount must be non-negative; use credit() for grants")
    t = await ensure_tenant_credits_initialized(tenant_id)
    balance = int(t.get("ai_credits_balance", 0)) - int(amount)
    grant = int(t.get("ai_credits_monthly_grant") or grant_for(t.get("ai_credits_plan")))
    await db.tenants.update_one(
        {"id": tenant_id},
        {"$set": {"ai_credits_balance": balance}},
    )
    await _record_transaction(
        tenant_id=tenant_id, delta=-int(amount), reason=reason,
        feature=feature, ref_id=ref_id, ref_type=ref_type,
        balance_after=balance, created_by=actor_user_id,
    )
    warning = balance < 0 or balance < int(grant * WARN_FRACTION)
    return {
        "ok": True,
        "balance_after": balance,
        "warning": bool(warning),
        "plan": t.get("ai_credits_plan") or DEFAULT_PLAN,
    }


async def credit_credits(tenant_id: str, amount: int, *,
                          reason: str = "topup",
                          feature: str = "other",
                          ref_id: Optional[str] = None,
                          ref_type: Optional[str] = None,
                          actor_user_id: Optional[str] = None) -> Dict[str, Any]:
    if amount < 0:
        raise ValueError("amount must be non-negative")
    t = await ensure_tenant_credits_initialized(tenant_id)
    balance = int(t.get("ai_credits_balance", 0)) + int(amount)
    await db.tenants.update_one(
        {"id": tenant_id},
        {"$set": {"ai_credits_balance": balance}},
    )
    await _record_transaction(
        tenant_id=tenant_id, delta=int(amount), reason=reason,
        feature=feature, ref_id=ref_id, ref_type=ref_type,
        balance_after=balance, created_by=actor_user_id,
    )
    return {"ok": True, "balance_after": balance}


async def reset_tenant_monthly(tenant_id: str) -> Dict[str, Any]:
    """Reset a single tenant's balance to its monthly grant. Unused
    credits do NOT carry over. Called by the monthly scheduler job."""
    t = await ensure_tenant_credits_initialized(tenant_id)
    plan = t.get("ai_credits_plan") or DEFAULT_PLAN
    grant = int(t.get("ai_credits_monthly_grant") or grant_for(plan))
    now = now_iso()
    await db.tenants.update_one(
        {"id": tenant_id},
        {"$set": {"ai_credits_balance": grant,
                  "ai_credits_last_reset_at": now}},
    )
    delta = grant - int(t.get("ai_credits_balance", 0))
    await _record_transaction(
        tenant_id=tenant_id, delta=delta, reason="monthly_reset",
        feature="other", ref_id=None, ref_type="reset",
        balance_after=grant, created_by=None,
    )
    return {"tenant_id": tenant_id, "balance_after": grant,
            "plan": plan, "reset_at": now}


async def run_monthly_reset_all() -> Dict[str, Any]:
    """APScheduler job — first day of month at 00:05 UTC.
    Runs once per tenant. Never raises out of the tenant loop."""
    processed = 0
    errors = 0
    async for t in db.tenants.find(
            {"active": {"$ne": False}}, {"_id": 0, "id": 1}):
        try:
            await reset_tenant_monthly(t["id"])
            processed += 1
        except Exception as e:
            errors += 1
            logger.warning(f"[ai_credits] reset failed for {t['id']}: {e}")
    logger.info(f"[ai_credits] monthly reset processed={processed} errors={errors}")
    return {"processed": processed, "errors": errors,
            "ran_at": now_iso()}
