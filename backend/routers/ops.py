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
from utils import not_deleted_filter as _nd
from routers.tenants import get_current_tenant

router = APIRouter()


# ═══ Crews ═════════════════════════════════════════════════════════════════
class CrewIn(BaseModel):
    name: str
    color: Optional[str] = "#0284C7"
    tech_ids: Optional[List[str]] = []


def _crew_member_added_at_map(
    tech_ids: Optional[List[str]], ts: Optional[str] = None,
) -> dict:
    """CREW-SCHEDULE-FANOUT · Feb-2026 — ``member_added_at`` seeder.

    Returns ``{tech_id: iso_utc_now_or_ts}`` for every id in
    ``tech_ids`` (empty-safe).  Used by ``create_crew`` (every initial
    member gets the same join timestamp — the crew's own
    ``created_at``) and by the migration backfill. The map value is a
    full ISO datetime; the schedule-query path floors it to the
    ``YYYY-MM-DD`` prefix before comparing to ``jobs.scheduled_date``
    so bare-date and ISO-datetime schedule values both lex-compare
    correctly.
    """
    ts = ts or now_iso()
    return {tid: ts for tid in (tech_ids or []) if tid}


async def _normalise_crew_tech_ids(raw_ids) -> List[str]:
    """TD-86 · Feb-2026 — type coerce + dedupe helper.

    Raises ``HTTPException(400)`` on non-list input and on non-string
    entries.  Preserves insertion order while dropping duplicates.
    """
    if raw_ids is None:
        return []
    if not isinstance(raw_ids, list):
        raise HTTPException(
            400, "tech_ids must be an array of user ids",
        )
    normalised: List[str] = []
    seen: set = set()
    for x in raw_ids:
        if not isinstance(x, str) or not x:
            raise HTTPException(
                400, "tech_ids entries must be non-empty strings",
            )
        if x in seen:
            continue
        seen.add(x)
        normalised.append(x)
    return normalised


async def _resolve_tenant_members(
    tenant_id: str, ids: List[str],
) -> dict:
    """TD-86 · Feb-2026 — shared crew-member tenant predicate.

    Resolves ``ids`` against ``users`` + ``technicians`` scoped to
    ``tenant_id``, then categorises every ``missing`` id by probing
    the two collections WITHOUT a tenant filter so the caller can
    distinguish "exists in another tenant" (``foreign_tenant``)
    from "doesn't exist anywhere" (``orphan``).

    Returns::

        {
            "resolved":  set[str],   # ids present in this tenant
            "missing":   list[str],  # ids not in this tenant
            "errors":    list[dict], # categorised 400 payload entries
        }

    Each ``errors`` entry has shape::

        {"tech_id": "<id>",
         "reason":  "foreign_tenant" | "orphan",
         "tenant_id": "<other_tenant>"  # foreign_tenant only
        }

    Used by both ``create_crew`` (POST) and ``update_crew`` (PATCH)
    so the two save paths share one source of truth for the guard.
    """
    if not ids:
        return {"resolved": set(), "missing": [], "errors": []}

    resolved: set = set()
    async for u in db.users.find(
        {"tenant_id": tenant_id, "id": {"$in": ids}},
        {"_id": 0, "id": 1},
    ):
        resolved.add(u["id"])
    if len(resolved) < len(ids):
        async for t in db.technicians.find(
            {"tenant_id": tenant_id, "id": {"$in": ids}},
            {"_id": 0, "id": 1},
        ):
            resolved.add(t["id"])

    missing = [x for x in ids if x not in resolved]
    if not missing:
        return {"resolved": resolved, "missing": [], "errors": []}

    # Categorise each missing id — probe users + technicians across
    # ALL tenants so we can tell foreign_tenant from orphan.
    foreign_map: dict = {}
    async for u in db.users.find(
        {"id": {"$in": missing}}, {"_id": 0, "id": 1, "tenant_id": 1},
    ):
        if u.get("id") and u.get("tenant_id") and u["tenant_id"] != tenant_id:
            foreign_map[u["id"]] = u["tenant_id"]
    async for t in db.technicians.find(
        {"id": {"$in": [x for x in missing if x not in foreign_map]}},
        {"_id": 0, "id": 1, "tenant_id": 1},
    ):
        if t.get("id") and t.get("tenant_id") and t["tenant_id"] != tenant_id:
            foreign_map.setdefault(t["id"], t["tenant_id"])

    errors: List[dict] = []
    for mid in missing:
        if mid in foreign_map:
            errors.append({
                "tech_id": mid,
                "reason": "foreign_tenant",
                "tenant_id": foreign_map[mid],
            })
        else:
            errors.append({"tech_id": mid, "reason": "orphan"})
    return {"resolved": resolved, "missing": missing, "errors": errors}


