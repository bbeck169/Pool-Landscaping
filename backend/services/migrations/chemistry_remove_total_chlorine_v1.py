"""Phase CHEM1 · Feb-2026 — one-shot ``total_chlorine`` removal migration.

Idempotent. ``$unset``s every persisted trace of ``total_chlorine``
from the ``service_reports`` (+ related) collections:

  * ``service_reports.chemical_readings[].key == "total_chlorine"``
    (list-of-dicts shape — the canonical tech write path)
  * ``service_reports.water_bodies[*].readings[].key == "total_chlorine"``
    (multi-body write path)
  * legacy dict-shape mirrors on ``jobs.chemical_readings.total_chlorine``
    (older seeds persisted this shape) and
    ``service_reports.chemical_readings.total_chlorine`` (same story).

The migration NEVER touches any other reading key and NEVER upserts.
Docs that don't reference ``total_chlorine`` are skipped by the
per-doc guard, so a subsequent run performs zero writes (report the
second-run count in the return envelope).

Sentinel key: ``feb2026_chemistry_remove_total_chlorine_v1``. The
sentinel is a soft guard only — every caller may pass ``force=True``
to bypass it. The per-doc ``$unset`` filter still short-circuits
already-clean docs.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from config import db

logger = logging.getLogger(__name__)

_SENTINEL = "feb2026_chemistry_remove_total_chlorine_v1"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _sentinel_fired() -> bool:
    doc = await db.migrations.find_one({"_id": _SENTINEL}, {"_id": 1})
    return doc is not None


async def _stamp_sentinel(summary: Dict[str, Any]) -> None:
    await db.migrations.update_one(
        {"_id": _SENTINEL},
        {"$set": {"_id": _SENTINEL, "ran_at": _now_iso(),
                    "summary": summary}},
        upsert=True,
    )


async def _unset_list_of_dicts(
    collection: str, tenant_id: Optional[str], dry_run: bool,
) -> Dict[str, int]:
    """``$pull`` every ``chemical_readings[]`` element whose ``key``
    equals ``total_chlorine`` on docs in ``collection``.

    Returns ``{scanned, updated}``. When ``dry_run`` is truthy the
    scanned count is populated but no ``$pull`` fires."""
    q: Dict[str, Any] = {
        "chemical_readings": {"$elemMatch": {"key": "total_chlorine"}},
    }
    if tenant_id:
        q["tenant_id"] = tenant_id
    coll = db[collection]
    scanned = await coll.count_documents(q)
    if scanned == 0 or dry_run:
        return {"scanned": scanned, "updated": 0}
    res = await coll.update_many(
        q,
        {"$pull": {"chemical_readings": {"key": "total_chlorine"}}},
    )
    return {"scanned": scanned, "updated": int(res.modified_count or 0)}


async def _unset_water_body_readings(
    tenant_id: Optional[str], dry_run: bool,
) -> Dict[str, int]:
    """``$pull`` the ``total_chlorine`` reading from every
    ``water_bodies[*].readings[]`` entry on ``service_reports``.

    Uses a positional-all update so we hit every body in the array.
    """
    q: Dict[str, Any] = {
        "water_bodies.readings": {
            "$elemMatch": {"key": "total_chlorine"},
        },
    }
    if tenant_id:
        q["tenant_id"] = tenant_id
    scanned = await db.service_reports.count_documents(q)
    if scanned == 0 or dry_run:
        return {"scanned": scanned, "updated": 0}
    res = await db.service_reports.update_many(
        q,
        {"$pull": {"water_bodies.$[].readings": {"key": "total_chlorine"}}},
    )
    return {"scanned": scanned, "updated": int(res.modified_count or 0)}


async def _unset_dict_shape(
    collection: str, tenant_id: Optional[str], dry_run: bool,
) -> Dict[str, int]:
    """``$unset`` the legacy ``chemical_readings.total_chlorine`` dict
    key on docs where ``chemical_readings`` is persisted as a dict
    (older seeds). Idempotent — ``$exists: true`` narrows the sweep so
    the second run flips 0 docs."""
    q: Dict[str, Any] = {
        "chemical_readings.total_chlorine": {"$exists": True},
    }
    if tenant_id:
        q["tenant_id"] = tenant_id
    coll = db[collection]
    scanned = await coll.count_documents(q)
    if scanned == 0 or dry_run:
        return {"scanned": scanned, "updated": 0}
    res = await coll.update_many(
        q, {"$unset": {"chemical_readings.total_chlorine": ""}},
    )
    return {"scanned": scanned, "updated": int(res.modified_count or 0)}


async def run_remove_total_chlorine_migration(
    *,
    force: bool = False,
    dry_run: bool = False,
    tenant_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Phase CHEM1 · Feb-2026 — run the one-shot ``$unset`` sweep.

    Args:
        force: bypass the ``feb2026_chemistry_remove_total_chlorine_v1``
            sentinel. Every ``$unset`` filter is idempotent regardless.
        dry_run: report what WOULD be touched without writing.
        tenant_id: optional scope to a single tenant.

    Returns:
        ``{sentinel, dry_run, tenant_id, service_reports_list,
          service_reports_dict, jobs_dict, water_bodies, totals}``
        where each per-collection value is ``{scanned, updated}``.
    """
    already_fired = await _sentinel_fired()
    if already_fired and not force:
        logger.info(
            "[chem1-remove-total-chlorine] sentinel already fired — skipping"
        )
        return {
            "sentinel": _SENTINEL,
            "sentinel_fired_before": True,
            "skipped": True,
            "dry_run": dry_run,
            "tenant_id": tenant_id,
        }

    sr_list = await _unset_list_of_dicts(
        "service_reports", tenant_id, dry_run,
    )
    sr_dict = await _unset_dict_shape(
        "service_reports", tenant_id, dry_run,
    )
    jobs_dict = await _unset_dict_shape("jobs", tenant_id, dry_run)
    wb = await _unset_water_body_readings(tenant_id, dry_run)

    totals = {
        "scanned": (sr_list["scanned"] + sr_dict["scanned"]
                     + jobs_dict["scanned"] + wb["scanned"]),
        "updated": (sr_list["updated"] + sr_dict["updated"]
                     + jobs_dict["updated"] + wb["updated"]),
    }

    summary = {
        "service_reports_list_of_dicts": sr_list,
        "service_reports_dict_shape":    sr_dict,
        "jobs_dict_shape":               jobs_dict,
        "water_bodies_nested":           wb,
        "totals":                        totals,
    }

    if not dry_run:
        await _stamp_sentinel(summary)

    logger.info(
        "[chem1-remove-total-chlorine] dry_run=%s tenant_id=%s totals=%s",
        dry_run, tenant_id, totals,
    )
    return {
        "sentinel": _SENTINEL,
        "sentinel_fired_before": already_fired,
        "dry_run": dry_run,
        "tenant_id": tenant_id,
        **summary,
    }
