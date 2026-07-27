"""Feb-2026 · Schedule multi-select job soft-delete — pytest.

Covers the three new endpoints:
    POST /api/jobs/{jid}/soft-delete
    POST /api/jobs/bulk-soft-delete
    POST /api/jobs/{jid}/undelete
plus the ``deleted_at`` filter added to ``GET /api/jobs``.

Every test seeds throwaway job rows scoped to the primary tenant and
cleans up in the fixture teardown — no real jobs mutated. Uses the
existing preview seed users (``super@aquaterra.com``, plus a fresh
throwaway ``admin`` and ``technician`` row minted per-fixture so we
don't collide with the recently-deleted seed accounts).
"""
from __future__ import annotations
import os
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

import jwt as _jwt
import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

_BACKEND_ENV = Path(__file__).resolve().parents[1] / ".env"
_ENV = dotenv_values(_BACKEND_ENV)
_MONGO_URL = _ENV.get("MONGO_URL") or os.environ.get("MONGO_URL")
_DB_NAME = _ENV.get("DB_NAME") or os.environ.get("DB_NAME")
_JWT_SECRET = _ENV.get("JWT_SECRET") or os.environ.get("JWT_SECRET")
_sync = MongoClient(_MONGO_URL)[_DB_NAME]

_REACT_ENV = Path(__file__).resolve().parents[2] / "frontend" / ".env"
_REACT = dotenv_values(_REACT_ENV) if _REACT_ENV.is_file() else {}
_PUBLIC_URL = _REACT.get("REACT_APP_BACKEND_URL") or os.environ.get(
    "REACT_APP_BACKEND_URL")
API = os.environ.get("BACKEND_API_URL") or (
    (_PUBLIC_URL.rstrip("/") + "/api") if _PUBLIC_URL else
    "http://localhost:8001/api"
)


def _mint_jwt(uid: str, role: str = "admin", exp_minutes: int = 60) -> str:
    """Mint a JWT directly — bypasses ``/auth/login`` so we can drive
    tests as a freshly-seeded user without paying for password + email
    validation on the login endpoint (the seed admin/mike accounts
    were removed in the Feb-2026 preview wipe)."""
    return _jwt.encode(
        {"sub": uid, "role": role,
          "exp": datetime.now(timezone.utc) + timedelta(minutes=exp_minutes)},
        _JWT_SECRET, algorithm="HS256",
    )


def _super_admin_tenant_id() -> str:
    return _sync.users.find_one(
        {"email": "super@aquaterra.com"}, {"_id": 0, "tenant_id": 1})["tenant_id"]


def _super_admin_id() -> str:
    return _sync.users.find_one(
        {"email": "super@aquaterra.com"}, {"_id": 0, "id": 1})["id"]


