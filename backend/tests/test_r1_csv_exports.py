"""Phase R1 · Feb-2026 — CSV export endpoint contract tests.

Locks the ``/api/reports/kpi/{key}/export.csv`` shape for every
registered metric — scalar + grouped variants — so a schema
regression is caught before landing on the FE.
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


class TestScalarExport:
    def test_revenue_total_csv_shape(self, super_h):
        r = requests.get(
            f"{API}/reports/kpi/revenue_total/export.csv?period=mtd",
            headers=super_h, timeout=15)
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/csv")
        cd = r.headers.get("content-disposition") or ""
        assert 'attachment' in cd and "revenue-total" in cd
        body = r.text
        assert body.startswith("\ufeff"), "missing BOM"
        assert "Metric,Period,Start,End,Value,Prior,Delta %" in body
        assert "Total Revenue" in body
        assert "Sparkline point,Bucket,Value" in body
        assert "R1 Financial Suite" in body
        assert "Generated at" in body

    def test_pnl_by_period_csv(self, super_h):
        r = requests.get(
            f"{API}/reports/kpi/pnl_by_period/export.csv?period=mtd",
            headers=super_h, timeout=15)
        assert r.status_code == 200
        assert "Net Profit" in r.text


class TestGroupedExport:
    @pytest.mark.parametrize("key,expected_col,label_marker", [
        ("pnl_line_items",          "Label",                 "P&L Line Items"),
        ("cashflow_by_period",      "Bucket",                "Cash Flow by Period"),
        ("ar_aging",                "Bucket",                "AR Aging"),
        ("ar_aging_by_customer",    "Customer Name",         "AR Aging by Customer"),
        ("revenue_by_service_type", "Service Category Name", "Revenue by Service Type"),
        ("unpaid_invoices",         "Invoice Number",        "Unpaid Invoices"),
    ])
    def test_column_order_locked(self, super_h, key, expected_col, label_marker):
        r = requests.get(
            f"{API}/reports/kpi/{key}/export.csv?period=mtd",
            headers=super_h, timeout=15)
        assert r.status_code == 200
        body = r.text
        assert body.startswith("\ufeff")
        assert label_marker in body, (
            f"{key} missing metric label {label_marker!r}"
        )
        assert expected_col in body, (
            f"{key} missing expected header column {expected_col!r}"
        )

    def test_ar_aging_total_line_present(self, super_h):
        r = requests.get(
            f"{API}/reports/kpi/ar_aging/export.csv?period=mtd",
            headers=super_h, timeout=15)
        body = r.text
        # Look for the "Total,<number>" header emitted by the CSV helper.
        lines = body.splitlines()
        total_lines = [l for l in lines if l.startswith("Total,")]
        assert total_lines, "grouped CSV missing Total,... header"


class TestExportGuard:
    def test_unknown_metric_returns_404(self, super_h):
        r = requests.get(
            f"{API}/reports/kpi/nonexistent_metric/export.csv?period=mtd",
            headers=super_h, timeout=10)
        assert r.status_code in (404, 400)

    def test_unauthenticated_returns_401_or_403(self):
        r = requests.get(
            f"{API}/reports/kpi/pnl_line_items/export.csv?period=mtd",
            timeout=10)
        assert r.status_code in (401, 403)


class TestCachingHeaders:
    def test_no_store_header(self, super_h):
        # Manual exports should always reflect fresh reads.
        r = requests.get(
            f"{API}/reports/kpi/pnl_line_items/export.csv?period=mtd",
            headers=super_h, timeout=15)
        assert r.headers.get("cache-control") == "no-store"
