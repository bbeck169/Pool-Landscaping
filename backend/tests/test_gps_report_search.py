"""Phase G5b addendum · Feb-2026 — customer_name hydration + search
filters across the GPS report surface.

Covers:
* /gps/route + /gps/stops carry ``attributed_customer_name``.
* /admin/gps/attribution/summary + /attribution/job/{id} carry
  customer names on top jobs and attributed stops respectively.
* Deleted-customer graceful path returns null.
* q_customer / q_address filters on /gps/stops, /gps/route,
  /attribution/summary, /admin/gps/export/activity.csv.
* Regex-special chars in filter values are escaped safely.
"""
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
from utils import new_id, now_iso  # noqa: E402


def _login(email, pw="password123"):
    r = requests.post(f"{API}/auth/login",
                      json={"email": email, "password": pw}, timeout=15)
    r.raise_for_status()
    return r.json()["access_token"]


def _admin_headers():
    return {"Authorization": f"Bearer {_login('super@aquaterra.com')}"}


TENANT_TAG = "G5b-search-test"
UID_A = "tech-g5b-search-A"
UID_B = "tech-g5b-search-B"


def _seed_env(tid, day):
    # Ensure the test tech user exists — /gps/stops requires it.
    for uid, name in [(UID_A, "G5b Search Tech A"),
                      (UID_B, "G5b Search Tech B")]:
        if not _sync.users.find_one({"id": uid, "tenant_id": tid}):
            _sync.users.insert_one({
                "id": uid, "tenant_id": tid,
                "email": f"{uid}@aquaterra.com",
                "role": "technician", "name": name,
                "is_active": True,
            })

    # Two customers.
    cust_alice = {"id": new_id(), "tenant_id": tid,
                    "name": f"{TENANT_TAG} Alice Waters",
                    "service_lat": 33.5, "service_lng": -112.0}
    cust_bob   = {"id": new_id(), "tenant_id": tid,
                    "name": f"{TENANT_TAG} Bob Chen",
                    "service_lat": 33.6, "service_lng": -112.1}
    _sync.customers.insert_many([cust_alice, cust_bob])

    # Two jobs, one per customer.
    job_a = {"id": new_id(), "tenant_id": tid, "technician_id": UID_A,
              "customer_id": cust_alice["id"],
              "customer_name": cust_alice["name"],
              "status": "scheduled", "scheduled_date": day,
              "title": f"{TENANT_TAG} JobA",
              "service_type": "pool_clean",
              "lat": 33.5, "lon": -112.0}
    job_b = {"id": new_id(), "tenant_id": tid, "technician_id": UID_A,
              "customer_id": cust_bob["id"],
              "customer_name": cust_bob["name"],
              "status": "scheduled", "scheduled_date": day,
              "title": f"{TENANT_TAG} JobB",
              "service_type": "pool_clean",
              "lat": 33.6, "lon": -112.1}
    _sync.jobs.insert_many([job_a, job_b])

    # Three stops for tech A on ``day`` — one near JobA, one near JobB,
    # one out at sea (no match).
    stops = [
        {"id": new_id(), "tenant_id": tid, "user_id": UID_A,
          "started_at": f"{day}T08:00:00Z",
          "ended_at":   f"{day}T08:10:00Z",
          "duration_s": 600,
          "center_lat": 33.5, "center_lon": -112.0,
          "radius_m": 20, "ping_count": 12,
          "source": "g5b-search", "attribution_status": "pending",
          "address": {"formatted": "42 Main Street, Chandler AZ"}},
        {"id": new_id(), "tenant_id": tid, "user_id": UID_A,
          "started_at": f"{day}T09:00:00Z",
          "ended_at":   f"{day}T09:20:00Z",
          "duration_s": 1200,
          "center_lat": 33.6, "center_lon": -112.1,
          "radius_m": 20, "ping_count": 15,
          "source": "g5b-search", "attribution_status": "pending",
          "address": {"formatted": "9 Oak Road, Peoria AZ"}},
        {"id": new_id(), "tenant_id": tid, "user_id": UID_A,
          "started_at": f"{day}T10:00:00Z",
          "ended_at":   f"{day}T10:10:00Z",
          "duration_s": 600,
          "center_lat": 34.0, "center_lon": -113.5,
          "radius_m": 20, "ping_count": 8,
          "source": "g5b-search", "attribution_status": "pending",
          "address": {"formatted": "Somewhere out west"}},
    ]
    _sync.driver_stops.insert_many(stops)
    return cust_alice, cust_bob, job_a, job_b, stops


