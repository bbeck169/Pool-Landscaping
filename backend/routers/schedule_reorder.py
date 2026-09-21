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
from utils import not_deleted_filter as _nd

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

    Feb-2026 · P1 parity with the web ``MAX_ORDER_VALUE = 50`` guard in
    ``NumberedReorder.jsx``. 50 aligns with the offline-cache window
    and is safely above the busiest observed tech day (~30 stops).
    """
    tech_user_id: Optional[str] = None
    date: Optional[str] = Field(None, description="YYYY-MM-DD")
    ordered_job_ids: Optional[List[str]] = Field(None, max_length=50)
    job_ids: Optional[List[str]] = Field(None, max_length=50)


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

    # ── Phase P10 · Feb-2026 — Technician pin-to-self ──
    # Defensive: the outer admin gate above already rejects
    # technician callers with 403, but if a future scope widening
    # opens this endpoint to techs, the P9 jail contract requires
    # a silent lane-pin (never let a technician reorder another
    # lane's jobs). Kept as an early-return no-op today.
    if (user.get("role") or "").lower() == "technician":
        pinned = user.get("technician_id") or user.get("id")
        if pinned:
            tech_user_id = pinned

    # Legacy payload — infer tech + date from the first job.
    if not tech_user_id or not date:
        first = await db.jobs.find_one(
            {"id": ids[0], "tenant_id": tenant_id},
            {"_id": 0, "tech_user_id": 1, "technician_id": 1,
             "assigned_technician_id": 1, "assigned_to": 1,
             "crew_id": 1, "scheduled_date": 1},
        )
        if not first:
            raise HTTPException(400, "cannot infer tech/date — first job not found")
        # Phase P10 · Feb-2026 — the "lane" a job belongs to can be
        # any of the 4 tech-assignment fields OR ``crew_id`` when
        # the job is assigned by crew alone. Prefer the tech
        # fields (existing behaviour) but fall through to crew so
        # crew-only jobs no longer 400 with "tech_user_id required".
        tech_user_id = tech_user_id or (
            first.get("tech_user_id") or first.get("assigned_to")
            or first.get("technician_id")
            or first.get("assigned_technician_id")
            or first.get("crew_id"))
        if not date:
            sd = first.get("scheduled_date") or ""
            date = sd[:10]
        if not tech_user_id or not date:
            raise HTTPException(400, "tech_user_id and date required")

    # ── Phase P10 · Feb-2026 — widen the lane filter ──
    # Pre-P10 shape was ``$or: [tech_user_id, assigned_to,
    # technician_id]`` — silently dropped every crew-only job.
    # Widen the disjunction to match the P9 jail's helper
    # (``build_tech_field_or_clause``) PLUS ``crew_id`` so a lane
    # id can resolve as either a technician identifier or a crew
    # identifier without server-side disambiguation.
    #
    # Phase P10 · Feb-2026 — soft-delete + tech-match $and merge.
    # Both the tech-lane disjunction and ``not_deleted_filter``
    # return ``$or``; a naive dict spread would silently drop one
    # of them (the second key wins) — that regression collapsed
    # the filter to "any non-deleted job on this date for the
    # tenant" and matched Carlos's jobs on Mike's lane. Nest both
    # under ``$and`` — same shape the day-route endpoint uses.
    tech_or = [
        {"tech_user_id": tech_user_id},
        {"assigned_to": tech_user_id},
        {"technician_id": tech_user_id},
        {"assigned_technician_id": tech_user_id},
        {"crew_id": tech_user_id},
    ]
    day_filter = {
        "tenant_id": tenant_id,
        "scheduled_date": _date_regex(date),
        "$and": [
            {"$or": tech_or},
            _nd(),
        ],
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
        # ── Phase P10 · Feb-2026 — 409 lane-mismatch semantics ──
        # Pre-P10 shape was a flat 422 with a text reason. Split
        # into two structured 409 codes so the client can render a
        # specific banner ("Assign a technician or crew…" vs
        # "Reorder within a single lane"). The 409 still returns
        # ``missing_job_ids`` (submitted ids that aren't on the
        # requested lane) — those are the outsiders that were
        # dragged across a lane boundary. Cross-tenant ids surface
        # through this branch too (they can't match the lane
        # filter). Also inspect the tenant-wide set to distinguish
        # "unassigned job in this tenant" from "wrong lane".
        outsiders = sorted(submitted - day_ids)
        if outsiders:
            # Check whether any outsider is an unassigned job in
            # THIS tenant — surface as a distinct code so the UI
            # can nudge the operator to assign a tech/crew first.
            unassigned: List[str] = []
            async for j in db.jobs.find(
                {"id": {"$in": outsiders}, "tenant_id": tenant_id},
                {"_id": 0, "id": 1, "technician_id": 1,
                 "assigned_technician_id": 1, "assigned_to": 1,
                 "tech_user_id": 1, "crew_id": 1},
            ):
                if not any(j.get(k) for k in (
                    "technician_id", "assigned_technician_id",
                    "assigned_to", "tech_user_id", "crew_id",
                )):
                    unassigned.append(j["id"])
            if unassigned:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code":     "reorder_unassigned_job",
                        "job_ids":  sorted(unassigned),
                        "lane_id":  tech_user_id,
                    },
                )
        raise HTTPException(
            status_code=409,
            detail={
                "code":            "reorder_lane_mismatch",
                "missing_job_ids": outsiders,
                "lane_id":         tech_user_id,
            },
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
# POST /api/jobs/reorder-day-route  · Sprint 3d (Feb-2026)
# ═══════════════════════════════════════════════════════════════════════
class ReorderDayRouteBody(BaseModel):
    """Insert-and-shift reorder — moves ONE job to ``new_position``
    and contiguously renumbers the rest of the day's non-terminal
    jobs.

    ``technician_id`` maps to whichever of ``tech_user_id`` /
    ``assigned_to`` / ``technician_id`` the job carries — see the
    tech-match ``$or`` filter below.

    Positions are **1-indexed** in the API surface (matches the UX);
    persisted internally as 0-indexed ``route_index``.
    """
    date: str = Field(..., description="YYYY-MM-DD (tenant-tz aware)")
    technician_id: str
    job_id: str
    new_position: int = Field(..., description="1-indexed target slot")


@router.post("/jobs/reorder-day-route",
              operation_id="jobs.reorder_day_route",
              tags=["jobs", "schedule"])
async def reorder_day_route(
    body: ReorderDayRouteBody,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    """Sprint 3d · Feb-2026 — insert-and-shift reorder with
    **immovable completed-job anchors**.

    Semantics (user-confirmed clarification, Feb-2026):
        1. Fetch every job for ``(tenant, technician_id, date)``
           sorted by current ``route_index``.  N = total slots
           (anchors + incomplete jobs), numbered 1..N in the
           API surface.
        2. Terminal-status jobs (completed / cancelled /
           skipped) are **immovable anchors** — their
           ``route_index`` is frozen and never rewritten.
        3. ``new_position`` is clamped to the nearest non-anchor
           slot only when it is *out of range* (``≤ 0`` or ``> N``).
           A value that lands in-range but on an anchor slot is
           **rejected** with ``409 slot_occupied_by_completed_job``
           so the UI can surface a helpful "that slot is locked"
           message rather than silently displacing a completed job.
        4. Splice ``job_id`` out of the free-jobs list, insert at
           the target free-slot index, then re-assign the free
           slots in order.  Anchors keep their slot.
        5. Persist per-job ``route_index`` updates for the moved
           subset (anchors are left untouched).  Partial-state
           failures are logged; the endpoint still returns the
           persisted subset so the frontend can reflect reality.
        6. Return the FULL renumbered list — including anchors
           with ``is_anchor: true`` — so the client can drop its
           local state and paint the new order without a
           follow-up GET.

    Auth: admin / manager / super_admin (mirrors ``/jobs/reorder``).

    Day-boundary note: scoped to ``(tenant, technician_id, date)``
    with a ``scheduled_date`` prefix match (``YYYY-MM-DD``).  This
    matches the rest of the codebase (see ``routers/jobs.py`` line
    509) — callers pass the tenant-local calendar day and jobs are
    stored with ``scheduled_date`` in that same local calendar day.
    Not a UTC-midnight comparison.
    """
    _require_admin_or_manager(user)
    tenant_id = tenant["id"]
    date = body.date
    technician_id = body.technician_id
    job_id = body.job_id
    typed = int(body.new_position)

    # Build the day filter. NOTE: both the tech-id ``$or`` and the
    # soft-delete ``$or`` (from ``not_deleted_filter``) claim the
    # same ``$or`` key at the top level, so we must nest them under
    # ``$and`` — a plain dict merge would silently drop the tech
    # filter and match every tech on the day.
    #
    # Phase P10 · Feb-2026 — widen the lane filter to match the
    # bulk endpoint's disjunction (matches P9 jail's assignment
    # field set plus ``crew_id`` for crew-assigned jobs).
    tech_or = [
        {"tech_user_id":            technician_id},
        {"assigned_to":             technician_id},
        {"technician_id":           technician_id},
        {"assigned_technician_id":  technician_id},
        {"crew_id":                 technician_id},
    ]
    day_filter = {
        "tenant_id":      tenant_id,
        "scheduled_date": _date_regex(date),
        "$and": [
            {"$or": tech_or},
            _nd(),
        ],
    }

    # ── 1. Fetch ALL day jobs (anchors + incomplete). ─────────
    day_jobs: List[Dict[str, Any]] = []
    async for j in db.jobs.find(
        day_filter,
        {"_id": 0, "id": 1, "status": 1, "route_index": 1,
         "customer_id": 1},
    ):
        day_jobs.append(j)

    if not day_jobs:
        raise HTTPException(404, "no jobs on this tech's day")

    # Sort by current route_index (missing → end of list).
    day_jobs.sort(key=lambda j: j.get("route_index")
                    if isinstance(j.get("route_index"), int) else 10**6)
    n = len(day_jobs)

    # Classify anchor vs free by 0-indexed slot.
    anchor_positions: set[int] = set()
    free_positions: List[int] = []
    for i, j in enumerate(day_jobs):
        if (j.get("status") or "").lower() in _TERMINAL_STATUSES:
            anchor_positions.add(i)
        else:
            free_positions.append(i)

    if not free_positions:
        raise HTTPException(404, "no non-terminal jobs on this tech's day")

    # Target job must exist and be non-terminal.
    target = next((j for j in day_jobs if j["id"] == job_id), None)
    if target is None:
        raise HTTPException(404, "job_id not on this tech's day")
    if (target.get("status") or "").lower() in _TERMINAL_STATUSES:
        raise HTTPException(404, "job_id is a completed/terminal anchor and cannot be reordered")

    current_idx = day_jobs.index(target)  # 0-indexed absolute slot
    current_position = current_idx + 1    # 1-indexed for messaging

    # ── 2. Clamp OUT-OF-RANGE positions to nearest free slot. ─
    if typed < 1:
        target_idx = free_positions[0]
    elif typed > n:
        target_idx = free_positions[-1]
    else:
        target_idx = typed - 1
    target_position = target_idx + 1  # 1-indexed

    # ── 3. Anchor collision guard (in-range hitting anchor). ──
    if target_idx in anchor_positions:
        anchor_job_id = day_jobs[target_idx]["id"]
        raise HTTPException(
            status_code=409,
            detail={
                "code":                "slot_occupied_by_completed_job",
                "message": (
                    f"Position {target_position} is occupied by a completed "
                    f"job and cannot be reassigned. Completed jobs are locked "
                    f"in place — pick a different position."
                ),
                "requested_position":  target_position,
                "anchor_job_id":       anchor_job_id,
                "n":                   n,
                "free_positions": [p + 1 for p in free_positions],
            },
        )

    # ── 4. Same-position no-op. ───────────────────────────────
    if target_idx == current_idx:
        renumbered = [
            {"job_id": j["id"],
             "sequence_number": i + 1,
             "is_anchor": i in anchor_positions}
            for i, j in enumerate(day_jobs)
        ]
        return {
            "success":          True,
            "changed":          False,
            "renumbered":       renumbered,
            "tech_user_id":     technician_id,
            "date":             date,
            "old_position":     current_position,
            "new_position":     target_position,
            "affected_job_ids": [],
            "updated_count":    0,
            "n":                n,
        }

    # ── 5. Splice & insert on free-jobs list. ─────────────────
    # Free jobs in their current absolute order (anchor slots
    # skipped). ``free_positions`` is the sorted list of absolute
    # 0-indexed slot numbers reserved for non-anchor jobs.
    free_jobs = [day_jobs[p] for p in free_positions]
    # Remove the moved job from the free list…
    free_jobs = [j for j in free_jobs if j["id"] != job_id]
    # …then insert it at the free-list index corresponding to the
    # chosen absolute slot. ``free_positions.index(target_idx)`` is
    # the index within the free-slot sequence.
    insert_at_free_idx = free_positions.index(target_idx)
    free_jobs.insert(insert_at_free_idx, target)

    # Build the new absolute list: fill anchors at their frozen
    # slots and place free_jobs into the free slots (in order).
    new_day_jobs: List[Dict[str, Any]] = [None] * n  # type: ignore[list-item]
    for i, j in enumerate(day_jobs):
        if i in anchor_positions:
            new_day_jobs[i] = j
    for slot, j in zip(free_positions, free_jobs):
        new_day_jobs[slot] = j

    # ── 6. Persist route_index for jobs whose slot changed. ──
    now = _now_iso()
    partial_error: Optional[str] = None
    persisted = 0
    changed_ids: List[str] = []
    for new_i, j in enumerate(new_day_jobs):
        if new_i in anchor_positions:
            continue  # anchor — frozen
        # Find the job's OLD 0-indexed slot to skip no-op writes.
        old_i = day_jobs.index(j)
        if old_i == new_i:
            continue
        changed_ids.append(j["id"])
        try:
            r = await db.jobs.update_one(
                {"id": j["id"], **day_filter},
                {"$set": {
                    "route_index":         new_i,
                    "route_reordered_at":  now,
                    "route_reordered_by":  user.get("id"),
                }},
            )
            if r.matched_count:
                persisted += 1
        except Exception as exc:                                   # noqa: BLE001
            import logging
            logging.getLogger("schedule_reorder.day_route").warning(
                "[reorder-day-route] partial-state failure "
                "tenant=%s tech=%s date=%s job=%s err=%s",
                tenant_id, technician_id, date, j["id"], exc,
            )
            partial_error = f"{type(exc).__name__}: {str(exc)[:120]}"
            break

    # affected_job_ids = every non-anchor job whose slot changed.
    affected = changed_ids

    # ── 7. Best-effort ``dispatch_route_orders`` upsert. ─────
    try:
        ordered_customer_ids: List[str] = []
        for j in new_day_jobs:
            cid = j.get("customer_id")
            if cid:
                ordered_customer_ids.append(cid)
        weekday = _weekday_of(date)
        await db.dispatch_route_orders.update_one(
            {"tenant_id": tenant_id, "day": weekday,
             "tech_user_id": technician_id},
            {"$set": {
                "tenant_id":            tenant_id,
                "day":                  weekday,
                "tech_user_id":         technician_id,
                "ordered_customer_ids": ordered_customer_ids,
                "updated_at":           now,
                "updated_by":           user.get("id"),
                "source":               "reorder_day_route",
                "source_date":          date,
            }},
            upsert=True,
        )
    except Exception:
        pass

    # ── 8. Audit line. ────────────────────────────────────────
    try:
        import uuid as _uuid
        await db.audit_logs.insert_one({
            "id":               str(_uuid.uuid4()),
            "tenant_id":        tenant_id,
            "event":            "job_route_reordered",
            "actor_user_id":    user.get("id"),
            "job_id":           job_id,
            "old_position":     current_position,
            "new_position":     target_position,
            "affected_job_ids": affected,
            "at":               now,
            "created_at":       now,
        })
    except Exception:  # pragma: no cover
        pass

    resp: Dict[str, Any] = {
        "success":          partial_error is None,
        "changed":          True,
        "renumbered": [
            {"job_id": j["id"],
             "sequence_number": i + 1,
             "is_anchor": i in anchor_positions}
            for i, j in enumerate(new_day_jobs)
        ],
        "tech_user_id":     technician_id,
        "date":             date,
        "old_position":     current_position,
        "new_position":     target_position,
        "affected_job_ids": affected,
        "updated_count":    persisted,
        "n":                n,
    }
    if partial_error:
        resp["partial_error"] = partial_error
    return resp




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
    q = {**q, **_nd()}
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
