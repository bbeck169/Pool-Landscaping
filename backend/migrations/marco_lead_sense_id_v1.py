"""LS-A · Feb-2026 — Tenant ``marco_lead_sense_id`` backfill.

First structural pass of the MARCO Lead-Sense track (see
``memory/SPEC_MARCO_LEAD_SENSE.md``). Seeds two additive
fields on every tenant document that lacks them:

    marco_lead_sense_id           = <12-char nanoid>
    lead_sense_allowed_origins    = []

The id is generated via ``secrets.token_urlsafe(9)`` (yields a
12-char URL-safe string) with a small collision-retry loop so
the migration remains safe if run against a database that
already carries a partial backfill from a prior aborted pass.

Idempotent. Fields that already carry a value (a super-admin-
seeded id or admin-configured origin list) are preserved — the
sweep only writes missing keys, never overwrites.

Also ensures a UNIQUE partial index on ``marco_lead_sense_id``
so the LS-B intake endpoint can resolve tenants by lead-sense-
id in O(1) without a full-scan risk. Partial-filter clause
skips docs where the field is null so a partial-backfill state
doesn't collide with the unique constraint.

Sentinel-gated via
``migration_status[key="marco_lead_sense_id_v1"]`` so
subsequent boot passes short-circuit without a full
``tenants.find`` cursor drain.

Return shape (dry-run + execute + short-circuit all return the
same keys — mirrors ``automation_rules_v1`` / P52 conventions)::

    {
        "ok": bool,
        "skipped": bool,
        "skipped_by_marker": bool,
        "tenants_scanned": int,
        "tenants_backfilled": int,
        "ids_generated": int,
        "origins_seeded": int,
        "index_ensured": bool,
        "duration_s": float,
        "dry_run": bool,
        "executed_at": iso | None,
    }

Usage:
    python -m migrations.marco_lead_sense_id_v1 --dry-run
    python -m migrations.marco_lead_sense_id_v1 --execute
    python -m migrations.marco_lead_sense_id_v1 --execute --force
"""
from __future__ import annotations

import argparse
import asyncio
import json
import secrets
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from config import db, logger


MIGRATION_KEY = "marco_lead_sense_id_v1"
MARKER_COLLECTION = "migration_status"


# Boot wiring — ``True`` because the backfill is safe to auto-
# apply (idempotent, additive) and lets a pod that lands before
# the sentinel is stamped self-heal on the first boot after
# this PR.
STARTUP_EXECUTE_MODE = True

# Field length: ``secrets.token_urlsafe(9)`` returns 12 chars
# (9 bytes → 12 base64url chars, no padding). Kept in lockstep
# with ``routers.tenants._LEAD_SENSE_ID_LENGTH``.
_ID_NBYTES = 9
_MAX_COLLISION_RETRIES = 3


def _new_lead_sense_id() -> str:
    """Return a fresh 12-char URL-safe id.

    ``token_urlsafe(9)`` produces 12 base64url chars from 9
    random bytes — 72 bits of entropy, effectively collision-
    free below billions of tenants. The migration still handles
    collisions defensively (see ``run``'s retry loop) so an
    attacker who can somehow trigger repeated rotates can't
    poison the flow.
    """
    return secrets.token_urlsafe(_ID_NBYTES)


# ═════════════════════════════════════════════════════════════════
# Sentinel helpers (mirror automation_rules_v1 / marco_orchestrator_seed_v1)
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
            "ids_generated": int(summary.get("ids_generated") or 0),
            "origins_seeded": int(summary.get("origins_seeded") or 0),
            "must_succeed": False,
        }},
        upsert=True,
    )