@pytest.fixture(autouse=True)
def _cleanup():
    tid = _sync.tenants.find_one({})["id"]
    _sync.jobs.delete_many({"tenant_id": tid,
                              "title": {"$regex": TENANT_TAG}})
    _sync.customers.delete_many({"tenant_id": tid,
                                    "name": {"$regex": TENANT_TAG}})
    _sync.driver_stops.delete_many({"tenant_id": tid,
                                      "source": "g5b-search"})
    # Reset attribution settings to a permissive default so every test
    # starts from a known place (500m threshold, same-day-only,
    # scheduled-status required).
    _sync.stop_attribution_meta.update_one(
        {"tenant_id": tid},
        {"$set": {"tenant_id": tid,
                  "proximity_threshold_m": 500,
                  "same_day_only": True,
                  "require_scheduled_status": True}},
        upsert=True)
    yield
    _sync.jobs.delete_many({"tenant_id": tid,
                              "title": {"$regex": TENANT_TAG}})
    _sync.customers.delete_many({"tenant_id": tid,
                                    "name": {"$regex": TENANT_TAG}})
    _sync.driver_stops.delete_many({"tenant_id": tid,
                                      "source": "g5b-search"})
    _sync.stop_attribution_meta.delete_many({"tenant_id": tid})


class TestCustomerHydration:
    def _tid(self):
        return _sync.tenants.find_one({})["id"]

    def test_gps_stops_carries_customer_name(self):
        tid = self._tid()
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        cust_a, cust_b, job_a, job_b, stops = _seed_env(tid, day)
        # Run the batch to attribute the two near stops.
        requests.patch(f"{API}/admin/gps/attribution/settings",
                       headers=_admin_headers(),
                       json={"proximity_threshold_m": 500,
                             "same_day_only": True,
                             "require_scheduled_status": True},
                       timeout=15)
        requests.post(f"{API}/admin/gps/attribution/run-batch",
                      headers=_admin_headers(), timeout=15)
        # /gps/stops → each stop row has ``attributed_customer_name``
        r = requests.get(
            f"{API}/gps/stops?user_id={UID_A}"
            f"&from={day}T00:00:00Z&to={day}T23:59:59Z",
            headers=_admin_headers(), timeout=15)
        assert r.status_code == 200
        rows = r.json()["stops"]
        by_id = {row["id"]: row for row in rows}
        assert by_id[stops[0]["id"]]["attributed_customer_name"] == cust_a["name"]
        assert by_id[stops[1]["id"]]["attributed_customer_name"] == cust_b["name"]
        assert by_id[stops[2]["id"]]["attributed_customer_name"] is None

    def test_gps_route_carries_customer_name(self):
        tid = self._tid()
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        cust_a, _, _, _, stops = _seed_env(tid, day)
        requests.post(f"{API}/admin/gps/attribution/run-batch",
                      headers=_admin_headers(), timeout=15)
        r = requests.get(
            f"{API}/gps/route?user_id={UID_A}"
            f"&from={day}T00:00:00Z&to={day}T23:59:59Z",
            headers=_admin_headers(), timeout=15)
        assert r.status_code == 200
        route = r.json()
        # Every stop should have ``attributed_customer_name`` echoed
        # (may be null when no match).
        for row in route["stops"]:
            assert "attributed_customer_name" in row
        names = {row["attributed_customer_name"] for row in route["stops"]}
        assert cust_a["name"] in names

    def test_deleted_customer_graceful_null(self):
        tid = self._tid()
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        cust_a, _, _, _, stops = _seed_env(tid, day)
        requests.post(f"{API}/admin/gps/attribution/run-batch",
                      headers=_admin_headers(), timeout=15)
        # Verify attribution first so we hit the deleted-customer path.
        pre = _sync.driver_stops.find_one({"id": stops[0]["id"]})
        assert pre.get("attributed_customer_id") == cust_a["id"]
        # Now nuke the customer.
        _sync.customers.delete_one({"id": cust_a["id"]})
        r = requests.get(
            f"{API}/gps/stops?user_id={UID_A}"
            f"&from={day}T00:00:00Z&to={day}T23:59:59Z",
            headers=_admin_headers(), timeout=15)
        rows = r.json()["stops"]
        row_a = next(r for r in rows if r["id"] == stops[0]["id"])
        # attributed_customer_id remains, name is null.
        assert row_a["attributed_customer_id"] == cust_a["id"]
        assert row_a["attributed_customer_name"] is None

    def test_attribution_summary_includes_customer_names(self):
        tid = self._tid()
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        cust_a, cust_b, job_a, job_b, _ = _seed_env(tid, day)
        requests.post(f"{API}/admin/gps/attribution/run-batch",
                      headers=_admin_headers(), timeout=15)
        r = requests.get(
            f"{API}/admin/gps/attribution/summary?range=day",
            headers=_admin_headers(), timeout=15)
        top = r.json()["top_jobs_by_time_on_site"]
        names = {row["customer_name"] for row in top}
        assert cust_a["name"] in names
        assert cust_b["name"] in names

    def test_job_detail_stops_carry_customer_name(self):
        tid = self._tid()
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        cust_a, _, job_a, _, _ = _seed_env(tid, day)
        requests.post(f"{API}/admin/gps/attribution/run-batch",
                      headers=_admin_headers(), timeout=15)
        r = requests.get(
            f"{API}/admin/gps/attribution/job/{job_a['id']}",
            headers=_admin_headers(), timeout=15)
        body = r.json()
        for s in body["attributed_stops"]:
            assert s.get("attributed_customer_name") == cust_a["name"]


