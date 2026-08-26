"""Feb-2026 · Auto-extend recurring series when the last unfinished
occurrence is completed.

Design
------

* Called via ``asyncio.create_task`` from ``PATCH /api/jobs/{id}`` when
  the transition to ``status=completed`` commits.
* Loads the completed job, its template, then the count of remaining
  future not-yet-completed occurrences for that ``recurring_template_id``.
* Early-exits on every "don't extend" branch (non-recurring, still
  has work, series stopped, ``end_date`` in the past).
* When the go-ahead is given, walks 4 future occurrences using the
  template's own cadence (weekly / biweekly / monthly / nth-weekday)
  by reusing ``_next_occurrences`` — no duplicate generator code.
* Idempotent via (a) the partial-unique
  ``(recurring_template_id, scheduled_date)`` index on ``jobs`` and
  (b) an in-process per-template ``asyncio.Lock``.
* Multi-tenant safe — every query scopes by ``tenant_id``.
"""
from __future__ import annotations

import asyncio
from datetime import date, timedelta
from typing import Optional

from config import db, logger
from routers.recurring_jobs import _next_occurrences, _parse_date
from utils import new_id

# In-process guard against two completes racing on the same template.
# Single-replica deployment → in-process is sufficient. The Mongo
# partial-unique index remains the durable dedup contract.
_TEMPLATE_LOCKS: dict[str, asyncio.Lock] = {}

# Auto-extend at most this many future occurrences per fire. Matches
# the "next 4 weeks" product intent for weekly cadence; for monthly
# templates that's the next 4 months instead — same semantic.
DEFAULT_EXTEND_COUNT = 4


def _lock_for(template_id: str) -> asyncio.Lock:
    lock = _TEMPLATE_LOCKS.get(template_id)
    if lock is None:
        lock = asyncio.Lock()
        _TEMPLATE_LOCKS[template_id] = lock
    return lock


async def _remaining_future_open_count(template_id: str, tenant_id: str,
                                          today_iso: str) -> int:
    """Non-completed jobs on this template scheduled today or later.
    Cancelled + completed rows are excluded — a completed cancellation
    still means "not on today's route" for this purpose."""
    return await db.jobs.count_documents({
        "tenant_id": tenant_id,
        "recurring_template_id": template_id,
        "scheduled_date": {"$gte": today_iso},
        "status": {"$nin": ["completed", "cancelled"]},
    })


async def _template_is_live(tpl: dict, today: date) -> bool:
    if tpl.get("stopped_at"):
        return False
    if tpl.get("active") is False:
        return False
    if tpl.get("recurrence_never_ends"):
        return True
    end_iso = tpl.get("end_date")
    if not end_iso:
        return True
    end = _parse_date(end_iso)
    return end is None or end > today


