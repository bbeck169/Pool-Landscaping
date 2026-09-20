"""Feb-2026 · Backlog Item 3 — crew-only jobs surface on individual tech schedules.

Root case: crew_id-assigned jobs (with no ``technician_id``) were
invisible on individual crew-members' ``/schedule`` views because
``scope_jobs_query`` filtered strictly by ``technician_id``. The
fix extends the query so a tech sees jobs where EITHER
``technician_id == user's tech id`` OR ``crew_id IN user's crews``.

Rules the suite locks:

  1. A tech who's a member of crew X sees crew-only jobs assigned
     to crew X (no explicit ``technician_id``).
  2. A tech NOT in crew X does NOT see those jobs.
  3. A tech's own jobs (with matching ``technician_id``) still
     show up — no regression on the existing filter.
  4. Admin listings unchanged (they still see everything).
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

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

_TOK: dict = {}


def _login(email: str, password: str = "password123") -> tuple[str, dict]:
    key = f"tok:{email}"
    if key in _TOK:
        return _TOK[key]
    r = requests.post(
        f"{API}/auth/login",
        json={"email": email, "password": password}, timeout=30,
    )
    r.raise_for_status()
    tok = r.json()["access_token"]
    me = requests.get(
        f"{API}/auth/me",
        headers={"Authorization": f"Bearer {tok}"}, timeout=30,
    ).json()
    _TOK[key] = (tok, me)
    return tok, me


_PREFIX = f"crewscope-{uuid.uuid4().hex[:8]}"


def _seed_crew_only_job(*, tenant_id: str, crew_id: str) -> str:
    jid = f"{_PREFIX}-job-{uuid.uuid4().hex[:6]}"
    _sync.jobs.insert_one({
        "id": jid, "tenant_id": tenant_id,
        "title": f"Crew-scope test job {jid[-6:]}",
        "customer_id": "seed-customer",
        "customer_name": "Seed",
        "property_id": None,
        "service_type": "Pool Cleaning",
        "scheduled_date": "2026-08-31",
        "arrival_window": "9-10am",
        "status": "scheduled",
        "crew_id": crew_id,
        # NB: NO ``technician_id`` — this is the exact shape the
        # bug was about.
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    return jid


def _seed_direct_tech_job(*, tenant_id: str, technician_id: str) -> str:
    jid = f"{_PREFIX}-job-{uuid.uuid4().hex[:6]}"
    _sync.jobs.insert_one({
        "id": jid, "tenant_id": tenant_id,
        "title": f"Direct-tech test job {jid[-6:]}",
        "customer_id": "seed-customer",
        "customer_name": "Seed",
        "property_id": None,
        "service_type": "Pool Cleaning",
        "scheduled_date": "2026-08-31",
        "arrival_window": "9-10am",
        "status": "scheduled",
        "technician_id": technician_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    return jid


def _seed_crew(*, tenant_id: str, name: str, tech_ids: list) -> str:
    cid = f"{_PREFIX}-crew-{uuid.uuid4().hex[:6]}"
    _sync.crews.insert_one({
        "id": cid, "tenant_id": tenant_id,
        "name": name, "tech_ids": tech_ids,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    return cid


def _cleanup() -> None:
    _sync.jobs.delete_many({"id": {"$regex": f"^{_PREFIX}"}})
    _sync.crews.delete_many({"id": {"$regex": f"^{_PREFIX}"}})


def setup_module(module):
    _cleanup()


def teardown_module(module):
    _cleanup()


# ══════════════════════════════════════════════════════════════════════
# 1 · Tech in the crew sees the crew-only job.
# ══════════════════════════════════════════════════════════════════════
def test_tech_in_crew_sees_crew_only_jobs():
    # ``mike@aquaterra.com`` is a tech seeded in the aquaterra tenant.
    tok, me = _login("mike@aquaterra.com")
    tid = me.get("tenant_id")
    tech_pk = me.get("technician_id")
    assert tech_pk, "seed regression — mike must carry technician_id"
    crew_id = _seed_crew(
        tenant_id=tid, name="Test crew · Mike included",
        tech_ids=[tech_pk, "some-other-tech"],
    )
    job_id = _seed_crew_only_job(tenant_id=tid, crew_id=crew_id)
    try:
        r = requests.get(
            f"{API}/jobs?limit=2000",
            headers={"Authorization": f"Bearer {tok}"}, timeout=30,
        )
        assert r.status_code == 200, r.text
        rows = r.json()
        ids = {row["id"] for row in rows}
        assert job_id in ids, (
            "crew-only job must appear on the crew member's schedule "
            f"(saw {len(ids)} jobs but not the seeded one)"
        )
    finally:
        _sync.jobs.delete_one({"id": job_id})
        _sync.crews.delete_one({"id": crew_id})


# ══════════════════════════════════════════════════════════════════════
# 2 · Tech NOT in the crew does not see the crew-only job.
# ══════════════════════════════════════════════════════════════════════
def test_tech_not_in_crew_does_not_see_crew_only_jobs():
    tok_mike, mike = _login("mike@aquaterra.com")
    tok_carlos, carlos = _login("carlos@aquaterra.com")
    tid = mike.get("tenant_id")
    tech_pk_mike = mike.get("technician_id")
    tech_pk_carlos = carlos.get("technician_id")
    assert tech_pk_mike and tech_pk_carlos
    assert tech_pk_mike != tech_pk_carlos
    # Crew has ONLY Carlos, not Mike.
    crew_id = _seed_crew(
        tenant_id=tid, name="Carlos-only crew", tech_ids=[tech_pk_carlos],
    )
    job_id = _seed_crew_only_job(tenant_id=tid, crew_id=crew_id)
    try:
        r = requests.get(
            f"{API}/jobs?limit=2000",
            headers={"Authorization": f"Bearer {tok_mike}"}, timeout=30,
        )
        assert r.status_code == 200
        ids = {row["id"] for row in r.json()}
        assert job_id not in ids, (
            "tech OUTSIDE the crew must not see the crew-only job"
        )
        # Carlos SHOULD see it.
        r2 = requests.get(
            f"{API}/jobs?limit=2000",
            headers={"Authorization": f"Bearer {tok_carlos}"}, timeout=30,
        )
        ids2 = {row["id"] for row in r2.json()}
        assert job_id in ids2, (
            "the crew member (Carlos) must see the crew-only job"
        )
    finally:
        _sync.jobs.delete_one({"id": job_id})
        _sync.crews.delete_one({"id": crew_id})


# ══════════════════════════════════════════════════════════════════════
# 3 · No regression — a tech's directly-assigned jobs still show up.
# ══════════════════════════════════════════════════════════════════════
def test_tech_still_sees_own_directly_assigned_jobs():
    tok, me = _login("mike@aquaterra.com")
    tid = me.get("tenant_id")
    tech_pk = me.get("technician_id")
    direct_id = _seed_direct_tech_job(
        tenant_id=tid, technician_id=tech_pk,
    )
    try:
        r = requests.get(
            f"{API}/jobs?limit=2000",
            headers={"Authorization": f"Bearer {tok}"}, timeout=30,
        )
        ids = {row["id"] for row in r.json()}
        assert direct_id in ids, (
            "direct-tech job regressed — must still appear on "
            "the tech's schedule after the crew-scope expansion"
        )
    finally:
        _sync.jobs.delete_one({"id": direct_id})


# ══════════════════════════════════════════════════════════════════════
# 4 · Admin listings are unaffected (still see everything).
# ══════════════════════════════════════════════════════════════════════
def test_admin_listing_still_sees_all_jobs():
    tok_admin, _ = _login("admin@aquaterra.com")
    tok_mike, mike = _login("mike@aquaterra.com")
    tid = mike.get("tenant_id")
    crew_id = _seed_crew(
        tenant_id=tid, name="Admin-view test crew",
        tech_ids=[mike.get("technician_id")],
    )
    job_id = _seed_crew_only_job(tenant_id=tid, crew_id=crew_id)
    try:
        r = requests.get(
            f"{API}/jobs?limit=2000",
            headers={"Authorization": f"Bearer {tok_admin}"}, timeout=30,
        )
        ids = {row["id"] for row in r.json()}
        assert job_id in ids, "admin regressed — must see all jobs"
    finally:
        _sync.jobs.delete_one({"id": job_id})
        _sync.crews.delete_one({"id": crew_id})
