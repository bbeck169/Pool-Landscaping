"""Feb-2026 · Web/backend gaps flagged by the mobile agent.

Adds three surfaces:

* ``PATCH /api/users/me`` — self-update for the authenticated user.
  Currently accepts a single field, ``auto_clockin_enabled: bool``,
  so the mobile Clock-In screen can toggle the tech's own preference
  without needing an admin.
* ``POST /api/admin/users/{uid}/create-customer-record`` — super_admin
  repair for orphan customer auth users (role=customer with no linked
  ``customer_id`` or a stale ``customer_id`` pointing at a missing
  record). Idempotent: returns the existing linkage when everything is
  already in shape.
* ``run_auto_clockin_backfill()`` — idempotent boot migration that
  stamps ``auto_clockin_enabled=True`` on every existing technician
  user missing the field, ``False`` on every non-technician user
  missing the field. Runs from ``server._background_seed``.
"""
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from config import db, logger
from utils import get_current_user, now_iso, new_id

router = APIRouter(tags=["Auto Clock-In / User self-service"])


class SelfPatchBody(BaseModel):
    auto_clockin_enabled: bool | None = None


@router.patch("/users/me", operation_id="users.selfPatch")
async def patch_self(body: SelfPatchBody,
                       user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    """Authenticated user updates their OWN preferences.

    Deliberately narrow — self-update MUST NOT let a user escalate
    their role or department. Only ``auto_clockin_enabled`` is
    accepted today; more fields can be added later behind the same
    guard.
    """
    updates: Dict[str, Any] = {}
    if body.auto_clockin_enabled is not None:
        updates["auto_clockin_enabled"] = bool(body.auto_clockin_enabled)
    if not updates:
        return {"ok": True, "no_op": True, "user": user}

    updates["updated_at"] = now_iso()
    await db.users.update_one({"id": user["id"]}, {"$set": updates})
    fresh = await db.users.find_one({"id": user["id"]},
                                      {"_id": 0, "password_hash": 0})
    return {"ok": True, "user": fresh}


@router.post("/admin/users/{uid}/create-customer-record",
              operation_id="admin.repairOrphanCustomer")
async def create_customer_record_for_orphan_user(
    uid: str,
    actor: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """Super-admin repair for orphan customer auth users.

    An orphan is a ``role=customer`` user whose ``customer_id`` is
    missing OR points at a customer record that doesn't exist in the
    tenant's ``customers`` collection. This endpoint creates a
    minimal customer record from the auth-user's fields and links
    them together. Idempotent — if the link already resolves to a
    real record, the endpoint short-circuits with ``was_already_linked``.
    """
    if actor.get("role") != "super_admin":
        raise HTTPException(403, "Super-admin only")

    target = await db.users.find_one({"id": uid}, {"_id": 0})
    if not target:
        raise HTTPException(404, "User not found")
    if target.get("role") != "customer":
        raise HTTPException(400, "Target user is not a customer role")

    existing = None
    if target.get("customer_id"):
        existing = await db.customers.find_one(
            {"id": target["customer_id"], "tenant_id": target.get("tenant_id")},
            {"_id": 0},
        )
    if existing:
        return {"ok": True, "was_already_linked": True,
                "customer_id": existing["id"]}

    new_cid = new_id()
    doc = {
        "id": new_cid,
        "tenant_id": target.get("tenant_id"),
        "name": target.get("name") or target.get("email", "").split("@")[0],
        "email": target.get("email"),
        "phone": target.get("phone") or "",
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "is_active": True,
        "created_via": "orphan_repair",
        "linked_user_id": uid,
    }
    await db.customers.insert_one(doc)
    await db.users.update_one({"id": uid}, {"$set": {"customer_id": new_cid,
                                                        "updated_at": now_iso()}})
    logger.info("[orphan-repair] created customer %s for user %s (%s)",
                new_cid, uid, target.get("email"))
    return {"ok": True, "was_already_linked": False, "customer_id": new_cid}


async def run_auto_clockin_backfill() -> Dict[str, int]:
    """Idempotent boot migration. Stamps ``auto_clockin_enabled`` on
    every existing user missing the field: True for role=technician,
    False for every other role. Re-runs are no-ops because the field
    is present on all touched docs after the first pass."""
    n_tech = await db.users.update_many(
        {"role": "technician", "auto_clockin_enabled": {"$exists": False}},
        {"$set": {"auto_clockin_enabled": True}},
    )
    n_other = await db.users.update_many(
        {"role": {"$ne": "technician"}, "auto_clockin_enabled": {"$exists": False}},
        {"$set": {"auto_clockin_enabled": False}},
    )
    n_tech_c = int(getattr(n_tech, "modified_count", 0) or 0)
    n_other_c = int(getattr(n_other, "modified_count", 0) or 0)
    if n_tech_c or n_other_c:
        logger.info(
            "[auto-clockin-backfill] tech_true=%s non_tech_false=%s",
            n_tech_c, n_other_c,
        )
    return {"tech_true": n_tech_c, "non_tech_false": n_other_c}
