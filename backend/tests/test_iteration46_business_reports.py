"""Iteration 46 — Business Reports (Feature E) + income-by-category retest."""
import os
import requests
import pytest

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://pool-app-mobile.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"


def _login(email, password="password123"):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def admin_token():
    return _login("admin@aquaterra.com")


@pytest.fixture(scope="module")
def tech_token():
    return _login("mike@aquaterra.com")


@pytest.fixture(scope="module")
def customer_token():
    return _login("customer@aquaterra.com")


def _auth(tok):
    return {"Authorization": f"Bearer {tok}"}


# ---------------- income-by-category retest ----------------
class TestIncomeByCategoryFix:
    def test_returns_positive_total_for_seed_paid_invoices(self, admin_token):
        r = requests.get(f"{API}/finances/income-by-category", headers=_auth(admin_token), timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        assert "total" in data and "rows" in data and "invoice_count" in data
        assert data["total"] > 0, f"Expected total>0, got {data}"
        # Loose sanity: seed revenue ~3615.80
        assert data["total"] >= 1000, f"Total suspiciously low: {data['total']}"
        assert data["invoice_count"] > 0
        assert isinstance(data["rows"], list) and len(data["rows"]) > 0
        for row in data["rows"]:
            assert "category" in row and "amount" in row
            assert row["amount"] >= 0

    def test_rbac_forbids_non_admin(self, tech_token, customer_token):
        for tok in (tech_token, customer_token):
            r = requests.get(f"{API}/finances/income-by-category", headers=_auth(tok), timeout=15)
            assert r.status_code == 403, r.text


# ---------------- business-summary ----------------
class TestBusinessSummary:
    def test_admin_summary_shape(self, admin_token):
        r = requests.get(f"{API}/reports/business-summary", headers=_auth(admin_token), timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        # Top-level keys
        for k in ["generated_at", "kpis", "revenue_series", "revenue_by_service",
                  "top_customers", "jobs_by_status", "technician_performance",
                  "income_by_category", "income_total", "pool_service", "labor_hours"]:
            assert k in d, f"missing key {k}"

        # KPIs
        kpis = d["kpis"]
        for k in ["revenue", "outstanding", "avg_ticket", "completion_rate",
                  "total_jobs", "total_customers", "open_leads",
                  "active_coverage", "labor_hours_week"]:
            assert k in kpis, f"missing kpi {k}"
        assert kpis["revenue"] > 0
        assert kpis["total_customers"] > 0
        assert kpis["total_jobs"] > 0
        assert 0 <= kpis["completion_rate"] <= 100

        # revenue series should have 6 months
        assert isinstance(d["revenue_series"], list)
        assert len(d["revenue_series"]) == 6
        for pt in d["revenue_series"]:
            assert "label" in pt and "value" in pt

        # income by category — the fix
        assert d["income_total"] > 0, f"income_total should be >0 after fix, got {d['income_total']}"
        assert isinstance(d["income_by_category"], list) and len(d["income_by_category"]) > 0

        # pool_service shape
        assert "rows" in d["pool_service"]

        # labor_hours is a list of {label,value}
        assert isinstance(d["labor_hours"], list)

    def test_admin_only_tech_403(self, tech_token):
        r = requests.get(f"{API}/reports/business-summary", headers=_auth(tech_token), timeout=15)
        assert r.status_code == 403, r.text

    def test_admin_only_customer_403(self, customer_token):
        r = requests.get(f"{API}/reports/business-summary", headers=_auth(customer_token), timeout=15)
        assert r.status_code == 403, r.text

    def test_unauth_401(self):
        r = requests.get(f"{API}/reports/business-summary", timeout=15)
        assert r.status_code in (401, 403)


# ---------------- regression: /api/reports still works ----------------
class TestReportsRegression:
    def test_reports_admin(self, admin_token):
        r = requests.get(f"{API}/reports", headers=_auth(admin_token), timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        for k in ["revenue", "outstanding", "avg_ticket", "completion_rate",
                  "total_jobs", "revenue_series", "jobs_by_status",
                  "revenue_by_service", "top_customers", "technician_performance"]:
            assert k in d, f"missing {k}"
        assert d["revenue"] > 0
        assert len(d["revenue_series"]) == 6
