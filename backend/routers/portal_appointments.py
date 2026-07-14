"""Phase 20B.1b · Customer self-service appointment booking.

Customer picks a date + preferred window → server creates a
`pending_appointment`. Admin queue approves or rejects. On confirm, a job is
auto-created via the standard jobs pipeline with `source_appointment_id`.

Availability is a lightweight open-slot calculation from existing jobs + tech
count; not a full calendar sync (that arrives in a later phase).
"""
from datetime import datetime, timedelta, timezone
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from config import db, logger
from utils import now_iso, new_id, get_current_user, require_admin
from routers.tenants import get_current_tenant

router = APIRouter()


WINDOWS = [
    {"key": "morning",   "label": "Morning (8am–12pm)",   "start_hour": 8,  "end_hour": 12},
    {"key": "afternoon", "label": "Afternoon (1pm–5pm)",  "start_hour": 13, "end_hour": 17},
]


class AppointmentIn(BaseModel):
    service_type: str
    preferred_date: str            # YYYY-MM-DD
    preferred_window: str          # "morning" | "afternoon"
    address: Optional[str] = None
    notes: Optional[str] = None


class RejectIn(BaseModel):
    reason: str


def _require_customer(user: dict) -> str:
    if user.get("role") != "customer" or not user.get("customer_id"):
        raise HTTPException(403, "Customers only")
    return user["customer_id"]


