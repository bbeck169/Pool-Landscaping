"""Phase G5d · Feb-2026 — Driver scorecard aggregation + API tests."""
from __future__ import annotations

import csv
import io
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = MongoClient(_ENV["MONGO_URL"])[_ENV["DB_NAME"]]
API = os.environ.get("BACKEND_API_URL") or "http://localhost:8001/api"

_BACKEND_DIR = str(Path(__file__).resolve().parents[1])
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)
from utils import new_id  # noqa: E402


def _login(email, pw="password123"):
    r = requests.post(f"{API}/auth/login",
                      json={"email": email, "password": pw}, timeout=15)
    r.raise_for_status()
    return r.json()["access_token"]


def _admin_headers():
    return {"Authorization": f"Bearer {_login('super@aquaterra.com')}"}


def _customer_headers():
    return {"Authorization": f"Bearer {_login('customer@aquaterra.com')}"}


TAG = "G5d-sc-test"
UIDS = {"A": "tech-g5d-alpha", "B": "tech-g5d-bravo",
        "C": "tech-g5d-charlie"}


def _now(): return datetime.now(timezone.utc)


def _seed_users(tid):
    for uid, name, dept in [
        (UIDS["A"], "G5d Alpha Tech", "north"),
        (UIDS["B"], "G5d Bravo Tech", "north"),
        (UIDS["C"], "G5d Charlie Tech", "south"),
    ]:
        if not _sync.users.find_one({"id": uid}):
            _sync.users.insert_one({"id": uid, "tenant_id": tid,
                                     "email": f"{uid}@aquaterra.com",
                                     "role": "technician", "name": name,
                                     "department": dept,
                                     "is_active": True})


