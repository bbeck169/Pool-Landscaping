"""Feb-2026 · Schedule drag-and-drop reorder + Dispatch import.

Two endpoints, admin/manager/super_admin gated:

  POST /api/jobs/reorder
    Body: { tech_user_id, date, ordered_job_ids: [...] }
    Atomically re-numbers ``route_index`` for the listed jobs.
    Avoids N-way PATCH races when the user drops a card mid-list.

  POST /api/dispatch/import-schedule
    Body: { date, tech_user_ids?: [...] }
    Materializes ``dispatch_route_orders`` docs (keyed by weekday +
    tech) from the jobs visible on the Schedule screen for that
    date. Preserves any existing ``route_index`` values on the jobs
    (contiguously renumbered), assigns end-of-list numbers to jobs
    that don't have one. Idempotent — re-running for the same day
    re-syncs missing rows only; existing dispatch_route_orders docs
    are updated with the current ordering.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from config import db
from routers.tenants import get_current_tenant
from utils import get_current_user

router = APIRouter()

_ADMIN_ROLES = {"admin", "super_admin", "manager"}
# Feb-2026 · numbered-order reorder — jobs in a terminal status are
# excluded from the "day set" both on the client (they don't render a
# number input) and on the server (they don't count toward the
# expected N).  Keep this in sync with the schedule pill palette.
_TERMINAL_STATUSES = {
    "completed", "canceled", "cancelled", "skipped", "could_not_service",
}


def _require_admin_or_manager(user: dict) -> None:
    if (user.get("role") or "") not in _ADMIN_ROLES:
        raise HTTPException(403, "admin/manager only")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _date_regex(date: str) -> Dict[str, str]:
    """Match either ``YYYY-MM-DD`` or an ISO datetime prefixed with it."""
    return {"$regex": f"^{re.escape(date)}"}


def _weekday_of(date_str: str) -> str:
    """Return the lowercase weekday name for a YYYY-MM-DD string."""
    d = datetime.strptime(date_str[:10], "%Y-%m-%d")
    return d.strftime("%A").lower()


# ═══════════════════════════════════════════════════════════════════════
# POST /api/jobs/reorder
# ═══════════════════════════════════════════════════════════════════════
class ReorderBody(BaseModel):
    """Accepts two shapes for backwards compat:
      * ``{tech_user_id, date, ordered_job_ids}`` — new (Feb-2026).
      * ``{job_ids}`` — legacy (GridPanel Rearrange mode). We infer
        ``tech_user_id`` + ``date`` from the first job.
    """
    tech_user_id: Optional[str] = None
    date: Optional[str] = Field(None, description="YYYY-MM-DD")
    ordered_job_ids: Optional[List[str]] = None
    job_ids: Optional[List[str]] = None


@router.post("/jobs/reorder",
              operation_id="jobs.reorder",
              tags=["jobs", "schedule"])
async def reorder_jobs(
    body: ReorderBody,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    """Atomically re-number ``route_index`` for the given jobs.

    Match filter is tenant-scoped + tech-scoped + date-scoped, so a
    payload with a cross-tenant id (or a job that doesn't belong to
    this tech) is silently ignored — the response's ``updated`` count
    reflects only real writes. Returns 400 on empty payload.
    """
    _require_admin_or_manager(user)
    ids = body.ordered_job_ids or body.job_ids or []
    if not ids:
        raise HTTPException(400, "ordered_job_ids required")

    # ── Defense-in-depth · duplicate ids in payload ────────────
    # Feb-2026 · numbered-order reorder guardrail.  A duplicate
    # would cause the same job to overwrite its own route_index in
    # the same batch and silently swallow the second write's
    # position; safer to reject up-front with a 422.
    if len(set(ids)) != len(ids):
        raise HTTPException(422, "ordered_job_ids contains duplicate ids")

    tenant_id = tenant["id"]
    tech_user_id = body.tech_user_id
    date = body.date

    # Legacy payload — infer tech + date from the first job.
    if not tech_user_id or not date:
        first = await db.jobs.find_one(
            {"id": ids[0], "tenant_id": tenant_id},
            {"_id": 0, "tech_user_id": 1, "technician_id": 1,
             "assigned_to": 1, "scheduled_date": 1},
        )
        if not first:
            raise HTTPException(400, "cannot infer tech/date — first job not found")
        tech_user_id = tech_user_id or (
            first.get("tech_user_id") or first.get("assigned_to")
            or first.get("technician_id"))
        if not date:
            sd = first.get("scheduled_date") or ""
            date = sd[:10]
        if not tech_user_id or not date:
            raise HTTPException(400, "tech_user_id and date required")

    tech_match = {"$or": [
        {"tech_user_id": tech_user_id},
        {"assigned_to": tech_user_id},
        {"technician_id": tech_user_id},
    ]}
    day_filter = {
        "tenant_id": tenant_id,
        "scheduled_date": _date_regex(date),
        **tech_match,
    }

    # ── Defense-in-depth · set completeness ─────────────────────
    # Fetch every non-terminal job on this (tenant, tech, date) and
    # require the payload's id set to match it exactly.  This
    # prevents partial reorders (which would silently leave some
    # jobs at their old ``route_index`` and produce an inconsistent
    # visual order after the next reload) and cross-day/cross-tech
    # ids (which the per-job update filter would silently drop).
    day_jobs: List[Dict[str, Any]] = []
    async for j in db.jobs.find(day_filter, {"_id": 0, "id": 1, "status": 1}):
        if (j.get("status") or "").lower() in _TERMINAL_STATUSES:
            continue
        day_jobs.append(j)
    day_ids = {j["id"] for j in day_jobs}
    submitted = set(ids)
    if submitted != day_ids:
        missing = sorted(day_ids - submitted)
        extra = sorted(submitted - day_ids)
        reason_bits = []
        if missing:
            reason_bits.append(f"missing {len(missing)} job(s)")
        if extra:
            reason_bits.append(
                f"{len(extra)} job(s) not on this tech's {date}",
            )
        reason = "; ".join(reason_bits) or "set mismatch"
        raise HTTPException(
            422,
            f"ordered_job_ids must be the exact set of non-terminal jobs "
            f"on this tech's day — {reason}",
        )

    updated = 0
    for i, jid in enumerate(ids):
        r = await db.jobs.update_one(
            {"id": jid, **day_filter},
            {"$set": {
                "route_index": i,
                "route_reordered_at": _now_iso(),
                "route_reordered_by": user.get("id"),
            }},
        )
        if r.matched_count:
            updated += 1

    # Best-effort dispatch_route_orders upsert so the Dispatch Board
    # reflects the new order without a follow-up import call.  Not
    # fatal on failure — the schedule persistence has already
    # succeeded above.
    try:
        ordered_customer_ids: List[str] = []
        async for j in db.jobs.find(
            {"id": {"$in": ids}, "tenant_id": tenant_id},
            {"_id": 0, "id": 1, "customer_id": 1},
        ):
            ordered_customer_ids.append((j.get("id"), j.get("customer_id")))
        # Preserve payload order.
        by_id = {jid: cid for jid, cid in ordered_customer_ids}
        ordered_customer_ids = [
            by_id.get(jid) for jid in ids if by_id.get(jid)
        ]
        weekday = _weekday_of(date)
        await db.dispatch_route_orders.update_one(
            {"tenant_id": tenant_id, "day": weekday,
             "tech_user_id": tech_user_id},
            {"$set": {
                "tenant_id": tenant_id, "day": weekday,
                "tech_user_id": tech_user_id,
                "ordered_customer_ids": ordered_customer_ids,
                "updated_at": _now_iso(),
                "updated_by": user.get("id"),
                "source": "schedule_reorder",
                "source_date": date,
            }},
            upsert=True,
        )
    except Exception:
        pass

    return {
        "ok": True,
        "updated": updated,
        "expected": len(ids),
        "tech_user_id": tech_user_id,
        "date": date,
    }


# ═══════════════════════════════════════════════════════════════════════
# POST /api/dispatch/import-schedule
# ═══════════════════════════════════════════════════════════════════════
class ImportBody(BaseModel):
    date: str = Field(..., description="YYYY-MM-DD")
    tech_user_ids: Optional[List[str]] = None


@router.post("/dispatch/import-schedule",
              operation_id="dispatch.importSchedule",
              tags=["dispatch", "schedule"])
async def import_schedule(
    body: ImportBody,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    """Seed the Dispatch Board with the day's scheduled jobs.

    For each tech that has jobs on ``date``:
      * Preserve existing ``route_index`` values on those jobs.
      * Assign contiguous ``route_index`` (0..N-1) to jobs that
        don't have one yet, appended to the end of the current list.
      * Upsert a ``dispatch_route_orders`` doc keyed by
        ``(tenant_id, day=<weekday>, tech_user_id)`` with the ordered
        ``customer_ids`` (Dispatch Board's data contract).

    Idempotent: re-running for the same date syncs any newly-added
    jobs into the same dispatch_route_orders doc without duplicating
    existing entries. Route ordering is preserved when the schedule
    hasn't materially changed.
    """
    _require_admin_or_manager(user)
    tenant_id = tenant["id"]
    weekday = _weekday_of(body.date)

    # Pull the day's jobs. Tech filter is optional.
    q: Dict[str, Any] = {
        "tenant_id": tenant_id,
        "scheduled_date": _date_regex(body.date),
    }
    if body.tech_user_ids:
        q["$or"] = [
            {"tech_user_id": {"$in": body.tech_user_ids}},
            {"assigned_to": {"$in": body.tech_user_ids}},
            {"technician_id": {"$in": body.tech_user_ids}},
        ]

    # Group jobs by their effective tech id (fallback chain).
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    async for j in db.jobs.find(q, {"_id": 0, "id": 1, "customer_id": 1,
                                      "tech_user_id": 1, "technician_id": 1,
                                      "assigned_to": 1, "route_index": 1}):
        tech = (j.get("tech_user_id") or j.get("assigned_to")
                or j.get("technician_id"))
        if not tech:
            continue
        grouped.setdefault(tech, []).append(j)

    techs_written = 0
    jobs_indexed = 0
    routes_written = 0
    for tech_id, jobs in grouped.items():
        # Preserve current route_index; missing → append at end.
        with_idx = [j for j in jobs if isinstance(j.get("route_index"), int)]
        without_idx = [j for j in jobs if j not in with_idx]
        with_idx.sort(key=lambda j: j.get("route_index", 0))
        # Renumber contiguously.
        ordered = with_idx + without_idx
        for i, j in enumerate(ordered):
            if j.get("route_index") != i:
                await db.jobs.update_one(
                    {"id": j["id"], "tenant_id": tenant_id},
                    {"$set": {"route_index": i,
                              "route_source": "schedule_import",
                              "route_reordered_at": _now_iso()}},
                )
                jobs_indexed += 1

        ordered_customer_ids = [j["customer_id"] for j in ordered
                                 if j.get("customer_id")]
        r = await db.dispatch_route_orders.update_one(
            {"tenant_id": tenant_id, "day": weekday,
             "tech_user_id": tech_id},
            {"$set": {
                "tenant_id": tenant_id, "day": weekday,
                "tech_user_id": tech_id,
                "ordered_customer_ids": ordered_customer_ids,
                "updated_at": _now_iso(),
                "updated_by": user.get("id"),
                "source": "schedule_import",
                "source_date": body.date,
            }},
            upsert=True,
        )
        techs_written += 1
        if r.upserted_id or r.modified_count:
            routes_written += 1

    return {
        "ok": True,
        "date": body.date,
        "weekday": weekday,
        "techs_written": techs_written,
        "routes_written": routes_written,
        "jobs_indexed": jobs_indexed,
        "job_count": sum(len(v) for v in grouped.values()),
    }