@router.get("/portal/availability")
async def availability(
    date_range: Optional[str] = Query(None, description="days ahead (default 14)"),
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    """Return lightweight open windows for the next N business days."""
    _require_customer(user)
    try:
        days = int(date_range) if date_range else 14
    except ValueError:
        days = 14
    days = min(30, max(1, days))
    tid = tenant["id"]
    tech_count = max(1, await db.users.count_documents(
        {"tenant_id": tid, "role": "tech"}
    ))
    # Slot capacity per window = tech_count * 3 (max 3 jobs per tech per window).
    capacity = tech_count * 3
    out: List[dict] = []
    d0 = datetime.now(timezone.utc).date()
    for i in range(1, days + 1):
        d = d0 + timedelta(days=i)
        if d.weekday() >= 5:   # skip weekends
            continue
        day_iso = d.isoformat()
        for w in WINDOWS:
            booked = await db.jobs.count_documents({
                "tenant_id": tid,
                "scheduled_start": {"$regex": f"^{day_iso}"},
            })
            available = max(0, capacity - booked)
            out.append({
                "date": day_iso,
                "window": w["key"],
                "label": f"{d.strftime('%a %b %d')} · {w['label']}",
                "slots_remaining": available,
                "full": available == 0,
            })
    return {"windows": out, "capacity_per_window": capacity}


@router.post("/portal/appointments")
async def create_appointment(body: AppointmentIn,
                              user: dict = Depends(get_current_user),
                              tenant: dict = Depends(get_current_tenant)):
    cid = _require_customer(user)
    if body.preferred_window not in {"morning", "afternoon"}:
        raise HTTPException(400, "preferred_window must be morning or afternoon")
    try:
        datetime.fromisoformat(body.preferred_date)
    except ValueError:
        raise HTTPException(400, "preferred_date must be YYYY-MM-DD")
    cust = await db.customers.find_one(
        {"id": cid, "tenant_id": tenant["id"]}, {"_id": 0}
    ) or {}
    appt = {
        "id": new_id(),
        "tenant_id": tenant["id"],
        "customer_id": cid,
        "customer_name": cust.get("name") or user.get("name", "Customer"),
        "service_type": (body.service_type or "General Service").strip(),
        "preferred_date": body.preferred_date,
        "preferred_window": body.preferred_window,
        "address": (body.address or cust.get("address") or "").strip(),
        "notes": (body.notes or "").strip(),
        "status": "pending",
        "decided_by": None,
        "decided_at": None,
        "reject_reason": None,
        "created_job_id": None,
        "created_at": now_iso(),
    }
    await db.portal_appointments.insert_one(dict(appt))
    # WS notify admins.
    try:
        from routers.realtime import bus
        admins = await db.users.find(
            {"tenant_id": tenant["id"], "role": {"$in": ["admin", "super_admin"]}},
            {"_id": 0, "id": 1},
        ).to_list(200)
        for a in admins:
            await bus.broadcast(a["id"], {
                "type": "portal_appointment_pending",
                "payload": {"appointment_id": appt["id"],
                            "customer_name": appt["customer_name"],
                            "service_type": appt["service_type"],
                            "preferred_date": appt["preferred_date"],
                            "preferred_window": appt["preferred_window"]},
            })
    except Exception as e:
        logger.warning(f"portal_appointment WS notify failed: {e}")
    appt.pop("_id", None)
    return appt


@router.get("/portal/appointments")
async def list_appointments(user: dict = Depends(get_current_user),
                             tenant: dict = Depends(get_current_tenant)):
    """Customers see their own; admins see everything in tenant."""
    if user.get("role") == "customer":
        return await db.portal_appointments.find(
            {"tenant_id": tenant["id"], "customer_id": user["customer_id"]},
            {"_id": 0},
        ).sort("created_at", -1).to_list(500)
    if user.get("role") in ("admin", "super_admin"):
        return await db.portal_appointments.find(
            {"tenant_id": tenant["id"]}, {"_id": 0},
        ).sort("created_at", -1).to_list(1000)
    raise HTTPException(403, "Not allowed")


@router.post("/portal/appointments/{appt_id}/confirm")
async def confirm_appointment(appt_id: str,
                               user: dict = Depends(require_admin),
                               tenant: dict = Depends(get_current_tenant)):
    appt = await db.portal_appointments.find_one(
        {"id": appt_id, "tenant_id": tenant["id"]}, {"_id": 0}
    )
    if not appt:
        raise HTTPException(404, "Appointment not found")
    if appt["status"] != "pending":
        return {"ok": True, "already": appt["status"], "job_id": appt.get("created_job_id")}
    win = next((w for w in WINDOWS if w["key"] == appt["preferred_window"]), WINDOWS[0])
    sched_start = f"{appt['preferred_date']}T{win['start_hour']:02d}:00:00+00:00"
    job = {
        "id": new_id(),
        "tenant_id": tenant["id"],
        "customer_id": appt["customer_id"],
        "customer_name": appt["customer_name"],
        "title": appt["service_type"],
        "service_type": appt["service_type"],
        "job_type": appt["service_type"],
        "address": appt["address"],
        "status": "scheduled",
        "source_appointment_id": appt_id,
        "scheduled_start": sched_start,
        "scheduled_date": appt["preferred_date"],
        "notes": appt["notes"] or f"Booked via portal · {win['label']}",
        "photos": [], "price": 0.0, "billable": True,
        "created_at": now_iso(),
    }
    await db.jobs.insert_one(dict(job))
    await db.portal_appointments.update_one(
        {"id": appt_id, "tenant_id": tenant["id"]},
        {"$set": {
            "status": "confirmed",
            "decided_by": user["id"],
            "decided_at": now_iso(),
            "created_job_id": job["id"],
        }},
    )
    # Notify the customer.
    try:
        from routers.realtime import bus
        await bus.broadcast(appt["customer_id"], {
            "type": "portal_appointment_confirmed",
            "payload": {"appointment_id": appt_id, "job_id": job["id"]},
        })
    except Exception as e:
        logger.warning(f"appointment confirm WS notify failed: {e}")
    return {"ok": True, "status": "confirmed", "job_id": job["id"]}


@router.post("/portal/appointments/{appt_id}/reject")
async def reject_appointment(appt_id: str, body: RejectIn,
                              user: dict = Depends(require_admin),
                              tenant: dict = Depends(get_current_tenant)):
    if not (body.reason or "").strip():
        raise HTTPException(400, "Reason required")
    appt = await db.portal_appointments.find_one(
        {"id": appt_id, "tenant_id": tenant["id"]}, {"_id": 0}
    )
    if not appt:
        raise HTTPException(404, "Appointment not found")
    if appt["status"] != "pending":
        return {"ok": True, "already": appt["status"]}
    await db.portal_appointments.update_one(
        {"id": appt_id, "tenant_id": tenant["id"]},
        {"$set": {
            "status": "rejected",
            "decided_by": user["id"],
            "decided_at": now_iso(),
            "reject_reason": body.reason.strip(),
        }},
    )
    try:
        from routers.realtime import bus
        await bus.broadcast(appt["customer_id"], {
            "type": "portal_appointment_rejected",
            "payload": {"appointment_id": appt_id, "reason": body.reason},
        })
    except Exception as e:
        logger.warning(f"appointment reject WS notify failed: {e}")
    return {"ok": True, "status": "rejected"}
