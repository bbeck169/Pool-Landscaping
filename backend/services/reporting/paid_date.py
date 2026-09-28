"""Phase R1 · Feb-2026 — Shared invoice paid-date resolution.

Fixes the R0 drift where ``revenue_total`` queried a
``paid_date`` field that the live schema doesn't populate (the
real field is ``paid_at``). R0 fell through to a
``created_at``-in-range fallback, silently bucketing on invoice
creation instead of payment date.

This helper is the single source of truth for the paid-window
filter used by every revenue / cashflow / P&L metric. Prefers
``paid_at``, falls back to ``paid_date`` (for any legacy rows),
falls back to ``created_at`` (for rows missing both — matches
R0's pre-fix behaviour so old data still buckets somewhere).

Usage (Mongo find/aggregate filter)::

    from services.reporting.paid_date import build_paid_window_filter

    match = {
        "$and": [
            {"payment_status": "paid"},
            build_paid_window_filter(start, end),
        ]
    }

Reconciliation with R0
----------------------
R0's ``revenue_total`` swapped to this helper in the same phase.
Numbers may shift for tenants where a paid invoice's ``paid_at``
lies in a different calendar bucket than its ``created_at`` (the
common case: invoice raised on the last day of month N, paid on
the first day of month N+1). The delta is documented in
``PHASE_R1_A_FINANCIAL_BACKEND.md`` §5.

R0.1's ``revenue_by_customer`` + ``revenue_by_city`` already used
the correct ``paid_at`` filter via ``_revenue_shared.build_lens_filter``
so they need only a light refactor to consume THIS helper. Their
numeric output does not change.
"""
from __future__ import annotations


def build_paid_window_filter(start: str, end: str) -> dict:
    """Match paid invoices whose payment date lies in ``[start, end)``.

    Cascading resolution — the first non-empty field wins:

    * ``paid_at`` present + non-empty → bucket on ``paid_at``
    * else ``paid_date`` present + non-empty → bucket on ``paid_date``
    * else ``created_at`` in the window (matches R0 pre-fix behaviour)

    Emits a single ``$or`` filter that Mongo can plan against a
    ``(tenant_id, paid_at)`` compound index for the common path.
    """
    return {
        "$or": [
            # Preferred: live schema.
            {"paid_at": {"$gte": start, "$lt": end}},
            # Legacy: pre-Feb-2026 rows may have paid_date instead.
            {"$and": [
                {"paid_at": {"$in": [None, ""]}},
                {"paid_date": {"$gte": start, "$lt": end}},
            ]},
            # Fallback: neither payment field populated — bucket on
            # created_at so a paid invoice with a missing payment
            # date still lands somewhere (R0 pre-fix behaviour).
            {"$and": [
                {"paid_at": {"$in": [None, ""]}},
                {"paid_date": {"$in": [None, ""]}},
                {"created_at": {"$gte": start, "$lt": end}},
            ]},
        ]
    }


# ``PAID_STATUS_FILTER`` matches R0's ``PAID_FILTER`` semantically:
# a row is "paid" when it has a positive ``amount_paid`` OR its
# ``payment_status`` is the literal string "paid". Kept as a
# module-level constant so every metric picks up the same
# definition of "paid".
#
# FIN-PARITY-B · Feb-2026 — the ``amount_paid > 0`` branch is
# what makes PDF-imported payments show up in revenue metrics
# automatically. ``payment_reconciler.reconcile_invoice_after_payment``
# always writes ``amount_paid`` on the linked invoice, so a
# fully-paid or partial-paid imported invoice satisfies the $or
# without a schema migration or a paid_flag backfill.
PAID_STATUS_FILTER = {
    "$or": [
        {"amount_paid": {"$gt": 0}},
        {"payment_status": "paid"},
    ],
}


# ``OUTSTANDING_STATUS_FILTER`` — an invoice is outstanding when
# it is NOT paid AND its workflow ``status`` is one of the
# reader-visible states. Drafts + cancelled + null-status rows
# are excluded so AR aging doesn't over-count. See R1 audit §2 in
# ``PHASE_R1_A_FINANCIAL_BACKEND.md``.
#
# FIN-PARITY-B · Feb-2026 — ``partial`` is now a first-class
# ``payment_status`` value written by both ``record_payment`` and
# the FIN-PARITY-A ``payment_reconciler``. Add it to the eligible
# statuses so a partial-paid invoice still contributes its
# remaining balance (``total - amount_paid``) to AR-aging /
# unpaid-invoices metrics.  The trailing ``payment_status != "paid"``
# guard remains as belt-and-braces.
OUTSTANDING_STATUS_FILTER = {
    "$and": [
        {"doc_type": "invoice"},
        {"$or": [
            {"payment_status": {"$in": [
                "unpaid", "partial", "pending_reconciliation",
            ]}},
            {"payment_status": {"$in": [None, ""]}},
        ]},
        # Must have been issued/sent/accepted to count as owed.
        {"status": {"$in": ["issued", "sent", "accepted"]}},
        # NOT paid — belt-and-braces so amount_paid > 0 rows
        # (partial payment) still show up in the OUTSTANDING
        # bucket for their remaining balance.
        {"payment_status": {"$ne": "paid"}},
    ]
}


def build_effective_due_date_expr(net_terms_days: int = 30) -> dict:
    """Return a Mongo ``$expr`` fragment that computes
    ``effective_due_date`` per invoice:

    * ``due_date`` if present + non-empty
    * else ``created_at + net_terms_days``

    Returns a ``$dateAdd`` / ``$ifNull`` expression suitable for a
    ``$addFields`` stage. Callers can then ``$match`` against the
    computed field for bucketing.
    """
    return {
        "$let": {
            "vars": {
                "cast_due": {"$cond": [
                    {"$in": ["$due_date", [None, ""]]},
                    None,
                    {"$dateFromString": {
                        "dateString": "$due_date",
                        "onError": None, "onNull": None,
                    }},
                ]},
                "cast_created": {"$dateFromString": {
                    "dateString": "$created_at",
                    "onError": None, "onNull": None,
                }},
            },
            "in": {"$ifNull": ["$$cast_due", {
                "$dateAdd": {
                    "startDate": "$$cast_created",
                    "unit": "day",
                    "amount": int(net_terms_days),
                }
            }]},
        }
    }
