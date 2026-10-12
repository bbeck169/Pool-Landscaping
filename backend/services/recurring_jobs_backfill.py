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

# ---------------------------------------------------------------------------
# RECURRING-JOBS SAFETY NET (context-loss resilience breadcrumb)
# Companion routers (fire sites):
#   - backend/routers/jobs.py              (PUT /jobs/{jid})
#   - backend/routers/service_reports.py   (submit path)
#   - backend/routers/mobile_sync.py       (offline replay)
# Companion audit: /app/docs/recurring-jobs-audit.md
# Nightly cron fix: 54af96872 (cursor advances only on provable progress)
# Admin backfill endpoint chain: 22164d562, ea54df36b, 9593a8450, 8e691ea4f
# Infinite recurrence (null end_date): 43be86e2d
# Site 2 (service_reports) idempotency: option (a) — helper internal only.
# ---------------------------------------------------------------------------

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



# ────────────────────────────────────────────────────────────────────
# On-complete safety net
# ────────────────────────────────────────────────────────────────────
async def materialize_next_from_completed_job(
    *,
    job: Dict[str, Any],
    tenant_id: str,
    actor_user_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Safety-net: on job completion, insert the next expected
    occurrence for the parent recurring template if the nightly
    cron hasn't already materialized it.

    Preconditions (early returns, each returns ``None``):

      1. ``job.get("recurring_template_id")`` is None → no-op
         (non-recurring job).
      2. Parent template not found in ``db.recurring_job_templates``
         → no-op.
      3. Template is paused (``is_active=False`` OR legacy
         ``active=False``) → no-op.
      4. Walker returns zero occurrences for ``(scheduled_date+1 →
         today+14)`` horizon → no-op (bounded template already at or
         past ``end_date``; or horizon is somehow collapsed).
      5. Idempotency check — a non-soft-deleted job already exists for
         ``(tenant_id, recurring_template_id, scheduled_date)`` →
         no-op (cron already did it, or a prior safety-net fired).

    On commit path: insert a single job doc shaped the same way the
    nightly cron materializer / horizon backfill script do (title,
    service_type, customer_name, address, resolved property,
    price_dollars, status='scheduled', recurring_template_id,
    backfilled_by marker, created_at).

    Logger output (structured, matches operator triage format)::

        recurring_job.on_complete_safety_net.triggered
            tenant=<id> parent_job=<id> template=<id>
            next_date=<iso> inserted_job=<id>

    Caller contract — safety-net failures MUST NOT block the parent
    "mark complete" HTTP call. Caller wraps in try/except and emits
    ``recurring_job.on_complete_safety_net.failed`` WARN (not
    re-raised).

    Returns the inserted job dict on success, ``None`` if any
    precondition short-circuited.
    """
    # Lazy imports — same style as ``run_horizon_backfill`` so the
    # module stays importable in test harnesses that stub ``config.db``
    # before the first call.
    from config import db
    from routers.recurring_jobs import _next_occurrences
    from utils import new_id, now_iso
    from services.auto_visit_email import _format_property_address

    # ── Precondition 1 — not a recurring job ─────────────────────
    template_id = job.get("recurring_template_id")
    if not template_id:
        return None
    parent_job_id = job.get("id")

    # ── Precondition 2 — template not found ──────────────────────
    tpl = await db.recurring_job_templates.find_one(
        {"id": template_id, "tenant_id": tenant_id},
        {"_id": 0},
    )
    if not tpl:
        return None

    # ── Precondition 3 — template paused ─────────────────────────
    is_active_flag = tpl.get("is_active")
    active_flag = tpl.get("active")
    if is_active_flag is False:
        return None
    if is_active_flag is None and active_flag is False:
        # Legacy row — honour the legacy ``active`` field only when
        # ``is_active`` is explicitly missing.
        return None

    # Anchor the walker ONE day past this job's scheduled_date so we
    # never re-emit the parent's slot (the parent IS this completed
    # job).  Walker inclusive-on-anchor semantics (see line 311-313 of
    # ``routers/recurring_jobs.py``) make `+1 day` the correct offset.
    try:
        parent_date = date.fromisoformat(str(job.get("scheduled_date")))
    except Exception:
        # Malformed scheduled_date — bail out safely.
        return None
    anchor = parent_date + timedelta(days=1)
    horizon = date.today() + timedelta(days=14)
    if anchor > horizon:
        return None

    # ── Precondition 4 — walker empty ────────────────────────────
    occs = _next_occurrences(tpl, anchor, horizon, max_count=1)
    if not occs:
        return None
    next_date = occs[0]
    next_iso = next_date.isoformat()

    # ── Precondition 5 — idempotency ─────────────────────────────
    existing = await db.jobs.find_one(
        {"tenant_id": tenant_id,
         "recurring_template_id": template_id,
         "scheduled_date": next_iso,
         "deleted_at": {"$exists": False}},
        {"_id": 0, "id": 1},
    )
    if existing:
        return None

    # ── Insert the next job ──────────────────────────────────────
    cust = await db.customers.find_one(
        {"id": tpl.get("customer_id"), "tenant_id": tenant_id},
        {"_id": 0, "name": 1, "address": 1, "primary_property_id": 1},
    ) or {}
    resolved_property_id: Optional[str] = None
    resolved_property_address: Optional[str] = None
    candidate_pid = tpl.get("property_id") or cust.get("primary_property_id")
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
    price_dollars = round((tpl.get("price_cents") or 0) / 100.0, 2)

    job_doc: Dict[str, Any] = {
        "id": new_id(),
        "tenant_id": tenant_id,
        "title": tpl.get("service_type") or "Recurring Service",
        "service_type": tpl.get("service_type"),
        "customer_id": tpl.get("customer_id"),
        "customer_name": cust.get("name") or tpl.get("customer_name"),
        "address": resolved_property_address or cust.get("address") or "",
        "technician_id": tpl.get("assigned_tech_id"),
        "crew_id": tpl.get("crew_id"),
        "crew_name": tpl.get("crew_name"),
        "scheduled_date": next_iso,
        "status": "scheduled",
        "price": price_dollars,
        "notes": tpl.get("notes") or "",
        "recurring_template_id": template_id,
        "created_at": now_iso(),
        "backfilled_by": "on_complete_safety_net",
    }
    if resolved_property_id:
        job_doc["property_id"] = resolved_property_id

    try:
        await db.jobs.insert_one(job_doc)
    except Exception as exc:  # noqa: BLE001
        msg = str(exc).lower()
        if "duplicate key" in msg or "e11000" in msg:
            # Race with the live cron or a concurrent safety-net
            # call — the dedupe guard did its job somewhere else.
            return None
        # Unexpected insert failure — surface so the caller can log
        # the structured ``.failed`` line.
        raise

    logger.info(
        "recurring_job.on_complete_safety_net.triggered "
        "tenant=%s parent_job=%s template=%s next_date=%s "
        "inserted_job=%s actor=%s",
        tenant_id, parent_job_id, template_id, next_iso,
        job_doc["id"], actor_user_id,
    )
    return job_doc