def _seed_user(role: str, department: str | None = None) -> dict:
    tid = _super_admin_tenant_id()
    uid = f"pytest-job-{uuid.uuid4().hex[:10]}"
    doc = {
        "id": uid, "email": f"{uid}@pytest.example",
        "name": f"Test {role}",
        "role": role, "department": department,
        "tenant_id": tid,
        "password_hash": "$2b$12$aaaaaaaaaaaaaaaaaaaaaOxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _sync.users.insert_one({**doc})
    return doc


def _seed_job(*, status: str = "scheduled",
              completed_at: str | None = None,
              scheduled_date: str | None = None) -> dict:
    tid = _super_admin_tenant_id()
    jid = f"pytest-job-{uuid.uuid4().hex[:12]}"
    doc = {
        "id": jid, "tenant_id": tid,
        "customer_id": "pytest-cust",
        "customer_name": "PyTest Customer",
        "service_type": "Weekly",
        "status": status,
        "scheduled_date": scheduled_date or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    if completed_at is not None:
        doc["completed_at"] = completed_at
    _sync.jobs.insert_one({**doc})
    return doc


@pytest.fixture
def super_headers():
    tok = _mint_jwt(_super_admin_id(), role="super_admin")
    yield {"Authorization": f"Bearer {tok}"}


@pytest.fixture
def admin_user():
    u = _seed_user("admin")
    yield u
    _sync.users.delete_one({"id": u["id"]})


@pytest.fixture
def admin_headers(admin_user):
    tok = _mint_jwt(admin_user["id"], role="admin")
    yield {"Authorization": f"Bearer {tok}"}


@pytest.fixture
def tech_user():
    u = _seed_user("technician", department="pool")
    yield u
    _sync.users.delete_one({"id": u["id"]})


@pytest.fixture
def tech_headers(tech_user):
    tok = _mint_jwt(tech_user["id"], role="technician")
    yield {"Authorization": f"Bearer {tok}"}


@pytest.fixture
def open_job():
    j = _seed_job(status="scheduled")
    yield j
    _sync.jobs.delete_one({"id": j["id"]})


@pytest.fixture
def historical_completed_job():
    """Completed 60 days ago — protected by the 30-day guardrail."""
    old = (datetime.now(timezone.utc) - timedelta(days=60))
    j = _seed_job(status="completed",
                    completed_at=old.isoformat(),
                    scheduled_date=old.strftime("%Y-%m-%d"))
    yield j
    _sync.jobs.delete_one({"id": j["id"]})


@pytest.fixture
def recent_completed_job():
    """Completed 10 days ago — inside the 30-day window, delete allowed."""
    recent = (datetime.now(timezone.utc) - timedelta(days=10))
    j = _seed_job(status="completed",
                    completed_at=recent.isoformat(),
                    scheduled_date=recent.strftime("%Y-%m-%d"))
    yield j
    _sync.jobs.delete_one({"id": j["id"]})


# ─── Single soft-delete ──────────────────────────────────────────────
def test_admin_can_soft_delete_open_job(admin_headers, open_job):
    r = requests.post(f"{API}/jobs/{open_job['id']}/soft-delete",
                        headers=admin_headers, timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["job_id"] == open_job["id"]
    assert body["deleted_at"]
    fresh = _sync.jobs.find_one({"id": open_job["id"]}, {"_id": 0})
    assert fresh["deleted_at"]
    assert fresh["deleted_by_user_id"]


def test_tech_cannot_soft_delete(tech_headers, open_job):
    r = requests.post(f"{API}/jobs/{open_job['id']}/soft-delete",
                        headers=tech_headers, timeout=15)
    assert r.status_code == 403, r.text


def test_cannot_delete_historical_completed_job(admin_headers,
                                                  historical_completed_job):
    r = requests.post(f"{API}/jobs/{historical_completed_job['id']}/soft-delete",
                        headers=admin_headers, timeout=15)
    assert r.status_code == 400, r.text
    assert "30" in (r.json().get("detail") or "")


def test_can_delete_recently_completed_job(admin_headers, recent_completed_job):
    r = requests.post(f"{API}/jobs/{recent_completed_job['id']}/soft-delete",
                        headers=admin_headers, timeout=15)
    assert r.status_code == 200, r.text


# ─── Bulk soft-delete ────────────────────────────────────────────────
def test_bulk_soft_delete_returns_per_id_results(admin_headers):
    tid = _super_admin_tenant_id()
    good = _seed_job(status="scheduled")
    bad = f"pytest-nonexistent-{uuid.uuid4().hex[:8]}"
    old = (datetime.now(timezone.utc) - timedelta(days=90))
    historic = _seed_job(status="completed",
                            completed_at=old.isoformat(),
                            scheduled_date=old.strftime("%Y-%m-%d"))
    try:
        r = requests.post(f"{API}/jobs/bulk-soft-delete",
                            json={"job_ids": [good["id"], bad, historic["id"]]},
                            headers=admin_headers, timeout=20)
        assert r.status_code == 200, r.text
        body = r.json()
        assert good["id"] in body["deleted"]
        failed_ids = [f["job_id"] for f in body["failed"]]
        assert bad in failed_ids
        assert historic["id"] in failed_ids
        assert body["count"] == 1
    finally:
        _sync.jobs.delete_one({"id": good["id"]})
        _sync.jobs.delete_one({"id": historic["id"]})


def test_bulk_soft_delete_capped_at_100(admin_headers):
    r = requests.post(f"{API}/jobs/bulk-soft-delete",
                        json={"job_ids": [f"x{i}" for i in range(101)]},
                        headers=admin_headers, timeout=20)
    assert r.status_code == 400
    assert "100" in (r.json().get("detail") or "")


def test_bulk_soft_delete_empty_list_400(admin_headers):
    r = requests.post(f"{API}/jobs/bulk-soft-delete",
                        json={"job_ids": []},
                        headers=admin_headers, timeout=15)
    assert r.status_code == 400


# ─── GET /api/jobs filter ────────────────────────────────────────────
def test_jobs_list_excludes_soft_deleted_by_default(admin_headers, open_job):
    requests.post(f"{API}/jobs/{open_job['id']}/soft-delete",
                    headers=admin_headers, timeout=15)
    r = requests.get(f"{API}/jobs?limit=5000",
                       headers=admin_headers, timeout=15)
    ids = [j["id"] for j in r.json()]
    assert open_job["id"] not in ids


def test_jobs_list_super_admin_can_include_deleted(super_headers,
                                                       admin_headers,
                                                       open_job):
    requests.post(f"{API}/jobs/{open_job['id']}/soft-delete",
                    headers=admin_headers, timeout=15)
    r = requests.get(f"{API}/jobs?include_deleted=true&limit=5000",
                       headers=super_headers, timeout=15)
    ids = [j["id"] for j in r.json()]
    assert open_job["id"] in ids


def test_jobs_list_admin_include_deleted_flag_ignored(admin_headers, open_job):
    """Regular admin passing include_deleted still gets filtered."""
    requests.post(f"{API}/jobs/{open_job['id']}/soft-delete",
                    headers=admin_headers, timeout=15)
    r = requests.get(f"{API}/jobs?include_deleted=true&limit=5000",
                       headers=admin_headers, timeout=15)
    ids = [j["id"] for j in r.json()]
    assert open_job["id"] not in ids


# ─── Undelete ────────────────────────────────────────────────────────
def test_super_admin_can_undelete_job(super_headers, admin_headers, open_job):
    requests.post(f"{API}/jobs/{open_job['id']}/soft-delete",
                    headers=admin_headers, timeout=15)
    r = requests.post(f"{API}/jobs/{open_job['id']}/undelete",
                        headers=super_headers, timeout=15)
    assert r.status_code == 200, r.text
    fresh = _sync.jobs.find_one({"id": open_job["id"]}, {"_id": 0})
    assert fresh["deleted_at"] in (None,)


def test_admin_cannot_undelete_job(admin_headers, open_job):
    requests.post(f"{API}/jobs/{open_job['id']}/soft-delete",
                    headers=admin_headers, timeout=15)
    r = requests.post(f"{API}/jobs/{open_job['id']}/undelete",
                        headers=admin_headers, timeout=15)
    assert r.status_code == 403, r.text
