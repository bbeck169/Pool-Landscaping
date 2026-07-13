from fastapi import APIRouter, HTTPException, Depends, Query
from typing import List, Optional
from datetime import datetime, timezone, timedelta

from config import db, logger, EMERGENT_LLM_KEY
from utils import (now_iso, new_id, hash_password, verify_password, create_token,
                   get_current_user, require_admin, send_sms, notify_customer, auth_response)
from models import *

router = APIRouter()


# ----------------------- Price Book -----------------------
@router.get("/items")
async def list_items(user: dict = Depends(require_admin)):
    return await db.items.find({}, {"_id": 0}).sort("name", 1).to_list(1000)


@router.post("/items")
async def create_item(body: ItemIn, user: dict = Depends(require_admin)):
    doc = body.dict()
    doc.update({"id": new_id(), "created_at": now_iso()})
    await db.items.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.delete("/items/{iid}")
async def delete_item(iid: str, user: dict = Depends(require_admin)):
    await db.items.delete_one({"id": iid})
    return {"ok": True}


