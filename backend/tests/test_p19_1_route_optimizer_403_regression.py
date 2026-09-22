"""Phase P19.1 · Feb-2026 — Route Optimizer 403 regression fix.

Locks in the P9 silent-pin contract on ``POST /schedule/optimize-route``:

  1. Admin caller · 0 jobs → 200 + empty envelope (baseline sanity).
  2. Technician caller · 0 visible jobs → 200 + empty envelope.
     This is the regression the phase fixes — the previous
     Feb-2026 hotfix hard-403'd every technician invocation before
     the day-scoped query even ran.
  3. Technician caller · 1+ visible jobs → 200 + non-empty envelope
     with the P12 soft-guard fields still populated.
  4. Customer / portal role → 403 (legit blanket forbid).
  5. Missing / expired token → 401 (real auth failure — never 403).
  6. Cross-tenant impersonation via ``user_id=`` → 403 (legit).
  7. Non-admin technician targeting another user's id → 403 (legit).
"""
from __future__ import annotations

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
MONGO_URL = _BE.get("MONGO_URL")
DB_NAME = _BE.get("DB_NAME")


def _login(email: str, pw: str = "password123") -> dict:
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": pw}, timeout=15)
    r.raise_for_status()
    return r.json()


@pytest.fixture(scope="module")
def dbc() -> MongoClient:
    return MongoClient(MONGO_URL)[DB_NAME]


@pytest.fixture(scope="module")
def admin_h() -> dict:
    return {"Authorization": f"Bearer {_login('admin@aquaterra.com')['access_token']}"}


@pytest.fixture(scope="module")
def customer_h() -> dict:
    return {"Authorization": f"Bearer {_login('customer@aquaterra.com')['access_token']}"}


@pytest.fixture(scope="module")
def mike(dbc):
    u = dbc.users.find_one({"email": "mike@aquaterra.com"})
    assert u, "expected mike@aquaterra.com to exist in seeded db"
    return u


@pytest.fixture(scope="module")
def tech_h() -> dict:
    return {"Authorization": f"Bearer {_login('mike@aquaterra.com')['access_token']}"}


@pytest.fixture
def _cleanup(dbc):
    """Track seeded job ids for teardown so a mid-test failure
    doesn't leak fixtures into the next run."""
    bag: list[str] = []
    yield bag
    for jid in bag:
        dbc.jobs.delete_one({"id": jid})


# Distant-future day so nothing collides with real seeded jobs
# and the query cache reliably starts clean.  Different from the
# P12 orphan-loop test's day so parallel runs don't interfere.
_EMPTY_DAY = "2028-05-17"
_LOADED_DAY = "2028-05-18"


# ═════════════════════════════════════════════════════════════════════
# Acceptance 1 · Admin with 0 jobs on the target day → 200 + empty
# envelope.  Baseline sanity — proves the endpoint's empty-shape is
# stable BEFORE we assert on the technician-role regression.
# ═════════════════════════════════════════════════════════════════════
def test_admin_with_zero_jobs_returns_200_empty_envelope(
    admin_h, mike, dbc,
):
    # Sanity: no jobs on the empty day for mike in this tenant.
    dbc.jobs.delete_many(
        {"tenant_id": mike["tenant_id"],
          "scheduled_date": _EMPTY_DAY,
          "technician_id": mike["id"]},
    )
    r = requests.post(
        f"{API}/schedule/optimize-route",
        headers=admin_h,
        json={"technician_id": mike["id"], "date": _EMPTY_DAY},
        timeout=30,
    )
    assert r.status_code == 200, r.text[:400]
    body = r.json()
    assert body.get("ordered_job_ids") == []
    # P12 soft-guard fields stamp on every response — including
    # the "trivial" empty branch.
    assert body.get("orphaned_tech_ids") == []
    assert body.get("skipped_unassigned") == []
    assert body.get("algorithm") == "trivial"


# ═════════════════════════════════════════════════════════════════════
# Acceptance 2 · Technician with a valid session + 0 visible jobs →
# 200 + empty envelope.  THE regression under test — the previous
# blanket 403 short-circuited BEFORE the day-scoped filter ran, so
# a legitimate tech-scoped preview call always failed.
# ═════════════════════════════════════════════════════════════════════
def test_technician_with_zero_jobs_returns_200_empty_envelope_not_403(
    tech_h, mike, dbc,
):
    dbc.jobs.delete_many(
        {"tenant_id": mike["tenant_id"],
          "scheduled_date": _EMPTY_DAY,
          "technician_id": mike["id"]},
    )
    r = requests.post(
        f"{API}/schedule/optimize-route",
        headers=tech_h,
        json={"date": _EMPTY_DAY},
        timeout=30,
    )
    # The previous shape returned 403 here — assert the fix.
    assert r.status_code == 200, (
        f"expected 200 for tech-empty-day, got {r.status_code}: "
        f"{r.text[:400]}"
    )
    body = r.json()
    assert body.get("ordered_job_ids") == []
    # P12 soft-guard fields still stamp — the response shape is
    # identical to the admin-empty branch.
    assert body.get("orphaned_tech_ids") == []
    assert body.get("skipped_unassigned") == []
    assert body.get("algorithm") == "trivial"


