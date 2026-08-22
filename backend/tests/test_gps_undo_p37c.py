"""Feb-2026 · P37c — undo-start endpoint tests.

Contract for ``POST /api/jobs/{jid}/timer/undo-start``:
    * Within grace window → 200; timer fields cleared; audit-log
      ``job_timer_undo_start`` written.
    * Outside grace window → 400 ``outside_grace_window`` (server
      is authoritative on the clock — never trust client).
    * Non-assigned tech → 403.
    * No active timer → 400 ``no_active_timer``.
    * Already stopped timer → 400 ``timer_already_stopped``.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = MongoClient(_ENV["MONGO_URL"])[_ENV["DB_NAME"]]
API = "http://localhost:8001/api"


def _login(email: str, pw: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login",
                        json={"email": email, "password": pw}, timeout=15)
    r.raise_for_status()
    return r.json()["access_token"]


def _hdrs(email: str) -> dict:
    return {"Authorization": f"Bearer {_login(email)}"}


@pytest.fixture
def admin_h(): return _hdrs("admin@aquaterra.com")


@pytest.fixture
def tech_h(): return _hdrs("mike@aquaterra.com")


@pytest.fixture
def tech_user():
    return _sync.users.find_one({"email": "mike@aquaterra.com"})


@pytest.fixture
def aquaterra_tid():
    return _sync.users.find_one({"email": "admin@aquaterra.com"})["tenant_id"]


def _seed_running_job(tid: str, tech_user: dict, started_delta_s: int = 5,
                        *, tech_owns: bool = True) -> str:
    """Seed a job with an already-running timer."""
    jid = f"TEST_p37c_j_{uuid.uuid4().hex[:8]}"
    tech_id = tech_user.get("technician_id") or tech_user["id"]
    started_at = (datetime.now(tz=timezone.utc)
                    - timedelta(seconds=started_delta_s)).isoformat()
    _sync.jobs.insert_one({
        "id": jid, "tenant_id": tid,
        "technician_id": tech_id if tech_owns else "someone-else",
        "customer_id": f"TEST_p37c_c_{uuid.uuid4().hex[:6]}",
        "service_type": "Landscape", "kind": "landscape",
        "status": "in_progress",
        "timer_started_at": started_at,
        "timer_start_method": "gps_arrival",
        "arrival_lat": 33.5806, "arrival_lng": -112.2374,
        "created_at": "2026-06-01T09:00:00+00:00",
    })
    return jid


@pytest.fixture(autouse=True)
def _cleanup(aquaterra_tid):
    def _reset():
        _sync.jobs.delete_many(
            {"tenant_id": aquaterra_tid, "id": {"$regex": "^TEST_p37c_"}})
        _sync.audit_logs.delete_many({"event": "job_timer_undo_start",
                                          "tenant_id": aquaterra_tid})
    _reset()
    yield
    _reset()


def test_undo_within_grace_window(tech_h, tech_user, aquaterra_tid):
    jid = _seed_running_job(aquaterra_tid, tech_user, started_delta_s=5)
    r = requests.post(f"{API}/jobs/{jid}/timer/undo-start",
                         headers=tech_h, json={"within_seconds": 60},
                         timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["undone"] is True
    row = _sync.jobs.find_one({"id": jid})
    assert row.get("timer_started_at") is None
    assert row.get("timer_start_method") is None
    audit = _sync.audit_logs.find_one({"event": "job_timer_undo_start",
                                            "payload.job_id": jid})
    assert audit is not None


def test_undo_outside_grace_window_400(tech_h, tech_user, aquaterra_tid):
    jid = _seed_running_job(aquaterra_tid, tech_user, started_delta_s=120)
    r = requests.post(f"{API}/jobs/{jid}/timer/undo-start",
                         headers=tech_h, json={"within_seconds": 60},
                         timeout=15)
    assert r.status_code == 400, r.text
    body = r.json()
    assert body["detail"]["detail"] == "outside_grace_window"
    row = _sync.jobs.find_one({"id": jid})
    assert row.get("timer_started_at") is not None


def test_undo_non_assigned_tech_403(tech_h, tech_user, aquaterra_tid):
    jid = _seed_running_job(aquaterra_tid, tech_user, tech_owns=False)
    r = requests.post(f"{API}/jobs/{jid}/timer/undo-start",
                         headers=tech_h, json={"within_seconds": 60},
                         timeout=15)
    assert r.status_code == 403, r.text


def test_undo_no_active_timer_400(tech_h, tech_user, aquaterra_tid):
    jid = _seed_running_job(aquaterra_tid, tech_user)
    _sync.jobs.update_one({"id": jid},
        {"$unset": {"timer_started_at": ""}})
    r = requests.post(f"{API}/jobs/{jid}/timer/undo-start",
                         headers=tech_h, json={"within_seconds": 60},
                         timeout=15)
    assert r.status_code == 400
    assert r.json()["detail"]["detail"] == "no_active_timer"


def test_undo_already_stopped_timer_400(tech_h, tech_user, aquaterra_tid):
    jid = _seed_running_job(aquaterra_tid, tech_user)
    _sync.jobs.update_one({"id": jid},
        {"$set": {"timer_stopped_at":
                    datetime.now(tz=timezone.utc).isoformat()}})
    r = requests.post(f"{API}/jobs/{jid}/timer/undo-start",
                         headers=tech_h, json={"within_seconds": 60},
                         timeout=15)
    assert r.status_code == 400
    assert r.json()["detail"]["detail"] == "timer_already_stopped"


def test_openapi_lists_undo_route():
    r = requests.get(f"{API}/openapi.json", timeout=15)
    assert r.status_code == 200
    assert "/api/jobs/{jid}/timer/undo-start" in (r.json().get("paths") or {})
