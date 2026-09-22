"""Phase P12.3 · Feb-2026 · Approval preview 404-on-empty
symmetry with the main optimize endpoint (P19.1 sibling).

The main ``/api/schedule/optimize-route`` endpoint returns a
``200`` + empty envelope for a tech-scoped empty day per the P9
silent-pin contract; the preview at
``/api/jobs/route-optimization/preview`` used to return
``404 no_jobs_for_tech_on_date`` for the same shape.  The P12.3
fold-in flips it to match.

Locked-in behaviour:
  1. Technician caller · 0 visible jobs on preview → 200 + empty
     envelope with the P19.1 soft-guard fields stamped.
  2. Admin caller · 0 jobs on preview → 200 + empty envelope
     (baseline sanity, mirrors the main-endpoint admin-empty case).
  3. Preview with populated day still returns 200 + populated —
     unchanged.
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
def tech_h() -> dict:
    return {"Authorization": f"Bearer {_login('mike@aquaterra.com')['access_token']}"}


@pytest.fixture(scope="module")
def mike(dbc):
    u = dbc.users.find_one({"email": "mike@aquaterra.com"})
    assert u, "mike@aquaterra.com missing from seed"
    return u


_EMPTY_DAY = "2028-07-11"
_LOADED_DAY = "2028-07-12"


def _preview(headers, tech_id, date):
    return requests.post(
        f"{API}/jobs/route-optimization/preview",
        headers=headers,
        json={"tech_user_id": tech_id, "date": date,
                "current_lat": 33.80, "current_lng": -112.10},
        timeout=15,
    )


# ═════════════════════════════════════════════════════════════════════
# Acceptance 1 · Technician · 0 visible jobs → 200 empty (not 404).
# The regression the fold-in fixes.
# ═════════════════════════════════════════════════════════════════════
def test_preview_tech_zero_jobs_returns_200_empty_not_404(
    tech_h, mike, dbc,
):
    tenant_id = mike["tenant_id"]
    dbc.jobs.delete_many(
        {"tenant_id": tenant_id, "scheduled_date": _EMPTY_DAY,
          "technician_id": mike["id"]},
    )
    dbc.jobs.delete_many(
        {"tenant_id": tenant_id, "scheduled_date": _EMPTY_DAY,
          "tech_user_id": mike["id"]},
    )
    r = _preview(tech_h, mike["id"], _EMPTY_DAY)
    assert r.status_code == 200, (
        f"tech-empty preview must silent-pin (200), got "
        f"{r.status_code}: {r.text[:400]}"
    )
    body = r.json()
    assert body.get("proposed_order") == []
    assert body.get("ordered_job_ids") == []
    assert body.get("orphaned_tech_ids") == []
    assert body.get("skipped_unassigned") == []
    assert body.get("algorithm") == "trivial"
    assert body.get("no_change") is True
    # ``estimated_miles_saved`` + ``estimated_minutes_saved`` are
    # stamped as 0 so downstream FE math (which reads them for
    # "you'd save X miles" copy) doesn't KeyError.
    assert body.get("estimated_miles_saved") == 0.0
    assert body.get("estimated_minutes_saved") == 0.0


# ═════════════════════════════════════════════════════════════════════
# Acceptance 2 · Admin · 0 jobs → 200 empty (baseline sanity).
# ═════════════════════════════════════════════════════════════════════
def test_preview_admin_zero_jobs_returns_200_empty(
    admin_h, mike, dbc,
):
    tenant_id = mike["tenant_id"]
    dbc.jobs.delete_many(
        {"tenant_id": tenant_id, "scheduled_date": _EMPTY_DAY,
          "technician_id": mike["id"]},
    )
    dbc.jobs.delete_many(
        {"tenant_id": tenant_id, "scheduled_date": _EMPTY_DAY,
          "tech_user_id": mike["id"]},
    )
    r = _preview(admin_h, mike["id"], _EMPTY_DAY)
    assert r.status_code == 200, r.text[:400]
    body = r.json()
    assert body.get("proposed_order") == []
    assert body.get("no_change") is True


# ═════════════════════════════════════════════════════════════════════
# Acceptance 3 · Preview with populated day still returns 200 +
# populated — the empty-symmetry flip is additive, not a widening
# of the happy path.
# ═════════════════════════════════════════════════════════════════════
def test_preview_populated_day_returns_200_populated(
    admin_h, mike, dbc,
):
    tenant_id = mike["tenant_id"]
    day = _LOADED_DAY
    dbc.jobs.delete_many({"tenant_id": tenant_id, "scheduled_date": day,
                             "technician_id": mike["id"]})
    dbc.jobs.delete_many({"tenant_id": tenant_id, "scheduled_date": day,
                             "tech_user_id": mike["id"]})
    seeded = []
    try:
        for i in range(3):
            jid = f"TEST-p12_3-prv-{uuid.uuid4().hex[:8]}"
            dbc.jobs.insert_one({
                "id": jid, "tenant_id": tenant_id,
                "tech_user_id": mike["id"],
                "status": "scheduled", "scheduled_date": day,
                "title": "p12.3 preview fixture",
                "site_lat": 33.81 + 0.01 * i,
                "site_lng": -112.11 - 0.01 * i,
                "lat": 33.81 + 0.01 * i,
                "lng": -112.11 - 0.01 * i,
                "route_index": i,
            })
            seeded.append(jid)
        r = _preview(admin_h, mike["id"], day)
        assert r.status_code == 200, r.text[:400]
        body = r.json()
        # ``proposed_order`` carries the seeded ids; empty-branch
        # ``no_change=True`` fires only when the day was empty.
        assert set(body.get("proposed_order") or []) >= set(seeded)
    finally:
        dbc.jobs.delete_many({"id": {"$in": seeded}})
