"""Phase 20B.3 · Assets / equipment tracking.

Manages physical company assets (trucks, trailers, pumps, tools) with:
- CRUD on assets
- Assign / unassign to a user (logs to `asset_assignments_log`)
- Maintenance log entries (`asset_maintenance`)
- Next-due reminder scan (admin poll endpoint; a real cron can hit the
  same helper daily)
"""
from datetime import datetime, timedelta, timezone
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from config import db, logger
from utils import now_iso, new_id, get_current_user, require_admin
from routers.tenants import get_current_tenant

router = APIRouter()


class AssetIn(BaseModel):
    name: str
    category: str                              # vehicle|equipment|tool|other
    asset_tag: Optional[str] = None
    serial_number: Optional[str] = None
    purchase_date: Optional[str] = None
    purchase_price: Optional[float] = None
    warranty_expires_at: Optional[str] = None
    assigned_to_user_id: Optional[str] = None
    home_location: Optional[str] = None
    status: Optional[str] = "active"           # active|maintenance|retired
    photo_url: Optional[str] = None
    notes: Optional[str] = ""


class AssetUpdate(BaseModel):
    name: Optional[str] = None
    category: Optional[str] = None
    asset_tag: Optional[str] = None
    serial_number: Optional[str] = None
    purchase_date: Optional[str] = None
    purchase_price: Optional[float] = None
    warranty_expires_at: Optional[str] = None
    home_location: Optional[str] = None
    status: Optional[str] = None
    photo_url: Optional[str] = None
    notes: Optional[str] = None


class AssignIn(BaseModel):
    user_id: Optional[str] = None            # `None` → unassign
    notes: Optional[str] = None


class MaintenanceIn(BaseModel):
    kind: str                                # service|repair|inspection
    performed_at: Optional[str] = None
    performed_by: Optional[str] = None
    mileage_or_hours: Optional[float] = None
    cost: Optional[float] = 0.0
    notes: Optional[str] = ""
    next_due_at: Optional[str] = None
    receipt_urls: Optional[List[str]] = None


