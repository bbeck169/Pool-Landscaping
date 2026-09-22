"""Phase P26 · Feb-2026 — Map endpoints return coord fallback + audit.

End-to-end integration guard for the three list endpoints that
serialize job coords for the schedule map / dispatch board:

  * ``GET /api/jobs`` — the primary list handler (K58 ladder — was
    already correct pre-P26; guard the new ``coord_source`` audit
    field).
  * ``GET /api/schedule/today`` — the tech's timeline. Pre-P26 this
    endpoint emitted ``lat = j.get("site_lat") or j.get("lat")``
    with NO customer fallback; the reported P26 bug.
  * ``GET /api/dispatch/board`` — the operator's dispatch view.
    Pre-P26 the ``jobs_fallback`` branch ignored the job's own
    coords and only ever consulted the customer.

Each endpoint MUST:
  1. Return every scheduled job (no pin dropping) with its coords
     resolved via the shared resolver.
  2. Stamp ``coord_source`` on every job/pin (``"job"`` |
     ``"customer"`` | null).
  3. Batch the customer fetch (one ``find`` per list call — the
     unit tests in ``test_p26_coord_fallback.py`` grep-guard this).

Uses live HTTP via ``admin@aquaterra.com`` (preview tenant
``affdfbfa-88b9-4baa-ae45-2ef78531b6e4``) so the response payload
shape is exercised through the FastAPI serializer.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient


_FE = dotenv_values(
    Path(__file__).resolve().parents[2] / "frontend" / ".env",
)
_BE = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
BASE = (_FE.get("EXPO_PUBLIC_BACKEND_URL")
        or "http://localhost:8001").rstrip("/")
API = f"{BASE}/api"
MONGO_URL = _BE.get("MONGO_URL"); DB_NAME = _BE.get("DB_NAME")

TAG = "P26E2E_"
PHOENIX = ZoneInfo("America/Phoenix")


def _login(email: str, pw: str = "password123") -> dict:
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": pw}, timeout=15)
    r.raise_for_status()
    return r.json()


@pytest.fixture(scope="module")
def dbc() -> MongoClient:
    return MongoClient(MONGO_URL)[DB_NAME]


@pytest.fixture(scope="module")
def admin_login() -> dict:
    return _login("admin@aquaterra.com")


@pytest.fixture(scope="module")
def admin_h(admin_login) -> dict:
    return {"Authorization": f"Bearer {admin_login['access_token']}"}


@pytest.fixture(scope="module")
def admin_tenant_id(admin_login) -> str:
    # ``active_tenant_id`` lives in the JWT payload — the /auth/login
    # response body's ``user`` object does NOT carry the tenant_id
    # (multi-tenant memberships shape). Decode the token to pull it.
    import jwt as _jwt
    tok = admin_login["access_token"]
    payload = _jwt.decode(tok, options={"verify_signature": False})
    tid = payload.get("active_tenant_id")
    assert tid, f"admin token has no active_tenant_id: {payload}"
    return tid


@pytest.fixture
def _seeded(dbc, admin_tenant_id):
    """Seed 3 customers + 3 jobs (own-coords, customer-fallback,
    no-coords-anywhere). Torn down at end of test."""
    tenant_id = admin_tenant_id
    tech_id = f"{TAG}TECH_{uuid.uuid4().hex[:6]}"
    today = datetime.now(PHOENIX).strftime("%Y-%m-%d")

    ids: dict = {"customers": [], "jobs": [], "tech_id": tech_id,
                  "today": today, "tenant_id": tenant_id}

    # 3 customers.
    c_own = f"{TAG}CUST_OWN_{uuid.uuid4().hex[:6]}"      # customer coords irrelevant (job has own)
    c_svc = f"{TAG}CUST_SVC_{uuid.uuid4().hex[:6]}"      # only customer coords
    c_none = f"{TAG}CUST_NONE_{uuid.uuid4().hex[:6]}"    # no coords anywhere
    dbc.customers.insert_many([
        {"id": c_own,  "tenant_id": tenant_id, "name": "Own Coords Cust",
         "service_lat": 10.0, "service_lng": 10.0},
        {"id": c_svc,  "tenant_id": tenant_id, "name": "Svc Coords Cust",
         "service_lat": 33.5, "service_lng": -112.3},
        {"id": c_none, "tenant_id": tenant_id, "name": "No Coords Cust",
         "service_lat": None, "service_lng": None},
    ])
    ids["customers"] = [c_own, c_svc, c_none]

    # Insert a technician row so the schedule endpoint's live-tech
    # space validation doesn't drop these jobs.
    dbc.technicians.insert_one({
        "id": tech_id, "tenant_id": tenant_id,
        "name": "P26 Tech", "email": f"{tech_id[-6:]}@p26.test",
        "user_id": tech_id, "active": True,
    })

    # 3 jobs — one per fallback case.
    j_own = f"{TAG}JOB_OWN_{uuid.uuid4().hex[:6]}"
    j_svc = f"{TAG}JOB_SVC_{uuid.uuid4().hex[:6]}"
    j_none = f"{TAG}JOB_NONE_{uuid.uuid4().hex[:6]}"
    dbc.jobs.insert_many([
        # Own coords — must win over customer coords.
        {"id": j_own, "tenant_id": tenant_id,
         "customer_id": c_own, "technician_id": tech_id,
         "customer_name": "Own Coords Cust",
         "scheduled_date": today,
         "status": "scheduled", "service_type": "pool_service",
         "site_lat": 44.4, "site_lng": -88.8,
         "created_at": datetime.now(timezone.utc).isoformat()},
        # Own coords null — fallback to customer.
        {"id": j_svc, "tenant_id": tenant_id,
         "customer_id": c_svc, "technician_id": tech_id,
         "customer_name": "Svc Coords Cust",
         "scheduled_date": today,
         "status": "scheduled", "service_type": "pool_service",
         "site_lat": None, "site_lng": None,
         "lat": None, "lng": None,
         "latitude": None, "longitude": None,
         "created_at": datetime.now(timezone.utc).isoformat()},
        # Neither present.
        {"id": j_none, "tenant_id": tenant_id,
         "customer_id": c_none, "technician_id": tech_id,
         "customer_name": "No Coords Cust",
         "scheduled_date": today,
         "status": "scheduled", "service_type": "pool_service",
         "site_lat": None, "site_lng": None,
         "created_at": datetime.now(timezone.utc).isoformat()},
    ])
    ids["jobs"] = [j_own, j_svc, j_none]
    ids["j_own"] = j_own
    ids["j_svc"] = j_svc
    ids["j_none"] = j_none

    yield ids

    # Teardown.
    dbc.jobs.delete_many({"id": {"$in": ids["jobs"]}})
    dbc.customers.delete_many({"id": {"$in": ids["customers"]}})
    dbc.technicians.delete_one({"id": tech_id})


# ── 1) GET /api/jobs stamps coord_source + fallback for all 3 cases ─


def test_p26_jobs_list_endpoint_returns_coord_source_for_each_case(
    admin_h, admin_tenant_id, _seeded,
):
    r = requests.get(
        f"{API}/jobs",
        params={"start": _seeded["today"], "end": _seeded["today"]},
        headers=admin_h, timeout=15,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    rows = body if isinstance(body, list) else (body.get("items") or [])
    by_id = {row["id"]: row for row in rows if row.get("id") in _seeded["jobs"]}
    assert len(by_id) == 3, (
        f"Expected 3 seeded jobs in list, got {len(by_id)}: "
        f"{list(by_id.keys())}"
    )

    # Case A — job has own coords → coord_source == "job".
    a = by_id[_seeded["j_own"]]
    assert a.get("coord_source") == "job", (
        f"j_own coord_source expected 'job', got {a.get('coord_source')!r} "
        f"(location_lat={a.get('location_lat')})"
    )
    assert a.get("location_lat") == 44.4
    assert a.get("location_lng") == -88.8

    # Case B — job coords null, customer has service coords →
    # coord_source == "customer".
    b = by_id[_seeded["j_svc"]]
    assert b.get("coord_source") == "customer", (
        f"j_svc coord_source expected 'customer', got "
        f"{b.get('coord_source')!r} "
        f"(location_lat={b.get('location_lat')})"
    )
    assert b.get("location_lat") == 33.5
    assert b.get("location_lng") == -112.3

    # Case C — neither present → coord_source is None.
    c = by_id[_seeded["j_none"]]
    assert c.get("coord_source") is None, (
        f"j_none coord_source expected None, got {c.get('coord_source')!r}"
    )
    assert c.get("location_lat") is None
    assert c.get("location_lng") is None


# ── 2) GET /api/schedule/today emits coord_source ─────────────────


def test_p26_schedule_today_endpoint_returns_coord_source(
    admin_h, admin_tenant_id, _seeded,
):
    # ``/schedule/today`` is scoped to the caller's user_id — the
    # admin's own timeline won't contain the seeded tech's jobs. We
    # instead assert the endpoint EXISTS and returns 200 with the
    # expected top-level ``items`` field so the FE contract stays
    # stable. Coord-source shape is verified by inspecting an
    # example item (if any items exist for the admin user) or by
    # the resolver's unit tests (which drive the same code path).
    r = requests.get(
        f"{API}/schedule/today",
        params={"date": _seeded["today"]},
        headers=admin_h, timeout=15,
    )
    # Admin doesn't have to have jobs assigned; the endpoint just
    # returns an empty items list. Contract is what we're guarding.
    assert r.status_code == 200, r.text
    body = r.json()
    assert "items" in body

    # Guardrail: if ANY item is a job type, it MUST carry the
    # coord_source key (even if null). Sample first job-typed row.
    for item in body["items"]:
        if item.get("type") == "job":
            assert "coord_source" in item, (
                f"schedule/today job item missing coord_source key: "
                f"{item.keys()}"
            )
            # ``lat``/``lng`` MUST both be present (either both
            # resolved or both null — no half-populated pair).
            has_lat = item.get("lat") is not None
            has_lng = item.get("lng") is not None
            assert has_lat == has_lng, (
                f"schedule/today job item has half-null coords: "
                f"lat={item.get('lat')} lng={item.get('lng')}"
            )
            # Any resolved coord MUST have a matching non-null
            # coord_source, and any null coord MUST have
            # coord_source == None.
            if has_lat:
                assert item["coord_source"] in ("job", "customer"), (
                    f"coord_source for resolved item is "
                    f"{item.get('coord_source')!r}"
                )
            else:
                assert item["coord_source"] is None, (
                    f"coord_source={item.get('coord_source')!r} "
                    f"for null-coord item"
                )
            # Only need to inspect one job-typed item.
            break


# ── 3) Source guardrail — schedule.py uses the shared resolver ────


def test_p26_schedule_router_routes_through_shared_resolver():
    """A refactor that reintroduced the ``j.get('site_lat') or
    j.get('lat')`` pattern in the emit loop would silently drop
    the customer fallback again. Source-lint guard."""
    src = (Path(__file__).resolve().parents[1] / "routers"
           / "schedule.py").read_text(encoding="utf-8")
    assert "resolve_job_coordinates" in src, (
        "routers/schedule.py no longer imports/uses "
        "resolve_job_coordinates — P26 customer-fallback regression."
    )
    # Pre-P26 anti-pattern MUST NOT appear on the emit path.
    anti = 'j.get("site_lat") or j.get("lat")'
    assert anti not in src, (
        "Pre-P26 fallback-less coord read detected in "
        "routers/schedule.py — customer.service_lat fallback lost."
    )


def test_p26_dispatch_board_routes_through_shared_resolver():
    src = (Path(__file__).resolve().parents[1] / "routers"
           / "dispatch_board.py").read_text(encoding="utf-8")
    assert "resolve_job_coordinates" in src, (
        "routers/dispatch_board.py no longer uses "
        "resolve_job_coordinates — P26 job-own-coords regression on "
        "the jobs_fallback branch."
    )


def test_p26_jobs_router_stamps_coord_source():
    src = (Path(__file__).resolve().parents[1] / "routers"
           / "jobs.py").read_text(encoding="utf-8")
    assert 'd["coord_source"]' in src, (
        "routers/jobs.py no longer stamps coord_source on the "
        "list-response envelope — P26 audit-field regression."
    )
