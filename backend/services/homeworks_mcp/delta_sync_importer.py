"""Queue Item 5 · Feb-2026 — Homeworks Delta Sync importer.

Thin wrapper that runs the two existing customer importers back-to-
back — active first, then inactive — under a single run document
tracked as ``kind = "delta_sync"``. Both underlying importers are
strictly idempotent (skip-if-``original_id``-exists), so this run
picks up only customers created on the Homeworks side since the
previous successful full or delta sync. No update-in-place: mirrors
the existing importers' contract.

Design rationale (deliberately not a full re-implementation):
  * We already own two production-locked importers with rate-limiting,
    checkpointing, cancel handling, poison-pill tolerance, and
    child-entity cascade skips. Duplicating any of that logic here
    creates two drift surfaces for the same MCP client behaviour.
  * The idempotency contract already ships the "delta" for free:
    scan everything, insert only when ``original_id`` isn't present.
  * A P2 backlog item exists to consolidate active + inactive into a
    single config-driven module. This wrapper is intentionally small
    so it can graduate cleanly once that consolidation lands.

Ships an operator launcher (``scripts/homeworks_run_delta_sync.py``)
so a super_admin can spin the run in the same nohup shape the other
two importers use.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from config import db
from services.homeworks_mcp import (
    active_customers_importer as _active,
    inactive_customers_importer as _inactive,
)

logger = logging.getLogger("homeworks_mcp.delta_sync")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Dry-run report ───────────────────────────────────────────────────
@dataclass
class DryRunReport:
    """Aggregated dry-run report across both underlying importers.

    Kept flat + serializable so ``FastAPI`` can return it directly and
    the launcher can hydrate it from the run doc without importing
    the underlying importer's dataclass shape.
    """
    active_report: Dict[str, Any] = field(default_factory=dict)
    inactive_report: Dict[str, Any] = field(default_factory=dict)
    total_customer_count: int = 0
    existing_in_aquaterra_by_original_id: int = 0
    estimated_duration_minutes: int = 0
    since_last_sync: Optional[str] = None  # ISO of most recent finished run
    fatal_error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ── Helpers ──────────────────────────────────────────────────────────
async def _last_successful_sync_at(tenant_id: str) -> Optional[str]:
    """Look up the newest ``finished_at`` across any of the three
    customer-touching import kinds for this tenant. Used purely as
    an informational field on the dry-run report — the underlying
    importers do their own skip-if-exists filtering so we do NOT
    pass this cursor down to them.
    """
    doc = await db.homeworks_import_runs.find_one(
        {"tenant_id": tenant_id,
         "kind": {"$in": ["active_customers", "inactive_customers",
                            "delta_sync"]},
         "status": "completed",
         "finished_at": {"$ne": None}},
        {"_id": 0, "finished_at": 1},
        sort=[("finished_at", -1)],
    )
    return (doc or {}).get("finished_at")


async def dry_run(tenant_id: str, *,
                    user_id: Optional[str] = None) -> DryRunReport:
    """Run BOTH underlying dry-runs and aggregate. Fails soft on the
    per-cohort report so a single failing branch doesn't kill the
    whole preview."""
    report = DryRunReport()
    try:
        active_report = await _active.dry_run(tenant_id, user_id=user_id)
        report.active_report = active_report.to_dict()
    except Exception as exc:  # noqa: BLE001
        logger.warning("[delta_sync] active dry_run failed: %s", exc)
        report.active_report = {"fatal_error": f"active:{exc}"}
    try:
        inactive_report = await _inactive.dry_run(tenant_id, user_id=user_id)
        report.inactive_report = inactive_report.to_dict()
    except Exception as exc:  # noqa: BLE001
        logger.warning("[delta_sync] inactive dry_run failed: %s", exc)
        report.inactive_report = {"fatal_error": f"inactive:{exc}"}

    a_total = int(report.active_report.get("inactive_customer_count") or 0)
    i_total = int(report.inactive_report.get("inactive_customer_count") or 0)
    a_existing = int(report.active_report.get(
        "existing_in_aquaterra_by_original_id") or 0)
    i_existing = int(report.inactive_report.get(
        "existing_in_aquaterra_by_original_id") or 0)
    a_dur = int(report.active_report.get("estimated_duration_minutes") or 0)
    i_dur = int(report.inactive_report.get("estimated_duration_minutes") or 0)

    report.total_customer_count = a_total + i_total
    report.existing_in_aquaterra_by_original_id = a_existing + i_existing
    report.estimated_duration_minutes = a_dur + i_dur
    report.since_last_sync = await _last_successful_sync_at(tenant_id)

    if (report.active_report.get("fatal_error")
            and report.inactive_report.get("fatal_error")):
        report.fatal_error = "both_cohorts_failed_dry_run"
    return report


# ── Run persistence ──────────────────────────────────────────────────
async def create_run(*, tenant_id: str, user_id: Optional[str],
                      dry_run_report: Optional[DryRunReport],
                      status: str = "queued") -> str:
    run_id = uuid.uuid4().hex
    doc = {
        "run_id": run_id,
        "tenant_id": tenant_id,
        "started_at": _now_iso(),
        "finished_at": None,
        "status": status,
        "kind": "delta_sync",
        "dry_run_report": dry_run_report.to_dict() if dry_run_report else None,
        "sub_runs": {  # populated by run_full as it delegates
            "active_customers": None,
            "inactive_customers": None,
        },
        "counters": {
            "customers_scanned": 0,
            "customers_imported": 0,
            "customers_skipped": 0,
            "customers_failed": 0,
        },
        "resume_cursor": 0,
        "error_log": [],
        "started_by_user_id": user_id,
        "updated_at": _now_iso(),
    }
    await db.homeworks_import_runs.insert_one(doc)
    return run_id


# ── Driver ───────────────────────────────────────────────────────────
async def _delegate_run(*, tenant_id: str, user_id: Optional[str],
                          importer, kind: str,
                          parent_run_id: str) -> Dict[str, Any]:
    """Create a queued sub-run for one underlying importer, tick it
    through ``run_full``, and return the resulting counters + run_id.
    Failures are captured on the parent run's error log."""
    sub_run_id = await importer.create_run(
        tenant_id=tenant_id, user_id=user_id,
        dry_run_report=None, status="queued",
    )
    await db.homeworks_import_runs.update_one(
        {"run_id": parent_run_id},
        {"$set": {f"sub_runs.{kind}": sub_run_id,
                    "updated_at": _now_iso()}},
    )
    try:
        counters = await importer.run_full(
            tenant_id=tenant_id, user_id=user_id, run_id=sub_run_id,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("[delta_sync] sub-run %s (%s) crashed", kind,
                          sub_run_id)
        await db.homeworks_import_runs.update_one(
            {"run_id": parent_run_id},
            {"$push": {"error_log": {
                "stage": f"sub_run_crash:{kind}",
                "sub_run_id": sub_run_id, "error": str(exc)[:500],
                "at": _now_iso(),
            }}},
        )
        return {"crashed": True, "sub_run_id": sub_run_id,
                "counters": {}}
    return {"crashed": False, "sub_run_id": sub_run_id,
            "counters": asdict(counters)}


async def run_full(*, tenant_id: str, user_id: Optional[str],
                    run_id: str) -> Dict[str, Any]:
    """Drive the delta sync end-to-end. Runs active first (typically
    smaller cohort → faster feedback), then inactive. Aggregates
    counters into the parent run doc."""
    # Promote to running.
    await db.homeworks_import_runs.update_one(
        {"run_id": run_id},
        {"$set": {"status": "running", "updated_at": _now_iso()}},
    )

    active_result = await _delegate_run(
        tenant_id=tenant_id, user_id=user_id,
        importer=_active, kind="active_customers",
        parent_run_id=run_id,
    )
    inactive_result = await _delegate_run(
        tenant_id=tenant_id, user_id=user_id,
        importer=_inactive, kind="inactive_customers",
        parent_run_id=run_id,
    )

    # Aggregate.
    def _sum(a: Dict[str, Any], b: Dict[str, Any], key: str) -> int:
        return int(a.get(key) or 0) + int(b.get(key) or 0)

    ac = active_result.get("counters") or {}
    ic = inactive_result.get("counters") or {}
    agg = {
        "customers_scanned": _sum(ac, ic, "customers_scanned"),
        "customers_imported": _sum(ac, ic, "customers_imported"),
        "customers_skipped": _sum(ac, ic, "customers_skipped"),
        "customers_failed": _sum(ac, ic, "customers_failed"),
    }
    both_crashed = active_result["crashed"] and inactive_result["crashed"]
    final_status = "failed" if both_crashed else "completed"
    await db.homeworks_import_runs.update_one(
        {"run_id": run_id},
        {"$set": {"status": final_status,
                    "counters": agg,
                    "finished_at": _now_iso(),
                    "updated_at": _now_iso()}},
    )
    return agg
