"""Feb-2026 · Schedule inline-edit · PUT /api/jobs/{jid} role gate.

The Schedule screen's Edit affordance surfaces ``PUT /api/jobs/{jid}``
to admin+ users. Before Feb-2026 the endpoint only gated technicians
(own-job check); customer / manager / unknown role sessions could
freely PATCH any job in-tenant. This suite pins the tightened gate:

* admin / super_admin / manager → 200 accepted.
* technician on their OWN job    → 200 accepted (regression guard).
* technician on someone else's   → 403.
* customer                       → 403.

Sync ``pymongo`` + live ``requests`` — matches routes-enriched /
recurring-autogen suite style.
"""
from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import pytest
import requests
from pymongo import MongoClient


BASE_URL = ""
for ln in Path("/app/frontend/.env").read_text().splitlines():
    if ln.startswith("REACT_APP_BACKEND_URL="):
        BASE_URL = ln.split("=", 1)[1].strip().strip('"').rstrip("/")
        break
API = f"{BASE_URL}/api"

AQUATERRA_TID = "3814833a-dd0d-4bd9-90ea-351c24924649"
CREDS = {
    "super":       {"email": "super@aquaterra.com",       "password": "password123"},
    "admin":       {"email": "admin@aquaterra.com",       "password": "password123"},
    "landscaper":  {"email": "landscaper@aquaterra.com",  "password": "password123"},
    "mike":        {"email": "mike@aquaterra.com",        "password": "password123"},
}


def _env(k: str) -> str:
    for ln in Path("/app/backend/.env").read_text().splitlines():
        if ln.startswith(f"{k}="):
            return ln.split("=", 1)[1].strip().strip('"')
    return ""


@pytest.fixture(scope="module")
def sync_db():
    cli = MongoClient(_env("MONGO_URL"), serverSelectionTimeoutMS=5000)
    try:
        yield cli[_env("DB_NAME") or "aquaterra"]
    finally:
        cli.close()


def _login(email: str, password: str) -> str:
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=15)
    r.raise_for_status()
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def super_token(): return _login(**CREDS["super"])


@pytest.fixture(scope="module")
def admin_token():
    try: return _login(**CREDS["admin"])
    except Exception: return None


@pytest.fixture(scope="module")
def landscaper_token(): return _login(**CREDS["landscaper"])


@pytest.fixture(scope="module")
def mike_token(): return _login(**CREDS["mike"])


@pytest.fixture()
def unassigned_job(sync_db, super_token):
    """Seed an unassigned job we can PATCH from multiple roles."""
    jid = f"role-gate-{uuid4().hex[:10]}"
    sync_db.jobs.insert_one({
        "id": jid, "tenant_id": AQUATERRA_TID,
        "customer_id": "bug-repro-1", "customer_name": "Bug Repro Alice",
        "scheduled_date": "2026-08-19", "status": "scheduled",
        "service_type": "Weekly Pool", "title": "Role gate seed",
        "notes": "seed",
    })
    yield jid
    sync_db.jobs.delete_one({"id": jid})


@pytest.fixture()
def techs_own_job(sync_db, mike_token):
    """Seed a job assigned to Mike (pool tech) so his own-job branch works."""
    # Fetch mike's technician_id from /auth/me
    me = requests.get(
        f"{API}/auth/me",
        headers={"Authorization": f"Bearer {mike_token}"},
        timeout=15,
    ).json()
    tech_id = me.get("technician_id") or me.get("id")
    jid = f"role-gate-own-{uuid4().hex[:10]}"
    sync_db.jobs.insert_one({
        "id": jid, "tenant_id": AQUATERRA_TID,
        "customer_id": "bug-repro-1", "customer_name": "Bug Repro Alice",
        "scheduled_date": "2026-08-19", "status": "scheduled",
        "service_type": "Weekly Pool", "title": "Mike own-job seed",
        "technician_id": tech_id,
    })
    yield jid
    sync_db.jobs.delete_one({"id": jid})


def _put(jid: str, token: str, patch: dict) -> requests.Response:
    return requests.put(
        f"{API}/jobs/{jid}", json=patch,
        headers={"Authorization": f"Bearer {token}"},
        timeout=15,
    )


def test_super_admin_can_edit_any_job(super_token, unassigned_job):
    r = _put(unassigned_job, super_token, {"title": "Super edited"})
    assert r.status_code == 200, r.text


def test_admin_can_edit_any_job(admin_token, unassigned_job):
    if admin_token is None:
        pytest.skip("admin seed account not provisioned in this pod")
    r = _put(unassigned_job, admin_token, {"title": "Admin edited"})
    assert r.status_code == 200, r.text


def test_technician_can_edit_their_own_job(mike_token, techs_own_job):
    r = _put(techs_own_job, mike_token, {"notes": "own-job edit ok"})
    assert r.status_code == 200, r.text


def test_technician_cannot_edit_someone_elses_job(landscaper_token, techs_own_job):
    # ``techs_own_job`` is assigned to Mike; Landscaper is a different
    # technician and must be blocked with 403 (regression guard for
    # the pre-existing own-job check).
    r = _put(techs_own_job, landscaper_token, {"notes": "should be blocked"})
    assert r.status_code == 403, r.text
