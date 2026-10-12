"""Feb-2026 · P0 · Recurring-jobs horizon backfill (CLI wrapper).

Thin ``argparse`` + stdout-render layer over
``backend.services.recurring_jobs_backfill.run_horizon_backfill``.

The CLI exists so operators can run the sweep from a pod shell when
needed. The service is also wired into the admin HTTP endpoint
``POST /api/admin/recurring-jobs/backfill-horizon`` for cases where
shell access isn't available.

Idempotent, dry-run-first operator CLI that plugs holes in the
2-week rolling horizon of ``db.jobs`` for every active recurring
template. Companion to the cron cursor-fix in
``backend/routers/recurring_jobs.py::_generate_from_template``.

Usage
-----
    # Dry-run (default — safe to run ANYTIME on prod)
    python -m backend.scripts.backfill_recurring_jobs_window --days-ahead 14 --dry-run

    # Commit (writes to db.jobs — requires explicit flag)
    python -m backend.scripts.backfill_recurring_jobs_window --days-ahead 14 --commit

    # Scoped to a single tenant for staged rollout
    python -m backend.scripts.backfill_recurring_jobs_window --days-ahead 14 --commit --tenant <tenant_id>

Exit codes
----------
* ``0`` — success, no template-level failures.
* ``2`` — one or more templates errored during hole computation.
  Template-level failures are isolated (one bad row doesn't abort
  the whole sweep); exit=2 surfaces the fact that the operator
  should inspect ``errored_templates`` in the summary.

What this script DOES NOT do
----------------------------
* Resurrect soft-deleted jobs. If a job was deleted intentionally
  by an operator, re-inserting would surprise them.  The script
  logs these as ``soft_deleted_present`` so operators can decide.
* Advance ``last_generated_through``.  Rewinding the cursor is a
  separate concern (see ``RECURRING-DELETE-RESETS-CURSOR``
  backlog item in ``/app/memory/PRD.md``).
* Create a template.  If no template exists for a cluster of
  orphan jobs, use
  ``POST /api/recurring-jobs/backfill-orphans`` instead.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from typing import List, Optional


logger = logging.getLogger("backfill_recurring_jobs_window")


async def _run(args) -> int:
    # Lazy import keeps module importable without ``config.db`` wired.
    from services.recurring_jobs_backfill import run_horizon_backfill

    summary = await run_horizon_backfill(
        days_ahead=args.days_ahead,
        commit=args.commit,
        tenant_id=args.tenant,
    )

    # ─── Report (stdout format preserved verbatim) ─────────────
    mode = "COMMIT" if args.commit else "DRY-RUN"
    print(f"\n═══ Backfill summary ({mode}) ═══")
    print(f"today={summary['today']}  horizon={summary['horizon']}  "
          f"days_ahead={summary['days_ahead']}")
    if args.tenant:
        print(f"tenant_scope={args.tenant}")
    print(f"templates_processed    = {summary['templates_processed']}")
    print(f"expected_dates_total   = {summary['expected_dates_total']}")
    print(f"already_present        = {summary['already_present']}")
    print(f"missing (holes)        = {summary['missing']}")
    print(f"soft_deleted_present   = {summary['soft_deleted_present']} "
          f"(NOT resurrected)")
    if args.commit:
        print(f"inserted               = {summary['inserted']}")
        print(f"race_dedup             = {summary['race_dedup']}")
        print(f"insert_errors          = {summary['insert_errors']}")
    print(f"errored_templates      = {len(summary['errored_templates'])}")

    per_template = summary.get("per_template_detail") or []
    if per_template and args.verbose:
        print(f"\n--- per-template detail (first 20) ---")
        for row in per_template[:20]:
            print(f"  tenant={row['tenant_id']}  tpl={row['template_id']}  "
                  f"cust={row['customer_name']!r}  "
                  f"freq={row['frequency']}  dow={row['day_of_week']}  "
                  f"missing={row['missing_dates']}  "
                  f"soft_del={row['soft_deleted_dates']}")

    return 2 if summary["errored_templates"] else 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Idempotent hole-plug for recurring job materialization.",
    )
    parser.add_argument("--days-ahead", type=int, default=14,
                         help="Horizon size in days from today (default 14).")
    parser.add_argument("--tenant", type=str, default=None,
                         help="Scope to a single tenant_id (default: all).")
    g = parser.add_mutually_exclusive_group()
    g.add_argument("--dry-run", action="store_true", default=True,
                    help=(
                        "No writes (default). Reports what WOULD be "
                        "inserted."))
    g.add_argument("--commit", action="store_true", default=False,
                    help=(
                        "Writes to db.jobs. Requires explicit flag; "
                        "dry-run is the safe default."))
    parser.add_argument("--verbose", action="store_true", default=False,
                         help="Print per-template detail (first 20).")
    args = parser.parse_args(argv)

    logging.basicConfig(
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        level=logging.INFO,
    )
    return asyncio.run(_run(args))


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
