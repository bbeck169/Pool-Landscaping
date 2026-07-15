from fastapi import APIRouter, HTTPException, Depends, Query
from typing import List, Optional
from datetime import datetime, timezone, timedelta

from config import db, logger, EMERGENT_LLM_KEY
from utils import (now_iso, new_id, hash_password, verify_password, create_token,
                   get_current_user, require_admin, send_sms, notify_customer, auth_response)
from routers.tenants import get_current_tenant
from models import *

router = APIRouter()


# ----------------------- Customers -----------------------
@router.get("/me")
async def get_my_profile(user: dict = Depends(get_current_user),
                         tenant: dict = Depends(get_current_tenant)):
    if user.get("role") != "customer" or not user.get("customer_id"):
        raise HTTPException(403, "Customers only")
    doc = await db.customers.find_one(
        {"id": user["customer_id"], "tenant_id": tenant["id"]}, {"_id": 0}
    )
    if not doc:
        raise HTTPException(404, "Profile not found")
    return doc


@router.put("/me")
async def update_my_profile(body: CustomerProfileUpdate,
                            user: dict = Depends(get_current_user),
                            tenant: dict = Depends(get_current_tenant)):
    if user.get("role") != "customer" or not user.get("customer_id"):
        raise HTTPException(403, "Customers only")
    update = {k: v for k, v in body.dict().items() if v is not None}
    if update:
        await db.customers.update_one(
            {"id": user["customer_id"], "tenant_id": tenant["id"]},
            {"$set": update},
        )
        # keep the login user's display name/avatar in sync
        user_patch = {k: update[k] for k in ("name", "avatar") if k in update}
        if user_patch:
            await db.users.update_one(
                {"id": user["id"], "tenant_id": tenant["id"]},
                {"$set": user_patch},
            )
    return await db.customers.find_one(
        {"id": user["customer_id"], "tenant_id": tenant["id"]}, {"_id": 0}
    )


@router.get("/customers")
async def list_customers(
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
    search: Optional[str] = None,
    tag: Optional[str] = None,
    waitlisted: Optional[bool] = None,
    unscheduled: Optional[bool] = None,
):
    # RBAC: only staff (admin/technician/super_admin) may list customer records. Customers use /me.
    if user.get("role") not in ("admin", "technician", "super_admin"):
        raise HTTPException(403, "Not allowed")
    q: dict = {"tenant_id": tenant["id"]}
    if search:
        rx = {"$regex": search, "$options": "i"}
        q["$or"] = [{"name": rx}, {"email": rx}, {"phone": rx}, {"address": rx}]
    if tag:
        q["tags"] = tag
    if waitlisted is not None:
        q["waitlisted"] = bool(waitlisted)
    docs = await db.customers.find(q, {"_id": 0}).sort("name", 1).to_list(2000)
    # If unscheduled=true, filter out customers who have any non-completed/cancelled job.
    if unscheduled:
        scheduled_ids = set(
            [d["customer_id"] async for d in db.jobs.find(
                {"tenant_id": tenant["id"], "status": {"$nin": ["completed", "cancelled"]}},
                {"customer_id": 1, "_id": 0},
            )]
        )
        docs = [d for d in docs if d["id"] not in scheduled_ids]
    return docs


@router.post("/customers/bulk")
async def customers_bulk(body: CustomerBulkAction,
                         user: dict = Depends(require_admin),
                         tenant: dict = Depends(get_current_tenant)):
    """Bulk-update or bulk-delete a selection of customers (tenant-scoped)."""
    if not body.ids:
        return {"ok": True, "updated": 0}
    q = {"id": {"$in": body.ids}, "tenant_id": tenant["id"]}
    if body.action == "delete":
        res = await db.customers.delete_many(q)
        return {"ok": True, "deleted": res.deleted_count}
    if body.action in ("add_tag", "remove_tag"):
        if not body.tag:
            raise HTTPException(400, "tag is required")
        op = "$addToSet" if body.action == "add_tag" else "$pull"
        res = await db.customers.update_many(q, {op: {"tags": body.tag}})
        return {"ok": True, "updated": res.modified_count}
    if body.action in ("add_waitlist", "remove_waitlist"):
        res = await db.customers.update_many(
            q, {"$set": {"waitlisted": body.action == "add_waitlist"}}
        )
        return {"ok": True, "updated": res.modified_count}
    raise HTTPException(400, f"Unknown action: {body.action}")


@router.post("/customers")
async def create_customer(body: CustomerIn,
                          user: dict = Depends(require_admin),
                          tenant: dict = Depends(get_current_tenant)):
    doc = body.dict()
    doc.update({"id": new_id(), "tenant_id": tenant["id"], "created_at": now_iso()})
    await db.customers.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.post("/customers/{cid}/create-login")
async def create_customer_login(cid: str, body: CreateLoginRequest,
                                user: dict = Depends(require_admin),
                                tenant: dict = Depends(get_current_tenant)):
    customer = await db.customers.find_one(
        {"id": cid, "tenant_id": tenant["id"]}, {"_id": 0}
    )
    if not customer:
        raise HTTPException(404, "Customer not found")
    email = body.email.lower()
    if await db.users.find_one({"email": email}):
        raise HTTPException(400, "An account with this email already exists")
    new_user = {
        "id": new_id(), "name": customer["name"], "email": email,
        "password_hash": hash_password(body.password), "role": "customer",
        "avatar": "", "technician_id": None, "customer_id": cid,
        "tenant_id": tenant["id"],
    }
    await db.users.insert_one(new_user)
    await db.customers.update_one(
        {"id": cid, "tenant_id": tenant["id"]},
        {"$set": {"email": email, "has_login": True}},
    )
    return {"ok": True, "email": email}


