"""QuoteIQ Phase Q1 · Sub-scope A — AI credits admin endpoints."""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from config import db
from utils import get_current_user, require_admin, require_super_admin
from routers.tenants import get_current_tenant
from services.ai_credits import (
    ensure_tenant_credits_initialized, credit_credits, grant_for,
    PLAN_GRANTS, DEFAULT_PLAN, WARN_FRACTION,
)


router = APIRouter(tags=["AI Credits"])


class TopupIn(BaseModel):
    amount: int = Field(..., ge=1, le=1_000_000)
    note: Optional[str] = ""


class PlanIn(BaseModel):
    plan: str = Field(...)


@router.get("/ai-credits/balance")
async def get_balance(user: dict = Depends(require_admin),
                       tenant: dict = Depends(get_current_tenant)):
    t = await ensure_tenant_credits_initialized(tenant["id"])
    balance = int(t.get("ai_credits_balance", 0))
    plan = t.get("ai_credits_plan") or DEFAULT_PLAN
    grant = int(t.get("ai_credits_monthly_grant") or grant_for(plan))
    return {
        "tenant_id": tenant["id"],
        "balance": balance,
        "plan": plan,
        "monthly_grant": grant,
        "last_reset_at": t.get("ai_credits_last_reset_at"),
        "warning": balance < 0 or balance < int(grant * WARN_FRACTION),
        "available_plans": PLAN_GRANTS,
    }


@router.get("/ai-credits/transactions")
async def list_transactions(user: dict = Depends(require_admin),
                              tenant: dict = Depends(get_current_tenant),
                              feature: Optional[str] = Query(None),
                              limit: int = Query(50, ge=1, le=500),
                              cursor: Optional[str] = Query(None)):
    q: Dict[str, Any] = {"tenant_id": tenant["id"]}
    if feature:
        q["feature"] = feature
    if cursor:
        q["created_at"] = {"$lt": cursor}
    rows = await db.ai_credit_transactions.find(q, {"_id": 0}) \
        .sort("created_at", -1).to_list(limit)
    next_cursor = rows[-1]["created_at"] if len(rows) == limit else None
    return {"count": len(rows), "transactions": rows,
            "next_cursor": next_cursor}


@router.post("/ai-credits/topup")
async def topup(body: TopupIn,
                  user: dict = Depends(require_super_admin),
                  tenant: dict = Depends(get_current_tenant)):
    r = await credit_credits(
        tenant["id"], body.amount, reason=body.note or "manual_topup",
        feature="other", ref_type="topup", actor_user_id=user["id"],
    )
    return {"ok": True, "balance_after": r["balance_after"]}


@router.patch("/ai-credits/plan")
async def set_plan(body: PlanIn,
                    user: dict = Depends(require_super_admin),
                    tenant: dict = Depends(get_current_tenant)):
    plan = (body.plan or "").lower().strip()
    if plan not in PLAN_GRANTS:
        raise HTTPException(422,
                              f"plan must be one of {sorted(PLAN_GRANTS.keys())}")
    grant = grant_for(plan)
    await db.tenants.update_one(
        {"id": tenant["id"]},
        {"$set": {"ai_credits_plan": plan,
                  "ai_credits_monthly_grant": grant}},
    )
    from services.ai_credits import _record_transaction
    # Log the plan change for audit.
    t = await db.tenants.find_one({"id": tenant["id"]}, {"_id": 0})
    await _record_transaction(
        tenant_id=tenant["id"], delta=0, reason=f"plan_change_to_{plan}",
        feature="other", ref_id=None, ref_type="plan_change",
        balance_after=int((t or {}).get("ai_credits_balance", 0)),
        created_by=user["id"],
    )
    return {"ok": True, "plan": plan, "monthly_grant": grant}
