"""Feb-2026 · Optimize Route (tech→admin approval + 10 s undo).

Tech taps Optimize on the mobile Daily Route Map. That flows through:

    Tech        →  POST /api/jobs/route-optimization/preview       (compute-only, no state)
    Tech        →  POST /api/jobs/route-optimization/request       (creates pending suggestion)
    Admin       →  POST /api/jobs/route-optimization/{id}/approve  (applies + notifies tech)
    Admin       →  POST /api/jobs/route-optimization/{id}/reject   (denies + notifies tech)
    Admin       →  POST /api/jobs/route-optimization/apply         (direct apply, no request row)
    Anyone      →  POST /api/jobs/route-optimization/undo          (restores prior order · 10 s TTL)

State collection: ``route_optimization_requests``.
Ledger collection: ``route_optimize_events`` (reused via services.route_events.log_event
with ``kind="optimize_approval"``).

Route namespace intentionally distinct from the pre-existing
``/api/schedule/optimize-route`` (immediate apply, no approval) and
``/api/dispatch/route/optimize`` (admin dispatch board flow) so all three
coexist without collision.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Path as FPath
from pydantic import BaseModel, Field

from config import db
from utils import get_current_user, new_id, now_iso
from utils import not_deleted_filter as _nd
from services.route_optimizer import (
    PINNED_STATUSES,
    GOOGLE_DIRECTIONS_MAX_WAYPOINTS,
    compute_optimization,
    compute_optimization_v2,
)
from services import notifications as _notif
from services import route_events as _rte

router = APIRouter(prefix="/jobs/route-optimization",
                    tags=["route-optimization-approval"])

UNDO_WINDOW_SECONDS = 10

# ── Helpers ────────────────────────────────────────────────────────────


def _tenant_of(user: dict) -> str:
    tid = user.get("tenant_id") or ""
    if not tid:
        raise HTTPException(400, "tenant scope required")
    return tid


def _is_admin(user: dict) -> bool:
    return (user.get("role") or "").lower() in ("admin", "super_admin", "manager")


async def _resolve_job_coords(job: dict, tenant_id: str) -> Optional[tuple[float, float]]:
    """Resolve (lat, lng) using the same fallback chain the mobile client uses."""
    for lat_k, lng_k in [
        ("lat", "lng"),
        ("lat", "lon"),
        ("latitude", "longitude"),
        ("site_lat", "site_lng"),
        ("site_lat", "site_lon"),
    ]:
        la, lo = job.get(lat_k), job.get(lng_k)
        if isinstance(la, (int, float)) and isinstance(lo, (int, float)):
            return float(la), float(lo)
    prop_id = job.get("property_id")
    if prop_id:
        p = await db.properties.find_one(
            {"id": prop_id, "tenant_id": tenant_id},
            {"_id": 0, "lat": 1, "lng": 1, "location": 1},
        ) or {}
        loc = p.get("location") or {}
        la, lo = p.get("lat") or loc.get("lat"), p.get("lng") or loc.get("lng")
        if isinstance(la, (int, float)) and isinstance(lo, (int, float)):
            return float(la), float(lo)
    cust_id = job.get("customer_id")
    if cust_id:
        c = await db.customers.find_one(
            {"id": cust_id, "tenant_id": tenant_id},
            {"_id": 0, "lat": 1, "lon": 1, "latitude": 1, "longitude": 1,
             "service_lat": 1, "service_lon": 1},
        ) or {}
        for a, b in [("lat", "lon"), ("latitude", "longitude"),
                       ("service_lat", "service_lon")]:
            la, lo = c.get(a), c.get(b)
            if isinstance(la, (int, float)) and isinstance(lo, (int, float)):
                return float(la), float(lo)
    return None


async def _load_day_jobs(tenant_id: str,
                          tech_user_ids: list[str],
                          date: str) -> list[dict[str, Any]]:
    """Fetch a tech's jobs for a date, sorted by current route_index.

    Feb-2026 · P2→P0 · Identity-mismatch hotfix. Legacy jobs are
    stamped with ``technician_id = user.id``; post-``bulk-reassign``
    (jobs.py::_lookup_tech_user :: canonical_tech_id) jobs are
    stamped with ``technician_id = user.technician_id``. Real
    tenants have BOTH shapes co-existing. Callers must pass the
    tech's full identity set (``user.id`` + ``user.technician_id``,
    de-duped and None-stripped) so we don't hide legitimate jobs.
    """
    import re
    date_prefix = re.escape(date)
    q = {
        "tenant_id": tenant_id,
        "$or": [
            {"tech_user_id": {"$in": tech_user_ids}},
            {"assigned_to": {"$in": tech_user_ids}},
            {"technician_id": {"$in": tech_user_ids}},
        ],
        "$and": [{
            "$or": [
                {"scheduled_date": {"$regex": f"^{date_prefix}"}},
                {"scheduled_start": {"$regex": f"^{date_prefix}"}},
            ],
        }],
    }
    q = {**q, **_nd()}
    jobs: list[dict[str, Any]] = []
    async for j in db.jobs.find(q, {"_id": 0}).sort([("route_index", 1),
                                                       ("scheduled_start", 1)]):
        jobs.append(j)
    return jobs


def _route_scope_ids_for(user_doc: dict[str, Any]) -> list[str]:
    """Return the de-duped, None-stripped identity list for a tech.

    Used by every read-path in this router so route optimize / apply /
    undo consistently match jobs stamped with either ``user.id`` OR
    ``user.technician_id``.
    """
    return list(filter(None, [user_doc.get("id"),
                              user_doc.get("technician_id")]))


async def _resolve_target_scope_ids(caller: dict[str, Any],
                                      target_user_id: str) -> list[str]:
    """Feb-2026 · P2→P0 · identity-mismatch resolution.

    Returns the ``[user.id, user.technician_id]`` scope-id set for the
    target tech (falling back to just ``target_user_id`` if the users
    row cannot be found — safe: matches the historical single-id
    behavior). Zero DB round-trips when the caller IS the target
    (common tech-self case).
    """
    if caller.get("id") == target_user_id:
        return _route_scope_ids_for(caller)
    row = await db.users.find_one({"id": target_user_id},
                                    {"_id": 0, "id": 1, "technician_id": 1})
    if not row:
        return [target_user_id]
    return _route_scope_ids_for(row) or [target_user_id]


async def _hydrate_geo(jobs: list[dict[str, Any]], tenant_id: str
                        ) -> list[dict[str, Any]]:
    """Return a NEW list with ``lat``/``lng`` populated on each job."""
    out: list[dict[str, Any]] = []
    for j in jobs:
        coords = await _resolve_job_coords(j, tenant_id)
        if coords:
            out.append({**j, "lat": coords[0], "lng": coords[1]})
        else:
            out.append({**j})
    return out


def _date_expires_at_iso(date: str) -> str:
    """End-of-day UTC for the request's TTL check."""
    return f"{date}T23:59:59+00:00"


