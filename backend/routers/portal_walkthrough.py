"""Feb-2026 · Slice I — Customer portal first-login walkthrough.

Two tiny read/write endpoints + one idempotent backfill (existing
customers get a ``grandfathered`` sentinel so we don't spam them on
first re-login).
"""
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException

from config import db, logger
from utils import get_current_user, now_iso

router = APIRouter(prefix="/customer-portal", tags=["Portal Walkthrough"])


def _require_customer(user: Dict[str, Any]) -> str:
    """Portal endpoints only make sense for a signed-in customer.
    Returns the ``customer_id`` claim; 403 otherwise."""
    if user.get("role") != "customer":
        raise HTTPException(403, "Customer login required")
    cid = user.get("customer_id")
    if not cid:
        raise HTTPException(400, "Signed-in user has no linked customer record")
    return cid


@router.get("/walkthrough/status")
async def get_walkthrough_status(user: Dict[str, Any] = Depends(get_current_user)):
    cid = _require_customer(user)
    tid = user["tenant_id"]
    row = await db.customers.find_one(
        {"id": cid, "tenant_id": tid},
        {"_id": 0, "portal_walkthrough_completed_at": 1},
    ) or {}
    completed_at = row.get("portal_walkthrough_completed_at")
    is_completed = bool(completed_at)
    return {
        "completed": is_completed,
        # Slice L.j · alias — some frontend surfaces (older builds)
        # reference ``has_completed``. Emit both so both keep working.
        "has_completed": is_completed,
        "completed_at": completed_at,
        "should_show": not is_completed,
    }


@router.post("/walkthrough/complete")
async def mark_walkthrough_complete(
    user: Dict[str, Any] = Depends(get_current_user),
):
    """Called by the frontend when the visitor finishes OR skips the
    tour. Both surfaces close it out — replaying it later doesn't
    clear the flag."""
    cid = _require_customer(user)
    tid = user["tenant_id"]
    ts = now_iso()
    await db.customers.update_one(
        {"id": cid, "tenant_id": tid},
        {"$set": {"portal_walkthrough_completed_at": ts,
                    "updated_at": ts}},
    )
    return {"ok": True, "completed_at": ts}


async def run_walkthrough_backfill() -> Dict[str, int]:
    """One-shot idempotent backfill: any existing customer without a
    ``portal_walkthrough_completed_at`` gets the ``grandfathered``
    sentinel so they don't get spammed with the tour on their next
    login. New customers created AFTER this backfill still trigger
    the walkthrough because the field is absent on their doc."""
    res = await db.customers.update_many(
        {"portal_walkthrough_completed_at": {"$exists": False},
         "created_at": {"$lt": now_iso()}},
        {"$set": {"portal_walkthrough_completed_at": "grandfathered"}},
    )
    n = int(getattr(res, "modified_count", 0) or 0)
    if n:
        logger.info(f"[slice-i] grandfathered walkthrough on {n} customer(s)")
    return {"grandfathered": n}
