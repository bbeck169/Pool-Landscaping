"""Phase K49b · Feb-2026 — Regression test for the missing-``id``
customer doc that 500'd ``GET /api/customers``.

Root cause: a legacy customer doc was written without a top-level
``id`` field (only ``_id``).  ``routers/customers.py:768`` and every
downstream hydration in the customers-list handler indexed
``d["id"]``, which raised ``KeyError`` for that doc and 500'd the
whole endpoint — including K49's new ``sort=last_name_asc`` path.

Two layers of defence shipped in K49b:

1. **Router guard** — every ``d["id"]`` access in the customers-list
   handler now filters on ``d.get("id")``.  This test verifies the
   endpoint returns 200 EVEN IF the migration hasn't run: it seeds a
   fresh missing-id doc AFTER the sentinel is set, hits the
   endpoint on both the default sort AND ``sort=last_name_asc``,
   and asserts 200.
2. **Backfill migration** — ``k49b_customer_id_backfill`` sets
   ``id = str(_id)``.  We also exercise the migration directly to
   confirm the seeded doc surfaces in the response with a valid
   ``id`` afterwards.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path

import pytest
import requests
from bson import ObjectId
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

API = "http://localhost:8001/api"
_sync = MongoClient(os.environ["MONGO_URL"])
_db = _sync[os.environ["DB_NAME"]]


def _login(email: str, password: str = "password123") -> str:
    r = requests.post(
        f"{API}/auth/login",
        json={"email": email, "password": password},
        timeout=30,
    )
    if r.status_code != 200:
        pytest.skip(f"login skipped for {email}: {r.status_code}")
    return r.json()["access_token"]


def _admin_ctx() -> dict:
    tok = _login("super@aquaterra.com")
    me = requests.get(
        f"{API}/auth/me",
        headers={"Authorization": f"Bearer {tok}"}, timeout=15,
    ).json()
    return {
        "headers": {"Authorization": f"Bearer {tok}"},
        "tenant_id": me["tenant_id"],
    }


@pytest.fixture
def seeded_missing_id_customer():
    """Insert a legacy-shaped customer WITHOUT a top-level ``id``
    field, mirroring the Kaylan Testcase doc that caused the K49b
    500. Cleans up on teardown."""
    ctx = _admin_ctx()
    tenant_id = ctx["tenant_id"]
    oid = ObjectId()
    marker = f"k49b-{uuid.uuid4()}"
    _db.customers.insert_one({
        "_id": oid,
        # NO top-level "id" field — this is the crash trigger.
        "tenant_id": tenant_id,
        "name": f"K49b Missing Id Fixture {marker}",
        "first_name": "K49b",
        "last_name": "MissingIdFixture",
        "is_active": True,
        "k49b_test_marker": marker,
    })
    try:
        yield {**ctx, "oid": oid, "marker": marker}
    finally:
        _db.customers.delete_many({"_id": oid})


# ═════════════════════════════════════════════════════════════════════
# 1) Router guard — endpoint returns 200 even without the migration
# ═════════════════════════════════════════════════════════════════════
def test_k49b_router_guard_default_sort_returns_200(
    seeded_missing_id_customer,
):
    """The list handler must not KeyError on a doc that lacks
    ``id``. Uses the default sort to exercise the fast path."""
    r = requests.get(
        f"{API}/customers?page=1&page_size=200",
        headers=seeded_missing_id_customer["headers"], timeout=30,
    )
    assert r.status_code == 200, r.text


def test_k49b_router_guard_last_name_asc_returns_200(
    seeded_missing_id_customer,
):
    """K49's new aggregation path must also survive the missing-id
    doc without 500ing."""
    r = requests.get(
        f"{API}/customers?sort=last_name_asc&page=1&page_size=200",
        headers=seeded_missing_id_customer["headers"], timeout=30,
    )
    assert r.status_code == 200, r.text


def test_k49b_router_guard_bare_array_shape_returns_200(
    seeded_missing_id_customer,
):
    """Legacy no-pagination shape must not crash either."""
    r = requests.get(
        f"{API}/customers",
        headers=seeded_missing_id_customer["headers"], timeout=30,
    )
    assert r.status_code == 200, r.text


# ═════════════════════════════════════════════════════════════════════
# 2) Backfill migration — seeded doc surfaces with id=str(_id) after
# ═════════════════════════════════════════════════════════════════════
def test_k49b_backfill_migration_populates_id_from_oid(
    seeded_missing_id_customer,
):
    """Directly invoke the migration on the seeded doc's tenant and
    confirm the doc now has ``id = str(_id)``."""
    from migrations.k49b_customer_id_backfill import run
    ctx = seeded_missing_id_customer
    out = asyncio.run(run(apply=True, tenant_id=ctx["tenant_id"],
                              force=True))
    assert out["status"] == "applied"
    doc = _db.customers.find_one({"_id": ctx["oid"]})
    assert doc is not None
    assert doc.get("id") == str(ctx["oid"]), (
        f"expected id=str(_id), got {doc.get('id')!r}"
    )
    assert doc.get("k49b_id_backfilled_at"), (
        "backfilled doc missing the k49b_id_backfilled_at audit stamp"
    )


def test_k49b_backfill_migration_is_idempotent(
    seeded_missing_id_customer,
):
    """A second apply must not re-touch already-backfilled docs
    (the filter still requires the missing-id shape)."""
    from migrations.k49b_customer_id_backfill import run
    ctx = seeded_missing_id_customer
    # First apply — records the stamp.
    first = asyncio.run(run(apply=True, tenant_id=ctx["tenant_id"],
                                force=True))
    doc_after_first = _db.customers.find_one({"_id": ctx["oid"]})
    stamp_1 = doc_after_first.get("k49b_id_backfilled_at")
    # Second apply — must not change the doc or bump the stamp.
    second = asyncio.run(run(apply=True, tenant_id=ctx["tenant_id"],
                                 force=True))
    doc_after_second = _db.customers.find_one({"_id": ctx["oid"]})
    stamp_2 = doc_after_second.get("k49b_id_backfilled_at")
    assert stamp_1 == stamp_2, (
        "idempotent apply should NOT rewrite the audit stamp"
    )
    # Stats on second run should show 0 needing backfill.
    assert (second["stats"]["customers_needing_backfill"] == 0
              or second["stats"]["customers_applied"] == 0), (
        f"second apply should be a no-op, got: {second['stats']}"
    )


# ═════════════════════════════════════════════════════════════════════
# 3) Post-backfill the seeded doc surfaces on the wire with real id
# ═════════════════════════════════════════════════════════════════════
def test_k49b_seeded_doc_surfaces_with_valid_id_after_backfill(
    seeded_missing_id_customer,
):
    """After the migration runs, the seeded doc must appear in the
    list response with ``id`` populated (no more silent-skip)."""
    from migrations.k49b_customer_id_backfill import run
    ctx = seeded_missing_id_customer
    asyncio.run(run(apply=True, tenant_id=ctx["tenant_id"],
                        force=True))
    r = requests.get(
        f"{API}/customers?search=K49b+MissingIdFixture"
        f"&page=1&page_size=10",
        headers=ctx["headers"], timeout=30,
    )
    assert r.status_code == 200, r.text
    items = r.json().get("items", [])
    hits = [i for i in items if i.get("id") == str(ctx["oid"])]
    assert hits, (
        f"seeded doc should surface with id=str(_id) after backfill; "
        f"response items: {[i.get('id') for i in items]}"
    )
