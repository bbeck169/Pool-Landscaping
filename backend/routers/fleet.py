"""FLEET-A · Feb-2026 — /api/fleet/* router.

Endpoints:
    POST  /api/fleet/ping                    (technician)
    POST  /api/fleet/checkin                 (technician)
    GET   /api/fleet/board                   (admin, super)
    GET   /api/fleet/breadcrumbs/{tech_id}   (admin, super)
    POST  /api/fleet/membership/{tech_id}    (admin, super)
    GET   /api/fleet/membership              (admin, super)

Every endpoint is tenant-scoped via ``get_current_tenant`` and
role-gated in-handler.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from config import db, logger
from routers.tenants import get_current_tenant
from services.fleet.eta import compute_eta
from services.fleet.notifications import (
    NotifyOutcome, maybe_send_on_the_way,
)
from services.fleet.rate_limit import check_and_stamp
from utils import get_current_user, new_id, now_iso

router = APIRouter(prefix="/fleet", tags=["fleet"])


# ─── Roles ─────────────────────────────────────────────────────────

_TECH_ROLES = {"technician", "tech"}
_ADMIN_ROLES = {"admin", "super_admin", "owner"}
_SUPER_ROLES = {"super_admin"}


def _require_tech(user: dict) -> dict:
    role = (user.get("role") or "").lower()
    if role not in _TECH_ROLES:
        raise HTTPException(
            403,
            detail={"error_code": "not_a_technician",
                     "message": "Only technicians may ping."},
        )
    return user


def _require_admin_or_super(user: dict) -> dict:
    role = (user.get("role") or "").lower()
    if role not in _ADMIN_ROLES:
        raise HTTPException(
            403,
            detail={"error_code": "forbidden",
                     "message": "Admin or super_admin required"},
        )
    return user


# ─── in-fleet gate ─────────────────────────────────────────────────

async def _is_in_fleet(tenant_id: str, tech_user_id: str) -> bool:
    row = await db.fleet_membership.find_one(
        {"tenant_id": tenant_id, "tech_user_id": tech_user_id},
        {"_id": 0, "in_fleet": 1},
    )
    return bool(row and row.get("in_fleet") is True)


# ─── Request models ───────────────────────────────────────────────

class PingBody(BaseModel):
    lat: float = Field(..., ge=-90, le=90)
    lng: float = Field(..., ge=-180, le=180)
    accuracy_m: Optional[float] = Field(None, ge=0, le=10000)
    speed_kmh: Optional[float] = Field(None, ge=0, le=500)
    heading_deg: Optional[float] = Field(None, ge=0, le=360)
    battery_pct: Optional[float] = Field(None, ge=0, le=100)
    device_time: Optional[str] = None
    job_id: Optional[str] = None


class CheckinBody(BaseModel):
    kind: str = Field(..., pattern="^(on_the_way|arrived)$")
    job_id: str
    lat: Optional[float] = Field(None, ge=-90, le=90)
    lng: Optional[float] = Field(None, ge=-180, le=180)


class MembershipBody(BaseModel):
    in_fleet: bool
    notes: Optional[str] = Field(None, max_length=500)


# ─── Helpers ──────────────────────────────────────────────────────

_STALE_PING_MAX_SECONDS = 60


def _parse_device_time(iso: Optional[str]) -> Optional[datetime]:
    if not iso:
        return None
    try:
        s = iso.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


# ─── POST /ping ───────────────────────────────────────────────────

@router.post("/ping")
async def post_ping(
    body: PingBody,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    _require_tech(user)
    tech_id = user["id"]

    if not await _is_in_fleet(tenant["id"], tech_id):
        raise HTTPException(
            403,
            detail={"error_code": "not_in_fleet",
                     "message": "Technician is not enrolled in the fleet."},
        )

    # Stale device_time rejection — never trust client timestamps
    # further than 60s from server now.
    device_dt = _parse_device_time(body.device_time)
    if device_dt is not None:
        skew = abs((_now_utc() - device_dt).total_seconds())
        if skew > _STALE_PING_MAX_SECONDS:
            raise HTTPException(
                400,
                detail={
                    "error_code": "stale_ping",
                    "message": (
                        f"device_time is {int(skew)}s from server now — "
                        f"limit is {_STALE_PING_MAX_SECONDS}s."
                    ),
                    "server_time_skew_s": int(skew),
                },
            )

    # Rate-limit — 1 ping per 5s per tech.
    if not check_and_stamp(tenant["id"], tech_id):
        raise HTTPException(
            429,
            detail={"error_code": "rate_limited",
                     "message": "1 ping per 5 seconds per tech."},
        )

    now_dt = _now_utc()
    doc = {
        "id": new_id(),
        "tenant_id": tenant["id"],
        "tech_user_id": tech_id,
        "recorded_at": now_iso(),
        "recorded_at_dt": now_dt,
        "source": "gps",
        "lat": body.lat, "lng": body.lng,
        "accuracy_m": body.accuracy_m,
        "speed_kmh": body.speed_kmh,
        "heading_deg": body.heading_deg,
        "battery_pct": body.battery_pct,
        "device_time": body.device_time,
        "server_time_skew_s": (
            int(abs((_now_utc() - device_dt).total_seconds()))
            if device_dt is not None else None
        ),
        "job_id": body.job_id,
        "created_at": now_iso(),
    }
    await db.tech_locations.insert_one(doc)
    return {"ok": True, "id": doc["id"], "recorded_at": doc["recorded_at"]}


# ─── POST /checkin ────────────────────────────────────────────────

@router.post("/checkin")
async def post_checkin(
    body: CheckinBody,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    _require_tech(user)
    tech_id = user["id"]

    if not await _is_in_fleet(tenant["id"], tech_id):
        raise HTTPException(
            403,
            detail={"error_code": "not_in_fleet",
                     "message": "Technician is not enrolled in the fleet."},
        )

    # Ensure the job belongs to this tenant.
    job = await db.jobs.find_one(
        {"id": body.job_id, "tenant_id": tenant["id"]},
        {"_id": 0},
    )
    if not job:
        raise HTTPException(
            404, detail={"error_code": "job_not_found",
                          "job_id": body.job_id},
        )

    now_dt = _now_utc()
    source = (
        "manual_arrived" if body.kind == "arrived"
        else "manual_on_the_way"
    )
    doc = {
        "id": new_id(),
        "tenant_id": tenant["id"],
        "tech_user_id": tech_id,
        "recorded_at": now_iso(),
        "recorded_at_dt": now_dt,
        "source": source,
        "lat": body.lat, "lng": body.lng,
        "accuracy_m": None, "speed_kmh": None,
        "heading_deg": None, "battery_pct": None,
        "device_time": None,
        "job_id": body.job_id,
        "created_at": now_iso(),
    }
    await db.tech_locations.insert_one(doc)

    resp: Dict[str, Any] = {"ok": True, "id": doc["id"], "kind": body.kind}

    if body.kind == "arrived":
        # Patch job.actual_start_time if unset — never overwrite.
        patched = False
        if not job.get("actual_start_time"):
            await db.jobs.update_one(
                {"id": body.job_id, "tenant_id": tenant["id"],
                  # Guard against a concurrent write — only set when
                  # still unset at update time.
                  "$or": [
                      {"actual_start_time": None},
                      {"actual_start_time": {"$exists": False}},
                  ]},
                {"$set": {"actual_start_time": now_iso()}},
            )
            patched = True
        resp["actual_start_time_patched"] = patched
        return resp

    # kind == "on_the_way" — fire the customer notification pipeline.
    outcome: NotifyOutcome = await maybe_send_on_the_way(
        tenant_id=tenant["id"],
        tech_user_id=tech_id,
        job_id=body.job_id,
        tech_lat=body.lat,
        tech_lng=body.lng,
    )
    resp["notification"] = {
        "sent": outcome.sent,
        "reason": outcome.reason,
        "eta_minutes": outcome.eta_minutes,
        "provider": outcome.provider,
        "channels": outcome.channels,
    }
    return resp


# ─── GET /board ───────────────────────────────────────────────────

def _job_coords(job: Dict[str, Any]) -> Optional[tuple]:
    for lat_key, lng_key in (
        ("latitude", "longitude"),
        ("site_lat", "site_lng"),
        ("lat", "lng"),
    ):
        lat, lng = job.get(lat_key), job.get(lng_key)
        if isinstance(lat, (int, float)) and isinstance(lng, (int, float)):
            return float(lat), float(lng)
    return None


async def _latest_location(tenant_id: str,
                             tech_user_id: str) -> Optional[Dict[str, Any]]:
    return await db.tech_locations.find_one(
        {"tenant_id": tenant_id, "tech_user_id": tech_user_id},
        {"_id": 0},
        sort=[("recorded_at", -1)],
    )


async def _next_scheduled_job(tenant_id: str,
                                 tech_user_id: str) -> Optional[Dict[str, Any]]:
    """The nearest-future job for this tech.  Falls back to any
    currently-open in-progress job."""
    now = now_iso()
    # In-progress first — the tech is already on it.
    in_progress = await db.jobs.find_one(
        {"tenant_id": tenant_id,
          "technician_id": tech_user_id,
          "status": {"$in": ["in_progress", "started", "on_site"]},
          "$or": [
              {"deleted_at": None},
              {"deleted_at": {"$exists": False}},
          ]},
        {"_id": 0}, sort=[("scheduled_start", 1)],
    )
    if in_progress:
        return in_progress
    return await db.jobs.find_one(
        {"tenant_id": tenant_id,
          "technician_id": tech_user_id,
          "status": {"$in": ["scheduled", "pending", "confirmed"]},
          "scheduled_start": {"$gte": now},
          "$or": [
              {"deleted_at": None},
              {"deleted_at": {"$exists": False}},
          ]},
        {"_id": 0}, sort=[("scheduled_start", 1)],
    )


async def _eta_via_snapshot_or_compute(
    *, tenant_id: str, tech_user_id: str, job_id: str,
    from_lat: float, from_lng: float,
    to_lat: float, to_lng: float,
) -> Dict[str, Any]:
    """Return a live ETA — reuses a snapshot if it's fresh
    (stale_at > now); otherwise recomputes and caches."""
    now = _now_utc()
    fresh = await db.fleet_eta_snapshots.find_one(
        {"tenant_id": tenant_id, "job_id": job_id},
        {"_id": 0}, sort=[("computed_at", -1)],
    )
    if fresh and fresh.get("stale_at_dt") and fresh["stale_at_dt"] > now:
        return {
            "provider": fresh["provider"],
            "distance_m": fresh["distance_m"],
            "duration_s": fresh["duration_s"],
            "eta_arrival_at": fresh["eta_arrival_at"],
            "cache": "fresh",
        }
    result = await compute_eta(from_lat, from_lng, to_lat, to_lng)
    stale_at = now + timedelta(seconds=60)
    eta_arrival_at = now + timedelta(seconds=result.duration_s)
    snapshot = {
        "id": new_id(),
        "tenant_id": tenant_id,
        "tech_user_id": tech_user_id,
        "job_id": job_id,
        "computed_at": now.isoformat().replace("+00:00", "Z"),
        "computed_at_dt": now,
        "from_lat": from_lat, "from_lng": from_lng,
        "to_lat": to_lat, "to_lng": to_lng,
        "provider": result.provider,
        "distance_m": result.distance_m,
        "duration_s": result.duration_s,
        "eta_arrival_at": eta_arrival_at.isoformat().replace("+00:00", "Z"),
        "stale_at": stale_at.isoformat().replace("+00:00", "Z"),
        "stale_at_dt": stale_at,
    }
    await db.fleet_eta_snapshots.insert_one(snapshot)
    return {
        "provider": result.provider,
        "distance_m": result.distance_m,
        "duration_s": result.duration_s,
        "eta_arrival_at": snapshot["eta_arrival_at"],
        "cache": "recomputed",
    }


@router.get("/board")
async def get_board(
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    _require_admin_or_super(user)

    members_cursor = db.fleet_membership.find(
        {"tenant_id": tenant["id"], "in_fleet": True},
        {"_id": 0, "tech_user_id": 1},
    )
    tech_ids = [row["tech_user_id"] async for row in members_cursor]
    if not tech_ids:
        return {"count": 0, "techs": []}

    tech_docs_cursor = db.users.find(
        {"id": {"$in": tech_ids}, "tenant_id": tenant["id"]},
        {"_id": 0, "id": 1, "name": 1, "display_name": 1, "role": 1,
         "avatar_color": 1},
    )
    tech_docs = {row["id"]: row async for row in tech_docs_cursor}

    now_dt = _now_utc()
    result: List[Dict[str, Any]] = []
    for tid in tech_ids:
        loc = await _latest_location(tenant["id"], tid)
        last_ping_age_s: Optional[int] = None
        if loc:
            try:
                rec_at = datetime.fromisoformat(
                    (loc.get("recorded_at") or "").replace("Z", "+00:00")
                )
                if rec_at.tzinfo is None:
                    rec_at = rec_at.replace(tzinfo=timezone.utc)
                last_ping_age_s = int((now_dt - rec_at).total_seconds())
            except (TypeError, ValueError):
                last_ping_age_s = None

        job = await _next_scheduled_job(tenant["id"], tid)
        eta_payload: Optional[Dict[str, Any]] = None
        if job and loc and (loc.get("lat") is not None):
            coords = _job_coords(job)
            if coords:
                try:
                    eta_payload = await _eta_via_snapshot_or_compute(
                        tenant_id=tenant["id"], tech_user_id=tid,
                        job_id=job["id"],
                        from_lat=float(loc["lat"]),
                        from_lng=float(loc["lng"]),
                        to_lat=coords[0], to_lng=coords[1],
                    )
                except Exception:                                  # noqa: BLE001
                    # Never fail the board on an ETA compute error.
                    logger.exception(
                        "[fleet.board] eta compute failed tech=%s job=%s",
                        tid, job["id"],
                    )
                    eta_payload = None

        result.append({
            "tech_user_id": tid,
            "tech_name": (tech_docs.get(tid) or {}).get("name")
                or (tech_docs.get(tid) or {}).get("display_name")
                or tid,
            "role": (tech_docs.get(tid) or {}).get("role"),
            "avatar_color": (tech_docs.get(tid) or {}).get("avatar_color"),
            "location": loc,
            "last_ping_age_s": last_ping_age_s,
            "current_job": (
                {
                    "id": job["id"],
                    "title": job.get("title"),
                    "customer_id": job.get("customer_id"),
                    "customer_name": job.get("customer_name"),
                    "address": job.get("service_address")
                        or job.get("address"),
                    "lat": _job_coords(job)[0] if _job_coords(job) else None,
                    "lng": _job_coords(job)[1] if _job_coords(job) else None,
                    "status": job.get("status"),
                    "scheduled_start": job.get("scheduled_start"),
                }
                if job else None
            ),
            "eta": eta_payload,
            "battery_pct": (loc or {}).get("battery_pct"),
        })

    return {"count": len(result), "techs": result}


# ─── GET /breadcrumbs/{tech_id} ────────────────────────────────────

@router.get("/breadcrumbs/{tech_user_id}")
async def get_breadcrumbs(
    tech_user_id: str,
    since: Optional[str] = Query(None),
    until: Optional[str] = Query(None),
    job_id: Optional[str] = Query(None),
    limit: int = Query(1000, ge=1, le=5000),
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    _require_admin_or_super(user)

    q: Dict[str, Any] = {
        "tenant_id": tenant["id"], "tech_user_id": tech_user_id,
    }
    if job_id:
        q["job_id"] = job_id
    if since or until:
        rng: Dict[str, Any] = {}
        if since:
            rng["$gte"] = since
        if until:
            rng["$lte"] = until
        q["recorded_at"] = rng

    cursor = db.tech_locations.find(q, {"_id": 0}).sort(
        [("recorded_at", -1)]
    ).limit(limit)
    rows = await cursor.to_list(limit)
    return {"count": len(rows), "tech_user_id": tech_user_id, "items": rows}


# ─── Membership CRUD ──────────────────────────────────────────────

@router.post("/membership/{tech_user_id}")
async def set_membership(
    tech_user_id: str,
    body: MembershipBody,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    _require_admin_or_super(user)

    now = now_iso()
    update_set: Dict[str, Any] = {
        "in_fleet": body.in_fleet,
        "notes": body.notes,
    }
    if body.in_fleet:
        update_set["enabled_by"] = user.get("id")
        update_set["enabled_by_email"] = user.get("email")
        update_set["enabled_at"] = now
    else:
        update_set["disabled_by"] = user.get("id")
        update_set["disabled_by_email"] = user.get("email")
        update_set["disabled_at"] = now

    existing = await db.fleet_membership.find_one(
        {"tenant_id": tenant["id"], "tech_user_id": tech_user_id},
        {"_id": 0},
    )
    if existing:
        await db.fleet_membership.update_one(
            {"tenant_id": tenant["id"], "tech_user_id": tech_user_id},
            {"$set": update_set},
        )
        doc = await db.fleet_membership.find_one(
            {"tenant_id": tenant["id"], "tech_user_id": tech_user_id},
            {"_id": 0},
        )
    else:
        doc = {
            "id": new_id(),
            "tenant_id": tenant["id"],
            "tech_user_id": tech_user_id,
            **update_set,
            "created_at": now,
        }
        await db.fleet_membership.insert_one(doc)
        # ``insert_one`` mutates ``doc`` in place to add the BSON
        # ``_id``; drop it before returning so the response body
        # stays JSON-serialisable.
        doc.pop("_id", None)

    # Audit log — mirror HD-A / SAFE-SEND audit shape.
    try:
        await db.audit_logs.insert_one({
            "id": new_id(),
            "tenant_id": tenant["id"],
            "event": (
                "fleet.membership.enabled"
                if body.in_fleet else "fleet.membership.disabled"
            ),
            "actor_id": user.get("id"),
            "actor_email": user.get("email"),
            "actor_role": (user.get("role") or "").lower(),
            "target_user_id": tech_user_id,
            "notes": body.notes,
            "created_at": now,
        })
    except Exception:                                              # noqa: BLE001
        logger.exception("[fleet.membership] audit insert failed")
    return {"ok": True, "membership": doc}


@router.get("/membership")
async def list_membership(
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    _require_admin_or_super(user)

    # Every technician-role user in the tenant, joined against
    # their fleet_membership row (if any).  Techs with no
    # membership row default to in_fleet=False.
    users_cursor = db.users.find(
        {"tenant_id": tenant["id"],
          "role": {"$in": list(_TECH_ROLES)},
          "$or": [
              {"deleted_at": None},
              {"deleted_at": {"$exists": False}},
          ]},
        {"_id": 0, "id": 1, "name": 1, "email": 1,
         "role": 1, "display_name": 1},
    )
    techs = [row async for row in users_cursor]
    members_cursor = db.fleet_membership.find(
        {"tenant_id": tenant["id"]}, {"_id": 0},
    )
    members = {row["tech_user_id"]: row async for row in members_cursor}

    out: List[Dict[str, Any]] = []
    for t in techs:
        m = members.get(t["id"], {})
        out.append({
            "tech_user_id": t["id"],
            "tech_name": t.get("name") or t.get("display_name") or t.get("email") or t["id"],
            "email": t.get("email"),
            "role": t.get("role"),
            "in_fleet": bool(m.get("in_fleet")),
            "enabled_by_email": m.get("enabled_by_email"),
            "enabled_at": m.get("enabled_at"),
            "disabled_at": m.get("disabled_at"),
            "notes": m.get("notes"),
        })
    return {"count": len(out), "items": out}
