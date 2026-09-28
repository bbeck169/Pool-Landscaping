"""HD-A · Nightly purge worker.

Sweeps every eligible collection and hard-purges rows whose
``deleted_at`` is older than ``HARD_DELETE_PURGE_AFTER_DAYS`` days
(defaults to 30). Runs the standard cascade purge path so
tombstones are written for every row deleted.

Two entry points:

1. ``run_nightly_purge()`` — a coroutine intended to be scheduled
   by whatever job system the platform uses (currently the FastAPI
   startup does not carry a real scheduler; the endpoint below is
   available for a cron-triggered admin call).
2. ``POST /api/hard-delete/admin/run-nightly-purge`` — super-admin
   button that invokes the same coroutine on-demand. Wire-up lives
   in ``routers/hard_delete.py`` so the router stays cohesive.
"""
from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from config import db, logger

from .cascade import purge_cascade
from .registry import all_specs


def _purge_after_days() -> int:
    try:
        return int(os.environ.get("HARD_DELETE_PURGE_AFTER_DAYS", "30"))
    except (TypeError, ValueError):
        return 30


def _cutoff_iso(days: Optional[int] = None) -> str:
    d = days if days is not None else _purge_after_days()
    cutoff = datetime.now(timezone.utc) - timedelta(days=d)
    return cutoff.isoformat().replace("+00:00", "Z")


async def _list_expired_roots(
    days: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Return every soft-deleted doc older than the cutoff, tagged
    ``cascade_role=root`` where possible.  Children carrying
    ``cascade_role=child`` are skipped — cascade purge handles them
    via the root's descent, so hitting them individually would
    double-purge and (harmlessly) log a "not found" tombstone.
    """
    cutoff = _cutoff_iso(days)
    rows: List[Dict[str, Any]] = []
    for spec in all_specs():
        cursor = db[spec.collection].find(
            {
                "deleted_at": {"$ne": None, "$exists": True, "$lt": cutoff},
                # Skip children — the root walks them for us.
                "$or": [
                    {"cascade_role": {"$ne": "child"}},
                    {"cascade_role": {"$exists": False}},
                ],
            },
            {"_id": 0, "id": 1, "tenant_id": 1, "deleted_at": 1,
             "cascade_role": 1},
        )
        async for row in cursor:
            rows.append({
                "entity_type": spec.entity_type,
                "id": row["id"],
                "tenant_id": row.get("tenant_id"),
                "deleted_at": row.get("deleted_at"),
            })
    return rows


async def run_nightly_purge(
    *,
    days: Optional[int] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Purge every eligible row older than the retention window.

    Args:
        days: Override for ``HARD_DELETE_PURGE_AFTER_DAYS``. Useful
            for manual test invocations.
        dry_run: If True, enumerate the candidates but skip the
            actual purge writes. Response includes ``candidates``.

    Returns::

        {
          "cutoff":     "<ISO cutoff>",
          "candidates": <int>,
          "purged":     <int>,
          "blocked":    [ … stripe-locked refs the sweep couldn't purge … ],
          "errors":     [ … per-row exceptions swallowed here … ]
        }
    """
    candidates = await _list_expired_roots(days)
    resp: Dict[str, Any] = {
        "cutoff": _cutoff_iso(days),
        "candidates": len(candidates),
        "purged": 0,
        "blocked": [],
        "errors": [],
    }
    if dry_run:
        resp["dry_run"] = True
        resp["candidates_detail"] = candidates
        return resp

    for cand in candidates:
        try:
            result, blocks = await purge_cascade(
                cand["entity_type"], cand["id"], cand["tenant_id"],
                user_id="system-nightly-purge",
                user_email="system-nightly-purge",
                purge_reason="nightly retention window",
                skip_trash=False,
            )
            if blocks:
                resp["blocked"].append({
                    "entity_type": cand["entity_type"],
                    "id": cand["id"],
                    "refs": blocks,
                })
                continue
            purged = result.get("purged") or {}
            resp["purged"] += sum(len(v) for v in purged.values())
        except Exception as exc:                                    # noqa: BLE001
            logger.exception(
                "[hard_delete.nightly_purge] failed on %s/%s",
                cand.get("entity_type"), cand.get("id"),
            )
            resp["errors"].append({
                "entity_type": cand["entity_type"],
                "id": cand["id"],
                "error": str(exc),
            })
    logger.info(
        "[hard_delete.nightly_purge] cutoff=%s candidates=%s purged=%s blocked=%s errors=%s",
        resp["cutoff"], resp["candidates"], resp["purged"],
        len(resp["blocked"]), len(resp["errors"]),
    )
    return resp


async def dry_run() -> Dict[str, Any]:
    """Alias for ``run_nightly_purge(dry_run=True)``."""
    return await run_nightly_purge(dry_run=True)


def _main() -> None:                                                 # pragma: no cover
    """CLI entrypoint — ``python -m backend.services.hard_delete.nightly_purge``."""
    result = asyncio.run(run_nightly_purge())
    print(result)


if __name__ == "__main__":                                            # pragma: no cover
    _main()
