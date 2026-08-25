"""Feb-2026 · Shared helper for reading the effective technician id off a
``jobs`` document.

Historical write drift means job docs in production stamp the assignee id
under any of FOUR distinct field names, depending on which write path
last touched the row:

    1. ``technician_id``           — create / dispatch / instaschedule /
                                     service_report submit
    2. ``assigned_to``             — dispatch, schedule_reorder, sequences,
                                     dispatch_board, dispatch_route_insert,
                                     dispatch_route_optimize,
                                     route_optimization_approval
    3. ``assigned_technician_id``  — route_optimization, workforce,
                                     properties, inventory_reports
    4. ``tech_user_id``            — schedule_reorder,
                                     dispatch_route_optimize,
                                     route_optimization_approval

READ paths that only look at ``technician_id`` silently drop every row
whose assignment was last touched by a writer using one of the other
three shapes — producing the "Assigned to Unassigned" symptom on the
Workstream page even though the job clearly has a tech.

The Schedule identity-mismatch hotfix (``routers/schedule.py:91-95``)
already unions three of these on its side; this helper is the equivalent
lens for READ paths that need the effective id in isolation.
"""
from typing import Any, Mapping, Optional


# Ordered — first non-empty wins. ``technician_id`` takes precedence
# so paths that already stamp it correctly (create / dispatch) keep
# the historical id shape they emitted.
_TID_FIELDS = (
    "technician_id",
    "assigned_to",
    "assigned_technician_id",
    "tech_user_id",
)


def effective_tid(job: Optional[Mapping[str, Any]]) -> Optional[str]:
    """Return the effective technician id off a job doc, checking all
    four field-name shapes in priority order. Returns ``None`` when
    none are populated. Never raises.
    """
    if not job:
        return None
    for f in _TID_FIELDS:
        v = job.get(f)
        if v:
            return v
    return None
