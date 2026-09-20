"""Phase C1 · Feb-2026 — completion follow-up helpers for the jobs router.

Two responsibilities live here so ``routers/jobs.py`` stays focused:

*   :func:`stamp_completion_fields` — populate ``completed_at`` (idempotent)
    and auto-populate ``follow_up_at`` on the ``→ completed`` transition,
    consulting the linked ``recurring_job_templates`` doc for cadence.
    Admin-supplied overrides on either field are preserved.
*   :func:`compute_follow_up_offset_days` — pure function that resolves
    the offset in days from the completed job's linked recurring
    template (weekly / monthly / custom). Non-recurring jobs fall back
    to :data:`DEFAULT_FOLLOW_UP_DAYS`.

The Sales-Pipeline Kanban Follow-up column reads ``follow_up_at`` and
``needs_follow_up`` — either field alone is enough to make a completed
job appear on the board when it's within +14d of "now".
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional


DEFAULT_FOLLOW_UP_DAYS = 14


def compute_follow_up_offset_days(
    template: Optional[Dict[str, Any]],
) -> int:
    """Resolve the follow-up offset (days) from a recurring template.

    Returns :data:`DEFAULT_FOLLOW_UP_DAYS` for missing / inactive
    templates. Otherwise:

    *   ``weekly``  → ``interval_days`` if present, else 7.
    *   ``monthly`` → 30.
    *   ``custom``  → ``interval_days`` if present, else 14.
    *   anything else → 14.
    """
    if not template or not template.get("active", True):
        return DEFAULT_FOLLOW_UP_DAYS
    freq = (template.get("frequency") or "").lower()
    interval = template.get("interval_days")
    try:
        interval_int = int(interval) if interval not in (None, "") else None
    except (TypeError, ValueError):
        interval_int = None

    if freq == "weekly":
        return interval_int or 7
    if freq == "monthly":
        return 30
    if freq == "custom":
        return interval_int or DEFAULT_FOLLOW_UP_DAYS
    return DEFAULT_FOLLOW_UP_DAYS


def _iso(dt: datetime) -> str:
    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).isoformat()


async def stamp_completion_fields(
    db,
    *,
    tenant_id: str,
    job: Dict[str, Any],
    update: Dict[str, Any],
) -> None:
    """Mutate ``update`` in-place so the ``→ completed`` write persists
    ``completed_at`` + ``follow_up_at``.

    Rules:

    *   ``completed_at``: set to ``now(UTC).isoformat()`` on the actual
        status flip (``update.status == "completed"`` AND
        ``job.status != "completed"``). If the caller already supplied
        ``completed_at`` in the update, respect it. If the job already
        carries a ``completed_at`` (idempotent re-write on an already-
        completed doc), don't overwrite.
    *   ``follow_up_at``: only set if neither the update nor the job
        already carry a value. Offset resolved via
        :func:`compute_follow_up_offset_days` on the linked template
        (looked up by ``job.recurring_template_id``); non-recurring
        jobs get :data:`DEFAULT_FOLLOW_UP_DAYS`.
    """
    new_status = str(update.get("status") or "").lower()
    prev_status = str(job.get("status") or "").lower()
    if new_status != "completed" or prev_status == "completed":
        return

    now = datetime.now(timezone.utc)

    if not update.get("completed_at") and not job.get("completed_at"):
        update["completed_at"] = _iso(now)

    # Never overwrite an existing follow_up_at (admin-set overrides win).
    if update.get("follow_up_at") or job.get("follow_up_at"):
        return

    template: Optional[Dict[str, Any]] = None
    tpl_id = job.get("recurring_template_id")
    if tpl_id:
        template = await db.recurring_job_templates.find_one(
            {"id": tpl_id, "tenant_id": tenant_id},
            {"_id": 0, "id": 1, "frequency": 1,
             "interval_days": 1, "active": 1, "is_active": 1},
        )
        # ``is_active`` is the newer flag; ``active`` older seeds.
        if template is not None:
            template["active"] = (
                template.get("is_active",
                              template.get("active", True))
            )

    offset_days = compute_follow_up_offset_days(template)
    fu = now + timedelta(days=offset_days)
    update["follow_up_at"] = _iso(fu)