async def _generate_next(tpl: dict, *, count: int, from_date: date,
                            db_handle=None) -> dict:
    """Materialize up to ``count`` future occurrences from ``from_date``.

    Reuses ``_next_occurrences`` to pick the exact cadence-driven dates
    (weekly / biweekly / monthly / nth_weekday) and inserts each. Per-
    insert ``DuplicateKeyError`` is swallowed so a re-fire on a partial
    prior extend is a no-op.
    """
    from pymongo.errors import DuplicateKeyError
    _db = db_handle if db_handle is not None else db
    tenant_id = tpl["tenant_id"]
    template_id = tpl["id"]
    # Cap by the template's end_date if it has one and never_ends is off.
    horizon_days = 365 * 2
    if not tpl.get("recurrence_never_ends") and tpl.get("end_date"):
        end = _parse_date(tpl["end_date"])
        if end and end > from_date:
            horizon_days = max(1, (end - from_date).days)
        elif end and end <= from_date:
            return {"inserted": 0, "skipped": 0, "dates": []}
    through = from_date + timedelta(days=horizon_days)
    # Ask the underlying generator for a generous window — we still
    # only insert until we've achieved ``count`` NEW rows (dedup via
    # the partial-unique index is expected during auto-extend because
    # earlier ``generate_now`` runs or nightly cron may already have
    # written the near-term slots). Cap at 6x to bound compute.
    dates = _next_occurrences(tpl, from_date, through, max_count=count * 6)

    cust = await _db.customers.find_one(
        {"id": tpl.get("customer_id"), "tenant_id": tenant_id},
        {"_id": 0, "name": 1, "address": 1, "is_muted": 1},
    ) or {}
    # Feb-2026 · P27 — muted customers are excluded from recurring
    # job auto-generation (part of the "silent-mode" contract).
    if cust.get("is_muted"):
        logger.info(
            "[p27] recurring autogen skipped — customer %s is muted "
            "(template=%s, tenant=%s)",
            tpl.get("customer_id"), tpl.get("id"), tenant_id,
        )
        return {"inserted": 0, "skipped": 0, "dates": [],
                  "muted_customer_id": tpl.get("customer_id")}
    tech_id = tpl.get("assigned_tech_id")
    tech = None
    if tech_id:
        tech = await _db.users.find_one({"id": tech_id, "tenant_id": tenant_id},
                                          {"_id": 0, "name": 1})
    tech_name = (tech or {}).get("name")
    price_dollars = round((tpl.get("price_cents") or 0) / 100.0, 2)

    inserted, skipped = 0, 0
    inserted_dates: list[str] = []
    for d in dates:
        if inserted >= count:
            # Feb-2026 · Cap at ``count`` new rows. Generator returns a
            # generous window (``count * 6``) so dedup-skipped slots
            # can still resolve to fresh future dates, but we stop the
            # moment we've materialised the requested number.
            break
        iso = d.isoformat()
        try:
            await _db.jobs.insert_one({
                "id": new_id(),
                "tenant_id": tenant_id,
                "recurring_template_id": template_id,
                "title": tpl.get("service_type") or "Recurring Service",
                "service_type": tpl.get("service_type"),
                # Feb 2026 · Inherit the template's work_class so
                # materialized recurring occurrences carry the same
                # service/repair tag. Legacy templates without the
                # field materialize as "service" (matches the read-
                # time invariant in ``services/work_class.py``).
                "work_class": (
                    "repair" if (tpl.get("work_class") == "repair")
                    else "service"
                ),
                "customer_id": tpl.get("customer_id"),
                "customer_name": cust.get("name") or tpl.get("customer_name"),
                "address": cust.get("address") or "",
                "technician_id": tech_id,
                "technician_name": tech_name,
                "scheduled_date": iso,
                "status": "scheduled",
                "price": price_dollars,
                "auto_generated_by": "recurring_autogen_on_complete",
            })
            inserted += 1
            inserted_dates.append(iso)
        except DuplicateKeyError:
            # Same-day occurrence already materialised — expected on
            # concurrent completes; partial-unique index does its job.
            # Does NOT count against ``count`` — we still want ``count``
            # NEW rows out the door.
            skipped += 1
    if inserted:
        # Advance the template's ``last_generated_through`` cursor so
        # the nightly bulk generator doesn't re-walk the same window.
        latest_iso = inserted_dates[-1]
        prev = tpl.get("last_generated_through") or ""
        if latest_iso > prev:
            await _db.recurring_job_templates.update_one(
                {"id": template_id, "tenant_id": tenant_id},
                {"$set": {"last_generated_through": latest_iso}},
            )
    return {"inserted": inserted, "skipped": skipped, "dates": inserted_dates}


async def maybe_extend_recurring_series(
    job_id: str,
    tenant_id: str,
    *,
    count: int = DEFAULT_EXTEND_COUNT,
    db_handle=None,
) -> Optional[dict]:
    """The public entry point. Returns the extend report on success or
    ``None`` when the caller's early-exit conditions apply.

    ``db_handle`` is optional; tests inject a fresh loop-bound Motor
    client to avoid the ``config.db`` loop-binding class of flakes.

    Never raises — the caller schedules this as fire-and-forget from
    the job-status handler, and any exception here would spam the
    error log without helping the user.
    """
    _db = db_handle if db_handle is not None else db
    try:
        job = await _db.jobs.find_one(
            {"id": job_id, "tenant_id": tenant_id},
            {"_id": 0, "recurring_template_id": 1},
        )
        if not job:
            return None
        template_id = job.get("recurring_template_id")
        if not template_id:
            return None

        lock = _lock_for(template_id)
        async with lock:
            today = date.today()
            today_iso = today.isoformat()

            remaining = await _db.jobs.count_documents({
                "tenant_id": tenant_id,
                "recurring_template_id": template_id,
                "scheduled_date": {"$gte": today_iso},
                "status": {"$nin": ["completed", "cancelled"]},
            })
            if remaining > 0:
                return None

            tpl = await _db.recurring_job_templates.find_one(
                {"id": template_id, "tenant_id": tenant_id},
                {"_id": 0},
            )
            if not tpl:
                return None
            if not await _template_is_live(tpl, today):
                return None

            from_date = today + timedelta(days=1)
            report = await _generate_next(
                tpl, count=count, from_date=from_date, db_handle=_db,
            )
            logger.info(
                "recurring_series_auto_extended "
                f"template_id={template_id} triggered_by_job_id={job_id} "
                f"count_generated={report['inserted']} "
                f"skipped={report['skipped']} "
                f"next_dates={report['dates']}"
            )
            return {
                "template_id": template_id,
                "triggered_by_job_id": job_id,
                **report,
            }
    except Exception as e:  # pragma: no cover — defensive
        logger.warning(f"maybe_extend_recurring_series failed: {e}")
        return None
