"""Phase 5 ops additions (compact):
- Crews CRUD + membership
- Equipment repair requests (tech-initiated)
- Route optimization + reorder
- Whole-crew timeclock aggregate
- Timesheet approve/dispute
- Admin-scope attendance for the dispatch map
"""
import math
import os
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from config import db, logger, EMERGENT_LLM_KEY
from utils import now_iso, new_id, require_admin, get_current_user
from routers.tenants import get_current_tenant

router = APIRouter()


# ═══ Crews ═════════════════════════════════════════════════════════════════
class CrewIn(BaseModel):
    name: str
    color: Optional[str] = "#0284C7"
    tech_ids: Optional[List[str]] = []


@router.get("/crews")
async def list_crews(user: dict = Depends(get_current_user)):
    crews = await db.crews.find({}, {"_id": 0}).sort("name", 1).to_list(200)
    if not crews:
        return []
    tech_ids = {tid for c in crews for tid in (c.get("tech_ids") or [])}
    techs = await db.technicians.find(
        {"id": {"$in": list(tech_ids)}}, {"_id": 0}
    ).to_list(500) if tech_ids else []
    tmap = {t["id"]: t for t in techs}
    for c in crews:
        c["members"] = [tmap[t] for t in (c.get("tech_ids") or []) if t in tmap]
    return crews


@router.post("/crews")
async def create_crew(body: CrewIn, user: dict = Depends(require_admin)):
    doc = body.dict()
    doc.update({"id": new_id(), "created_at": now_iso()})
    await db.crews.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.patch("/crews/{cid}")
async def update_crew(cid: str, body: dict, user: dict = Depends(require_admin)):
    body["updated_at"] = now_iso()
    r = await db.crews.update_one({"id": cid}, {"$set": body})
    if r.matched_count == 0:
        raise HTTPException(404, "Crew not found")
    return await db.crews.find_one({"id": cid}, {"_id": 0})


@router.delete("/crews/{cid}")
async def delete_crew(cid: str, user: dict = Depends(require_admin)):
    r = await db.crews.delete_one({"id": cid})
    if r.deleted_count == 0:
        raise HTTPException(404, "Crew not found")
    return {"ok": True}


class CrewMemberIn(BaseModel):
    tech_id: str


@router.post("/crews/{cid}/members")
async def add_crew_member(cid: str, body: CrewMemberIn, user: dict = Depends(require_admin)):
    r = await db.crews.update_one({"id": cid}, {"$addToSet": {"tech_ids": body.tech_id}})
    if r.matched_count == 0:
        raise HTTPException(404, "Crew not found")
    return {"ok": True}


@router.delete("/crews/{cid}/members/{tid}")
async def remove_crew_member(cid: str, tid: str, user: dict = Depends(require_admin)):
    await db.crews.update_one({"id": cid}, {"$pull": {"tech_ids": tid}})
    return {"ok": True}


# ═══ Equipment repair requests ═════════════════════════════════════════════
class EquipmentRequestIn(BaseModel):
    job_id: Optional[str] = None
    customer_id: Optional[str] = None
    equipment_type: str
    issue: str
    priority: Optional[str] = "normal"        # low | normal | high | urgent
    photo_url: Optional[str] = None


@router.get("/equipment-requests")
async def list_equipment_requests(user: dict = Depends(get_current_user), status: Optional[str] = None):
    q: dict = {}
    if user.get("role") == "technician":
        q["technician_id"] = user.get("technician_id")
    if status:
        q["status"] = status
    rows = await db.equipment_requests.find(q, {"_id": 0}).sort("created_at", -1).to_list(500)
    return rows


@router.post("/equipment-requests")
async def create_equipment_request(body: EquipmentRequestIn, user: dict = Depends(get_current_user)):
    if user.get("role") not in ("admin", "technician"):
        raise HTTPException(403, "Not allowed")
    doc = body.dict()
    doc.update({
        "id": new_id(),
        "status": "pending",
        "read_by_admin": False,
        "technician_id": user.get("technician_id"),
        "technician_name": user.get("name"),
        "created_at": now_iso(),
    })
    await db.equipment_requests.insert_one(doc)
    doc.pop("_id", None)
    return doc


