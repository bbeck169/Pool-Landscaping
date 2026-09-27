"""LDM-A · Feb-2026 — Tenant ``settings.automation_rules`` backfill.

First structural pass of the AI Live Dispatcher + Predictive Maintenance
track (see ``memory/SPEC_LIVE_DISPATCHER_AND_MAINTENANCE.md``). Seeds
the four automation-rule fields on every tenant document that lacks
them:

    settings.automation_rules.dispatch_delay_threshold_mins = 20
    settings.automation_rules.dispatch_sms_customer_count   = 3
    settings.automation_rules.filter_clean_interval_months  = 6
    settings.automation_rules.salt_cell_replacement_months  = 36

Idempotent. Fields that already carry a value (default or admin-set)
are preserved — the sweep only writes missing keys, never overwrites.
Sentinel-gated via ``migration_status[key="automation_rules_v1"]`` so
subsequent boot passes short-circuit without a full ``tenants.find``
cursor drain.

Return shape (dry-run + execute + short-circuit all return the same
keys — mirrors the P52 / marco_orchestrator_seed_v1 conventions)::

    {
        "ok": bool,
        "skipped": bool,
        "skipped_by_marker": bool,
        "tenants_scanned": int,
        "tenants_backfilled": int,  # tenants that received at least one $set
        "fields_written": int,      # sum of per-tenant missing-key counts
        "duration_s": float,
        "dry_run": bool,
        "executed_at": iso | None,
    }

Usage:
    python -m migrations.automation_rules_v1 --dry-run
    python -m migrations.automation_rules_v1 --execute
    python -m migrations.automation_rules_v1 --execute --force
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from config import db, logger


MIGRATION_KEY = "automation_rules_v1"
MARKER_COLLECTION = "migration_status"

# Server-authoritative defaults. Kept in lockstep with
# ``routers/tenants.py::AUTOMATION_RULE_DEFAULTS`` — either bump both
# or neither. The tenants router's read helper falls back to these
# same values when a rule is missing, so a pod that comes up before
# this migration lands still hydrates sane defaults into the API
# response — but the persisted document isn't shaped correctly until
# the sweep runs.
DEFAULTS: Dict[str, int] = {
    "dispatch_delay_threshold_mins": 20,
    "dispatch_sms_customer_count": 3,
    "filter_clean_interval_months": 6,
    "salt_cell_replacement_months": 36,
}

# Boot wiring — ``True`` because the backfill is safe to auto-apply
# (idempotent, only touches missing sub-keys) and lets a pod that
# lands before the sentinel is stamped self-heal on the first boot
# after this PR.
STARTUP_EXECUTE_MODE = True


# ═════════════════════════════════════════════════════════════════
# Sentinel helpers (mirror marco_orchestrator_seed_v1 — same
# ``migration_status`` collection that ``_REQUIRED_MIGRATIONS`` in
# server.py reads for the ``/api/health`` readiness probe).
# ═════════════════════════════════════════════════════════════════
async def _sentinel_present(target) -> bool:
    row = await target[MARKER_COLLECTION].find_one(
        {"key": MIGRATION_KEY}, {"_id": 0},
    )
    return bool(row and row.get("completed_at"))


async def _stamp_sentinel(target, summary: Dict[str, Any]) -> None:
    now = datetime.now(timezone.utc).isoformat()
    await target[MARKER_COLLECTION].update_one(
        {"key": MIGRATION_KEY},
        {"$set": {
            "key": MIGRATION_KEY,
            "completed_at": now,
            "tenants_scanned": int(summary.get("tenants_scanned") or 0),
            "tenants_backfilled": int(summary.get("tenants_backfilled") or 0),
            "fields_written": int(summary.get("fields_written") or 0),
            "must_succeed": False,
        }},
        upsert=True,
    )


# ═════════════════════════════════════════════════════════════════
# Core apply
# ═════════════════════════════════════════════════════════════════
async def run(*, dry_run: bool = False, force: bool = False,
              db_client=None, log=None) -> Dict[str, Any]:
    """One sweep across ``tenants``. Returns the summary above."""
    target = db_client if db_client is not None else db
    lg = log or logger
    started = time.monotonic()
    now_iso = datetime.now(timezone.utc).isoformat()

    # Marker short-circuit — execute only. Dry-run always inspects.
    if not dry_run and not force and await _sentinel_present(target):
        lg.info(
            "[%s] sentinel present — skipping (use --force to re-run)",
            MIGRATION_KEY,
        )
        return {
            "ok": True,
            "skipped": True,
            "skipped_by_marker": True,
            "tenants_scanned": 0,
            "tenants_backfilled": 0,
            "fields_written": 0,
            "duration_s": round(time.monotonic() - started, 3),
            "dry_run": False,
            "executed_at": None,
        }

    tenants_scanned = 0
    tenants_backfilled = 0
    fields_written = 0

    async for t in target.tenants.find(
        {}, {"_id": 0, "id": 1, "settings.automation_rules": 1},
    ):
        tenants_scanned += 1
        tid = t.get("id")
        if not tid:
            continue
        current = ((t.get("settings") or {}).get("automation_rules") or {})
        set_ops: Dict[str, Any] = {}
        for key, default_val in DEFAULTS.items():
            if key not in current:
                set_ops[f"settings.automation_rules.{key}"] = default_val
        if not set_ops:
            continue
        tenants_backfilled += 1
        fields_written += len(set_ops)
        if not dry_run:
            await target.tenants.update_one(
                {"id": tid}, {"$set": set_ops},
            )
        lg.info(
            "[%s] tenant=%s backfilled=%s%s",
            MIGRATION_KEY, tid, len(set_ops),
            " (dry-run)" if dry_run else "",
        )

    summary = {
        "ok": True,
        "skipped": False,
        "skipped_by_marker": False,
        "tenants_scanned": tenants_scanned,
        "tenants_backfilled": tenants_backfilled,
        "fields_written": fields_written,
        "duration_s": round(time.monotonic() - started, 3),
        "dry_run": dry_run,
        "executed_at": None if dry_run else now_iso,
    }

    if not dry_run:
        await _stamp_sentinel(target, summary)

    lg.info(
        "[%s] complete tenants_scanned=%s tenants_backfilled=%s "
        "fields_written=%s dry_run=%s",
        MIGRATION_KEY, tenants_scanned, tenants_backfilled,
        fields_written, dry_run,
    )
    return summary


# ═════════════════════════════════════════════════════════════════
# Startup entry point (called from server.py boot chain)
# ═════════════════════════════════════════════════════════════════
async def run_at_startup(db_client=None) -> Optional[Dict[str, Any]]:
    """Idempotent auto-apply on backend boot.

    Sentinel-gated internally; a second boot short-circuits without
    a full ``tenants.find`` cursor drain. Never re-raises — matches
    the ``must_succeed=False`` posture of the surrounding structural
    bucket in ``server.py``.
    """
    if not STARTUP_EXECUTE_MODE:
        return None
    try:
        return await run(dry_run=False, force=False, db_client=db_client)
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "[%s] startup apply failed: %s", MIGRATION_KEY, exc,
        )
        return {
            "ok": False,
            "skipped": False,
            "skipped_by_marker": False,
            "tenants_scanned": 0,
            "tenants_backfilled": 0,
            "fields_written": 0,
            "duration_s": 0.0,
            "dry_run": False,
            "executed_at": None,
            "error": str(exc),
        }


# ═════════════════════════════════════════════════════════════════
# CLI
# ═════════════════════════════════════════════════════════════════
def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Backfill tenant.settings.automation_rules (LDM-A).",
    )
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true",
                       help="Inspect + report; no writes.")
    mode.add_argument("--execute", action="store_true",
                       help="Apply the backfill. Idempotent.")
    p.add_argument("--force", action="store_true",
                    help="Ignore the migration_status sentinel.")
    return p.parse_args()


async def _cli_main() -> int:
    args = _parse_args()
    summary = await run(dry_run=args.dry_run, force=args.force)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_cli_main()))
