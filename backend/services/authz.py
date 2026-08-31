"""Feb-2026 · Phase F1 · shared tech-job authorization helper.

Prior to this module every "Not your job" gate lived inline in
``routers/jobs.py``, ``workstream_job_detail.py``,
``job_media_line_items.py``, ``maintenance.py``, and
``service_reports.py`` — each checking only ``job.technician_id``
against the tech's own id. That broke crew-only jobs (jobs with a
``crew_id`` and no direct ``technician_id``): the tech belongs to
the crew but is not the direct assignee, so every gate returned 403
"Not your job" even though the tech legitimately owns the shift.

``is_tech_authorized_on_job`` is the single source of truth. Callers
pass ``(user, job, db, tenant_id=None)`` and get back a ``bool``.
Semantics mirror ``scope_jobs_query`` in ``routers/jobs.py``:

* Direct assignment via ``job.technician_id`` matching either
  ``user.id`` or ``user.technician_id`` (older seeds stamped the
  user_id, newer seeds stamp the technicians-table id).
* Crew membership — the job carries ``crew_id`` and the tech's id
  appears in ``crews.tech_ids`` for that crew, scoped to the same
  tenant as the job.

Non-tech callers should not use this helper; role gates run BEFORE
the helper in every call site.
"""
from __future__ import annotations

from typing import Any, Dict, Optional


async def is_tech_authorized_on_job(
    user: Dict[str, Any],
    job: Dict[str, Any],
    db: Any,
    tenant_id: Optional[str] = None,
) -> bool:
    """Return True if ``user`` (a technician) may act on ``job``.

    The caller must have already confirmed
    ``user.role == 'technician'`` — this helper does NOT re-check
    role. Never raises: every branch returns a bool so callers keep
    control of the HTTP shape.

    Args:
        user: Session dict; expected keys ``id``, ``technician_id``.
        job:  Job doc; expected keys ``technician_id``, ``crew_id``,
              ``tenant_id``.
        db:   Motor database handle (needed for the crew lookup).
        tenant_id: Optional tenant scope for the ``crews`` lookup.
              Falls back to ``job.tenant_id`` when omitted.

    Returns:
        ``True`` when the tech is either the direct assignee of
        ``job`` OR a member of the crew referenced by
        ``job.crew_id``. ``False`` otherwise.
    """
    if not isinstance(user, dict) or not isinstance(job, dict):
        return False

    assigned = job.get("technician_id")
    user_id = user.get("id")
    user_tech_id = user.get("technician_id")

    # ── Direct assignment — the historical/inline check ──────────
    # ``jobs.technician_id`` may store either the user row id
    # (older seeds) or the technicians-table id (newer seeds), so
    # we accept a match against either.
    if assigned and assigned in (user_id, user_tech_id):
        return True

    # ── Crew-membership fallback — the P0-B fix ──────────────────
    # A job bound only to a crew (``crew_id`` set,
    # ``technician_id`` null OR set to another tech) must still be
    # visible/actionable to every member of that crew.
    crew_id = job.get("crew_id")
    if not crew_id:
        return False

    tid = tenant_id or job.get("tenant_id")
    if not tid:
        return False

    # ``crews.tech_ids`` is the same id-space as
    # ``technicians.id`` / ``users.technician_id``. Older seeds
    # occasionally stamped the user_id there too — we accept
    # either for parity with ``scope_jobs_query``.
    tech_pk = user_tech_id or user_id
    if not tech_pk:
        return False

    try:
        crew = await db.crews.find_one(
            {"id": crew_id, "tenant_id": tid, "tech_ids": tech_pk},
            {"_id": 0, "id": 1},
        )
    except Exception as exc:  # noqa: BLE001 — never block on membership lookup
        # Feb-2026 · F2 addendum — log the specific failure so ops
        # sees transient Mongo blips instead of a silent 403 wave.
        # Kept as ``False`` return (fail-closed) for authorization
        # safety; visibility only.
        import logging  # noqa: PLC0415 — local to avoid top-level cost

        logging.getLogger("services.authz").error(
            "is_tech_authorized_on_job crew lookup failed "
            "user_id=%s tech_pk=%s crew_id=%s tenant_id=%s error=%s",
            user_id, tech_pk, crew_id, tid, exc,
        )
        return False
    return crew is not None
