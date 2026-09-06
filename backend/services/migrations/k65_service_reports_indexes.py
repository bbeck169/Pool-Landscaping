"""K65 · Feb-2026 — Service-report enrichment index for the Schedule
read path.

Sentinel: ``k65_service_reports_indexes_v1``. Idempotent + sentinel-
guarded, mirrors the K15/K21 pattern.

Background
----------
``routers/jobs.py::list_jobs`` runs a Phase 46.2 post-enrichment step
that resolves service-report pill flags for every job in the returned
window::

    db.service_reports.find(
        {"tenant_id": tid, "job_id": {"$in": jids}},
        {...},
    ).to_list(...)

The K65 diagnosis flagged this query as a suspected COLLSCAN at
Aquaterra prod scale. Post-diagnosis inspection of the live index map
revealed an EXISTING compound index
``tenant_id_1_job_id_1_tech_id_1`` whose ``(tenant_id, job_id)``
prefix ALREADY covers the query. This migration therefore:

  1. Detects the existing compound and records a
     ``already_covered_by_prefix`` status without creating a duplicate
     index (avoids wasted disk + writes on prod).
  2. Only creates the standalone ``k65_service_reports_tenant_job``
     compound ``(tenant_id ASC, job_id ASC)`` when NO prefix-covering
     index is present.
  3. Writes the sentinel row unconditionally on success so future
     boots early-return.

Ship report:
  - Sentinel key: ``k65_service_reports_indexes_v1``
  - Target index (only when prefix isn't already covered):
      ``k65_service_reports_tenant_job`` on
      ``(tenant_id ASC, job_id ASC)``
  - Estimated build time at Aquaterra prod scale (~35k
    service_reports rows): sub-second with ``background=True``;
    non-blocking on the primary.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from config import db


logger = logging.getLogger("k65_service_reports_indexes_migration")

_SENTINEL_ID = "k65_service_reports_indexes_v1"

_TARGET_NAME = "k65_service_reports_tenant_job"
_TARGET_KEYS: List[Tuple[str, int]] = [("tenant_id", 1), ("job_id", 1)]


async def _sentinel_row() -> Optional[Dict[str, Any]]:
    return await db.migrations.find_one({"id": _SENTINEL_ID}, {"_id": 0})


async def _write_sentinel(summary: Dict[str, Any]) -> None:
    await db.migrations.update_one(
        {"id": _SENTINEL_ID},
        {"$set": {
            "id": _SENTINEL_ID,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "summary": summary,
        }},
        upsert=True,
    )


def _prefix_covers(idx_key: List[Tuple[str, int]]) -> bool:
    """True when ``idx_key`` starts with ``[(tenant_id, 1), (job_id, 1)]``.
    Handles both the pymongo list-of-tuples shape and the raw
    SON-doc shape (both are surfaced through ``index_information``).
    """
    if not idx_key or len(idx_key) < 2:
        return False
    # First two fields must be tenant_id ASC + job_id ASC (in that order).
    try:
        return (
            idx_key[0][0] == "tenant_id" and int(idx_key[0][1]) == 1
            and idx_key[1][0] == "job_id" and int(idx_key[1][1]) == 1
        )
    except (IndexError, TypeError, ValueError):
        return False


async def run_k65_service_reports_indexes_migration(
    *, force: bool = False,
) -> Dict[str, Any]:
    """Create the K65 service_reports (tenant_id, job_id) prefix
    index unless already covered by an existing compound.

    Returns::

        {"status": "ok" | "skipped",
         "summary": {
             "created": <int>,
             "already_present": <int>,
             "already_covered_by_prefix": <int>,
             "covered_by": <name or None>,
             "errors": [...],
             "targets": [...],
         }}
    """
    if not force:
        sentinel = await _sentinel_row()
        if sentinel:
            return {
                "status": "skipped",
                "reason": "sentinel_present",
                "sentinel": sentinel,
            }

    summary: Dict[str, Any] = {
        "created": 0,
        "already_present": 0,
        "already_covered_by_prefix": 0,
        "covered_by": None,
        "errors": [],
        "targets": [],
    }

    # Scan existing indexes on service_reports.
    covered_by: Optional[str] = None
    existing_named: Dict[str, List[Tuple[str, int]]] = {}
    try:
        info = await db.service_reports.index_information()
        for name, meta in info.items():
            keys = meta.get("key") or []
            # ``index_information`` returns key as a list of
            # ``(field, direction)`` tuples on both sync + async
            # pymongo drivers.
            existing_named[name] = list(keys)
            if name == _TARGET_NAME:
                # Exact target already present.
                continue
            if _prefix_covers(list(keys)):
                covered_by = name
    except Exception as exc:  # noqa: BLE001
        summary["errors"].append({"stage": "list_indexes", "error": str(exc)})
        logger.warning("[k65] index_information failed: %s", exc)

    target_result: Dict[str, Any] = {"index": _TARGET_NAME}
    try:
        if _TARGET_NAME in existing_named:
            target_result["status"] = "already_present"
            summary["already_present"] += 1
        elif covered_by is not None:
            target_result["status"] = "already_covered_by_prefix"
            target_result["covered_by"] = covered_by
            summary["already_covered_by_prefix"] += 1
            summary["covered_by"] = covered_by
            logger.info(
                "[k65] target %s skipped — covered by prefix of %s",
                _TARGET_NAME, covered_by,
            )
        else:
            await db.service_reports.create_index(
                _TARGET_KEYS, name=_TARGET_NAME, background=True,
            )
            target_result["status"] = "created"
            summary["created"] += 1
    except Exception as exc:  # noqa: BLE001
        target_result["status"] = "error"
        target_result["error"] = str(exc)
        summary["errors"].append(target_result)
        logger.warning(
            "[k65] index service_reports.%s failed: %s",
            _TARGET_NAME, exc,
        )
    summary["targets"].append(target_result)

    if not summary["errors"]:
        await _write_sentinel(summary)

    logger.info(
        "[k65] created=%s already_present=%s covered_by_prefix=%s errors=%s",
        summary["created"], summary["already_present"],
        summary["already_covered_by_prefix"], len(summary["errors"]),
    )
    return {"status": "ok", "summary": summary}
