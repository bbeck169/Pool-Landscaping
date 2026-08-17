"""Feb-2026 · Comms whitelist admin routes (P0 safety directive).

Two super_admin-only endpoints:
  - ``GET /comms/suppression-log`` — paginated read of the
    ``comms_suppression_log`` collection (rows written when the
    ``is_comm_allowed`` gate blocked an outbound comm)
  - ``PATCH /comms/demo-flag`` — toggle ``is_demo_account`` on a
    specific ``users`` or ``customers`` row. Audit-logged.

Deliberately narrow — no bulk toggle. A single toggle per request
keeps the surface area low + matches the "explicit opt-in per
record" spirit of the P0 dispatch.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from config import db
from utils import get_current_user

logger = logging.getLogger("comms.admin_routes")

router = APIRouter(prefix="/comms", tags=["Comms Whitelist"])


def _require_super(user: Dict[str, Any]) -> None:
    if (user or {}).get("role") != "super_admin":
        raise HTTPException(403, "super_admin_only")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Suppression log listing ─────────────────────────────────────────
@router.get("/suppression-log",
             operation_id="comms.suppression_log.list")
async def list_suppression_log(
    user: Dict[str, Any] = Depends(get_current_user),
    limit: int = Query(100, ge=1, le=500),
    skip: int = Query(0, ge=0),
    comm_type: Optional[str] = Query(None),
    recipient_type: Optional[str] = Query(None),
    provider: Optional[str] = Query(None),
    recipient_id: Optional[str] = Query(None),
):
    _require_super(user)
    q: Dict[str, Any] = {"tenant_id": user.get("tenant_id")}
    if comm_type:
        q["comm_type"] = comm_type
    if recipient_type:
        q["recipient_type"] = recipient_type
    if provider:
        q["provider"] = provider
    if recipient_id:
        q["recipient_id"] = recipient_id
    total = await db.comms_suppression_log.count_documents(q)
    rows = await db.comms_suppression_log.find(
        q, {"_id": 0},
    ).sort("created_at", -1).skip(skip).limit(limit).to_list(limit)
    return {"total": total, "limit": limit, "skip": skip, "rows": rows}


# ── Demo-account flag toggle (single record) ────────────────────────
class DemoFlagIn(BaseModel):
    record_type: str  # "user" or "customer"
    record_id: str
    is_demo_account: bool


_TOGGLE_ROLES = {"super_admin", "admin", "manager"}


@router.patch("/demo-flag",
               operation_id="comms.demo_flag.set")
async def set_demo_flag(body: DemoFlagIn,
                          user: Dict[str, Any] = Depends(get_current_user)):
    role = (user or {}).get("role")
    if role not in _TOGGLE_ROLES:
        raise HTTPException(403, "demo_flag_requires_admin_or_manager")
    if body.record_type == "user":
        coll = db.users
    elif body.record_type == "customer":
        coll = db.customers
    else:
        raise HTTPException(
            400, "record_type must be 'user' or 'customer'")

    tenant_id = user.get("tenant_id")
    q = {"id": body.record_id, "tenant_id": tenant_id}
    now = _now_iso()
    r = await coll.update_one(
        q, {"$set": {"is_demo_account": bool(body.is_demo_account),
                       "is_demo_account_updated_at": now,
                       "is_demo_account_updated_by": user.get("id")}},
    )
    if r.matched_count == 0:
        raise HTTPException(404, "record_not_found_in_tenant")

    # Audit — a bulk-status-change style single entry per toggle.
    try:
        from models import new_id  # type: ignore
        await db.audit_logs.insert_one({
            "id": new_id(),
            "tenant_id": tenant_id,
            "event": "comms.demo_flag_change",
            "record_type": body.record_type,
            "record_id": body.record_id,
            "is_demo_account": bool(body.is_demo_account),
            "actor_id": user.get("id"),
            "actor_email": user.get("email"),
            "actor_role": role,
            "created_at": now,
        })
    except Exception as exc:  # noqa: BLE001
        logger.warning("[comms.demo_flag] audit insert failed: %s", exc)

    return {"ok": True, "matched": r.matched_count,
              "modified": r.modified_count}


# ── Health / meta banner support ────────────────────────────────────
@router.get("/whitelist/status",
             operation_id="comms.whitelist.status")
async def whitelist_status(
    user: Dict[str, Any] = Depends(get_current_user),
):
    """Small meta endpoint for the Settings → Notifications banner.
    Tells the FE that comms are demo-only + how many suppression
    rows have accumulated + how many records are flagged demo.
    """
    tenant_id = user.get("tenant_id")
    q = {"tenant_id": tenant_id}
    users_demo = await db.users.count_documents(
        {**q, "is_demo_account": True})
    cust_demo = await db.customers.count_documents(
        {**q, "is_demo_account": True})
    suppress_24h_ago = datetime.now(timezone.utc)
    from datetime import timedelta
    suppress_24h_ago -= timedelta(days=1)
    suppressed_24h = await db.comms_suppression_log.count_documents(
        {**q, "created_at": {"$gte": suppress_24h_ago}},
    )
    return {
        "whitelist_active": True,
        "users_flagged_demo": int(users_demo),
        "customers_flagged_demo": int(cust_demo),
        "suppressed_last_24h": int(suppressed_24h),
    }