async def _fanout_admin_notification(tenant_id: str, tech_user_id: str,
                                       req: dict) -> None:
    """Fire the in-app ``route_optimization_request`` notification to admins."""
    try:
        u = await db.users.find_one(
            {"id": tech_user_id, "tenant_id": tenant_id},
            {"_id": 0, "name": 1, "full_name": 1, "email": 1},
        ) or {}
        tech_name = (u.get("full_name") or u.get("name")
                      or (u.get("email") or "").split("@")[0]
                      or tech_user_id)
        title = f"Route optimization requested by {tech_name}"
        body = (
            f"{req['stops_affected']} stops · "
            f"{req['estimated_miles_saved']} mi saved · "
            f"{req['estimated_minutes_saved']} min saved · "
            f"{req['route_date']}"
        )
        await _notif.enqueue_for_tenant_admins(
            tenant_id, "route_optimization_request",
            title, body,
            source_ref={"kind": "route_optimization_request", "id": req["id"]},
            href=f"/dispatch?optimize={req['id']}",
            priority="normal",
        )
    except Exception:
        # Never fail the request path on notification hiccups.
        pass


async def _notify_tech_of_resolution(tenant_id: str, tech_user_id: str,
                                       verb: str, req: dict) -> None:
    """Notify the requesting tech of approve/reject."""
    try:
        title = f"Route optimization {verb}"
        body = (
            f"{req.get('stops_affected', 0)} stops · "
            f"{req.get('route_date', '')}"
        )
        await _notif.emit([tech_user_id], "route_optimization_request",
                            title, body,
                            source_ref={"kind": "route_optimization_request",
                                          "id": req.get("id")},
                            href="/schedule",
                            priority="normal",
                            tenant_id=tenant_id)
    except Exception:
        pass


