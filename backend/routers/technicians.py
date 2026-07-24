# ruff: noqa: F403,F405
from fastapi import APIRouter, HTTPException, Depends, Query
from typing import List, Optional
from datetime import datetime, timezone, timedelta

from config import db, logger, EMERGENT_LLM_KEY
from utils import (now_iso, new_id, hash_password, verify_password, create_token,
                   get_current_user, require_admin, send_sms, notify_customer, auth_response)
from models import *  # noqa: F403,F405

router = APIRouter()


# ----------------------- Technicians -----------------------
@router.get("/technicians")
async def list_technicians(user: dict = Depends(get_current_user)):
    docs = await db.technicians.find({}, {"_id": 0}).sort("name", 1).to_list(1000)
    # Phase 21 · Feb 2026 · Addition B — enrich each technician with the
    # linked user's ``display_color_hex`` so the Schedule / dispatch UIs
    # can tint event cards without a second roundtrip. Cheap: one bulk
    # ``$in`` lookup regardless of tech count.
    tech_user_ids = [t.get("user_id") for t in docs if t.get("user_id")]
    color_by_uid: dict = {}
    if tech_user_ids:
        async for u in db.users.find(
            {"id": {"$in": tech_user_ids}},
            {"_id": 0, "id": 1, "display_color_hex": 1},
        ):
            if u.get("display_color_hex"):
                color_by_uid[u["id"]] = u["display_color_hex"]
    for t in docs:
        t["active_jobs"] = await db.jobs.count_documents(
            {"technician_id": t["id"], "status": {"$in": ["pending", "active"]}}
        )
        t["display_color_hex"] = color_by_uid.get(t.get("user_id"))
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
    # Techs can only view their own profile — enforce here.
    if user.get("role") == "technician" and user.get("id") != tid and user.get("technician_id") != tid:
        raise HTTPException(403, "You can only view your own profile")
    doc = await db.technicians.find_one({"id": tid}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Technician not found")
    doc["jobs"] = await db.jobs.find({"technician_id": tid}, {"_id": 0}).sort("scheduled_date", -1).to_list(200)
    return doc


@router.get("/technicians/{tid}/performance")
async def technician_performance(tid: str, user: dict = Depends(get_current_user)):
    """Computed performance metrics over the last 90 days."""
    if user.get("role") == "technician" and user.get("id") != tid and user.get("technician_id") != tid:
        raise HTTPException(403, "You can only view your own profile")
    from datetime import datetime, timezone, timedelta  # noqa: F811
    cutoff = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
    jobs = await db.jobs.find(
        {"technician_id": tid, "created_at": {"$gte": cutoff}}, {"_id": 0}
    ).to_list(500)
    total = len(jobs)
    completed = [j for j in jobs if j.get("status") == "completed"]
    on_time = [j for j in completed if not j.get("late")]
    durations = [j.get("duration_min") or 0 for j in completed if j.get("duration_min")]
    ratings = [j.get("rating") for j in completed if j.get("rating") is not None]
    return {
        "period_days": 90,
        "total_jobs": total,
        "completed_jobs": len(completed),
        "completion_rate": round(100 * len(completed) / total, 1) if total else 0,
        "on_time_rate": round(100 * len(on_time) / len(completed), 1) if completed else 0,
        "avg_duration_min": round(sum(durations) / len(durations)) if durations else 0,
        "avg_customer_rating": round(sum(ratings) / len(ratings), 2) if ratings else None,
    }

