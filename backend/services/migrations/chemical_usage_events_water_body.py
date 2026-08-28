"""Feb-2026 · Multi-body Phase 1 · Option 2 · chemical_usage_events
backfill.

Adds a nullable ``water_body_id`` column (plus companion
``water_body_type`` / ``water_body_label``) to every legacy
``chemical_usage_events`` doc so the rewritten
``/api/reports/chemical-costs`` aggregator can split rollups per body.

Behavior:
  * Idempotent + sentinel-guarded — sentinel
    ``chemical_usage_events_water_body_v1``.
  * For every event that lacks ``water_body_id`` (i.e. never has been
    stamped since Phase 1 · Option 2 shipped):
      - Stamp ``water_body_id: null``.
      - If the parent ``service_reports`` doc carries exactly ONE
        ``water_bodies[]`` entry AND that body has a chemical whose
        slug matches the event's ``product_slug``, best-effort link
        the event to that body's id / type / label.
      - Otherwise leave ``water_body_id: null`` (rolls into the
        ``Legacy`` bucket in the report response).
  * Never rewrites events that already carry a ``water_body_id``.
  * Runs on boot after the ``service_reports.water_bodies``
    migration (order matters — the report bodies must exist before we
    can link events to them).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from config import db
from utils import now_iso


logger = logging.getLogger("chemical_usage_events_water_body_migration")


_SENTINEL_ID = "chemical_usage_events_water_body_v1"


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
    return {"water_body_id": {"$exists": False}}


async def run_chemical_usage_events_water_body_migration(
    *, force: bool = False,
) -> Dict[str, Any]:
    """Full-fleet migration entry point.

    ``force=True`` bypasses the sentinel — used by the super_admin
    admin endpoint for on-demand re-runs.
    """
    if not force:
        sentinel = await _sentinel_row()
        if sentinel:
            logger.info(
                "[chemical_usage_events.water_body] sentinel present · skipping",
            )
            return {
                "status": "skipped",
                "reason": "sentinel_present",
                "sentinel": sentinel,
            }

    scanned = 0
    stamped_null = 0
    linked_to_body = 0
    errors: list = []
    now = now_iso()

    # Cache service_reports → water_bodies map to avoid a query per
    # event. Only fetches reports that CAN carry bodies (i.e. those
    # touched by the Phase 1 backend migration).
    report_cache: Dict[str, Any] = {}

    async def _bodies_for(service_report_id: str, tenant_id: str):
        """Return ``water_bodies`` for a report (cached)."""
        key = (service_report_id, tenant_id)
        if key in report_cache:
            return report_cache[key]
        rep = await db.service_reports.find_one(
            {"id": service_report_id, "tenant_id": tenant_id},
            {"_id": 0, "id": 1, "water_bodies": 1},
        )
        bodies = list((rep or {}).get("water_bodies") or [])
        report_cache[key] = bodies
        return bodies

    cursor = db.chemical_usage_events.find(
        _needs_migration_filter(),
        {"_id": 0, "id": 1, "tenant_id": 1, "service_report_id": 1,
          "product_slug": 1, "water_body_id": 1},
    )
    async for ev in cursor:
        scanned += 1
        try:
            sr_id = ev.get("service_report_id")
            tid = ev.get("tenant_id")
            product_slug = str(ev.get("product_slug") or "").lower()
            body_id = None
            body_type = None
            body_label = None
            if sr_id and tid:
                bodies = await _bodies_for(sr_id, tid)
                # Best-effort link when a UNIQUE body carries a
                # chemical whose slug matches this event's slug. This
                # keeps the legacy attribution honest — we don't
                # guess when it's ambiguous (e.g. same chem in both
                # pool + spa on a multi-body report).
                candidates = []
                for b in bodies:
                    slugs = {
                        str((c or {}).get("product_slug")
                              or (c or {}).get("slug")
                              or "").lower()
                        for c in (b.get("chemicals_used")
                                    or b.get("chemicals_added") or [])
                    }
                    if product_slug and product_slug in slugs:
                        candidates.append(b)
                if len(candidates) == 1:
                    b = candidates[0]
                    body_id = b.get("id")
                    body_type = (b.get("type") or "").lower() or None
                    body_label = b.get("label")
                elif len(bodies) == 1:
                    # Report has exactly one body — every event
                    # belongs to it even if the slug fuzzy-match
                    # above missed (legacy events sometimes carried
                    # names instead of slugs).
                    b = bodies[0]
                    body_id = b.get("id")
                    body_type = (b.get("type") or "").lower() or None
                    body_label = b.get("label")
            result = await db.chemical_usage_events.update_one(
                {"id": ev["id"],
                  "water_body_id": {"$exists": False}},
                {"$set": {
                    "water_body_id": body_id,
                    "water_body_type": body_type,
                    "water_body_label": body_label,
                    "water_body_backfilled_at": now,
                }},
            )
            if result.modified_count:
                if body_id:
                    linked_to_body += 1
                else:
                    stamped_null += 1
        except Exception as exc:                                # noqa: BLE001
            errors.append({"id": ev.get("id"), "error": str(exc)})
            logger.warning(
                f"[chemical_usage_events.water_body] "
                f"{ev.get('id')} failed: {exc}",
            )

    summary = {
        "scanned": scanned,
        "linked_to_body": linked_to_body,
        "stamped_null": stamped_null,
        "errors_count": len(errors),
        "errors": errors,
    }
    if errors:
        summary["errors_sample"] = errors[:10]
    await _write_sentinel(summary)
    logger.info(
        f"[chemical_usage_events.water_body] scanned={scanned} "
        f"linked_to_body={linked_to_body} stamped_null={stamped_null} "
        f"errors={len(errors)}",
    )
    return {"status": "ok", "summary": summary}
