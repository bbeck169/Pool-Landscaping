"""Phase 15B — Admin onboarding wizard state.

Stores per-admin progress in `db.onboarding_state`. Fields:
{
  admin_id: str,
  current_step: int (0..6),
  completed: bool,
  skipped: bool,
  data: dict,  # incremental fields captured per step
  updated_at: iso,
}
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from config import db, logger
from utils import now_iso, new_id, require_admin

router = APIRouter()

TOTAL_STEPS = 7


class UpdateProgressIn(BaseModel):
    current_step: Optional[int] = None
    data: Optional[dict] = None
    completed: Optional[bool] = None
    skipped: Optional[bool] = None


async def _seed_completed_for_demo() -> None:
    """Mark the demo admin as complete on startup so the wizard doesn't hijack the demo."""
    admin = await db.users.find_one({"email": "admin@aquaterra.com", "role": "admin"}, {"_id": 0})
    if not admin:
        return
    existing = await db.onboarding_state.find_one({"admin_id": admin["id"]}, {"_id": 0})
    if existing:
        return
    await db.onboarding_state.insert_one({
        "id": new_id(),
        "admin_id": admin["id"],
        "current_step": TOTAL_STEPS,
        "completed": True,
        "skipped": False,
        "data": {"seeded": True},
        "updated_at": now_iso(),
    })


@router.get("/onboarding")
async def get_state(user: dict = Depends(require_admin)):
    doc = await db.onboarding_state.find_one({"admin_id": user["id"]}, {"_id": 0})
    if not doc:
        # Lazy-initialise for new admins.
        doc = {
            "id": new_id(),
            "admin_id": user["id"],
            "current_step": 0,
            "completed": False,
            "skipped": False,
            "data": {},
            "updated_at": now_iso(),
        }
        await db.onboarding_state.insert_one(doc)
        doc.pop("_id", None)
    return {**doc, "total_steps": TOTAL_STEPS}


@router.post("/onboarding/progress")
async def update_progress(body: UpdateProgressIn, user: dict = Depends(require_admin)):
    doc = await db.onboarding_state.find_one({"admin_id": user["id"]}, {"_id": 0})
    if not doc:
        doc = {
            "id": new_id(),
            "admin_id": user["id"],
            "current_step": 0,
            "completed": False,
            "skipped": False,
            "data": {},
            "updated_at": now_iso(),
        }
        await db.onboarding_state.insert_one(doc)
    upd: dict = {"updated_at": now_iso()}
    if body.current_step is not None:
        upd["current_step"] = max(0, min(TOTAL_STEPS, body.current_step))
    if body.completed is not None:
        upd["completed"] = bool(body.completed)
        if body.completed:
            upd["current_step"] = TOTAL_STEPS
    if body.skipped is not None:
        upd["skipped"] = bool(body.skipped)
        if body.skipped:
            upd["completed"] = True
            upd["current_step"] = TOTAL_STEPS
    if body.data is not None:
        merged = dict(doc.get("data") or {})
        merged.update(body.data)
        upd["data"] = merged

    await db.onboarding_state.update_one({"admin_id": user["id"]}, {"$set": upd})
    fresh = await db.onboarding_state.find_one({"admin_id": user["id"]}, {"_id": 0})
    return {**fresh, "total_steps": TOTAL_STEPS}


@router.post("/onboarding/restart")
async def restart(user: dict = Depends(require_admin)):
    await db.onboarding_state.update_one(
        {"admin_id": user["id"]},
        {"$set": {
            "current_step": 0,
            "completed": False,
            "skipped": False,
            "updated_at": now_iso(),
        }},
        upsert=True,
    )
    fresh = await db.onboarding_state.find_one({"admin_id": user["id"]}, {"_id": 0})
    if not fresh:
        fresh = {
            "id": new_id(),
            "admin_id": user["id"],
            "current_step": 0,
            "completed": False,
            "skipped": False,
            "data": {},
            "updated_at": now_iso(),
        }
        await db.onboarding_state.insert_one(fresh)
        fresh.pop("_id", None)
    return {**fresh, "total_steps": TOTAL_STEPS}
