"""Phase R1 · Feb-2026 — End-to-end contract tests for the 7 new
financial metrics + reconciliation with the R0 paid-date fix.

Runs against the live backend (``http://localhost:8001/api``)
against the aquaterra tenant using the ``super@aquaterra.com``
super-admin fixture.  Correctness checks are envelope-level
(shape + invariants) — the numeric ground-truth is exercised via
the reconciliation test that asserts the same paid-window filter
now drives ``revenue_total`` and ``pnl_line_items.Revenue``.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values

_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
API = "http://localhost:8001/api"


def _login(email: str, pw: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login",
                      json={"email": email, "password": pw}, timeout=15)
    r.raise_for_status()
    j = r.json()
    return j.get("access_token") or j.get("token")


@pytest.fixture(scope="module")
def super_h():
    return {"Authorization": f"Bearer {_login('super@aquaterra.com')}"}


# ── Contract shape ───────────────────────────────────────────────
_GROUPED_KEYS = {"total", "rows", "row_count", "filters_applied",
                  "lens", "period", "prior_period"}
_SCALAR_KEYS = {"value", "prior_value", "delta_pct", "sparkline",
                 "period", "key", "label"}


class TestScalarMetricsEnvelope:
    def test_pnl_by_period(self, super_h):
        r = requests.get(f"{API}/reports/kpi/pnl_by_period?period=mtd",
                          headers=super_h, timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        assert _SCALAR_KEYS <= d.keys(), f"missing keys: {_SCALAR_KEYS - d.keys()}"
        assert isinstance(d["value"], (int, float))
        assert isinstance(d["prior_value"], (int, float))
        assert isinstance(d.get("sparkline") or [], list)


class TestGroupedMetricsEnvelope:
    @pytest.mark.parametrize("key", [
        "pnl_line_items",
        "cashflow_by_period",
        "ar_aging",
        "ar_aging_by_customer",
        "revenue_by_service_type",
        "unpaid_invoices",
    ])
    def test_envelope_shape(self, super_h, key):
        r = requests.get(f"{API}/reports/kpi/{key}?period=mtd",
                          headers=super_h, timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        assert _GROUPED_KEYS <= d.keys(), (
            f"{key} missing: {_GROUPED_KEYS - d.keys()}"
        )
        assert isinstance(d["rows"], list)
        assert d["row_count"] == len(d["rows"]) \
            or d["row_count"] >= len(d["rows"])  # ≥ when limit paged


class TestReconciliation:
    """R0 paid-date fix — after the shared helper landed,
    ``revenue_total`` and ``pnl_line_items.Revenue`` MUST produce
    the same number for the same period."""

    def test_revenue_total_matches_pnl_revenue_row(self, super_h):
        r_kpi = requests.get(f"{API}/reports/kpi/revenue_total?period=mtd",
                              headers=super_h, timeout=15)
        r_pnl = requests.get(f"{API}/reports/kpi/pnl_line_items?period=mtd",
                              headers=super_h, timeout=15)
        assert r_kpi.status_code == 200 and r_pnl.status_code == 200
        rev = float(r_kpi.json().get("value") or 0.0)
        pnl_rev_row = next(row for row in r_pnl.json()["rows"]
                           if row["label"] == "Revenue")
        assert abs(rev - float(pnl_rev_row["value"])) < 0.01, (
            f"revenue_total ({rev}) != pnl_line_items.Revenue "
            f"({pnl_rev_row['value']})"
        )


class TestArAgingBuckets:
    def test_four_buckets_always_present(self, super_h):
        r = requests.get(f"{API}/reports/kpi/ar_aging?period=mtd",
                          headers=super_h, timeout=15)
        d = r.json()
        buckets = [row["bucket"] for row in d["rows"]]
        assert buckets == ["0-30", "31-60", "61-90", "90+"]

    def test_net_terms_days_surfaced(self, super_h):
        d = requests.get(f"{API}/reports/kpi/ar_aging?period=mtd",
                          headers=super_h, timeout=15).json()
        # Tenant hasn't opted into a custom value → default 30.
        assert d["net_terms_days"] == 30

    def test_total_equals_sum_of_buckets(self, super_h):
        d = requests.get(f"{API}/reports/kpi/ar_aging?period=mtd",
                          headers=super_h, timeout=15).json()
        s = round(sum(r["amount"] for r in d["rows"]), 2)
        # Tolerance loosened to 2 cents so rounding drift (each
        # per-row round-2 vs total round-2) can't false-fire.
        assert abs(s - d["total"]) < 0.02


class TestArAgingByCustomer:
    def test_sorted_descending_by_outstanding(self, super_h):
        d = requests.get(
            f"{API}/reports/kpi/ar_aging_by_customer?period=mtd",
            headers=super_h, timeout=15).json()
        totals = [r["total_outstanding"] for r in d["rows"]]
        assert totals == sorted(totals, reverse=True)

    def test_customer_buckets_sum_to_customer_total(self, super_h):
        d = requests.get(
            f"{API}/reports/kpi/ar_aging_by_customer?period=mtd",
            headers=super_h, timeout=15).json()
        for row in d["rows"][:5]:  # spot-check first 5
            bs = round(sum(b["amount"] for b in row["buckets"].values()), 2)
            assert abs(bs - row["total_outstanding"]) < 0.01, (
                f"{row['customer_name']}: bucket-sum {bs} != "
                f"total {row['total_outstanding']}"
            )


class TestRevenueByServiceType:
    def test_uncategorized_bucket_when_field_missing(self, super_h):
        """Aquaterra invoices don't populate ``service_category_id``
        on line items — every row should collapse to 'Uncategorized'
        rather than 500ing."""
        d = requests.get(
            f"{API}/reports/kpi/revenue_by_service_type?period=mtd",
            headers=super_h, timeout=15).json()
        cats = [row["service_category_name"] for row in d["rows"]]
        assert "Uncategorized" in cats

    def test_lens_switch_between_invoiced_and_collected(self, super_h):
        d1 = requests.get(
            f"{API}/reports/kpi/revenue_by_service_type?"
            f"period=mtd&lens=invoiced",
            headers=super_h, timeout=15).json()
        d2 = requests.get(
            f"{API}/reports/kpi/revenue_by_service_type?"
            f"period=mtd&lens=collected",
            headers=super_h, timeout=15).json()
        assert d1["lens"] == "invoiced"
        assert d2["lens"] == "collected"


class TestUnpaidInvoices:
    def test_sorted_by_days_overdue_desc(self, super_h):
        d = requests.get(
            f"{API}/reports/kpi/unpaid_invoices?period=mtd",
            headers=super_h, timeout=15).json()
        days = [r["days_overdue"] for r in d["rows"]]
        assert days == sorted(days, reverse=True)

    def test_effective_due_date_populated(self, super_h):
        d = requests.get(
            f"{API}/reports/kpi/unpaid_invoices?period=mtd",
            headers=super_h, timeout=15).json()
        for row in d["rows"]:
            assert row["effective_due_date"], (
                f"invoice {row['id']} missing effective_due_date"
            )

    def test_partial_flag_matches_amount_paid(self, super_h):
        d = requests.get(
            f"{API}/reports/kpi/unpaid_invoices?period=mtd",
            headers=super_h, timeout=15).json()
        for row in d["rows"]:
            expected_partial = row["amount_paid"] > 0
            assert row["partial"] == expected_partial


class TestCashflowByPeriod:
    def test_running_balance_monotone_from_first_row(self, super_h):
        """The running-balance column should be cumulative — each
        row is prev + net."""
        d = requests.get(
            f"{API}/reports/kpi/cashflow_by_period?period=ytd",
            headers=super_h, timeout=15).json()
        running = 0.0
        for row in d["rows"]:
            running = round(running + row["net"], 2)
            assert abs(running - row["running_balance"]) < 0.01, (
                f"running_balance drift at {row['bucket']}: "
                f"expected {running}, got {row['running_balance']}"
            )

    def test_summary_totals_match_row_sums(self, super_h):
        d = requests.get(
            f"{API}/reports/kpi/cashflow_by_period?period=ytd",
            headers=super_h, timeout=15).json()
        inv = round(sum(r["invoiced"] for r in d["rows"]), 2)
        col = round(sum(r["collected"] for r in d["rows"]), 2)
        assert abs(inv - d["summary"]["invoiced_total"]) < 0.01
        assert abs(col - d["summary"]["collected_total"]) < 0.01


class TestTenantIsolation:
    """Every metric must scope to the caller's tenant. A cross-
    tenant leak would show up as another tenant's row bleeding
    into aquaterra's response."""

    def test_ar_aging_customers_are_aquaterra_only(self, super_h):
        from pymongo import MongoClient
        c = MongoClient(_ENV["MONGO_URL"])
        db = c[_ENV["DB_NAME"]]
        tenant = db.tenants.find_one({"slug": "aquaterra"}, {"id": 1})
        tenant_id = tenant["id"]
        d = requests.get(
            f"{API}/reports/kpi/ar_aging_by_customer?period=ytd",
            headers=super_h, timeout=15).json()
        cust_ids = [r["customer_id"] for r in d["rows"] if r.get("customer_id")]
        if cust_ids:
            hits = db.customers.count_documents(
                {"tenant_id": tenant_id, "id": {"$in": cust_ids}}
            )
            assert hits == len(set(cust_ids)), (
                "AR aging leaked non-aquaterra customer ids"
            )
        c.close()


