from fastapi import APIRouter, HTTPException, Depends
from datetime import datetime, timezone, timedelta
from typing import Optional

from config import db, logger
from utils import now_iso, new_id, get_current_user, require_admin, notify_customer
from models import MaintScheduleIn, MaintSettingsIn, MaintLogIn, MaintBulkIn

router = APIRouter()

# Filter cleanings default every 90 days; salt cell cleanings every 365 days.
MAINT_TYPES = {
    "filter": {"label": "Filter Cleaning", "service_type": "Filter Cleaning", "default_interval": 90, "settings_key": "filter_interval_days"},
    "salt_cell": {"label": "Salt Cell Cleaning", "service_type": "Salt Cell Cleaning", "default_interval": 365, "settings_key": "salt_cell_interval_days"},
}
DUE_SOON_DAYS = 14
UPCOMING_STATUSES = ("requested", "pending", "active")


def _infer_type(job: dict) -> Optional[str]:
    if job.get("maintenance_type") in MAINT_TYPES:
        return job["maintenance_type"]
    st = (job.get("service_type") or "").lower()
    if "salt" in st:
        return "salt_cell"
    if "filter" in st:
        return "filter"
    return None


async def create_recurring_maintenance(completed_job: dict) -> Optional[dict]:
    """When a maintenance job is completed, schedule the next one so the pool never
    falls off the cadence. No-op if the job isn't maintenance or a future one already exists."""
    mtype = _infer_type(completed_job)
    if not mtype:
        return None
    cid = completed_job.get("customer_id")
    if not cid:
        return None
    # Don't duplicate if an upcoming cleaning of the same type is already on the books.
    existing = await db.jobs.find_one({
        "customer_id": cid, "maintenance_type": mtype,
        "status": {"$in": list(UPCOMING_STATUSES)},
    })
    if existing:
        return None
    customer = await db.customers.find_one({"id": cid}, {"_id": 0})
    if not customer:
        return None
    interval = _interval_for(customer, mtype)
    next_date = (datetime.now(timezone.utc) + timedelta(days=interval)).date().isoformat()
    cfg = MAINT_TYPES[mtype]
    job = {
        "id": new_id(), "title": cfg["label"], "customer_id": cid,
        "customer_name": completed_job.get("customer_name", customer.get("name", "")),
        "technician_id": completed_job.get("technician_id"),
        "technician_name": completed_job.get("technician_name"),
        "technician_avatar": completed_job.get("technician_avatar", ""),
        "address": customer.get("address", ""), "service_type": cfg["service_type"],
        "maintenance_type": mtype, "scheduled_date": next_date,
        "notes": "", "price": 0.0, "status": "pending", "photos": [],
        "auto_recurring": True, "created_at": now_iso(),
    }
    await db.jobs.insert_one(job)
    await notify_customer(cid, "Next service scheduled",
                          f"Your next {cfg['label'].lower()} is booked for {next_date}.", job_id=job["id"])
    return job


def _interval_for(customer: dict, mtype: str) -> int:
    key = MAINT_TYPES[mtype]["settings_key"]
    intervals = (customer or {}).get("maintenance_intervals") or {}
    val = intervals.get(key)
    return int(val) if val else MAINT_TYPES[mtype]["default_interval"]


def _status(next_due: Optional[str], has_record: bool, today: str, soon: str) -> str:
    if not has_record:
        return "never"
    if next_due and next_due < today:
        return "overdue"
    if next_due and next_due <= soon:
        return "due_soon"
    return "ok"


