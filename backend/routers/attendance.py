from fastapi import APIRouter, HTTPException, Depends, Query
from datetime import datetime, timezone
from typing import Optional

from config import db
from utils import now_iso, new_id, get_current_user, require_admin
from routers.tenants import get_current_tenant
from models import PunchIn

router = APIRouter()


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _require_tech(user: dict) -> str:
    if user.get("role") != "technician" or not user.get("technician_id"):
        raise HTTPException(403, "Only technicians can clock in and out.")
    return user["technician_id"]


def _hours(a: str, b: str) -> float:
    try:
        d = datetime.fromisoformat(b) - datetime.fromisoformat(a)
        return round(d.total_seconds() / 3600.0, 2)
    except Exception:
        return 0.0


@router.get("/attendance/today")
async def attendance_today(user: dict = Depends(get_current_user),
                           tenant: dict = Depends(get_current_tenant)):
    tid = _require_tech(user)
    doc = await db.timesheets.find_one(
        {"technician_id": tid, "date": _today(), "tenant_id": tenant["id"]},
        {"_id": 0},
    )
    if not doc:
        return {"date": _today(), "clocked_in": False, "clocked_out": False, "timesheet": None}
    return {
        "date": _today(),
        "clocked_in": bool(doc.get("clock_in_at")),
        "clocked_out": bool(doc.get("clock_out_at")),
        "timesheet": doc,
    }


@router.post("/attendance/clock-in")
async def clock_in(body: PunchIn,
                   user: dict = Depends(get_current_user),
                   tenant: dict = Depends(get_current_tenant)):
    tid = _require_tech(user)
    today = _today()
    existing = await db.timesheets.find_one(
        {"technician_id": tid, "date": today, "tenant_id": tenant["id"]},
        {"_id": 0},
    )
    if existing and existing.get("clock_in_at"):
        raise HTTPException(400, "You're already clocked in for today.")
    doc = {
        "id": new_id(), "tenant_id": tenant["id"],
        "technician_id": tid, "technician_name": user.get("name", ""),
        "date": today,
        "clock_in_at": now_iso(), "clock_in_lat": body.lat, "clock_in_lng": body.lng,
        "clock_out_at": None, "clock_out_lat": None, "clock_out_lng": None,
        "hours": 0.0, "created_at": now_iso(),
    }
    await db.timesheets.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.post("/attendance/clock-out")
async def clock_out(body: PunchIn,
                    user: dict = Depends(get_current_user),
                    tenant: dict = Depends(get_current_tenant)):
    tid = _require_tech(user)
    today = _today()
    doc = await db.timesheets.find_one(
        {"technician_id": tid, "date": today, "tenant_id": tenant["id"]},
        {"_id": 0},
    )
    if not doc or not doc.get("clock_in_at"):
        raise HTTPException(400, "Clock in first before clocking out.")
    if doc.get("clock_out_at"):
        raise HTTPException(400, "You've already clocked out for today.")
    out_at = now_iso()
    hours = _hours(doc["clock_in_at"], out_at)
    await db.timesheets.update_one(
        {"id": doc["id"], "tenant_id": tenant["id"]},
        {"$set": {
            "clock_out_at": out_at, "clock_out_lat": body.lat, "clock_out_lng": body.lng,
            "hours": hours,
        }},
    )
    return await db.timesheets.find_one(
        {"id": doc["id"], "tenant_id": tenant["id"]}, {"_id": 0}
    )


@router.get("/attendance/report")
async def attendance_report(technician_id: Optional[str] = Query(None),
                            date_from: Optional[str] = Query(None),
                            date_to: Optional[str] = Query(None),
                            admin: dict = Depends(require_admin),
                            tenant: dict = Depends(get_current_tenant)):
    q: dict = {"tenant_id": tenant["id"]}
    if technician_id:
        q["technician_id"] = technician_id
    if date_from or date_to:
        rng: dict = {}
        if date_from:
            rng["$gte"] = date_from
        if date_to:
            rng["$lte"] = date_to
        q["date"] = rng
    rows = await db.timesheets.find(q, {"_id": 0}).sort("date", -1).to_list(2000)
    total_hours = round(sum(float(r.get("hours") or 0) for r in rows), 2)
    return {"count": len(rows), "total_hours": total_hours, "rows": rows}


# ─────────────────────────────────────────────────────────────────
# Feb-2026 · Mobile Ticket 2 Part 2 — hard delete for
# ``db.timesheets``.  Admin-tier only (mirrors
# ``timeclock_admin._require_admin_strict`` = admin + super_admin
# only).  Row is snapshotted into ``db.timesheets_hard_deletes``
# before ``delete_one`` so a DB admin can recover a fat-finger.
# Reason ≥ 3 chars required for the audit trail (no typed-CAPTCHA
# UI per operator spec, server-side gate is enough).
# ─────────────────────────────────────────────────────────────────
def _require_admin_strict_attendance(user: dict = Depends(get_current_user)):
    role = (user.get("role") or "").lower()
    if role not in ("admin", "super_admin"):
        raise HTTPException(
            status_code=403,
            detail={"code": "forbidden",
                    "msg": "Admin or super_admin role required."},
        )
    return user


@router.delete("/attendance/timesheets/{row_id}")
async def delete_timesheet(row_id: str,
                           reason: str = Query(..., min_length=3),
                           actor: dict = Depends(_require_admin_strict_attendance),
                           tenant: dict = Depends(get_current_tenant)):
    reason_clean = (reason or "").strip()
    if len(reason_clean) < 3:
        raise HTTPException(400, detail={
            "code": "reason_required",
            "msg": "A reason of at least 3 characters is required.",
        })
    row = await db.timesheets.find_one(
        {"id": row_id, "tenant_id": tenant["id"]}, {"_id": 0},
    )
    if not row:
        # 404 for missing-id AND cross-tenant miss (never leak
        # the existence of another tenant's row).
        raise HTTPException(404, detail={"code": "timesheet_not_found"})

    now = now_iso()
    await db.timesheets_hard_deletes.insert_one({
        "id": new_id(),
        "tenant_id": tenant["id"],
        "collection": "timesheets",
        "original_id": row_id,
        "deleted_by": actor["id"],
        "deleted_at": now,
        "reason": reason_clean,
        "original_row": row,
    })
    await db.timesheets.delete_one(
        {"id": row_id, "tenant_id": tenant["id"]},
    )
    return {"deleted": True, "hard": True, "row_id": row_id,
            "deleted_at": now}
