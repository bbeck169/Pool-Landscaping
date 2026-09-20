"""Feb-2026 · Crew Phase A · Job crew_id write paths.

Locks in the crew-assignment handlers added in this PR:

  * PUT ``/api/jobs/{jid}`` — accepts ``crew_id`` on the ``JobUpdate``
    body, validates it resolves to a crew in the caller's tenant,
    stamps denormalized ``crew_name`` + ``crew_color`` on the job,
    and preserves ``technician_id`` (overlay semantics — locked
    product decision).
  * POST ``/api/jobs/bulk-reassign`` — accepts ``new_crew_id`` on the
    body. Callers can send tech-only, crew-only, or both (overlay).
    At least one must be provided. Same tenant + no-op guarantees
    match the single-job PUT.
  * GET ``/api/jobs?crew_id=...`` — admin-equivalent filter.

RBAC is separately covered by ``test_crew_assignment_rbac.py``.

Harness mirrors ``test_team_picker_tech_both.py``.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient
from tests._shared_mongo import (
    shared_client as _shared_client,
    shared_db as _shared_db,
)


os.environ.setdefault("ALLOW_TEST_HOOKS", "1")

_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = _shared_db()
API = "http://localhost:8001/api"

JWT_SECRET = (
    _ENV.get("JWT_SECRET") or os.environ.get("JWT_SECRET")
    or "dev-secret-change-me"
)
JWT_ALGO = _ENV.get("JWT_ALGO") or "HS256"


def _tok(user_id: str, email: str, role: str,
          tenant_id: str | None = None) -> str:
    payload = {
        "sub": user_id, "email": email, "role": role,
        "tenant_id": tenant_id or "",
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)


@pytest.fixture()
def tenant_id():
    tid = f"jca-{uuid.uuid4().hex[:8]}"
    _sync.tenants.insert_one({
        "id": tid, "name": f"JCA {tid}", "slug": f"jca-{tid}",
        "active": True, "widget_allowed_domains": [],
    })
    yield tid
    for col in ("tenants", "users", "crews", "jobs", "audit_log"):
        _sync[col].delete_many({"tenant_id": tid})


def _seed_user(tenant_id: str, role: str, *,
                department=None) -> dict:
    uid = f"{role}-{uuid.uuid4().hex[:8]}"
    email = f"{uid}@jca.test"
    _sync.users.insert_one({
        "id": uid, "tenant_id": tenant_id, "role": role,
        "name": f"JCA {role}", "email": email,
        "department": department, "technician_id": None,
    })
    return {"id": uid, "email": email, "role": role,
            "tenant_id": tenant_id,
            "token": _tok(uid, email, role, tenant_id)}


def _seed_crew(tenant_id: str, name: str = "Blue Team",
                color: str = "#0284C7") -> dict:
    cid = f"crew-{uuid.uuid4().hex[:8]}"
    doc = {
        "id": cid, "tenant_id": tenant_id, "name": name,
        "color": color, "tech_ids": [],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _sync.crews.insert_one(doc)
    return doc


def _seed_job(tenant_id: str, *, technician_id=None,
                crew_id=None) -> dict:
    jid = f"job-{uuid.uuid4().hex[:8]}"
    day_iso = datetime.now(timezone.utc).replace(
        hour=10, minute=0, second=0, microsecond=0,
    ).isoformat()
    doc = {
        "id": jid, "tenant_id": tenant_id,
        "title": "Crew Phase A assign test",
        "service_type": "pool_service",
        "scheduled_date": day_iso, "status": "scheduled",
        "technician_id": technician_id, "crew_id": crew_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _sync.jobs.insert_one(doc)
    return doc


def _auth(token: str, tenant_id: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "X-Tenant-Id": tenant_id,
    }


@pytest.fixture()
def admin(tenant_id):
    return _seed_user(tenant_id, "admin")


# ══════════════════════════════════════════════════════════════════
# PUT /jobs/{id} — single-job crew assignment
# ══════════════════════════════════════════════════════════════════
def test_put_job_with_valid_crew_stamps_name_and_color(admin, tenant_id):
    crew = _seed_crew(tenant_id, name="Blue Team", color="#0284C7")
    job = _seed_job(tenant_id)
    r = requests.put(
        f"{API}/jobs/{job['id']}",
        headers=_auth(admin["token"], admin["tenant_id"]),
        json={"crew_id": crew["id"]},
    )
    assert r.status_code == 200, r.text
    # Refetch the job — crew_id, crew_name, crew_color all stamped.
    row = _sync.jobs.find_one({"id": job["id"]},
                                {"_id": 0, "crew_id": 1, "crew_name": 1,
                                 "crew_color": 1, "technician_id": 1})
    assert row["crew_id"] == crew["id"]
    assert row["crew_name"] == "Blue Team"
    assert row["crew_color"] == "#0284C7"


def test_put_job_with_crew_preserves_lead_tech(admin, tenant_id):
    # Overlay semantics — assigning a crew must NOT clear the tech.
    tech = _seed_user(tenant_id, "technician", department="pool")
    crew = _seed_crew(tenant_id)
    job = _seed_job(tenant_id, technician_id=tech["id"])
    r = requests.put(
        f"{API}/jobs/{job['id']}",
        headers=_auth(admin["token"], admin["tenant_id"]),
        json={"crew_id": crew["id"]},
    )
    assert r.status_code == 200, r.text
    row = _sync.jobs.find_one({"id": job["id"]},
                                {"_id": 0, "crew_id": 1, "technician_id": 1})
    assert row["crew_id"] == crew["id"]
    assert row["technician_id"] == tech["id"], (
        "lead tech must be preserved on crew assign — overlay semantics"
    )


def test_put_job_with_nonexistent_crew_returns_400(admin, tenant_id):
    job = _seed_job(tenant_id)
    r = requests.put(
        f"{API}/jobs/{job['id']}",
        headers=_auth(admin["token"], admin["tenant_id"]),
        json={"crew_id": "crew-does-not-exist"},
    )
    assert r.status_code == 400, r.text
    assert "crew" in r.text.lower()
    # Job must NOT have been touched.
    row = _sync.jobs.find_one({"id": job["id"]},
                                {"_id": 0, "crew_id": 1})
    assert row.get("crew_id") is None


def test_put_job_with_cross_tenant_crew_returns_400(admin, tenant_id):
    # Seed a crew in a DIFFERENT tenant.
    other_tid = f"jca-other-{uuid.uuid4().hex[:8]}"
    _sync.tenants.insert_one({
        "id": other_tid, "name": "Other", "slug": other_tid,
        "active": True, "widget_allowed_domains": [],
    })
    try:
        other_crew = _seed_crew(other_tid, name="Other tenant's crew")
        job = _seed_job(tenant_id)
        r = requests.put(
            f"{API}/jobs/{job['id']}",
            headers=_auth(admin["token"], admin["tenant_id"]),
            json={"crew_id": other_crew["id"]},
        )
        assert r.status_code == 400, r.text
        row = _sync.jobs.find_one({"id": job["id"]},
                                    {"_id": 0, "crew_id": 1})
        assert row.get("crew_id") is None
    finally:
        for col in ("tenants", "crews"):
            _sync[col].delete_many({"tenant_id": other_tid})


# ══════════════════════════════════════════════════════════════════
# POST /jobs/bulk-reassign — new_crew_id
# ══════════════════════════════════════════════════════════════════
def test_bulk_reassign_with_crew_only(admin, tenant_id):
    crew = _seed_crew(tenant_id, name="Red Team", color="#DC2626")
    jobs = [_seed_job(tenant_id) for _ in range(3)]
    r = requests.post(
        f"{API}/jobs/bulk-reassign",
        headers=_auth(admin["token"], admin["tenant_id"]),
        json={"job_ids": [j["id"] for j in jobs],
               "new_crew_id": crew["id"]},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["count"] == 3
    assert body["new_crew_id"] == crew["id"]
    assert body["new_crew_name"] == "Red Team"
    assert body["new_tech_id"] is None
    # All 3 jobs now have crew_id + crew_name + crew_color.
    for j in jobs:
        row = _sync.jobs.find_one({"id": j["id"]},
                                    {"_id": 0, "crew_id": 1,
                                     "crew_name": 1, "crew_color": 1})
        assert row["crew_id"] == crew["id"]
        assert row["crew_name"] == "Red Team"
        assert row["crew_color"] == "#DC2626"


def test_bulk_reassign_with_both_tech_and_crew_overlay(admin, tenant_id):
    tech = _seed_user(tenant_id, "technician", department="pool")
    crew = _seed_crew(tenant_id)
    jobs = [_seed_job(tenant_id) for _ in range(2)]
    r = requests.post(
        f"{API}/jobs/bulk-reassign",
        headers=_auth(admin["token"], admin["tenant_id"]),
        json={"job_ids": [j["id"] for j in jobs],
               "new_tech_id": tech["id"],
               "new_crew_id": crew["id"]},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["new_tech_id"], "tech id must be echoed"
    assert body["new_crew_id"] == crew["id"]
    for j in jobs:
        row = _sync.jobs.find_one({"id": j["id"]},
                                    {"_id": 0, "crew_id": 1,
                                     "technician_id": 1,
                                     "assigned_tech_id": 1})
        assert row["crew_id"] == crew["id"]
        # Both tech mirror fields written.
        assert row["technician_id"] is not None
        assert row["assigned_tech_id"] == row["technician_id"]


def test_bulk_reassign_with_neither_returns_400(admin, tenant_id):
    jobs = [_seed_job(tenant_id) for _ in range(2)]
    r = requests.post(
        f"{API}/jobs/bulk-reassign",
        headers=_auth(admin["token"], admin["tenant_id"]),
        json={"job_ids": [j["id"] for j in jobs]},
    )
    assert r.status_code == 400, r.text
    assert "new_tech_id" in r.text or "new_crew_id" in r.text


def test_bulk_reassign_with_cross_tenant_crew_returns_400(admin, tenant_id):
    other_tid = f"jca-other-{uuid.uuid4().hex[:8]}"
    _sync.tenants.insert_one({
        "id": other_tid, "name": "Other", "slug": other_tid,
        "active": True, "widget_allowed_domains": [],
    })
    try:
        other_crew = _seed_crew(other_tid, name="Other tenant's crew")
        jobs = [_seed_job(tenant_id) for _ in range(2)]
        r = requests.post(
            f"{API}/jobs/bulk-reassign",
            headers=_auth(admin["token"], admin["tenant_id"]),
            json={"job_ids": [j["id"] for j in jobs],
                   "new_crew_id": other_crew["id"]},
        )
        assert r.status_code == 400, r.text
        # No job was touched.
        for j in jobs:
            row = _sync.jobs.find_one({"id": j["id"]},
                                        {"_id": 0, "crew_id": 1})
            assert row.get("crew_id") is None
    finally:
        for col in ("tenants", "crews"):
            _sync[col].delete_many({"tenant_id": other_tid})


def test_bulk_reassign_crew_only_does_not_notify_outgoing_tech(admin, tenant_id):
    # Job already has a lead tech; crew-only reassign must NOT
    # generate a "you lost this job" notification because the tech
    # was never moved off (overlay semantics).
    tech = _seed_user(tenant_id, "technician", department="pool")
    crew = _seed_crew(tenant_id)
    job = _seed_job(tenant_id, technician_id=tech["id"])
    r = requests.post(
        f"{API}/jobs/bulk-reassign",
        headers=_auth(admin["token"], admin["tenant_id"]),
        json={"job_ids": [job["id"]], "new_crew_id": crew["id"]},
    )
    assert r.status_code == 200, r.text
    row = _sync.jobs.find_one({"id": job["id"]},
                                {"_id": 0, "crew_id": 1,
                                 "technician_id": 1})
    # Both dimensions live on the job now.
    assert row["crew_id"] == crew["id"]
    assert row["technician_id"] == tech["id"], (
        "lead tech must be preserved on crew-only reassign"
    )
    # Zero ``job_unassigned`` notifications for this tech.
    notifs = list(_sync.notifications.find(
        {"tenant_id": tenant_id, "user_ids": tech["id"],
         "kind": "job_unassigned"},
    ))
    assert notifs == [], (
        f"crew-only reassign must not fire job_unassigned for lead "
        f"tech; got {notifs}"
    )


# ══════════════════════════════════════════════════════════════════
# GET /jobs?crew_id=... — admin-equivalent list filter
# ══════════════════════════════════════════════════════════════════
def test_list_jobs_filter_by_crew_id(admin, tenant_id):
    crew_a = _seed_crew(tenant_id, name="Crew A")
    crew_b = _seed_crew(tenant_id, name="Crew B")
    job_a = _seed_job(tenant_id, crew_id=crew_a["id"])
    job_b = _seed_job(tenant_id, crew_id=crew_b["id"])
    job_c = _seed_job(tenant_id, crew_id=None)   # unassigned
    r = requests.get(
        f"{API}/jobs",
        params={"crew_id": crew_a["id"]},
        headers=_auth(admin["token"], admin["tenant_id"]),
    )
    assert r.status_code == 200, r.text
    ids = [j["id"] for j in r.json()]
    assert job_a["id"] in ids
    assert job_b["id"] not in ids
    assert job_c["id"] not in ids
