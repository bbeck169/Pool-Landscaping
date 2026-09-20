"""Feb-2026 · Crew Phase A · RBAC gates for crew assignment.

Locks in the role-based access control added in this PR:

  * PUT /api/jobs/{id} with a ``crew_id`` body → allowed for
    admin, super_admin, owner, manager. Rejected 403 for technician
    (even on their own job) and every non-admin role.
  * GET /api/jobs?crew_id=... — admin-equivalent only (403 for
    technicians even though ``scope_jobs_query`` would still limit
    them to their own rows — defense-in-depth).
  * POST /api/jobs/bulk-reassign inherits ``require_admin_or_manager``
    on the dependency so all 4 admin-equivalent roles pass and every
    other role 401/403s.

Kept separate from the assignment-behavior tests
(``test_jobs_crew_assignment.py``) so an RBAC regression is
easy to spot in the report.
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
    tid = f"cra-{uuid.uuid4().hex[:8]}"
    _sync.tenants.insert_one({
        "id": tid, "name": f"CRA {tid}", "slug": f"cra-{tid}",
        "active": True, "widget_allowed_domains": [],
    })
    yield tid
    for col in ("tenants", "users", "crews", "jobs", "customers"):
        _sync[col].delete_many({"tenant_id": tid})


def _seed_user(tenant_id: str, role: str, *,
                department=None,
                technician_id=None) -> dict:
    uid = f"{role}-{uuid.uuid4().hex[:8]}"
    email = f"{uid}@cra.test"
    _sync.users.insert_one({
        "id": uid, "tenant_id": tenant_id, "role": role,
        "name": f"CRA {role}", "email": email,
        "department": department, "technician_id": technician_id,
    })
    return {"id": uid, "email": email, "role": role,
            "tenant_id": tenant_id,
            "technician_id": technician_id,
            "token": _tok(uid, email, role, tenant_id)}


def _seed_crew(tenant_id: str, name: str = "Blue Team") -> dict:
    cid = f"crew-{uuid.uuid4().hex[:8]}"
    doc = {
        "id": cid, "tenant_id": tenant_id, "name": name,
        "color": "#0284C7", "tech_ids": [],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _sync.crews.insert_one(doc)
    return doc


def _seed_job(tenant_id: str, *,
                technician_id=None) -> dict:
    jid = f"job-{uuid.uuid4().hex[:8]}"
    day_iso = datetime.now(timezone.utc).replace(
        hour=10, minute=0, second=0, microsecond=0,
    ).isoformat()
    _sync.jobs.insert_one({
        "id": jid, "tenant_id": tenant_id,
        "title": "RBAC test",
        "service_type": "pool_service",
        "scheduled_date": day_iso, "status": "scheduled",
        "technician_id": technician_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    return {"id": jid}


def _auth(token: str, tenant_id: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "X-Tenant-Id": tenant_id,
    }


# ══════════════════════════════════════════════════════════════════
# PUT /jobs/{id} with crew_id — the 4 admin-equivalent roles pass.
# ══════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("role", ["admin", "super_admin", "owner", "manager"])
def test_admin_equivalent_roles_can_assign_crew(role, tenant_id):
    actor = _seed_user(tenant_id, role)
    crew = _seed_crew(tenant_id)
    job = _seed_job(tenant_id)
    r = requests.put(
        f"{API}/jobs/{job['id']}",
        headers=_auth(actor["token"], actor["tenant_id"]),
        json={"crew_id": crew["id"]},
    )
    assert r.status_code == 200, f"{role} should be allowed: {r.text}"
    row = _sync.jobs.find_one({"id": job["id"]},
                                {"_id": 0, "crew_id": 1})
    assert row["crew_id"] == crew["id"]


# ══════════════════════════════════════════════════════════════════
# Technician cannot assign a crew — even on their own job.
# ══════════════════════════════════════════════════════════════════
def test_technician_cannot_assign_crew_even_on_own_job(tenant_id):
    tech_id = f"tech-rec-{uuid.uuid4().hex[:6]}"
    tech = _seed_user(tenant_id, "technician",
                        technician_id=tech_id, department="pool")
    crew = _seed_crew(tenant_id)
    # Job assigned to this tech — they can PATCH other fields on it,
    # but not crew_id.
    job = _seed_job(tenant_id, technician_id=tech_id)
    r = requests.put(
        f"{API}/jobs/{job['id']}",
        headers=_auth(tech["token"], tech["tenant_id"]),
        json={"crew_id": crew["id"]},
    )
    assert r.status_code == 403, r.text
    assert "crew" in r.text.lower()
    # crew_id must not have been written.
    row = _sync.jobs.find_one({"id": job["id"]},
                                {"_id": 0, "crew_id": 1})
    assert row.get("crew_id") is None


# ══════════════════════════════════════════════════════════════════
# Customer role cannot assign a crew.
# ══════════════════════════════════════════════════════════════════
def test_customer_cannot_assign_crew(tenant_id):
    customer = _seed_user(tenant_id, "customer")
    crew = _seed_crew(tenant_id)
    job = _seed_job(tenant_id)
    r = requests.put(
        f"{API}/jobs/{job['id']}",
        headers=_auth(customer["token"], customer["tenant_id"]),
        json={"crew_id": crew["id"]},
    )
    # ``update_job`` rejects non-technician / non-admin roles 403
    # before we even reach the crew_id gate.
    assert r.status_code == 403, r.text


# ══════════════════════════════════════════════════════════════════
# GET /jobs?crew_id=… — admin-equivalent only (defense-in-depth).
# ══════════════════════════════════════════════════════════════════
def test_technician_cannot_filter_jobs_by_crew_id(tenant_id):
    tech = _seed_user(tenant_id, "technician",
                        technician_id=f"tid-{uuid.uuid4().hex[:6]}",
                        department="pool")
    crew = _seed_crew(tenant_id)
    r = requests.get(
        f"{API}/jobs",
        params={"crew_id": crew["id"]},
        headers=_auth(tech["token"], tech["tenant_id"]),
    )
    # 403 explicit — even though ``scope_jobs_query`` would already
    # limit the tech to their own jobs, we explicitly gate the
    # ``crew_id`` param.
    assert r.status_code == 403, r.text


@pytest.mark.parametrize("role", ["admin", "super_admin", "owner", "manager"])
def test_admin_equivalent_can_filter_jobs_by_crew_id(role, tenant_id):
    actor = _seed_user(tenant_id, role)
    crew = _seed_crew(tenant_id)
    r = requests.get(
        f"{API}/jobs",
        params={"crew_id": crew["id"]},
        headers=_auth(actor["token"], actor["tenant_id"]),
    )
    assert r.status_code == 200, f"{role} should be allowed: {r.text}"


# ══════════════════════════════════════════════════════════════════
# POST /jobs/bulk-reassign — same 4 roles pass; tech/customer 401/403.
# ══════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("role", ["admin", "super_admin", "owner", "manager"])
def test_admin_equivalent_can_bulk_reassign_with_crew(role, tenant_id):
    actor = _seed_user(tenant_id, role)
    crew = _seed_crew(tenant_id)
    job = _seed_job(tenant_id)
    r = requests.post(
        f"{API}/jobs/bulk-reassign",
        headers=_auth(actor["token"], actor["tenant_id"]),
        json={"job_ids": [job["id"]], "new_crew_id": crew["id"]},
    )
    assert r.status_code == 200, f"{role} should be allowed: {r.text}"


def test_technician_bulk_reassign_blocked(tenant_id):
    tech = _seed_user(tenant_id, "technician",
                        technician_id=f"tid-{uuid.uuid4().hex[:6]}",
                        department="pool")
    crew = _seed_crew(tenant_id)
    job = _seed_job(tenant_id)
    r = requests.post(
        f"{API}/jobs/bulk-reassign",
        headers=_auth(tech["token"], tech["tenant_id"]),
        json={"job_ids": [job["id"]], "new_crew_id": crew["id"]},
    )
    # require_admin_or_manager rejects — could be 401 or 403.
    assert r.status_code in (401, 403), r.text
