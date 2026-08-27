"""Feb 2026 · One-time backfill: stamp ``technician_name`` on jobs
that were created before the Feb-2026 write-side denorm fix started
persisting it.

Contract:
  * Runs once per environment — guarded by a sentinel doc in
    ``db.migrations`` (``id: 'feb2026_technician_names_backfill_v1'``).
    Second-and-later boots become a ~10ms no-op.
  * Eligibility: ``technician_id`` set + ``technician_name`` empty
    (missing / None / empty string) + NOT soft-deleted
    (``deleted_at`` absent or None).
  * Resolution uses the same shared ``resolve_technician_names``
    cascade the read-time enrichers call (``db.users.technician_id``
    canonical wins, then ``db.technicians``, then ``db.users.id``,
    then synthesise from ``first_name + last_name``). If nothing
    resolves, the job is LEFT UNTOUCHED — logged as unresolved so
    ops can investigate rather than fabricate a name.
  * Writes ONE ``$set`` per resolvable job. Skipped jobs (soft-
    deleted OR unresolved) are counted in the summary log.

Ships as a startup routine wired from ``server.py`` — matches the
pattern of the existing ``routers/job_titles.py``
``backfill_from_existing_jobs`` migration.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict

from config import db


logger = logging.getLogger("technician_backfill")


_SENTINEL_ID = "feb2026_technician_names_backfill_v1"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def backfill_technician_names_on_jobs() -> Dict[str, Any]:
    """Idempotent backfill. Returns a summary dict::

        {
          "skipped": bool,   # True if the sentinel says we already ran
          "reason":  str,    # only when skipped=True
          "eligible": int,   # jobs matched by the eligibility query
          "backfilled": int, # jobs successfully written
          "unresolved": int, # jobs the resolver couldn't name
          "soft_deleted_skipped": int,  # matched by counter query
          "tenants_touched": int,
        }
    """
    sentinel = await db.migrations.find_one({"id": _SENTINEL_ID})
    if sentinel:
        return {
            "skipped": True, "reason": "already_ran",
            "ran_at": sentinel.get("ran_at"),
            "backfilled": sentinel.get("backfilled", 0),
            "unresolved": sentinel.get("unresolved", 0),
        }

    from services.service_report_view import resolve_technician_names

    # Eligibility — technician_id set, technician_name empty/missing,
    # not soft-deleted. We inline the ``$or`` for the soft-delete
    # guard because ``utils.not_deleted_filter`` already returns an
    # ``$or`` clause and Mongo won't accept two top-level ``$or``
    # arrays. Instead we merge them into ``$and``.
    eligibility = {
        "$and": [
            {"technician_id": {"$exists": True, "$nin": [None, ""]}},
            {"$or": [
                {"technician_name": {"$exists": False}},
                {"technician_name": None},
                {"technician_name": ""},
            ]},
            {"$or": [
                {"deleted_at": None},
                {"deleted_at": {"$exists": False}},
            ]},
        ],
    }

    # Soft-deleted counter — how many otherwise-eligible jobs we
    # deliberately skipped (spec asks us to log it).
    soft_deleted_skipped = await db.jobs.count_documents({
        "$and": [
            {"technician_id": {"$exists": True, "$nin": [None, ""]}},
            {"$or": [
                {"technician_name": {"$exists": False}},
                {"technician_name": None},
                {"technician_name": ""},
            ]},
            {"deleted_at": {"$ne": None, "$exists": True}},
        ],
    })

    # Group by tenant so we can batch the resolver query.
    tenants: Dict[str, list] = {}
    async for row in db.jobs.find(
        eligibility,
        {"_id": 0, "id": 1, "tenant_id": 1, "technician_id": 1},
    ):
        tid = row.get("tenant_id")
        if not tid:
            continue
        tenants.setdefault(tid, []).append(row)

    backfilled = 0
    unresolved = 0
    eligible = sum(len(rows) for rows in tenants.values())

    for tenant_id, rows in tenants.items():
        # Dedupe the tech ids we ask the resolver about — a large
        # tenant may have dozens of jobs per tech.
        tids = list({r.get("technician_id") for r in rows
                       if r.get("technician_id")})
        name_map = await resolve_technician_names(db, tenant_id, tids)
        for row in rows:
            job_id = row.get("id")
            tech_id = row.get("technician_id")
            if not job_id or not tech_id:
                continue
            resolved = (name_map.get(tech_id) or "").strip()
            if not resolved:
                unresolved += 1
                continue
            # Stamp both the resolved name AND a small audit
            # breadcrumb so ops can filter to "backfilled by this
            # migration" if we ever need to roll it back.
            await db.jobs.update_one(
                {"id": job_id, "tenant_id": tenant_id},
                {"$set": {
                    "technician_name": resolved,
                    "technician_name_backfilled_at": _now_iso(),
                }},
            )
            backfilled += 1

    report = {
        "skipped": False,
        "eligible": eligible,
        "backfilled": backfilled,
        "unresolved": unresolved,
        "soft_deleted_skipped": soft_deleted_skipped,
        "tenants_touched": sum(1 for rs in tenants.values() if rs),
    }

    await db.migrations.insert_one({
        "id": _SENTINEL_ID,
        "ran_at": _now_iso(),
        **report,
    })

    logger.info(
        "[tech-backfill] backfilled %d jobs, %d unresolved, "
        "%d skipped (soft-deleted), %d tenants",
        backfilled, unresolved, soft_deleted_skipped, report["tenants_touched"],
    )
    return report
