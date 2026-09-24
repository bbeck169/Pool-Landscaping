"""Phase P46 · Feb-2026 — ``bulk_charge_runs`` index swap.

Ops escape hatch that mirrors what the hardened ``ensure_indexes``
does at boot: drop the legacy 2-column
``tenant_idempotency_unique`` index and create the correct 3-column
``tenant_idempotency_dry_run_unique`` on
``(tenant_id, idempotency_key, dry_run)``.

Why a one-shot script when the boot path already self-heals?
Two reasons:

* **Prod fix without Republish.**  If prod ships with the legacy
  index and we need to unbreak bulk-charge writes NOW, the operator
  runs this script against prod (with ``--execute``) instead of
  waiting for the next full deploy cycle.
* **Auditability.**  On success, the script stamps
  ``migrations_applied[name="p46_bulk_charge_index_swap"]`` so
  subsequent runs short-circuit (unless ``--force``); the marker
  gives ops a clear "yes, this was applied" record.

Idempotent in every rung:
  * DROP is safe even when the legacy index is already absent
    (``ns not found`` / ``index not found`` → INFO + continue).
  * CREATE is safe when the correct 3-column index is already
    present (``list_indexes`` match by name + spec → skip).
  * If the same NAME exists but with a DIFFERENT spec, drop + recreate
    (WARN).  This is the "someone hand-created a 3-column index
    but with different key ordering" recovery path.

Return shape (dry-run + execute + short-circuit all return the
same keys — ops can grep the JSON):

    {
        "dropped_legacy": bool,      // legacy index was present and dropped
        "created_new": bool,         // new 3-col index was absent and created
        "already_correct": bool,     // no work needed — new already present
        "skipped_by_marker": bool,   // execute short-circuited by marker
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
from pathlib import Path
from typing import Any, Dict, Optional

from config import db, logger


MIGRATION_NAME = "p46_bulk_charge_index_swap"
MARKER_COLLECTION = "migrations_applied"

LEGACY_INDEX_NAME = "tenant_idempotency_unique"
NEW_INDEX_NAME = "tenant_idempotency_dry_run_unique"
NEW_INDEX_KEY_SPEC = [("tenant_id", 1), ("idempotency_key", 1),
                       ("dry_run", 1)]

# P46 startup wiring — mirrors P38 / P38.1.  ``True`` because the
# fix is safe to auto-apply (idempotent + inspects state first) and
# ops needs the boot pass to self-heal any pod that lands with the
# legacy index still attached.  Flip to ``False`` if a follow-up
# ever needs to gate this on manual approval.
STARTUP_EXECUTE_MODE = True


# ═════════════════════════════════════════════════════════════════
# Marker helpers
# ═════════════════════════════════════════════════════════════════
async def _marker_present(db_client=None) -> bool:
    target = db_client if db_client is not None else db
    doc = await target[MARKER_COLLECTION].find_one({"name": MIGRATION_NAME})
    return bool(doc)


async def _stamp_marker(summary: Dict[str, Any], db_client=None) -> None:
    target = db_client if db_client is not None else db
    now_iso = datetime.now(timezone.utc).isoformat()
    await target[MARKER_COLLECTION].update_one(
        {"name": MIGRATION_NAME},
        {"$set": {
            "name": MIGRATION_NAME,
            "applied_at": now_iso,
            "summary": {
                "dropped_legacy": summary.get("dropped_legacy"),
                "created_new": summary.get("created_new"),
                "already_correct": summary.get("already_correct"),
            },
        }},
        upsert=True,
    )


# ═════════════════════════════════════════════════════════════════
# Index-state helpers
# ═════════════════════════════════════════════════════════════════
async def _list_indexes(collection) -> Dict[str, Dict[str, Any]]:
    """Return ``{name: full-index-doc}`` for ``bulk_charge_runs``."""
    out: Dict[str, Dict[str, Any]] = {}
    async for ix in collection.list_indexes():
        name = ix.get("name") or ""
        out[name] = dict(ix)
    return out


def _new_index_spec_matches(ix: Dict[str, Any]) -> bool:
    """True when the existing index matches the P46 target spec:
    unique + 3-column key ordering ``(tenant_id, idempotency_key,
    dry_run)``.  Motor / pymongo returns the key as an ordered dict
    when the index was created via a list-of-tuples spec — coerce
    to a list of pairs before comparing."""
    if not ix.get("unique"):
        return False
    key_pairs = list((ix.get("key") or {}).items())
    return key_pairs == NEW_INDEX_KEY_SPEC


# ═════════════════════════════════════════════════════════════════
# Main entrypoint
# ═════════════════════════════════════════════════════════════════
async def run(
    *,
    execute: bool = False,
    force: bool = False,
    verbose: bool = False,
    db_client=None,
) -> Dict[str, Any]:
    """Swap the legacy 2-col unique index for the correct 3-col one.

    Parameters
    ----------
    execute:
        ``False`` (default) → dry-run: inspect state + report,
        NO mutations.  ``True`` → apply changes.  If the P46
        marker is already stamped (and ``force`` is False), short-
        circuits with ``skipped_by_marker: True``.
    force:
        Bypass the marker check.  Runs the swap even if the marker
        is stamped (useful for a hand-invoked re-repair after a
        manual rollback).
    verbose:
        Emit an extra pre-run INFO line dumping the full index
        list for the collection.  Silent on success by default.
    """
    from pymongo.errors import OperationFailure
    started = time.time()
    target = db_client if db_client is not None else db
    coll = target.bulk_charge_runs

    # ── Marker gate (execute-only) ─────────────────────────────
    if execute and not force and await _marker_present(target):
        logger.info(
            "[p46] marker present in %s — skipping execute pass "
            "(pass --force to override)",
            MARKER_COLLECTION,
        )
        return {
            "dropped_legacy": False,
            "created_new": False,
            "already_correct": False,
            "skipped_by_marker": True,
            "duration_s": round(time.time() - started, 3),
            "dry_run": False,
            "executed_at": None,
        }

    # ── Inspect current state ─────────────────────────────────
    current = await _list_indexes(coll)
    if verbose:
        logger.info("[p46] bulk_charge_runs indexes pre-run: %s",
                     [n for n in current.keys()])

    legacy_present = LEGACY_INDEX_NAME in current
    new_present = NEW_INDEX_NAME in current
    new_matches = (
        new_present and _new_index_spec_matches(current[NEW_INDEX_NAME])
    )

    # ── Fast-path: nothing to do ──────────────────────────────
    if not legacy_present and new_matches:
        logger.info(
            "[p46] bulk_charge_runs indexes already correct: "
            "legacy_present=False new_matches=True — no-op",
        )
        summary = {
            "dropped_legacy": False,
            "created_new": False,
            "already_correct": True,
            "skipped_by_marker": False,
            "duration_s": round(time.time() - started, 3),
            "dry_run": not execute,
            "executed_at": (
                datetime.now(timezone.utc).isoformat() if execute else None
            ),
        }
        # Stamp the marker even on the no-op execute so the next
        # boot short-circuits.
        if execute:
            await _stamp_marker(summary, target)
        return summary

    dropped_legacy = False
    created_new = False

    if not execute:
        # Dry-run reports what we WOULD do without mutating.
        would_drop = legacy_present
        would_create = not new_matches
        logger.info(
            "[p46] DRY-RUN — would_drop_legacy=%s would_create_new=%s "
            "legacy_present=%s new_present=%s new_matches=%s",
            would_drop, would_create,
            legacy_present, new_present, new_matches,
        )
        return {
            "dropped_legacy": would_drop,
            "created_new": would_create,
            "already_correct": False,
            "skipped_by_marker": False,
            "duration_s": round(time.time() - started, 3),
            "dry_run": True,
            "executed_at": None,
        }

    # ── Execute ────────────────────────────────────────────────
    # 1) Drop legacy if present.
    if legacy_present:
        try:
            await coll.drop_index(LEGACY_INDEX_NAME)
            dropped_legacy = True
            logger.info(
                "[p46] dropped legacy index %s on bulk_charge_runs",
                LEGACY_INDEX_NAME,
            )
        except OperationFailure as exc:
            # Race window: another migration or ensure_indexes could
            # have dropped it between our list + drop.  Treat as OK.
            if ("index not found" not in str(exc).lower()
                    and "ns not found" not in str(exc).lower()):
                logger.error(
                    "[p46] drop legacy index failed: %s — continuing "
                    "so the new index can still be created",
                    exc,
                )
            else:
                logger.info(
                    "[p46] legacy index already absent (race) — continuing",
                )

    # 2) Create/repair the new 3-col unique index.
    if new_present and not new_matches:
        # Same name, wrong spec — drop + recreate (WARN).
        logger.warning(
            "[p46] existing %s has wrong spec — dropping + recreating",
            NEW_INDEX_NAME,
        )
        try:
            await coll.drop_index(NEW_INDEX_NAME)
        except OperationFailure as exc:
            logger.error(
                "[p46] drop mismatched %s failed: %s", NEW_INDEX_NAME, exc,
            )
        new_present = False  # ensure we go into create branch

    if not new_present:
        try:
            await coll.create_index(
                NEW_INDEX_KEY_SPEC,
                unique=True,
                name=NEW_INDEX_NAME,
                background=True,
            )
            created_new = True
            logger.info(
                "[p46] created new 3-column unique index %s on "
                "bulk_charge_runs (tenant_id, idempotency_key, dry_run)",
                NEW_INDEX_NAME,
            )
        except OperationFailure as exc:
            if "already exists" in str(exc).lower():
                logger.info(
                    "[p46] %s already exists (race) — continuing",
                    NEW_INDEX_NAME,
                )
            else:
                logger.error("[p46] create %s failed: %s",
                              NEW_INDEX_NAME, exc)
                raise

    summary = {
        "dropped_legacy": dropped_legacy,
        "created_new": created_new,
        "already_correct": False,
        "skipped_by_marker": False,
        "duration_s": round(time.time() - started, 3),
        "dry_run": False,
        "executed_at": datetime.now(timezone.utc).isoformat(),
    }
    await _stamp_marker(summary, target)
    logger.info(
        "[p46] complete — dropped_legacy=%s created_new=%s duration=%ss",
        dropped_legacy, created_new, summary["duration_s"],
    )
    return summary


# ═════════════════════════════════════════════════════════════════
# CLI
# ═════════════════════════════════════════════════════════════════
def _build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="p46_bulk_charge_index_swap",
        description=(
            "Swap the legacy 2-col unique index on "
            "``bulk_charge_runs`` for the correct 3-col one "
            "(tenant_id, idempotency_key, dry_run).  Dry-run by "
            "default."
        ),
    )
    grp = p.add_mutually_exclusive_group()
    grp.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        default=True,
        help="Preview only (default).  No writes.",
    )
    grp.add_argument(
        "--execute",
        dest="execute",
        action="store_true",
        default=False,
        help="Apply the index swap.  Stamps the marker on success.",
    )
    p.add_argument(
        "--force",
        dest="force",
        action="store_true",
        default=False,
        help="Bypass the marker check on execute.",
    )
    p.add_argument(
        "--verbose",
        dest="verbose",
        action="store_true",
        default=False,
        help="Emit the pre-run index listing to the log.",
    )
    return p


def _cli_main() -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")

    args = _build_argparser().parse_args()
    execute = bool(args.execute) and not args.dry_run
    if args.execute:
        execute = True

    summary = asyncio.run(run(
        execute=execute,
        force=args.force,
        verbose=args.verbose,
    ))
    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(_cli_main())
