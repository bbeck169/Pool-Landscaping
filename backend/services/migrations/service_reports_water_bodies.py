"""Feb-2026 · Multi-body service reports — boot migration.

Idempotent + sentinel-guarded. Scans every ``service_reports`` doc that
lacks a ``water_bodies`` array and populates a single default body
from the legacy top-level fields (``chemical_readings`` →
``water_bodies[0].readings``; ``chemicals_added`` →
``water_bodies[0].chemicals_used``; ``photos`` → ``water_bodies[0].media``;
``notes`` → ``water_bodies[0].notes``).

The body ``type`` is inferred from the parent job:
  * Pool-classified jobs → ``"pool"``.
  * Everything else      → ``"other"``.

The top-level fields are LEFT IN PLACE — the router keeps them as a
backward-compat mirror so pre-migration mobile clients, doorhanger
renderers, and any consumer that hasn't been ported yet keep working.

Contract:
  * Idempotent — subsequent boots see the sentinel and short-circuit.
    Docs that already carry a non-empty ``water_bodies`` are skipped
    even inside the same run.
  * Never mutates a submitted-locked report's semantics — only adds
    the new array; legacy fields are preserved verbatim.
  * Reports the number of docs scanned / migrated / skipped so
    operators can spot outliers in the boot log.

Sentinel: ``feb2026_service_reports_water_bodies_v1``.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from config import db
from services.water_bodies import build_default_body_from_report
from utils import now_iso


logger = logging.getLogger("service_reports_water_bodies_migration")


_SENTINEL_ID = "feb2026_service_reports_water_bodies_v1"


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


def _needs_migration_filter() -> Dict[str, Any]:
    return {
        "$or": [
            {"water_bodies": {"$exists": False}},
            {"water_bodies": None},
            {"water_bodies": []},
        ],
    }


async def run_water_bodies_migration(*, force: bool = False) -> Dict[str, Any]:
    """Full-fleet migration entry point.

    ``force=True`` bypasses the sentinel — used by the super_admin
    admin endpoint for on-demand re-runs (mirrors the pattern used by
    ``invoice_number_backfill``).
    """
    if not force:
        sentinel = await _sentinel_row()
        if sentinel:
            logger.info(
                "[service_reports.water_bodies] sentinel present · skipping",
            )
            return {
                "status": "skipped",
                "reason": "sentinel_present",
                "sentinel": sentinel,
            }

    scanned = 0
    migrated = 0
    skipped_already_multi = 0
    errors: list = []
    now = now_iso()

    cursor = db.service_reports.find(
        _needs_migration_filter(),
        {"_id": 0, "id": 1, "tenant_id": 1, "job_id": 1,
          "chemical_readings": 1, "chemicals_added": 1,
          "photos": 1, "notes": 1, "water_bodies": 1},
    )
    async for rep in cursor:
        scanned += 1
        try:
            if isinstance(rep.get("water_bodies"), list) and rep["water_bodies"]:
                # Raced with a concurrent write — treat as done.
                skipped_already_multi += 1
                continue
            job = None
            if rep.get("job_id") and rep.get("tenant_id"):
                job = await db.jobs.find_one(
                    {"id": rep["job_id"], "tenant_id": rep["tenant_id"]},
                    {"_id": 0, "service_type": 1, "job_type": 1,
                      "title": 1, "template": 1},
                )
            body = build_default_body_from_report(rep, job=job or {})
            result = await db.service_reports.update_one(
                {"id": rep["id"],
                  "$or": [
                    {"water_bodies": {"$exists": False}},
                    {"water_bodies": None},
                    {"water_bodies": []},
                  ]},
                {"$set": {
                    "water_bodies": [body],
                    "updated_at": now,
                    "water_bodies_migrated_at": now,
                }},
            )
            if result.modified_count:
                migrated += 1
        except Exception as exc:                                # noqa: BLE001
            errors.append({"id": rep.get("id"), "error": str(exc)})
            logger.warning(
                f"[service_reports.water_bodies] {rep.get('id')} failed: {exc}",
            )

    summary = {
        "scanned": scanned,
        "migrated": migrated,
        "skipped_already_multi": skipped_already_multi,
        "errors_count": len(errors),
        # Feb-2026 · Phase 2 preflight — contract wants both keys so the
        # admin UI can render an "Errors" section without inspecting
        # ``errors_sample``. ``errors`` is always a list (empty when
        # ``errors_count == 0``); ``errors_sample`` is retained for
        # backwards compat.
        "errors": errors,
    }
    if errors:
        summary["errors_sample"] = errors[:10]
    await _write_sentinel(summary)
    logger.info(
        f"[service_reports.water_bodies] scanned={scanned} "
        f"migrated={migrated} skipped_already_multi={skipped_already_multi} "
        f"errors={len(errors)}",
    )
    return {"status": "ok", "summary": summary}
