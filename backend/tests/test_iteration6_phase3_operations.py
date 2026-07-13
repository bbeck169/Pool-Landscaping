"""Iteration 6 — Phase 3 Operations: Dispatch, Work Stream (activity), Reports.

Covers:
- GET /api/dispatch?date=YYYY-MM-DD (admin-only)
- GET /api/activity (admin-only)
- GET /api/reports (admin-only)
- RBAC: 403 for technician + customer on all three
- Dispatch assign flow: PUT /api/jobs/{id} {technician_id}
- Regression: Phase 2 endpoints still admin-only
"""
import os
from datetime import datetime, timezone

import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "").rstrip("/")
assert BASE_URL, "EXPO_PUBLIC_BACKEND_URL must be set"

ADMIN = {"email": "admin@aquaterra.com", "password": "password123"}
TECH = {"email": "mike@aquaterra.com", "password": "password123"}
CUST = {"email": "customer@aquaterra.com", "password": "password123"}


def _login(creds):
    r = requests.post(f"{BASE_URL}/api/auth/login", json=creds, timeout=15)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    body = r.json()
    return body["access_token"], body["user"]


@pytest.fixture(scope="module")
def admin_headers():
    tok, _ = _login(ADMIN)
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def tech_headers():
    tok, _ = _login(TECH)
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def customer_headers():
    tok, _ = _login(CUST)
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


