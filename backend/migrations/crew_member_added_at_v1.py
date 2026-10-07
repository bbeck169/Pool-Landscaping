"""CREW-SCHEDULE-FANOUT · Feb-2026 — backfill ``crews.member_added_at``.

Phase B of ``CREW-SCHEDULE-FANOUT``.  The schedule-view fanout was
widened (``routers/schedule.py`` + ``routers/jobs.py``) so each
crew-member's visibility is time-boxed on ``member.added_at <=
job.scheduled_date``.  The per-member timestamp lives on a new
``member_added_at: Dict[str, str]`` map on each ``crews`` doc:

    { "<tech_id>": "<iso-utc-join-datetime>", … }

This script fills the map for every pre-existing crew where it's
missing.  Floor for existing members = ``crew.created_at`` (the only
timestamp we have).  New members added after this ship get stamped
with ``now_iso()`` by ``routers/ops.add_crew_member``.

Idempotent — a second run finds nothing to update and reports
``changed=0``.  Sentinel-gated via ``_migrations`` collection so a
healthy pod only pays the full-scan cost once per tenant pool.

Index note (G5 of the ticket brief): the compound key
``(tenant_id, crew_id, scheduled_date)`` already ships via
``migrations/k44_perf_indexes.k15_jobs_crew_schedule`` and is
registered on startup from ``server.py:_bg_k44_perf_indexes``.  We
do NOT redeclare it here — ``createIndex`` on an existing identical
spec is a safe no-op in Mongo, but duplicating the catalogue entry
would make the k44 inventory harder to audit.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict

from config import db


_SENTINEL_ID = "crew_member_added_at_v1"
logger = logging.getLogger("crew_member_added_at_v1")


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _already_ran() -> bool:
    row = await db["_migrations"].find_one({"id": _SENTINEL_ID})
    return bool(row and row.get("completed_at"))


async def _mark_complete(stats: Dict[str, Any]) -> None:
    await db["_migrations"].update_one(
        {"id": _SENTINEL_ID},
        {
            "$set": {
                "id": _SENTINEL_ID,
                "completed_at": _iso_now(),
                "stats": stats,
            },
        },
        upsert=True,
    )


async def run(*, force: bool = False) -> Dict[str, Any]:
    """Backfill ``member_added_at`` on every crew that's missing it.

    * ``force=True`` ignores the sentinel and re-runs the scan.  The
      update is still idempotent (``$set`` on a map value is a no-op
      when the value is unchanged), so forcing is safe.
    * Return shape: ``{"scanned": N, "updated": M, "skipped": K}``.
    """
    if not force and await _already_ran():
        return {"scanned": 0, "updated": 0, "skipped": 0, "sentinel": "present"}

    scanned = 0
    updated = 0
    skipped = 0

    async for crew in db.crews.find(
        {},
        {"_id": 0, "id": 1, "tech_ids": 1, "member_added_at": 1,
         "created_at": 1, "tenant_id": 1},
    ):
        scanned += 1
        existing = crew.get("member_added_at") or {}
        tech_ids = [t for t in (crew.get("tech_ids") or []) if t]
        if not tech_ids:
            skipped += 1
            continue
        # Floor used for existing members = the crew's own
        # ``created_at`` (best-effort: we have no finer signal for
        # when a specific tech was added pre-``member_added_at``).
        floor = crew.get("created_at") or _iso_now()
        patch: Dict[str, str] = {}
        for tid in tech_ids:
            if tid in existing and existing[tid]:
                # Already stamped — leave it alone.  Idempotent.
                continue
            patch[f"member_added_at.{tid}"] = floor
        if not patch:
            skipped += 1
            continue
        r = await db.crews.update_one({"id": crew["id"]}, {"$set": patch})
        if r.modified_count:
            updated += 1
        else:
            skipped += 1

    stats = {"scanned": scanned, "updated": updated, "skipped": skipped}
    await _mark_complete(stats)
    logger.info("[migration] crew_member_added_at_v1 %s", stats)
    return stats