@router.get("/maintenance/overview")
async def maintenance_overview(admin: dict = Depends(require_admin)):
    customers = await db.customers.find({}, {"_id": 0}).sort("name", 1).to_list(1000)
    records = await db.maintenance_records.find({}, {"_id": 0}).to_list(5000)
    # Upcoming (not-yet-completed) maintenance jobs.
    up_jobs = await db.jobs.find(
        {"maintenance_type": {"$in": list(MAINT_TYPES.keys())}, "status": {"$in": list(UPCOMING_STATUSES)}},
        {"_id": 0, "id": 1, "customer_id": 1, "maintenance_type": 1, "scheduled_date": 1, "technician_name": 1, "auto_recurring": 1},
    ).to_list(2000)

    # Latest record per (customer, type)
    latest: dict = {}
    for r in records:
        key = (r.get("customer_id"), r.get("type"))
        cur = latest.get(key)
        if not cur or (r.get("date") or "") > (cur.get("date") or ""):
            latest[key] = r
    # Earliest upcoming job per (customer, type)
    upcoming: dict = {}
    for j in up_jobs:
        key = (j.get("customer_id"), j.get("maintenance_type"))
        cur = upcoming.get(key)
        if not cur or (j.get("scheduled_date") or "9999") < (cur.get("scheduled_date") or "9999"):
            upcoming[key] = j

    today = datetime.now(timezone.utc).date().isoformat()
    soon = (datetime.now(timezone.utc) + timedelta(days=DUE_SOON_DAYS)).date().isoformat()
    rank = {"overdue": 0, "due_soon": 1, "ok": 2, "never": 3}
    summary = {"overdue": 0, "due_soon": 0, "scheduled": 0, "never": 0}
    rows = []
    for c in customers:
        row = {"customer_id": c["id"], "customer_name": c.get("name", ""), "address": c.get("address", "")}
        worst = 3
        for mtype, cfg in MAINT_TYPES.items():
            rec = latest.get((c["id"], mtype))
            interval = _interval_for(c, mtype)
            last_date = rec.get("date") if rec else None
            next_due = None
            if last_date:
                try:
                    next_due = (datetime.fromisoformat(last_date[:10]) + timedelta(days=interval)).date().isoformat()
                except Exception:
                    next_due = None
            status = _status(next_due, bool(rec), today, soon)
            up = upcoming.get((c["id"], mtype))
            row[mtype] = {
                "label": cfg["label"],
                "last_date": last_date,
                "last_photos": len(rec.get("photos", [])) if rec else 0,
                "interval_days": interval,
                "next_due": next_due,
                "status": status,
                "upcoming_job": {
                    "id": up["id"], "scheduled_date": up.get("scheduled_date"),
                    "technician_name": up.get("technician_name"),
                    "auto_recurring": bool(up.get("auto_recurring")),
                } if up else None,
            }
            if up:
                summary["scheduled"] += 1
            if status in summary:
                summary[status] += 1
            worst = min(worst, rank.get(status, 3))
        row["_worst"] = worst
        rows.append(row)
    rows.sort(key=lambda r: (r.pop("_worst"), r["customer_name"]))
    return {"summary": summary, "rows": rows}


async def _compute_digest():
    customers = await db.customers.find({}, {"_id": 0, "id": 1, "name": 1, "address": 1}).to_list(1000)
    records = await db.maintenance_records.find({}, {"_id": 0}).to_list(5000)
    up_jobs = await db.jobs.find(
        {"maintenance_type": {"$in": list(MAINT_TYPES.keys())}, "status": {"$in": list(UPCOMING_STATUSES)}},
        {"_id": 0, "customer_id": 1, "maintenance_type": 1},
    ).to_list(2000)
    cmap = {c["id"]: c for c in customers}
    latest: dict = {}
    for r in records:
        key = (r.get("customer_id"), r.get("type"))
        cur = latest.get(key)
        if not cur or (r.get("date") or "") > (cur.get("date") or ""):
            latest[key] = r
    scheduled = {(j["customer_id"], j["maintenance_type"]) for j in up_jobs}

    today_d = datetime.now(timezone.utc).date()
    today = today_d.isoformat()
    week = (today_d + timedelta(days=7)).isoformat()
    items = []
    overdue_ct, due_ct = 0, 0
    for (cid, mtype), rec in latest.items():
        customer = cmap.get(cid)
        if not customer or (cid, mtype) in scheduled:
            continue  # already booked — no action needed
        interval = _interval_for(customer, mtype)
        try:
            next_due = (datetime.fromisoformat(rec["date"][:10]) + timedelta(days=interval)).date()
        except Exception:
            continue
        nd = next_due.isoformat()
        is_overdue = nd < today
        is_due = today <= nd <= week
        if not (is_overdue or is_due):
            continue
        items.append({
            "customer_id": cid, "customer_name": customer.get("name", ""),
            "type": mtype, "label": MAINT_TYPES[mtype]["label"],
            "next_due": nd, "overdue": is_overdue, "days": (next_due - today_d).days,
        })
        if is_overdue:
            overdue_ct += 1
        else:
            due_ct += 1
    items.sort(key=lambda x: (not x["overdue"], x["next_due"]))
    return overdue_ct, due_ct, items


