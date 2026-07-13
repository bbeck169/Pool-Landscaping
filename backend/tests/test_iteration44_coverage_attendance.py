"""Tests for iteration 44: Route Coverage + Attendance (clock-in/out) features."""
import os
from datetime import datetime, date, timedelta
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

# Base URL from Expo public backend URL (frontend/.env)
_FE_ENV = dotenv_values(Path(__file__).resolve().parents[2] / "frontend" / ".env")
BASE_URL = (_FE_ENV.get("EXPO_PUBLIC_BACKEND_URL") or os.environ.get("EXPO_BACKEND_URL") or "").rstrip("/")
assert BASE_URL, "EXPO_PUBLIC_BACKEND_URL not set"

_BE_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
MONGO_URL = _BE_ENV.get("MONGO_URL")
DB_NAME = _BE_ENV.get("DB_NAME")

ADMIN = ("admin@aquaterra.com", "password123")
TECH = ("mike@aquaterra.com", "password123")
CUST = ("customer@aquaterra.com", "password123")


# ----- helpers -----
def _login(email, password):
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": password}, timeout=15)
    assert r.status_code == 200, f"login failed for {email}: {r.status_code} {r.text}"
    d = r.json()
    return d["access_token"], d["user"]


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _mongo():
    return MongoClient(MONGO_URL)[DB_NAME]


# ---- shared fixtures ----
@pytest.fixture(scope="module")
def admin_ctx():
    tok, u = _login(*ADMIN)
    return {"token": tok, "user": u, "hdr": _hdr(tok)}


@pytest.fixture(scope="module")
def tech_ctx():
    tok, u = _login(*TECH)
    return {"token": tok, "user": u, "hdr": _hdr(tok)}


@pytest.fixture(scope="module")
def cust_ctx():
    tok, u = _login(*CUST)
    return {"token": tok, "user": u, "hdr": _hdr(tok)}


@pytest.fixture(scope="module")
def technicians(admin_ctx):
    r = requests.get(f"{BASE_URL}/api/technicians", headers=admin_ctx["hdr"], timeout=15)
    assert r.status_code == 200
    techs = r.json()
    assert len(techs) >= 2, "Need at least 2 techs to test coverage"
    return techs


@pytest.fixture(scope="module")
def mike(technicians):
    m = next((t for t in technicians if "mike" in t.get("name", "").lower() or "mike" in (t.get("email") or "").lower()), None)
    assert m is not None, "Mike not found among technicians"
    return m


@pytest.fixture(scope="module")
def other_tech(technicians, mike):
    o = next((t for t in technicians if t["id"] != mike["id"]), None)
    assert o is not None
    return o


