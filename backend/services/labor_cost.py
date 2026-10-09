"""Phase 10 · Feb-2026 — Technician labor cost computation.

Combines two inputs into one per-tech labor cost dict:
    * ``hours_worked`` — summed timecard ``duration_minutes`` from
      ``db.time_entries`` (same source the diagnostic
      ``_wages_by_role`` in ``services.finance.ebit`` reads from).
    * ``pool_jobs_completed`` — per-tech count of completed pool
      service visits, derived from the canonical Phase 1
      ``compute_pool_service`` output (``by_technician.pools_serviced``).
      Reusing the Phase 1 helper guarantees the "pool job" predicate
      (``derive_industry_for_job(..., strict_mode=True) == "pool"`` +
      ``work_class == "service"``) stays byte-identical across the
      Pool Service Report, the EBIT labor row (added here), and this
      new ``/reports/labor-cost`` endpoint. Any future tweak to the
      predicate lives in one place.

Per-tech total:
    hourly_cost   = hours_worked         * hourly_rate
    per_pool_cost = pool_jobs_completed  * per_pool_rate
    total         = hourly_cost + per_pool_cost

Rates live on the user doc (``users.hourly_rate`` already shipped
with the EBIT diagnostic; ``users.per_pool_rate`` is NEW in Phase 10
and persisted via ``PATCH /api/users/{id}``). Nullable → treated as
zero so a tenant that only sets ``hourly_rate`` for some techs still
computes a stable total.

Decimal semantics: rates stored as str/Decimal strings on the user
doc; coerced to :class:`decimal.Decimal` at compute time and
quantised to two places on the response boundary so JSON serialises
as plain floats without 0.1 + 0.2 drift.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Dict, List, Optional


# Two-place quantiser — matches the chemistry-decimals convention
# used elsewhere in the app so money reads consistently.
_Q = Decimal("0.01")


def _to_decimal(v: Any) -> Decimal:
    """Permissive coercion → Decimal. None / '' / junk → 0."""
    if v is None:
        return Decimal(0)
    if isinstance(v, Decimal):
        return v
    try:
        # Route through str() so a float like 25.0 doesn't carry
        # its binary representation into the Decimal (the Decimal
        # constructor accepts float directly but preserves the FP
        # error — not what we want for money).
        return Decimal(str(v))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(0)


def _quantise(d: Decimal) -> float:
    """Round half-up to 2 places. JSON-safe output type."""
    return float(d.quantize(_Q, rounding=ROUND_HALF_UP))


async def _hours_by_tech(
    db,
    tenant_id: str,
    start_date: str,
    end_date: str,
) -> Dict[str, Decimal]:
    """Sum ``duration_minutes`` → hours per ``user_id`` in the window.

    Mirrors the filter logic in ``services.finance.ebit._wages_by_role``:
    date comes from the ``date`` field if present, falling back to
    the first 10 chars of ``started_at``. Half-open-right window
    (``start_date <= day <= end_date``) matches the EBIT convention.
    """
    cursor = db.time_entries.find(
        {"tenant_id": tenant_id},
        {"_id": 0, "user_id": 1, "duration_minutes": 1,
         "date": 1, "started_at": 1},
    )
    out: Dict[str, Decimal] = {}
    async for e in cursor:
        d = (e.get("date") or (e.get("started_at") or "")[:10])[:10]
        if not d or not (start_date <= d <= end_date):
            continue
        uid = e.get("user_id") or ""
        if not uid:
            continue
        minutes = _to_decimal(e.get("duration_minutes"))
        hours = minutes / Decimal(60)
        out[uid] = out.get(uid, Decimal(0)) + hours
    return out


async def _pool_jobs_by_tech(
    tenant_id: str,
    start_date: str,
    end_date: str,
) -> Dict[str, int]:
    """Delegate to the Phase 1 ``compute_pool_service`` so the "pool
    job completed" predicate stays canonical across the app.

    Returns {technician_id: pools_serviced_count}. The Phase 1 helper
    already applies ``derive_industry_for_job(..., strict_mode=True)
    == "pool"`` + ``work_class == "service"`` which is EXACTLY the
    predicate the brief specifies for ``pool_jobs_completed``.

    Imported lazily to avoid the ``routers.jobs`` ⇄ ``services``
    circular-dep (``routers.jobs`` imports from several services at
    module scope).
    """
    from routers.jobs import compute_pool_service
    report = await compute_pool_service(tenant_id, start_date, end_date)
    rows = report.get("by_technician") or []
    out: Dict[str, int] = {}
    for r in rows:
        tid = r.get("technician_id") or ""
        if not tid:
            continue
        out[tid] = int(r.get("pools_serviced") or 0)
    return out


async def _resolve_tech_names_and_rates(
    db,
    tenant_id: str,
    tech_ids: List[str],
) -> Dict[str, Dict[str, Any]]:
    """Fetch ``name``, ``hourly_rate``, ``per_pool_rate`` for every
    tech id in the union of (hours set, pool jobs set, tech_filter).

    Users store the pay rates loosely (free-form fields; see Phase 10
    team.update_user allow-list). Missing → None → zero at compute
    time.
    """
    if not tech_ids:
        return {}
    docs = await db.users.find(
        {"tenant_id": tenant_id, "id": {"$in": tech_ids}},
        {"_id": 0, "id": 1, "name": 1,
         "hourly_rate": 1, "per_pool_rate": 1,
         "technician_id": 1},
    ).to_list(len(tech_ids) + 32)
    index: Dict[str, Dict[str, Any]] = {}
    for u in docs:
        # Index under both the user id AND the user's technician_id
        # so callers that bucket pool-service rows under
        # ``technician_id`` (the canonical Phase 1 bucket) still hit
        # the user's rate card.
        for key in (u.get("id"), u.get("technician_id")):
            if key:
                index[key] = u
    return index


async def compute_labor_cost(
    tenant_id: str,
    start_date: str,
    end_date: str,
    tech_filter: Optional[str] = None,
    *,
    db=None,
) -> Dict[str, Any]:
    """Return per-tech + total labor cost for the window.

    Shape:

    .. code-block:: python

        {
          "by_tech": [
            {
              "tech_id":              str,
              "tech_name":            str,
              "hourly_rate":          float,
              "per_pool_rate":        float,
              "hours_worked":         float,
              "hourly_cost":          float,
              "pool_jobs_completed":  int,
              "per_pool_cost":        float,
              "total_labor_cost":     float,
            }, ...
          ],
          "totals": {
            "hours_worked":        float,
            "hourly_cost":         float,
            "pool_jobs_completed": int,
            "per_pool_cost":       float,
            "total_labor_cost":    float,
          },
          "range": {"start": str, "end": str},
        }

    When every tech has no rates set the response totals are 0.00 —
    the FE renders cleanly and callers (EBIT) read zero labor cost
    without crashing.
    """
    if db is None:
        from config import db as _global_db
        db = _global_db

    hours = await _hours_by_tech(db, tenant_id, start_date, end_date)
    pool_jobs = await _pool_jobs_by_tech(tenant_id, start_date, end_date)

    tech_ids: List[str] = list({*hours.keys(), *pool_jobs.keys()})
    if tech_filter:
        tech_ids = [t for t in tech_ids if t == tech_filter]
    user_index = await _resolve_tech_names_and_rates(db, tenant_id, tech_ids)

    by_tech: List[Dict[str, Any]] = []
    tot_hours = Decimal(0)
    tot_hourly_cost = Decimal(0)
    tot_pool_jobs = 0
    tot_per_pool_cost = Decimal(0)

    for tid in tech_ids:
        u = user_index.get(tid) or {}
        h = hours.get(tid, Decimal(0))
        pj = pool_jobs.get(tid, 0)
        hourly_rate = _to_decimal(u.get("hourly_rate"))
        per_pool_rate = _to_decimal(u.get("per_pool_rate"))
        hourly_cost = h * hourly_rate
        per_pool_cost = Decimal(pj) * per_pool_rate
        total = hourly_cost + per_pool_cost

        by_tech.append({
            "tech_id":             tid,
            "tech_name":           (u.get("name") or ""),
            "hourly_rate":         _quantise(hourly_rate),
            "per_pool_rate":       _quantise(per_pool_rate),
            "hours_worked":        _quantise(h),
            "hourly_cost":         _quantise(hourly_cost),
            "pool_jobs_completed": pj,
            "per_pool_cost":       _quantise(per_pool_cost),
            "total_labor_cost":    _quantise(total),
        })
        tot_hours += h
        tot_hourly_cost += hourly_cost
        tot_pool_jobs += pj
        tot_per_pool_cost += per_pool_cost

    # Sort descending by total cost so the biggest earners land at
    # the top of the report. Zero-cost rows cluster at the bottom.
    by_tech.sort(key=lambda r: r["total_labor_cost"], reverse=True)

    totals = {
        "hours_worked":        _quantise(tot_hours),
        "hourly_cost":         _quantise(tot_hourly_cost),
        "pool_jobs_completed": tot_pool_jobs,
        "per_pool_cost":       _quantise(tot_per_pool_cost),
        "total_labor_cost":    _quantise(tot_hourly_cost + tot_per_pool_cost),
    }

    return {
        "by_tech": by_tech,
        "totals":  totals,
        "range":   {"start": start_date, "end": end_date},
    }