def _seed_scenario(tid):
    """Alpha: many stops, high on-time. Bravo: fewer, mixed. Charlie: idle."""
    now = _now()
    day = now.strftime("%Y-%m-%d")
    # Jobs — reused for on-time computation.
    j1 = {"id": new_id(), "tenant_id": tid, "status": "scheduled",
           "scheduled_date": day,
           "scheduled_start": (now - timedelta(hours=5)).isoformat()
                              .replace("+00:00", "Z"),
           "title": f"{TAG} morning", "lat": 33.5, "lon": -112.0,
           "customer_id": "cust-A"}
    j2 = {"id": new_id(), "tenant_id": tid, "status": "scheduled",
           "scheduled_date": day,
           "scheduled_start": (now - timedelta(hours=3)).isoformat()
                              .replace("+00:00", "Z"),
           "title": f"{TAG} noon", "lat": 33.6, "lon": -112.1,
           "customer_id": "cust-B"}
    _sync.jobs.insert_many([j1, j2])

    # Alpha: 4 stops, 2 attributed on-time.
    a_stops = [
        {"id": new_id(), "tenant_id": tid, "user_id": UIDS["A"],
          "started_at": (now - timedelta(hours=5, minutes=5)).isoformat()
                          .replace("+00:00", "Z"),
          "ended_at":   (now - timedelta(hours=4, minutes=40)).isoformat()
                          .replace("+00:00", "Z"),
          "duration_s": 1500, "center_lat": 33.5, "center_lon": -112.0,
          "radius_m": 20, "ping_count": 30, "source": TAG,
          "attribution_status": "auto_linked",
          "attributed_job_id": j1["id"], "attributed_customer_id": "cust-A"},
        {"id": new_id(), "tenant_id": tid, "user_id": UIDS["A"],
          "started_at": (now - timedelta(hours=3, minutes=2)).isoformat()
                          .replace("+00:00", "Z"),
          "ended_at":   (now - timedelta(hours=2, minutes=30)).isoformat()
                          .replace("+00:00", "Z"),
          "duration_s": 1920, "center_lat": 33.6, "center_lon": -112.1,
          "radius_m": 20, "ping_count": 25, "source": TAG,
          "attribution_status": "auto_linked",
          "attributed_job_id": j2["id"], "attributed_customer_id": "cust-B"},
        {"id": new_id(), "tenant_id": tid, "user_id": UIDS["A"],
          "started_at": (now - timedelta(hours=1, minutes=30)).isoformat()
                          .replace("+00:00", "Z"),
          "ended_at":   (now - timedelta(hours=1)).isoformat()
                          .replace("+00:00", "Z"),
          "duration_s": 1800, "center_lat": 33.7, "center_lon": -112.2,
          "radius_m": 20, "ping_count": 15, "source": TAG,
          "attribution_status": "no_match"},
        {"id": new_id(), "tenant_id": tid, "user_id": UIDS["A"],
          "started_at": (now - timedelta(minutes=30)).isoformat()
                          .replace("+00:00", "Z"),
          "ended_at":   (now - timedelta(minutes=10)).isoformat()
                          .replace("+00:00", "Z"),
          "duration_s": 1200, "center_lat": 33.7, "center_lon": -112.2,
          "radius_m": 20, "ping_count": 10, "source": TAG,
          "attribution_status": "no_match"},
    ]

    # Bravo: 1 stop, 1 attributed.
    b_stops = [
        {"id": new_id(), "tenant_id": tid, "user_id": UIDS["B"],
          "started_at": (now - timedelta(hours=4, minutes=50)).isoformat()
                          .replace("+00:00", "Z"),
          "ended_at":   (now - timedelta(hours=4, minutes=20)).isoformat()
                          .replace("+00:00", "Z"),
          "duration_s": 1800, "center_lat": 33.5, "center_lon": -112.0,
          "radius_m": 20, "ping_count": 20, "source": TAG,
          "attribution_status": "auto_linked",
          "attributed_job_id": j1["id"], "attributed_customer_id": "cust-A"},
    ]

    # Charlie: 1 huge idle stop → penalty.
    c_stops = [
        {"id": new_id(), "tenant_id": tid, "user_id": UIDS["C"],
          "started_at": (now - timedelta(hours=6)).isoformat()
                          .replace("+00:00", "Z"),
          "ended_at":   now.isoformat().replace("+00:00", "Z"),
          "duration_s": 6 * 3600, "center_lat": 33.4, "center_lon": -111.9,
          "radius_m": 20, "ping_count": 12, "source": TAG,
          "attribution_status": "no_match"},
    ]
    _sync.driver_stops.insert_many(a_stops + b_stops + c_stops)

    # Seed a few pings for each so days_active + estimated_miles fire.
    def _ping(uid, minutes_ago, lat, lon):
        return {"id": new_id(), "tenant_id": tid, "user_id": uid,
                "lat": lat, "lon": lon, "accuracy_m": 10.0,
                "source": "foreground",
                "captured_at": (now - timedelta(minutes=minutes_ago))
                                 .isoformat().replace("+00:00", "Z")}
    _sync.gps_pings.insert_many([
        _ping(UIDS["A"], 300, 33.50, -112.00),
        _ping(UIDS["A"], 299, 33.51, -112.01),
        _ping(UIDS["A"], 180, 33.60, -112.10),
        _ping(UIDS["B"], 290, 33.50, -112.00),
        _ping(UIDS["B"], 289, 33.502, -112.00),
        _ping(UIDS["C"], 360, 33.40, -111.90),
        _ping(UIDS["C"], 100, 33.40, -111.90),
    ])
    return j1, j2


@pytest.fixture(autouse=True)
def _cleanup():
    tid = _sync.tenants.find_one({})["id"]
    _seed_users(tid)
    _sync.jobs.delete_many({"tenant_id": tid,
                              "title": {"$regex": TAG}})
    _sync.driver_stops.delete_many({"tenant_id": tid, "source": TAG})
    _sync.gps_pings.delete_many({"tenant_id": tid,
                                   "user_id": {"$in": list(UIDS.values())}})
    _sync.scorecard_cache.delete_many({})
    yield
    _sync.jobs.delete_many({"tenant_id": tid,
                              "title": {"$regex": TAG}})
    _sync.driver_stops.delete_many({"tenant_id": tid, "source": TAG})
    _sync.gps_pings.delete_many({"tenant_id": tid,
                                   "user_id": {"$in": list(UIDS.values())}})
    _sync.scorecard_cache.delete_many({})


