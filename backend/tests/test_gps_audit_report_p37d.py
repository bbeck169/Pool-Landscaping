"""Feb-2026 · P37d — GPS Auto-Start audit report tests."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone, timedelta
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
API = "http://localhost:8001/api"

_TAG = "TEST_p37d_"


def _login(email="admin@aquaterra.com", pw="password123") -> str:
    r = requests.post(f"{API}/auth/login",
                        json={"email": email, "password": pw}, timeout=15)
    r.raise_for_status()
    return r.json()["access_token"]


@pytest.fixture
def admin_h():
    return {"Authorization": f"Bearer {_login()}"}


@pytest.fixture
def aquaterra_tid():
    return _sync.users.find_one({"email": "admin@aquaterra.com"})["tenant_id"]


def _seed_audit_row(tid: str, *, outcome: str, distance_m=None,
                       radius_m=75, tech_id="tech-1", job_id=None,
                       at=None) -> None:
    at = at or datetime.now(timezone.utc).isoformat()
    _sync.audit_logs.insert_one({
        "id": f"{_TAG}{uuid.uuid4().hex[:10]}",
        "tenant_id": tid,
        "event": "job_timer_auto_start",
        "at": at,
        "actor_id": tech_id,
        "payload": {
            "outcome": outcome,
            "distance_m": distance_m,
            "radius_m": radius_m,
            "technician_id": tech_id,
            "job_id": job_id or f"{_TAG}job-{uuid.uuid4().hex[:6]}",
            "arrived_at": at,
            "consent_state": "active",
        },
    })


@pytest.fixture(autouse=True)
def _cleanup(aquaterra_tid):
    def _reset():
        _sync.audit_logs.delete_many(
            {"tenant_id": aquaterra_tid, "id": {"$regex": f"^{_TAG}"}})
    _reset(); yield; _reset()


def test_summary_matches_seeded_distribution(admin_h, aquaterra_tid):
    """20 audit rows across the 5 outcomes at varying distances."""
    # Isolate the window from any pre-existing job_timer_auto_start
    # rows on the shared aquaterra tenant by capturing a "start
    # marker" and using it as the ``from=`` query param.
    frm = datetime.now(timezone.utc).isoformat()
    # 8 started (distances 5, 10, 20, 30, 50, 60, 70, 100)
    for d in [5, 10, 20, 30, 50, 60, 70, 100]:
        _seed_audit_row(aquaterra_tid, outcome="started", distance_m=d)
    # 4 throttled (distance recorded)
    for d in [15, 20, 25, 40]:
        _seed_audit_row(aquaterra_tid, outcome="throttled", distance_m=d)
    # 3 out_of_radius
    for d in [120, 200, 350]:
        _seed_audit_row(aquaterra_tid, outcome="out_of_radius", distance_m=d)
    # 3 consent_required (no distance)
    for _ in range(3):
        _seed_audit_row(aquaterra_tid, outcome="consent_required")
    # 2 feature_disabled
    for _ in range(2):
        _seed_audit_row(aquaterra_tid, outcome="feature_disabled")

    r = requests.get(f"{API}/reports/gps-auto-start-audit?from={frm}",
                        headers=admin_h, timeout=20)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    s = body["summary"]
    assert s["total_arrivals"] == 20
    assert s["started"] == 8
    assert s["throttled"] == 4
    assert s["out_of_radius"] == 3
    assert s["consent_required"] == 3
    assert s["feature_disabled"] == 2
    # 15 distances present (8 started + 4 throttled + 3 out_of_radius).
    assert s["distance_sample_size"] == 15
    # Median of sorted [5,10,15,20,20,25,30,40,50,60,70,100,120,200,350] = 40.
    assert s["median_distance_m"] == 40.0
    # p90 nearest-rank = 200 (index 13 for n=15 → round(0.9*14)=13).
    assert s["p90_distance_m"] == 200.0


def test_percent_buckets_sum_to_100(admin_h, aquaterra_tid):
    frm = datetime.now(timezone.utc).isoformat()
    for d in [5, 10, 15, 20, 22]:      # 5 excellent (<25)
        _seed_audit_row(aquaterra_tid, outcome="started", distance_m=d)
    for d in [30, 40, 50, 60, 70]:     # 5 acceptable (25..75)
        _seed_audit_row(aquaterra_tid, outcome="started", distance_m=d)
    for d in [100, 150]:               # 2 over radius (>75)
        _seed_audit_row(aquaterra_tid, outcome="started", distance_m=d)

    r = requests.get(f"{API}/reports/gps-auto-start-audit?from={frm}",
                        headers=admin_h, timeout=15)
    s = r.json()["summary"]
    # 5/12 = 41.7%, 5/12 = 41.7%, 2/12 = 16.7%. Sum with rounding = 100.1.
    total = s["percent_excellent"] + s["percent_acceptable"] + s["percent_over_radius"]
    assert 99.5 <= total <= 100.5, f"buckets sum to {total} (expected ~100)"


def test_rbac_technician_403(aquaterra_tid):
    _seed_audit_row(aquaterra_tid, outcome="started", distance_m=10)
    tok = _login("carlos@aquaterra.com")
    r = requests.get(f"{API}/reports/gps-auto-start-audit",
                        headers={"Authorization": f"Bearer {tok}"},
                        timeout=15)
    assert r.status_code == 403, r.text


def test_empty_window_returns_zeros(admin_h):
    """No audit rows in the window → summary all zeros, no crash."""
    # Use a from/to that predates any seeded rows.
    frm = "2020-01-01T00:00:00+00:00"
    to = "2020-01-02T00:00:00+00:00"
    r = requests.get(
        f"{API}/reports/gps-auto-start-audit?from={frm}&to={to}",
        headers=admin_h, timeout=15)
    assert r.status_code == 200, r.text
    s = r.json()["summary"]
    assert s["total_arrivals"] == 0
    assert s["started"] == 0
    assert s["median_distance_m"] is None
    assert s["p90_distance_m"] is None
    assert s["percent_excellent"] == 0
    assert r.json()["recent_events"] == []


def test_tech_id_filter_narrows_the_slice(admin_h, aquaterra_tid):
    frm = datetime.now(timezone.utc).isoformat()
    _seed_audit_row(aquaterra_tid, outcome="started", distance_m=10,
                       tech_id="tech-A")
    _seed_audit_row(aquaterra_tid, outcome="started", distance_m=20,
                       tech_id="tech-A")
    _seed_audit_row(aquaterra_tid, outcome="started", distance_m=30,
                       tech_id="tech-B")
    r = requests.get(
        f"{API}/reports/gps-auto-start-audit?from={frm}&tech_id=tech-A",
        headers=admin_h, timeout=15)
    body = r.json()
    assert body["summary"]["total_arrivals"] == 2
    assert body["summary"]["distance_sample_size"] == 2


def test_legacy_rows_without_outcome_count_as_started(admin_h, aquaterra_tid):
    """Pre-P37d audit rows written without an ``outcome`` field must
    still count toward ``total_arrivals``; they default to
    ``started`` since only successful arrives got logged pre-P37d."""
    frm = datetime.now(timezone.utc).isoformat()
    _sync.audit_logs.insert_one({
        "id": f"{_TAG}legacy-{uuid.uuid4().hex[:6]}",
        "tenant_id": aquaterra_tid,
        "event": "job_timer_auto_start",
        "at": datetime.now(timezone.utc).isoformat(),
        "actor_id": "tech-legacy",
        "payload": {"distance_m": 12, "radius_m": 75,
                       "technician_id": "tech-legacy",
                       "job_id": f"{_TAG}legacy-job"},
    })
    r = requests.get(f"{API}/reports/gps-auto-start-audit?from={frm}",
                        headers=admin_h, timeout=15)
    s = r.json()["summary"]
    assert s["total_arrivals"] == 1
    assert s["started"] == 1


def test_openapi_lists_endpoint():
    r = requests.get(f"{API}/openapi.json", timeout=15)
    assert r.status_code == 200
    assert "/api/reports/gps-auto-start-audit" in (r.json().get("paths") or {})
