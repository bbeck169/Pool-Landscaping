# ruff: noqa: F403,F405
from fastapi import APIRouter, HTTPException, Depends, Query
from typing import List, Optional
from datetime import datetime, timezone, timedelta

from config import db, logger, EMERGENT_LLM_KEY
from utils import (now_iso, new_id, hash_password, verify_password, create_token,
                   get_current_user, require_admin, send_sms, notify_customer, auth_response)
from models import *  # noqa: F403,F405

router = APIRouter()


# ----------------------- Price Book -----------------------
@router.get("/items")
async def list_items(user: dict = Depends(require_admin)):
    # BUG B fix (Feb-2026) — filter out soft-deleted rows.
    return await db.items.find(
        {"$or": [{"deleted_at": None}, {"deleted_at": {"$exists": False}}]},
        {"_id": 0},
    ).sort("name", 1).to_list(1000)


@router.post("/items")
async def create_item(body: ItemIn, user: dict = Depends(require_admin)):
    doc = body.dict()
    doc.update({"id": new_id(), "created_at": now_iso()})
    await db.items.insert_one(doc)
    doc.pop("_id", None)
    return doc


async def _soft_delete_item(iid: str, actor_id: Optional[str]) -> dict:
    row = await db.items.find_one({"id": iid}, {"_id": 0})
    if not row:
        raise HTTPException(404, "Item not found")
    if row.get("deleted_at"):
        return {"ok": True, "already_deleted": True}
    await db.items.update_one(
        {"id": iid},
        {"$set": {"deleted_at": now_iso(),
                    "deleted_by_user_id": actor_id}},
    )
    return {"ok": True, "id": iid, "soft_deleted": True}


@router.delete("/items/{iid}")
async def delete_item(iid: str, user: dict = Depends(require_admin)):
    # BUG B fix — switched from hard delete to soft delete so history
    # rows (invoices/quotes referencing the item) stay intact.
    return await _soft_delete_item(iid, user.get("id"))


# Alias per the Item 8 spec — same collection, different URL surface.
@router.delete("/pricebook/{iid}",
                operation_id="pricebook.delete")
async def delete_pricebook_item(iid: str, user: dict = Depends(require_admin)):
    return await _soft_delete_item(iid, user.get("id"))