async def _ensure_unique_index(target, lg) -> bool:
    """Create the unique partial index on ``tenants.marco_lead_sense_id``
    if it doesn't already exist. Uses ``partialFilterExpression``
    to skip null values so the index is safe in the presence of
    tenants that still lack the field (rare — this sweep should
    backfill them — but the transition window is real).

    Returns ``True`` iff the index now exists (either freshly
    created or already present).
    """
    try:
        await target.tenants.create_index(
            [("marco_lead_sense_id", 1)],
            unique=True,
            name="marco_lead_sense_id_unique",
            partialFilterExpression={
                "marco_lead_sense_id": {"$type": "string"},
            },
        )
        return True
    except Exception as exc:  # noqa: BLE001
        lg.warning(
            "[%s] unique index ensure failed (continuing): %s",
            MIGRATION_KEY, exc,
        )
        return False


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
            "ids_generated": 0,
            "origins_seeded": 0,
            "index_ensured": False,
            "duration_s": round(time.monotonic() - started, 3),
            "dry_run": False,
            "executed_at": None,
        }

    # Pre-seed the set of ids already in use so we can dedupe
    # generated candidates without a per-tenant round-trip.
    existing_ids = set()
    async for t in target.tenants.find(
        {"marco_lead_sense_id": {"$type": "string"}},
        {"_id": 0, "marco_lead_sense_id": 1},
    ):
        val = t.get("marco_lead_sense_id")
        if isinstance(val, str) and val:
            existing_ids.add(val)

    tenants_scanned = 0
    tenants_backfilled = 0
    ids_generated = 0
    origins_seeded = 0

    async for t in target.tenants.find(
        {},
        {"_id": 0, "id": 1, "marco_lead_sense_id": 1,
         "lead_sense_allowed_origins": 1},
    ):
        tenants_scanned += 1
        tid = t.get("id")
        if not tid:
            continue
        set_ops: Dict[str, Any] = {}
        # Field 1 — marco_lead_sense_id (only if missing).
        cur_id = t.get("marco_lead_sense_id")
        if not (isinstance(cur_id, str) and cur_id):
            # Generate a fresh id, retrying if we happen to collide
            # with one already assigned (astronomically unlikely
            # but the retry keeps us robust in test scenarios that
            # seed lots of tenants).
            new_id: Optional[str] = None
            for _ in range(_MAX_COLLISION_RETRIES + 1):
                cand = _new_lead_sense_id()
                if cand not in existing_ids:
                    new_id = cand
                    existing_ids.add(cand)
                    break
            if new_id is None:
                lg.warning(
                    "[%s] tenant=%s: could not generate a "
                    "collision-free id after %s attempts — "
                    "skipping this tenant",
                    MIGRATION_KEY, tid, _MAX_COLLISION_RETRIES + 1,
                )
                continue
            set_ops["marco_lead_sense_id"] = new_id
            ids_generated += 1
        # Field 2 — lead_sense_allowed_origins (only if missing).
        cur_orig = t.get("lead_sense_allowed_origins")
        if cur_orig is None:
            set_ops["lead_sense_allowed_origins"] = []
            origins_seeded += 1
        if not set_ops:
            continue
        tenants_backfilled += 1
        if not dry_run:
            await target.tenants.update_one(
                {"id": tid}, {"$set": set_ops},
            )
        lg.info(
            "[%s] tenant=%s backfilled_fields=%s%s",
            MIGRATION_KEY, tid, list(set_ops.keys()),
            " (dry-run)" if dry_run else "",
        )

    # Ensure the unique index — even if no rows were backfilled
    # in this pass. Idempotent (Mongo returns success if the
    # index already exists with the same spec).
    index_ensured = False
    if not dry_run:
        index_ensured = await _ensure_unique_index(target, lg)

    summary = {
        "ok": True,
        "skipped": False,
        "skipped_by_marker": False,
        "tenants_scanned": tenants_scanned,
        "tenants_backfilled": tenants_backfilled,
        "ids_generated": ids_generated,
        "origins_seeded": origins_seeded,
        "index_ensured": index_ensured,
        "duration_s": round(time.monotonic() - started, 3),
        "dry_run": dry_run,
        "executed_at": None if dry_run else now_iso,
    }

    if not dry_run:
        await _stamp_sentinel(target, summary)

    lg.info(
        "[%s] complete tenants_scanned=%s tenants_backfilled=%s "
        "ids_generated=%s origins_seeded=%s index_ensured=%s "
        "dry_run=%s",
        MIGRATION_KEY, tenants_scanned, tenants_backfilled,
        ids_generated, origins_seeded, index_ensured, dry_run,
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
            "ids_generated": 0,
            "origins_seeded": 0,
            "index_ensured": False,
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
        description=(
            "Backfill tenant.marco_lead_sense_id + "
            "lead_sense_allowed_origins (LS-A)."
        ),
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