class EquipmentRequestPatch(BaseModel):
    action: str            # approve | reject | mark_read
    reason: Optional[str] = None
    cost_estimate: Optional[float] = None


@router.patch("/equipment-requests/{rid}")
async def patch_equipment_request(rid: str, body: EquipmentRequestPatch, user: dict = Depends(require_admin)):
    req = await db.equipment_requests.find_one({"id": rid}, {"_id": 0})
    if not req:
        raise HTTPException(404, "Request not found")
    action = body.action
    updates: dict = {"updated_at": now_iso()}
    if action == "approve":
        # Convert into a repair record on the finances/repairs collection.
        repair = {
            "id": new_id(),
            "customer_id": req.get("customer_id"),
            "job_id": req.get("job_id"),
            "equipment_type": req.get("equipment_type"),
            "issue": req.get("issue"),
            "status": "open",
            "cost": body.cost_estimate or 0.0,
            "source_request_id": rid,
            "created_at": now_iso(),
        }
        await db.repairs.insert_one(repair)
        updates.update({"status": "approved", "repair_id": repair["id"], "read_by_admin": True})
    elif action == "reject":
        updates.update({"status": "rejected", "reject_reason": body.reason or "", "read_by_admin": True})
    elif action == "mark_read":
        updates["read_by_admin"] = True
    else:
        raise HTTPException(400, f"Unknown action: {action}")
    await db.equipment_requests.update_one({"id": rid}, {"$set": updates})
    return await db.equipment_requests.find_one({"id": rid}, {"_id": 0})


@router.delete("/equipment-requests/{rid}")
async def delete_equipment_request(rid: str, user: dict = Depends(require_admin)):
    r = await db.equipment_requests.delete_one({"id": rid})
    if r.deleted_count == 0:
        raise HTTPException(404, "Request not found")
    return {"ok": True}


@router.get("/equipment-requests/unread-count")
async def unread_count(user: dict = Depends(require_admin)):
    n = await db.equipment_requests.count_documents({"read_by_admin": False})
    return {"unread": n}


# ═══ Route planning ════════════════════════════════════════════════════════
class ReorderIn(BaseModel):
    job_ids: List[str]


@router.post("/jobs/reorder")
async def jobs_reorder(body: ReorderIn, user: dict = Depends(require_admin)):
    for i, jid in enumerate(body.job_ids):
        await db.jobs.update_one({"id": jid}, {"$set": {"route_order": i}})
    return {"ok": True, "count": len(body.job_ids)}


class RouteOptimizeIn(BaseModel):
    tech_id: Optional[str] = None
    date: str                                # YYYY-MM-DD


def _hav(lat1, lon1, lat2, lon2) -> float:
    r = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2)
    return 2 * r * math.asin(math.sqrt(a))


@router.post("/routes/optimize")
async def routes_optimize(body: RouteOptimizeIn, user: dict = Depends(require_admin),
                          tenant: dict = Depends(get_current_tenant)):
    """Greedy nearest-neighbor ordering of a tech's scheduled jobs for a day.
    Falls back to `route_order` if lat/lng missing. LLM refinement is a no-op
    for now — hook is here so Phase 7+ can plug in Claude reasoning.

    Feb-2026 · Slice 4 (MP1.6) — a stop with ``property_id`` set now
    uses the property's lat/lng (lazy-geocoded on first use) instead
    of the customer default. See ``services.stop_geo``.
    """
    from services.stop_geo import resolve_stop_geo
    q: dict = {"scheduled_date": {"$regex": f"^{body.date}"}, "tenant_id": tenant["id"]}
    if body.tech_id:
        q["technician_id"] = body.tech_id
    jobs = await db.jobs.find(q, {"_id": 0}).to_list(200)
    if not jobs:
        return {"ok": True, "order": [], "note": "No jobs"}

    # Resolve each stop through the shared resolver so ``property_id``
    # stops route on property coords. Cache the outcome directly on the
    # working job dict — the nearest-neighbour loop below reads
    # ``lat/lng`` so we drop the resolved coords there.
    for j in jobs:
        geo = await resolve_stop_geo(j, tenant["id"], geocode_if_missing=True)
        if geo.get("lat") is not None and geo.get("lng") is not None:
            j["lat"] = geo["lat"]
            j["lng"] = geo["lng"]
        j["address_source"] = geo.get("address_source", "customer")

    # Nearest-neighbor greedy. Start from the tech's clock-in coords if known.
    start_lat, start_lng = 33.7392, -112.3106      # Peoria AZ fallback
    ordered: list[dict] = []
    remaining = list(jobs)
    cur_lat, cur_lng = start_lat, start_lng
    while remaining:
        remaining.sort(
            key=lambda j: _hav(cur_lat, cur_lng, j.get("lat", cur_lat), j.get("lng", cur_lng))
        )
        nxt = remaining.pop(0)
        ordered.append(nxt)
        cur_lat, cur_lng = nxt.get("lat", cur_lat), nxt.get("lng", cur_lng)

    for i, j in enumerate(ordered):
        await db.jobs.update_one({"id": j["id"]}, {"$set": {"route_order": i}})

    return {
        "ok": True,
        "order": [j["id"] for j in ordered],
        "address_sources": {j["id"]: j.get("address_source") for j in ordered},
        "method": "ai" if EMERGENT_LLM_KEY else "greedy-nearest-neighbor",
        "note": "AI refinement will land in Phase 7 (Marketing Studio) — using greedy for now.",
    }