class TestLeaderboard:

    def _tid(self):
        return _sync.tenants.find_one({})["id"]

    def test_ranking_and_metrics(self):
        tid = self._tid()
        _seed_scenario(tid)
        r = requests.get(
            f"{API}/admin/gps/scorecard/leaderboard?range=this_week",
            headers=_admin_headers(), timeout=15)
        assert r.status_code == 200
        body = r.json()
        alpha = next(x for x in body["rows"] if x["user_id"] == UIDS["A"])
        bravo = next(x for x in body["rows"] if x["user_id"] == UIDS["B"])
        charlie = next(x for x in body["rows"] if x["user_id"] == UIDS["C"])
        # Alpha's 4 stops + 2 linked to different jobs.
        assert alpha["metrics"]["stops_count"] == 4
        assert alpha["metrics"]["unique_jobs_attributed"] == 2
        assert alpha["metrics"]["unique_customers_attributed"] == 2
        assert alpha["metrics"]["on_time_arrival_rate"] == 1.0
        assert alpha["metrics"]["days_active"] >= 1
        # Bravo: 1 attributed → coverage 1.0.
        assert bravo["metrics"]["attribution_coverage"] == 1.0
        # Charlie: 6-hr idle stop triggers idle penalty.
        assert charlie["metrics"]["idle_penalty"] > 0
        # Alpha and Bravo should both outrank Charlie (idle-heavy).
        # Other pre-existing tenant technicians may sit in between —
        # we only care about our three's relative order.
        assert alpha["rank"] < charlie["rank"]
        assert bravo["rank"] < charlie["rank"]
        assert alpha["score"] > charlie["score"]
        assert bravo["score"] > charlie["score"]

    def test_department_filter(self):
        tid = self._tid()
        _seed_scenario(tid)
        r = requests.get(
            f"{API}/admin/gps/scorecard/leaderboard?range=this_week"
            f"&department=south",
            headers=_admin_headers(), timeout=15)
        rows = r.json()["rows"]
        uids = [x["user_id"] for x in rows]
        assert UIDS["C"] in uids
        assert UIDS["A"] not in uids
        assert UIDS["B"] not in uids

    def test_customer_forbidden(self):
        r = requests.get(
            f"{API}/admin/gps/scorecard/leaderboard?range=this_week",
            headers=_customer_headers(), timeout=15)
        assert r.status_code == 403

    def test_empty_state_returns_shape(self):
        r = requests.get(
            f"{API}/admin/gps/scorecard/leaderboard?range=this_week"
            f"&department=nonexistent-dept",
            headers=_admin_headers(), timeout=15)
        assert r.status_code == 200
        assert r.json()["rows"] == []

    def test_custom_range_needs_bounds(self):
        r = requests.get(
            f"{API}/admin/gps/scorecard/leaderboard?range=custom",
            headers=_admin_headers(), timeout=15)
        assert r.status_code == 422


class TestUserDetail:

    def _tid(self):
        return _sync.tenants.find_one({})["id"]

    def test_returns_trend_of_8_weeks(self):
        tid = self._tid()
        _seed_scenario(tid)
        r = requests.get(
            f"{API}/admin/gps/scorecard/user/{UIDS['A']}?range=this_week",
            headers=_admin_headers(), timeout=30)
        assert r.status_code == 200
        b = r.json()
        assert "row" in b and "trend" in b
        assert len(b["trend"]) == 8
        for entry in b["trend"]:
            assert 0 <= entry["score"] <= 100

    def test_404_for_unknown_user(self):
        r = requests.get(
            f"{API}/admin/gps/scorecard/user/does-not-exist?range=this_week",
            headers=_admin_headers(), timeout=15)
        assert r.status_code == 404


class TestCsvExport:

    def _tid(self):
        return _sync.tenants.find_one({})["id"]

    def test_header_and_rows(self):
        tid = self._tid()
        _seed_scenario(tid)
        r = requests.get(
            f"{API}/admin/gps/scorecard/export.csv?range=this_week",
            headers=_admin_headers(), timeout=15)
        assert r.status_code == 200
        rows = list(csv.reader(io.StringIO(r.text)))
        assert rows[0][0] == "rank"
        assert "unique_jobs_attributed" in rows[0]
        assert "idle_penalty" in rows[0]
        # At least our three seeded techs appear.
        uids = [r_[1] for r_ in rows[1:]]
        assert UIDS["A"] in uids
        assert UIDS["B"] in uids
        assert UIDS["C"] in uids

    def test_customer_cannot_export(self):
        r = requests.get(
            f"{API}/admin/gps/scorecard/export.csv?range=this_week",
            headers=_customer_headers(), timeout=15)
        assert r.status_code == 403
