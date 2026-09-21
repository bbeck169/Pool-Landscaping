"""Phase P1 · Feb-2026 — Multi-Property Support on Job Create / Edit.

Locks the two invariants documented in ``routers/jobs.py::
_stringify_property_address`` / ``_resolve_property_for_job``:

  1. ``jobs.address`` is ALWAYS a plain string on write — dict / list
     inputs are rejected (create) OR coerced through the canonical
     ``line1, city, state`` formatter (property retag path).
  2. ``property_id`` — when provided — MUST belong to the SAME
     tenant AND the SAME customer.  Mismatch returns 422 with a
     machine-parseable code.  Cross-tenant errors return the same
     code + message as unknown-id so a caller cannot enumerate.

Uses ``fastapi.testclient`` against the live app (in-process, no
Motor stubs) — the write-path validation logic runs on real Mongo
so we don't have to re-mock the whole schedule / dispatch / tenant
resolver chain.

Every test seeds + cleans up its own tenant + customer + property
docs so the suite is safe to run in parallel and never leaks state
into other suites.
"""
from __future__ import annotations

import os
from typing import Any, Dict

import pytest
from fastapi.testclient import TestClient
from pymongo import MongoClient

from server import app


# ── TestClient MUST be used as a context manager so its BlockingPortal
# is created once + reused across every request in this module.
# Without ``with TestClient(app) as c:``, Starlette's transport spins
# up a fresh portal (thread + event loop) PER REQUEST — Motor's
# ``config.db`` client latches its ``io_loop`` to the FIRST request's
# portal loop, and the very next request 500s with "Event loop is
# closed". See ``_TestClientTransport.handle_request`` in
# starlette 0.37.
@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]


# ── Sync pymongo helpers.
#
# The FastAPI app uses ``config.db`` (an ``AsyncIOMotorClient``) which
# is bound to the TestClient portal's event loop on first request.
# Seed / cleanup fixtures that spin their own asyncio loop for a
# throwaway Motor client cross-contaminate Motor's shared executor
# handle and cause "Event loop is closed" on subsequent portal
# requests.  Sync pymongo has no event loop and shares no state with
# Motor, so it is the safe choice for test fixture DB ops.
def _sync_db():
    """Return a sync pymongo Database — caller closes it via
    ``client.close()`` on the ``.client`` attribute if desired.
    Cheap enough to open per call (< 5 ms in-container)."""
    return MongoClient(MONGO_URL)[DB_NAME]


def _seed_sync(fixture: Dict[str, Any]) -> None:
    db = _sync_db()
    if fixture.get("tenants"):
        db.tenants.insert_many(fixture["tenants"])
    if fixture.get("users"):
        db.users.insert_many(fixture["users"])
    if fixture.get("customers"):
        db.customers.insert_many(fixture["customers"])
    if fixture.get("properties"):
        db.properties.insert_many(fixture["properties"])


def _cleanup_sync(prefix: str) -> None:
    """Purge everything this suite seeded — every fixture id starts
    with ``P1_TEST_`` so a single ``id: {$regex: ...}`` filter
    catches the entire run."""
    db = _sync_db()
    filt = {"id": {"$regex": f"^{prefix}"}}
    for coll in ("tenants", "users", "customers",
                  "properties", "jobs"):
        db[coll].delete_many(filt)


