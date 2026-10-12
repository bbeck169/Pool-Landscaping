"""Feb-2026 · P0 · Recurring-jobs horizon backfill.

Idempotent, dry-run-first operator CLI that plugs holes in the
2-week rolling horizon of ``db.jobs`` for every active recurring
template. Companion to the cron cursor-fix in
``backend/routers/recurring_jobs.py::_generate_from_template``.

The cron now holds its cursor on insert errors (no more silent
skip-forward), but existing stuck templates — those whose cursor
already advanced past missing dates OR whose jobs got deleted
without the template cursor rewinding — need this one-shot sweep
to heal.

Usage
-----
    # Dry-run (default — safe to run ANYTIME on prod)
    python -m backend.scripts.backfill_recurring_jobs_window --days-ahead 14 --dry-run

    # Commit (writes to db.jobs — requires explicit flag)
    python -m backend.scripts.backfill_recurring_jobs_window --days-ahead 14 --commit

    # Scoped to a single tenant for staged rollout
    python -m backend.scripts.backfill_recurring_jobs_window --days-ahead 14 --commit --tenant <tenant_id>

Algorithm
---------
For every active recurring template (``is_active=True`` OR legacy
``active=True``, ``start_date <= today``) across every tenant (or
scoped to ``--tenant``):

1. Compute the expected occurrence dates via the same walker the
   cron uses (``_next_occurrences(tpl, today, today+N)``). This
   intentionally starts from ``today``, not
   ``last_generated_through + 1``, so holes past the cursor are
   found.
2. For each expected date, query ``db.jobs`` for
   ``{tenant_id, recurring_template_id, scheduled_date}``:
     - Row exists and is NOT soft-deleted      → skip (idempotent)
     - Row exists and is soft-deleted           → log, skip
       (operator decides whether to resurrect — never automatic)
     - Row missing                              → insert in commit mode,
                                                  log-only in dry-run
3. Does NOT touch ``last_generated_through``.  This is a hole-plug,
   not a cursor reset.  The cron continues to drive forward
   progress from its own cursor; this script only fills gaps.

Exit code is 0 on success, 2 when any template errored during
hole computation (template-level failures are isolated — one bad
row doesn't abort the whole sweep).

What this script DOES NOT do
----------------------------
* Resurrect soft-deleted jobs. If a job was deleted intentionally
  by an operator, re-inserting would surprise them.  The script
  logs these as ``SOFT_DELETED_PRESENT`` so operators can decide.
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
from collections import Counter
from datetime import date, timedelta
from typing import Any, Dict, List, Optional


logger = logging.getLogger("backfill_recurring_jobs_window")


# ─── Module path hygiene ────────────────────────────────────────────
# Script is invoked as ``python -m backend.scripts.backfill_...``
# which puts ``/app`` on sys.path.  Import the router helpers
# lazily inside ``main`` so test harnesses can import this module
# without a Motor connection.


async def _main(args) -> int:
    from config import db  # noqa: E402
    from routers.recurring_jobs import _next_occurrences  # noqa: E402
    from utils import new_id, now_iso  # noqa: E402
    from services.auto_visit_email import _format_property_address  # noqa: E402

    today = date.today()
    horizon = today + timedelta(days=args.days_ahead)

    _filter: Dict[str, Any] = {
        "$and": [
            {"$or": [
                {"is_active": True},
                {"active": True, "is_active": {"$exists": False}},
            ]},
            {"start_date": {"$ne": None, "$lte": today.isoformat()}},
        ],
    }
    if args.tenant:
        _filter["tenant_id"] = args.tenant

    counters: Counter = Counter()
    per_template: List[Dict[str, Any]] = []
    errored_templates: List[str] = []

    async for tpl in db.recurring_job_templates.find(_filter, {"_id": 0}):
        tpl_id = tpl.get("id")
        tenant_id = tpl.get("tenant_id")
        try:
            dates = _next_occurrences(tpl, today, horizon, max_count=200)
            missing: List[str] = []
            soft_del: List[str] = []
            existing: int = 0
            for d in dates:
                iso = d.isoformat()
                row = await db.jobs.find_one(
                    {"tenant_id": tenant_id,
                     "recurring_template_id": tpl_id,
                     "scheduled_date": iso},
                    {"_id": 0, "id": 1, "deleted_at": 1},
                )
                if row is None:
                    missing.append(iso)
                elif row.get("deleted_at"):
                    soft_del.append(iso)
                else:
                    existing += 1
            counters["templates_processed"] += 1
            counters["expected_dates"] += len(dates)
            counters["already_present"] += existing
            counters["missing"] += len(missing)
            counters["soft_deleted_present"] += len(soft_del)
            if missing:
                per_template.append({
                    "tenant_id": tenant_id,
                    "template_id": tpl_id,
                    "customer_name": tpl.get("customer_name"),
                    "frequency": tpl.get("frequency"),
                    "day_of_week": tpl.get("day_of_week"),
                    "missing_dates": missing,
                    "soft_deleted_dates": soft_del,
                })
                if args.commit:
                    # Resolve customer + property for the insert.
                    cust = await db.customers.find_one(
                        {"id": tpl.get("customer_id"), "tenant_id": tenant_id},
                        {"_id": 0, "name": 1, "address": 1,
                         "primary_property_id": 1},
                    ) or {}
                    resolved_property_id: Optional[str] = None
                    resolved_property_address: Optional[str] = None
                    candidate_pid = (tpl.get("property_id")
                                      or cust.get("primary_property_id"))
                    if candidate_pid:
                        prop = await db.properties.find_one(
                            {"id": candidate_pid, "tenant_id": tenant_id,
                             "deleted_at": {"$exists": False}},
                            {"_id": 0, "id": 1, "address": 1},
                        )
                        if prop:
                            resolved_property_id = prop["id"]
                            resolved_property_address = (
                                _format_property_address(prop) or None)
                    price_dollars = round(
                        (tpl.get("price_cents") or 0) / 100.0, 2)
                    for iso in missing:
                        job_doc: Dict[str, Any] = {
                            "id": new_id(),
                            "tenant_id": tenant_id,
                            "title": (tpl.get("service_type")
                                        or "Recurring Service"),
                            "service_type": tpl.get("service_type"),
                            "customer_id": tpl.get("customer_id"),
                            "customer_name": (cust.get("name")
                                               or tpl.get("customer_name")),
                            "address": (resolved_property_address
                                         or cust.get("address") or ""),
                            "technician_id": tpl.get("assigned_tech_id"),
                            "crew_id": tpl.get("crew_id"),
                            "crew_name": tpl.get("crew_name"),
                            "scheduled_date": iso,
                            "status": "scheduled",
                            "price": price_dollars,
                            "notes": tpl.get("notes") or "",
                            "recurring_template_id": tpl_id,
                            "created_at": now_iso(),
                            "backfilled_by": (
                                "backfill_recurring_jobs_window"),
                        }
                        if resolved_property_id:
                            job_doc["property_id"] = resolved_property_id
                        try:
                            await db.jobs.insert_one(job_doc)
                            counters["inserted"] += 1
                        except Exception as e:
                            msg = str(e).lower()
                            if "duplicate key" in msg or "e11000" in msg:
                                # Race with the live cron / another
                                # backfill process.  Safe to skip.
                                counters["race_dedup"] += 1
                            else:
                                logger.warning(
                                    "backfill_insert_failed tenant=%s "
                                    "template=%s date=%s error=%r",
                                    tenant_id, tpl_id, iso, e,
                                )
                                counters["insert_errors"] += 1
        except Exception as e:
            logger.warning("template_errored tenant=%s template=%s error=%r",
                            tenant_id, tpl_id, e)
            errored_templates.append(f"{tenant_id}/{tpl_id}")

    # ─── Report ────────────────────────────────────────────────
    mode = "COMMIT" if args.commit else "DRY-RUN"
    print(f"\n═══ Backfill summary ({mode}) ═══")
    print(f"today={today.isoformat()}  horizon={horizon.isoformat()}  "
          f"days_ahead={args.days_ahead}")
    if args.tenant:
        print(f"tenant_scope={args.tenant}")
    print(f"templates_processed    = {counters['templates_processed']}")
    print(f"expected_dates_total   = {counters['expected_dates']}")
    print(f"already_present        = {counters['already_present']}")
    print(f"missing (holes)        = {counters['missing']}")
    print(f"soft_deleted_present   = {counters['soft_deleted_present']} "
          f"(NOT resurrected)")
    if args.commit:
        print(f"inserted               = {counters['inserted']}")
        print(f"race_dedup             = {counters['race_dedup']}")
        print(f"insert_errors          = {counters['insert_errors']}")
    print(f"errored_templates      = {len(errored_templates)}")

    if per_template and args.verbose:
        print(f"\n--- per-template detail (first 20) ---")
        for row in per_template[:20]:
            print(f"  tenant={row['tenant_id']}  tpl={row['template_id']}  "
                  f"cust={row['customer_name']!r}  "
                  f"freq={row['frequency']}  dow={row['day_of_week']}  "
                  f"missing={row['missing_dates']}  "
                  f"soft_del={row['soft_deleted_dates']}")

    return 2 if errored_templates else 0


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
    return asyncio.run(_main(args))


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