class TestSearchFilters:
    def _tid(self):
        return _sync.tenants.find_one({})["id"]

    def _link(self, day):
        tid = self._tid()
        cust_a, cust_b, ja, jb, stops = _seed_env(tid, day)
        requests.post(f"{API}/admin/gps/attribution/run-batch",
                      headers=_admin_headers(), timeout=15)
        return cust_a, cust_b, ja, jb, stops

    def test_q_customer_filters_gps_stops(self):
        tid = self._tid()
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        cust_a, cust_b, _, _, _ = self._link(day)
        r = requests.get(
            f"{API}/gps/stops?user_id={UID_A}"
            f"&from={day}T00:00:00Z&to={day}T23:59:59Z"
            f"&q_customer=Alice",
            headers=_admin_headers(), timeout=15)
        rows = r.json()["stops"]
        # Only Alice's row remains.
        assert len(rows) == 1
        assert rows[0]["attributed_customer_name"] == cust_a["name"]

    def test_q_address_filters_gps_route(self):
        tid = self._tid()
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self._link(day)
        r = requests.get(
            f"{API}/gps/route?user_id={UID_A}"
            f"&from={day}T00:00:00Z&to={day}T23:59:59Z"
            f"&q_address=Main",
            headers=_admin_headers(), timeout=15)
        stops = r.json()["stops"]
        assert len(stops) == 1
        assert "Main" in stops[0]["address"]["formatted"]

    def test_and_semantics(self):
        tid = self._tid()
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self._link(day)
        # Alice + Oak = no rows (Alice is on Main).
        r = requests.get(
            f"{API}/gps/stops?user_id={UID_A}"
            f"&from={day}T00:00:00Z&to={day}T23:59:59Z"
            f"&q_customer=Alice&q_address=Oak",
            headers=_admin_headers(), timeout=15)
        assert len(r.json()["stops"]) == 0
        # Alice + Main = 1 row.
        r = requests.get(
            f"{API}/gps/stops?user_id={UID_A}"
            f"&from={day}T00:00:00Z&to={day}T23:59:59Z"
            f"&q_customer=Alice&q_address=Main",
            headers=_admin_headers(), timeout=15)
        assert len(r.json()["stops"]) == 1

    def test_regex_chars_escaped(self):
        tid = self._tid()
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self._link(day)
        # Nasty inputs must NOT crash or over-match.
        for junk in [".*", "(", "[", ".{100}", "?:.*"]:
            r = requests.get(
                f"{API}/gps/stops?user_id={UID_A}"
                f"&from={day}T00:00:00Z&to={day}T23:59:59Z"
                f"&q_customer={junk}",
                headers=_admin_headers(), timeout=15)
            assert r.status_code == 200
            # Junk should match zero rows (escaped literal).
            assert len(r.json()["stops"]) == 0

    def test_summary_respects_filters(self):
        tid = self._tid()
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        cust_a, cust_b, ja, jb, _ = self._link(day)
        r = requests.get(
            f"{API}/admin/gps/attribution/summary?range=day"
            f"&q_customer=Alice",
            headers=_admin_headers(), timeout=15)
        top = r.json()["top_jobs_by_time_on_site"]
        # Only Alice's job remains.
        assert all("Alice" in row.get("customer_name") for row in top)
        assert any(row["job_id"] == ja["id"] for row in top)
        assert all(row["job_id"] != jb["id"] for row in top)

    def test_csv_export_carries_column_and_respects_filters(self):
        tid = self._tid()
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        cust_a, _, _, _, _ = self._link(day)
        r = requests.get(
            f"{API}/admin/gps/export/activity.csv"
            f"?from={day}T00:00:00Z&to={day}T23:59:59Z"
            f"&user_id={UID_A}&q_customer=Alice",
            headers=_admin_headers(), timeout=15)
        assert r.status_code == 200
        rows = list(csv.reader(io.StringIO(r.text)))
        header = rows[0]
        assert "attributed_customer_name" in header
        idx = header.index("attributed_customer_name")
        # First body row's customer column matches Alice.
        data_rows = rows[1:]
        assert len(data_rows) >= 1
        assert all("Alice" in row[idx] for row in data_rows)
