"""Feb-2026 · TD-quiet-hours-cron-tick-recovery · Phase 1.

One-shot recovery for ``outbound_deferred`` rows stuck in
``status="pending"`` whose ``scheduled_for`` has fallen behind the
current UTC time by more than ``--grace-minutes`` (default 5).
Covers the shipped failure modes:

  * The quiet-hours release cron (``services/quiet_hours_release.
    py::run_release_tick``) missed a tick (APScheduler lag, server
    restart during a window, cron thread wedged).
  * A fresh ``defer_send`` call succeeded but no cron tick has
    fired since the row's ``scheduled_for`` passed.

Scope
=====

**Pending-only.**  Rows in ``status="releasing"`` are OUT OF SCOPE
for this script.  Those rows were already claimed by a worker via
``find_one_and_update`` and are either (a) genuinely mid-dispatch
by a live worker or (b) orphaned by a worker that crashed between
claim and status-flip.  Distinguishing (a) from (b) requires a
stale-``claimed_at`` heuristic that risks double-dispatch when a
worker is alive-but-slow (long adapter timeout, Resend 429
backoff).  Deferred to the follow-up P3 candidate
``TD-quiet-hours-releasing-orphan-recovery``.

The orphaned-``releasing`` row count IS surfaced in dry-run output
as a bookmark so operators can see the gap and dispatch the
follow-up when the stale-claim threshold is agreed.

**Race safety.**  The claim uses the identical atomic ``find_one_
and_update`` pattern the live cron (``claim_pending_batch``) and
the Phase-2 release-now flush (``_claim_tenant_pending``) use —
``{status: "pending"} → {status: "releasing"}`` is a single-
document update, so a concurrent cron tick cannot double-claim.
If the live cron and this recovery script race on the same row,
exactly one succeeds; the loser sees ``None`` and moves on.

**Dispatch.**  Reuses ``services.quiet_hours_release._dispatch_row``
verbatim.  The post-release row state (``status``, ``released_at``,
``provider_id``, ``release_result``) is byte-identical to what the
cron tick would have produced if it had fired on time.

Tenant isolation
================

Every read + write is scoped by ``tenant_id``.  A ``--all-tenants``
run iterates per tenant with full isolation.  Within a run, if any
single tenant errors mid-apply, the per-tenant audit row records
the partial counts, that tenant halts loudly, and the remaining
tenants continue cleanly (per the brief's fail-closed-per-tenant
spec; distinct from the merge-dupes script's re-raise semantics).

Idempotency
===========

A second ``--apply`` run after the first = all-zero (the first run
either released the row to ``sent``/``failed`` or marked it
``failed`` — either way its ``status`` is terminal and it falls
out of the stuck-predicate match).

Audit
=====

One ``migration_runs`` doc per tenant per invocation (mirrors
``merge_income_categories_duplicates_v1``).

CLI
===

    # dry-run on one tenant (default; prints what WOULD release)
    python backend/migrations/recover_outbound_deferred_stuck_pending_v1.py \\
      --tenant-id <tid>

    # apply on one tenant
    python backend/migrations/recover_outbound_deferred_stuck_pending_v1.py \\
      --tenant-id <tid> --apply

    # dry-run across every active tenant
    python backend/migrations/recover_outbound_deferred_stuck_pending_v1.py \\
      --all-tenants

    # apply across every active tenant with a 15-minute grace
    python backend/migrations/recover_outbound_deferred_stuck_pending_v1.py \\
      --all-tenants --apply --grace-minutes 15
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import dotenv_values  # noqa: E402
from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

from utils import now_iso  # noqa: E402


logger = logging.getLogger("recover_outbound_deferred_stuck_pending_v1")


DEFAULT_GRACE_MINUTES = 5
# Hard cap per tenant per invocation so a wedged dispatch can't
# monopolise a run.  Matches the live cron's BATCH_LIMIT (200).
BATCH_LIMIT = 200

# Terminal statuses that mean the row has "left the system" —
# treated as released from the recovery script's point of view.
_RELEASED_OK_STATUSES = {
    "sent", "mocked", "deferred", "suppressed_not_demo",
    "skipped_opted_out",
}


def _now_utc() -> datetime:
    return datetime.now(tz=timezone.utc)


def _cutoff_iso(now: datetime, grace_minutes: int) -> str:
    return (now - timedelta(minutes=grace_minutes)).isoformat()


async def _list_tenants(db) -> List[str]:
    rows = await db.tenants.find(
        {"$or": [{"active": {"$ne": False}},
                   {"active": {"$exists": False}}]},
        {"_id": 0, "id": 1},
    ).to_list(10_000)
    return [r["id"] for r in rows if r.get("id")]


async def _count_stuck_pending(
    db, tenant_id: str, cutoff_iso: str,
) -> int:
    return int(await db.outbound_deferred.count_documents({
        "tenant_id": tenant_id,
        "status": "pending",
        "scheduled_for": {"$lte": cutoff_iso},
    }))


async def _count_orphaned_releasing(
    db, tenant_id: str, cutoff_iso: str,
) -> int:
    """Bookmark count for the follow-up ticket
    ``TD-quiet-hours-releasing-orphan-recovery``.  Rows that MAY
    be orphaned (``status="releasing"`` + stale ``scheduled_for``)
    but are NOT touched by this script."""
    return int(await db.outbound_deferred.count_documents({
        "tenant_id": tenant_id,
        "status": "releasing",
        "scheduled_for": {"$lte": cutoff_iso},
    }))


async def _sample_row_ids(
    db, tenant_id: str, cutoff_iso: str, limit: int = 5,
) -> List[str]:
    cur = db.outbound_deferred.find(
        {"tenant_id": tenant_id, "status": "pending",
         "scheduled_for": {"$lte": cutoff_iso}},
        {"_id": 0, "id": 1, "scheduled_for": 1, "channel": 1},
    ).sort("scheduled_for", 1).limit(limit)
    return [r async for r in cur]


async def _claim_stuck_pending(
    db, tenant_id: str, cutoff_iso: str, *,
    limit: int = BATCH_LIMIT,
) -> List[Dict[str, Any]]:
    """Atomically claim up to ``limit`` stuck pending rows for
    ``tenant_id``.  Uses the same ``find_one_and_update`` primitive
    the live cron and the Phase-2 release-now flush use, so a
    concurrent live worker cannot double-claim the same row.
    """
    claimed: List[Dict[str, Any]] = []
    for _ in range(limit):
        row = await db.outbound_deferred.find_one_and_update(
            {"tenant_id": tenant_id, "status": "pending",
             "scheduled_for": {"$lte": cutoff_iso}},
            {"$set": {"status": "releasing", "claimed_at": now_iso()}},
            return_document=True,
        )
        if not row:
            break
        row.pop("_id", None)
        claimed.append(row)
    return claimed


async def _recover_tenant(
    db, tenant_id: str, *,
    cutoff_iso: str, dry_run: bool,
    dispatch: Optional[Callable] = None,
) -> Dict[str, Any]:
    """Recover stuck pending rows for one tenant.  Returns per-row
    results + aggregates.  Fails CLOSED-PER-TENANT: on exception
    inside the per-row dispatch loop, the tenant's audit records
    partial counts and the exception is swallowed so other tenants
    continue.  The outer orchestrator surfaces per-tenant errors
    in its return dict."""
    stuck_count = await _count_stuck_pending(db, tenant_id, cutoff_iso)
    orphaned_releasing = await _count_orphaned_releasing(
        db, tenant_id, cutoff_iso,
    )
    sample = await _sample_row_ids(db, tenant_id, cutoff_iso)

    out: Dict[str, Any] = {
        "stuck_pending_count":        stuck_count,
        "orphaned_releasing_count":   orphaned_releasing,
        "sample_rows":                sample,
        "released_count":             0,
        "failed_count":               0,
        "per_row":                    [],
        "error":                      None,
    }
    if dry_run or stuck_count == 0:
        return out

    # Resolve the dispatch callable lazily so tests can inject a
    # pure mock without importing the comms adapters.
    if dispatch is None:
        from services.quiet_hours_release import _dispatch_row
        dispatch = _dispatch_row

    try:
        claimed = await _claim_stuck_pending(db, tenant_id, cutoff_iso)
    except Exception as exc:
        logger.exception(
            "[recover-stuck] tenant=%s claim phase failed", tenant_id,
        )
        out["error"] = f"claim: {type(exc).__name__}: {exc}"
        return out

    for row in claimed:
        row_id = row.get("id")
        try:
            result = await dispatch(row)
            status_raw = (result or {}).get("status")
            if status_raw in _RELEASED_OK_STATUSES:
                db_status = "sent"
                out["released_count"] += 1
            else:
                db_status = "failed"
                out["failed_count"] += 1
            await db.outbound_deferred.update_one(
                {"id": row_id},
                {"$set": {
                    "status": db_status,
                    "released_at": now_iso(),
                    "provider_id": (result or {}).get("provider_id"),
                    "release_result": {
                        k: v for k, v in (result or {}).items()
                        if k in ("status", "error", "provider_id")
                    },
                }},
            )
            out["per_row"].append({
                "row_id":  row_id,
                "channel": row.get("channel"),
                "scheduled_for": row.get("scheduled_for"),
                "action":  db_status,
                "result":  (result or {}).get("status"),
            })
        except Exception as exc:
            logger.exception(
                "[recover-stuck] tenant=%s row=%s dispatch failed",
                tenant_id, row_id,
            )
            out["failed_count"] += 1
            out["per_row"].append({
                "row_id":  row_id,
                "channel": row.get("channel"),
                "scheduled_for": row.get("scheduled_for"),
                "action":  "failed",
                "result":  f"exception: {type(exc).__name__}: {exc}",
            })
            # Mark the row ``failed`` so a re-run doesn't repeat
            # the same crash on the same row.  Fail-closed-per-row.
            try:
                await db.outbound_deferred.update_one(
                    {"id": row_id},
                    {"$set": {
                        "status": "failed",
                        "released_at": now_iso(),
                        "release_result": {
                            "status": "failed",
                            "error":
                                f"recover-stuck: {type(exc).__name__}: {exc}",
                        },
                    }},
                )
            except Exception:  # noqa: BLE001
                # Secondary failure writing the ``failed`` state is
                # non-fatal — the orchestrator surfaces the error.
                pass
            # Carry the error forward on the tenant so the audit
            # row records partial counts.  Continue the per-row
            # loop so other claimed rows aren't orphaned in
            # ``releasing``.
            if out["error"] is None:
                out["error"] = (
                    f"row {row_id}: {type(exc).__name__}: {exc}"
                )
    return out


async def recover_stuck_pending(
    db, *, tenant_id: Optional[str] = None,
    all_tenants: bool = False,
    grace_minutes: int = DEFAULT_GRACE_MINUTES,
    dry_run: bool = True,
    dispatch: Optional[Callable] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Top-level entry point.  Pass ``tenant_id`` OR ``all_tenants``
    (mutex, one required).  ``grace_minutes`` controls the "stuck"
    threshold.  ``dispatch`` is a seam for pytest — production
    callers leave it ``None`` and get the shipped
    ``_dispatch_row``.  ``now`` is a seam for pytest — production
    callers leave it ``None``."""
    if tenant_id and all_tenants:
        raise ValueError(
            "pass either --tenant-id OR --all-tenants, not both",
        )
    if not tenant_id and not all_tenants:
        raise ValueError(
            "pass --tenant-id <id> OR --all-tenants (explicit)",
        )
    if grace_minutes < 0:
        raise ValueError("--grace-minutes must be >= 0")

    now = now or _now_utc()
    cutoff_iso = _cutoff_iso(now, grace_minutes)
    audit_at = now.isoformat()
    tids = [tenant_id] if tenant_id else await _list_tenants(db)

    per_tenant: Dict[str, Dict[str, Any]] = {}
    totals = {
        "tenants_scanned":           0,
        "stuck_pending_count":       0,
        "orphaned_releasing_count":  0,
        "released_count":            0,
        "failed_count":              0,
        "tenants_with_errors":       0,
    }

    for tid in tids:
        if not tid:
            continue
        totals["tenants_scanned"] += 1
        summary = await _recover_tenant(
            db, tid,
            cutoff_iso=cutoff_iso, dry_run=dry_run,
            dispatch=dispatch,
        )
        per_tenant[tid] = summary
        totals["stuck_pending_count"] += summary["stuck_pending_count"]
        totals["orphaned_releasing_count"] += \
            summary["orphaned_releasing_count"]
        totals["released_count"] += summary["released_count"]
        totals["failed_count"] += summary["failed_count"]
        if summary["error"]:
            totals["tenants_with_errors"] += 1
        if not dry_run:
            await db.migration_runs.insert_one({
                "id":        str(uuid.uuid4()),
                "name":      "recover_outbound_deferred_stuck_pending_v1",
                "tenant_id": tid,
                "status":    "error" if summary["error"] else "ok",
                "grace_minutes": grace_minutes,
                "cutoff_iso":    cutoff_iso,
                "summary": {k: v for k, v in summary.items()
                            if k != "per_row"},
                "at":        audit_at,
            })

    return {
        "dry_run":        dry_run,
        "all_tenants":    bool(all_tenants and not tenant_id),
        "grace_minutes":  grace_minutes,
        "cutoff_iso":     cutoff_iso,
        "totals":         totals,
        "per_tenant":     per_tenant,
    }


