"""Feb-2026 · Unified clock-state reader (GPS Ping Issue 2 ·
P1 — operator-confirmed).

Single authoritative source for "is user X on shift right now?"
across the three distinct clock-state collections:

  * ``time_entries``       — payroll paired shifts
  * ``timeclock_punches``  — raw clock events (in/out event log)
  * ``job_timers``         — job-scoped wall-time (started_at /
                             ended_at pair)

Context
-------
Pre-ticket, ``POST /gps/pings`` only consulted ``time_entries`` so
a tech legitimately on-shift via a mobile punch (``timeclock_
punches``) or a GPS-arrival-started job timer (``job_timers``) got
409 ``not_clocked_in`` and the mobile client silently dropped the
ping. The App Store privacy-string promise "only track while
clocked in" also tilted the other way — a ping accepted via a
stale ``time_entries`` row after a mobile punch-out would store
breadcrumbs the user wouldn't expect.

Design
------
Two exports:

  * :func:`is_user_on_shift` — the thin ``bool`` gate the brief
    specifies.  Delegates to :func:`find_open_shift_ref`.
  * :func:`find_open_shift_ref` — returns a dict with
    ``{"source": str, "shift_id": str}`` for the matched row (or
    ``None`` when the user is off shift).  The GPS ingest path
    uses this to tag inserted ping docs with ``clock_in_id`` so
    downstream reports can correlate pings to a specific shift,
    regardless of which collection authored it.

Both helpers:

  * Tenant-scope every read on ``tenant_id``.
  * Apply the AZ-TZ soft-delete filter (``deleted_at: None``) on
    ``timeclock_punches`` so a tombstoned punch cannot resurrect
    a dead shift (matches commit ``af5745e58``).
  * Normalize naive-tz ``at`` inputs to UTC before comparing.
  * Return a boolean / dict without raising; a Mongo hiccup is
    logged and treated as "off shift" (fail-closed — a privacy-
    first default, mirroring the ingest's existing 409 posture).

Pool-tech opt-out
-----------------
The ``users.gps_tracking_opt_out`` flag is NOT consulted here.
It is already checked at the ingest layer (``gps_ingest.py``) BEFORE
this helper is invoked, so an opt-out tech returns 409
``user_opted_out`` and never reaches the shift gate.  Keeping the
two gates independent preserves the operator's "opt-outs must not
be treated as on shift" guarantee while letting other callers
(e.g. internal shift audits) ask the clock question without
inheriting a tracking-specific gate.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from config import db, logger


def _ensure_aware_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """Normalize ``dt`` to a tz-aware UTC datetime.  Naive values
    land as UTC (same posture as the shipped ``dashboard_service
    _category.py::_parse_iso`` fix).  ``None`` passes through."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _iso(dt: datetime) -> str:
    """Z-suffix UTC ISO so string-sorted Mongo comparisons stay
    monotonic alongside the shipped punch timestamps."""
    return (dt.astimezone(timezone.utc).isoformat()
              .replace("+00:00", "Z"))


async def _open_time_entry(tenant_id: str, user_id: str,
                             at_iso: Optional[str]) -> Optional[Dict[str, Any]]:
    """Match an open paired shift.  When ``at_iso`` is provided,
    also allow a closed shift whose window straddles ``at``."""
    base = {"tenant_id": tenant_id, "user_id": user_id}
    try:
        if at_iso is None:
            return await db.time_entries.find_one(
                {**base, "clock_out_at": None}, {"_id": 0, "id": 1},
            )
        return await db.time_entries.find_one(
            {**base,
             "clock_in_at": {"$lte": at_iso},
             "$or": [{"clock_out_at": None},
                     {"clock_out_at": {"$gte": at_iso}}]},
            {"_id": 0, "id": 1},
        )
    except Exception as exc:                                     # noqa: BLE001
        logger.warning(
            "[clock-state] time_entries read failed tenant=%s user=%s: %s",
            tenant_id, user_id, exc,
        )
        return None


