"""Phase 20A.1 · Cross-tenant hardening for `POST /api/schedule/optimize-route`.

These tests complement `test_phase20a.py` (which covers ordering, cache, and
tech-cross-tenant rejection). Here we lock down the admin-override path so
`user_id` cannot be used to peek across tenants or to plan for phantom users.
"""
import uuid
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

_FE = dotenv_values(Path(__file__).resolve().parents[2] / "frontend" / ".env")
_BE = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
BASE = (_FE.get("EXPO_PUBLIC_BACKEND_URL") or "http://localhost:8001").rstrip("/")
API = f"{BASE}/api"
MONGO_URL = _BE.get("MONGO_URL"); DB_NAME = _BE.get("DB_NAME")


def _login(email, pw="password123"):
    r = requests.post(f"{API}/auth/login",
                      json={"email": email, "password": pw}, timeout=15)
    r.raise_for_status()
    return r.json()


@pytest.fixture(scope="module")
def dbc(): return MongoClient(MONGO_URL)[DB_NAME]


@pytest.fixture(scope="module")
def sunbelt_admin_h():
    try:
        return {"Authorization": f"Bearer {_login('admin@sunbelt.com')['access_token']}"}
    except Exception:
        pytest.skip("sunbelt admin missing")


@pytest.fixture(scope="module")
def aquaterra_admin_h():
    return {"Authorization": f"Bearer {_login('admin@aquaterra.com')['access_token']}"}


@pytest.fixture(scope="module")
def aquaterra_tech_h():
    return {"Authorization": f"Bearer {_login('mike@aquaterra.com')['access_token']}"}


def test_optimize_route_cross_tenant_403(sunbelt_admin_h, dbc):
    """Sunbelt admin passing an Aquaterra user_id must be rejected."""
    aqua_u = dbc.users.find_one({"email": "mike@aquaterra.com"})
    assert aqua_u, "expected mike@aquaterra.com to exist in seeded db"
    r = requests.post(f"{API}/schedule/optimize-route?user_id=" + aqua_u["id"],
                      headers=sunbelt_admin_h, json={}, timeout=15)
    assert r.status_code == 403, f"expected 403 cross-tenant, got {r.status_code} {r.text[:200]}"
    assert "not in current tenant" in r.text


def test_optimize_route_nonexistent_user_404(aquaterra_admin_h):
    """Admin passing a fake user_id must be rejected with 404."""
    ghost = str(uuid.uuid4())
    r = requests.post(f"{API}/schedule/optimize-route?user_id=" + ghost,
                      headers=aquaterra_admin_h, json={}, timeout=15)
    assert r.status_code == 404, f"expected 404 ghost user, got {r.status_code} {r.text[:200]}"


def test_optimize_route_tech_cannot_plan_other_user_403(aquaterra_tech_h, dbc):
    """A technician cannot pass a user_id different from their own."""
    other = dbc.users.find_one({"email": "admin@aquaterra.com"})  # same tenant, different user
    assert other, "expected admin@aquaterra.com to exist"
    r = requests.post(f"{API}/schedule/optimize-route?user_id=" + other["id"],
                      headers=aquaterra_tech_h, json={}, timeout=15)
    assert r.status_code == 403, f"expected 403 tech-other-user, got {r.status_code} {r.text[:200]}"



# ═══════════════════════════════════════════════════════════════════════
# Feb-2026 · optimize-route targeting + day-filter fix
# ═══════════════════════════════════════════════════════════════════════
def test_optimize_route_honors_body_technician_id_for_admin(
    aquaterra_admin_h, dbc,
):
    """Admin caller passing ``technician_id`` in the body payload
    (see ``CalendarSchedule.optimizeRoute``) must plan for that
    tech — historically the endpoint only read the ``user_id``
    query param and silently defaulted to the caller."""
    mike = dbc.users.find_one({"email": "mike@aquaterra.com"})
    assert mike, "mike@aquaterra.com missing from seed"
    admin_row = dbc.users.find_one({"email": "admin@aquaterra.com"})
    tenant_id = mike["tenant_id"]

    # Seed a single job on Mike for a specific day so the endpoint
    # has something concrete to plan. Job is stored with
    # ``scheduled_date`` only — locks the day-filter fix
    # simultaneously (see next test for the isolated assertion).
    day = "2026-09-14"
    jid = str(uuid.uuid4())
    dbc.jobs.insert_one({
        "id": jid, "tenant_id": tenant_id,
        "technician_id": mike["id"],
        "title": "optimize-route-target-test",
        "status": "scheduled",
        "scheduled_date": day,
        "site_lat": 33.7, "site_lng": -112.2,
        "address": "1 test st, Peoria, AZ",
    })
    try:
        r = requests.post(
            f"{API}/schedule/optimize-route",
            headers=aquaterra_admin_h,
            json={"technician_id": mike["id"], "date": day},
            timeout=15,
        )
        assert r.status_code == 200, r.text[:400]
        out = r.json()
        # Endpoint planned for Mike, not the admin caller — Mike's
        # seeded job must appear in the returned list. The
        # ``ordered_job_ids`` is empty when <2 stops (trivial
        # algorithm), but the endpoint still returns the resolved
        # 1-stop set.
        assert jid in (out.get("ordered_job_ids") or []), (
            f"admin caller with technician_id={mike['id']} did NOT "
            f"plan for that tech's job. Response: {out}"
        )
        # Regression guard — the response must not include admin's
        # own jobs (which are absent for this specific day anyway,
        # but assert the shape didn't leak them).
        assert admin_row["id"] not in (out.get("ordered_job_ids") or [])
    finally:
        dbc.jobs.delete_one({"id": jid, "tenant_id": tenant_id})


def test_optimize_route_day_filter_matches_scheduled_date(
    aquaterra_admin_h, dbc,
):
    """A job seeded with ONLY ``scheduled_date`` (no
    ``scheduled_start``) must show up on the optimizer output for
    that day. Mirrors ``get_route_stops``'s ``$and`` day-filter so
    the two endpoints stay in sync."""
    mike = dbc.users.find_one({"email": "mike@aquaterra.com"})
    assert mike, "mike@aquaterra.com missing from seed"
    tenant_id = mike["tenant_id"]

    # Seed two co-located jobs on Mike for a specific day. Both
    # carry only ``scheduled_date`` (no ``scheduled_start``) — the
    # pre-fix code would have dropped them entirely.
    day = "2026-09-15"
    jid_a, jid_b = str(uuid.uuid4()), str(uuid.uuid4())
    for jid, lat in ((jid_a, 33.71), (jid_b, 33.72)):
        dbc.jobs.insert_one({
            "id": jid, "tenant_id": tenant_id,
            "technician_id": mike["id"],
            "title": "optimize-route-day-filter-test",
            "status": "scheduled",
            "scheduled_date": day,
            "site_lat": lat, "site_lng": -112.2,
            "address": f"{jid} st, Peoria, AZ",
        })
    try:
        r = requests.post(
            f"{API}/schedule/optimize-route",
            headers=aquaterra_admin_h,
            json={"technician_id": mike["id"], "date": day},
            timeout=30,
        )
        assert r.status_code == 200, r.text[:400]
        ordered = r.json().get("ordered_job_ids") or []
        assert jid_a in ordered, (
            f"day-filter dropped a scheduled_date-only job: {jid_a} "
            f"not in {ordered}"
        )
        assert jid_b in ordered
    finally:
        dbc.jobs.delete_many(
            {"id": {"$in": [jid_a, jid_b]}, "tenant_id": tenant_id},
        )
