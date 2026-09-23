"""Phase P38.1 · Feb-2026 — reverse backfill: `scheduled_start` from
`scheduled_date`.

Companion to P38.  Where P38 handled rows with ``scheduled_start``
but no ``scheduled_date``, P38.1 handles the INVERSE: rows with
``scheduled_date`` set (calendar day) but ``scheduled_start`` null.
Preview DB carries ~2,374 such rows — unscheduled-time jobs whose
schedule dashboards can't range-query them on ``scheduled_start``.

Rules
-----
* **Default time:** 08:00 in the tenant's local timezone.  Env
  ``P38_1_DEFAULT_START_TIME`` (``HH:MM``) overrides.
* **Timezone-safe:** same helper P38 uses (`services.tenant_helpers.
  get_tenant_timezone`).  Tenant with NO tz field → UTC 08:00 +
  WARN + counted under ``backfilled_utc_fallback``.
* **Idempotent:** hybrid — narrow query + ``migrations_applied``
  marker doc.  Second full-scope ``--execute`` short-circuits via
  the marker gate.
* **Preserves existing:** query excludes rows that already carry
  ``scheduled_start``.
* **Tenant-scoped opt-in:** ``--tenant=<id>`` bypasses the marker.
* **Batch 500** with progress log per batch.
* **Dry-run by default.**

Wired into ``_run_boot_sequence`` in ``backend/server.py``.  Ships
with ``STARTUP_EXECUTE_MODE = False`` so the first deploy after
this PR does NOT auto-mutate prod.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
from datetime import datetime, time as dtime, timezone
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple

from zoneinfo import ZoneInfo

from config import db, logger


MIGRATION_NAME = "p38_1_reverse_backfill_scheduled_start"
MARKER_COLLECTION = "migrations_applied"
BATCH_SIZE = 500
_DEFAULT_TIME_ENV = "P38_1_DEFAULT_START_TIME"
_DEFAULT_TIME_FALLBACK = "08:00"

# P38.1 startup wiring — mirrors P38's ``STARTUP_EXECUTE_MODE``.
# Ships as False.  Flip in a follow-up PR after operator approves
# the boot-log dry-run count.
STARTUP_EXECUTE_MODE = False


_HHMM_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


def _default_time_of_day() -> dtime:
    """Return the configured HH:MM as a ``datetime.time``.  Falls back
    to 08:00 on malformed env values (logs WARN)."""
    raw = (os.environ.get(_DEFAULT_TIME_ENV) or "").strip()
    if not raw:
        raw = _DEFAULT_TIME_FALLBACK
    m = _HHMM_RE.match(raw)
    if not m:
        logger.warning(
            "[p38.1] invalid %s=%r — falling back to %s",
            _DEFAULT_TIME_ENV, raw, _DEFAULT_TIME_FALLBACK,
        )
        return dtime(hour=8, minute=0)
    hh, mm = int(m.group(1)), int(m.group(2))
    return dtime(hour=hh, minute=mm)


# ═════════════════════════════════════════════════════════════════
# Tenant tz — mirrors P38's split so we can distinguish "has tz field"
# (use the helper) from "no tz field at all" (UTC + WARN + fallback
# bucket count).
# ═════════════════════════════════════════════════════════════════
def _tenant_has_tz(tenant: Optional[Mapping[str, Any]]) -> bool:
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
    from services.tenant_helpers import get_tenant_timezone
    return get_tenant_timezone(tenant)


def _derive_scheduled_start(
    scheduled_date: str,
    tenant: Optional[Mapping[str, Any]],
    default_time: dtime,
) -> Tuple[Optional[str], bool, Optional[str]]:
    """Return ``(iso_scheduled_start, used_utc_fallback, source)``.

    ``source`` is one of:
      * ``"iso_datetime_direct"`` — ``scheduled_date`` parsed as a
        full ISO datetime with a non-midnight time → copied verbatim
        (naive → assumed UTC).  ``used_utc_fallback`` is False on
        this path (the datetime carries its own tz).
      * ``"date_default_time"`` — ``scheduled_date`` parsed either as
        ``YYYY-MM-DD`` OR as a midnight-only ISO datetime → default
        time-of-day applied in the tenant's local tz.
        ``used_utc_fallback`` is True when the tenant carries NO tz
        field at all (UTC 08:00 fallback).
      * ``None`` (with ``(None, False, None)``) — unparseable.  Caller
        counts under ``skipped_unparseable``.

    The "midnight is ambiguous" heuristic: an ISO datetime whose time
    component is exactly ``00:00:00`` could either be an
    intentionally-scheduled midnight event OR a legacy writer that
    stored a date-only value as ``T00:00:00Z``.  We prefer the
    conservative interpretation (default-time treatment) so the
    scheduler dashboards render these at a sensible service-day
    start rather than at 12:00 AM.
    """
    if not isinstance(scheduled_date, str) or not scheduled_date.strip():
        return (None, False, None)
    raw = scheduled_date.strip()
    # ``fromisoformat`` handles the ``Z`` suffix only in 3.11+; be
    # defensive.
    normalised = raw.replace("Z", "+00:00") if raw.endswith("Z") else raw

    # Attempt 1 — full ISO datetime path.  ``fromisoformat`` also
    # accepts bare ``YYYY-MM-DD`` (returns midnight naive), which
    # falls into the midnight branch below.
    try:
        dt = datetime.fromisoformat(normalised)
    except (ValueError, TypeError):
        dt = None

    if dt is not None and dt.time() != dtime(0, 0):
        # Real time-of-day carried inline — direct copy path.
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (dt.isoformat(), False, "iso_datetime_direct")

    # Attempt 2 — date-only / midnight-only → default-time path.
    if dt is not None:
        the_date = dt.date()
    else:
        # ``fromisoformat`` failed entirely; try strict ``YYYY-MM-DD``
        # via strptime on the first 10 chars.
        try:
            the_date = datetime.strptime(raw[:10], "%Y-%m-%d").date()
        except (ValueError, TypeError):
            return (None, False, None)

    if _tenant_has_tz(tenant):
        tz = _tz_for_tenant(tenant)
        used_utc = False
    else:
        tz = timezone.utc
        used_utc = True
    try:
        local_dt = datetime(
            year=the_date.year, month=the_date.month, day=the_date.day,
            hour=default_time.hour, minute=default_time.minute,
            tzinfo=tz,
        )
    except ValueError:
        return (None, False, None)
    return (local_dt.isoformat(), used_utc, "date_default_time")


# ═════════════════════════════════════════════════════════════════
# Marker helpers (mirror P38)
# ═════════════════════════════════════════════════════════════════
async def _marker_present() -> bool:
    doc = await db[MARKER_COLLECTION].find_one({"name": MIGRATION_NAME})
    return bool(doc)


async def _stamp_marker(summary: Dict[str, Any]) -> None:
    now_iso = datetime.now(timezone.utc).isoformat()
    await db[MARKER_COLLECTION].update_one(
        {"name": MIGRATION_NAME},
        {"$set": {
            "name": MIGRATION_NAME,
            "applied_at": now_iso,
            "summary": {
                "scanned": summary.get("scanned"),
                "backfilled": summary.get("backfilled"),
                "backfilled_utc_fallback": summary.get(
                    "backfilled_utc_fallback",
                ),
                "default_time": summary.get("default_time"),
                "tenant_filter": summary.get("tenant_filter"),
                "limit": summary.get("limit"),
            },
        }},
        upsert=True,
    )


# ═════════════════════════════════════════════════════════════════
# Main entry
# ═════════════════════════════════════════════════════════════════
async def run(
    *,
    execute: bool = False,
    tenant_id: Optional[str] = None,
    limit: Optional[int] = None,
    force: bool = False,
    normalize_scheduled_date: bool = False,
) -> Dict[str, Any]:
    started = time.time()
    default_time = _default_time_of_day()
    default_time_str = default_time.strftime("%H:%M")

    if execute and not force and not tenant_id and await _marker_present():
        logger.info(
            "[p38.1] marker present in %s — skipping execute pass "
            "(pass --force or --tenant to override)",
            MARKER_COLLECTION,
        )
        return {
            "scanned": 0,
            "backfilled": 0,
            "backfilled_iso_direct": 0,
            "backfilled_default_time": 0,
            "backfilled_utc_fallback": 0,
            "skipped_unparseable": 0,
            "normalized_scheduled_date": 0,
            "duration_s": round(time.time() - started, 3),
            "dry_run": False,
            "skipped_by_marker": True,
            "executed_at": None,
            "tenant_filter": tenant_id,
            "limit": limit,
            "default_time": default_time_str,
            "normalize_flag": normalize_scheduled_date,
        }

    # Narrow query — ``scheduled_date`` set + ``scheduled_start`` null/missing.
    query: Dict[str, Any] = {
        "scheduled_date": {"$nin": [None, ""], "$exists": True},
        "$or": [
            {"scheduled_start": None},
            {"scheduled_start": {"$exists": False}},
        ],
    }
    if tenant_id:
        query["tenant_id"] = tenant_id

    projection = {
        "_id": 0,
        "id": 1,
        "tenant_id": 1,
        "scheduled_date": 1,
    }

    tenant_cache: Dict[str, Optional[Mapping[str, Any]]] = {}

    async def _get_tenant(tid: str) -> Optional[Mapping[str, Any]]:
        if tid in tenant_cache:
            return tenant_cache[tid]
        doc = await db.tenants.find_one({"id": tid})
        tenant_cache[tid] = doc
        return doc

    scanned = 0
    backfilled = 0
    backfilled_iso_direct = 0
    backfilled_default_time = 0
    backfilled_utc_fallback = 0
    skipped_unparseable = 0
    normalized_scheduled_date = 0

    cursor = db.jobs.find(query, projection)
    if limit is not None and limit > 0:
        cursor = cursor.limit(limit)

    batch: list[dict] = []

    async def _flush_batch(rows: list[dict]) -> None:
        nonlocal backfilled, backfilled_iso_direct, backfilled_default_time
        nonlocal backfilled_utc_fallback, skipped_unparseable
        nonlocal normalized_scheduled_date
        for row in rows:
            tid = row.get("tenant_id") or ""
            sd = row.get("scheduled_date") or ""
            tenant = await _get_tenant(tid) if tid else None
            iso_start, used_utc, source = _derive_scheduled_start(
                sd, tenant, default_time,
            )
            if iso_start is None:
                skipped_unparseable += 1
                logger.warning(
                    "[p38.1] skipping unparseable tenant=%s job=%s "
                    "scheduled_date=%r",
                    tid, row.get("id"), sd,
                )
                continue
            if used_utc:
                logger.warning(
                    "[p38.1] utc fallback for tenant=%s job=%s — "
                    "scheduled_start=%s derived from scheduled_date "
                    "@ %s UTC (tenant tz missing)",
                    tid, row.get("id"), iso_start, default_time_str,
                )

            # Compute the ``scheduled_date`` normalisation write (if
            # the flag is set AND the current stored value carries a
            # ``T`` — meaning it's NOT already a plain YYYY-MM-DD).
            normalized_target: Optional[str] = None
            if normalize_scheduled_date and "T" in sd:
                normalized_target = sd[:10]

            if execute:
                update_doc: Dict[str, Any] = {"scheduled_start": iso_start}
                if normalized_target and normalized_target != sd:
                    update_doc["scheduled_date"] = normalized_target
                await db.jobs.update_one(
                    {"id": row["id"], "tenant_id": tid},
                    {"$set": update_doc},
                )
            backfilled += 1
            if source == "iso_datetime_direct":
                backfilled_iso_direct += 1
            elif source == "date_default_time":
                backfilled_default_time += 1
            if used_utc:
                backfilled_utc_fallback += 1
            if normalized_target and normalized_target != sd:
                normalized_scheduled_date += 1

    async for doc in cursor:
        scanned += 1
        batch.append(doc)
        if len(batch) >= BATCH_SIZE:
            await _flush_batch(batch)
            logger.info(
                "[p38.1] batch progress — scanned=%s backfilled=%s "
                "iso_direct=%s default_time=%s utc_fallback=%s "
                "skipped=%s dry_run=%s",
                scanned, backfilled,
                backfilled_iso_direct, backfilled_default_time,
                backfilled_utc_fallback, skipped_unparseable,
                not execute,
            )
            batch = []
    if batch:
        await _flush_batch(batch)

    duration_s = round(time.time() - started, 3)
    summary: Dict[str, Any] = {
        "scanned": scanned,
        "backfilled": backfilled,
        "backfilled_iso_direct": backfilled_iso_direct,
        "backfilled_default_time": backfilled_default_time,
        "backfilled_utc_fallback": backfilled_utc_fallback,
        "skipped_unparseable": skipped_unparseable,
        "normalized_scheduled_date": normalized_scheduled_date,
        "duration_s": duration_s,
        "dry_run": not execute,
        "skipped_by_marker": False,
        "executed_at": (
            datetime.now(timezone.utc).isoformat() if execute else None
        ),
        "tenant_filter": tenant_id,
        "limit": limit,
        "default_time": default_time_str,
        "normalize_flag": normalize_scheduled_date,
    }

    if execute and not tenant_id:
        await _stamp_marker(summary)

    logger.info(
        "[p38.1] done — scanned=%s backfilled=%s iso_direct=%s "
        "default_time=%s utc_fallback=%s skipped=%s "
        "normalized=%s duration_s=%s dry_run=%s tenant=%s",
        scanned, backfilled, backfilled_iso_direct,
        backfilled_default_time, backfilled_utc_fallback,
        skipped_unparseable, normalized_scheduled_date,
        duration_s, not execute, tenant_id or "*",
    )
    return summary


# ═════════════════════════════════════════════════════════════════
# CLI
# ═════════════════════════════════════════════════════════════════
def _build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="p38_1_reverse_backfill_scheduled_start",
        description=(
            "Backfill jobs.scheduled_start from scheduled_date at a "
            "default time-of-day in the tenant's local timezone.  "
            "Handles both YYYY-MM-DD and full-ISO-datetime shapes.  "
            "Dry-run by default."
        ),
    )
    grp = p.add_mutually_exclusive_group()
    grp.add_argument("--dry-run", dest="dry_run", action="store_true", default=True)
    grp.add_argument("--execute", dest="execute", action="store_true", default=False)
    p.add_argument("--tenant", dest="tenant", default=None)
    p.add_argument("--limit", dest="limit", type=int, default=None)
    p.add_argument("--force", dest="force", action="store_true", default=False)
    p.add_argument(
        "--normalize-scheduled-date",
        dest="normalize_scheduled_date",
        action="store_true",
        default=False,
        help=(
            "Additionally clean up ``scheduled_date`` by truncating any "
            "full-ISO-datetime shape (\"YYYY-MM-DDT...\") to just its "
            "date portion (\"YYYY-MM-DD\").  Non-destructive default: OFF."
        ),
    )
    return p


def _cli_main() -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")

    args = _build_argparser().parse_args()
    execute = bool(args.execute)
    summary = asyncio.run(run(
        execute=execute,
        tenant_id=args.tenant,
        limit=args.limit,
        force=args.force,
        normalize_scheduled_date=bool(args.normalize_scheduled_date),
    ))
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(_cli_main())