@router.get("/maintenance/digest")
async def maintenance_digest(admin: dict = Depends(require_admin)):
    """Lightweight weekly digest: filter/salt cleanings that are overdue or due within
    the next 7 days and not already scheduled — for an at-a-glance dashboard review."""
    overdue_ct, due_ct, items = await _compute_digest()
    return {"overdue": overdue_ct, "due_this_week": due_ct, "items": items[:6]}


@router.post("/maintenance/bulk-schedule")
async def maintenance_bulk_schedule(body: MaintBulkIn, admin: dict = Depends(require_admin)):
    """One-tap: book every overdue / due-this-week pool onto a chosen date & technician."""
    try:
        datetime.fromisoformat(body.scheduled_date[:10])
    except (ValueError, TypeError):
        raise HTTPException(400, "scheduled_date must be YYYY-MM-DD")
    _, _, items = await _compute_digest()
    if not items:
        return {"created": 0, "jobs": []}
    tech_name, tech_avatar = None, ""
    if body.technician_id:
        tech = await db.technicians.find_one({"id": body.technician_id}, {"_id": 0})
        tech_name = tech["name"] if tech else None
        tech_avatar = tech.get("avatar", "") if tech else ""
    created = []
    for it in items:
        customer = await db.customers.find_one({"id": it["customer_id"]}, {"_id": 0})
        if not customer:
            continue
        cfg = MAINT_TYPES[it["type"]]
        job = {
            "id": new_id(), "title": cfg["label"], "customer_id": it["customer_id"],
            "customer_name": it["customer_name"], "technician_id": body.technician_id,
            "technician_name": tech_name, "technician_avatar": tech_avatar,
            "address": customer.get("address", ""), "service_type": cfg["service_type"],
            "maintenance_type": it["type"], "scheduled_date": body.scheduled_date,
            "notes": "", "price": 0.0, "status": "pending", "photos": [], "created_at": now_iso(),
        }
        await db.jobs.insert_one(job)
        await notify_customer(it["customer_id"], "Service scheduled",
                              f"Your {cfg['label'].lower()} is scheduled for {body.scheduled_date}.", job_id=job["id"])
        created.append(it["customer_id"])
    return {"created": len(created)}


@router.get("/maintenance/records")
async def maintenance_records(customer_id: str, type: Optional[str] = None, user: dict = Depends(get_current_user)):
    if user.get("role") not in ("admin", "technician"):
        raise HTTPException(403, "Not allowed")
    q = {"customer_id": customer_id}
    if type:
        q["type"] = type
    recs = await db.maintenance_records.find(q, {"_id": 0}).sort("date", -1).to_list(500)
    return recs


