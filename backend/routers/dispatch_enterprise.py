"""EMV · Feb-2026 — Enterprise Map View (dispatch bird's-eye).

READ-ONLY endpoint that returns every technician's jobs across a
date window (default 7 days, max 14) so dispatchers can render an
interactive map + polylines of every route in the company in a
single fetch.

Contract locks:
  * ``GET /api/dispatch/enterprise-view`` — admin/super_admin/manager only.
  * Query params: ``start_date`` (YYYY-MM-DD, defaults to today UTC),
    ``end_date`` (YYYY-MM-DD, defaults to ``start_date + 6``).
  * Span cap: 14 days inclusive → 400 above.
  * Truncation cap: 2000 jobs per response. ``truncated=True`` when
    the raw match count exceeds the cap. Additional jobs are trimmed
    from the tail (latest scheduled_date + highest route_index).
  * Tenant-scoped. HD-A soft-delete filter applied via
    ``utils.not_deleted_filter()``.
  * Deterministic per-request color fallback for technicians whose
    ``display_color_hex`` is missing. Uses
    ``constants.tech_colors.deterministic_color_for_id`` (SHA-256 →
    palette[hash % N]). NO DB WRITE — the color is computed per
    response and never persisted.
  * Index-covered query: relies on
    ``diag_jobs_tenant_sched_route_idx`` = ``(tenant_id,
    scheduled_date, route_index, created_at)`` (see
    ``migrations/diag_schedule_dispatch_indexes.py``). Additive-only;
    this endpoint does not create new indexes.

Response shape:
    {
      "start_date": "YYYY-MM-DD",
      "end_date":   "YYYY-MM-DD",
      "days_in_range": int,
      "technicians": [
        {"id", "name", "display_color_hex", "color_source",
          "job_count"}
      ],
      "jobs": [
        {"id", "customer_id", "customer_name", "technician_id",
          "scheduled_date", "route_index", "lat", "lng",
          "address", "service_type", "title", "status",
          "has_coordinates"}
      ],
      "missing_coordinates_count": int,
      "truncated": bool,
      "total_jobs_matched": int,
      "cap": 2000
    }
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from config import db
from constants.tech_colors import deterministic_color_for_id
from routers.tenants import get_current_tenant
from utils import get_current_user, not_deleted_filter

router = APIRouter()

_READ_ROLES = {"admin", "super_admin", "manager", "owner"}

# Contract locks referenced by tests + docstring above.
MAX_SPAN_DAYS = 14
DEFAULT_SPAN_DAYS = 7
JOB_TRUNCATION_CAP = 2000


def _require_read(user: dict) -> None:
    if (user or {}).get("role") not in _READ_ROLES:
        raise HTTPException(
            status_code=403,
            detail="Enterprise Map View is admin, manager, or super_admin only",
        )


def _parse_date(value: Optional[str], *, param: str) -> Optional[date]:
    if value is None or value == "":
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"{param} must be YYYY-MM-DD (got {value!r})",
        ) from exc


def _coord(job: Dict[str, Any]) -> tuple[Optional[float], Optional[float]]:
    """Preferred order matches ``services.geo_resolver.resolve_job_coordinates``:
    ``site_lat/site_lng`` first, then ``lat/lng``, then ``latitude/longitude``.
    """
    for lat_k, lng_k in (
        ("site_lat", "site_lng"),
        ("lat", "lng"),
        ("latitude", "longitude"),
    ):
        lat = job.get(lat_k)
        lng = job.get(lng_k)
        if lat is not None and lng is not None:
            try:
                return float(lat), float(lng)
            except (TypeError, ValueError):
                continue
    return None, None


@router.get(
    "/dispatch/enterprise-view",
    tags=["dispatch"],
    operation_id="dispatch.enterpriseView",
)
async def get_enterprise_view(
    start_date: Optional[str] = Query(
        None,
        description=(
            "YYYY-MM-DD window start (inclusive). Defaults to today (UTC) "
            "when omitted."
        ),
    ),
    end_date: Optional[str] = Query(
        None,
        description=(
            "YYYY-MM-DD window end (inclusive). Defaults to "
            "``start_date + 6`` when omitted. Span must be ≤14 days."
        ),
    ),
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    """Return every technician's jobs across a 7-day (default) window
    for the enterprise dispatch map. Read-only, tenant-scoped, HD-A
    soft-delete-aware.
    """
    _require_read(user)

    start = _parse_date(start_date, param="start_date")
    end = _parse_date(end_date, param="end_date")
    if start is None:
        start = datetime.now(timezone.utc).date()
    if end is None:
        end = start + timedelta(days=DEFAULT_SPAN_DAYS - 1)
    if end < start:
        raise HTTPException(
            status_code=400,
            detail="end_date must be on or after start_date",
        )
    span = (end - start).days + 1
    if span > MAX_SPAN_DAYS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"date range spans {span} days; max {MAX_SPAN_DAYS} allowed. "
                f"Narrow start_date/end_date."
            ),
        )

    start_iso = start.isoformat()
    end_iso = end.isoformat()

    # ── Job fetch ──────────────────────────────────────────────────
    # Index-covered by ``diag_jobs_tenant_sched_route_idx``:
    # (tenant_id, scheduled_date, route_index, created_at).
    job_query: Dict[str, Any] = {
        "tenant_id": tenant["id"],
        "scheduled_date": {"$gte": start_iso, "$lte": end_iso},
        **not_deleted_filter(),
    }

    # Total matched (pre-truncation) for the ``truncated`` flag +
    # accurate ``total_jobs_matched`` in the response body.
    total_matched = await db.jobs.count_documents(job_query)
    truncated = total_matched > JOB_TRUNCATION_CAP

    cursor = db.jobs.find(
        job_query,
        {
            "_id": 0, "id": 1,
            "customer_id": 1, "customer_name": 1,
            "technician_id": 1, "assigned_to": 1, "tech_user_id": 1,
            "scheduled_date": 1, "route_index": 1, "created_at": 1,
            "site_lat": 1, "site_lng": 1, "lat": 1, "lng": 1,
            "latitude": 1, "longitude": 1,
            "address": 1, "service_type": 1, "title": 1, "status": 1,
        },
    ).sort([
        ("scheduled_date", 1),
        ("route_index", 1),
        ("created_at", 1),
    ])
    raw_jobs = await cursor.to_list(JOB_TRUNCATION_CAP)

    # ── Technician directory (users role=technician for this tenant)
    # We also union any assigned_to / technician_id / tech_user_id
    # referenced by the returned jobs so a job assigned to a deleted
    # user still surfaces on the map (with a fallback color).
    referenced_tech_ids: set[str] = set()
    for j in raw_jobs:
        for key in ("technician_id", "assigned_to", "tech_user_id"):
            v = j.get(key)
            if v:
                referenced_tech_ids.add(v)

    tech_docs: List[Dict[str, Any]] = []
    async for u in db.users.find(
        {"tenant_id": tenant["id"], "role": "technician"},
        {"_id": 0, "id": 1, "name": 1, "email": 1,
          "display_color_hex": 1},
    ):
        tech_docs.append(u)

    # Also pick up any referenced-but-missing tech ids from db.users
    # (e.g. legacy assigned_to values pointing at admin/manager rows).
    known_ids = {t["id"] for t in tech_docs if t.get("id")}
    missing_refs = [tid for tid in referenced_tech_ids if tid not in known_ids]
    if missing_refs:
        async for u in db.users.find(
            {"tenant_id": tenant["id"], "id": {"$in": missing_refs}},
            {"_id": 0, "id": 1, "name": 1, "email": 1,
              "display_color_hex": 1},
        ):
            tech_docs.append(u)
            known_ids.add(u["id"])

    tech_by_id: Dict[str, Dict[str, Any]] = {}
    for t in tech_docs:
        tid = t.get("id")
        if not tid:
            continue
        stored = t.get("display_color_hex")
        if stored:
            color = stored
            color_source = "db"
        else:
            # DETERMINISTIC PER-REQUEST FALLBACK. Never mutates the DB.
            color = deterministic_color_for_id(tid)
            color_source = "hash_fallback"
        tech_by_id[tid] = {
            "id": tid,
            "name": t.get("name") or t.get("email") or tid,
            "display_color_hex": color,
            "color_source": color_source,
            "job_count": 0,
        }

    # ── Job payload ────────────────────────────────────────────────
    jobs_out: List[Dict[str, Any]] = []
    missing_coords_count = 0
    for j in raw_jobs:
        # Resolve owning tech (job.technician_id preferred, then
        # assigned_to, then tech_user_id). Same precedence as
        # dispatch_reassign + schedule_ai apply path.
        tech_id = (
            j.get("technician_id")
            or j.get("assigned_to")
            or j.get("tech_user_id")
        )
        # If tech_id references someone missing from the directory,
        # inject a synthetic entry so the map can still colour the
        # pin (deterministic fallback). This never writes to the DB.
        if tech_id and tech_id not in tech_by_id:
            tech_by_id[tech_id] = {
                "id": tech_id,
                "name": tech_id,
                "display_color_hex": deterministic_color_for_id(tech_id),
                "color_source": "hash_fallback",
                "job_count": 0,
            }
        lat, lng = _coord(j)
        has_coords = lat is not None and lng is not None
        if not has_coords:
            missing_coords_count += 1
        if tech_id and tech_id in tech_by_id:
            tech_by_id[tech_id]["job_count"] += 1
        jobs_out.append({
            "id": j.get("id"),
            "customer_id": j.get("customer_id"),
            "customer_name": j.get("customer_name") or "",
            "technician_id": tech_id,
            "scheduled_date": j.get("scheduled_date"),
            "route_index": j.get("route_index"),
            "lat": lat,
            "lng": lng,
            "address": j.get("address") or "",
            "service_type": j.get("service_type") or "",
            "title": j.get("title") or "",
            "status": j.get("status") or "",
            "has_coordinates": has_coords,
        })

    technicians_out = sorted(
        tech_by_id.values(),
        key=lambda t: ((t.get("job_count") or 0) * -1,
                        (t.get("name") or "").lower()),
    )

    return {
        "start_date": start_iso,
        "end_date": end_iso,
        "days_in_range": span,
        "technicians": technicians_out,
        "jobs": jobs_out,
        "missing_coordinates_count": missing_coords_count,
        "truncated": truncated,
        "total_jobs_matched": total_matched,
        "cap": JOB_TRUNCATION_CAP,
    }
