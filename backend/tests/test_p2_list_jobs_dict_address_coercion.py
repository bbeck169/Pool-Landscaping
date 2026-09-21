"""Phase P2 · Feb-2026 — list_jobs read-path safety net for legacy
dict-address rows.

Locks the invariant that ``GET /api/jobs`` (and by extension
``GET /api/jobs/{id}``) coerces any dict / list ``address`` value
to a string on the way OUT to the client, and fires exactly one
WARN log per (request, job_id) so ops can locate + repair the
underlying bad doc.

The fixture inserts a job with ``address={"street":"leaky", ...}``
directly via ``pymongo`` — this bypasses ``JobIn``'s Pydantic
``Optional[str]`` validator (which would otherwise 422 the dict
on write) so we can exercise the read-path net against a shape
that already exists in prod-legacy data.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict

import pytest
from fastapi.testclient import TestClient
from pymongo import MongoClient

from server import app


MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]


# ── TestClient MUST be used as a context manager so its
# BlockingPortal is created once + reused across every request in
# this module. Same rationale as ``test_p1_multi_property_job_writes``.
@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def _sync_db():
    return MongoClient(MONGO_URL)[DB_NAME]


# ── Fixture bundle — one tenant, one super_admin user, one
# customer, one job with a DICT address (the shape the P0 triage
# was chasing). Every id starts with ``P2_TEST_`` so the module-
# level teardown catches everything.
_PREFIX = "P2_TEST_"


@pytest.fixture
def dict_address_fixture():
    tenant_id = f"{_PREFIX}tid"
    fixture: Dict[str, Any] = {
        "tenants": [{
            "id": tenant_id,
            "name": "P2 Test Tenant",
            "slug": f"{_PREFIX}tenant",
            "active": True,
        }],
        "users": [{
            "id": f"{_PREFIX}sa",
            "tenant_id": tenant_id,
            "active_tenant_id": tenant_id,
            "email": f"{_PREFIX}sa@example.com",
            "role": "super_admin",
            "name": "P2 Super Admin",
            "is_active": True,
            "hashed_password": "xxx",
        }],
        "customers": [{
            "id": f"{_PREFIX}cust",
            "tenant_id": tenant_id,
            "name": "P2 Legacy Cust",
            "address": "789 Legacy Blvd, Peoria, AZ",
        }],
        # ── The legacy leak — dict-shape address on a jobs row.
        # We insert it directly so the P1 write-side 422 doesn't
        # fire.
        "jobs": [{
            "id": f"{_PREFIX}job_dict_addr",
            "tenant_id": tenant_id,
            "customer_id": f"{_PREFIX}cust",
            "customer_name": "P2 Legacy Cust",
            "title": "Dict-address leak repro",
            "status": "scheduled",
            "scheduled_date": "2026-08-15",
            "address": {"street": "leaky", "city": "Sun City",
                        "state": "AZ"},   # ← the bad shape
            "created_at": "2026-08-15T00:00:00+00:00",
        }, {
            # Control row — ordinary string address stays a string
            # AND emits NO WARN. Confirms the coercer is a no-op
            # on healthy data.
            "id": f"{_PREFIX}job_str_addr",
            "tenant_id": tenant_id,
            "customer_id": f"{_PREFIX}cust",
            "customer_name": "P2 Legacy Cust",
            "title": "Healthy control",
            "status": "scheduled",
            "scheduled_date": "2026-08-16",
            "address": "42 Healthy Ln, Peoria, AZ",
            "created_at": "2026-08-16T00:00:00+00:00",
        }],
    }
    db = _sync_db()
    db.tenants.insert_many(fixture["tenants"])
    db.users.insert_many(fixture["users"])
    db.customers.insert_many(fixture["customers"])
    db.jobs.insert_many(fixture["jobs"])
    yield fixture
    # Teardown — id-prefix regex catches every collection.
    filt = {"id": {"$regex": f"^{_PREFIX}"}}
    for coll in ("tenants", "users", "customers", "jobs"):
        db[coll].delete_many(filt)


def _headers_for(user_id: str) -> Dict[str, str]:
    """Mint a JWT for the seeded super_admin.  Same shape as the P1
    suite — direct ``jwt.encode`` with the app's ``JWT_SECRET`` /
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