@router.post("/maintenance/schedule")
async def maintenance_schedule(body: MaintScheduleIn, admin: dict = Depends(require_admin)):
    if body.type not in MAINT_TYPES:
        raise HTTPException(400, "Invalid maintenance type")
    try:
        datetime.fromisoformat(body.scheduled_date[:10])
    except (ValueError, TypeError):
        raise HTTPException(400, "scheduled_date must be YYYY-MM-DD")
    customer = await db.customers.find_one({"id": body.customer_id}, {"_id": 0})
    if not customer:
        raise HTTPException(404, "Customer not found")
    cfg = MAINT_TYPES[body.type]
    tech_name, tech_avatar = None, ""
    if body.technician_id:
        tech = await db.technicians.find_one({"id": body.technician_id}, {"_id": 0})
        tech_name = tech["name"] if tech else None
        tech_avatar = tech.get("avatar", "") if tech else ""
    job = {
        "id": new_id(), "title": cfg["label"], "customer_id": customer["id"],
        "customer_name": customer["name"], "technician_id": body.technician_id,
        "technician_name": tech_name, "technician_avatar": tech_avatar,
        "address": customer.get("address", ""), "service_type": cfg["service_type"],
        "maintenance_type": body.type, "scheduled_date": body.scheduled_date,
        "notes": "", "price": 0.0, "status": "pending", "photos": [], "created_at": now_iso(),
    }
    await db.jobs.insert_one(job)
    job.pop("_id", None)
    # Optionally update this pool's cadence.
    if body.interval_days and body.interval_days > 0:
        await db.customers.update_one(
            {"id": customer["id"]},
            {"$set": {f"maintenance_intervals.{cfg['settings_key']}": int(body.interval_days)}},
        )
    await notify_customer(customer["id"], "Service scheduled",
                          f"Your {cfg['label'].lower()} is scheduled for {body.scheduled_date}.", job_id=job["id"])
    return job


@router.put("/maintenance/settings/{customer_id}")
async def maintenance_settings(customer_id: str, body: MaintSettingsIn, admin: dict = Depends(require_admin)):
    cust = await db.customers.find_one({"id": customer_id}, {"_id": 0})
    if not cust:
        raise HTTPException(404, "Customer not found")
    upd = {}
    if body.filter_interval_days and body.filter_interval_days > 0:
        upd["maintenance_intervals.filter_interval_days"] = int(body.filter_interval_days)
    if body.salt_cell_interval_days and body.salt_cell_interval_days > 0:
        upd["maintenance_intervals.salt_cell_interval_days"] = int(body.salt_cell_interval_days)
    if upd:
        await db.customers.update_one({"id": customer_id}, {"$set": upd})
    return await db.customers.find_one({"id": customer_id}, {"_id": 0})


@router.post("/jobs/{jid}/maintenance-log")
async def log_maintenance(jid: str, body: MaintLogIn, user: dict = Depends(get_current_user)):
    from routers.jobs import with_field_report
    if user.get("role") == "customer":
        raise HTTPException(403, "Not allowed")
    job = await db.jobs.find_one({"id": jid})
    if not job:
        raise HTTPException(404, "Job not found")
    if user.get("role") == "technician" and job.get("technician_id") != user.get("technician_id"):
        raise HTTPException(403, "Not your job")
    mtype = _infer_type(job)
    if not mtype:
        raise HTTPException(400, "This job is not a filter or salt cell maintenance job")
    date = (job.get("scheduled_date") or now_iso())[:10]
    fields = {k: v for k, v in body.dict().items() if v is not None and k != "photos"}
    photos = []
    for p in (body.photos or []):
        if p.get("data"):
            photos.append({"id": new_id(), "label": p.get("label", "photo"), "data": p["data"]})
    record = {
        "customer_id": job.get("customer_id"), "customer_name": job.get("customer_name", ""),
        "type": mtype, "date": date, "job_id": jid,
        "technician_id": job.get("technician_id"), "technician_name": job.get("technician_name"),
        "psi": body.psi, "filter_condition": body.filter_condition,
        "salt_ppm": body.salt_ppm, "cell_condition": body.cell_condition,
        "notes": body.notes, "photos": photos, "updated_at": now_iso(),
    }
    await db.maintenance_records.update_one(
        {"job_id": jid},
        {"$set": record, "$setOnInsert": {"id": new_id(), "created_at": now_iso()}},
        upsert=True,
    )
    job_maint = dict(fields)
    job_maint["photos"] = photos
    job_maint["logged_at"] = now_iso()
    await db.jobs.update_one({"id": jid}, {"$set": {"maintenance": job_maint, "maintenance_logged": True, "maintenance_type": mtype}})
    return with_field_report(await db.jobs.find_one({"id": jid}, {"_id": 0}))