@router.get("/customers/{cid}")
async def get_customer(cid: str,
                       user: dict = Depends(get_current_user),
                       tenant: dict = Depends(get_current_tenant)):
    doc = await db.customers.find_one(
        {"id": cid, "tenant_id": tenant["id"]}, {"_id": 0}
    )
    if not doc:
        raise HTTPException(404, "Customer not found")
    jobs = await db.jobs.find(
        {"customer_id": cid, "tenant_id": tenant["id"]}, {"_id": 0}
    ).sort("scheduled_date", -1).to_list(200)
    doc["jobs"] = jobs
    return doc


@router.get("/customers/{cid}/deactivation-preview")
async def deactivation_preview(cid: str,
                                user: dict = Depends(require_admin),
                                tenant: dict = Depends(get_current_tenant)):
    """Phase 34f — dry-run for the Active/Inactive toggle confirm dialog.
    Returns the counts that WOULD be affected if the caller flipped
    `is_active` from true → false right now. Does not mutate anything."""
    if not await db.customers.find_one(
        {"id": cid, "tenant_id": tenant["id"]}, {"_id": 0, "id": 1}
    ):
        raise HTTPException(404, "Customer not found")
    today_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    future_q = {
        "customer_id": cid,
        "tenant_id": tenant["id"],
        "scheduled_date": {"$gte": today_iso},
        "status": {"$in": ["scheduled", "pending", "confirmed"]},
    }
    future_count = await db.jobs.count_documents(future_q)
    recurring_count = await db.jobs.count_documents(
        {**future_q, "auto_recurring": True}
    )
    return {
        "future_job_count": future_count,
        "recurring_template_count": recurring_count,
    }


@router.put("/customers/{cid}")
async def update_customer(cid: str, body: CustomerIn,
                          user: dict = Depends(require_admin),
                          tenant: dict = Depends(get_current_tenant)):
    existing = await db.customers.find_one(
        {"id": cid, "tenant_id": tenant["id"]}, {"_id": 0}
    )
    if not existing:
        raise HTTPException(404, "Customer not found")

    # Phase 34f — Active/inactive lifecycle detection. Missing field on the
    # existing doc defaults to True (all legacy customers were implicitly
    # active). New value defaults to True on the input model.
    was_active = existing.get("is_active", True)
    now_active = bool(body.is_active) if body.is_active is not None else True
    deactivating = was_active is True and now_active is False

    await db.customers.update_one(
        {"id": cid, "tenant_id": tenant["id"]}, {"$set": body.dict()}
    )

    cancelled_job_count = 0
    deactivated_recurring_count = 0
    if deactivating:
        today_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        q = {
            "customer_id": cid,
            "tenant_id": tenant["id"],
            "scheduled_date": {"$gte": today_iso},
            "status": {"$in": ["scheduled", "pending", "confirmed"]},
        }
        # Count recurring instances BEFORE the update so we can report both
        # totals honestly. `auto_recurring` is the flag Phase 20 attached to
        # jobs created by `create_recurring_maintenance` — there is no
        # separate recurring-templates collection in this codebase.
        deactivated_recurring_count = await db.jobs.count_documents(
            {**q, "auto_recurring": True}
        )
        upd = await db.jobs.update_many(
            q,
            {"$set": {
                "status": "cancelled",
                "cancellation_reason": "Customer marked inactive",
                "cancelled_at": now_iso(),
                "cancelled_by_user_id": user["id"],
                "auto_recurring": False,
            }},
        )
        cancelled_job_count = int(upd.modified_count or 0)

        # Log the transition for the future retention report.
        await db.customer_activation_events.insert_one({
            "id": new_id(),
            "tenant_id": tenant["id"],
            "customer_id": cid,
            "from_status": "active",
            "to_status": "inactive",
            "changed_at": now_iso(),
            "changed_by_user_id": user["id"],
            "cancelled_job_count": cancelled_job_count,
            "deactivated_recurring_count": deactivated_recurring_count,
        })
    elif was_active is False and now_active is True:
        # Reactivation logged for symmetry, but nothing else cascades.
        await db.customer_activation_events.insert_one({
            "id": new_id(),
            "tenant_id": tenant["id"],
            "customer_id": cid,
            "from_status": "inactive",
            "to_status": "active",
            "changed_at": now_iso(),
            "changed_by_user_id": user["id"],
            "cancelled_job_count": 0,
            "deactivated_recurring_count": 0,
        })

    doc = await db.customers.find_one(
        {"id": cid, "tenant_id": tenant["id"]}, {"_id": 0}
    )
    if deactivating:
        doc["cancelled_job_count"] = cancelled_job_count
        doc["deactivated_recurring_count"] = deactivated_recurring_count
    return doc


@router.delete("/customers/{cid}")
async def delete_customer(cid: str,
                          user: dict = Depends(require_admin),
                          tenant: dict = Depends(get_current_tenant)):
    await db.customers.delete_one({"id": cid, "tenant_id": tenant["id"]})
    return {"ok": True}
