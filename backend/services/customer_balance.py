"""PERF-AUDIT-C · Feb-2026 — Shared customer-balance compute + denorm.

Single source of truth for the four KPI tiles on the customer
profile (balance_due, past_due, credit, overdue) PLUS the companion
denorm writer that stores the computed values back onto the
customer doc so profile reads are O(1) field lookups instead of
per-request aggregations.

Why precompute?
───────────────
The customer-profile KPI endpoint (``GET /customers/{cid}/kpi-
summary``) runs a 4-way parallel fan-out (balance aggregation,
pending-estimates count, unread-messages count, credits lookup).
On preview with ~400 invoices for the heaviest customer it clocks
in at 7-12ms — fast but linear in open-invoice count.  At 10k+
invoices per customer (the shape production is drifting toward)
the balance aggregation starts dominating the P95.

Precompute strategy:
  * Store ``balance_due`` (dollars, float), ``past_due`` (dollars),
    ``credit_balance_cents`` (int), ``overdue_count`` (int), and
    ``balance_recomputed_at`` (ISO) directly on the customer doc.
  * Profile read: single ``find_one`` returns everything the UI
    needs without touching ``quotes``.
  * Write path (future-wire): event handlers on invoice create /
    update / pay / void, payment apply, credit grant/revoke call
    ``recompute_customer_balance_denorm`` to refresh the stored
    fields.
  * Audit endpoint (admin): ``POST /api/admin/customers/balance-
    audit?fix=false`` iterates every customer in the tenant,
    computes vs stored, returns the mismatch list + counts.
    ``fix=true`` writes computed values back.
  * Lazy backfill: profile endpoints call
    ``recompute_customer_balance_denorm`` opportunistically when
    the stored fields are missing OR older than
    ``_STALE_THRESHOLD_SECONDS`` — so even without event-handler
    wiring the common case stays fresh.

Formula (locked to match ``routers/customers.py::get_customer_kpi_
summary``)
──────────────────────────────────────────────────────────────────
Balance aggregation runs over ``db.quotes`` with::

    {tenant_id, customer_id, doc_type="invoice",
     payment_status in {"unpaid", "partial", "partially_paid"},
     deleted_at not set}

For each matching row::

    balance    = (total or 0) - (amount_paid or 0)
    is_past_due = due_date is not None AND due_date < today_iso

Then::

    balance_due    = sum(balance over all rows)
    past_due       = sum(balance where is_past_due)
    overdue_count  = count(rows where is_past_due)

Credit balance = ``customer_credits_balance.balance_cents`` for
(tenant, customer).  Falls back to
``int(balance_dollars * 100)`` for legacy rows that only wrote the
dollar-denominated field.

Edge cases locked by tests
──────────────────────────
  * Empty — no invoices, no credits → all zeros.
  * Draft invoices excluded (status filter is on payment_status,
    not status; draft invoices sit at payment_status=unpaid and
    DO count toward balance_due as intended — matches current UI
    behavior).
  * Void invoices excluded (``deleted_at`` filter).
  * Partial payment — balance_due reflects the unpaid remainder
    (total minus amount_paid), not the full total.
  * Credit applied partial — the applied portion stays on
    amount_paid; the unapplied credit sits on
    customer_credits_balance.
  * Unapplied credit — credit_balance_cents > 0, balance_due
    unchanged.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


logger = logging.getLogger("services.customer_balance")


# Lazy-backfill threshold.  Any stored value older than this (or
# missing entirely) triggers a background recompute on the next
# profile read.  Tuned to keep the UI fresh without stampeding the
# DB on hot customers.
_STALE_THRESHOLD_SECONDS = 60.0


# Open-invoice payment-status filter — locked to the same list
# used by routers/customers.py::get_customer_kpi_summary so the
# audit endpoint reports true parity instead of definition drift.
_OPEN_PAYMENT_STATUSES = ["unpaid", "partial", "partially_paid"]


def _today_iso() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _agg_invoice_balance(
    db, tenant_id: str, customer_id: str, *, today_iso: str,
) -> Dict[str, Any]:
    """Run the single-pass balance+past_due+overdue aggregation.

    Returns a dict with keys ``balance_due`` (dollars, float),
    ``past_due`` (dollars, float), and ``overdue_count`` (int).
    Zero defaults when there are no matching rows.
    """
    from utils import not_deleted_filter
    nd = not_deleted_filter()
    _open_match = {
        "tenant_id": tenant_id,
        "customer_id": customer_id,
        "doc_type": "invoice",
        "payment_status": {"$in": _OPEN_PAYMENT_STATUSES},
        **nd,
    }
    pipeline = [
        {"$match": _open_match},
        {"$project": {
            "balance": {"$subtract": [
                {"$ifNull": ["$total", 0]},
                {"$ifNull": ["$amount_paid", 0]},
            ]},
            "is_past_due": {
                "$and": [
                    {"$ne": [{"$ifNull": ["$due_date", None]}, None]},
                    {"$lt": ["$due_date", today_iso]},
                ]},
        }},
        {"$group": {
            "_id": None,
            "balance_due": {"$sum": "$balance"},
            "past_due": {
                "$sum": {"$cond": ["$is_past_due", "$balance", 0]}},
            "overdue_count": {
                "$sum": {"$cond": ["$is_past_due", 1, 0]}},
        }},
    ]
    cur = db.quotes.aggregate(pipeline)
    rows = await cur.to_list(1)
    row = rows[0] if rows else {}
    return {
        "balance_due": float(row.get("balance_due") or 0.0),
        "past_due": float(row.get("past_due") or 0.0),
        "overdue_count": int(row.get("overdue_count") or 0),
    }


async def _credit_balance_cents(
    db, tenant_id: str, customer_id: str,
) -> int:
    row = await db.customer_credits_balance.find_one(
        {"tenant_id": tenant_id, "customer_id": customer_id},
        {"_id": 0, "balance_cents": 1, "balance": 1},
    ) or {}
    cents = row.get("balance_cents")
    if cents is None:
        try:
            cents = int(round(float(row.get("balance") or 0) * 100))
        except Exception:                                             # noqa: BLE001
            cents = 0
    try:
        return int(cents)
    except Exception:                                                 # noqa: BLE001
        return 0


async def compute_customer_balance(
    db, tenant_id: str, customer_id: str,
) -> Dict[str, Any]:
    """Live-compute the four KPI tile values for a customer.

    Returns a dict::

        {
            "balance_due":           float,      # dollars
            "past_due":              float,      # dollars
            "credit_balance_cents":  int,
            "overdue_count":         int,
            "as_of":                 str,        # ISO timestamp
        }

    No side effects — pure read.  Call
    ``recompute_customer_balance_denorm`` to also persist the result.
    """
    agg, credit_cents = await asyncio.gather(
        _agg_invoice_balance(
            db, tenant_id, customer_id, today_iso=_today_iso(),
        ),
        _credit_balance_cents(db, tenant_id, customer_id),
        return_exceptions=True,
    )
    if isinstance(agg, Exception):
        logger.warning(
            "[compute_customer_balance] agg failed tenant=%s cust=%s: %s",
            tenant_id, customer_id, agg,
        )
        agg = {"balance_due": 0.0, "past_due": 0.0, "overdue_count": 0}
    if isinstance(credit_cents, Exception):
        logger.warning(
            "[compute_customer_balance] credit failed tenant=%s "
            "cust=%s: %s",
            tenant_id, customer_id, credit_cents,
        )
        credit_cents = 0
    return {
        "balance_due":          round(float(agg["balance_due"]), 2),
        "past_due":             round(float(agg["past_due"]), 2),
        "credit_balance_cents": int(credit_cents),
        "overdue_count":        int(agg["overdue_count"]),
        "as_of":                _now_iso(),
    }


async def recompute_customer_balance_denorm(
    db, tenant_id: str, customer_id: str,
) -> Dict[str, Any]:
    """Compute + persist the four KPI values to the customer doc.

    Writes ``balance_due``, ``past_due``, ``credit_balance_cents``,
    ``overdue_count``, ``balance_recomputed_at`` onto the matched
    customer.  Idempotent — repeated calls converge on the same
    stored shape.

    Returns the computed dict (same shape as
    ``compute_customer_balance``) PLUS a ``persisted: bool`` flag
    (False when the customer row doesn't exist for the tenant).
    """
    computed = await compute_customer_balance(
        db, tenant_id, customer_id,
    )
    res = await db.customers.update_one(
        {"id": customer_id, "tenant_id": tenant_id},
        {"$set": {
            "balance_due":            computed["balance_due"],
            "past_due":               computed["past_due"],
            "credit_balance_cents":   computed["credit_balance_cents"],
            "overdue_count":          computed["overdue_count"],
            "balance_recomputed_at":  computed["as_of"],
        }},
    )
    computed["persisted"] = bool(res.matched_count)
    return computed


def _stored_is_stale(cust: Dict[str, Any]) -> bool:
    """Return True when the customer doc's cached balance is
    missing OR older than ``_STALE_THRESHOLD_SECONDS``."""
    if cust is None:
        return True
    if "balance_due" not in cust or "past_due" not in cust:
        return True
    stamp = cust.get("balance_recomputed_at")
    if not stamp:
        return True
    try:
        then = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except Exception:                                                 # noqa: BLE001
        return True
    now = datetime.now(timezone.utc)
    age = (now - then).total_seconds()
    return age > _STALE_THRESHOLD_SECONDS


async def ensure_fresh_balance_denorm(
    db, tenant_id: str, customer_id: str,
    cust_doc: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Lazy-backfill wrapper for profile reads.

    If the customer doc's cached balance is missing or stale, run
    the recompute and persist.  Otherwise return the cached values
    pulled directly off the doc so the hot read path stays
    O(1-field-lookup).

    Pass ``cust_doc`` to avoid a second ``find_one`` when the caller
    has already fetched the customer row (profile endpoints always
    have).  Omit it and this function will fetch internally.
    """
    cust = cust_doc
    if cust is None:
        cust = await db.customers.find_one(
            {"id": customer_id, "tenant_id": tenant_id},
            {"_id": 0, "balance_due": 1, "past_due": 1,
             "credit_balance_cents": 1, "overdue_count": 1,
             "balance_recomputed_at": 1},
        )
    if _stored_is_stale(cust):
        return await recompute_customer_balance_denorm(
            db, tenant_id, customer_id,
        )
    return {
        "balance_due":          float(cust.get("balance_due") or 0.0),
        "past_due":             float(cust.get("past_due") or 0.0),
        "credit_balance_cents": int(cust.get("credit_balance_cents") or 0),
        "overdue_count":        int(cust.get("overdue_count") or 0),
        "as_of":                cust.get("balance_recomputed_at"),
        "persisted":            True,
    }


async def audit_tenant_customer_balances(
    db, tenant_id: str, *, fix: bool = False,
    limit: Optional[int] = None,
) -> Dict[str, Any]:
    """Iterate every customer in ``tenant_id``, compute vs stored,
    optionally repair.

    Scans the ``customers`` collection scoped to ``tenant_id`` +
    ``deleted_at`` not set.  For each row compares the stored
    denorm fields vs. the freshly computed values.

    Returns::

        {
            "ok":                 True,
            "fix":                bool,
            "tenant_id":          str,
            "customers_scanned":  int,
            "customers_matched":  int,     # stored == computed
            "customers_drifted":  int,     # stored != computed
            "customers_missing":  int,     # stored fields absent
            "customers_fixed":    int,     # 0 when fix=False
            "mismatches":         [        # <= 50 entries for the
                {"customer_id": str,       #    operator diff UI
                 "stored":  {...},
                 "computed":{...}},
                ...
            ],
        }

    Dry-run default: ``fix=False`` reports but doesn't write.
    """
    scanned = 0
    matched = 0
    drifted = 0
    missing = 0
    fixed = 0
    mismatches: List[Dict[str, Any]] = []
    _MISMATCH_CAP = 50

    _match: Dict[str, Any] = {
        "tenant_id": tenant_id,
        "deleted_at": {"$in": [None]},
    }
    projection = {
        "_id": 0, "id": 1,
        "balance_due": 1, "past_due": 1,
        "credit_balance_cents": 1, "overdue_count": 1,
        "balance_recomputed_at": 1,
    }
    cursor = db.customers.find(_match, projection)
    if limit:
        cursor = cursor.limit(int(limit))

    async for cust in cursor:
        scanned += 1
        cid = cust.get("id")
        if not cid:
            continue

        has_denorm = all(
            k in cust
            for k in ("balance_due", "past_due",
                        "credit_balance_cents", "overdue_count")
        )
        stored = {
            "balance_due":          float(cust.get("balance_due") or 0.0),
            "past_due":             float(cust.get("past_due") or 0.0),
            "credit_balance_cents": int(cust.get("credit_balance_cents") or 0),
            "overdue_count":        int(cust.get("overdue_count") or 0),
        }

        try:
            computed_full = await compute_customer_balance(
                db, tenant_id, cid,
            )
        except Exception as _exc:                                     # noqa: BLE001
            logger.warning(
                "[balance_audit] compute failed tenant=%s cust=%s: %s",
                tenant_id, cid, _exc,
            )
            continue

        computed = {
            "balance_due":          computed_full["balance_due"],
            "past_due":             computed_full["past_due"],
            "credit_balance_cents": computed_full["credit_balance_cents"],
            "overdue_count":        computed_full["overdue_count"],
        }

        if not has_denorm:
            missing += 1
        elif stored == computed:
            matched += 1
            continue
        else:
            drifted += 1

        # Mismatch (or missing denorm) → report + optionally fix.
        if len(mismatches) < _MISMATCH_CAP:
            mismatches.append({
                "customer_id": cid,
                "stored":   stored if has_denorm else None,
                "computed": computed,
            })

        if fix:
            await db.customers.update_one(
                {"id": cid, "tenant_id": tenant_id},
                {"$set": {
                    "balance_due":            computed["balance_due"],
                    "past_due":               computed["past_due"],
                    "credit_balance_cents":   computed["credit_balance_cents"],
                    "overdue_count":          computed["overdue_count"],
                    "balance_recomputed_at":  computed_full["as_of"],
                }},
            )
            fixed += 1

    return {
        "ok":                True,
        "fix":               fix,
        "tenant_id":         tenant_id,
        "customers_scanned": scanned,
        "customers_matched": matched,
        "customers_drifted": drifted,
        "customers_missing": missing,
        "customers_fixed":   fixed,
        "mismatches":        mismatches,
    }