# ─────────────────────────── CLI ──────────────────────────────────
def _print_summary(result: Dict[str, Any]) -> None:
    totals = result["totals"]
    print(f"grace_minutes              = {result['grace_minutes']}")
    print(f"cutoff_iso                 = {result['cutoff_iso']}")
    print(f"tenants_scanned            = {totals['tenants_scanned']}")
    print(f"stuck_pending_count        = {totals['stuck_pending_count']}")
    print(f"orphaned_releasing_count   = {totals['orphaned_releasing_count']}"
          "  (bookmark · see TD-quiet-hours-releasing-orphan-recovery)")
    print(f"released_count             = {totals['released_count']}")
    print(f"failed_count               = {totals['failed_count']}")
    print(f"tenants_with_errors        = {totals['tenants_with_errors']}")
    print()
    if not result["per_tenant"]:
        return
    print("per-tenant:")
    for tid, row in result["per_tenant"].items():
        err = row.get("error")
        print(
            f"  tenant={tid}  stuck_pending={row['stuck_pending_count']}  "
            f"orphan_rel={row['orphaned_releasing_count']}  "
            f"released={row['released_count']}  "
            f"failed={row['failed_count']}"
            + (f"  [ERROR] {err}" if err else "")
        )
        for s in row.get("sample_rows") or []:
            print(
                f"    sample  id={s.get('id')}  channel={s.get('channel')}  "
                f"scheduled_for={s.get('scheduled_for')}"
            )


