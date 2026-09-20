"""Phase G5b · Feb-2026 — Attribution admin API integration tests.

Hits the live backend and validates RBAC + endpoint contracts.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient
from tests._shared_mongo import (
    shared_client as _shared_client,
    shared_db as _shared_db,
)


_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = _shared_db()
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


def _customer_headers():
    return {"Authorization": f"Bearer {_login('customer@aquaterra.com')}"}


TENANT_TAG = "G5b-api-test"


def _mk_stop(tid, uid, lat, lon, dur=600, status="pending"):
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return {
        "id": new_id(), "tenant_id": tid, "user_id": uid,
        "started_at": f"{day}T10:00:00Z",
        "ended_at": f"{day}T10:{(dur // 60):02d}:00Z",
        "duration_s": dur, "center_lat": lat, "center_lon": lon,
        "radius_m": 40, "ping_count": 13, "source": "batch",
        "attribution_status": status,
    }


def _mk_job(tid, uid, lat, lon, status="scheduled"):
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return {
        "id": new_id(), "tenant_id": tid, "technician_id": uid,
        "status": status, "scheduled_date": day,
        "title": f"{TENANT_TAG} job", "service_type": "pool_clean",
        "lat": lat, "lon": lon,
    }


@pytest.fixture(autouse=True)
def _cleanup():
    tid = _sync.tenants.find_one({})["id"]
    _sync.jobs.delete_many({"tenant_id": tid, "title": {"$regex": TENANT_TAG}})
    _sync.driver_stops.delete_many({"tenant_id": tid, "source": "batch",
                                     "ping_count": 13})
    _sync.stop_attribution_meta.delete_many({"tenant_id": tid})
    _sync.audits.delete_many({"tenant_id": tid,
                                "kind": "stop_attribution_changed"})
    yield
    _sync.jobs.delete_many({"tenant_id": tid, "title": {"$regex": TENANT_TAG}})
    _sync.driver_stops.delete_many({"tenant_id": tid, "source": "batch",
                                     "ping_count": 13})
    _sync.stop_attribution_meta.delete_many({"tenant_id": tid})
    _sync.audits.delete_many({"tenant_id": tid,
                                "kind": "stop_attribution_changed"})


class TestSettings:

    def test_get_defaults(self):
        r = requests.get(f"{API}/admin/gps/attribution/settings",
                         headers=_admin_headers(), timeout=15)
        assert r.status_code == 200
        b = r.json()
        assert b["proximity_threshold_m"] == 100
        assert b["same_day_only"] is True

    def test_patch_and_persist(self):
        r = requests.patch(f"{API}/admin/gps/attribution/settings",
                           headers=_admin_headers(),
                           json={"proximity_threshold_m": 250}, timeout=15)
        assert r.status_code == 200
        assert r.json()["proximity_threshold_m"] == 250

    def test_out_of_range_rejected(self):
        r = requests.patch(f"{API}/admin/gps/attribution/settings",
                           headers=_admin_headers(),
                           json={"proximity_threshold_m": 9}, timeout=15)
        assert r.status_code == 422
        r2 = requests.patch(f"{API}/admin/gps/attribution/settings",
                            headers=_admin_headers(),
                            json={"proximity_threshold_m": 999999}, timeout=15)
        assert r2.status_code == 422

    def test_customer_forbidden(self):
        r = requests.get(f"{API}/admin/gps/attribution/settings",
                         headers=_customer_headers(), timeout=15)
        assert r.status_code == 403


class TestManualOverrideAndBatch:

    def _tid(self):
        return _sync.tenants.find_one({})["id"]

    def test_run_batch_links_pending(self):
        tid = self._tid()
        uid = "tech-g5b-api"
        j = _mk_job(tid, uid, 33.5, -112.0)
        _sync.jobs.insert_one(j)
        s = _mk_stop(tid, uid, 33.5001, -112.0001)
        _sync.driver_stops.insert_one(s)
        r = requests.post(f"{API}/admin/gps/attribution/run-batch",
                          headers=_admin_headers(), timeout=15)
        assert r.status_code == 200
        counts = r.json()
        assert counts["processed"] >= 1
        assert counts["auto_linked"] >= 1

    def test_manual_link_and_unlink_and_audit(self):
        tid = self._tid()
        uid = "tech-g5b-api"
        j = _mk_job(tid, uid, 33.5, -112.0)
        _sync.jobs.insert_one(j)
        s = _mk_stop(tid, uid, 33.6, -112.1)  # far away
        _sync.driver_stops.insert_one(s)

        # Manual link.
        r = requests.post(
            f"{API}/admin/gps/stops/{s['id']}/attribute",
            headers=_admin_headers(),
            json={"job_id": j["id"]}, timeout=15)
        assert r.status_code == 200
        assert r.json()["attribution_status"] == "manual_linked"
        assert r.json()["attributed_job_id"] == j["id"]

        # Audit row present.
        audit = _sync.audits.find_one({
            "tenant_id": tid, "kind": "stop_attribution_changed"})
        assert audit is not None
        assert audit["after"]["attribution_status"] == "manual_linked"

        # Unlink.
        r2 = requests.post(
            f"{API}/admin/gps/stops/{s['id']}/attribute",
            headers=_admin_headers(),
            json={"unlink": True}, timeout=15)
        assert r2.status_code == 200
        assert r2.json()["attribution_status"] == "unlinked"
        assert r2.json()["attributed_job_id"] is None

    def test_manual_link_bad_job_id_404(self):
        tid = self._tid()
        s = _mk_stop(tid, "tech-g5b-api", 33.5, -112.0)
        _sync.driver_stops.insert_one(s)
        r = requests.post(f"{API}/admin/gps/stops/{s['id']}/attribute",
                          headers=_admin_headers(),
                          json={"job_id": "does-not-exist"}, timeout=15)
        assert r.status_code == 404

    def test_manual_link_missing_job_id_422(self):
        tid = self._tid()
        s = _mk_stop(tid, "tech-g5b-api", 33.5, -112.0)
        _sync.driver_stops.insert_one(s)
        r = requests.post(f"{API}/admin/gps/stops/{s['id']}/attribute",
                          headers=_admin_headers(),
                          json={}, timeout=15)
        assert r.status_code == 422

    def test_summary_shape(self):
        tid = self._tid()
        uid = "tech-g5b-api"
        j = _mk_job(tid, uid, 33.5, -112.0)
        _sync.jobs.insert_one(j)
        # Two stops attributed to this job (via the batch).
        _sync.driver_stops.insert_many([
            _mk_stop(tid, uid, 33.5, -112.0),
            _mk_stop(tid, uid, 33.5001, -112.0),
        ])
        requests.post(f"{API}/admin/gps/attribution/run-batch",
                      headers=_admin_headers(), timeout=15)
        r = requests.get(f"{API}/admin/gps/attribution/summary?range=week",
                         headers=_admin_headers(), timeout=15)
        assert r.status_code == 200
        body = r.json()
        assert "counts" in body and "top_jobs_by_time_on_site" in body
        # Our job should appear in top jobs.
        top_ids = [row["job_id"] for row in body["top_jobs_by_time_on_site"]]
        assert j["id"] in top_ids

    def test_job_detail(self):
        tid = self._tid()
        uid = "tech-g5b-api"
        j = _mk_job(tid, uid, 33.5, -112.0)
        _sync.jobs.insert_one(j)
        stops = [
            _mk_stop(tid, uid, 33.5, -112.0),
            _mk_stop(tid, uid, 33.5001, -112.0001),
        ]
        _sync.driver_stops.insert_many(stops)
        requests.post(f"{API}/admin/gps/attribution/run-batch",
                      headers=_admin_headers(), timeout=15)
        r = requests.get(f"{API}/admin/gps/attribution/job/{j['id']}",
                         headers=_admin_headers(), timeout=15)
        assert r.status_code == 200
        b = r.json()
        assert b["job_id"] == j["id"]
        assert b["unique_techs"] == 1
        assert len(b["attributed_stops"]) == 2
        assert b["total_stop_duration_s"] == 1200

    def test_summary_customer_forbidden(self):
        r = requests.get(f"{API}/admin/gps/attribution/summary",
                         headers=_customer_headers(), timeout=15)
        assert r.status_code == 403


class TestAttributionLogicViaAPI:
    """Exercises the attributor decision paths through the batch
    endpoint so we test the real code path without wrestling with
    per-test Motor event loops."""

    def _tid(self):
        return _sync.tenants.find_one({})["id"]

    def test_no_match_when_all_jobs_outside_threshold(self):
        tid = self._tid()
        uid = "tech-g5b-api"
        # Set threshold small and put the job far away.
        requests.patch(f"{API}/admin/gps/attribution/settings",
                       headers=_admin_headers(),
                       json={"proximity_threshold_m": 50}, timeout=15)
        _sync.jobs.insert_one(_mk_job(tid, uid, 34.0, -113.0))
        s = _mk_stop(tid, uid, 33.5, -112.0)
        _sync.driver_stops.insert_one(s)
        requests.post(f"{API}/admin/gps/attribution/run-batch",
                      headers=_admin_headers(), timeout=15)
        fresh = _sync.driver_stops.find_one({"id": s["id"]})
        assert fresh["attribution_status"] == "no_match"
        assert fresh["attributed_job_id"] is None

    def test_skips_jobs_without_geocoding(self):
        tid = self._tid()
        uid = "tech-g5b-api"
        # Job has no lat/lon anywhere — skipped, resulting in no_match.
        j = {
            "id": new_id(), "tenant_id": tid, "technician_id": uid,
            "status": "scheduled",
            "scheduled_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "title": f"{TENANT_TAG} nogeo",
        }
        _sync.jobs.insert_one(j)
        s = _mk_stop(tid, uid, 33.5, -112.0)
        _sync.driver_stops.insert_one(s)
        requests.post(f"{API}/admin/gps/attribution/run-batch",
                      headers=_admin_headers(), timeout=15)
        fresh = _sync.driver_stops.find_one({"id": s["id"]})
        assert fresh["attribution_status"] == "no_match"

    def test_same_day_only_filter(self):
        tid = self._tid()
        uid = "tech-g5b-api"
        yday = (datetime.now(timezone.utc)
                - timedelta(days=1)).strftime("%Y-%m-%d")
        j = _mk_job(tid, uid, 33.5, -112.0)
        j["scheduled_date"] = yday
        _sync.jobs.insert_one(j)
        s = _mk_stop(tid, uid, 33.5, -112.0)
        _sync.driver_stops.insert_one(s)
        # same_day_only=True default → no match.
        requests.patch(f"{API}/admin/gps/attribution/settings",
                       headers=_admin_headers(),
                       json={"same_day_only": True,
                             "proximity_threshold_m": 100}, timeout=15)
        requests.post(f"{API}/admin/gps/attribution/run-batch",
                      headers=_admin_headers(), timeout=15)
        fresh = _sync.driver_stops.find_one({"id": s["id"]})
        assert fresh["attribution_status"] == "no_match"

        # Reset to pending and rerun with same_day_only=False.
        _sync.driver_stops.update_one(
            {"id": s["id"]},
            {"$set": {"attribution_status": "pending",
                      "attributed_job_id": None}})
        requests.patch(f"{API}/admin/gps/attribution/settings",
                       headers=_admin_headers(),
                       json={"same_day_only": False}, timeout=15)
        requests.post(f"{API}/admin/gps/attribution/run-batch",
                      headers=_admin_headers(), timeout=15)
        fresh2 = _sync.driver_stops.find_one({"id": s["id"]})
        assert fresh2["attribution_status"] == "auto_linked"
        assert fresh2["attributed_job_id"] == j["id"]

    def test_manual_linked_survives_batch(self):
        tid = self._tid()
        uid = "tech-g5b-api"
        j = _mk_job(tid, uid, 33.5, -112.0)
        _sync.jobs.insert_one(j)
        s = _mk_stop(tid, uid, 33.5, -112.0)
        # Pre-seed as manual_linked to a fake id.
        s["attribution_status"] = "manual_linked"
        s["attributed_job_id"] = "ADMIN_PICKED"
        _sync.driver_stops.insert_one(s)
        requests.post(f"{API}/admin/gps/attribution/run-batch",
                      headers=_admin_headers(), timeout=15)
        fresh = _sync.driver_stops.find_one({"id": s["id"]})
        assert fresh["attribution_status"] == "manual_linked"
        assert fresh["attributed_job_id"] == "ADMIN_PICKED"

    def test_unlinked_survives_batch(self):
        tid = self._tid()
        uid = "tech-g5b-api"
        j = _mk_job(tid, uid, 33.5, -112.0)
        _sync.jobs.insert_one(j)
        s = _mk_stop(tid, uid, 33.5, -112.0)
        s["attribution_status"] = "unlinked"
        s["attributed_job_id"] = None
        _sync.driver_stops.insert_one(s)
        requests.post(f"{API}/admin/gps/attribution/run-batch",
                      headers=_admin_headers(), timeout=15)
        fresh = _sync.driver_stops.find_one({"id": s["id"]})
        assert fresh["attribution_status"] == "unlinked"
        assert fresh["attributed_job_id"] is None
