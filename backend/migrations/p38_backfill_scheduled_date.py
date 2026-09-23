"""Phase P38 · Feb-2026 — `scheduled_date` backfill from `scheduled_start`.

Some pre-P13 jobs — and jobs written by legacy routes that only
populate ``scheduled_start`` (the ISO datetime) — have ``scheduled_date``
null / missing.  Because the P37 CustomerDetail history sorts DESC on
``scheduled_date``, those rows sort as blank-string and cluster at the
tail of the list where the user can't see them.  The P34 CustomersList
tester surfaced one such row on offset=900 for the Jennifer Carson
customer.

This migration walks the ``jobs`` collection and, for every row that
has ``scheduled_start`` populated but ``scheduled_date`` null/missing,
derives ``scheduled_date`` as the ``YYYY-MM-DD`` string in the
**tenant's local timezone** and writes it back.

Rules
-----
* **Idempotent by query narrowness** — the filter matches only rows
  needing work; a second run finds zero rows.  A stamped marker in
  ``db.migrations_applied`` is also written on successful execute so
  boot-time re-scans of ~8k jobs are skipped once the migration has
  succeeded (perf guardrail, per P38 brief).
* **Timezone-safe** — uses ``services.tenant_helpers.get_tenant_timezone``
  when the tenant carries a resolvable tz field.  When the tenant doc
  has NO tz field at all (top-level ``timezone`` empty AND legacy
  ``settings.timezone`` / ``settings.tz`` empty), falls back to UTC,
  emits a WARN per row, and counts the row under
  ``backfilled_utc_fallback`` in the summary.
* **Preserves existing** — rows with a non-null ``scheduled_date``
  are untouched.  The query itself excludes them.
* **Tenant filter opt-in** — ``--tenant=<id>`` limits the scan to one
  tenant; combined with the marker bypass this is the "explicit
  re-invoke" path a follow-up cleanup can use.
* **Batch 500** — cursor pulls 500 rows per iteration, logs progress
  every batch.
* **Dry-run by default** — the CLI defaults to ``--dry-run``; only
  ``--execute`` mutates the DB.

Startup wiring
--------------
Wired into ``_run_boot_sequence`` in ``backend/server.py`` via a
``_p38_factory`` that reads :data:`STARTUP_EXECUTE_MODE`.  Ships as
``False`` (dry-run) so the first deploy after this PR does NOT auto-
mutate prod — the operator gets the dry-run count line in the boot
log, approves, and flips the constant in a follow-up.

Return shape
------------
``{
    "scanned": N,
    "backfilled": N,
    "backfilled_utc_fallback": N,
    "duration_s": float,
    "dry_run": bool,
    "skipped_by_marker": bool,
    "executed_at": iso | None,
    "tenant_filter": <id> | None,
    "limit": <int> | None,
}``
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Mapping, Optional
from zoneinfo import ZoneInfo

from config import db, logger


MIGRATION_NAME = "p38_backfill_scheduled_date"
MARKER_COLLECTION = "migrations_applied"
BATCH_SIZE = 500

# P38 startup wiring: ``False`` means the boot factory runs in dry-run
# mode (scans, logs the count, mutates NOTHING).  Flip to ``True`` in
# a follow-up PR AFTER the operator approves the dry-run count.  The
# marker in ``migrations_applied`` prevents re-execution once True.
STARTUP_EXECUTE_MODE = False


# ═════════════════════════════════════════════════════════════════
# TZ helpers — mirrored from ``services.tenant_helpers`` so this
# migration can distinguish "tenant HAS a tz field" (use helper,
# ultimate fallback is Phoenix) from "tenant has NO tz field at all"
# (bypass helper, use UTC + WARN + count under fallback bucket).
# ═════════════════════════════════════════════════════════════════
def _tenant_has_tz(tenant: Optional[Mapping[str, Any]]) -> bool:
    """True when the tenant doc carries ANY resolvable tz field."""
    if not tenant:
        return False
    top = (tenant.get("timezone") or "").strip()
    if top:
        return True
    settings = tenant.get("settings") or {}
    if isinstance(settings, Mapping):
        legacy = (settings.get("timezone") or settings.get("tz") or "").strip()
        if legacy:
            return True
    return False


def _tz_for_tenant(tenant: Optional[Mapping[str, Any]]) -> ZoneInfo:
    """Resolve the tenant's ``ZoneInfo`` via the canonical helper.

    Only called when :func:`_tenant_has_tz` returned True — this
    delegates to ``services.tenant_helpers.get_tenant_timezone``
    which handles legacy nested fields + malformed IANA strings.
    """
    from services.tenant_helpers import get_tenant_timezone
    return get_tenant_timezone(tenant)


def _derive_scheduled_date(
    scheduled_start: str,
    tenant: Optional[Mapping[str, Any]],
) -> tuple[Optional[str], bool]:
    """Return ``(YYYY-MM-DD, used_utc_fallback)`` or ``(None, False)``
    if the ``scheduled_start`` string can't be parsed.

    The datetime is parsed as an ISO string; naive datetimes are
    assumed UTC (matches the codebase convention where every writer
    calls ``.isoformat()`` on a tz-aware ``datetime.now(timezone.utc)``).
    The returned date is the calendar day in either the tenant's
    local tz or UTC (fallback).
    """
    try:
        # Python 3.11+ handles both ``2026-02-15T18:30:00+00:00`` and
        # ``2026-02-15T18:30:00Z`` via ``fromisoformat`` (the ``Z``
        # suffix landed in 3.11).  Handle both defensively.
        raw = scheduled_start.replace("Z", "+00:00") if scheduled_start.endswith("Z") else scheduled_start
        dt = datetime.fromisoformat(raw)
    except (ValueError, AttributeError, TypeError):
        return (None, False)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    used_utc_fallback = False
    if _tenant_has_tz(tenant):
        local = dt.astimezone(_tz_for_tenant(tenant))
    else:
        used_utc_fallback = True
        local = dt.astimezone(timezone.utc)
    return (local.date().isoformat(), used_utc_fallback)


# ═════════════════════════════════════════════════════════════════
# Marker helpers
# ═════════════════════════════════════════════════════════════════
async def _marker_present() -> bool:
    """True when the P38 marker doc exists in ``migrations_applied``."""
    doc = await db[MARKER_COLLECTION].find_one({"name": MIGRATION_NAME})
    return bool(doc)


async def _stamp_marker(summary: Dict[str, Any]) -> None:
    """Idempotent upsert of the P38 marker doc post-execute."""
    now_iso = datetime.now(timezone.utc).isoformat()
    await db[MARKER_COLLECTION].update_one(
        {"name": MIGRATION_NAME},
        {"$set": {
            "name": MIGRATION_NAME,
            "applied_at": now_iso,
            "summary": {
                # Trim the summary — no need to persist the raw
                # ``duration_s`` (it just clutters the marker doc)
                # but keep the counters for audit.
                "scanned": summary.get("scanned"),
                "backfilled": summary.get("backfilled"),
                "backfilled_utc_fallback": summary.get(
                    "backfilled_utc_fallback",
                ),
                "tenant_filter": summary.get("tenant_filter"),
                "limit": summary.get("limit"),
            },
        }},
        upsert=True,
    )


# ═════════════════════════════════════════════════════════════════
# Main entrypoint
# ═════════════════════════════════════════════════════════════════
async def run(
    *,
    execute: bool = False,
    tenant_id: Optional[str] = None,
    limit: Optional[int] = None,
    force: bool = False,
) -> Dict[str, Any]:
    """Scan ``jobs`` and backfill ``scheduled_date`` from
    ``scheduled_start`` for rows missing it.

    Parameters
    ----------
    execute:
        ``False`` (default) → dry-run: count only, no mutations.
        ``True`` → apply the update.  If the P38 marker is already
        stamped (and ``force`` is False + ``tenant_id`` is None),
        the run short-circuits with ``skipped_by_marker: True``.
    tenant_id:
        Optional tenant filter.  Bypasses the marker check (a
        tenant-scoped run is an explicit re-invoke).
    limit:
        Optional cap on rows processed (across all batches).
    force:
        Bypass the marker check even for full-scope execute.
    """
    started = time.time()

    # ── Marker gate (execute-only, full-scope) ─────────────
    if execute and not force and not tenant_id and await _marker_present():
        logger.info(
            "[p38] marker present in %s — skipping execute pass "
            "(pass --force or --tenant to override)",
            MARKER_COLLECTION,
        )
        return {
            "scanned": 0,
            "backfilled": 0,
            "backfilled_utc_fallback": 0,
            "duration_s": round(time.time() - started, 3),
            "dry_run": False,
            "skipped_by_marker": True,
            "executed_at": None,
            "tenant_filter": tenant_id,
            "limit": limit,
        }

    # ── Query — narrow: scheduled_start set + scheduled_date null/missing.
    #    Tenant-scoped when ``--tenant`` is provided so the migration
    #    can be re-invoked against a single tenant safely.
    query: Dict[str, Any] = {
        "scheduled_start": {"$ne": None, "$exists": True},
        "$or": [
            {"scheduled_date": None},
            {"scheduled_date": {"$exists": False}},
        ],
    }
    if tenant_id:
        query["tenant_id"] = tenant_id

    projection = {
        "_id": 0,
        "id": 1,
        "tenant_id": 1,
        "scheduled_start": 1,
    }

    # Tenant tz cache — 1 lookup per tenant instead of per row.
    tenant_cache: Dict[str, Optional[Mapping[str, Any]]] = {}

    async def _get_tenant(tid: str) -> Optional[Mapping[str, Any]]:
        if tid in tenant_cache:
            return tenant_cache[tid]
        doc = await db.tenants.find_one({"id": tid})
        tenant_cache[tid] = doc
        return doc

    scanned = 0
    backfilled = 0
    backfilled_utc_fallback = 0

    # Motor cursor — pull in batches of BATCH_SIZE.  ``no_cursor_timeout``
    # would help for very long runs but Motor exposes it only via
    # ``find(..., no_cursor_timeout=True)``; on ~8k rows the default
    # 10-minute timeout is more than enough.
    cursor = db.jobs.find(query, projection)
    if limit is not None and limit > 0:
        cursor = cursor.limit(limit)

    batch: list[dict] = []

    async def _flush_batch(rows: list[dict]) -> None:
        """Apply one batch's derivations.  Mutates ``backfilled`` +
        ``backfilled_utc_fallback`` counters via nonlocal."""
        nonlocal backfilled, backfilled_utc_fallback
        for row in rows:
            tid = row.get("tenant_id") or ""
            ss = row.get("scheduled_start") or ""
            tenant = await _get_tenant(tid) if tid else None
            date_str, used_utc = _derive_scheduled_date(ss, tenant)
            if date_str is None:
                # Unparseable ``scheduled_start`` — skip silently; the
                # row will show up in the next run's scanned count
                # but we can't derive a date.  Not an error path we
                # want to noise the boot log with.
                continue
            if used_utc:
                logger.warning(
                    "[p38] utc fallback for tenant=%s job=%s — "
                    "scheduled_date=%s derived from scheduled_start "
                    "in UTC (tenant tz missing)",
                    tid,
                    row.get("id"),
                    date_str,
                )
            if execute:
                await db.jobs.update_one(
                    {"id": row["id"], "tenant_id": tid},
                    {"$set": {"scheduled_date": date_str}},
                )
            backfilled += 1
            if used_utc:
                backfilled_utc_fallback += 1

    async for doc in cursor:
        scanned += 1
        batch.append(doc)
        if len(batch) >= BATCH_SIZE:
            await _flush_batch(batch)
            logger.info(
                "[p38] batch progress — scanned=%s backfilled=%s "
                "utc_fallback=%s dry_run=%s",
                scanned, backfilled, backfilled_utc_fallback, not execute,
            )
            batch = []
    if batch:
        await _flush_batch(batch)

    duration_s = round(time.time() - started, 3)
    summary: Dict[str, Any] = {
        "scanned": scanned,
        "backfilled": backfilled,
        "backfilled_utc_fallback": backfilled_utc_fallback,
        "duration_s": duration_s,
        "dry_run": not execute,
        "skipped_by_marker": False,
        "executed_at": (
            datetime.now(timezone.utc).isoformat() if execute else None
        ),
        "tenant_filter": tenant_id,
        "limit": limit,
    }

    # Stamp the marker post-execute for full-scope runs.  Skipping
    # tenant-scoped runs so a per-tenant cleanup doesn't lock out
    # future full-scope re-invocations.
    if execute and not tenant_id:
        await _stamp_marker(summary)

    logger.info(
        "[p38] done — scanned=%s backfilled=%s utc_fallback=%s "
        "duration_s=%s dry_run=%s tenant=%s",
        scanned, backfilled, backfilled_utc_fallback,
        duration_s, not execute, tenant_id or "*",
    )
    return summary


# ═════════════════════════════════════════════════════════════════
# CLI
# ═════════════════════════════════════════════════════════════════
def _build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="p38_backfill_scheduled_date",
        description=(
            "Backfill jobs.scheduled_date from scheduled_start in the "
            "tenant's local timezone.  Dry-run by default."
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
        help="Apply the update.  Stamps the marker on success.",
    )
    p.add_argument(
        "--tenant",
        dest="tenant",
        default=None,
        help="Optional tenant filter.  Bypasses the marker check.",
    )
    p.add_argument(
        "--limit",
        dest="limit",
        type=int,
        default=None,
        help="Cap total rows processed.",
    )
    p.add_argument(
        "--force",
        dest="force",
        action="store_true",
        default=False,
        help="Bypass the marker check on full-scope execute.",
    )
    return p


def _cli_main() -> int:
    # Allow ``python backend/migrations/p38_backfill_scheduled_date.py``
    # AND ``python -m migrations.p38_backfill_scheduled_date``.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")

    args = _build_argparser().parse_args()
    execute = bool(args.execute) and not args.dry_run
    # argparse mutual-exclusion covers ``--dry-run --execute`` together,
    # but the ``default=True`` on ``--dry-run`` means the flag is True
    # even when ``--execute`` was passed alone.  Prefer explicit
    # ``--execute`` when both would evaluate True.
    if args.execute:
        execute = True

    summary = asyncio.run(run(
        execute=execute,
        tenant_id=args.tenant,
        limit=args.limit,
        force=args.force,
    ))
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(_cli_main())