# --------------------------- Dispatch ---------------------------
class TestDispatch:
    def test_dispatch_admin_today(self, admin_headers):
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        r = requests.get(f"{BASE_URL}/api/dispatch?date={today}", headers=admin_headers, timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["date"] == today
        assert "columns" in d and isinstance(d["columns"], list)
        assert "unassigned" in d and isinstance(d["unassigned"], list)
        for col in d["columns"]:
            for field in ("technician_id", "technician_name", "jobs"):
                assert field in col, f"missing {field} in column {col}"
            assert isinstance(col["jobs"], list)
            assert "_id" not in col
            for job in col["jobs"]:
                assert "_id" not in job
                assert "id" in job
        for job in d["unassigned"]:
            assert "_id" not in job
            assert not job.get("technician_id"), f"unassigned bucket has assigned job: {job}"

    def test_dispatch_default_date(self, admin_headers):
        # No date query param — should default to today
        r = requests.get(f"{BASE_URL}/api/dispatch", headers=admin_headers, timeout=15)
        assert r.status_code == 200
        d = r.json()
        assert d["date"] == datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def test_dispatch_specific_date(self, admin_headers):
        r = requests.get(f"{BASE_URL}/api/dispatch?date=2020-01-15", headers=admin_headers, timeout=15)
        assert r.status_code == 200
        d = r.json()
        assert d["date"] == "2020-01-15"
        # historic date almost certainly empty
        assert isinstance(d["columns"], list)
        assert isinstance(d["unassigned"], list)

    def test_dispatch_denies_tech(self, tech_headers):
        r = requests.get(f"{BASE_URL}/api/dispatch", headers=tech_headers, timeout=15)
        assert r.status_code == 403, f"tech should be blocked, got {r.status_code}"

    def test_dispatch_denies_customer(self, customer_headers):
        r = requests.get(f"{BASE_URL}/api/dispatch", headers=customer_headers, timeout=15)
        assert r.status_code == 403


class TestDispatchAssign:
    """End-to-end: create unassigned job → GET /dispatch shows it in unassigned bucket
    → PUT /jobs/{id} {technician_id} → GET /dispatch shows it under that tech."""

    @pytest.fixture(scope="class")
    def seed(self, admin_headers):
        # pick a technician + a customer from existing data
        tech_r = requests.get(f"{BASE_URL}/api/technicians", headers=admin_headers, timeout=15)
        assert tech_r.status_code == 200
        techs = tech_r.json()
        assert len(techs) >= 1
        tech = techs[0]

        cust_r = requests.get(f"{BASE_URL}/api/customers", headers=admin_headers, timeout=15)
        assert cust_r.status_code == 200
        custs = cust_r.json()
        assert len(custs) >= 1
        customer = custs[0]

        # Use a fresh future date to isolate the test job in that day's bucket
        today = datetime.now(timezone.utc)
        scheduled = today.replace(year=today.year + 1).strftime("%Y-%m-%dT10:00:00+00:00")
        day = scheduled[:10]

        payload = {
            "customer_id": customer["id"],
            "customer_name": customer.get("name"),
            "title": "TEST_Iter6 Dispatch Assign",
            "service_type": "Weekly Cleaning",
            "scheduled_date": scheduled,
            "status": "pending",
            "address": customer.get("address", ""),
            "price": 0,
            # Intentionally NO technician_id → unassigned
        }
        cr = requests.post(f"{BASE_URL}/api/jobs", json=payload, headers=admin_headers, timeout=15)
        assert cr.status_code == 200, f"create job failed: {cr.status_code} {cr.text}"
        job = cr.json()
        assert "_id" not in job
        return {"job_id": job["id"], "tech_id": tech["id"], "tech_name": tech.get("name"), "day": day}

    def test_created_job_in_unassigned_bucket(self, admin_headers, seed):
        r = requests.get(f"{BASE_URL}/api/dispatch?date={seed['day']}", headers=admin_headers, timeout=15)
        assert r.status_code == 200
        d = r.json()
        ids_unassigned = [j["id"] for j in d["unassigned"]]
        assert seed["job_id"] in ids_unassigned, f"job not in unassigned: {ids_unassigned}"

    def test_assign_moves_job_to_technician_column(self, admin_headers, seed):
        r = requests.put(
            f"{BASE_URL}/api/jobs/{seed['job_id']}",
            json={"technician_id": seed["tech_id"]},
            headers=admin_headers,
            timeout=15,
        )
        assert r.status_code == 200, f"assign failed: {r.status_code} {r.text}"
        body = r.json()
        assert body.get("technician_id") == seed["tech_id"]
        assert "_id" not in body

        # Verify via dispatch
        r2 = requests.get(f"{BASE_URL}/api/dispatch?date={seed['day']}", headers=admin_headers, timeout=15)
        assert r2.status_code == 200
        d = r2.json()
        # Not in unassigned
        assert seed["job_id"] not in [j["id"] for j in d["unassigned"]]
        # In the assigned tech's column
        col = next((c for c in d["columns"] if c["technician_id"] == seed["tech_id"]), None)
        assert col is not None, f"technician column missing for {seed['tech_id']}"
        assert seed["job_id"] in [j["id"] for j in col["jobs"]]


# --------------------------- Work Stream (activity) ---------------------------
class TestActivity:
    def test_activity_admin(self, admin_headers):
        r = requests.get(f"{BASE_URL}/api/activity", headers=admin_headers, timeout=15)
        assert r.status_code == 200
        events = r.json()
        assert isinstance(events, list)
        # Seed data should generate at least a few events (jobs, paid quotes, leads)
        assert len(events) >= 1, "expected at least one activity event"
        allowed_types = {"request", "job_done", "job", "payment", "lead"}
        for e in events:
            for f in ("type", "icon", "title", "detail", "at"):
                assert f in e, f"missing {f} in event {e}"
            assert e["type"] in allowed_types
            assert "_id" not in e
        # Reverse chronological — 'at' non-increasing
        ats = [e["at"] for e in events]
        assert ats == sorted(ats, reverse=True), "activity not reverse-chronological"

    def test_activity_limit(self, admin_headers):
        r = requests.get(f"{BASE_URL}/api/activity?limit=3", headers=admin_headers, timeout=15)
        assert r.status_code == 200
        events = r.json()
        assert len(events) <= 3

    def test_activity_denies_tech(self, tech_headers):
        r = requests.get(f"{BASE_URL}/api/activity", headers=tech_headers, timeout=15)
        assert r.status_code == 403

    def test_activity_denies_customer(self, customer_headers):
        r = requests.get(f"{BASE_URL}/api/activity", headers=customer_headers, timeout=15)
        assert r.status_code == 403


# --------------------------- Reports ---------------------------
class TestReports:
    def test_reports_admin(self, admin_headers):
        r = requests.get(f"{BASE_URL}/api/reports", headers=admin_headers, timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        # top-level KPIs
        for k in ("revenue", "outstanding", "avg_ticket", "completion_rate",
                  "revenue_series", "jobs_by_status", "revenue_by_service",
                  "top_customers", "technician_performance"):
            assert k in d, f"missing key {k} in reports payload"

        # numeric KPIs
        assert isinstance(d["revenue"], (int, float))
        assert isinstance(d["outstanding"], (int, float))
        assert isinstance(d["avg_ticket"], (int, float))
        assert isinstance(d["completion_rate"], int)
        assert 0 <= d["completion_rate"] <= 100

        # 6-month revenue series
        rs = d["revenue_series"]
        assert isinstance(rs, list) and len(rs) == 6
        for point in rs:
            assert "label" in point and "value" in point
            assert isinstance(point["value"], (int, float))

        # Charts arrays are lists of {label, value}
        for k in ("jobs_by_status", "revenue_by_service", "top_customers"):
            for row in d[k]:
                assert "label" in row and "value" in row

        # Technician performance
        for tp in d["technician_performance"]:
            assert "label" in tp
            assert "completed" in tp and isinstance(tp["completed"], int)
            assert "active" in tp and isinstance(tp["active"], int)

    def test_reports_denies_tech(self, tech_headers):
        r = requests.get(f"{BASE_URL}/api/reports", headers=tech_headers, timeout=15)
        assert r.status_code == 403, f"tech should be blocked from /reports (pricing!), got {r.status_code}"

    def test_reports_denies_customer(self, customer_headers):
        r = requests.get(f"{BASE_URL}/api/reports", headers=customer_headers, timeout=15)
        assert r.status_code == 403


# --------------------------- Phase 2 regression ---------------------------
class TestPhase2Regression:
    """Quick smoke to confirm phase-2 endpoints still work admin-only."""

    @pytest.mark.parametrize("path", ["/leads", "/team", "/items", "/payments"])
    def test_admin_200(self, admin_headers, path):
        r = requests.get(f"{BASE_URL}/api{path}", headers=admin_headers, timeout=15)
        assert r.status_code == 200, f"{path}: {r.status_code} {r.text}"

    @pytest.mark.parametrize("path", ["/leads", "/team", "/items", "/payments"])
    def test_tech_403(self, tech_headers, path):
        r = requests.get(f"{BASE_URL}/api{path}", headers=tech_headers, timeout=15)
        assert r.status_code == 403

    @pytest.mark.parametrize("path", ["/leads", "/team", "/items", "/payments"])
    def test_customer_403(self, customer_headers, path):
        r = requests.get(f"{BASE_URL}/api{path}", headers=customer_headers, timeout=15)
        assert r.status_code == 403


# --------------------------- Auth negatives ---------------------------
class TestAuthNegatives:
    @pytest.mark.parametrize("path", ["/dispatch", "/activity", "/reports"])
    def test_no_token(self, path):
        r = requests.get(f"{BASE_URL}/api{path}", timeout=15)
        assert r.status_code in (401, 403)

    @pytest.mark.parametrize("path", ["/dispatch", "/activity", "/reports"])
    def test_bad_token(self, path):
        r = requests.get(
            f"{BASE_URL}/api{path}",
            headers={"Authorization": "Bearer not-a-valid-jwt"},
            timeout=15,
        )
        assert r.status_code == 401