# ── Pydantic bodies ────────────────────────────────────────────────────


class PreviewBody(BaseModel):
    date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    current_lat: Optional[float] = None
    current_lng: Optional[float] = None
    tech_user_id: Optional[str] = None  # admin override; techs ignore


class RequestBody(PreviewBody):
    pass


class ApplyBody(BaseModel):
    tech_user_id: str = Field(..., min_length=1)
    date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    proposed_order: list[str] = Field(..., min_length=1)
    miles_saved: float = 0.0
    minutes_saved: float = 0.0


# ── Endpoints ──────────────────────────────────────────────────────────


@router.post("/preview")
async def preview(body: PreviewBody,
                    caller: dict = Depends(get_current_user)):
    """Pure compute — no state written."""
    tenant_id = _tenant_of(caller)
    if (caller.get("role") or "").lower() == "customer":
        raise HTTPException(403, "Not allowed")

    # Admin may target another tech; tech is always themselves.
    tech_id = caller["id"]
    if body.tech_user_id and _is_admin(caller):
        tech_id = body.tech_user_id
    elif body.tech_user_id and body.tech_user_id != caller["id"]:
        raise HTTPException(403, "Cannot preview another user's route")

    jobs = await _load_day_jobs(tenant_id,
                                  await _resolve_target_scope_ids(caller, tech_id),
                                  body.date)
    if not jobs:
        raise HTTPException(404, "no_jobs_for_tech_on_date")

    hydrated = await _hydrate_geo(jobs, tenant_id)

    # Fallback: no GPS from caller → first pending stop's coords.
    start_lat, start_lng = body.current_lat, body.current_lng
    used_fallback_origin = False
    if start_lat is None or start_lng is None:
        first_pending = next(
            (j for j in hydrated
             if (j.get("status") or "").lower() not in PINNED_STATUSES
             and isinstance(j.get("lat"), (int, float))),
            None,
        )
        if first_pending is None:
            raise HTTPException(422, "no_origin_available")
        start_lat = first_pending["lat"]
        start_lng = first_pending["lng"]
        used_fallback_origin = True

    # Feb-2026 · Google Routes API v2 cap — enforce BEFORE compute so
    # we don't waste a Haversine fallback pass on requests we'll reject.
    # Pinned stops don't count toward the cap (they don't go through
    # Directions).
    reshufflable_count = sum(
        1 for j in hydrated
        if isinstance(j.get("lat"), (int, float))
        and (j.get("status") or "").lower() not in PINNED_STATUSES
    )
    if reshufflable_count > GOOGLE_DIRECTIONS_MAX_WAYPOINTS:
        raise HTTPException(
            400,
            {
                "code": "too_many_stops",
                "max_waypoints": GOOGLE_DIRECTIONS_MAX_WAYPOINTS,
                "actual": reshufflable_count,
                "message": (
                    f"Route optimization supports up to "
                    f"{GOOGLE_DIRECTIONS_MAX_WAYPOINTS} reshufflable "
                    f"stops per day — this day has {reshufflable_count}. "
                    f"Split the day or reduce the stop count to try again."
                ),
            },
        )

    result = await compute_optimization_v2(
        current_order_jobs=hydrated,
        start_lat=float(start_lat),
        start_lng=float(start_lng),
    )
    return {
        **result,
        "tech_user_id": tech_id,
        "date": body.date,
        "origin": {"lat": start_lat, "lng": start_lng,
                    "source": "device_gps_fallback" if used_fallback_origin
                              else "device_gps"},
        "estimated_miles_saved": result["miles_saved"],
        "estimated_minutes_saved": result["minutes_saved"],
    }


