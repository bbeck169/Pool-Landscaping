"""Feb-2026 · Recurring Jobs — one-time idempotent backfill for the
new ``is_active`` gate + ``start_date`` invariant.

Contract:
  * For every ``recurring_job_templates`` row WITHOUT an
    ``is_active`` field: stamp ``is_active = bool(active)`` so
    existing business behavior (legacy ``active: True`` default)
    is preserved end-to-end. Any legacy row that was soft-deleted
    via the pre-fix DELETE endpoint (``active: False``) stays
    ``is_active: False`` too.
  * For every row with neither ``is_active`` nor ``start_date``:
    also stamp ``start_date = created_at.date()`` when the row
    carries a ``created_at`` timestamp. When ``created_at`` is
    missing, ``start_date`` is left null and the generator gate
    keeps it out of the nightly run (the operator must edit the
    template through the UI to seed the missing date).

Idempotent — safe to re-run on every pod boot. The first pass
does the write; subsequent passes find zero candidates and
return ``{"scanned": …, "backfilled": 0, "start_date_backfilled": 0}``.

Wired via ``server.py`` startup pipeline; see the ``step(...)``
call next to the other Feb-2026 migrations.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict

from config import db, logger


async def backfill_recurring_is_active() -> Dict[str, Any]:
    scanned = 0
    backfilled = 0
    start_date_backfilled = 0

    async for row in db.recurring_job_templates.find(
        {"is_active": {"$exists": False}},
        {"_id": 1, "id": 1, "active": 1, "start_date": 1, "created_at": 1},
    ):
        scanned += 1
        set_updates: Dict[str, Any] = {
            # Preserve existing business behavior — the legacy
            # ``active`` default was True, so old rows migrate to
            # ``is_active=True`` and keep generating.
            "is_active": bool(row.get("active", True)),
        }
        # Optionally seed ``start_date`` from ``created_at`` when
        # both are missing. We only touch ``start_date`` if it's
        # unset AND the row carries a parseable ``created_at``.
        if not row.get("start_date") and row.get("created_at"):
            _created_raw = row["created_at"]
            _created_iso = None
            if isinstance(_created_raw, str):
                _created_iso = _created_raw
            elif isinstance(_created_raw, datetime):
                _created_iso = _created_raw.isoformat()
            if _created_iso:
                # Trim to YYYY-MM-DD — matches the ``start_date``
                # ISO-date contract used everywhere else in this
                # router.
                try:
                    _d = _created_iso[:10]
                    # Validate the shape without pulling ``date``.
                    datetime.fromisoformat(_d)
                    set_updates["start_date"] = _d
                    start_date_backfilled += 1
                except Exception:  # noqa: BLE001
                    pass
        await db.recurring_job_templates.update_one(
            {"_id": row["_id"]}, {"$set": set_updates},
        )
        backfilled += 1

    logger.info(
        "[migration:recurring_is_active_backfill] scanned=%d "
        "is_active_backfilled=%d start_date_backfilled=%d",
        scanned, backfilled, start_date_backfilled,
    )
    return {
        "scanned": scanned,
        "backfilled": backfilled,
        "start_date_backfilled": start_date_backfilled,
    }
