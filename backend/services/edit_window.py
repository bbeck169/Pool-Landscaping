"""Feb-2026 · 24-hour post-completion edit window.

Central home for the constants + gate helpers used by both the web
PATCH endpoint and the mobile-sync ``_handle_job_edit`` replay path.

Single source of truth:
  * ``EDIT_WINDOW_HOURS`` — the 24 in the phrase "24-hour edit window".
    Bumping this to 48 later is a one-line change here.
  * ``is_within_edit_window(job)`` — matches the exact contract in the
    Feb-2026 phase spec.
  * ``hours_since_completion(job)`` — float, used by the 403 response
    payload so the FE can render an accurate "N.M hours past window".
  * ``IMMUTABLE_FIELDS`` — the tenant-invariant fields that can NEVER
    be changed via the edit path (only via the original status-flow
    endpoints).  Reused by :func:`assert_immutable_fields_untouched`.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, Optional

from fastapi import HTTPException


EDIT_WINDOW_HOURS = 24

# Phase K6 · Feb-2026 — Completed Job Unlock.  These roles can PATCH
# a completed job WITHOUT the 24h edit-window gate.  Every mutation
# still writes:
#   1. The pre-existing ``db.job_edits`` audit doc (job-detail
#      history).
#   2. A ``db.audit_events`` row with ``event_type
#      = "job_edited_after_completion"`` so the Communication
#      Timeline on the customer page surfaces the edit.
# Portal + dispatcher-only + viewer roles remain blocked by
# ``_authorize_edit`` — K6 loosens the WINDOW, not the role gate.
K6_UNLOCK_ROLES = frozenset({
    "super_admin", "admin", "manager",
    "tech", "technician", "owner",
    # CLOSED-JOB-EDIT-UNLOCK · Feb-2026 — "employee" added as a
    # forward-compat string.  Zero behavioral impact at ship
    # time: no seeded user carries ``role="employee"`` today.
    # The row lives here so when the staff-role expansion lands,
    # the new users inherit the K6 unlock automatically without
    # a follow-up patch to this file.  Keeps web + mobile +
    # pytest in lockstep — change this set ONCE and every gate
    # moves together.
    "employee",
})


def role_bypasses_edit_window(role: Optional[str]) -> bool:
    """K6 · Feb-2026 — True iff the role can PATCH a completed job
    past the 24h window.  Case-insensitive on the role string so
    "Tech" / "TECHNICIAN" / "super_admin" all normalize correctly."""
    return (role or "").strip().lower() in K6_UNLOCK_ROLES


# Fields a technician / admin cannot mutate via the edit path.  The
# original status-flow endpoints (PUT status transition, admin
# customer-move, etc.) remain the ONLY way to change these post-
# completion.  Change one of these and the PATCH returns 400.
IMMUTABLE_FIELDS = frozenset({
    "id", "tenant_id", "customer_id", "technician_id",
    "created_at", "completed_at", "status", "invoice_id",
    "route_index", "scheduled_start", "scheduled_end",
})


def _parse_completed_at(job: Dict[str, Any]) -> Optional[datetime]:
    raw = job.get("completed_at")
    if not raw:
        return None
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=timezone.utc)
    if not isinstance(raw, str):
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def is_within_edit_window(job: Optional[Dict[str, Any]]) -> bool:
    """CLOSED-JOB-EDIT-UNLOCK · Feb-2026 — SEMANTIC CHANGE.

    True iff the job is ``completed``.  The pre-fix contract
    additionally required ``utcnow() - completed_at <=
    EDIT_WINDOW_HOURS`` so late corrections after 24h hit a 403
    ``edit_window_expired``.  Field-tech + admin-equivalent feedback
    was unanimous: real-world corrections (missed photos, chemistry
    tweaks, note typos, pricing adjustments) land days later and the
    24h gate was blocking legitimate work.

    The window check is now dropped.  All gating moves one layer out:
      * The role check (``_authorize_edit`` → K6 + role gate in
        ``routers/jobs.py::patch_job_edit_window``) still fences
        non-staff out of the edit path.
      * The status check still fences non-completed jobs out — the
        PATCH endpoint only operates on ``status="completed"``.
      * ``IMMUTABLE_FIELDS`` still fences off customer_id /
        technician_id / tenant_id / created_at reassignments.
      * The audit trail (``db.job_edits``) still fires on every
        edit regardless of elapsed time, so every post-completion
        change remains discoverable on the Communication Timeline.

    Missing ``completed_at`` or non-completed status → False.
    Never raises.  Returning True for any completed job means the
    403 ``edit_window_expired`` path is now effectively dead code
    for the web PATCH endpoint; the dead branch is retained
    one-gate-up as a defensive fallback in case a future refactor
    reinstates a window.
    """
    if not job:
        return False
    if (job.get("status") or "").lower() != "completed":
        return False
    # No ``completed_at`` → the job claims to be ``completed`` but
    # has no timestamp; conservative stance is to treat as "not
    # inside the window" so the edit path falls through to the
    # explicit K6-bypass branch in ``patch_job_edit_window``.
    completed_at = _parse_completed_at(job)
    if completed_at is None:
        return False
    # Was: ``datetime.now(utc) - completed_at <= timedelta(hours=
    # EDIT_WINDOW_HOURS)``.  Now: unconditionally True for
    # completed jobs with a parseable ``completed_at``.
    return True


def hours_since_completion(job: Optional[Dict[str, Any]]) -> Optional[float]:
    """Return the elapsed hours as a float, or ``None`` if the job
    is missing / not completed / has no ``completed_at``."""
    if not job:
        return None
    completed_at = _parse_completed_at(job)
    if completed_at is None:
        return None
    delta = datetime.now(timezone.utc) - completed_at
    return round(delta.total_seconds() / 3600.0, 2)


def assert_immutable_fields_untouched(patch_body: Dict[str, Any]) -> None:
    """Raise ``HTTPException(400)`` on the FIRST immutable field in
    the incoming patch.  Kept as the FIRST gate the PATCH endpoint
    runs so a hostile payload can't slip a customer_id reassign
    into an otherwise-innocuous chemistry edit.
    """
    for k in patch_body.keys():
        if k in IMMUTABLE_FIELDS:
            raise HTTPException(
                status_code=400,
                detail={
                    "detail": "immutable_field",
                    "field": k,
                    "message": (
                        f"Field '{k}' cannot be changed via the "
                        f"edit path — use the original status flow."
                    ),
                },
            )


def diff_fields(
    before: Dict[str, Any], after_partial: Dict[str, Any],
    *, skip: Iterable[str] = (),
) -> Dict[str, Dict[str, Any]]:
    """Return ``{field_path: {"before": <old>, "after": <new>}}`` for
    every key in ``after_partial`` whose value differs from
    ``before``.  ``skip`` = fields to ignore (e.g. ``updated_at``).
    Only records the actual DIFF — never the full document.
    """
    skip_set = set(skip)
    out: Dict[str, Dict[str, Any]] = {}
    for k, new_v in after_partial.items():
        if k in skip_set:
            continue
        old_v = before.get(k)
        if old_v != new_v:
            out[k] = {"before": old_v, "after": new_v}
    return out