# ─────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────
def test_p2_list_jobs_coerces_dict_address_and_warns(
    client, dict_address_fixture, caplog,
):
    """Direct-inserted dict-address row is coerced to string on the
    wire AND a single WARN is emitted with the offending type."""
    caplog.set_level(logging.WARNING, logger="pool_crm.routers.jobs")

    h = _headers_for(f"{_PREFIX}sa")
    r = client.get(
        f"/api/jobs?scheduled_date=2026-08-15",
        headers=h,
    )
    assert r.status_code == 200, r.text
    rows = r.json()
    assert isinstance(rows, list)
    target = next(
        (x for x in rows if x.get("id") == f"{_PREFIX}job_dict_addr"),
        None,
    )
    assert target is not None, "seeded dict-address row missing from response"

    # Coerced to a STRING on the wire.
    assert isinstance(target["address"], str), (
        f"address stayed non-string in response: type="
        f"{type(target['address']).__name__} value={target['address']!r}"
    )
    # The stringify helper (line1/city/state join) does NOT know
    # about the ``street`` key on legacy shapes, so the coerced
    # value can be empty — the invariant here is TYPE, not
    # content. What matters is the frontend never sees a dict.
    assert target["address"] != {"street": "leaky", "city": "Sun City",
                                    "state": "AZ"}

    # Exactly one WARN for the offending job id.
    warns = [
        rec for rec in caplog.records
        if rec.levelno == logging.WARNING
        and "jobs.read.address_coerced" in rec.getMessage()
        and f"{_PREFIX}job_dict_addr" in rec.getMessage()
    ]
    assert len(warns) == 1, (
        f"expected exactly 1 WARN for the coerced job, got {len(warns)}: "
        f"{[r.getMessage() for r in warns]}"
    )
    # Offending type is surfaced so ops can grep.
    assert "offending_type=dict" in warns[0].getMessage()


def test_p2_list_jobs_no_warn_on_string_address_control(
    client, dict_address_fixture, caplog,
):
    """The control row with a string address is untouched AND
    triggers NO WARN — the coercer must be a no-op on healthy
    data."""
    caplog.set_level(logging.WARNING, logger="pool_crm.routers.jobs")

    h = _headers_for(f"{_PREFIX}sa")
    r = client.get(
        "/api/jobs?scheduled_date=2026-08-16",
        headers=h,
    )
    assert r.status_code == 200, r.text
    rows = r.json()
    target = next(
        (x for x in rows if x.get("id") == f"{_PREFIX}job_str_addr"),
        None,
    )
    assert target is not None
    assert target["address"] == "42 Healthy Ln, Peoria, AZ"

    warns = [
        rec for rec in caplog.records
        if rec.levelno == logging.WARNING
        and "jobs.read.address_coerced" in rec.getMessage()
        and f"{_PREFIX}job_str_addr" in rec.getMessage()
    ]
    assert len(warns) == 0


def test_p2_get_job_detail_coerces_dict_address(
    client, dict_address_fixture, caplog,
):
    """The single-job DETAIL handler (``GET /jobs/{id}``) also
    applies the coercion — same invariant, same helper."""
    caplog.set_level(logging.WARNING, logger="pool_crm.routers.jobs")

    h = _headers_for(f"{_PREFIX}sa")
    r = client.get(
        f"/api/jobs/{_PREFIX}job_dict_addr",
        headers=h,
    )
    assert r.status_code == 200, r.text
    doc = r.json()

    assert isinstance(doc["address"], str)
    warns = [
        rec for rec in caplog.records
        if rec.levelno == logging.WARNING
        and "jobs.read.address_coerced" in rec.getMessage()
        and f"{_PREFIX}job_dict_addr" in rec.getMessage()
    ]
    assert len(warns) >= 1


def test_p2_no_writeback_to_mongo_from_read_path(
    client, dict_address_fixture,
):
    """The read-path coercion is response-only — the underlying
    Mongo doc still carries the dict-address shape, waiting for a
    separate targeted repair.  This asserts we did NOT overreach
    and silently backfill from the read handler."""
    h = _headers_for(f"{_PREFIX}sa")
    _ = client.get(f"/api/jobs/{_PREFIX}job_dict_addr", headers=h)

    doc = _sync_db().jobs.find_one(
        {"id": f"{_PREFIX}job_dict_addr"}, {"_id": 0, "address": 1},
    )
    # Still a dict in Mongo — the read handler did NOT rewrite it.
    assert isinstance(doc["address"], dict)
    assert doc["address"].get("street") == "leaky"
