"""Phase P52 · Feb-2026 — Tenant ``default_locale`` backfill.

One-shot migration that seeds ``default_locale`` on every tenant
document that lacks the field (or carries an obviously stale value
outside the allowed ``{en, es, fr}`` set).  Landing surface is the
frontend i18n detection chain — with the field populated,
``auth.jsx`` can hydrate ``localStorage.tenant_default_locale`` on
``/auth/me`` boot and the i18n resolver's tenant rung starts firing.

Idempotent — safe to re-run.  Only updates rows where the field is
missing or holds an unsupported value; already-set tenants are
counted but not touched.  On success, stamps
``migrations_applied[name="p52_tenant_default_locale"]`` so
subsequent boot passes short-circuit (unless ``--force``).

Return shape (dry-run + execute + short-circuit all return the
same keys):

    {
        "tenants_seen": int,
        "already_set": int,
        "backfilled": int,
        "coerced_bad_value": int,  // present but not in allowed set
        "skipped_by_marker": bool,
        "duration_s": float,
        "dry_run": bool,
        "executed_at": iso | None,
    }

Usage:
    python -m migrations.p52_tenant_default_locale --dry-run   # inspect
    python -m migrations.p52_tenant_default_locale --execute   # apply
    python -m migrations.p52_tenant_default_locale --execute --force
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


MIGRATION_NAME = "p52_tenant_default_locale"
MARKER_COLLECTION = "migrations_applied"

ALLOWED_LOCALES = frozenset({"en", "es", "fr"})
DEFAULT_LOCALE = "en"

# P52 startup wiring — ``True`` because the backfill is safe to
# auto-apply (idempotent, only touches missing/invalid fields) and
# lets any pod that lands without the field self-heal on boot.
STARTUP_EXECUTE_MODE = True


# ═════════════════════════════════════════════════════════════════
# Marker helpers (mirror P46)
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
                "backfilled": summary.get("backfilled"),
                "already_set": summary.get("already_set"),
                "coerced_bad_value": summary.get("coerced_bad_value"),
                "tenants_seen": summary.get("tenants_seen"),
            },
        }},
        upsert=True,
    )


# ═════════════════════════════════════════════════════════════════
# Core apply
# ═════════════════════════════════════════════════════════════════
async def run(*, dry_run: bool = True, force: bool = False,
                db_client=None, log=None) -> Dict[str, Any]:
    """One sweep across ``tenants``.  Returns the summary above.

    ``dry_run=True`` inspects but never writes.  ``force=True``
    ignores the marker (both for the short-circuit AND the stamp
    at the end — a forced run stamps a fresh timestamp)."""
    target = db_client if db_client is not None else db
    lg = log or logger
    started = time.monotonic()
    now_iso = datetime.now(timezone.utc).isoformat()

    # Marker short-circuit (execute only — dry-run always inspects).
    if not dry_run and not force:
        if await _marker_present(db_client=target):
            lg.info("[%s] marker present — skipping (use --force to re-run)",
                     MIGRATION_NAME)
            return {
                "tenants_seen": 0,
                "already_set": 0,
                "backfilled": 0,
                "coerced_bad_value": 0,
                "skipped_by_marker": True,
                "duration_s": round(time.monotonic() - started, 3),
                "dry_run": False,
                "executed_at": None,
            }

    tenants_seen = 0
    already_set = 0
    backfilled = 0
    coerced_bad_value = 0

    async for t in target.tenants.find({}, {"_id": 0, "id": 1,
                                                "default_locale": 1}):
        tenants_seen += 1
        tid = t.get("id")
        current = t.get("default_locale")
        if current in ALLOWED_LOCALES:
            already_set += 1
            continue
        # Missing / null / stale value → needs backfill.  Distinguish
        # the two so the summary tells ops whether they inherited a
        # bad row or an unset one.
        if current is None:
            backfilled += 1
            action = "backfill-missing"
        else:
            coerced_bad_value += 1
            action = f"coerce-invalid({current!r})"
        if not dry_run and tid:
            await target.tenants.update_one(
                {"id": tid},
                {"$set": {"default_locale": DEFAULT_LOCALE}},
            )
        lg.info("[%s] tenant=%s %s → %s%s",
                 MIGRATION_NAME, tid, action, DEFAULT_LOCALE,
                 " (dry-run)" if dry_run else "")

    summary = {
        "tenants_seen": tenants_seen,
        "already_set": already_set,
        "backfilled": backfilled,
        "coerced_bad_value": coerced_bad_value,
        "skipped_by_marker": False,
        "duration_s": round(time.monotonic() - started, 3),
        "dry_run": dry_run,
        "executed_at": None if dry_run else now_iso,
    }

    if not dry_run:
        await _stamp_marker(summary, db_client=target)
        summary["executed_at"] = now_iso

    lg.info("[%s] summary: %s", MIGRATION_NAME,
             json.dumps({k: v for k, v in summary.items() if k != "duration_s"}))
    return summary


# ═════════════════════════════════════════════════════════════════
# Startup entry point (called from server.py boot chain)
# ═════════════════════════════════════════════════════════════════
async def run_at_startup(db_client=None) -> Optional[Dict[str, Any]]:
    """Idempotent auto-apply on backend boot.  Returns None when
    ``STARTUP_EXECUTE_MODE=False`` (kept as a flip switch)."""
    if not STARTUP_EXECUTE_MODE:
        return None
    try:
        return await run(dry_run=False, force=False, db_client=db_client)
    except Exception as exc:                                    # noqa: BLE001
        # Boot-hardening: never let a migration hiccup take down the
        # backend.  Log + return a synthetic summary so the caller
        # can decide what to do.
        (logger).exception(
            "[%s] startup apply failed: %s", MIGRATION_NAME, exc)
        return {
            "tenants_seen": 0, "already_set": 0, "backfilled": 0,
            "coerced_bad_value": 0, "skipped_by_marker": False,
            "duration_s": 0.0, "dry_run": False, "executed_at": None,
            "error": str(exc),
        }


# ═════════════════════════════════════════════════════════════════
# CLI
# ═════════════════════════════════════════════════════════════════
def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Backfill tenant.default_locale (Phase P52).",
    )
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true",
                        help="Inspect + report; no writes.")
    mode.add_argument("--execute", action="store_true",
                        help="Apply the backfill.  Idempotent.")
    p.add_argument("--force", action="store_true",
                     help="Ignore the migrations_applied marker.")
    return p.parse_args()


async def _cli_main() -> int:
    args = _parse_args()
    summary = await run(dry_run=args.dry_run, force=args.force)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_cli_main()))