# ---------- Coverage feature ----------
class TestCoverage:
    """POST /api/coverage, GET /api/coverage/active, POST /api/coverage/{id}/revert"""

    @pytest.fixture(autouse=True)
    def _seed_job(self, admin_ctx, mike):
        """Create a pending job assigned to Mike on today's date (a weekday in current week)."""
        # anchor: today; if Sunday, roll to Monday to ensure it's in current-week window
        d = date.today()
        if d.weekday() == 6:  # Sunday
            d = d + timedelta(days=1)
        self.anchor = d.isoformat()

        # need a customer to create job
        cr = requests.get(f"{BASE_URL}/api/customers", headers=admin_ctx["hdr"], timeout=15)
        assert cr.status_code == 200
        customers = cr.json()
        cust = customers[0]

        payload = {
            "title": "TEST_coverage_job",
            "customer_id": cust["id"],
            "technician_id": mike["id"],
            "service_type": "Pool Cleaning",
            "scheduled_date": self.anchor,
            "status": "pending",
            "price": 50.0,
        }
        j = requests.post(f"{BASE_URL}/api/jobs", json=payload, headers=admin_ctx["hdr"], timeout=15)
        assert j.status_code in (200, 201), f"job create failed: {j.status_code} {j.text}"
        self.job_id = j.json()["id"]
        yield
        # teardown: purge job + coverage referencing it
        db = _mongo()
        db.jobs.delete_one({"id": self.job_id})
        db.route_coverage.delete_many({"job_ids": self.job_id})
        db.notifications.delete_many({"$or": [{"title": {"$regex": "^Route "}}, {"title": {"$regex": "^Coverage"}}]})

    def test_same_source_target_returns_400(self, admin_ctx, mike):
        r = requests.post(f"{BASE_URL}/api/coverage",
                          json={"source_technician_id": mike["id"], "target_technician_id": mike["id"],
                                "scope": "day", "date": self.anchor},
                          headers=admin_ctx["hdr"], timeout=15)
        assert r.status_code == 400
        assert "different" in r.text.lower()

    def test_technician_forbidden(self, tech_ctx, mike, other_tech):
        r = requests.post(f"{BASE_URL}/api/coverage",
                          json={"source_technician_id": mike["id"], "target_technician_id": other_tech["id"],
                                "scope": "day", "date": self.anchor},
                          headers=tech_ctx["hdr"], timeout=15)
        assert r.status_code == 403

    def test_customer_forbidden(self, cust_ctx, mike, other_tech):
        r = requests.post(f"{BASE_URL}/api/coverage",
                          json={"source_technician_id": mike["id"], "target_technician_id": other_tech["id"],
                                "scope": "day", "date": self.anchor},
                          headers=cust_ctx["hdr"], timeout=15)
        assert r.status_code == 403

    def test_no_open_stops_400(self, admin_ctx, mike, other_tech):
        # Use a date far in the future when Mike has no jobs
        future = (date.today() + timedelta(days=180)).isoformat()
        r = requests.post(f"{BASE_URL}/api/coverage",
                          json={"source_technician_id": mike["id"], "target_technician_id": other_tech["id"],
                                "scope": "day", "date": future},
                          headers=admin_ctx["hdr"], timeout=15)
        assert r.status_code == 400
        assert "no open stops" in r.text.lower()

    def test_create_move_verify_active_and_revert(self, admin_ctx, mike, other_tech):
        # Create day coverage
        r = requests.post(f"{BASE_URL}/api/coverage",
                          json={"source_technician_id": mike["id"], "target_technician_id": other_tech["id"],
                                "scope": "day", "date": self.anchor},
                          headers=admin_ctx["hdr"], timeout=15)
        assert r.status_code == 200, f"coverage create: {r.status_code} {r.text}"
        cov = r.json()
        assert cov["source_technician_id"] == mike["id"]
        assert cov["target_technician_id"] == other_tech["id"]
        assert cov["scope"] == "day"
        assert cov["job_count"] >= 1
        assert cov["active"] is True
        # week_end must be a Saturday
        we = date.fromisoformat(cov["week_end"])
        assert we.weekday() == 5, f"week_end should be Saturday, got weekday={we.weekday()}"
        cov_id = cov["id"]

        # Verify job was moved
        jr = requests.get(f"{BASE_URL}/api/jobs/{self.job_id}", headers=admin_ctx["hdr"], timeout=15)
        assert jr.status_code == 200
        job = jr.json()
        assert job["technician_id"] == other_tech["id"]
        assert job.get("original_technician_id") == mike["id"]
        assert job.get("coverage_id") == cov_id

        # Verify active listing
        ar = requests.get(f"{BASE_URL}/api/coverage/active", headers=admin_ctx["hdr"], timeout=15)
        assert ar.status_code == 200
        active_ids = [c["id"] for c in ar.json()]
        assert cov_id in active_ids

        # Notifications for both techs (stored keyed by user_id, not technician_id)
        db = _mongo()
        src_user = db.users.find_one({"technician_id": mike["id"], "role": "technician"})
        tgt_user = db.users.find_one({"technician_id": other_tech["id"], "role": "technician"})
        if src_user:
            nsrc = db.notifications.count_documents({"user_id": src_user["id"], "title": {"$regex": "reassigned", "$options": "i"}})
            assert nsrc >= 1, "source tech should receive reassigned notification"
        if tgt_user:
            ntgt = db.notifications.count_documents({"user_id": tgt_user["id"], "title": {"$regex": "coverage assigned", "$options": "i"}})
            assert ntgt >= 1, "target tech should receive coverage-assigned notification"

        # Revert
        rv = requests.post(f"{BASE_URL}/api/coverage/{cov_id}/revert", headers=admin_ctx["hdr"], timeout=15)
        assert rv.status_code == 200
        assert rv.json().get("ok") is True

        # Job should be back on Mike
        jr2 = requests.get(f"{BASE_URL}/api/jobs/{self.job_id}", headers=admin_ctx["hdr"], timeout=15)
        job2 = jr2.json()
        assert job2["technician_id"] == mike["id"]
        assert "coverage_id" not in job2 or job2.get("coverage_id") in (None, "")

        # Second revert returns 400 (already reverted)
        rv2 = requests.post(f"{BASE_URL}/api/coverage/{cov_id}/revert", headers=admin_ctx["hdr"], timeout=15)
        assert rv2.status_code == 400

    def test_week_scope_sets_week_end_saturday(self, admin_ctx, mike, other_tech):
        r = requests.post(f"{BASE_URL}/api/coverage",
                          json={"source_technician_id": mike["id"], "target_technician_id": other_tech["id"],
                                "scope": "week", "date": self.anchor},
                          headers=admin_ctx["hdr"], timeout=15)
        assert r.status_code == 200, f"week coverage create: {r.status_code} {r.text}"
        cov = r.json()
        we = date.fromisoformat(cov["week_end"])
        assert we.weekday() == 5
        # cleanup: revert
        requests.post(f"{BASE_URL}/api/coverage/{cov['id']}/revert", headers=admin_ctx["hdr"], timeout=15)


