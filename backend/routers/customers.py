from fastapi import APIRouter, HTTPException, Depends, Query
from typing import List, Optional
from datetime import datetime, timezone, timedelta

from config import db, logger, EMERGENT_LLM_KEY
from utils import (now_iso, new_id, hash_password, verify_password, create_token,
                   get_current_user, require_admin, send_sms, notify_customer, auth_response)
from models import *

router = APIRouter()


# ----------------------- Customers -----------------------
@router.get("/me")
async def get_my_profile(user: dict = Depends(get_current_user)):
    if user.get("role") != "customer" or not user.get("customer_id"):
        raise HTTPException(403, "Customers only")
    doc = await db.customers.find_one({"id": user["customer_id"]}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Profile not found")
    return doc


@router.put("/me")
async def update_my_profile(body: CustomerProfileUpdate, user: dict = Depends(get_current_user)):
    if user.get("role") != "customer" or not user.get("customer_id"):
        raise HTTPException(403, "Customers only")
    update = {k: v for k, v in body.dict().items() if v is not None}
    if update:
        await db.customers.update_one({"id": user["customer_id"]}, {"$set": update})
        # keep the login user's display name/avatar in sync
        user_patch = {k: update[k] for k in ("name", "avatar") if k in update}
        if user_patch:
            await db.users.update_one({"id": user["id"]}, {"$set": user_patch})
    return await db.customers.find_one({"id": user["customer_id"]}, {"_id": 0})


@router.get("/customers")
async def list_customers(
    user: dict = Depends(get_current_user),
    search: Optional[str] = None,
    tag: Optional[str] = None,
    waitlisted: Optional[bool] = None,
    unscheduled: Optional[bool] = None,
):
    # RBAC: only staff (admin/technician) may list customer records. Customers use /me.
    if user.get("role") not in ("admin", "technician"):
        raise HTTPException(403, "Not allowed")
    q: dict = {}
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
                {"status": {"$nin": ["completed", "cancelled"]}},
                {"customer_id": 1, "_id": 0},
            )]
        )
        docs = [d for d in docs if d["id"] not in scheduled_ids]
    return docs


@router.post("/customers/bulk")
async def customers_bulk(body: CustomerBulkAction, user: dict = Depends(require_admin)):
    """Bulk-update or bulk-delete a selection of customers."""
    if not body.ids:
        return {"ok": True, "updated": 0}
    q = {"id": {"$in": body.ids}}
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
async def create_customer(body: CustomerIn, user: dict = Depends(require_admin)):
    doc = body.dict()
    doc.update({"id": new_id(), "created_at": now_iso()})
    await db.customers.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.post("/customers/{cid}/create-login")
async def create_customer_login(cid: str, body: CreateLoginRequest, user: dict = Depends(require_admin)):
    customer = await db.customers.find_one({"id": cid}, {"_id": 0})
    if not customer:
        raise HTTPException(404, "Customer not found")
    email = body.email.lower()
    if await db.users.find_one({"email": email}):
        raise HTTPException(400, "An account with this email already exists")
    new_user = {
        "id": new_id(), "name": customer["name"], "email": email,
        "password_hash": hash_password(body.password), "role": "customer",
        "avatar": "", "technician_id": None, "customer_id": cid,
    }
    await db.users.insert_one(new_user)
    await db.customers.update_one({"id": cid}, {"$set": {"email": email, "has_login": True}})
    return {"ok": True, "email": email}


@router.get("/customers/{cid}")
async def get_customer(cid: str, user: dict = Depends(get_current_user)):
    doc = await db.customers.find_one({"id": cid}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Customer not found")
    jobs = await db.jobs.find({"customer_id": cid}, {"_id": 0}).sort("scheduled_date", -1).to_list(200)
    doc["jobs"] = jobs
    return doc


@router.put("/customers/{cid}")
async def update_customer(cid: str, body: CustomerIn, user: dict = Depends(require_admin)):
    res = await db.customers.update_one({"id": cid}, {"$set": body.dict()})
    if res.matched_count == 0:
        raise HTTPException(404, "Customer not found")
    return await db.customers.find_one({"id": cid}, {"_id": 0})


@router.delete("/customers/{cid}")
async def delete_customer(cid: str, user: dict = Depends(require_admin)):
    await db.customers.delete_one({"id": cid})
    return {"ok": True}

