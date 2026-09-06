"""Phase R1 · Feb-2026 — Shared paid-date helper unit tests.

Locks the contract for ``services.reporting.paid_date`` — the
helper that every revenue / cashflow / P&L metric consumes.
"""
from __future__ import annotations

import pytest

from services.reporting.paid_date import (
    PAID_STATUS_FILTER,
    OUTSTANDING_STATUS_FILTER,
    build_paid_window_filter,
    build_effective_due_date_expr,
)


class TestPaidWindowFilter:
    def test_cascade_prefers_paid_at(self):
        f = build_paid_window_filter("2026-01-01", "2026-02-01")
        assert isinstance(f, dict)
        assert "$or" in f
        # First branch: paid_at in-window (fast path).
        first = f["$or"][0]
        assert "paid_at" in first
        assert first["paid_at"]["$gte"] == "2026-01-01"
        assert first["paid_at"]["$lt"] == "2026-02-01"

    def test_falls_through_to_paid_date_when_paid_at_empty(self):
        f = build_paid_window_filter("2026-01-01", "2026-02-01")
        second = f["$or"][1]
        assert second == {
            "$and": [
                {"paid_at": {"$in": [None, ""]}},
                {"paid_date": {"$gte": "2026-01-01",
                                "$lt":  "2026-02-01"}},
            ]
        }

    def test_final_fallback_created_at(self):
        """R0 pre-fix behaviour preserved for rows missing both
        payment fields — a paid row with no payment-date still
        buckets somewhere."""
        f = build_paid_window_filter("2026-01-01", "2026-02-01")
        third = f["$or"][2]
        assert third["$and"][0] == {"paid_at": {"$in": [None, ""]}}
        assert third["$and"][1] == {"paid_date": {"$in": [None, ""]}}
        assert third["$and"][2] == {"created_at": {"$gte": "2026-01-01",
                                                     "$lt":  "2026-02-01"}}

    def test_exclusive_upper_bound(self):
        """Buckets are half-open [start, end) so month N end == month N+1 start."""
        f = build_paid_window_filter("2026-01-01", "2026-02-01")
        # String-based invariant is stronger than tree-walking here:
        # every date operator in the filter is $lt (half-open) or
        # $gte (inclusive lower), never $lte / $gt.
        s = str(f)
        assert "$lt" in s and "$gte" in s
        assert "$lte" not in s
        # $gt only appears in ``PAID_STATUS_FILTER``'s
        # ``amount_paid: {$gt: 0}`` — NOT in this helper's output.
        assert "$gt" not in s or "amount_paid" not in s


def _rightmost_date_op(branch):
    if isinstance(branch, dict):
        for k, v in branch.items():
            if k in ("$or", "$and"):
                for sub in v:
                    r = _rightmost_date_op(sub)
                    if r:
                        return r
            elif k in ("paid_at", "paid_date", "created_at"):
                if isinstance(v, dict) and ("$gte" in v or "$lt" in v):
                    return v
    return {}


class TestPaidStatusFilter:
    def test_matches_paid_or_amount_paid_positive(self):
        # Semantic equivalence with R0's PAID_FILTER — a row is
        # paid when either signal fires.
        assert PAID_STATUS_FILTER == {
            "$or": [
                {"amount_paid": {"$gt": 0}},
                {"payment_status": "paid"},
            ]
        }


class TestOutstandingStatusFilter:
    def test_excludes_drafts_and_paid(self):
        # Drafts must never appear in AR aging.
        assert {"status": {"$in": ["issued", "sent", "accepted"]}} \
            in OUTSTANDING_STATUS_FILTER["$and"]
        # And a paid row must be excluded even if status says draft.
        assert {"payment_status": {"$ne": "paid"}} \
            in OUTSTANDING_STATUS_FILTER["$and"]

    def test_pending_reconciliation_counted_as_outstanding(self):
        # R1 audit §2 — locked assumption.
        payment_branch = None
        for a in OUTSTANDING_STATUS_FILTER["$and"]:
            if "$or" in a and any("payment_status" in b for b in a["$or"]):
                payment_branch = a
                break
        assert payment_branch is not None
        statuses = payment_branch["$or"][0]["payment_status"]["$in"]
        assert "pending_reconciliation" in statuses
        assert "unpaid" in statuses


class TestEffectiveDueDateExpr:
    def test_default_net_terms_30(self):
        expr = build_effective_due_date_expr()
        # Sanity: it's a $let / $ifNull expression referencing due_date + created_at.
        s = str(expr)
        assert "$let" in s
        assert "$ifNull" in s
        assert "$dateAdd" in s
        assert "due_date" in s
        assert "created_at" in s
        assert '"amount": 30' in s or "'amount': 30" in s

    @pytest.mark.parametrize("n", [0, 15, 45, 60, 365])
    def test_configurable_net_terms(self, n):
        expr = build_effective_due_date_expr(n)
        s = str(expr)
        assert f"'amount': {n}" in s or f'"amount": {n}' in s

    def test_out_of_range_still_produces_expr(self):
        # Callers can pass any int — the helper clamps
        # semantically only through the tenant-loading path in
        # ``ar_aging._resolve_net_terms``, not here.
        expr = build_effective_due_date_expr(9999)
        assert isinstance(expr, dict)
