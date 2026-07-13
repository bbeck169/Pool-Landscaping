"""Phase 6 — Reports + Finance backend tests."""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://poolscape-audit.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"


def _login(email, password):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=30)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def admin_headers():
    return {"Authorization": f"Bearer {_login('admin@aquaterra.com', 'password123')}"}


@pytest.fixture(scope="module")
def tech_headers():
    return {"Authorization": f"Bearer {_login('mike@aquaterra.com', 'password123')}"}


# ─── Endpoint contract shapes ─────────────────────────────────────────────────
SLICE_EPS = [
    ("/reports/revenue-by-city",     "cities"),
    ("/reports/revenue-by-crew",     "crews"),
    ("/reports/revenue-by-customer", "customers"),
    ("/reports/invoiced-items",      "unique_items"),
]


class TestPhase6Admin:
    def test_forecast(self, admin_headers):
        r = requests.get(f"{API}/reports/forecast", headers=admin_headers, timeout=30)
        assert r.status_code == 200, r.text
        j = r.json()
        assert "series" in j and "total" in j and "days" in j
        assert isinstance(j["series"], list)

    def test_forecast_cards(self, admin_headers):
        r = requests.get(f"{API}/reports/forecast-cards", headers=admin_headers, timeout=30)
        assert r.status_code == 200, r.text
        j = r.json()
        for k in ["pipeline_value", "weighted_forecast", "monthly_recurring", "at_risk"]:
            assert k in j

    @pytest.mark.parametrize("path,key", SLICE_EPS)
    def test_revenue_slices(self, admin_headers, path, key):
        r = requests.get(f"{API}{path}?start=2024-01-01&end=2026-12-31",
                         headers=admin_headers, timeout=30)
        assert r.status_code == 200, r.text
        j = r.json()
        assert "rows" in j and "summary" in j
        assert isinstance(j["rows"], list)
        for f in ["total", key, "invoices"]:
            assert f in j["summary"], f"missing summary.{f} in {path}"

    def test_gross_sales(self, admin_headers):
        r = requests.get(f"{API}/reports/gross-sales?start=2024-01-01&end=2026-12-31",
                         headers=admin_headers, timeout=30)
        assert r.status_code == 200, r.text
        j = r.json()
        assert "rows" in j and "trend" in j and "summary" in j
        for f in ["gross", "collected", "outstanding", "count"]:
            assert f in j["summary"]

    def test_payments_list(self, admin_headers):
        r = requests.get(f"{API}/payments/list?page=1&page_size=50",
                         headers=admin_headers, timeout=30)
        assert r.status_code == 200, r.text
        j = r.json()
        for f in ["rows", "page", "page_size", "total", "total_amount"]:
            assert f in j
        assert j["page"] == 1 and j["page_size"] == 50

    def test_billing_plans_run(self, admin_headers):
        r = requests.post(f"{API}/billing-plans/run", headers=admin_headers, timeout=60)
        assert r.status_code == 200, r.text
        j = r.json()
        assert "fired" in j and "runs" in j
        assert isinstance(j["runs"], list)

    def test_export_jobs(self, admin_headers):
        r = requests.get(f"{API}/export/jobs", headers=admin_headers, timeout=30)
        assert r.status_code == 200, r.text
        j = r.json()
        for f in ["filename", "content", "count"]:
            assert f in j

    def test_export_invoices(self, admin_headers):
        r = requests.get(f"{API}/export/invoices", headers=admin_headers, timeout=30)
        assert r.status_code == 200, r.text
        j = r.json()
        for f in ["filename", "content", "count"]:
            assert f in j


# ─── Existing endpoints regression ───────────────────────────────────────────
class TestRegression:
    def test_business_summary(self, admin_headers):
        r = requests.get(f"{API}/reports/business-summary", headers=admin_headers, timeout=30)
        assert r.status_code == 200, r.text

    def test_income_by_category(self, admin_headers):
        r = requests.get(f"{API}/finances/income-by-category", headers=admin_headers, timeout=30)
        assert r.status_code == 200, r.text


# ─── Non-admin (technician) must get 403 on all Phase-6 endpoints ────────────
NON_ADMIN_GET = [
    "/reports/forecast",
    "/reports/forecast-cards",
    "/reports/revenue-by-city",
    "/reports/revenue-by-crew",
    "/reports/revenue-by-customer",
    "/reports/gross-sales",
    "/reports/invoiced-items",
    "/payments/list",
    "/export/jobs",
    "/export/invoices",
]


class TestNonAdminForbidden:
    @pytest.mark.parametrize("path", NON_ADMIN_GET)
    def test_get_forbidden(self, tech_headers, path):
        r = requests.get(f"{API}{path}", headers=tech_headers, timeout=30)
        assert r.status_code == 403, f"{path} → {r.status_code}"

    def test_post_run_forbidden(self, tech_headers):
        r = requests.post(f"{API}/billing-plans/run", headers=tech_headers, timeout=30)
        assert r.status_code == 403


# ─── OpenAPI includes all 11 new paths ───────────────────────────────────────
def test_openapi_includes_phase6_paths():
    r = requests.get(f"{API}/openapi.json", timeout=30)
    assert r.status_code == 200
    paths = r.json().get("paths", {})
    required = [
        "/api/reports/forecast",
        "/api/reports/forecast-cards",
        "/api/reports/revenue-by-city",
        "/api/reports/revenue-by-crew",
        "/api/reports/revenue-by-customer",
        "/api/reports/gross-sales",
        "/api/reports/invoiced-items",
        "/api/payments/list",
        "/api/billing-plans/run",
        "/api/export/jobs",
        "/api/export/invoices",
    ]
    missing = [p for p in required if p not in paths]
    assert not missing, f"Missing paths in openapi: {missing}"