async def _open_timeclock_punch(tenant_id: str, user_id: str,
                                  at_iso: Optional[str]
                                  ) -> Optional[Dict[str, Any]]:
    """Match an IN punch that has no later OUT punch (either at
    all, when ``at_iso`` is None, or before ``at_iso`` when it is).
    Soft-deleted punches (``deleted_at != None``) never count."""
    base = {"tenant_id": tenant_id, "user_id": user_id,
              "deleted_at": None}
    try:
        in_filter = dict(base)
        in_filter["punch_type"] = "in"
        if at_iso is not None:
            in_filter["timestamp"] = {"$lte": at_iso}
        latest_in = await db.timeclock_punches.find_one(
            in_filter,
            {"_id": 0, "id": 1, "timestamp": 1},
            sort=[("timestamp", -1)],
        )
        if not latest_in:
            return None
        out_filter = dict(base)
        out_filter["punch_type"] = "out"
        out_bounds: Dict[str, Any] = {"$gt": latest_in["timestamp"]}
        if at_iso is not None:
            out_bounds["$lte"] = at_iso
        out_filter["timestamp"] = out_bounds
        matched_out = await db.timeclock_punches.find_one(
            out_filter, {"_id": 0, "id": 1},
        )
        if matched_out:
            return None
        return latest_in
    except Exception as exc:                                     # noqa: BLE001
        logger.warning(
            "[clock-state] timeclock_punches read failed "
            "tenant=%s user=%s: %s", tenant_id, user_id, exc,
        )
        return None


async def _open_job_timer(tenant_id: str, user_id: str,
                            at_iso: Optional[str]
                            ) -> Optional[Dict[str, Any]]:
    """Match a ``job_timers`` row whose window covers ``at`` (or
    is open-ended when ``at`` is None).  ``job_timers`` carries
    ``tech_id`` (resolved by ``auto_start_timer_on_arrival`` to
    either ``technicians.id`` or ``users.id``), so match on either
    field — mirrors the Phase 6 crew-aware admin filter from
    ``routers/jobs.py::scope_jobs_query``."""
    base = {"tenant_id": tenant_id,
              "$or": [{"tech_id": user_id}, {"user_id": user_id}]}
    try:
        if at_iso is None:
            return await db.job_timers.find_one(
                {**base, "ended_at": None}, {"_id": 0, "id": 1},
            )
        return await db.job_timers.find_one(
            {**base,
             "started_at": {"$lte": at_iso},
             "$or": [{"ended_at": None},
                     {"ended_at": {"$gte": at_iso}}]},
            {"_id": 0, "id": 1},
        )
    except Exception as exc:                                     # noqa: BLE001
        logger.warning(
            "[clock-state] job_timers read failed tenant=%s user=%s: %s",
            tenant_id, user_id, exc,
        )
        return None


async def find_open_shift_ref(user_id: str, tenant_id: str,
                                at: Optional[datetime] = None
                                ) -> Optional[Dict[str, Any]]:
    """Return a reference to an open shift row for ``user_id``
    on ``tenant_id`` across the three clock-state collections, or
    ``None`` if the user is off shift.

    Resolution priority (first-match wins — same precedence the
    shipped ``gps_ingest._get_open_shift`` used before this
    unification):

      1. ``time_entries``       — ``source="time_entries"``
      2. ``timeclock_punches``  — ``source="timeclock_punches"``
      3. ``job_timers``         — ``source="job_timers"``

    Return shape: ``{"source": str, "shift_id": str}`` or ``None``.
    """
    if not user_id or not tenant_id:
        return None
    at_dt = _ensure_aware_utc(at)
    at_iso = _iso(at_dt) if at_dt else None

    te = await _open_time_entry(tenant_id, user_id, at_iso)
    if te:
        return {"source": "time_entries", "shift_id": te.get("id")}
    tp = await _open_timeclock_punch(tenant_id, user_id, at_iso)
    if tp:
        return {"source": "timeclock_punches",
                  "shift_id": tp.get("id")}
    jt = await _open_job_timer(tenant_id, user_id, at_iso)
    if jt:
        return {"source": "job_timers", "shift_id": jt.get("id")}
    return None


async def is_user_on_shift(user_id: str, tenant_id: str,
                             at: Optional[datetime] = None) -> bool:
    """Thin ``bool`` wrapper over :func:`find_open_shift_ref` for
    callers that only need the gate decision.  Preferred over
    ad-hoc single-collection probes for every clock-state check
    outside ``timeclock_landscaping._unified_events`` (which
    returns the full event log for aggregation)."""
    ref = await find_open_shift_ref(user_id, tenant_id, at=at)
    return ref is not None
