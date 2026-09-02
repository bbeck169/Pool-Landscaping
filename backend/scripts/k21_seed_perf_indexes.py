"""Phase K21 · Feb-2026 — one-shot Mongo-index seed for the
customer-list / customer-detail / schedule hot paths on the web.

Root cause (RCA condensed):
  * ``db.customers`` has no index on the app-level ``id`` field, so
    every ``find_one({"id": cid})`` COLLSCANs the collection. 32+
    call-sites hit it directly; add
    ``perf_customers_jobs_tenant_customer_created`` for cross-tenant
    joins and mobile / web schedule fan-outs multiply the cost.
    Same story on ``jobs`` (60 call-sites) and ``quotes`` (34).
  * Customer-scoped reads on ``quotes`` (per-customer invoices tab)
    and ``chat_messages`` / ``communications`` (timeline) had ONLY
    a ``{tenant_id}`` index — every open of the customer detail
    swept the collection.

This script creates the missing indexes and skips the ones already
covered by an existing compound. Follows the K15 pattern: idempotent,
``--apply`` gated, standalone, NOT wired into boot.

Post-apply, expected latency change (unmeasurable on preview — the
seed data is thin — but for prod-scale tenants):

  * ``find_one({"id": cid})`` on customers / jobs / quotes: 10-100x
    (COLLSCAN → IXSCAN with a single-key equality).
  * Customer-detail page (fan-outs across jobs + quotes + chats):
    3-10x under normal load; the biggest wins compound because the
    page fires 5+ per-customer reads in parallel and each one drops
    from O(N) to O(log N + result-set).
  * Schedule pages already had ``{tenant_id, scheduled_date}`` +
    K15 tech/crew indexes; K21 only helps when the schedule fans
    out to per-job customer / property joins.
"""
from __future__ import annotations

import argparse
import os
import sys
from typing import Dict, List, Tuple

from dotenv import load_dotenv


# ── K21 index catalogue ────────────────────────────────────────────
# ``(collection, index_name, keys)`` — creation order is stable so
# the dry-run + apply output is deterministic.  ``keys`` is a list
# of ``(field, direction)`` tuples per pymongo convention.
_K21_INDEXES: List[Tuple[str, str, List[Tuple[str, int]]]] = [
    # customers — the biggest win.  ``find_one({"id": cid})`` is
    # invoked 32+ times across routers/customers.py + others.
    ("customers", "k21_customers_id",
     [("id", 1)]),
    ("customers", "k21_customers_tenant_id_lookup",
     [("tenant_id", 1), ("id", 1)]),
    # jobs — same PK problem plus per-customer sorted reads on
    # scheduled_date (customer-detail Jobs tab).  The existing
    # perf_customers_jobs_tenant_customer_created index covers the
    # {tenant_id, customer_id} prefix but sorts on created_at, so
    # scheduled_date DESC still triggers an in-memory sort.
    ("jobs", "k21_jobs_id",
     [("id", 1)]),
    ("jobs", "k21_jobs_tenant_customer_sched",
     [("tenant_id", 1), ("customer_id", 1), ("scheduled_date", -1)]),
    # quotes / invoices — no {tenant_id, customer_id, ...} index
    # existed before K21 despite the customer-detail Invoices tab
    # firing exactly that shape on every open.
    ("quotes", "k21_quotes_id",
     [("id", 1)]),
    ("quotes", "k21_quotes_tenant_customer_doctype_created",
     [("tenant_id", 1), ("customer_id", 1),
      ("doc_type", 1), ("created_at", -1)]),
    # properties — no ``id`` index. The {tenant_id, customer_id}
    # compound already lives as ``perf_customers_properties_tenant_customer``
    # so we skip the redundant K21 twin (see ``_SKIPPED`` below).
    ("properties", "k21_properties_id",
     [("id", 1)]),
    # chat_messages / communications — timeline reads filter by
    # {tenant_id, customer_id} sorted desc by created_at. Only a
    # tenant-wide index existed.
    ("chat_messages", "k21_chat_msgs_tenant_customer_time",
     [("tenant_id", 1), ("customer_id", 1), ("created_at", -1)]),
    ("communications", "k21_comms_tenant_customer_time",
     [("tenant_id", 1), ("customer_id", 1), ("created_at", -1)]),
    # payment_methods — the ``id`` (uuid) PK is hit on every card
    # detach + card-on-file resolve. {tenant_id, customer_id, ...}
    # is already covered by ``payment_methods_tenant_customer_default_idx``.
    ("payment_methods", "k21_pm_id",
     [("id", 1)]),
]