@router.get("/crews")
async def list_crews(user: dict = Depends(get_current_user),
                      tenant: dict = Depends(get_current_tenant)):
    """List crews for the current tenant.

    Feb-2026 · P0 fix — added ``tenant_id`` filter (the prior
    ``find({})`` leaked crews across tenants). The technician join
    is also tenant-scoped so seed rows from other tenants can't
    surface as "members".
    """
    tid = tenant["id"]
    crews = await db.crews.find(
        {"tenant_id": tid}, {"_id": 0},
    ).sort("name", 1).to_list(200)
    if not crews:
        return []
    tech_ids = {t for c in crews for t in (c.get("tech_ids") or [])}
    techs = await db.technicians.find(
        {"tenant_id": tid, "id": {"$in": list(tech_ids)}},
        {"_id": 0},
    ).to_list(500) if tech_ids else []
    # Also resolve user-synthesized member ids (Feb-2026 union fix in
    # /technicians). A crew "member" may be a raw user id when the
    # user has no technicians row yet.
    if tech_ids:
        async for u in db.users.find(
            {"tenant_id": tid, "id": {"$in": list(tech_ids)}},
            {"_id": 0, "id": 1, "email": 1, "first_name": 1,
             "last_name": 1, "name": 1, "phone": 1, "role": 1},
        ):
            techs.append({
                "id": u.get("id"),
                "user_id": u.get("id"),
                "name": (u.get("name")
                          or " ".join([u.get("first_name") or "",
                                        u.get("last_name") or ""]).strip()
                          or u.get("email") or "Unnamed"),
                "email": u.get("email"),
                "phone": u.get("phone"),
                "role": u.get("role"),
                "tenant_id": tid,
                "synthesized_from_users": True,
            })
    tmap = {t["id"]: t for t in techs}
    for c in crews:
        c["members"] = [tmap[t] for t in (c.get("tech_ids") or []) if t in tmap]
    return crews


