"""Phase K44 · Feb-2026 — Prod perf-index reconciliation (always-on).

Motivation
──────────
K15 (jobs schedule/status/crew) and K21 (customer/schedule web hot
paths) shipped as sentinel-gated boot migrations under
``services/migrations/k15_jobs_indexes.py`` and
``services/migrations/k21_perf_indexes.py``. F3.5 shipped the
customer-scoped compound indexes under
``services/migrations/perf_customers_indexes.py``.

In production those three sentinels never landed on the current
prod DB, and the F3.5 migration is behind ``_RUN_STARTUP_INDEXES``
(off-by-default in prod). Result: prod pages that fan out into
``jobs`` / ``quotes`` / ``customers`` / ``chat_messages`` /
``communications`` / ``payment_methods`` were seeing 30s+ latency
because every lookup COLLSCANs.

K44 is the belt-and-suspenders answer:

* Runs UNCONDITIONALLY at boot — NOT gated on
  ``RUN_STARTUP_INDEXES`` (unlike F3.5), NOT gated on a sentinel
  (unlike K15/K21). So even if the boot flag regresses or the
  sentinels get corrupted, indexes still land on the next redeploy.
* Purely additive — ``create_index`` is idempotent at the Mongo
  driver level: same ``name`` + same ``key`` spec is a no-op.
  Second-run cost is one ``list_indexes`` scan per collection.
* Never blocks boot — every per-collection block is wrapped in a
  narrow ``try/except`` and logged. Called via
  ``asyncio.create_task`` from ``server.py`` so the startup event
  returns immediately.

Sentinel
────────
Writes ``k44_perf_indexes_v1`` to ``db.migrations`` with a summary
of what was created vs. already-present, but does NOT read the
sentinel before running — the whole point is to guarantee coverage
regardless of prior state. Ops can grep the sentinel for the last
run's outcome.

Rollback
────────
Drop the K15/K21/perf_customers indexes by name; identical to K33
/ F3.5 rollback.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

from config import db


logger = logging.getLogger("k44_perf_indexes_migration")

_SENTINEL_ID = "k44_perf_indexes_v1"

# ── K44 index catalogue ────────────────────────────────────────────
# ``(collection, index_name, key_spec)``. Mirrors the union of the
# K15 + K21 + F3.5 catalogues so a fresh DB gets all three sets in
# one pass. Order is stable for deterministic logging.
_INDEXES: List[Tuple[str, str, List[Tuple[str, int]]]] = [
    # ── K15 (jobs schedule/status/crew) ────────────────────────────
    ("jobs", "k15_jobs_tech_schedule_status",
     [("tenant_id", 1), ("technician_id", 1),
      ("scheduled_date", 1), ("status", 1)]),
    ("jobs", "k15_jobs_crew_schedule",
     [("tenant_id", 1), ("crew_id", 1), ("scheduled_date", 1)]),

    # ── K21 (customer + schedule web hot paths) ────────────────────
    ("customers", "k21_customers_id",
     [("id", 1)]),
    ("customers", "k21_customers_tenant_id_lookup",
     [("tenant_id", 1), ("id", 1)]),
    ("jobs", "k21_jobs_id",
     [("id", 1)]),
    ("jobs", "k21_jobs_tenant_customer_sched",
     [("tenant_id", 1), ("customer_id", 1), ("scheduled_date", -1)]),
    ("quotes", "k21_quotes_id",
     [("id", 1)]),
    ("quotes", "k21_quotes_tenant_customer_doctype_created",
     [("tenant_id", 1), ("customer_id", 1),
      ("doc_type", 1), ("created_at", -1)]),
    # ── FIN-PARITY-B (Feb-2026) — server-side ``payment_status``
    # filter on ``list_quotes``. Compound key mirrors the exact
    # predicate emitted by ``routers.quotes.list_quotes`` when the
    # ``payment_status`` query param is set: ``tenant_id`` +
    # ``doc_type`` + ``payment_status`` + ``deleted_at``. Idempotent
    # via the k44 ``list_indexes`` cache check; background=True keeps
    # the initial build from blocking writes on a live cluster.
    ("quotes",
     "k44_quotes_tenant_doctype_paymentstatus_deleted",
     [("tenant_id", 1), ("doc_type", 1),
      ("payment_status", 1), ("deleted_at", 1)]),
    ("properties", "k21_properties_id",
     [("id", 1)]),
    ("chat_messages", "k21_chat_msgs_tenant_customer_time",
     [("tenant_id", 1), ("customer_id", 1), ("created_at", -1)]),
    ("communications", "k21_comms_tenant_customer_time",
     [("tenant_id", 1), ("customer_id", 1), ("created_at", -1)]),
    ("payment_methods", "k21_pm_id",
     [("id", 1)]),

    # ── F3.5 (perf_customers_v1 — customer-scoped compound tabs) ───
    ("jobs", "perf_customers_jobs_tenant_customer_created",
     [("tenant_id", 1), ("customer_id", 1), ("created_at", -1)]),
    ("invoices", "perf_customers_invoices_tenant_customer_created",
     [("tenant_id", 1), ("customer_id", 1), ("created_at", -1)]),
    ("payments", "perf_customers_payments_tenant_customer_created",
     [("tenant_id", 1), ("customer_id", 1), ("created_at", -1)]),
    ("customer_notes", "perf_customers_customer_notes_tenant_customer_created",
     [("tenant_id", 1), ("customer_id", 1), ("created_at", -1)]),
    ("properties", "perf_customers_properties_tenant_customer",
     [("tenant_id", 1), ("customer_id", 1)]),
]


async def _write_sentinel(summary: Dict[str, Any]) -> None:
    """Upsert a run summary into ``db.migrations`` for auditability.
    Not read on boot — this is diagnostic only."""
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
    """Force-apply every K15 + K21 + F3.5 index. Always runs.

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

    # Cache per-collection existing index names so we scan each
    # collection at most once even when it hosts multiple K44 rows.
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
                    "[k44] created index %s on %s", idx_name, coll_name,
                )
        except Exception as exc:  # noqa: BLE001
            target["status"] = "error"
            target["error"] = str(exc)
            summary["errors"].append(target)
            logger.warning(
                "[k44] index %s.%s failed: %s",
                coll_name, idx_name, exc,
            )
        summary["targets"].append(target)

    try:
        await _write_sentinel(summary)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[k44] sentinel write failed: %s", exc)

    logger.info(
        "[k44] created=%s already_present=%s errors=%s",
        summary["created"], summary["already_present"],
        len(summary["errors"]),
    )
    return {"status": "ok", "summary": summary}
