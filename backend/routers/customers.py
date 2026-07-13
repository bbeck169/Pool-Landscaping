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
async def list_customers(user: dict = Depends(get_current_user), search: Optional[str] = None):
    # RBAC: only staff (admin/technician) may list customer records. Customers use /me.
    if user.get("role") not in ("admin", "technician"):
        raise HTTPException(403, "Not allowed")
    q = {}
    if search:
        q = {"name": {"$regex": search, "$options": "i"}}
    docs = await db.customers.find(q, {"_id": 0}).sort("name", 1).to_list(1000)
    return docs


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