async def _cli(argv: Optional[List[str]] = None) -> None:
    p = argparse.ArgumentParser(description=(
        "Recover ``outbound_deferred`` rows stuck in "
        "``status=pending`` whose ``scheduled_for`` is older than "
        "``--grace-minutes`` (default 5)."
    ))
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--tenant-id", default=None,
                         help="Scope to one tenant.")
    group.add_argument("--all-tenants", action="store_true",
                         help="Scope to every active tenant.")
    p.add_argument("--apply", action="store_true",
                    help="Actually mutate.  Default is dry-run.")
    p.add_argument("--grace-minutes", type=int,
                    default=DEFAULT_GRACE_MINUTES,
                    help=("Stuck threshold in minutes "
                            f"(default {DEFAULT_GRACE_MINUTES})."))
    args = p.parse_args(argv)

    env = dotenv_values(
        str(Path(__file__).resolve().parents[1] / ".env"),
    )
    mongo_url = env.get("MONGO_URL") or ""
    db_name = env.get("DB_NAME") or ""
    if not mongo_url or not db_name:
        print("MONGO_URL / DB_NAME missing from backend/.env",
              file=sys.stderr)
        sys.exit(2)
    db = AsyncIOMotorClient(mongo_url)[db_name]

    scope = (f"tenant={args.tenant_id}"
             if args.tenant_id else "ALL TENANTS")
    print(f"== recover-stuck-pending · dry-run · scope={scope} ==")
    dry = await recover_stuck_pending(
        db, tenant_id=args.tenant_id,
        all_tenants=bool(args.all_tenants and not args.tenant_id),
        grace_minutes=args.grace_minutes,
        dry_run=True,
    )
    _print_summary(dry)
    if not args.apply:
        print("\nDry-run only.  Re-run with --apply to mutate.")
        return

    print(f"\n== recover-stuck-pending · APPLY · scope={scope} ==")
    real = await recover_stuck_pending(
        db, tenant_id=args.tenant_id,
        all_tenants=bool(args.all_tenants and not args.tenant_id),
        grace_minutes=args.grace_minutes,
        dry_run=False,
    )
    _print_summary(real)

    print("\n-- idempotency re-check (dry-run) --")
    recheck = await recover_stuck_pending(
        db, tenant_id=args.tenant_id,
        all_tenants=bool(args.all_tenants and not args.tenant_id),
        grace_minutes=args.grace_minutes,
        dry_run=True,
    )
    _print_summary(recheck)
    rt = recheck["totals"]
    if rt["stuck_pending_count"] > 0:
        print("WARNING: idempotency re-check still shows stuck rows.")


if __name__ == "__main__":
    asyncio.run(_cli())
