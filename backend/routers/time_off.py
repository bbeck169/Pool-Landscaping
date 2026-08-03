"""
Phase 40 (Feb-2026) — Time-off requests, policy, and balance API.
"""
from __future__ import annotations

from datetime import datetime, timezone, date, timedelta
from typing import Optional, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from config import db, logger
from utils import now_iso, new_id, get_current_user, require_admin
from routers.tenants import get_current_tenant
from services.time_off_accrual import (
    compute_balance, get_policy, DEFAULT_POLICY, waiting_period_remaining_days,
)

router = APIRouter(prefix="/time-off", tags=["time-off"])

TYPES = ("sick", "vacation", "personal", "unpaid")
STATUSES = ("pending", "approved", "rejected", "cancelled")


# ── Pydantic models ────────────────────────────────────────────────

class PolicyBody(BaseModel):
    accrual_numerator: int = Field(default=1, ge=1, le=100)
    accrual_denominator: int = Field(default=30, ge=1, le=1000)
    annual_cap_hours: float = Field(default=24, ge=0, le=1000)
    waiting_period_days: int = Field(default=90, ge=0, le=365)
    active: bool = True


class RequestBody(BaseModel):
    type: Literal["sick", "vacation", "personal", "unpaid"]
    from_date: str  # ISO date YYYY-MM-DD
    to_date: str
    hours: float = Field(ge=0.25, le=1000)
    reason: str = Field(default="", max_length=500)


class DecideBody(BaseModel):
    decision_notes: str = Field(default="", max_length=500)


# ── Policy endpoints ───────────────────────────────────────────────

@router.get("/policy")
async def read_policy(user: dict = Depends(get_current_user),
                      tenant: dict = Depends(get_current_tenant)):
    policy = await get_policy(db, tenant["id"])
    # Tech-role sanitisation — hide audit fields.
    if user.get("role") not in ("admin", "super_admin"):
        policy = {k: v for k, v in policy.items() if k not in ("updated_at", "updated_by", "id")}
    return policy


@router.put("/policy")
async def upsert_policy(body: PolicyBody,
                        admin: dict = Depends(require_admin),
                        tenant: dict = Depends(get_current_tenant)):
    existing = await db.time_off_policies.find_one({"tenant_id": tenant["id"]})
    doc = {
        "tenant_id": tenant["id"],
        "accrual_numerator": body.accrual_numerator,
        "accrual_denominator": body.accrual_denominator,
        "annual_cap_hours": body.annual_cap_hours,
        "waiting_period_days": body.waiting_period_days,
        "active": body.active,
        "updated_at": now_iso(),
        "updated_by": admin["id"],
    }
    if existing:
        await db.time_off_policies.update_one(
            {"tenant_id": tenant["id"]}, {"$set": doc}
        )
    else:
        doc["id"] = new_id()
        await db.time_off_policies.insert_one(doc)
    return await get_policy(db, tenant["id"])


# ── Balance ────────────────────────────────────────────────────────

@router.get("/balance/me")
async def my_balance(user: dict = Depends(get_current_user),
                     tenant: dict = Depends(get_current_tenant)):
    return await compute_balance(db, tenant["id"], user)


@router.get("/balance/{user_id}")
async def other_balance(user_id: str,
                        admin: dict = Depends(require_admin),
                        tenant: dict = Depends(get_current_tenant)):
    target = await db.users.find_one({"id": user_id, "tenant_id": tenant["id"]})
    if not target:
        raise HTTPException(status_code=404, detail="user_not_found")
    return await compute_balance(db, tenant["id"], target)


@router.get("/balances/all")
async def all_balances(admin: dict = Depends(require_admin),
                       tenant: dict = Depends(get_current_tenant)):
    """Admin view — one balance snapshot per active tech-like user,
    enriched with ``user_name`` + ``avatar_url`` so the UI can render
    the table without a follow-up ``/api/users`` fan-out."""
    out: list[dict] = []
    async for u in db.users.find({
        "tenant_id": tenant["id"],
        "role": {"$in": ["technician", "landscaper", "tech", "admin", "manager"]},
    }):
        bal = await compute_balance(db, tenant["id"], u)
        bal["user_name"] = u.get("name") or u.get("email") or "—"
        bal["avatar_url"] = u.get("avatar_url") or u.get("photo_url")
        bal["role"] = u.get("role")
        bal["hire_date"] = (
            u.get("hire_date").isoformat() if isinstance(u.get("hire_date"), datetime)
            else u.get("hire_date")
        )
        out.append(bal)
    out.sort(key=lambda b: (b.get("user_name") or "").lower())
    return out


# ── Requests ───────────────────────────────────────────────────────

def _proj(r: dict) -> dict:
    r.pop("_id", None)
    return r


