"""Feb-2026 · Reports Gap Fill Phase 5a.1 — Business Snapshot.

Current-state snapshot for a tenant. Three tiles:

  1. ``service_radius``      — tenant setting + last-30-days avg
                                company↔customer distance (when
                                computable).
  2. ``employee_count``      — active technicians in the tenant.
  3. ``bh_per_week_capacity`` — total budgeted hours/week across
                                active technicians. Falls back to
                                ``count * 40`` when techs don't
                                carry an explicit ``weekly_hours``
                                field (matches the app's canonical
                                ``overtime_weekly_hours=40``).

No date range — the snapshot is current-state only. Stamped with
a ``computed_at`` ISO timestamp so a CSV export is auditable.

Tenant-scoped by default. ``tenant_id=`` query param is honored
ONLY for ``super_admin``; other roles are locked to their own
tenant.

See ``/app/memory/FEATURE_REPORTS_GAP_FILL_PHASE5A_1.md`` for the
number-parity rationale and the "why avg_last_30d_miles can be
None" note.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from config import db, logger
from routers.tenants import get_current_tenant
from utils import get_current_user

router = APIRouter(tags=["reports"])


# ─── Canonical active-tech set (mirrors routers/technicians.py) ───
_ASSIGNABLE_ROLES = [
    "technician", "tech", "landscaper",
    "landscape_tech", "pool_tech", "tech_both",
]


async def _active_technicians_for_tenant(tenant_id: str) -> list[dict]:
    """Return the deduped active-technicians set for a tenant.
    Union of ``db.technicians`` rows + ``db.users`` rows with an
    assignable role, deduped by ``user_id`` (matches the shape
    consumed by ``routers/technicians.py::list_technicians`` so
    the count agrees byte-for-byte with the roster surface)."""
    tech_docs = await db.technicians.find(
        {"tenant_id": tenant_id},
        {"_id": 0, "id": 1, "user_id": 1, "weekly_hours": 1, "name": 1,
         "active": 1, "deleted_at": 1},
    ).to_list(2000)
    tech_docs = [
        t for t in tech_docs
        if t.get("active") is not False and not t.get("deleted_at")
    ]
    linked_user_ids: set = {t.get("user_id") for t in tech_docs
                              if t.get("user_id")}
    synth: list[dict] = []
    async for u in db.users.find(
        {"tenant_id": tenant_id,
         "role": {"$in": _ASSIGNABLE_ROLES},
         "email": {"$not": {"$regex": r"@t\.local$", "$options": "i"}},
         "$and": [
             {"$or": [{"deleted_at": None},
                        {"deleted_at": {"$exists": False}}]},
             {"$or": [{"active": {"$ne": False}},
                        {"active": {"$exists": False}}]},
         ]},
        {"_id": 0, "id": 1, "weekly_hours": 1, "hours_per_week": 1,
         "role": 1, "technician_id": 1},
    ):
        if u.get("id") in linked_user_ids:
            continue
        if u.get("technician_id") in {t.get("id") for t in tech_docs}:
            continue
        synth.append(u)
    return tech_docs + synth


def _weekly_hours_for(row: dict) -> float:
    """Extract the tech's budgeted weekly hours. Honors the
    canonical field names and falls back to the app-wide default
    (40 hrs/week, matching ``workforce.overtime_weekly_hours``)."""
    for k in ("weekly_hours", "hours_per_week", "budgeted_hours_per_week"):
        v = row.get(k)
        if v is None:
            continue
        try:
            fv = float(v)
            if fv > 0:
                return fv
        except (TypeError, ValueError):
            continue
    return 40.0


async def _avg_last_30d_distance_miles(tenant_id: str) -> Optional[float]:
    """Best-effort average customer distance from the tenant hub
    over the last 30 days. Returns ``None`` when the tenant lacks
    hub coordinates or no completed jobs in the window carry a
    ``distance_miles`` denormalization. We do NOT synthesize
    distances from raw lat/lng here — the truthful stance is
    "unknown" if the source docs don't carry a computed distance,
    so ops sees ``None`` in the export rather than a fabricated
    number."""
    since = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    total_miles = 0.0
    count = 0
    cursor = db.jobs.find(
        {"tenant_id": tenant_id,
         "$or": [{"completed_at": {"$gte": since}},
                   {"created_at":   {"$gte": since}}]},
        {"_id": 0, "distance_miles": 1},
    )
    async for j in cursor:
        v = j.get("distance_miles")
        try:
            fv = float(v) if v is not None else None
        except (TypeError, ValueError):
            fv = None
        if fv is not None and fv >= 0:
            total_miles += fv
            count += 1
    if count == 0:
        return None
    return round(total_miles / count, 2)


@router.get(
    "/reports/business-snapshot",
    operation_id="reports.businessSnapshot",
    summary="Business Snapshot — current-state tiles",
)
async def business_snapshot(
    tenant_id: Optional[str] = Query(
        None,
        description="super_admin only — override the tenant scope",
    ),
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    """Return the current-state snapshot for a tenant. Non-super-
    admin callers are locked to their own tenant; ``tenant_id=``
    is honored only when ``user.role == 'super_admin'``."""
    role = (user.get("role") or "").strip().lower()
    if tenant_id and role != "super_admin":
        raise HTTPException(
            status_code=403,
            detail="tenant_id override requires super_admin",
        )
    effective_tid: str = (tenant_id or tenant["id"]).strip()
    if not effective_tid:
        raise HTTPException(400, "tenant scope missing")

    tenant_doc = await db.tenants.find_one(
        {"id": effective_tid}, {"_id": 0},
    )
    if not tenant_doc:
        raise HTTPException(404, "tenant not found")

    max_radius_miles = tenant_doc.get("service_radius")
    try:
        max_radius_miles = (
            float(max_radius_miles) if max_radius_miles is not None else None
        )
    except (TypeError, ValueError):
        logger.warning(
            "[business-snapshot] tenant %s has non-numeric "
            "service_radius=%r — treating as unset",
            effective_tid, tenant_doc.get("service_radius"),
        )
        max_radius_miles = None

    active_techs = await _active_technicians_for_tenant(effective_tid)
    employee_count = len(active_techs)
    bh_per_week = round(sum(_weekly_hours_for(t) for t in active_techs), 2)

    avg_last_30d = await _avg_last_30d_distance_miles(effective_tid)

    return {
        "service_radius": {
            "max_miles":         max_radius_miles,
            "avg_last_30d_miles": avg_last_30d,
        },
        "employee_count":       employee_count,
        "bh_per_week_capacity": bh_per_week,
        "tenant_id":  effective_tid,
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }
