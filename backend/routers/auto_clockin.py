"""Feb-2026 · Web/backend gaps flagged by the mobile agent.

Adds these surfaces:

* ``PATCH /api/users/me`` — self-update for the authenticated user.
  Currently accepts a single field, ``auto_clockin_enabled: bool``,
  so the mobile Clock-In screen can toggle the tech's own preference
  without needing an admin.
* ``GET  /api/admin/orphan-customer-users`` — super_admin listing of
  every ``role=customer`` auth user whose ``customer_id`` is missing
  or points at a non-existent customer record. Pairs with the repair
  endpoint below.
* ``POST /api/admin/users/{uid}/create-customer-record`` — super_admin
  repair for orphan customer auth users. Idempotent: returns the
  existing linkage when everything is already in shape.
* ``POST /api/portal/complete-profile`` — customer self-serve repair
  for their own orphaned auth user. Idempotent: a second call is a
  no-op returning the existing linked customer record.
* ``run_auto_clockin_backfill()`` — idempotent boot migration that
  stamps ``auto_clockin_enabled=True`` on every existing technician
  user missing the field, ``False`` on every non-technician user
  missing the field. Runs from ``server._background_seed``.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

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


@router.get("/admin/orphan-customer-users",
             operation_id="admin.listOrphanCustomerUsers")
async def list_orphan_customer_users(
    actor: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """Return every ``role=customer`` auth user in the actor's tenant
    (or the whole database when the caller is super_admin) whose
    ``customer_id`` is missing OR points at a customer record that
    does not exist. Super-admin only.

    Response shape:
        ``{"users": [ {id, tenant_id, name, email, phone, created_at,
                       customer_id, reason} ]}``
    where ``reason`` is one of ``"missing_customer_id"`` |
    ``"stale_customer_id"`` so the UI can label rows.
    """
    if actor.get("role") != "super_admin":
        raise HTTPException(403, "Super-admin only")

    # Pull every role=customer user (scoped to tenant for regular admins;
    # super_admin sees all tenants so cross-tenant orphans surface).
    q: Dict[str, Any] = {"role": "customer"}
    users = await db.users.find(
        q, {"_id": 0, "password_hash": 0},
    ).to_list(length=5000)

    if not users:
        return {"users": []}

    # Collect the referenced customer_ids and figure out which exist in
    # ONE round-trip per tenant.  We split by tenant_id so the customer
    # lookup respects tenant scoping (customers of tenant A cannot
    # satisfy the link for a user in tenant B).
    by_tenant: Dict[str, List[str]] = {}
    for u in users:
        cid = u.get("customer_id")
        if not cid:
            continue
        by_tenant.setdefault(u.get("tenant_id") or "", []).append(cid)

    found: Dict[tuple, bool] = {}
    for tid, cids in by_tenant.items():
        cur = db.customers.find(
            {"tenant_id": tid, "id": {"$in": cids}},
            {"_id": 0, "id": 1},
        )
        async for row in cur:
            found[(tid, row["id"])] = True

    orphans: List[Dict[str, Any]] = []
    for u in users:
        cid = u.get("customer_id")
        tid = u.get("tenant_id") or ""
        if not cid:
            reason = "missing_customer_id"
        elif not found.get((tid, cid)):
            reason = "stale_customer_id"
        else:
            continue
        orphans.append({
            "id": u.get("id"),
            "tenant_id": tid,
            "name": u.get("name") or "",
            "email": u.get("email") or "",
            "phone": u.get("phone") or "",
            "created_at": u.get("created_at") or "",
            "customer_id": cid or None,
            "reason": reason,
        })
    # Newest first so freshly-created orphans surface at the top.
    orphans.sort(key=lambda x: x.get("created_at") or "", reverse=True)
    return {"users": orphans}


class CompleteProfileBody(BaseModel):
    first_name: Optional[str] = ""
    last_name: Optional[str] = ""
    phone: Optional[str] = ""
    service_address: Optional[str] = ""
    preferred_contact: Optional[str] = "email"  # email | sms | phone


@router.post("/portal/complete-profile",
              operation_id="portal.completeProfile")
async def portal_complete_profile(
    body: CompleteProfileBody,
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """Customer self-serve repair for their own orphaned auth account.

    Creates the missing linked customer document from the auth user's
    fields + the submitted form values, then clears the orphan flag by
    setting ``users.customer_id`` on the auth user. Idempotent — a
    second call short-circuits with ``was_already_linked=True`` and
    returns the existing ``customer_id``.

    Only customers can hit this endpoint (any other role → 403).
    """
    if user.get("role") != "customer":
        raise HTTPException(403, "Customers only")

    # Idempotent short-circuit — if the link is already valid, no-op.
    existing_cid = user.get("customer_id")
    if existing_cid:
        cust = await db.customers.find_one(
            {"id": existing_cid, "tenant_id": user.get("tenant_id")},
            {"_id": 0},
        )
        if cust:
            return {"ok": True, "was_already_linked": True,
                    "customer_id": existing_cid,
                    "customer_record_missing": False}

    first = (body.first_name or "").strip()
    last = (body.last_name or "").strip()
    # Compose display name — fall back to the auth-user's name / email
    # local-part so we NEVER end up with an empty customer name.
    composed = (f"{first} {last}").strip()
    display_name = composed or (user.get("name")
                                 or (user.get("email") or "").split("@")[0])

    pref = (body.preferred_contact or "email").lower().strip()
    if pref not in {"email", "sms", "phone"}:
        pref = "email"

    new_cid = new_id()
    doc = {
        "id": new_cid,
        "tenant_id": user.get("tenant_id"),
        "name": display_name,
        "first_name": first,
        "last_name": last,
        "email": user.get("email"),
        "phone": (body.phone or user.get("phone") or "").strip(),
        "address": (body.service_address or "").strip(),
        "preferred_contact": pref,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "is_active": True,
        "created_via": "customer_self_serve",
        "linked_user_id": user["id"],
    }
    await db.customers.insert_one(doc)
    await db.users.update_one(
        {"id": user["id"]},
        {"$set": {"customer_id": new_cid,
                   "phone": doc["phone"] or user.get("phone", ""),
                   "updated_at": now_iso()}},
    )
    logger.info("[portal-complete-profile] created customer %s for user %s (%s)",
                new_cid, user["id"], user.get("email"))
    return {"ok": True, "was_already_linked": False,
            "customer_id": new_cid,
            "customer_record_missing": False}


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
