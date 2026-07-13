from fastapi import APIRouter, HTTPException, Depends, Query
from typing import List, Optional
from datetime import datetime, timezone, timedelta

from config import db, logger, EMERGENT_LLM_KEY
from utils import (now_iso, new_id, hash_password, verify_password, create_token,
                   get_current_user, require_admin, send_sms, notify_customer, auth_response)
from models import *

router = APIRouter()


# ----------------------- Technicians -----------------------
@router.get("/technicians")
async def list_technicians(user: dict = Depends(get_current_user)):
    docs = await db.technicians.find({}, {"_id": 0}).sort("name", 1).to_list(1000)
    for t in docs:
        t["active_jobs"] = await db.jobs.count_documents(
            {"technician_id": t["id"], "status": {"$in": ["pending", "active"]}}
        )
    return docs


@router.post("/technicians")
async def create_technician(body: TechnicianIn, user: dict = Depends(require_admin)):
    doc = body.dict()
    doc.update({"id": new_id(), "active": True, "created_at": now_iso()})
    await db.technicians.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.get("/technicians/{tid}")
async def get_technician(tid: str, user: dict = Depends(get_current_user)):
    doc = await db.technicians.find_one({"id": tid}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Technician not found")
    doc["jobs"] = await db.jobs.find({"technician_id": tid}, {"_id": 0}).sort("scheduled_date", -1).to_list(200)
    return doc