@router.post("/request")
async def request_(body: RequestBody,
                    caller: dict = Depends(get_current_user)):
    """Tech creates a pending suggestion for admin approval."""
    tenant_id = _tenant_of(caller)
    role = (caller.get("role") or "").lower()
    if role == "customer":
        raise HTTPException(403, "Not allowed")
    # Admins should call /apply directly instead — but we don't 403 here;
    # we still let them create a request row for audit purposes.
    tech_id = caller["id"]
    if body.tech_user_id and _is_admin(caller):
        tech_id = body.tech_user_id

    prev = await preview(PreviewBody(date=body.date,
                                        current_lat=body.current_lat,
                                        current_lng=body.current_lng,
                                        tech_user_id=tech_id),
                            caller=caller)
    if prev.get("no_change") or (prev.get("miles_saved") or 0) <= 0:
        raise HTTPException(422, "no_optimization_available")

    # Load pre-existing route_index map for undo/audit + before_order.
    day_jobs = await _load_day_jobs(tenant_id,
                                      await _resolve_target_scope_ids(caller, tech_id),
                                      body.date)
    before_order = [j["id"] for j in day_jobs
                     if j["id"] in prev["proposed_order"]]
    before_index_map = {j["id"]: j.get("route_index")
                          for j in day_jobs
                          if j["id"] in prev["proposed_order"]}

    req_id = new_id()
    doc = {
        "id": req_id,
        "tenant_id": tenant_id,
        "tech_user_id": tech_id,
        "route_date": body.date,
        "before_order": before_order,
        "after_order": prev["proposed_order"],
        "before_index_map": before_index_map,
        "estimated_miles_saved": prev["miles_saved"],
        "estimated_minutes_saved": prev["minutes_saved"],
        "stops_affected": prev["stops_affected"],
        "pinned_ids": prev["pinned_ids"],
        "requested_at": now_iso(),
        "requested_by": caller["id"],
        "status": "pending",
        "expires_at": _date_expires_at_iso(body.date),
        "origin": prev.get("origin"),
    }

    # Unique pending-per-(tenant,tech,date): replace any existing pending row.
    await db.route_optimization_requests.update_many(
        {"tenant_id": tenant_id, "tech_user_id": tech_id,
          "route_date": body.date, "status": "pending"},
        {"$set": {"status": "expired", "resolved_at": now_iso(),
                    "resolved_by": "superseded"}},
    )
    await db.route_optimization_requests.insert_one(doc)

    await _fanout_admin_notification(tenant_id, tech_id, doc)

    doc.pop("_id", None)
    return doc


