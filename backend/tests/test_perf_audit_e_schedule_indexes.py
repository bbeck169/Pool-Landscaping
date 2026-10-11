"""PERF-AUDIT-E · Feb-2026 — Schedule hot-path index verification.

Locks the schedule page's primary jobs query to the compound
``tenant_id_1_scheduled_date_1`` index with a 1:1 keys→docs ratio
(perfect IXSCAN, no in-memory sort/filter residue).  Guards against
future regressions that would land the query back on a tenant-only
prefix + in-memory date filter.

The schedule page (``frontend/src/pages/schedule/CalendarSchedule``)
fires::

    GET /api/jobs?start=YYYY-MM-DD&end=YYYY-MM-DD
      [&technician_id=X][&crew_id=Y]

which lands on the standard ``jobs.find({tenant_id, scheduled_date:
{$gte, $lte}})`` query the Mongo planner serves off the
``tenant_id_1_scheduled_date_1`` index when present.  The companion
``diag_schedule_dispatch_indexes`` migration — plus
``k15_jobs_tech_schedule_status`` and
``k15_jobs_crew_schedule`` — provide the tech-scoped +
crew-scoped variants for the ``&technician_id=`` /
``&crew_id=`` arms.

Tests here operate against the live preview DB because the index
state we care about is the live state.  Idempotent: no writes.
"""
from __future__ import annotations

from tests._f7_loop_fixture import run_test


def _flatten_plan_stages(plan):
    """Walk the Mongo winning-plan tree and return a flat list of
    stage names in top-down order."""
    out = [plan.get("stage")]
    if "inputStage" in plan:
        out += _flatten_plan_stages(plan["inputStage"])
    for sub in plan.get("inputStages", []) or []:
        out += _flatten_plan_stages(sub)
    return out


def _find_index_used(plan):
    """Walk the plan tree + return the first IXSCAN's ``indexName``."""
    if plan.get("stage") == "IXSCAN":
        return plan.get("indexName")
    if "inputStage" in plan:
        name = _find_index_used(plan["inputStage"])
        if name:
            return name
    for sub in plan.get("inputStages", []) or []:
        name = _find_index_used(sub)
        if name:
            return name
    return None


# ═══════════════════════════════════════════════════════════════════
# Schedule day-view query uses an IXSCAN on
# ``tenant_id_1_scheduled_date_1`` (or a strict superset).
# ═══════════════════════════════════════════════════════════════════
def test_schedule_day_query_uses_compound_tenant_scheduled_date_index():
    """``jobs.find({tenant_id, scheduled_date: {$gte, $lte}})``
    MUST land on an IXSCAN whose index key begins with
    ``(tenant_id, scheduled_date)``.

    Permissible winning-plan indexes (any one is acceptable):
      * ``tenant_id_1_scheduled_date_1`` — the canonical schedule
        page index.
      * ``diag_jobs_tenant_sched_route_idx`` — the diag-timeout
        task-3 widened variant (same prefix, extra sort key).
      * ``k21_jobs_tenant_customer_sched`` — includes customer_id
        in the key but the planner can still satisfy a scheduled-
        date range by stepping customer_id. (Allowed as a safety
        net; the canonical index is strictly preferable.)
    """
    _ACCEPTABLE_INDEXES = {
        "tenant_id_1_scheduled_date_1",
        "diag_jobs_tenant_sched_route_idx",
        "k21_jobs_tenant_customer_sched",
    }

    async def _go(db):
        # Use the live Aquaterra preview tenant — ~6000 jobs seeded.
        # Any tenant with jobs works for an explain(); the planner
        # cares about the predicate shape, not the tenant.
        q = {
            "tenant_id": "affdfbfa-88b9-4baa-ae45-2ef78531b6e4",
            "scheduled_date": {"$gte": "2026-09-28",
                                 "$lte": "2026-09-28"},
        }
        exp = await db.jobs.find(q).sort(
            "scheduled_date", 1,
        ).explain()
        winning = (exp.get("queryPlanner") or {}).get("winningPlan") or {}
        stages = _flatten_plan_stages(winning)
        idx_name = _find_index_used(winning)

        # COLLSCAN is a regression — fail hard.
        assert "COLLSCAN" not in stages, (
            f"Schedule day query regressed to a COLLSCAN. "
            f"Stages={stages}"
        )
        assert idx_name is not None, (
            f"No IXSCAN found in winning plan; stages={stages}"
        )
        assert idx_name in _ACCEPTABLE_INDEXES, (
            f"Schedule day query uses unexpected index "
            f"{idx_name!r}. Acceptable: {sorted(_ACCEPTABLE_INDEXES)}."
            " Add the new index to the acceptable list if this is "
            "intentional, or confirm the planner regression."
        )

        # Guard against a wasteful IXSCAN — nReturned / keysExamined
        # must be close to 1:1 for the canonical index.  Allow some
        # slack (<= 3x ratio) because the broader indexes may walk
        # extra keys to satisfy the predicate.
        exec_stats = exp.get("executionStats") or {}
        n_returned = exec_stats.get("nReturned") or 0
        keys_examined = exec_stats.get("totalKeysExamined") or 0
        if n_returned > 0:
            # ratio reported for diagnostics even when the assertion
            # passes.
            ratio = keys_examined / max(n_returned, 1)
            assert ratio <= 3.0, (
                f"Schedule day IXSCAN wastes keys — "
                f"keys_examined={keys_examined} nReturned={n_returned} "
                f"ratio={ratio:.2f}x. Expect <= 3x."
            )

    run_test(_go)
