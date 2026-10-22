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
from tests._shared_mongo import (
    shared_client as _shared_client,
    shared_db as _shared_db,
)


_BACKEND_ENV = Path(__file__).resolve().parents[1] / ".env"
_ENV = dotenv_values(_BACKEND_ENV)
_MONGO_URL = _ENV.get("MONGO_URL") or os.environ.get("MONGO_URL")
_DB_NAME = _ENV.get("DB_NAME") or os.environ.get("DB_NAME")
_JWT_SECRET = _ENV.get("JWT_SECRET") or os.environ.get("JWT_SECRET")
_sync = _shared_db()
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


# ─── Bulk soft-delete (POST /jobs/bulk-soft-delete — RETIRED 410) ───
# TD-82-calendar-consolidate · Phase 2B · Oct-2026 — the legacy
# ``POST /jobs/bulk-soft-delete`` endpoint has been retired to 410
# Gone. All callers (web ``CalendarSchedule.jsx`` + mobile
# ``calendar.tsx``) migrated to the canonical
# ``POST /jobs/bulk-delete`` in ``routers/bulk_crm.py:444``. The 3
# tests below now assert the 410-Gone retire contract instead of
# the Phase-2A shim's legacy response shape. Full retire regression
# shape (detail-string + role-independence) lives in
# ``test_td82_bulk_delete_dedup.py``.
def test_bulk_soft_delete_returns_410_gone(admin_headers):
    r = requests.post(f"{API}/jobs/bulk-soft-delete",
                        json={"job_ids": ["some-id"]},
                        headers=admin_headers, timeout=20)
    assert r.status_code == 410, r.text
    assert "/jobs/bulk-delete" in (r.json().get("detail") or "")


def test_bulk_soft_delete_capped_at_100_returns_410(admin_headers):
    r = requests.post(f"{API}/jobs/bulk-soft-delete",
                        json={"job_ids": [f"x{i}" for i in range(101)]},
                        headers=admin_headers, timeout=20)
    # Pre-Phase-2B this returned 400 "capped at 100"; post-retire the
    # 410 gate fires before body-shape validation.
    assert r.status_code == 410


def test_bulk_soft_delete_empty_list_returns_410(admin_headers):
    r = requests.post(f"{API}/jobs/bulk-soft-delete",
                        json={"job_ids": []},
                        headers=admin_headers, timeout=15)
    # Pre-Phase-2B this returned 400 "job_ids is empty"; post-retire
    # the 410 gate fires before body-shape validation.
    assert r.status_code == 410


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


def test_admin_can_undelete_job(admin_headers, open_job):
    """TD-admin-undelete-rbac · Oct-2026 — Phase 34 Task X design
    intent: ``POST /jobs/{jid}/undelete`` admits any admin-equivalent
    role (``admin`` / ``super_admin`` / ``owner``) per the handler's
    inline role check at ``routers/jobs.py:4873``. This mirrors the
    ``require_admin`` helper widening in ``utils.py:220-228`` from
    the same phase and keeps undelete symmetric with sibling delete
    endpoints: ``DELETE /jobs/{jid}``, ``POST /jobs/{jid}/soft-delete``,
    and ``POST /jobs/bulk-delete`` (``bulk_crm.py:199``) are all gated
    at ``require_admin`` — any role that can delete can also undelete.

    (Pre-TD-admin-undelete-rbac the test here asserted ``403`` which
    was a stale assertion from before the Phase 34 Task X widening;
    TD-82 Phase 2A ship receipt ``470112f3d`` already flagged it as
    pre-existing-failing.)
    """
    requests.post(f"{API}/jobs/{open_job['id']}/soft-delete",
                    headers=admin_headers, timeout=15)
    r = requests.post(f"{API}/jobs/{open_job['id']}/undelete",
                        headers=admin_headers, timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("ok") is True
    assert body.get("job_id") == open_job["id"]
    assert isinstance(body.get("restored_at"), str) and body["restored_at"]
    # DB state matches response — job is live again.
    fresh = _sync.jobs.find_one({"id": open_job["id"]}, {"_id": 0})
    assert fresh.get("deleted_at") in (None,)
    assert fresh.get("undeleted_by_user_id") is not None


# ─── Negative-case locks: lower roles stay 403 ─────────────────────
# TD-admin-undelete-rbac · Oct-2026 — guards against future accidental
# widening of the undelete gate below the ``admin``-equivalent tier.
# Error-detail string is also locked so a future refactor that
# re-attaches the handler with a different 403 message trips the
# assertion.
_UNDELETE_FORBIDDEN_DETAIL = "Admin role required to undelete jobs"


def test_technician_cannot_undelete_job(tech_headers, admin_headers, open_job):
    """TD-admin-undelete-rbac · Oct-2026 — tech role gets 403.

    Delete via admin first (admin can soft-delete), then attempt
    undelete as tech. The handler's inline role check at
    ``routers/jobs.py:4873-4874`` rejects any role outside
    ``(admin, super_admin, owner)``.
    """
    requests.post(f"{API}/jobs/{open_job['id']}/soft-delete",
                    headers=admin_headers, timeout=15)
    r = requests.post(f"{API}/jobs/{open_job['id']}/undelete",
                        headers=tech_headers, timeout=15)
    assert r.status_code == 403, r.text
    assert (r.json().get("detail") or "") == _UNDELETE_FORBIDDEN_DETAIL


def test_manager_cannot_undelete_job(admin_headers, open_job):
    """TD-admin-undelete-rbac · Oct-2026 — manager role gets 403.

    ``manager`` passes ``require_admin_or_manager`` (used for
    bulk-reassign + bulk-reschedule + recurring CRUD) but is
    deliberately excluded from the delete/undelete tier, which
    uses ``require_admin``. Undelete follows the same boundary.
    """
    m = _seed_user("manager")
    try:
        tok = _mint_jwt(m["id"], role="manager")
        headers = {"Authorization": f"Bearer {tok}"}
        requests.post(f"{API}/jobs/{open_job['id']}/soft-delete",
                        headers=admin_headers, timeout=15)
        r = requests.post(f"{API}/jobs/{open_job['id']}/undelete",
                            headers=headers, timeout=15)
        assert r.status_code == 403, r.text
        assert (r.json().get("detail") or "") == _UNDELETE_FORBIDDEN_DETAIL
    finally:
        _sync.users.delete_one({"id": m["id"]})


def test_customer_cannot_undelete_job(admin_headers, open_job):
    """TD-admin-undelete-rbac · Oct-2026 — customer role gets 403.

    Customers never touch any mutation endpoint on jobs; this test
    locks the obvious floor and documents it.
    """
    c = _seed_user("customer")
    try:
        tok = _mint_jwt(c["id"], role="customer")
        headers = {"Authorization": f"Bearer {tok}"}
        requests.post(f"{API}/jobs/{open_job['id']}/soft-delete",
                        headers=admin_headers, timeout=15)
        r = requests.post(f"{API}/jobs/{open_job['id']}/undelete",
                            headers=headers, timeout=15)
        assert r.status_code == 403, r.text
        assert (r.json().get("detail") or "") == _UNDELETE_FORBIDDEN_DETAIL
    finally:
        _sync.users.delete_one({"id": c["id"]})