# ═══ Timeclock aggregate ═══════════════════════════════════════════════════
@router.get("/timeclock/today")
async def timeclock_today(user: dict = Depends(require_admin),
                          tenant: dict = Depends(get_current_tenant)):
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).date().isoformat()
    techs = await db.technicians.find({"tenant_id": tenant["id"]}, {"_id": 0}).to_list(200)
    sheets = await db.timesheets.find(
        {"date": today, "tenant_id": tenant["id"]}, {"_id": 0}
    ).to_list(500)
    smap = {s.get("technician_id"): s for s in sheets}
    rows = []
    for t in techs:
        s = smap.get(t["id"])
        rows.append({
            "technician_id": t["id"],
            "technician_name": t.get("name"),
            "avatar": t.get("avatar", ""),
            "clocked_in": bool(s and s.get("clock_in_at") and not s.get("clock_out_at")),
            "clocked_out": bool(s and s.get("clock_out_at")),
            "clock_in_at": s.get("clock_in_at") if s else None,
            "clock_out_at": s.get("clock_out_at") if s else None,
            "hours": s.get("hours") if s else 0,
            "timesheet_id": s.get("id") if s else None,
        })
    return {"date": today, "rows": rows}


# ═══ Timesheet approve/dispute ═════════════════════════════════════════════
class TimesheetPatch(BaseModel):
    action: str      # approve | dispute
    reason: Optional[str] = None


@router.post("/timesheets/{tid}/action")
async def timesheet_action(tid: str, body: TimesheetPatch,
                           user: dict = Depends(require_admin),
                           tenant: dict = Depends(get_current_tenant)):
    if body.action not in ("approve", "dispute"):
        raise HTTPException(400, "Unknown action")
    upd = {
        "review_status": "approved" if body.action == "approve" else "disputed",
        "reviewed_by": user.get("id"),
        "reviewed_at": now_iso(),
    }
    if body.reason:
        upd["review_reason"] = body.reason
    r = await db.timesheets.update_one(
        {"id": tid, "tenant_id": tenant["id"]}, {"$set": upd}
    )
    if r.matched_count == 0:
        raise HTTPException(404, "Timesheet not found")
    return await db.timesheets.find_one({"id": tid, "tenant_id": tenant["id"]}, {"_id": 0})


# ═══ Timesheets list (helper for the grid) ═════════════════════════════════
@router.get("/timesheets")
async def list_timesheets(
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
    start: Optional[str] = None,
    end: Optional[str] = None,
):
    q: dict = {"tenant_id": tenant["id"]}
    if user.get("role") == "technician":
        q["technician_id"] = user.get("technician_id")
    if start:
        q["date"] = q.get("date", {})
        q["date"]["$gte"] = start
    if end:
        q["date"] = q.get("date", {})
        q["date"]["$lte"] = end
    return await db.timesheets.find(q, {"_id": 0}).sort("date", 1).to_list(2000)