@pytest.fixture
def two_tenant_two_customer_fixture():
    """Two tenants, each with a customer + two properties.  Adds
    an admin super_admin user for each tenant so the write-path
    handler resolves the caller to a real doc.

    Fixture ids all live under the ``P1_TEST_*`` namespace so
    ``_cleanup`` can nuke them in one shot on teardown regardless
    of which tests actually ran.
    """
    fixture = {
        "tenants": [
            {"id": "P1_TEST_tid_A", "name": "P1 Test Tenant A",
              "active": True, "slug": "p1-test-a"},
            {"id": "P1_TEST_tid_B", "name": "P1 Test Tenant B",
              "active": True, "slug": "p1-test-b"},
        ],
        "users": [
            # Tenant A super_admin.
            {"id": "P1_TEST_sa_A", "tenant_id": "P1_TEST_tid_A",
              "email": "p1a@example.com", "role": "super_admin",
              "name": "P1 SA A", "active": True},
            # Tenant B super_admin.
            {"id": "P1_TEST_sa_B", "tenant_id": "P1_TEST_tid_B",
              "email": "p1b@example.com", "role": "super_admin",
              "name": "P1 SA B", "active": True},
        ],
        "customers": [
            {"id": "P1_TEST_cust_A_1", "tenant_id": "P1_TEST_tid_A",
              "name": "A · Cust 1", "address": "1 A Cust 1 St"},
            {"id": "P1_TEST_cust_A_2", "tenant_id": "P1_TEST_tid_A",
              "name": "A · Cust 2", "address": "2 A Cust 2 St"},
            {"id": "P1_TEST_cust_B_1", "tenant_id": "P1_TEST_tid_B",
              "name": "B · Cust 1", "address": "1 B Cust 1 St"},
        ],
        "properties": [
            # Cust A/1 — three properties (≥2 → picker required).
            {"id": "P1_TEST_prop_A_1a", "tenant_id": "P1_TEST_tid_A",
              "customer_id": "P1_TEST_cust_A_1", "label": "Main",
              "address": {"line1": "10 Main St", "city": "Peoria",
                            "state": "AZ", "postal_code": "85383"},
              "lat": 33.77, "lng": -112.34, "active": True,
              "sort_order": 0},
            {"id": "P1_TEST_prop_A_1b", "tenant_id": "P1_TEST_tid_A",
              "customer_id": "P1_TEST_cust_A_1", "label": "Guest House",
              "address": {"line1": "12 Main St", "city": "Peoria",
                            "state": "AZ", "postal_code": "85383"},
              "lat": 33.78, "lng": -112.35, "active": True,
              "sort_order": 1},
            {"id": "P1_TEST_prop_A_1c", "tenant_id": "P1_TEST_tid_A",
              "customer_id": "P1_TEST_cust_A_1", "label": "Pool House",
              "address": {"line1": "14 Main St", "city": "Peoria",
                            "state": "AZ", "postal_code": "85383"},
              "lat": 33.79, "lng": -112.36, "active": True,
              "sort_order": 2},
            # Cust A/2 — one property (picker hidden client-side,
            # auto-assigned server-side).
            {"id": "P1_TEST_prop_A_2a", "tenant_id": "P1_TEST_tid_A",
              "customer_id": "P1_TEST_cust_A_2", "label": "Main",
              "address": {"line1": "22 A Cust 2 St", "city": "Peoria",
                            "state": "AZ"},
              "lat": 33.80, "lng": -112.37, "active": True,
              "sort_order": 0},
            # Cust B/1 — one property under Tenant B (used to prove
            # cross-tenant rejection).
            {"id": "P1_TEST_prop_B_1a", "tenant_id": "P1_TEST_tid_B",
              "customer_id": "P1_TEST_cust_B_1", "label": "Main",
              "address": {"line1": "11 B Cust 1 St"},
              "lat": 34.00, "lng": -112.00, "active": True,
              "sort_order": 0},
        ],
    }
    _seed_sync(fixture)
    yield fixture
    _cleanup_sync("P1_TEST_")


def _headers_for(user_id: str) -> Dict[str, str]:
    """Mint a JWT for the seeded super_admin.  Matches the shape
    used by ``test_phase18_chemical_report.py`` / ``test_phase20_backlog``
    — direct ``jwt.encode`` with the app's ``JWT_SECRET`` /
    ``JWT_ALGO`` so we skip ``/auth/login`` (avoids password-hash
    plumbing on the fixture user)."""
    from datetime import datetime, timedelta, timezone
    import jwt
    from config import JWT_SECRET, JWT_ALGO
    payload = {
        "sub": user_id,
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
    }
    tok = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)
    return {"Authorization": f"Bearer {tok}"}


# ═══════════════════════════════════════════════════════════════════
# 1 · Address enforcement — dict / list → 422; never persists dict.
# ═══════════════════════════════════════════════════════════════════
def test_p1_create_rejects_dict_address_returns_422(
    client, two_tenant_two_customer_fixture,
):
    h = _headers_for("P1_TEST_sa_A")
    r = client.post(
        "/api/jobs",
        json={
            "title": "Address dict repro",
            "customer_id": "P1_TEST_cust_A_2",   # single-prop cust
            "address": {"street": "123 Main"},
            "scheduled_date": "2026-08-01",
        },
        headers=h,
    )
    # Pydantic ``Optional[str]`` on JobIn.address refuses a dict.
    assert r.status_code == 422, r.text

    # ── Post-condition — no jobs row was persisted.
    db = _sync_db()
    n = db.jobs.count_documents(
        {"customer_id": "P1_TEST_cust_A_2", "title": "Address dict repro"}
    )
    assert n == 0


