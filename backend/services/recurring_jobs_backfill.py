"""Feb-2026 · P0 · Recurring-jobs horizon backfill — shared service.

Extracted from ``backend/scripts/backfill_recurring_jobs_window.py``
so both the CLI (operator shell path) and the admin HTTP endpoint
(``POST /api/admin/recurring-jobs/backfill-horizon``) can call the
same idempotent hole-plug logic.

Algorithm (unchanged from the CLI script):

For every active recurring template (``is_active=True`` OR legacy
``active=True``, ``start_date <= today``) across every tenant (or
scoped to ``tenant_id``):

1. Compute expected occurrence dates via the walker the cron uses
   (``_next_occurrences(tpl, today, horizon)``). Starts from
   ``today``, not ``last_generated_through + 1``, so holes past the
   cursor are found.
2. For each expected date, classify ``db.jobs`` presence:
     - Row exists and is NOT soft-deleted      → ``already_present``
     - Row exists and is soft-deleted           → ``soft_deleted_present``
       (log-only; operator decides whether to resurrect)
     - Row missing                              → insert in commit mode,
                                                  log-only in dry-run
3. Never touches ``last_generated_through``.  This is a hole-plug,
   not a cursor reset.  The cron continues to drive forward
   progress from its own cursor.

Non-fatal failure contract
--------------------------
Template-level exceptions (e.g. the ``OverflowError`` seen on preview
seed data) are isolated — the template is recorded in
``errored_templates`` with its exception string, and the sweep
continues. Per-date insert failures are classified as either
``race_dedup`` (duplicate key — safe, concurrent cron) or
``insert_errors`` (recorded in ``warnings`` with context).

Return shape
------------
::

    {
      "mode": "dry_run" | "commit",
      "today": "YYYY-MM-DD",
      "horizon": "YYYY-MM-DD",
      "days_ahead": int,
      "tenant_scope": Optional[str],
      "templates_processed": int,
      "expected_dates_total": int,
      "already_present": int,
      "missing": int,
      "soft_deleted_present": int,
      "inserted": int,
      "race_dedup": int,
      "insert_errors": int,
      "errored_templates": [
          {"tenant_id": str, "template_id": str, "error": str},
          ...
      ],
      "warnings": [
          {"tenant_id": str, "template_id": str, "date": str,
           "error": str},
          ...
      ],
      "per_template_detail": [
          {"tenant_id": str, "template_id": str,
           "customer_name": Optional[str],
           "frequency": Optional[str],
           "day_of_week": Optional[int],
           "missing_dates": [str, ...],
           "soft_deleted_dates": [str, ...]},
          ...
      ],
    }
"""
from __future__ import annotations

import logging
from collections import Counter
from datetime import date, timedelta
from typing import Any, Dict, List, Optional


logger = logging.getLogger("recurring_jobs_backfill")


async def run_horizon_backfill(
    *,
    days_ahead: int = 14,
    commit: bool = False,
    tenant_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Idempotent hole-plug sweep across the rolling horizon.

    Parameters
    ----------
    days_ahead:
        Horizon size in days from ``date.today()``.
    commit:
        When ``True`` writes missing rows into ``db.jobs``. When
        ``False`` (default), classifies but writes nothing.
    tenant_id:
        Scope to a single tenant_id. ``None`` means every tenant.

    Returns
    -------
    Summary dict matching the shape documented in the module
    docstring. Never raises for template-level or per-date failures —
    those are captured in ``errored_templates`` and ``warnings``.
    """
    # Lazy imports keep the module importable in test harnesses
    # that stub ``config.db`` before the first call.
    from config import db  # noqa: E402
    from routers.recurring_jobs import _next_occurrences  # noqa: E402
    from utils import new_id, now_iso  # noqa: E402
    from services.auto_visit_email import _format_property_address  # noqa: E402

    today = date.today()
    horizon = today + timedelta(days=days_ahead)

    _filter: Dict[str, Any] = {
        "$and": [
            {"$or": [
                {"is_active": True},
                {"active": True, "is_active": {"$exists": False}},
            ]},
            {"start_date": {"$ne": None, "$lte": today.isoformat()}},
        ],
    }
    if tenant_id:
        _filter["tenant_id"] = tenant_id

    counters: Counter = Counter()
    per_template: List[Dict[str, Any]] = []
    errored_templates: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []

    async for tpl in db.recurring_job_templates.find(_filter, {"_id": 0}):
        tpl_id = tpl.get("id")
        tpl_tenant_id = tpl.get("tenant_id")
        try:
            dates = _next_occurrences(tpl, today, horizon, max_count=200)
            missing: List[str] = []
            soft_del: List[str] = []
            existing: int = 0
            for d in dates:
                iso = d.isoformat()
                row = await db.jobs.find_one(
                    {"tenant_id": tpl_tenant_id,
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
            counters["expected_dates_total"] += len(dates)
            counters["already_present"] += existing
            counters["missing"] += len(missing)
            counters["soft_deleted_present"] += len(soft_del)
            if missing:
                per_template.append({
                    "tenant_id": tpl_tenant_id,
                    "template_id": tpl_id,
                    "customer_name": tpl.get("customer_name"),
                    "frequency": tpl.get("frequency"),
                    "day_of_week": tpl.get("day_of_week"),
                    "missing_dates": missing,
                    "soft_deleted_dates": soft_del,
                })
                if commit:
                    # Resolve customer + property for the insert.
                    cust = await db.customers.find_one(
                        {"id": tpl.get("customer_id"),
                         "tenant_id": tpl_tenant_id},
                        {"_id": 0, "name": 1, "address": 1,
                         "primary_property_id": 1},
                    ) or {}
                    resolved_property_id: Optional[str] = None
                    resolved_property_address: Optional[str] = None
                    candidate_pid = (tpl.get("property_id")
                                      or cust.get("primary_property_id"))
                    if candidate_pid:
                        prop = await db.properties.find_one(
                            {"id": candidate_pid,
                             "tenant_id": tpl_tenant_id,
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
                            "tenant_id": tpl_tenant_id,
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
                                    tpl_tenant_id, tpl_id, iso, e,
                                )
                                counters["insert_errors"] += 1
                                warnings.append({
                                    "tenant_id": tpl_tenant_id,
                                    "template_id": tpl_id,
                                    "date": iso,
                                    "error": repr(e),
                                })
        except Exception as e:
            logger.warning(
                "template_errored tenant=%s template=%s error=%r",
                tpl_tenant_id, tpl_id, e,
            )
            errored_templates.append({
                "tenant_id": tpl_tenant_id,
                "template_id": tpl_id,
                "error": repr(e),
            })

    return {
        "mode": "commit" if commit else "dry_run",
        "today": today.isoformat(),
        "horizon": horizon.isoformat(),
        "days_ahead": days_ahead,
        "tenant_scope": tenant_id,
        "templates_processed": int(counters["templates_processed"]),
        "expected_dates_total": int(counters["expected_dates_total"]),
        "already_present": int(counters["already_present"]),
        "missing": int(counters["missing"]),
        "soft_deleted_present": int(counters["soft_deleted_present"]),
        "inserted": int(counters["inserted"]),
        "race_dedup": int(counters["race_dedup"]),
        "insert_errors": int(counters["insert_errors"]),
        "errored_templates": errored_templates,
        "warnings": warnings,
        "per_template_detail": per_template,
    }
