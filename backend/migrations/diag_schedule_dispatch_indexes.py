"""
Feb-2026 · Diag-Timeout Task 3 — Schedule/Dispatch perf indexes.

Companion to Task 1 (customer-search haystack). Fills the missing
compound indexes that back the ``/schedule/today`` and
``/dispatch/board`` hot paths.

Motivation
──────────
Prod tenants report ~30 s spinner on ``/schedule`` list + map loads.
Query-shape audit of the two endpoints turned up:

* ``GET /api/schedule/today`` fires:
    ``{tenant_id, scheduled_date: {$gte, $lte}, $and:[$or:[
       technician_id, assigned_technician_id, assigned_to, crew_id]]}``
    K15 already covers ``(tenant_id, technician_id, scheduled_date)``
    and ``(tenant_id, crew_id, scheduled_date)`` — but the two other
    OR arms (``assigned_technician_id`` and ``assigned_to``) COLLSCAN.

* ``GET /api/dispatch/board`` fires:
    ``{tenant_id, service_lat: {$exists, $ne: null}, service_days,
       $or:[category_ids, tags:$regex]}``
    then a second ``customers.find`` for unrouted. Nothing indexes
    ``(tenant_id, service_lat)`` or ``(tenant_id, service_days)`` so
    both scans read every customer doc.

This migration is additive + idempotent (``create_index`` no-ops
when the name+keys match) and runs UNCONDITIONALLY on boot, same
belt-and-suspenders shape as ``k44_perf_indexes.py``.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

from config import db

logger = logging.getLogger("diag_schedule_dispatch_indexes")

_SENTINEL_ID = "diag_schedule_dispatch_indexes_v1"

_INDEXES: List[Tuple[str, str, List[Tuple[str, int]]]] = [
    # Schedule/today alternate tech-id OR arms (K15 only covered
    # ``technician_id``).
    ("jobs", "diag_jobs_tenant_assigned_tech_sched",
     [("tenant_id", 1), ("assigned_technician_id", 1),
       ("scheduled_date", 1)]),
    ("jobs", "diag_jobs_tenant_assigned_to_sched",
     [("tenant_id", 1), ("assigned_to", 1), ("scheduled_date", 1)]),
    # Sort-order coverage for the schedule/today output sort.
    # (Mongo will use the (tenant_id, scheduled_date) index for the
    # match + then in-memory sort on (route_index, created_at); when
    # the day is small this is fine, but the compound index below
    # eliminates the sort stage on wide days.)
    ("jobs", "diag_jobs_tenant_sched_route_idx",
     [("tenant_id", 1), ("scheduled_date", 1), ("route_index", 1),
       ("created_at", 1)]),
    # Dispatch board — geocoded-pins scan and unrouted scan.
    ("customers", "diag_customers_tenant_service_lat",
     [("tenant_id", 1), ("service_lat", 1)]),
    ("customers", "diag_customers_tenant_service_days",
     [("tenant_id", 1), ("service_days", 1)]),
    ("customers", "diag_customers_tenant_assigned_tech",
     [("tenant_id", 1), ("assigned_tech_ids", 1)]),
    # Dispatch fallback `db.jobs.find({tenant_id, scheduled_date:
    # {$regex: ^YYYY-MM-DD}, $or: [tech_user_id, assigned_to,
    # technician_id]})` — the K15 (tenant_id, tech_user_id,
    # scheduled_date) index already helps the first OR arm; the
    # ``diag_jobs_tenant_assigned_to_sched`` above covers the third.
    # ``technician_id`` clause is served by K15's
    # ``k15_jobs_tech_schedule_status``.
]


async def _write_sentinel(summary: Dict[str, Any]) -> None:
    await db.migrations.update_one(
        {"id": _SENTINEL_ID},
        {"$set": {
            "id": _SENTINEL_ID,
            "last_run_at": datetime.now(timezone.utc).isoformat(),
            "summary": summary,
        }},
        upsert=True,
    )


async def run() -> Dict[str, Any]:
    summary: Dict[str, Any] = {
        "created": 0, "already_present": 0, "errors": [], "targets": [],
    }
    cache: Dict[str, set] = {}
    for coll_name, idx_name, keys in _INDEXES:
        target: Dict[str, Any] = {
            "collection": coll_name, "index": idx_name,
        }
        try:
            if coll_name not in cache:
                names = set()
                async for idx in db[coll_name].list_indexes():
                    names.add(idx.get("name") or "")
                cache[coll_name] = names
            if idx_name in cache[coll_name]:
                target["status"] = "already_present"
                summary["already_present"] += 1
            else:
                await db[coll_name].create_index(
                    keys, name=idx_name, background=True,
                )
                cache[coll_name].add(idx_name)
                target["status"] = "created"
                summary["created"] += 1
                logger.info(
                    "[diag_schedule] created %s on %s",
                    idx_name, coll_name,
                )
        except Exception as exc:  # noqa: BLE001
            target["status"] = "error"
            target["error"] = str(exc)
            summary["errors"].append(target)
            logger.warning(
                "[diag_schedule] index %s.%s failed: %s",
                coll_name, idx_name, exc,
            )
        summary["targets"].append(target)
    try:
        await _write_sentinel(summary)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[diag_schedule] sentinel write failed: %s", exc)
    logger.info(
        "[diag_schedule] created=%s already_present=%s errors=%s",
        summary["created"], summary["already_present"],
        len(summary["errors"]),
    )
    # Also mark this run in ``migration_status`` so the readiness
    # probe's ``perf_customers_v1``-style gate can key off the same
    # collection shape for a future rollout.
    try:
        await db.migration_status.update_one(
            {"key": _SENTINEL_ID},
            {"$set": {"key": _SENTINEL_ID,
                        "completed_at": datetime.now(
                            tz=timezone.utc,
                        ).isoformat(),
                        "summary": summary}},
            upsert=True,
        )
    except Exception:  # noqa: BLE001
        pass
    return {"status": "ok", "summary": summary}