def test_p1_create_persists_address_as_string_from_property(
    client, two_tenant_two_customer_fixture,
):
    """Cust A/1 has 3 properties.  Create a job pinned to
    ``P1_TEST_prop_A_1b`` — the persisted job doc's ``address``
    MUST be a plain string formatted from the property's dict
    address (no dict leak)."""
    h = _headers_for("P1_TEST_sa_A")
    r = client.post(
        "/api/jobs",
        json={
            "title": "Address string proof",
            "customer_id": "P1_TEST_cust_A_1",
            "property_id": "P1_TEST_prop_A_1b",
            "scheduled_date": "2026-08-02",
        },
        headers=h,
    )
    assert r.status_code == 200, r.text
    created = r.json()

    # ── Read back from Mongo (bypass the API projection) to
    # catch a dict slipping through.
    db = _sync_db()
    doc = db.jobs.find_one({"id": created["id"]}, {"_id": 0})

    assert doc is not None
    assert isinstance(doc["address"], str), (
        f"address must be a string, got {type(doc['address']).__name__}"
    )
    # Formatter yields ``line1, city, state``.
    assert doc["address"] == "12 Main St, Peoria, AZ"
    # And the property_id was persisted alongside.
    assert doc["property_id"] == "P1_TEST_prop_A_1b"
    # And the coords got snapshotted.
    assert doc.get("site_lat") == 33.78
    assert doc.get("site_lng") == -112.35


# ═══════════════════════════════════════════════════════════════════
# 2 · property_id validation — cross-customer + cross-tenant.
# ═══════════════════════════════════════════════════════════════════
def test_p1_create_rejects_cross_customer_property_id(
    client, two_tenant_two_customer_fixture,
):
    """Cust A/1's admin submits Cust A/2's property_id → 422 with
    ``property_customer_mismatch``.  Same tenant, different
    customer."""
    h = _headers_for("P1_TEST_sa_A")
    r = client.post(
        "/api/jobs",
        json={
            "title": "Cross-customer repro",
            "customer_id": "P1_TEST_cust_A_1",
            "property_id": "P1_TEST_prop_A_2a",   # belongs to A/2
            "scheduled_date": "2026-08-03",
        },
        headers=h,
    )
    assert r.status_code == 422, r.text
    body = r.json()
    detail = body.get("detail")
    # FastAPI wraps HTTPException detail dict verbatim.
    assert isinstance(detail, dict), detail
    assert detail.get("code") == "property_customer_mismatch"


def test_p1_create_rejects_cross_tenant_property_id_no_leak(
    client, two_tenant_two_customer_fixture,
):
    """Tenant A admin submits Tenant B's property_id → 422 with
    ``property_tenant_mismatch``.  The response MUST NOT reveal
    the property exists under a different tenant."""
    h = _headers_for("P1_TEST_sa_A")
    r = client.post(
        "/api/jobs",
        json={
            "title": "Cross-tenant repro",
            "customer_id": "P1_TEST_cust_A_1",
            "property_id": "P1_TEST_prop_B_1a",   # tenant B property
            "scheduled_date": "2026-08-04",
        },
        headers=h,
    )
    assert r.status_code == 422, r.text
    body = r.json()
    detail = body.get("detail")
    assert isinstance(detail, dict), detail
    assert detail.get("code") == "property_tenant_mismatch"
    # ── No leak: message doesn't mention the other tenant's name /
    # id / the fact that the property "exists somewhere else".
    msg = (detail.get("message") or "").lower()
    for forbidden in ("tenant_b", "P1_TEST_tid_B".lower(),
                       "cross-tenant", "other tenant", "another tenant"):
        assert forbidden not in msg, (
            f"tenant-mismatch message leaked forbidden token "
            f"{forbidden!r}: {msg!r}"
        )