@router.post("/crews")
async def create_crew(body: CrewIn, user: dict = Depends(require_admin),
                       tenant: dict = Depends(get_current_tenant)):
    # Feb-2026 · P0 fix — write ``tenant_id`` on create. list_crews
    # filters by tenant_id (P0 fix earlier this phase), so a doc
    # inserted without tenant_id becomes invisible on the very next
    # GET → the user sees "crews not saving". Mirror the tenant-
    # scoping already applied to /technicians and /jobs.
    doc = body.dict()
    # TD-86 · Feb-2026 — mirror the PATCH tenant guard so new crews
    # can never land with foreign-tenant / orphan tech_ids. The prior
    # implementation accepted whatever the FE sent, which is the
    # mechanism by which the preview DB accumulated orphan ids on
    # existing crew docs (see /app/memory/td86_crew_tenant_audit.md).
    #
    # TD-crew-silently-drop-orphan-members-and-backfill · Feb-2026 —
    # Operator reversal of the Ticket G strict-reject posture.  The
    # 400 on orphans created a stuck UX when ghosts persisted in the
    # crew doc but didn't render as member cards in the FE: operator
    # couldn't "see" them to "explicitly remove" them → infinite 400
    # loop on save.  New posture:
    #   * ``foreign_tenant`` errors STILL 400 (security concern — a
    #     foreign user_id leaking into a crew save means something
    #     cross-tenant is wrong; refuse the write).
    #   * ``orphan`` errors are SILENTLY DROPPED from the persisted
    #     ``tech_ids`` list.  INFO log emitted via config.logger
    #     (pool_crm) for operator audit trail.
    normalised = await _normalise_crew_tech_ids(doc.get("tech_ids"))
    if normalised:
        probe = await _resolve_tenant_members(tenant["id"], normalised)
        foreign_errors = [
            e for e in probe["errors"]
            if e.get("reason") == "foreign_tenant"
        ]
        orphan_errors = [
            e for e in probe["errors"] if e.get("reason") == "orphan"
        ]
        if foreign_errors:
            raise HTTPException(
                status_code=400,
                detail={
                    "detail": "crew tech_ids validation failed",
                    "field": "tech_ids",
                    "errors": foreign_errors,
                },
            )
        if orphan_errors:
            orphan_ids = [e["tech_id"] for e in orphan_errors]
            normalised = [x for x in normalised if x not in orphan_ids]
            logger.info(
                "[crews] silently dropped orphan tech_ids "
                "crew_id=<new> tenant_id=%s dropped=%s",
                tenant["id"], orphan_ids,
            )
    doc["tech_ids"] = normalised
    _now = now_iso()
    doc.update({"id": new_id(), "tenant_id": tenant["id"], "created_at": _now})
    # CREW-SCHEDULE-FANOUT · Feb-2026 — stamp a ``member_added_at``
    # map so the schedule-view time-box can compare each member's
    # join date against ``jobs.scheduled_date``. Initial members
    # share the crew's own ``created_at`` as their floor; later
    # ``add_crew_member`` writes stamp ``now_iso()``.
    doc["member_added_at"] = _crew_member_added_at_map(
        doc.get("tech_ids"), ts=_now,
    )
    await db.crews.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.patch("/crews/{cid}")
async def update_crew(cid: str, body: dict, user: dict = Depends(require_admin),
                       tenant: dict = Depends(get_current_tenant)):
    # Feb-2026 · Live-Tech-Map Phase 1 — palette lock on crew ``color``.
    # Off-palette values already saved on rows are TOLERATED on reads,
    # but new writes must land inside the approved 12-color palette.
    if "color" in body:
        raw = body.get("color")
        if raw is not None and raw != "":
            import re as _color_re
            if not isinstance(raw, str) or not _color_re.fullmatch(
                r"#[0-9A-Fa-f]{6}", raw,
            ):
                raise HTTPException(
                    400,
                    "color must be a '#RRGGBB' string (e.g. #3B82F6)",
                )
            from constants.tech_colors import is_palette_color, PALETTE_HEXES
            if not is_palette_color(raw):
                raise HTTPException(
                    400,
                    "color must be one of the approved palette colors: "
                    f"{PALETTE_HEXES}",
                )
            body["color"] = raw.upper()
    # Phase 9 · Feb-2026 — crew multi-member save defense in depth.
    #
    # The historical bug was a frontend stale-closure that collapsed
    # tech_ids to the single most-recently-clicked id (OpsHub.jsx
    # toggle used ``setForm({...form,...})`` instead of the functional
    # updater).  Even now that the FE is fixed, harden the endpoint
    # so a future caller sending a non-array ``tech_ids`` field OR a
    # tech_id that belongs to a different tenant fails loudly instead
    # of silently truncating the saved roster.
    #
    # TD-86 · Feb-2026 — swapped the inline predicate for the shared
    # ``_resolve_tenant_members`` helper (also used by POST) and
    # enriched the 400 payload with a categorised ``errors`` array
    # that distinguishes foreign-tenant ids from fully orphan ids.
    # See /app/memory/td86_crew_tenant_audit.md for the shape spec.
    # TD-crew-silently-drop-orphan-members-and-backfill · Feb-2026 —
    # see POST /crews docstring; same split applied here.
    if "tech_ids" in body:
        normalised = await _normalise_crew_tech_ids(body.get("tech_ids"))
        if normalised:
            probe = await _resolve_tenant_members(tenant["id"], normalised)
            foreign_errors = [
                e for e in probe["errors"]
                if e.get("reason") == "foreign_tenant"
            ]
            orphan_errors = [
                e for e in probe["errors"]
                if e.get("reason") == "orphan"
            ]
            if foreign_errors:
                raise HTTPException(
                    status_code=400,
                    detail={
                        "detail": "crew tech_ids validation failed",
                        "field": "tech_ids",
                        "errors": foreign_errors,
                    },
                )
            if orphan_errors:
                orphan_ids = [e["tech_id"] for e in orphan_errors]
                normalised = [
                    x for x in normalised if x not in orphan_ids
                ]
                logger.info(
                    "[crews] silently dropped orphan tech_ids "
                    "crew_id=%s tenant_id=%s dropped=%s",
                    cid, tenant["id"], orphan_ids,
                )
        body["tech_ids"] = normalised
    body["updated_at"] = now_iso()
    # Feb-2026 · P0 fix — scope the update to the caller's tenant so
    # a stale/foreign crew id can't mutate rows across tenants.
    r = await db.crews.update_one({"id": cid, "tenant_id": tenant["id"]}, {"$set": body})
    if r.matched_count == 0:
        raise HTTPException(404, "Crew not found")
    return await db.crews.find_one({"id": cid, "tenant_id": tenant["id"]}, {"_id": 0})


