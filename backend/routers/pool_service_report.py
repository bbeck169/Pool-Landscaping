"""Phase 45 · Task 4 — Pool Service Report.

`GET /api/reports/pool-service?week_start=YYYY-MM-DD`

For the calendar week beginning at `week_start` (Monday-anchored to
match existing schedule conventions), returns per-pool-tech counts of:
    pools_serviced  — jobs with status in {completed, closed}, service
                      type "pool", assigned to this tech, this week.
    skipped         — jobs with status == "skipped" (surface separately;
                      NOT counted in pools_serviced per spec).

RBAC: admin / super_admin only.
"""
from datetime import datetime, timedelta, timezone, date
from fastapi import APIRouter, HTTPException, Depends, Query
from config import db
from utils import get_current_user

router = APIRouter(prefix="/reports", tags=["reports"])


def _monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


@router.get("/pool-service")
async def pool_service(
    week_start: str = Query(...),
    user: dict = Depends(get_current_user),
):
    role = (user.get("role") or "").lower()
    if role not in ("admin", "super_admin"):
        raise HTTPException(403, detail="admin_only")
    try:
        start = date.fromisoformat(week_start)
    except ValueError:
        raise HTTPException(400, detail="week_start must be YYYY-MM-DD")
    # Snap to Monday of that week.
    start = _monday(start)
    end = start + timedelta(days=7)
    start_iso = f"{start.isoformat()}T00:00:00+00:00"
    end_iso = f"{end.isoformat()}T00:00:00+00:00"

    tenant_id = user["tenant_id"]
    jobs = await db.jobs.find({
        "tenant_id": tenant_id,
        "service_type": "pool",
        "scheduled_at": {"$gte": start_iso, "$lt": end_iso},
    }, {"_id": 0}).to_list(5000)

    by_tech: dict = {}
    for j in jobs:
        tid = j.get("technician_id") or "_unassigned"
        row = by_tech.setdefault(tid, {"tech_id": tid, "pools_serviced": 0, "skipped": 0})
        status = (j.get("status") or "").lower()
        if status in ("completed", "closed"):
            row["pools_serviced"] += 1
        elif status == "skipped":
            row["skipped"] += 1

    # Attach tech display names.
    tech_ids = [k for k in by_tech.keys() if k != "_unassigned"]
    if tech_ids:
        techs = await db.users.find(
            {"id": {"$in": tech_ids}, "tenant_id": tenant_id},
            {"_id": 0, "id": 1, "name": 1, "full_name": 1, "email": 1},
        ).to_list(len(tech_ids))
        name_by_id = {t["id"]: (t.get("full_name") or t.get("name") or t.get("email") or t["id"]) for t in techs}
    else:
        name_by_id = {}
    for tid, row in by_tech.items():
        row["tech_name"] = "Unassigned" if tid == "_unassigned" else name_by_id.get(tid, tid)

    rows = sorted(by_tech.values(), key=lambda r: (-r["pools_serviced"], r["tech_name"]))
    return {"week_start": start.isoformat(), "week_end": (end - timedelta(days=1)).isoformat(),
            "rows": rows}
