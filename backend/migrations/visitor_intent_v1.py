"""LS-B · Feb-2026 — ``visitor_intent`` collection index bootstrap.

Ensures the three indexes required by the LS-B intake + future
LS-D/E surfaces:

    (tenant_id, occurred_at desc)                 — per-tenant timelines
    (tenant_id, session_id, occurred_at)          — per-session journeys
    (session_id)                                  — cross-tenant lookups
                                                    (never exposed by API,
                                                    cheap to have for ops)

Idempotent. Sentinel-gated via
``migration_status[key="visitor_intent_v1"]`` so the second boot
short-circuits without any additional work — Mongo's
``create_index`` is already idempotent when the same spec exists,
but the sentinel keeps the boot log clean.

Return shape mirrors the LS-A / LDM-A migrations::

    {
        "ok": bool,
        "skipped": bool,
        "skipped_by_marker": bool,
        "indexes_ensured": int,
        "duration_s": float,
        "dry_run": bool,
        "executed_at": iso | None,
    }
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


MIGRATION_KEY = "visitor_intent_v1"
MARKER_COLLECTION = "migration_status"


STARTUP_EXECUTE_MODE = True


# ═════════════════════════════════════════════════════════════════
# Sentinel helpers (mirror marco_lead_sense_id_v1)
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
            "indexes_ensured": int(summary.get("indexes_ensured") or 0),
            "must_succeed": False,
        }},
        upsert=True,
    )


# ═════════════════════════════════════════════════════════════════
# Index bootstrap
# ═════════════════════════════════════════════════════════════════
_INDEX_SPECS = (
    {
        "name": "visitor_intent_tenant_occurred_desc",
        "keys": [("tenant_id", 1), ("occurred_at", -1)],
    },
    {
        "name": "visitor_intent_tenant_session_occurred",
        "keys": [
            ("tenant_id", 1), ("session_id", 1), ("occurred_at", -1),
        ],
    },
    {
        "name": "visitor_intent_session",
        "keys": [("session_id", 1)],
    },
)


async def _ensure_indexes(target, lg) -> int:
    """Create every index in ``_INDEX_SPECS``. Returns the count
    of indexes present after the pass. Never re-raises — a
    permission blip logs a warning and boot continues."""
    ensured = 0
    for spec in _INDEX_SPECS:
        try:
            await target.visitor_intent.create_index(
                spec["keys"], name=spec["name"],
            )
            ensured += 1
        except Exception as exc:  # noqa: BLE001
            lg.warning(
                "[%s] index %s ensure failed (continuing): %s",
                MIGRATION_KEY, spec["name"], exc,
            )
    return ensured


# ═════════════════════════════════════════════════════════════════
# Core apply
# ═════════════════════════════════════════════════════════════════
async def run(*, dry_run: bool = False, force: bool = False,
              db_client=None, log=None) -> Dict[str, Any]:
    target = db_client if db_client is not None else db
    lg = log or logger
    started = time.monotonic()
    now_iso = datetime.now(timezone.utc).isoformat()

    if not dry_run and not force and await _sentinel_present(target):
        lg.info(
            "[%s] sentinel present — skipping (use --force to re-run)",
            MIGRATION_KEY,
        )
        return {
            "ok": True,
            "skipped": True,
            "skipped_by_marker": True,
            "indexes_ensured": 0,
            "duration_s": round(time.monotonic() - started, 3),
            "dry_run": False,
            "executed_at": None,
        }

    if dry_run:
        # Report the specs without touching the collection.
        summary = {
            "ok": True,
            "skipped": False,
            "skipped_by_marker": False,
            "indexes_ensured": 0,
            "indexes_planned": [s["name"] for s in _INDEX_SPECS],
            "duration_s": round(time.monotonic() - started, 3),
            "dry_run": True,
            "executed_at": None,
        }
        lg.info(
            "[%s] dry-run — %s indexes would be ensured",
            MIGRATION_KEY, len(_INDEX_SPECS),
        )
        return summary

    ensured = await _ensure_indexes(target, lg)
    summary = {
        "ok": True,
        "skipped": False,
        "skipped_by_marker": False,
        "indexes_ensured": ensured,
        "duration_s": round(time.monotonic() - started, 3),
        "dry_run": False,
        "executed_at": now_iso,
    }
    await _stamp_sentinel(target, summary)
    lg.info(
        "[%s] complete indexes_ensured=%s duration_s=%s",
        MIGRATION_KEY, ensured, summary["duration_s"],
    )
    return summary


# ═════════════════════════════════════════════════════════════════
# Startup entry point
# ═════════════════════════════════════════════════════════════════
async def run_at_startup(db_client=None) -> Optional[Dict[str, Any]]:
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
            "indexes_ensured": 0,
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
        description="Ensure visitor_intent indexes (LS-B).",
    )
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true",
                       help="Report the specs; no writes.")
    mode.add_argument("--execute", action="store_true",
                       help="Apply the indexes. Idempotent.")
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