@router.get("/assets")
async def list_assets(
    category: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    assignee: Optional[str] = Query(None),
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    role = user.get("role")
    if role == "customer":
        raise HTTPException(403, "Not allowed")
    q: dict = {"tenant_id": tenant["id"]}
    if role in ("tech", "technician"):
        # Techs only see what's assigned to them.
        q["assigned_to_user_id"] = user["id"]
    if category: q["category"] = category
    if status:   q["status"] = status
    if assignee: q["assigned_to_user_id"] = assignee
    return await db.assets.find(q, {"_id": 0}).sort("name", 1).to_list(1000)


@router.post("/assets")
async def create_asset(body: AssetIn,
                       user: dict = Depends(require_admin),
                       tenant: dict = Depends(get_current_tenant)):
    doc = {
        "id": new_id(),
        "tenant_id": tenant["id"],
        **body.dict(),
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    await db.assets.insert_one(dict(doc))
    if doc.get("assigned_to_user_id"):
        await db.asset_assignments_log.insert_one({
            "id": new_id(),
            "tenant_id": tenant["id"],
            "asset_id": doc["id"],
            "from_user_id": None,
            "to_user_id": doc["assigned_to_user_id"],
            "assigned_at": now_iso(),
            "unassigned_at": None,
            "notes": "Initial assignment",
        })
    doc.pop("_id", None)
    return doc


@router.get("/assets/{aid}")
async def get_asset(aid: str,
                    user: dict = Depends(get_current_user),
                    tenant: dict = Depends(get_current_tenant)):
    if user.get("role") == "customer":
        raise HTTPException(403, "Not allowed")
    a = await db.assets.find_one({"id": aid, "tenant_id": tenant["id"]}, {"_id": 0})
    if not a: raise HTTPException(404, "Asset not found")
    if user.get("role") in ("tech", "technician") and a.get("assigned_to_user_id") != user["id"]:
        raise HTTPException(403, "Not assigned to you")
    return a


@router.put("/assets/{aid}")
async def update_asset(aid: str, body: AssetUpdate,
                       user: dict = Depends(require_admin),
                       tenant: dict = Depends(get_current_tenant)):
    upd = {k: v for k, v in body.dict().items() if v is not None}
    if not upd: raise HTTPException(400, "Nothing to update")
    upd["updated_at"] = now_iso()
    r = await db.assets.update_one(
        {"id": aid, "tenant_id": tenant["id"]}, {"$set": upd}
    )
    if r.matched_count == 0: raise HTTPException(404, "Asset not found")
    return await db.assets.find_one({"id": aid, "tenant_id": tenant["id"]}, {"_id": 0})


@router.delete("/assets/{aid}")
async def delete_asset(aid: str,
                       user: dict = Depends(require_admin),
                       tenant: dict = Depends(get_current_tenant)):
    r = await db.assets.delete_one({"id": aid, "tenant_id": tenant["id"]})
    if r.deleted_count == 0: raise HTTPException(404, "Asset not found")
    return {"ok": True}


@router.post("/assets/{aid}/assign")
async def assign_asset(aid: str, body: AssignIn,
                       user: dict = Depends(require_admin),
                       tenant: dict = Depends(get_current_tenant)):
    a = await db.assets.find_one({"id": aid, "tenant_id": tenant["id"]}, {"_id": 0})
    if not a: raise HTTPException(404, "Asset not found")
    prev_uid = a.get("assigned_to_user_id")
    new_uid = body.user_id  # None → unassign

    if new_uid:
        target = await db.users.find_one(
            {"id": new_uid, "tenant_id": tenant["id"]}, {"_id": 0}
        )
        if not target:
            raise HTTPException(404, "User not found in this tenant")

    now = now_iso()
    # Close previous assignment log entry.
    if prev_uid and prev_uid != new_uid:
        await db.asset_assignments_log.update_many(
            {"tenant_id": tenant["id"], "asset_id": aid,
             "to_user_id": prev_uid, "unassigned_at": None},
            {"$set": {"unassigned_at": now, "notes":
                      (body.notes or "reassigned")}},
        )
    # Open a new entry if there's a new owner.
    if new_uid and new_uid != prev_uid:
        await db.asset_assignments_log.insert_one({
            "id": new_id(),
            "tenant_id": tenant["id"],
            "asset_id": aid,
            "from_user_id": prev_uid,
            "to_user_id": new_uid,
            "assigned_at": now,
            "unassigned_at": None,
            "notes": body.notes or "",
        })

    await db.assets.update_one(
        {"id": aid, "tenant_id": tenant["id"]},
        {"$set": {"assigned_to_user_id": new_uid, "updated_at": now}},
    )
    return await db.assets.find_one(
        {"id": aid, "tenant_id": tenant["id"]}, {"_id": 0}
    )


@router.get("/assets/{aid}/assignments")
async def asset_assignments(aid: str,
                             user: dict = Depends(require_admin),
                             tenant: dict = Depends(get_current_tenant)):
    return await db.asset_assignments_log.find(
        {"asset_id": aid, "tenant_id": tenant["id"]}, {"_id": 0}
    ).sort("assigned_at", -1).to_list(500)


@router.get("/assets/{aid}/maintenance")
async def list_maintenance(aid: str,
                            user: dict = Depends(get_current_user),
                            tenant: dict = Depends(get_current_tenant)):
    if user.get("role") == "customer":
        raise HTTPException(403, "Not allowed")
    a = await db.assets.find_one({"id": aid, "tenant_id": tenant["id"]}, {"_id": 0})
    if not a: raise HTTPException(404, "Asset not found")
    if user.get("role") in ("tech", "technician") and a.get("assigned_to_user_id") != user["id"]:
        raise HTTPException(403, "Not assigned to you")
    return await db.asset_maintenance.find(
        {"asset_id": aid, "tenant_id": tenant["id"]}, {"_id": 0},
    ).sort("performed_at", -1).to_list(500)


@router.post("/assets/{aid}/maintenance")
async def add_maintenance(aid: str, body: MaintenanceIn,
                           user: dict = Depends(require_admin),
                           tenant: dict = Depends(get_current_tenant)):
    a = await db.assets.find_one({"id": aid, "tenant_id": tenant["id"]}, {"_id": 0})
    if not a: raise HTTPException(404, "Asset not found")
    doc = {
        "id": new_id(),
        "tenant_id": tenant["id"],
        "asset_id": aid,
        **body.dict(),
        "created_at": now_iso(),
    }
    doc["performed_at"] = doc.get("performed_at") or now_iso()
    await db.asset_maintenance.insert_one(dict(doc))
    if body.next_due_at:
        await db.assets.update_one(
            {"id": aid, "tenant_id": tenant["id"]},
            {"$set": {"next_maintenance_due_at": body.next_due_at,
                      "updated_at": now_iso()}},
        )
    doc.pop("_id", None)
    return doc


@router.get("/assets/reminders/due")
async def due_reminders(days: int = Query(7, ge=1, le=90),
                        user: dict = Depends(require_admin),
                        tenant: dict = Depends(get_current_tenant)):
    """Assets with `next_maintenance_due_at` within the next `days`."""
    cutoff = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()
    now = now_iso()
    q = {
        "tenant_id": tenant["id"],
        "next_maintenance_due_at": {"$exists": True, "$ne": None, "$lte": cutoff},
    }
    docs = await db.assets.find(q, {"_id": 0}).to_list(500)
    overdue = [d for d in docs if d.get("next_maintenance_due_at", "") < now]
    upcoming = [d for d in docs if d.get("next_maintenance_due_at", "") >= now]
    # Emit WS event so admins can toast.
    try:
        from routers.realtime import bus
        for d in overdue + upcoming:
            await bus.broadcast(user["id"], {
                "type": "asset_maintenance_due",
                "payload": {"asset_id": d["id"], "name": d.get("name"),
                            "next_due_at": d.get("next_maintenance_due_at"),
                            "overdue": d in overdue},
            })
    except Exception as e:
        logger.warning(f"assets due WS notify failed: {e}")
    return {"overdue": overdue, "upcoming": upcoming, "count": len(docs)}