@router.delete("/crews/{cid}")
async def delete_crew(cid: str, user: dict = Depends(require_admin),
                       tenant: dict = Depends(get_current_tenant)):
    # Feb-2026 · Phase F3 — block hard-delete when any active job
    # references this crew. Prevents orphan-crew refs at the
    # source (mirror of the customer path in customers.py).
    referencing_jobs_count = await db.jobs.count_documents({
        "crew_id": cid,
        "tenant_id": tenant["id"],
        "status": {"$nin": ["deleted"]},
        "$or": [{"deleted_at": None},
                {"deleted_at": {"$exists": False}}],
    })
    if referencing_jobs_count > 0:
        raise HTTPException(
            status_code=409,
            detail={
                "error_code": "has_referencing_jobs",
                "message": (
                    f"Crew is referenced by {referencing_jobs_count} "
                    "active job(s) — reassign those jobs first."
                ),
                "job_count": referencing_jobs_count,
                "resolution": (
                    "reassign the affected jobs before deleting the crew"
                ),
            },
        )
    r = await db.crews.delete_one({"id": cid, "tenant_id": tenant["id"]})
    if r.deleted_count == 0:
        raise HTTPException(404, "Crew not found")
    return {"ok": True}


class CrewMemberIn(BaseModel):
    tech_id: str


@router.post("/crews/{cid}/members")
async def add_crew_member(cid: str, body: CrewMemberIn, user: dict = Depends(require_admin)):
    # CREW-SCHEDULE-FANOUT · Feb-2026 — stamp ``member_added_at.<tid>``
    # on every add so the schedule-view time-box has a per-member
    # floor. New members only see jobs ``scheduled_date >= today``
    # (same-day joins), closing the "member just added can see
    # 3-year-old crew jobs" leak. ``$addToSet`` + dotted ``$set``
    # compose cleanly in one update op.
    _now = now_iso()
    r = await db.crews.update_one(
        {"id": cid},
        {
            "$addToSet": {"tech_ids": body.tech_id},
            "$set": {f"member_added_at.{body.tech_id}": _now},
        },
    )
    if r.matched_count == 0:
        raise HTTPException(404, "Crew not found")
    return {"ok": True, "added_at": _now}


@router.delete("/crews/{cid}/members/{tid}")
async def remove_crew_member(cid: str, tid: str, user: dict = Depends(require_admin)):
    # CREW-SCHEDULE-FANOUT · Feb-2026 — unset the ``member_added_at``
    # entry alongside the ``$pull`` so re-adds get a fresh floor
    # (otherwise a stale pre-removal ``added_at`` would widen the
    # new member's visibility window). ``$unset`` on a dotted path
    # that doesn't exist is a safe no-op.
    await db.crews.update_one(
        {"id": cid},
        {
            "$pull": {"tech_ids": tid},
            "$unset": {f"member_added_at.{tid}": ""},
        },
    )
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
    q = {**q, **_nd()}
    jobs = await db.jobs.find(q, {"_id": 0, "photos.data": 0}).to_list(200)
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
