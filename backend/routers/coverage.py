from fastapi import APIRouter, HTTPException, Depends
from datetime import datetime, timezone, date, timedelta

from config import db, logger
from utils import now_iso, new_id, require_admin, notify_technician
from models import CoverageIn

router = APIRouter()


def _saturday_of(d: date) -> date:
    """The Saturday ending d's week (Sat=5)."""
    return d + timedelta(days=(5 - d.weekday()) % 7)


def _fmt(d: str) -> str:
    try:
        return datetime.fromisoformat(d).strftime("%a %b %-d")
    except Exception:
        return d


async def _revert_coverage(cov: dict) -> int:
    """Restore original technician on any covered job still not completed. Returns count reverted."""
    reverted = 0
    for jid in cov.get("job_ids", []):
        job = await db.jobs.find_one({"id": jid}, {"_id": 0})
        if not job:
            continue
        # Only revert if it's still on the substitute and not completed.
        if job.get("status") == "completed":
            continue
        if job.get("technician_id") != cov["target_technician_id"]:
            continue
        await db.jobs.update_one({"id": jid}, {"$set": {
            "technician_id": cov["source_technician_id"],
            "technician_name": cov.get("source_technician_name"),
        }, "$unset": {"covered_by": "", "original_technician_id": "", "coverage_id": ""}})
        reverted += 1
    await db.route_coverage.update_one({"id": cov["id"]}, {"$set": {
        "active": False, "reverted_at": now_iso(), "reverted_count": reverted,
    }})
    return reverted


@router.post("/coverage")
async def create_coverage(body: CoverageIn, admin: dict = Depends(require_admin)):
    if body.source_technician_id == body.target_technician_id:
        raise HTTPException(400, "Choose a different technician to cover the route.")
    src = await db.technicians.find_one({"id": body.source_technician_id}, {"_id": 0})
    tgt = await db.technicians.find_one({"id": body.target_technician_id}, {"_id": 0})
    if not src or not tgt:
        raise HTTPException(404, "Technician not found")

    scope = body.scope if body.scope in ("day", "week") else "day"
    anchor_str = body.date or datetime.now(timezone.utc).date().isoformat()
    try:
        anchor = datetime.fromisoformat(anchor_str[:10]).date()
    except ValueError:
        raise HTTPException(400, "date must be YYYY-MM-DD")

    week_end = _saturday_of(anchor)
    if scope == "day":
        date_filter = {"scheduled_date": anchor.isoformat()}
        label = _fmt(anchor.isoformat())
    else:
        date_filter = {"scheduled_date": {"$gte": anchor.isoformat(), "$lte": week_end.isoformat()}}
        label = f"{_fmt(anchor.isoformat())}–{_fmt(week_end.isoformat())}"

    query = {"technician_id": body.source_technician_id, "status": {"$ne": "completed"}, **date_filter}
    jobs = await db.jobs.find(query, {"_id": 0}).to_list(1000)
    if not jobs:
        raise HTTPException(400, f"{src['name']} has no open stops to move for {label}.")

    cov_id = new_id()
    job_ids = [j["id"] for j in jobs]
    for j in jobs:
        upd = {"technician_id": body.target_technician_id, "technician_name": tgt["name"],
               "covered_by": body.target_technician_id, "coverage_id": cov_id}
        # Preserve the true original owner (in case a job was already covered).
        if not j.get("original_technician_id"):
            upd["original_technician_id"] = body.source_technician_id
        await db.jobs.update_one({"id": j["id"]}, {"$set": upd})

    cov = {
        "id": cov_id, "scope": scope, "date": anchor.isoformat(), "week_end": week_end.isoformat(),
        "source_technician_id": body.source_technician_id, "source_technician_name": src["name"],
        "target_technician_id": body.target_technician_id, "target_technician_name": tgt["name"],
        "job_ids": job_ids, "job_count": len(job_ids), "label": label,
        "active": True, "created_at": now_iso(), "created_by": admin["id"],
    }
    await db.route_coverage.insert_one(cov)
    cov.pop("_id", None)

    await notify_technician(body.target_technician_id, "Route coverage assigned",
                            f"You're covering {len(job_ids)} stop(s) for {src['name']} ({label}). Reverts after Sat {_fmt(week_end.isoformat())}.")
    await notify_technician(body.source_technician_id, "Route temporarily reassigned",
                            f"Your {label} route ({len(job_ids)} stop(s)) is covered by {tgt['name']} this week.")
    return cov


@router.get("/coverage/active")
async def list_active_coverage(admin: dict = Depends(require_admin)):
    return await db.route_coverage.find({"active": True}, {"_id": 0}).sort("created_at", -1).to_list(200)


@router.post("/coverage/{cid}/revert")
async def revert_coverage(cid: str, admin: dict = Depends(require_admin)):
    cov = await db.route_coverage.find_one({"id": cid}, {"_id": 0})
    if not cov:
        raise HTTPException(404, "Coverage not found")
    if not cov.get("active"):
        raise HTTPException(400, "This coverage is already reverted")
    n = await _revert_coverage(cov)
    await notify_technician(cov["source_technician_id"], "Route restored",
                            f"Your {cov.get('label', '')} route is back with you ({n} stop(s)).")
    await notify_technician(cov["target_technician_id"], "Coverage ended",
                            f"{cov.get('source_technician_name', '')}'s {cov.get('label', '')} route was returned.")
    return {"ok": True, "reverted": n}


async def revert_expired_coverage():
    """Auto-revert any active coverage whose week (ending Saturday) has passed. Runs daily."""
    today = datetime.now(timezone.utc).date().isoformat()
    expired = await db.route_coverage.find({"active": True, "week_end": {"$lt": today}}, {"_id": 0}).to_list(500)
    for cov in expired:
        n = await _revert_coverage(cov)
        await notify_technician(cov["source_technician_id"], "Route restored",
                                f"Your {cov.get('label', '')} route is back with you for the new week.")
        logger.info(f"Auto-reverted coverage {cov['id']} ({n} jobs) to {cov.get('source_technician_name')}")
    if expired:
        logger.info(f"Coverage auto-revert: {len(expired)} coverage(s) restored")