# Existing compound indexes that already cover a K21-proposed shape.
# Reported in the dry-run / apply output for auditability so nobody
# re-adds them later "just to be safe".
_SKIPPED: List[Tuple[str, str, str]] = [
    ("properties",
     "k21_properties_tenant_customer",
     "covered by perf_customers_properties_tenant_customer "
     "(tenant_id, customer_id)"),
    ("payment_methods",
     "k21_pm_tenant_customer_deleted",
     "covered by payment_methods_tenant_customer_default_idx "
     "prefix (tenant_id, customer_id)"),
]


def _env_db():
    load_dotenv("/app/backend/.env")
    from pymongo import MongoClient
    client = MongoClient(os.environ["MONGO_URL"])
    return client[os.environ["DB_NAME"]]


def _existing_names(db, coll: str) -> set[str]:
    return {idx["name"] for idx in db[coll].list_indexes()}


def _run_seed(db, *, apply: bool) -> int:
    """Emit ``[k21] <coll>.<name> — <status>`` lines for each K21
    index and the ``_SKIPPED`` cross-references."""
    exit_code = 0
    cache: Dict[str, set[str]] = {}
    for coll, name, keys in _K21_INDEXES:
        existing = cache.setdefault(coll, _existing_names(db, coll))
        if name in existing:
            print(f"[k21] {coll}.{name} — already_present")
            continue
        if not apply:
            print(f"[k21] {coll}.{name} — would_create")
            continue
        try:
            db[coll].create_index(keys, name=name, background=True)
        except Exception as exc:  # noqa: BLE001
            print(f"[k21] {coll}.{name} — error: "
                  f"{type(exc).__name__}: {exc}")
            exit_code = 2
            continue
        print(f"[k21] {coll}.{name} — created")
    for coll, name, why in _SKIPPED:
        print(f"[k21] {coll}.{name} — skipped ({why})")
    return exit_code


def _run_verify(db) -> int:
    """Confirm every K21 index exists on its collection.  Exit
    non-zero when any are missing so a CI runbook can fail fast."""
    missing: List[str] = []
    print("[k21-verify] current status:")
    for coll, name, _keys in _K21_INDEXES:
        existing = _existing_names(db, coll)
        marker = "OK" if name in existing else "MISSING"
        if marker == "MISSING":
            missing.append(f"{coll}.{name}")
        print(f"[k21-verify] [{marker:^7}] {coll}.{name}")
    for coll, name, why in _SKIPPED:
        print(f"[k21-verify] [SKIPPED] {coll}.{name} — {why}")
    if missing:
        for m in missing:
            print(f"[k21-verify] MISSING — {m}")
        return 1
    print("[k21-verify] all K21 indexes present.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Phase K21 · Feb-2026 — seed the perf-critical Mongo "
            "indexes for the customer + schedule web hot paths. "
            "Dry-run by default."
        ),
    )
    parser.add_argument("--apply", action="store_true",
                         help="Persist. Default is a dry-run.")
    parser.add_argument("--verify", action="store_true",
                         help=("List every K21 index and its status; "
                               "exit 1 if any are missing."))
    parser.add_argument("--tenant-id", default=None,
                         help=("Accepted for parity with other seed "
                               "scripts; indexes are collection-global "
                               "so this is a no-op."))
    args = parser.parse_args(argv)

    db = _env_db()
    if args.verify:
        return _run_verify(db)
    return _run_seed(db, apply=args.apply)


if __name__ == "__main__":
    sys.exit(main())
