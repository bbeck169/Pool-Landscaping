"""Feb-2026 · Crew Phase A · ``/api/schedule/today`` crew visibility.

Locks in the ``$or`` widening in ``backend/routers/schedule.py``
that adds a ``{"crew_id": {"$in": my_crew_ids}}`` branch so every
crew member sees the crew's jobs on their personal schedule.

Coverage per the Phase A brief:
  1. Crew members see a crew-assigned job on ``/schedule/today``.
  2. A tech NOT in the crew does not see the same job.
  3. Overlay — lead tech (``technician_id`` still set) plus every
     crew member see the job; a non-member tech does not.
  4. Immediate member removal — a tech pulled from the crew loses
     visibility on the next call (no snapshot; the ``$or`` re-fetches
     ``crew.tech_ids`` on every request).
  5. Cross-tenant guard — a crew from tenant B is not visible from
     tenant A.
  6. Empty-crew guard — a user with zero crews still gets the base
     3-clause ``$or`` filter (no ``{"$in": []}`` no-op branch).

Harness mirrors ``test_phase26_bulk_apply_departments.py`` (sync
PyMongo for setup + HTTP against the live pod; signed JWTs).
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


# ══════════════════════════════════════════════════════════════════
# Fixtures — one tenant per test, cleaned on teardown.
# ══════════════════════════════════════════════════════════════════
@pytest.fixture()
def tenant_id():
    tid = f"csv-{uuid.uuid4().hex[:8]}"
    _sync.tenants.insert_one({
        "id": tid, "name": f"CSV {tid}", "slug": f"csv-{tid}",
        "active": True, "widget_allowed_domains": [],
    })
    yield tid
    for col in ("tenants", "users", "technicians", "crews", "jobs",
                 "customers", "audit_log", "time_entries"):
        _sync[col].delete_many({"tenant_id": tid})


def _seed_user(tenant_id: str, role: str, *,
                department=None) -> dict:
    uid = f"{role}-{uuid.uuid4().hex[:8]}"
    email = f"{uid}@csv.test"
    _sync.users.insert_one({
        "id": uid, "tenant_id": tenant_id, "role": role,
        "name": f"CSV {role}", "email": email,
        "department": department,
        "technician_id": None,
    })
    return {"id": uid, "email": email, "role": role,
            "tenant_id": tenant_id,
            "token": _tok(uid, email, role, tenant_id)}


def _seed_crew(tenant_id: str, member_user_ids: list[str],
                name: str = "Blue Team") -> dict:
    cid = f"crew-{uuid.uuid4().hex[:8]}"
    doc = {
        "id": cid, "tenant_id": tenant_id, "name": name,
        "color": "#0284C7", "tech_ids": list(member_user_ids),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _sync.crews.insert_one(doc)
    return doc


def _seed_job(tenant_id: str, *, day_iso: str,
                technician_id: str | None = None,
                crew_id: str | None = None) -> dict:
    jid = f"job-{uuid.uuid4().hex[:8]}"
    doc = {
        "id": jid, "tenant_id": tenant_id,
        "title": "Crew Phase A visibility test",
        "service_type": "pool_service",
        "scheduled_date": day_iso,
        "status": "scheduled",
        "technician_id": technician_id,
        "crew_id": crew_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _sync.jobs.insert_one(doc)
    return doc


def _auth(token: str, tenant_id: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "X-Tenant-Id": tenant_id,
    }


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _today_iso() -> str:
    # ISO datetime that falls inside today's UTC bounds.
    return datetime.now(timezone.utc).replace(
        hour=10, minute=0, second=0, microsecond=0,
    ).isoformat()


def _fetch_today(user: dict) -> list[dict]:
    r = requests.get(
        f"{API}/schedule/today",
        params={"date": _today()},
        headers=_auth(user["token"], user["tenant_id"]),
    )
    assert r.status_code == 200, r.text
    # Endpoint returns ``{"items": [...]}`` where the items array
    # mixes job entries + time-entry entries; the ``type`` tag
    # discriminates. Only job items have a canonical ``id`` that
    # matches our seed doc.
    items = r.json().get("items") or []
    return [i for i in items if i.get("type") == "job"]


# ══════════════════════════════════════════════════════════════════
# 1 · Crew members see a crew-only job on /schedule/today.
# ══════════════════════════════════════════════════════════════════
def test_crew_members_see_crew_only_job(tenant_id):
    mike = _seed_user(tenant_id, "technician", department="pool")
    alex = _seed_user(tenant_id, "technician", department="landscaping")
    _seed_crew(tenant_id, [mike["id"], alex["id"]])
    job = _seed_job(
        tenant_id, day_iso=_today_iso(),
        technician_id=None,   # crew-only, no lead tech
        crew_id=_sync.crews.find_one({"tenant_id": tenant_id})["id"],
    )
    mike_jobs = [j["id"] for j in _fetch_today(mike)]
    alex_jobs = [j["id"] for j in _fetch_today(alex)]
    assert job["id"] in mike_jobs, f"mike must see the crew job, got {mike_jobs}"
    assert job["id"] in alex_jobs, f"alex must see the crew job, got {alex_jobs}"


# ══════════════════════════════════════════════════════════════════
# 2 · A tech NOT in the crew does NOT see the crew job.
# ══════════════════════════════════════════════════════════════════
def test_non_member_does_not_see_crew_job(tenant_id):
    mike = _seed_user(tenant_id, "technician", department="pool")
    bob  = _seed_user(tenant_id, "technician", department="pool")
    crew = _seed_crew(tenant_id, [mike["id"]])
    job  = _seed_job(
        tenant_id, day_iso=_today_iso(),
        technician_id=None, crew_id=crew["id"],
    )
    bob_jobs = [j["id"] for j in _fetch_today(bob)]
    assert job["id"] not in bob_jobs, (
        f"bob is not in the crew — should not see the job. Got {bob_jobs}"
    )
    # Sanity — mike (a member) still sees it.
    mike_jobs = [j["id"] for j in _fetch_today(mike)]
    assert job["id"] in mike_jobs


# ══════════════════════════════════════════════════════════════════
# 3 · Overlay — lead tech + crew members both see it.
#      A non-member tech still does not.
# ══════════════════════════════════════════════════════════════════
def test_overlay_lead_and_crew_both_visible(tenant_id):
    lead = _seed_user(tenant_id, "technician", department="pool")
    alex = _seed_user(tenant_id, "technician", department="pool")
    bob  = _seed_user(tenant_id, "technician", department="pool")
    crew = _seed_crew(tenant_id, [lead["id"], alex["id"]])
    job  = _seed_job(
        tenant_id, day_iso=_today_iso(),
        technician_id=lead["id"], crew_id=crew["id"],
    )
    # Lead sees it via the ``technician_id`` clause.
    assert job["id"] in [j["id"] for j in _fetch_today(lead)]
    # Alex sees it via the ``crew_id`` clause.
    assert job["id"] in [j["id"] for j in _fetch_today(alex)]
    # Bob (not a crew member) does not see it.
    assert job["id"] not in [j["id"] for j in _fetch_today(bob)]


# ══════════════════════════════════════════════════════════════════
# 4 · Immediate member removal — no snapshot, live tech_ids lookup.
# ══════════════════════════════════════════════════════════════════
def test_member_removal_immediately_hides_crew_job(tenant_id):
    mike = _seed_user(tenant_id, "technician", department="pool")
    alex = _seed_user(tenant_id, "technician", department="pool")
    crew = _seed_crew(tenant_id, [mike["id"], alex["id"]])
    job  = _seed_job(
        tenant_id, day_iso=_today_iso(),
        technician_id=None, crew_id=crew["id"],
    )
    # Baseline — alex sees the job.
    assert job["id"] in [j["id"] for j in _fetch_today(alex)]
    # Remove alex from the crew.
    _sync.crews.update_one(
        {"id": crew["id"]},
        {"$pull": {"tech_ids": alex["id"]}},
    )
    # Very next request — alex no longer sees the crew job.
    assert job["id"] not in [j["id"] for j in _fetch_today(alex)]
    # But mike still does (he's still a member).
    assert job["id"] in [j["id"] for j in _fetch_today(mike)]


# ══════════════════════════════════════════════════════════════════
# 5 · Cross-tenant — crew in tenant B invisible from tenant A.
# ══════════════════════════════════════════════════════════════════
def test_cross_tenant_crew_invisible(tenant_id):
    # tenant_id fixture is tenant A.
    mike_a = _seed_user(tenant_id, "technician", department="pool")
    # Bootstrap tenant B by hand — no fixture for it, and we
    # clean it in this test's finally.
    tb = f"csvB-{uuid.uuid4().hex[:8]}"
    _sync.tenants.insert_one({
        "id": tb, "name": f"CSV B {tb}", "slug": tb, "active": True,
        "widget_allowed_domains": [],
    })
    try:
        mike_b_uid = f"technician-{uuid.uuid4().hex[:8]}"
        _sync.users.insert_one({
            "id": mike_b_uid, "tenant_id": tb, "role": "technician",
            "email": f"{mike_b_uid}@csvb.test", "name": "CSV B tech",
            "department": "pool", "technician_id": None,
        })
        # Crew in tenant B contains mike_a's id (attacker-crafted).
        _sync.crews.insert_one({
            "id": f"crew-{uuid.uuid4().hex[:8]}", "tenant_id": tb,
            "name": "Attacker Crew", "color": "#000000",
            "tech_ids": [mike_a["id"]],
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        crew_b_id = _sync.crews.find_one({"tenant_id": tb})["id"]
        job_b = _seed_job(
            tb, day_iso=_today_iso(),
            technician_id=None, crew_id=crew_b_id,
        )
        # Even though tenant B's crew has mike_a in tech_ids, the
        # tenant guard on the crew prefetch (``tenant_id: tid``)
        # scopes the ``$in`` list to tenant A only, so mike_a's
        # tenant-A schedule_today does NOT include the tenant-B job.
        assert job_b["id"] not in [j["id"] for j in _fetch_today(mike_a)]
    finally:
        for col in ("tenants", "users", "crews", "jobs"):
            _sync[col].delete_many({"tenant_id": tb})


# ══════════════════════════════════════════════════════════════════
# 6 · Empty-crew guard — user with zero crews still gets base filter.
#      Regression guard against a ``$in: []`` slip-through that
#      would silently drop every non-tech-matching job.
# ══════════════════════════════════════════════════════════════════
def test_user_in_zero_crews_still_sees_own_jobs(tenant_id):
    mike = _seed_user(tenant_id, "technician", department="pool")
    job  = _seed_job(
        tenant_id, day_iso=_today_iso(),
        technician_id=mike["id"], crew_id=None,
    )
    # No crew seeded — the crew-clause branch must skip cleanly.
    assert job["id"] in [j["id"] for j in _fetch_today(mike)]