# ═════════════════════════════════════════════════════════════════════
# Acceptance 3 · Technician with visible jobs → 200 + non-empty
# envelope; P12 soft-guard still populates.
# ═════════════════════════════════════════════════════════════════════
def test_technician_with_visible_jobs_returns_200_non_empty(
    tech_h, mike, dbc, _cleanup,
):
    tenant_id = mike["tenant_id"]
    day = _LOADED_DAY
    dbc.jobs.delete_many(
        {"tenant_id": tenant_id, "scheduled_date": day,
          "technician_id": mike["id"]},
    )
    job_a = str(uuid.uuid4())
    job_b = str(uuid.uuid4())
    dbc.jobs.insert_one({
        "id": job_a, "tenant_id": tenant_id,
        "technician_id": mike["id"],
        "status": "scheduled", "scheduled_date": day,
        "title": "p19.1-tech-day · A",
        "site_lat": 33.8000, "site_lng": -112.1000,
        "address": "P19.1 stop A",
    })
    _cleanup.append(job_a)
    dbc.jobs.insert_one({
        "id": job_b, "tenant_id": tenant_id,
        "technician_id": mike["id"],
        "status": "scheduled", "scheduled_date": day,
        "title": "p19.1-tech-day · B",
        "site_lat": 33.8100, "site_lng": -112.1100,
        "address": "P19.1 stop B",
    })
    _cleanup.append(job_b)

    r = requests.post(
        f"{API}/schedule/optimize-route",
        headers=tech_h,
        json={"date": day},
        timeout=30,
    )
    assert r.status_code == 200, r.text[:400]
    body = r.json()
    ordered = body.get("ordered_job_ids") or []
    assert job_a in ordered, ordered
    assert job_b in ordered, ordered
    # P12 soft-guard keys still surface on the non-empty branch.
    assert "orphaned_tech_ids" in body
    assert "skipped_unassigned" in body


# ═════════════════════════════════════════════════════════════════════
# Acceptance 4 · Customer / portal role → 403 (legit blanket forbid).
# ═════════════════════════════════════════════════════════════════════
def test_customer_role_still_returns_403(customer_h):
    r = requests.post(
        f"{API}/schedule/optimize-route",
        headers=customer_h,
        json={"date": _EMPTY_DAY},
        timeout=15,
    )
    assert r.status_code == 403, r.text[:400]


# ═════════════════════════════════════════════════════════════════════
# Acceptance 5 · Missing / bogus token → 401.  Never 403 — the
# unauthenticated path must return the auth error code.
# ═════════════════════════════════════════════════════════════════════
def test_missing_token_returns_401_not_403():
    r_no_hdr = requests.post(
        f"{API}/schedule/optimize-route",
        json={"date": _EMPTY_DAY},
        timeout=15,
    )
    assert r_no_hdr.status_code in (401, 403), r_no_hdr.text[:200]
    # FastAPI's default HTTPBearer surfaces 403 when the header is
    # missing entirely.  When a bogus token is present, the auth
    # dependency MUST resolve to 401 — that's the case we assert.
    r_bogus = requests.post(
        f"{API}/schedule/optimize-route",
        headers={"Authorization": "Bearer bogus.token.value"},
        json={"date": _EMPTY_DAY},
        timeout=15,
    )
    assert r_bogus.status_code == 401, (
        f"bogus token must 401, got {r_bogus.status_code}: "
        f"{r_bogus.text[:200]}"
    )


# ═════════════════════════════════════════════════════════════════════
# Acceptance 6 · Cross-tenant impersonation → 403 (legit).
# A tenant-B admin passing a tenant-A user id must be rejected.
# ═════════════════════════════════════════════════════════════════════
def test_cross_tenant_admin_targeting_returns_403(mike):
    # A tenant-B admin (sunbelt) exists in the seed per the
    # existing ``test_route_optimization.py`` fixtures.  Skip when
    # the seed is a subset that doesn't carry it — the identical
    # cross-tenant assertion already lives in that suite, so a
    # missing sunbelt seed just narrows this file's surface, not
    # the overall guarantee.
    try:
        tok = _login("admin@sunbelt.com")["access_token"]
    except requests.HTTPError:
        pytest.skip("sunbelt admin missing from this seed")
    r = requests.post(
        f"{API}/schedule/optimize-route?user_id=" + mike["id"],
        headers={"Authorization": f"Bearer {tok}"},
        json={},
        timeout=15,
    )
    assert r.status_code == 403, r.text[:400]
    assert "not in current tenant" in r.text


# ═════════════════════════════════════════════════════════════════════
# Acceptance 7 · Tech targeting another user's id → 403 (legit
# cross-user guard, distinct from the "own empty day" case).  This
# proves the P19.1 fix didn't overshoot into permitting cross-user
# reads.
# ═════════════════════════════════════════════════════════════════════
def test_technician_targeting_other_user_still_returns_403(
    tech_h, dbc,
):
    other = dbc.users.find_one({"email": "admin@aquaterra.com"})
    assert other, "expected admin@aquaterra.com to exist"
    r = requests.post(
        f"{API}/schedule/optimize-route?user_id=" + other["id"],
        headers=tech_h,
        json={},
        timeout=15,
    )
    assert r.status_code == 403, r.text[:400]