@router.get("/requests")
async def list_requests(
    scope: Literal["me", "all"] = "me",
    status: Optional[str] = Query(default=None),
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    q: dict = {"tenant_id": tenant["id"]}
    if scope == "me":
        q["user_id"] = user["id"]
    else:
        if user.get("role") not in ("admin", "super_admin"):
            raise HTTPException(status_code=403, detail="admin_only")
    if status:
        if status not in STATUSES:
            raise HTTPException(status_code=400, detail="invalid_status")
        q["status"] = status
    docs = await db.time_off_requests.find(q).sort("created_at", -1).to_list(500)
    return [_proj(d) for d in docs]


@router.post("/requests")
async def submit_request(body: RequestBody,
                         user: dict = Depends(get_current_user),
                         tenant: dict = Depends(get_current_tenant)):
    # Date sanity
    try:
        f = date.fromisoformat(body.from_date)
        t = date.fromisoformat(body.to_date)
    except ValueError:
        raise HTTPException(status_code=400, detail={"code": "bad_date"})
    if f > t:
        raise HTTPException(status_code=400, detail={"code": "date_range"})

    # Waiting period check (only for balance-drawing types)
    policy = await get_policy(db, tenant["id"])
    remaining = waiting_period_remaining_days(user, policy)
    if body.type in ("sick", "vacation", "personal") and remaining > 0:
        raise HTTPException(
            status_code=400,
            detail={"code": "waiting_period", "remaining_days": remaining},
        )

    # Balance check (only for balance-drawing types)
    if body.type in ("sick", "vacation", "personal"):
        balance = await compute_balance(db, tenant["id"], user)
        if body.hours > balance["available_hours"]:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "insufficient_balance",
                    "available": balance["available_hours"],
                    "requested": body.hours,
                },
            )

    doc = {
        "id": new_id(),
        "tenant_id": tenant["id"],
        "user_id": user["id"],
        "type": body.type,
        "from_date": body.from_date,
        "to_date": body.to_date,
        "hours": body.hours,
        "reason": body.reason,
        "status": "pending",
        "approver_id": None,
        "decided_at": None,
        "decision_notes": "",
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    await db.time_off_requests.insert_one(doc)
    return _proj(doc)


async def _find_req(request_id: str, tenant_id: str) -> dict:
    r = await db.time_off_requests.find_one({"id": request_id, "tenant_id": tenant_id})
    if not r:
        raise HTTPException(status_code=404, detail="request_not_found")
    return r


@router.post("/requests/{request_id}/approve")
async def approve_request(request_id: str, body: DecideBody,
                          admin: dict = Depends(require_admin),
                          tenant: dict = Depends(get_current_tenant)):
    r = await _find_req(request_id, tenant["id"])
    if r["status"] != "pending":
        raise HTTPException(status_code=409, detail={"code": "not_pending"})

    # Re-check balance atomically at approval time.
    if r["type"] in ("sick", "vacation", "personal"):
        target = await db.users.find_one({"id": r["user_id"], "tenant_id": tenant["id"]})
        if not target:
            raise HTTPException(status_code=404, detail="user_not_found")
        balance = await compute_balance(db, tenant["id"], target)
        if float(r["hours"]) > balance["available_hours"]:
            raise HTTPException(status_code=400, detail={"code": "insufficient_balance_at_approval"})

    await db.time_off_requests.update_one(
        {"id": request_id, "tenant_id": tenant["id"], "status": "pending"},
        {"$set": {
            "status": "approved",
            "approver_id": admin["id"],
            "decided_at": now_iso(),
            "decision_notes": body.decision_notes,
            "updated_at": now_iso(),
        }},
    )
    return _proj(await _find_req(request_id, tenant["id"]))


@router.post("/requests/{request_id}/reject")
async def reject_request(request_id: str, body: DecideBody,
                         admin: dict = Depends(require_admin),
                         tenant: dict = Depends(get_current_tenant)):
    r = await _find_req(request_id, tenant["id"])
    if r["status"] != "pending":
        raise HTTPException(status_code=409, detail={"code": "not_pending"})
    await db.time_off_requests.update_one(
        {"id": request_id, "tenant_id": tenant["id"], "status": "pending"},
        {"$set": {
            "status": "rejected",
            "approver_id": admin["id"],
            "decided_at": now_iso(),
            "decision_notes": body.decision_notes,
            "updated_at": now_iso(),
        }},
    )
    return _proj(await _find_req(request_id, tenant["id"]))


@router.post("/requests/{request_id}/cancel")
async def cancel_request(request_id: str,
                         user: dict = Depends(get_current_user),
                         tenant: dict = Depends(get_current_tenant)):
    r = await _find_req(request_id, tenant["id"])
    # Only the submitter can cancel; admins can cancel-anyone via approve/reject path.
    if r["user_id"] != user["id"]:
        raise HTTPException(status_code=403, detail={"code": "not_owner"})
    if r["status"] not in ("pending", "approved"):
        raise HTTPException(status_code=409, detail={"code": "not_cancellable"})

    upd = {
        "status": "cancelled",
        "updated_at": now_iso(),
    }
    if r["status"] == "approved":
        upd["cancelled_after_approval"] = True  # audit breadcrumb; balance auto-recomputes
    await db.time_off_requests.update_one(
        {"id": request_id, "tenant_id": tenant["id"]},
        {"$set": upd},
    )
    return _proj(await _find_req(request_id, tenant["id"]))