# ═══════════════════════════════════════════════════════════════════
# 3 · Update-path retag — dict address is stringified.
# ═══════════════════════════════════════════════════════════════════
def test_p1_update_property_id_retags_and_stringifies_address(
    client, two_tenant_two_customer_fixture,
):
    """Create a job on Cust A/1 pointed at ``prop_A_1a``, then
    retag to ``prop_A_1c`` via PUT (the Job Edit endpoint used by
    the frontend's ScheduleJobEditModal + JobDetail).  The
    persisted address MUST remain a string (this is exactly the
    dict-leak the fix closes)."""
    h = _headers_for("P1_TEST_sa_A")

    # Seed the job.
    r = client.post(
        "/api/jobs",
        json={
            "title": "Retag repro",
            "customer_id": "P1_TEST_cust_A_1",
            "property_id": "P1_TEST_prop_A_1a",
            "scheduled_date": "2026-08-05",
        },
        headers=h,
    )
    assert r.status_code == 200, r.text
    job_id = r.json()["id"]

    # Retag to prop_A_1c.
    r = client.put(
        f"/api/jobs/{job_id}",
        json={"property_id": "P1_TEST_prop_A_1c"},
        headers=h,
    )
    assert r.status_code == 200, r.text

    doc = _sync_db().jobs.find_one({"id": job_id}, {"_id": 0})

    assert doc["property_id"] == "P1_TEST_prop_A_1c"
    assert isinstance(doc["address"], str)
    assert doc["address"] == "14 Main St, Peoria, AZ"


def test_p1_update_rejects_cross_customer_property_id(
    client, two_tenant_two_customer_fixture,
):
    """Retag path — target property belongs to a different customer
    → 422 ``property_customer_mismatch``.  Job is not mutated."""
    h = _headers_for("P1_TEST_sa_A")

    r = client.post(
        "/api/jobs",
        json={"title": "Retag-cross-customer",
              "customer_id": "P1_TEST_cust_A_1",
              "property_id": "P1_TEST_prop_A_1a",
              "scheduled_date": "2026-08-06"},
        headers=h,
    )
    assert r.status_code == 200, r.text
    job_id = r.json()["id"]

    r = client.put(
        f"/api/jobs/{job_id}",
        json={"property_id": "P1_TEST_prop_A_2a"},   # A/2's property
        headers=h,
    )
    assert r.status_code == 422, r.text
    body = r.json()
    detail = body.get("detail")
    assert isinstance(detail, dict), detail
    assert detail.get("code") == "property_customer_mismatch"


def test_p1_update_rejects_cross_tenant_property_id_no_leak(
    client, two_tenant_two_customer_fixture,
):
    """Retag path — target property belongs to a different tenant
    → 422 ``property_tenant_mismatch``.  No cross-tenant leak."""
    h = _headers_for("P1_TEST_sa_A")

    r = client.post(
        "/api/jobs",
        json={"title": "Retag-cross-tenant",
              "customer_id": "P1_TEST_cust_A_1",
              "property_id": "P1_TEST_prop_A_1a",
              "scheduled_date": "2026-08-07"},
        headers=h,
    )
    assert r.status_code == 200, r.text
    job_id = r.json()["id"]

    r = client.put(
        f"/api/jobs/{job_id}",
        json={"property_id": "P1_TEST_prop_B_1a"},   # tenant B
        headers=h,
    )
    assert r.status_code == 422, r.text
    body = r.json()
    detail = body.get("detail")
    assert isinstance(detail, dict), detail
    assert detail.get("code") == "property_tenant_mismatch"
    msg = (detail.get("message") or "").lower()
    for forbidden in ("tenant_b", "P1_TEST_tid_B".lower(),
                       "cross-tenant", "other tenant"):
        assert forbidden not in msg


# ═══════════════════════════════════════════════════════════════════
# 4 · Legacy customer (0 properties) — no property_id required,
#      address falls back to the customer's flat string.
# ═══════════════════════════════════════════════════════════════════
def test_p1_create_legacy_customer_no_property_id_uses_customer_address(
    client, two_tenant_two_customer_fixture,
):
    """Seed an extra legacy customer with zero properties, verify
    the job creates cleanly, ``property_id`` is null, and
    ``address`` falls back to the customer's flat string."""
    _sync_db().customers.insert_one({
        "id": "P1_TEST_cust_legacy",
        "tenant_id": "P1_TEST_tid_A",
        "name": "Legacy Cust",
        "address": "99 Legacy Ln, Peoria, AZ",
    })

    h = _headers_for("P1_TEST_sa_A")
    r = client.post(
        "/api/jobs",
        json={
            "title": "Legacy proof",
            "customer_id": "P1_TEST_cust_legacy",
            "scheduled_date": "2026-08-08",
        },
        headers=h,
    )
    assert r.status_code == 200, r.text

    doc = _sync_db().jobs.find_one(
        {"customer_id": "P1_TEST_cust_legacy"}, {"_id": 0}
    )

    assert doc is not None
    assert isinstance(doc["address"], str)
    assert doc["address"] == "99 Legacy Ln, Peoria, AZ"
    assert doc.get("property_id") is None
