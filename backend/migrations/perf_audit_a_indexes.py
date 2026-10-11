"""Phase PERF-AUDIT-A · Feb-2026 — Gap-fill perf indexes on
balance/credit/payment hot paths + customers.tags.

Companion to the existing ``k44_perf_indexes`` lineage.  Covers the
specific index gaps surfaced by the Feb-2026 customers+schedule
performance audit::

  * ``credits`` collection had **zero** non-``_id`` indexes — every
    read full-scanned.  Adds ``(tenant_id, customer_id)`` compound.
  * ``invoices`` only had the ``(tenant_id, customer_id,
    created_at)`` compound from ``perf_customers_invoices_*``.
    Unpaid-invoice balance aggregation needed
    ``(tenant_id, customer_id, status)``; past-due calc needed
    ``(tenant_id, customer_id, due_date)``.
  * ``quotes`` had the broader
    ``(tenant_id, customer_id, doc_type, created_at)`` compound but
    not the shorter ``(tenant_id, customer_id, status)`` variant
    the balance/pending-estimates aggregations hit.
  * ``payments`` was missing ``(tenant_id, invoice_id)`` for the
    invoice→payments reverse join used by the balance recompute.
  * ``customers`` was missing the ``(tenant_id, tags)`` multikey
    index — tag-filter dropdowns + the customer-list ``?tags=`` arm
    were tenant-scanning.
  * ``customers`` was missing the ``(tenant_id, deleted_at,
    is_active, created_at DESC)`` compound for the Active-tab sort
    order the customers list uses by default.

Pattern-match with ``k44_perf_indexes``:
  * Runs UNCONDITIONALLY at boot — NOT gated on a sentinel.
  * Purely additive — ``create_index`` is idempotent at the Mongo
    driver level.
  * Narrow ``try/except`` per collection so a single failure
    doesn't block the rest.
  * Called via ``asyncio.create_task`` from ``server.py`` so the
    startup event returns immediately.
  * Writes a diagnostic summary row to ``db.migrations`` after each
    run; not read on boot.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

from config import db


logger = logging.getLogger("perf_audit_a_indexes_migration")

_SENTINEL_ID = "perf_audit_a_indexes_v1"


_INDEXES: List[Tuple[str, str, List[Tuple[str, int]]]] = [
    # ── credits (collection had zero non-_id indexes) ──────────────
    ("credits",
     "perf_audit_a_credits_tenant_customer",
     [("tenant_id", 1), ("customer_id", 1)]),

    # ── invoices — balance + past-due hot paths ────────────────────
    # ``balance_due`` aggregation filters by (tenant, customer,
    # status in {'unpaid','partial','partially_paid'}).  The
    # existing ``perf_customers_invoices_tenant_customer_created``
    # covers the (tenant, customer) prefix but the planner still
    # scans every row to filter on status.
    ("invoices",
     "perf_audit_a_invoices_tenant_customer_status",
     [("tenant_id", 1), ("customer_id", 1), ("status", 1)]),
    # ``past_due`` + ``overdue_count`` filter by due_date<today on
    # the same customer scope.  Compound covers the equality +
    # range predicate without a second index intersection.
    ("invoices",
     "perf_audit_a_invoices_tenant_customer_duedate",
     [("tenant_id", 1), ("customer_id", 1), ("due_date", 1)]),

    # ── quotes — pending-estimates filter ──────────────────────────
    # The pending-estimates KPI tile fires
    # ``count_documents({tenant, customer, doc_type in ..., status
    # in draft/sent/pending/viewed})``.  Existing
    # ``k21_quotes_tenant_customer_doctype_created`` prefix helps
    # but the status filter is an in-memory evaluation.  The
    # shorter ``(tenant, customer, status)`` form here lets the
    # planner satisfy pending-estimates without inspecting
    # created_at.
    ("quotes",
     "perf_audit_a_quotes_tenant_customer_status",
     [("tenant_id", 1), ("customer_id", 1), ("status", 1)]),

    # ── payments — invoice reverse-join ────────────────────────────
    # Balance recompute walks ``payments.find({tenant_id,
    # invoice_id})`` to sum applied payments per invoice.  Compound
    # avoids a tenant-wide scan for every invoice-id lookup.
    ("payments",
     "perf_audit_a_payments_tenant_invoice",
     [("tenant_id", 1), ("invoice_id", 1)]),

    # ── customers — tag filter + Active-tab sort ──────────────────
    # ``?tags=`` arm on the customers list.  Multikey over the
    # ``tags`` array; the planner picks per-element matching.
    ("customers",
     "perf_audit_a_customers_tenant_tags",
     [("tenant_id", 1), ("tags", 1)]),
    # Active-tab default sort = ``created_at`` DESC with
    # ``deleted_at`` + ``is_active`` filters.  The existing
    # ``customers_tenant_deleted_is_active_id_bg`` matches the
    # filter prefix but the planner can't satisfy an
    # ``is_active + created_at DESC`` sort from it (``_id`` is the
    # final key, not ``created_at``).  New index widens that
    # compound with ``created_at: -1`` as the sort key.
    ("customers",
     "perf_audit_a_customers_tenant_deleted_active_created_desc",
     [("tenant_id", 1), ("deleted_at", 1),
      ("is_active", 1), ("created_at", -1)]),
]


async def _write_sentinel(summary: Dict[str, Any]) -> None:
    await db.migrations.update_one(
        {"id": _SENTINEL_ID},
        {"$set": {
            "id": _SENTINEL_ID,
            "last_run_at": datetime.now(timezone.utc).isoformat(),
            "summary": summary,
        }},
        upsert=True,
    )


async def run() -> Dict[str, Any]:
    """Force-apply every gap-fill index.  Always runs.

    Returns::

        {"status": "ok",
         "summary": {
             "created": <int>,
             "already_present": <int>,
             "errors": [...],
             "targets": [...],
         }}
    """
    summary: Dict[str, Any] = {
        "created": 0,
        "already_present": 0,
        "errors": [],
        "targets": [],
    }

    cache: Dict[str, set] = {}

    for coll_name, idx_name, keys in _INDEXES:
        target: Dict[str, Any] = {
            "collection": coll_name, "index": idx_name,
        }
        try:
            if coll_name not in cache:
                names = set()
                async for idx in db[coll_name].list_indexes():
                    names.add(idx.get("name") or "")
                cache[coll_name] = names
            if idx_name in cache[coll_name]:
                target["status"] = "already_present"
                summary["already_present"] += 1
            else:
                await db[coll_name].create_index(
                    keys, name=idx_name, background=True,
                )
                cache[coll_name].add(idx_name)
                target["status"] = "created"
                summary["created"] += 1
                logger.info(
                    "[perf_audit_a] created index %s on %s",
                    idx_name, coll_name,
                )
        except Exception as exc:                                      # noqa: BLE001
            target["status"] = "error"
            target["error"] = str(exc)
            summary["errors"].append(target)
            logger.warning(
                "[perf_audit_a] index %s.%s failed: %s",
                coll_name, idx_name, exc,
            )
        summary["targets"].append(target)

    try:
        await _write_sentinel(summary)
    except Exception as exc:                                          # noqa: BLE001
        logger.warning("[perf_audit_a] sentinel write failed: %s", exc)

    logger.info(
        "[perf_audit_a] created=%s already_present=%s errors=%s",
        summary["created"], summary["already_present"],
        len(summary["errors"]),
    )
    return {"status": "ok", "summary": summary}