async def _apply_internal(tenant_id: str, tech_user_id: str, date: str,
                           proposed_order: list[str],
                           miles_saved: float, minutes_saved: float,
                           executed_by: str) -> dict:
    """Shared apply path: PATCH route_index atomically + write ledger + prep undo."""
    if not proposed_order:
        raise HTTPException(422, "empty_proposed_order")

    # Snapshot before-state for undo.
    before_map: dict[str, Optional[int]] = {}
    updated = 0
    for new_idx, jid in enumerate(proposed_order):
        # capture current route_index BEFORE writing
        cur = await db.jobs.find_one(
            {"id": jid, "tenant_id": tenant_id},
            {"_id": 0, "route_index": 1},
        ) or {}
        before_map[jid] = cur.get("route_index")

        r = await db.jobs.update_one(
            {"id": jid, "tenant_id": tenant_id,
              "$or": [{"tech_user_id": tech_user_id},
                       {"assigned_to": tech_user_id},
                       {"technician_id": tech_user_id}]},
            {"$set": {"route_index": new_idx}},
        )
        if r.matched_count:
            updated += 1

    now = datetime.now(timezone.utc)
    undo_expires_at = (now + timedelta(seconds=UNDO_WINDOW_SECONDS)).isoformat()
    applied_at = now.isoformat()

    # Write ledger row.
    await _rte.log_event(
        tenant_id=tenant_id, kind="optimize_approval",
        tech_user_id=tech_user_id,
        route_date=date,
        savings_km=float(miles_saved) * 1.60934,   # store km for symmetry with route_events
        stop_count=updated,
        executed_by=executed_by or "",
    )

    # Persist an "applied" row so /undo can find the before-state.
    applied_doc = {
        "id": new_id(),
        "tenant_id": tenant_id,
        "tech_user_id": tech_user_id,
        "route_date": date,
        "proposed_order": proposed_order,
        "before_index_map": before_map,
        "miles_saved": float(miles_saved or 0.0),
        "minutes_saved": float(minutes_saved or 0.0),
        "applied_at": applied_at,
        "applied_by": executed_by,
        "undo_expires_at": undo_expires_at,
        "undone": False,
        "status": "applied",
    }
    await db.route_optimization_requests.insert_one(applied_doc)

    return {
        "applied_at": applied_at,
        "undo_expires_at": undo_expires_at,
        "applied_id": applied_doc["id"],
        "updated": updated,
    }


@router.post("/apply")
async def apply(body: ApplyBody,
                 caller: dict = Depends(get_current_user)):
    """Admin-only direct apply (skips the pending queue)."""
    tenant_id = _tenant_of(caller)
    if not _is_admin(caller):
        raise HTTPException(403, "Only admins may apply directly")

    # Verify tenant boundary — the tech must belong to caller's tenant.
    tech_row = await db.users.find_one(
        {"id": body.tech_user_id}, {"_id": 0, "tenant_id": 1},
    ) or {}
    if tech_row.get("tenant_id") not in (None, tenant_id):
        raise HTTPException(403, "tech_user_id not in current tenant")

    return await _apply_internal(
        tenant_id=tenant_id, tech_user_id=body.tech_user_id,
        date=body.date, proposed_order=body.proposed_order,
        miles_saved=body.miles_saved, minutes_saved=body.minutes_saved,
        executed_by=caller.get("id") or caller.get("email") or "",
    )


@router.post("/{request_id}/approve")
async def approve(request_id: str = FPath(..., min_length=1),
                    caller: dict = Depends(get_current_user)):
    tenant_id = _tenant_of(caller)
    if not _is_admin(caller):
        raise HTTPException(403, "Only admins may approve")

    req = await db.route_optimization_requests.find_one(
        {"id": request_id, "tenant_id": tenant_id}, {"_id": 0},
    )
    if not req:
        raise HTTPException(404, "request not found")
    if req.get("status") != "pending":
        raise HTTPException(409, f"request not pending (status={req.get('status')})")

    # TTL enforcement.
    exp = req.get("expires_at")
    if exp and datetime.fromisoformat(exp) < datetime.now(timezone.utc):
        await db.route_optimization_requests.update_one(
            {"id": request_id, "tenant_id": tenant_id},
            {"$set": {"status": "expired",
                        "resolved_at": now_iso(),
                        "resolved_by": caller.get("id") or ""}},
        )
        raise HTTPException(410, "request expired")

    result = await _apply_internal(
        tenant_id=tenant_id,
        tech_user_id=req["tech_user_id"],
        date=req["route_date"],
        proposed_order=req["after_order"],
        miles_saved=req.get("estimated_miles_saved") or 0.0,
        minutes_saved=req.get("estimated_minutes_saved") or 0.0,
        executed_by=caller.get("id") or caller.get("email") or "",
    )

    await db.route_optimization_requests.update_one(
        {"id": request_id, "tenant_id": tenant_id},
        {"$set": {"status": "approved",
                    "resolved_at": now_iso(),
                    "resolved_by": caller.get("id") or "",
                    "applied_id": result["applied_id"]}},
    )
    await _notify_tech_of_resolution(tenant_id, req["tech_user_id"],
                                       "approved", req)
    return {**result, "request_id": request_id, "status": "approved"}


