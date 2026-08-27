"""Feb 2026 · Customer Merge · Phase 3 — one-time boot cleanup.

Sentinel-guarded wrapper around
:func:`services.customer_merge.auto_merge.run_auto_merge_sweep_all_tenants`
so a fresh boot cleans up any pre-existing high-confidence duplicate
clusters that predate the Phase 1 detection engine.

Sentinel id: ``feb2026_customer_merge_boot_cleanup_v1``. Skips
re-running when the sentinel is already stamped. ``force=True``
bypasses the sentinel (used by the admin "Force sweep now"
endpoint).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict

from config import db

from services.customer_merge.auto_merge import (
    run_auto_merge_sweep_all_tenants,
)


logger = logging.getLogger("customer_merge.boot_cleanup")


_SENTINEL_ID = "feb2026_customer_merge_boot_cleanup_v1"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def run_customer_merge_boot_cleanup(*, force: bool = False) -> Dict[str, Any]:
    """Idempotent boot migration. Returns the rollup summary produced
    by the underlying sweep + an ``already_ran`` flag when the
    sentinel gated the run."""
    sentinel = await db.migrations.find_one({"id": _SENTINEL_ID})
    if sentinel and not force:
        return {
            "already_ran": True,
            "ran_at": sentinel.get("ran_at"),
            "summary": sentinel.get("summary") or {},
        }

    # Boot cleanup deliberately bypasses ``AUTO_MERGE_ENABLED`` — the
    # env flag exists to gate the daily cron; a one-time boot
    # cleanup is a deploy-level decision that already ran to this
    # point. If ops wants to skip cleanup entirely, don't ship the
    # migration.
    report = await run_auto_merge_sweep_all_tenants(
        initiated_by="auto", respect_env_flag=False,
    )

    if sentinel and force:
        await db.migrations.update_one(
            {"id": _SENTINEL_ID},
            {"$set": {"last_forced_run_at": _now_iso(),
                       "last_forced_summary": {
                           k: v for k, v in report.items()
                           if k not in {"per_tenant", "audit_ids"}
                       }}},
        )
    else:
        await db.migrations.insert_one({
            "id": _SENTINEL_ID,
            "ran_at": _now_iso(),
            "summary": {
                k: v for k, v in report.items()
                if k not in {"per_tenant", "audit_ids"}
            },
        })

    logger.info(
        "[customer_merge_boot] scanned %d tenants, auto-merged %d groups, "
        "affected %d records",
        report.get("tenants_scanned", 0),
        report.get("groups_auto_merged", 0),
        report.get("records_affected", 0),
    )
    return {"already_ran": False, "ran_at": _now_iso(), "summary": report}
