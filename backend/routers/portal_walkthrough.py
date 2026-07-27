"""Feb-2026 · Slice I + Item 7 — Customer portal first-login tour.

Two-flag system:
* ``customers.portal_walkthrough_completed_at`` — legacy per-customer
  flag (Slice I). Preserved for backwards compat.
* ``users.has_seen_customer_tour`` (bool) + ``customer_tour_seen_at``
  (iso ts) — Item 7 per-user flag. Authoritative going forward.

An admin reset endpoint flips ``has_seen_customer_tour=false`` on a
target user so support can replay the tour for anyone.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException

from config import db, logger
from utils import get_current_user, now_iso

router = APIRouter(tags=["Portal Walkthrough"])


def _require_customer(user: Dict[str, Any]) -> str:
    if user.get("role") != "customer":
        raise HTTPException(403, "Customer login required")
    cid = user.get("customer_id")
    if not cid:
        raise HTTPException(400, "Signed-in user has no linked customer record")
    return cid


def _require_admin(user: Dict[str, Any]) -> None:
    if user.get("role") not in {"admin", "super_admin"}:
        raise HTTPException(403, "Admin only")


async def _user_seen(user_id: str) -> bool:
    """Cheap lookup of the user-level flag."""
    if not user_id:
        return False
    u = await db.users.find_one(
        {"id": user_id}, {"_id": 0, "has_seen_customer_tour": 1},
    ) or {}
    return bool(u.get("has_seen_customer_tour"))


# ── Legacy (Slice I) status/complete — preserved ────────────────────
@router.get("/customer-portal/walkthrough/status")
async def get_walkthrough_status(user: Dict[str, Any] = Depends(get_current_user)):
    cid = _require_customer(user)
    tid = user["tenant_id"]
    row = await db.customers.find_one(
        {"id": cid, "tenant_id": tid},
        {"_id": 0, "portal_walkthrough_completed_at": 1},
    ) or {}
    completed_at = row.get("portal_walkthrough_completed_at")
    # Item 7 · user-level flag wins if either source says "seen".
    user_seen = await _user_seen(user.get("id") or "")
    is_completed = bool(completed_at) or user_seen
    # Phase 34 · Task V — v2 flag. When we bumped the tour step list
    # to include Task-K/R/34 anchors we need v1-completers to see the
    # extended flow once. The v2 flag lives in a NEW field so v1
    # cohort discovery is trivial (v1 flag true + v2 flag false or
    # missing = show once).
    u2 = await db.users.find_one(
        {"id": user.get("id") or ""},
        {"_id": 0, "portal_tour_completed_v2": 1},
    ) or {}
    v2_completed = bool(u2.get("portal_tour_completed_v2"))
    return {
        "completed": is_completed,
        "has_completed": is_completed,
        "completed_at": completed_at,
        "should_show": not is_completed,
        # v2 keys — new consumers should read these.
        "portal_tour_completed_v2": v2_completed,
        "should_show_v2": not v2_completed,
        "version": 2,
    }


@router.post("/customer-portal/walkthrough/complete")
async def mark_walkthrough_complete(
    user: Dict[str, Any] = Depends(get_current_user),
):
    cid = _require_customer(user)
    tid = user["tenant_id"]
    ts = now_iso()
    await db.customers.update_one(
        {"id": cid, "tenant_id": tid},
        {"$set": {"portal_walkthrough_completed_at": ts, "updated_at": ts}},
    )
    # Item 7 · mirror onto the user doc so the flag is authoritative
    # even when a customer has multiple login accounts.
    if user.get("id"):
        await db.users.update_one(
            {"id": user["id"]},
            {"$set": {
                "has_seen_customer_tour": True,
                "customer_tour_seen_at": ts,
                # Phase 34 · Task V — completing the tour NOW counts
                # as completing v2 (since the step list is v2).
                "portal_tour_completed_v2": True,
                "portal_tour_completed_v2_at": ts,
            }},
        )
    return {"ok": True, "completed_at": ts}


# ── Item 7 · user-level endpoints ───────────────────────────────────
@router.post("/users/me/mark-tour-seen")
async def mark_tour_seen(user: Dict[str, Any] = Depends(get_current_user)):
    """Customer-only. Flips the per-user ``has_seen_customer_tour``
    flag. Called when the customer completes OR dismisses the tour."""
    if user.get("role") != "customer":
        raise HTTPException(403, "Customer login required")
    if not user.get("id"):
        raise HTTPException(400, "User has no id")
    ts = now_iso()
    await db.users.update_one(
        {"id": user["id"]},
        {"$set": {"has_seen_customer_tour": True,
                    "customer_tour_seen_at": ts}},
    )
    # Also mark the legacy per-customer flag so status endpoints agree.
    cid = user.get("customer_id")
    if cid:
        await db.customers.update_one(
            {"id": cid, "tenant_id": user.get("tenant_id")},
            {"$set": {"portal_walkthrough_completed_at": ts,
                        "updated_at": ts}},
        )
    return {"ok": True, "has_seen_customer_tour": True,
             "customer_tour_seen_at": ts}


@router.post("/users/{uid}/reset-tour")
async def reset_tour_for_user(
    uid: str,
    user: Dict[str, Any] = Depends(get_current_user),
):
    """Admin/super_admin only. Flips ``has_seen_customer_tour=false``
    on the target user so the tour replays next login. Also clears
    ``portal_walkthrough_completed_at`` on the linked customer doc
    so both flags agree."""
    _require_admin(user)
    target = await db.users.find_one({"id": uid}, {"_id": 0}) or {}
    if not target:
        raise HTTPException(404, "User not found")
    # Regular admins can only reset tours for their own tenant. Super
    # admins can reset across tenants.
    if user.get("role") == "admin":
        if target.get("tenant_id") != user.get("tenant_id"):
            raise HTTPException(403, "Cross-tenant reset requires super_admin")
    await db.users.update_one(
        {"id": uid},
        {"$set": {"has_seen_customer_tour": False},
         "$unset": {"customer_tour_seen_at": ""}},
    )
    if target.get("customer_id"):
        await db.customers.update_one(
            {"id": target["customer_id"]},
            {"$unset": {"portal_walkthrough_completed_at": ""}},
        )
    return {"ok": True, "user_id": uid, "has_seen_customer_tour": False}


# ── Backfills ──────────────────────────────────────────────────────
async def run_walkthrough_backfill() -> Dict[str, int]:
    """One-shot idempotent backfill.

    * Slice I · legacy — grandfather existing customer docs so the
      tour doesn't fire for pre-existing accounts.
    * Item 7 · user-level — set ``has_seen_customer_tour=true`` on
      every existing customer-role user so returning customers who
      already know the app don't get a tour on next login. New
      customers created after boot keep the default ``false`` (no
      backfill for docs created after ``now``).
    * Phase 34 · Task V · v2 backfill — every existing customer user
      gets ``portal_tour_completed_v2=false`` so v1-completers see
      the extended tour once. Idempotent: only writes the field when
      it's missing.
    """
    ts_now = now_iso()
    res_customers = await db.customers.update_many(
        {"portal_walkthrough_completed_at": {"$exists": False},
         "created_at": {"$lt": ts_now}},
        {"$set": {"portal_walkthrough_completed_at": "grandfathered"}},
    )
    n_cust = int(getattr(res_customers, "modified_count", 0) or 0)

    res_users = await db.users.update_many(
        {"role": "customer",
         "has_seen_customer_tour": {"$ne": True}},
        {"$set": {"has_seen_customer_tour": True,
                    "customer_tour_seen_at": "grandfathered"}},
    )
    n_users = int(getattr(res_users, "modified_count", 0) or 0)

    # v2 backfill — write ``false`` where the field is missing so the
    # v2 flow can prompt each existing customer user once.
    res_v2 = await db.users.update_many(
        {"role": "customer",
         "portal_tour_completed_v2": {"$exists": False}},
        {"$set": {"portal_tour_completed_v2": False}},
    )
    n_v2 = int(getattr(res_v2, "modified_count", 0) or 0)

    if n_cust or n_users or n_v2:
        logger.info(
            "[tour-backfill] customers=%s users=%s v2=%s",
            n_cust, n_users, n_v2,
        )
    return {
        "grandfathered": n_cust,
        "grandfathered_users": n_users,
        "v2_flagged_users": n_v2,
    }
