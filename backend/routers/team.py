from fastapi import APIRouter, HTTPException, Depends, Query
from typing import List, Optional
from datetime import datetime, timezone, timedelta

from config import db, logger, EMERGENT_LLM_KEY
from utils import (now_iso, new_id, hash_password, verify_password, create_token,
                   get_current_user, require_admin, send_sms, notify_customer, auth_response)
from models import *

router = APIRouter()


# ----------------------- Team -----------------------
@router.get("/team")
async def list_team(user: dict = Depends(require_admin)):
    users = await db.users.find({"role": {"$in": ["admin", "technician"]}}, {"_id": 0, "password_hash": 0}).to_list(1000)
    for u in users:
        if u.get("technician_id"):
            u["active_jobs"] = await db.jobs.count_documents({"technician_id": u["technician_id"], "status": {"$in": ["pending", "active"]}})
    return users