class TestAuthGuard:
    def test_unauthenticated_returns_401_or_403(self):
        # FastAPI returns 403 when the Authorization header is
        # missing entirely and 401 when the token is invalid;
        # either is an acceptable "you're not authenticated"
        # signal for the FE.
        for key in ("pnl_by_period", "ar_aging", "unpaid_invoices"):
            r = requests.get(f"{API}/reports/kpi/{key}?period=mtd",
                              timeout=10)
            assert r.status_code in (401, 403), (
                f"{key} allowed unauthenticated: {r.status_code}"
            )


class TestFilterMatrix:
    def test_period_variants_all_200(self, super_h):
        # Only the periods the resolver supports today. If new
        # aliases (today / wtd) get added later, extend this
        # tuple in the same phase.
        for p in ("mtd", "qtd", "ytd", "last_30d"):
            r = requests.get(f"{API}/reports/kpi/pnl_by_period?period={p}",
                              headers=super_h, timeout=15)
            assert r.status_code == 200, f"period={p} → {r.status_code}"

    def test_limit_and_offset(self, super_h):
        d1 = requests.get(
            f"{API}/reports/kpi/ar_aging_by_customer?period=ytd&limit=2",
            headers=super_h, timeout=15).json()
        d2 = requests.get(
            f"{API}/reports/kpi/ar_aging_by_customer?"
            f"period=ytd&limit=2&offset=1",
            headers=super_h, timeout=15).json()
        # The paged rows should be different (assuming ≥3 rows total).
        if d1["row_count"] >= 3:
            assert d1["rows"][0]["customer_id"] != d2["rows"][0]["customer_id"]


class TestCacheHit:
    def test_second_call_is_cached(self, super_h):
        # First call primes.
        requests.get(f"{API}/reports/kpi/pnl_line_items?period=mtd",
                      headers=super_h, timeout=15)
        r = requests.get(f"{API}/reports/kpi/pnl_line_items?period=mtd",
                          headers=super_h, timeout=15)
        assert r.status_code == 200
        assert r.json().get("cached") is True