# ---------- Attendance feature ----------
class TestAttendance:
    """POST /api/attendance/clock-in|clock-out, GET today, GET report"""

    @pytest.fixture(autouse=True)
    def _clean_ts(self, tech_ctx):
        db = _mongo()
        tid = tech_ctx["user"].get("technician_id")
        today = date.today().isoformat()
        db.timesheets.delete_many({"technician_id": tid, "date": today})
        yield
        db.timesheets.delete_many({"technician_id": tid, "date": today})

    def test_today_before_clockin(self, tech_ctx):
        r = requests.get(f"{BASE_URL}/api/attendance/today", headers=tech_ctx["hdr"], timeout=15)
        assert r.status_code == 200
        d = r.json()
        assert d["clocked_in"] is False
        assert d["clocked_out"] is False
        assert d["timesheet"] is None

    def test_customer_forbidden(self, cust_ctx):
        r = requests.post(f"{BASE_URL}/api/attendance/clock-in", json={"lat": 33.0, "lng": -112.0},
                          headers=cust_ctx["hdr"], timeout=15)
        assert r.status_code == 403

    def test_admin_forbidden_clock_in(self, admin_ctx):
        r = requests.post(f"{BASE_URL}/api/attendance/clock-in", json={"lat": 33.0, "lng": -112.0},
                          headers=admin_ctx["hdr"], timeout=15)
        assert r.status_code == 403

    def test_clockout_before_clockin_400(self, tech_ctx):
        r = requests.post(f"{BASE_URL}/api/attendance/clock-out", json={"lat": 33.0, "lng": -112.0},
                          headers=tech_ctx["hdr"], timeout=15)
        assert r.status_code == 400

    def test_full_punch_flow(self, tech_ctx):
        # Clock in
        r = requests.post(f"{BASE_URL}/api/attendance/clock-in", json={"lat": 33.6, "lng": -112.3},
                          headers=tech_ctx["hdr"], timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["clock_in_lat"] == 33.6
        assert d["clock_in_lng"] == -112.3
        assert d["clock_in_at"] is not None
        assert d["clock_out_at"] is None

        # Duplicate clock-in blocked
        r2 = requests.post(f"{BASE_URL}/api/attendance/clock-in", json={"lat": 33.6, "lng": -112.3},
                           headers=tech_ctx["hdr"], timeout=15)
        assert r2.status_code == 400

        # GET today reflects state
        t = requests.get(f"{BASE_URL}/api/attendance/today", headers=tech_ctx["hdr"], timeout=15)
        assert t.status_code == 200
        td = t.json()
        assert td["clocked_in"] is True and td["clocked_out"] is False

        # Clock out
        o = requests.post(f"{BASE_URL}/api/attendance/clock-out", json={"lat": 33.61, "lng": -112.31},
                          headers=tech_ctx["hdr"], timeout=15)
        assert o.status_code == 200, o.text
        od = o.json()
        assert od["clock_out_at"] is not None
        assert od["clock_out_lat"] == 33.61
        assert od["hours"] is not None and od["hours"] >= 0

        # Second clock-out blocked
        o2 = requests.post(f"{BASE_URL}/api/attendance/clock-out", json={"lat": 33.6, "lng": -112.3},
                           headers=tech_ctx["hdr"], timeout=15)
        assert o2.status_code == 400

    def test_admin_report(self, admin_ctx, tech_ctx):
        # Ensure there's at least one row
        requests.post(f"{BASE_URL}/api/attendance/clock-in", json={"lat": 33.0, "lng": -112.0},
                      headers=tech_ctx["hdr"], timeout=15)
        requests.post(f"{BASE_URL}/api/attendance/clock-out", json={"lat": 33.0, "lng": -112.0},
                      headers=tech_ctx["hdr"], timeout=15)

        r = requests.get(f"{BASE_URL}/api/attendance/report", headers=admin_ctx["hdr"], timeout=15)
        assert r.status_code == 200
        d = r.json()
        assert "count" in d and "total_hours" in d and "rows" in d
        assert isinstance(d["rows"], list)
        assert d["count"] >= 1

    def test_report_forbidden_for_non_admin(self, tech_ctx, cust_ctx):
        r1 = requests.get(f"{BASE_URL}/api/attendance/report", headers=tech_ctx["hdr"], timeout=15)
        r2 = requests.get(f"{BASE_URL}/api/attendance/report", headers=cust_ctx["hdr"], timeout=15)
        assert r1.status_code == 403
        assert r2.status_code == 403


def test_revert_expired_coverage_function_exists():
    from routers import coverage as cov_mod
    assert callable(getattr(cov_mod, "revert_expired_coverage", None))