@router.post("/{request_id}/reject")
async def reject(request_id: str = FPath(..., min_length=1),
                   caller: dict = Depends(get_current_user)):
    tenant_id = _tenant_of(caller)
    if not _is_admin(caller):
        raise HTTPException(403, "Only admins may reject")

    req = await db.route_optimization_requests.find_one(
        {"id": request_id, "tenant_id": tenant_id}, {"_id": 0},
    )
    if not req:
        raise HTTPException(404, "request not found")
    if req.get("status") != "pending":
        raise HTTPException(409, f"request not pending (status={req.get('status')})")

    await db.route_optimization_requests.update_one(
        {"id": request_id, "tenant_id": tenant_id},
        {"$set": {"status": "rejected",
                    "resolved_at": now_iso(),
                    "resolved_by": caller.get("id") or ""}},
    )
    await _notify_tech_of_resolution(tenant_id, req["tech_user_id"],
                                       "rejected", req)
    return {"request_id": request_id, "status": "rejected"}


class UndoBody(BaseModel):
    applied_id: str = Field(..., min_length=1)


@router.post("/undo")
async def undo(body: UndoBody, caller: dict = Depends(get_current_user)):
    tenant_id = _tenant_of(caller)
    doc = await db.route_optimization_requests.find_one(
        {"id": body.applied_id, "tenant_id": tenant_id, "status": "applied"},
        {"_id": 0},
    )
    if not doc:
        raise HTTPException(404, "applied_id not found")
    if doc.get("undone"):
        raise HTTPException(410, "already_undone")

    exp = doc.get("undo_expires_at")
    if exp and datetime.fromisoformat(exp) < datetime.now(timezone.utc):
        raise HTTPException(410, "undo_window_expired")

    # Restore prior route_index atomically.
    before_map: dict[str, Optional[int]] = doc.get("before_index_map") or {}
    restored = 0
    for jid, prev_idx in before_map.items():
        if prev_idx is None:
            r = await db.jobs.update_one(
                {"id": jid, "tenant_id": tenant_id},
                {"$unset": {"route_index": ""}},
            )
        else:
            r = await db.jobs.update_one(
                {"id": jid, "tenant_id": tenant_id},
                {"$set": {"route_index": int(prev_idx)}},
            )
        if r.matched_count:
            restored += 1

    await db.route_optimization_requests.update_one(
        {"id": body.applied_id, "tenant_id": tenant_id},
        {"$set": {"undone": True, "undone_at": now_iso(),
                    "undone_by": caller.get("id") or ""}},
    )
    return {"restored": restored, "applied_id": body.applied_id}


@router.get("/pending")
async def list_pending(caller: dict = Depends(get_current_user)):
    """Admin-facing list — used by the web approval UI in sub-phase C."""
    tenant_id = _tenant_of(caller)
    if not _is_admin(caller):
        raise HTTPException(403, "Only admins may list pending requests")
    now = datetime.now(timezone.utc)
    rows: list[dict[str, Any]] = []
    async for r in db.route_optimization_requests.find(
        {"tenant_id": tenant_id, "status": "pending"},
        {"_id": 0},
    ).sort([("requested_at", -1)]):
        # Silently downgrade expired rows on read.
        exp = r.get("expires_at")
        if exp and datetime.fromisoformat(exp) < now:
            await db.route_optimization_requests.update_one(
                {"id": r["id"], "tenant_id": tenant_id, "status": "pending"},
                {"$set": {"status": "expired", "resolved_at": now.isoformat()}},
            )
            continue
        rows.append(r)
    return {"pending": rows}
