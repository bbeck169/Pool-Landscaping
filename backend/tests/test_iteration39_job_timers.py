"""Backend tests for the automated GPS-arrival job timer feature (iteration 39).

Coverage:
 - POST /api/jobs/{id}/arrive: auto-start (gps_arrival), idempotent, role guards.
 - PUT /api/jobs/{id} status=completed → auto-stop (job_completed) with duration.
 - GET /api/reports/job-timers: admin only, filtering by technician_id / customer_id / q.
"""
import os
import time
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values

_ENV = dotenv_values(Path(__file__).resolve().parents[2] / "frontend" / ".env")
BASE_URL = (_ENV.get("EXPO_PUBLIC_BACKEND_URL") or os.environ.get("EXPO_BACKEND_URL") or "").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN = ("admin@aquaterra.com", "password123")
TECH = ("mike@aquaterra.com", "password123")
CUST = ("customer@aquaterra.com", "password123")


def _login(email, password):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=30)
    assert r.status_code == 200, f"login failed for {email}: {r.status_code} {r.text}"
    j = r.json()
    return j.get("access_token") or j.get("token")


def _h(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


# ------------------- fixtures -------------------
@pytest.fixture(scope="module")
def tokens():
    return {"admin": _login(*ADMIN), "tech": _login(*TECH), "customer": _login(*CUST)}


@pytest.fixture()
def fresh_job(tokens):
    """Create a fresh job assigned to mike (technician) so tests are isolated."""
    admin = tokens["admin"]
    techs = requests.get(f"{API}/technicians", headers=_h(admin), timeout=30).json()
    mike = next((t for t in techs if "mike" in (t.get("name", "") + t.get("email", "")).lower()), techs[0])
    customers = requests.get(f"{API}/customers", headers=_h(admin), timeout=30).json()
    cust = customers[0]
    body = {
        "title": "TEST_ Timer Auto-Start Job",
        "customer_id": cust["id"],
        "technician_id": mike["id"],
        "service_type": "Pool Cleaning",
        "address": cust.get("address") or "123 Test St",
        "status": "pending",
        "price": 100.0,
    }
    r = requests.post(f"{API}/jobs", headers=_h(admin), json=body, timeout=30)
    assert r.status_code == 200, r.text
    job = r.json()
    yield job, mike, cust
    try:
        requests.delete(f"{API}/jobs/{job['id']}", headers=_h(admin), timeout=30)
    except Exception:
        pass


# ------------------- arrive endpoint -------------------
class TestArrive:
    def test_customer_forbidden(self, tokens, fresh_job):
        job, *_ = fresh_job
        r = requests.post(f"{API}/jobs/{job['id']}/arrive", headers=_h(tokens["customer"]),
                          json={"lat": 33.7, "lng": -112.3}, timeout=30)
        assert r.status_code == 403

    def test_unassigned_tech_forbidden(self, tokens, fresh_job):
        # Reassign this job away from mike, then verify mike gets 403.
        admin = tokens["admin"]
        job, mike, _ = fresh_job
        techs = requests.get(f"{API}/technicians", headers=_h(admin), timeout=30).json()
        other = next((t for t in techs if t["id"] != mike["id"]), None)
        if not other:
            pytest.skip("Need at least 2 technicians to test unassigned-tech guard")
        requests.put(f"{API}/jobs/{job['id']}", headers=_h(admin),
                     json={"technician_id": other["id"]}, timeout=30)
        r = requests.post(f"{API}/jobs/{job['id']}/arrive", headers=_h(tokens["tech"]),
                          json={"lat": 33.7, "lng": -112.3}, timeout=30)
        assert r.status_code == 403

    def test_arrive_starts_timer_and_is_idempotent(self, tokens, fresh_job):
        job, *_ = fresh_job
        tech = tokens["tech"]
        payload = {"lat": 33.7, "lng": -112.3, "site_lat": 33.7001, "site_lng": -112.3001}
        r1 = requests.post(f"{API}/jobs/{job['id']}/arrive", headers=_h(tech), json=payload, timeout=30)
        assert r1.status_code == 200, r1.text
        d1 = r1.json()
        assert d1.get("started") is True
        assert d1.get("already_running") is False
        assert d1.get("timer_started_at")

        # Verify persistence via GET
        got = requests.get(f"{API}/jobs/{job['id']}", headers=_h(tech), timeout=30).json()
        assert got.get("timer_started_at") == d1["timer_started_at"]
        assert got.get("timer_start_method") == "gps_arrival"
        assert got.get("status") == "in_progress"

        # Second call is idempotent
        r2 = requests.post(f"{API}/jobs/{job['id']}/arrive", headers=_h(tech), json=payload, timeout=30)
        assert r2.status_code == 200
        d2 = r2.json()
        assert d2.get("already_running") is True
        assert d2.get("timer_started_at") == d1["timer_started_at"]


# ------------------- auto-stop on completion -------------------
class TestAutoStop:
    def test_status_completed_auto_stops_timer(self, tokens, fresh_job):
        admin = tokens["admin"]
        tech = tokens["tech"]
        job, *_ = fresh_job
        # start timer
        requests.post(f"{API}/jobs/{job['id']}/arrive", headers=_h(tech),
                      json={"lat": 33.7, "lng": -112.3}, timeout=30)
        time.sleep(1.2)
        # complete
        r = requests.put(f"{API}/jobs/{job['id']}", headers=_h(admin),
                        json={"status": "completed"}, timeout=60)
        assert r.status_code == 200, r.text
        got = requests.get(f"{API}/jobs/{job['id']}", headers=_h(admin), timeout=30).json()
        assert got.get("timer_stopped_at"), "timer_stopped_at not set on completion"
        assert (got.get("timer_duration_seconds") or 0) > 0
        assert got.get("timer_stop_method") == "job_completed"

    def test_manual_start_stop_endpoints_absent(self, tokens, fresh_job):
        """There must be NO manual start/stop endpoints."""
        job, *_ = fresh_job
        admin = tokens["admin"]
        for path in (f"/jobs/{job['id']}/timer/start", f"/jobs/{job['id']}/timer/stop",
                     f"/jobs/{job['id']}/start-timer", f"/jobs/{job['id']}/stop-timer"):
            r = requests.post(f"{API}{path}", headers=_h(admin), json={}, timeout=15)
            assert r.status_code in (404, 405), f"Manual endpoint {path} unexpectedly present: {r.status_code}"


# ------------------- admin report -------------------
class TestJobTimersReport:
    def test_technician_forbidden(self, tokens):
        r = requests.get(f"{API}/reports/job-timers", headers=_h(tokens["tech"]), timeout=30)
        assert r.status_code == 403

    def test_customer_forbidden(self, tokens):
        r = requests.get(f"{API}/reports/job-timers", headers=_h(tokens["customer"]), timeout=30)
        assert r.status_code == 403

    def test_admin_shape_and_filters(self, tokens, fresh_job):
        admin = tokens["admin"]
        tech = tokens["tech"]
        job, mike, cust = fresh_job
        # start a timer so this job shows up in report
        requests.post(f"{API}/jobs/{job['id']}/arrive", headers=_h(tech),
                      json={"lat": 33.7, "lng": -112.3}, timeout=30)

        r = requests.get(f"{API}/reports/job-timers", headers=_h(admin), timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        assert set(["count", "total_seconds", "rows"]).issubset(data.keys())
        assert isinstance(data["rows"], list)
        row = next((x for x in data["rows"] if x["job_id"] == job["id"]), None)
        assert row is not None, "created job missing from report"
        # row shape
        for k in ("customer_name", "technician_name", "duration_seconds", "running"):
            assert k in row, f"row missing key: {k}"
        assert row["running"] is True
        assert row["technician_name"]

        # technician_id filter
        r2 = requests.get(f"{API}/reports/job-timers", headers=_h(admin),
                          params={"technician_id": mike["id"]}, timeout=30)
        assert r2.status_code == 200
        assert all(x["technician_id"] == mike["id"] for x in r2.json()["rows"])
        assert any(x["job_id"] == job["id"] for x in r2.json()["rows"])

        # customer_id filter
        r3 = requests.get(f"{API}/reports/job-timers", headers=_h(admin),
                          params={"customer_id": cust["id"]}, timeout=30)
        assert r3.status_code == 200
        assert all(x["customer_id"] == cust["id"] for x in r3.json()["rows"])

        # free-text q filter (customer name substring)
        needle = (cust.get("name") or "").split()[0]
        if needle:
            r4 = requests.get(f"{API}/reports/job-timers", headers=_h(admin),
                              params={"q": needle}, timeout=30)
            assert r4.status_code == 200
            for x in r4.json()["rows"]:
                hay = f"{x['customer_name']} {x['technician_name']} {x['address']} {x['service_type']}".lower()
                assert needle.lower() in hay
