"""Phase P4 · Feb-2026 — Recurring Jobs category dropdown backend
contract.

Locks the invariants for the PATCH-side of the two category-taxonomy
fields the Edit Recurring Job modal writes:

  • Both ids persist end-to-end.
  • Cross-tenant / archived / unknown id → HTTP 422 with the P4
    brief's ``code`` shape (``service_category_invalid`` /
    ``income_category_invalid``).
  • Explicit empty-string OR JSON ``null`` clears the field on the
    doc.
  • ``GET /service-categories`` and ``GET /income-categories``
    return only the requester's tenant's rows.

Backend was already ~90% wired for this (the fields, denorm names,
+ audit trail existed).  This suite pins the P4-specific status /
code alignment and the tenant-scoped list contract.
"""
from __future__ import annotations

import os
import uuid
from datetime import date, datetime, timezone
from typing import Any, Dict

import pytest
from fastapi.testclient import TestClient
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient

from server import app


TENANT_A = "P4_TEST_tenant_A"
TENANT_B = "P4_TEST_tenant_B"


def _sync_db():
    url = os.environ.get("MONGO_URL")
    name = os.environ.get("DB_NAME")
    if not (url and name):
        pytest.skip("MONGO_URL / DB_NAME not configured")
    return MongoClient(url)[name]


def _seed():
    """Two-tenant seed — A owns customers + templates + categories,
    B owns categories only (so we can prove A cannot reach B's
    category ids on PATCH)."""
    db = _sync_db()
    # Clean any prior run.
    for coll, filt in [
        ("tenants", {"id": {"$in": [TENANT_A, TENANT_B]}}),
        ("customers", {"tenant_id": {"$in": [TENANT_A, TENANT_B]}}),
        ("recurring_job_templates",
         {"tenant_id": {"$in": [TENANT_A, TENANT_B]}}),
        ("income_categories",
         {"tenant_id": {"$in": [TENANT_A, TENANT_B]}}),
        ("service_categories",
         {"tenant_id": {"$in": [TENANT_A, TENANT_B]}}),
    ]:
        db[coll].delete_many(filt)

    db.tenants.insert_many([
        {"id": TENANT_A, "name": "P4 T-A"},
        {"id": TENANT_B, "name": "P4 T-B"},
    ])
    db.customers.insert_one({
        "id": "P4_TEST_cust_A",
        "tenant_id": TENANT_A,
        "name": "P4 Cust A",
        "address": "1 Category Ln",
    })
    # Tenant A categories — normal + one archived (used to prove
    # archived rows are rejected the same way as cross-tenant).
    inc_A = str(uuid.uuid4())
    svc_A = str(uuid.uuid4())
    inc_A_archived = str(uuid.uuid4())
    svc_A_archived = str(uuid.uuid4())
    db.income_categories.insert_many([
        {"id": inc_A, "tenant_id": TENANT_A, "name": "P4 Pool Income",
         "is_archived": False, "sort_order": 0},
        {"id": inc_A_archived, "tenant_id": TENANT_A,
         "name": "P4 Archived Income",
         "is_archived": True, "sort_order": 99},
    ])
    db.service_categories.insert_many([
        {"id": svc_A, "tenant_id": TENANT_A,
         "name": "P4 Weekly Service",
         "is_archived": False, "sort_order": 0},
        {"id": svc_A_archived, "tenant_id": TENANT_A,
         "name": "P4 Archived Service",
         "is_archived": True, "sort_order": 99},
    ])
    # Tenant B has its own category ids that A must not be able
    # to reach.
    inc_B = str(uuid.uuid4())
    svc_B = str(uuid.uuid4())
    db.income_categories.insert_one({
        "id": inc_B, "tenant_id": TENANT_B,
        "name": "P4 Tenant B Income",
        "is_archived": False, "sort_order": 0,
    })
    db.service_categories.insert_one({
        "id": svc_B, "tenant_id": TENANT_B,
        "name": "P4 Tenant B Service",
        "is_archived": False, "sort_order": 0,
    })
    return {
        "inc_A": inc_A, "svc_A": svc_A,
        "inc_A_archived": inc_A_archived,
        "svc_A_archived": svc_A_archived,
        "inc_B": inc_B, "svc_B": svc_B,
    }


@pytest.fixture(scope="module")
def _module_client():
    """Module-scoped TestClient — the app's Motor io_loop binds
    to the portal's loop the first time TestClient enters its
    context, and stays valid for every test in this module.
    Function-scoping the TestClient causes "Event loop is
    closed" on the 2nd test because Motor caches the FIRST
    portal loop it saw."""
    from utils import require_admin, require_admin_or_manager, get_current_user
    from routers.tenants import get_current_tenant

    async def _fake_admin():
        return {
            "id": "P4_TEST_u_admin",
            "role": "admin",
            "email": "p4@example.com",
            "tenant_id": TENANT_A,
        }

    async def _fake_tenant():
        return {"id": TENANT_A, "name": "P4 T-A"}

    for dep in (require_admin, require_admin_or_manager, get_current_user):
        app.dependency_overrides[dep] = _fake_admin
    app.dependency_overrides[get_current_tenant] = _fake_tenant

    with TestClient(app) as tc:
        yield tc

    for dep in (require_admin, require_admin_or_manager, get_current_user):
        app.dependency_overrides.pop(dep, None)
    app.dependency_overrides.pop(get_current_tenant, None)


@pytest.fixture
def client(_module_client):
    """Function-scoped wrapper that re-seeds a clean two-tenant
    fixture per test so the previous test's PATCHes don't bleed
    over."""
    ids = _seed()
    # Also wipe any templates a prior test created — the seed
    # bulk-cleaned tenants above, so this is belt-and-suspenders.
    _sync_db().recurring_job_templates.delete_many(
        {"tenant_id": {"$in": [TENANT_A, TENANT_B]}},
    )
    yield _module_client, ids
    # Clean up any templates created via ``/api/recurring-jobs``.
    _sync_db().recurring_job_templates.delete_many(
        {"tenant_id": {"$in": [TENANT_A, TENANT_B]}},
    )


def _mk_template(tc: TestClient) -> str:
    today = date.today()
    r = tc.post("/api/recurring-jobs", json={
        "customer_id": "P4_TEST_cust_A",
        "service_type": "P4 fixture template",
        "frequency": "weekly", "day_of_week": today.weekday(),
        "start_date": today.isoformat(),
        "price_cents": 12000,
        "is_active": True, "active": True,
    })
    assert r.status_code == 200, r.text
    return r.json()["id"]


# ─────────────────────────────────────────────────────────────
# List endpoints — tenant scoping
# ─────────────────────────────────────────────────────────────
def test_p4_get_service_categories_is_tenant_scoped(client):
    """Tenant A's admin must see A's rows and NEVER B's rows."""
    tc, ids = client
    r = tc.get("/api/service-categories")
    assert r.status_code == 200, r.text
    body = r.json()
    all_ids = {c["id"] for c in body["items"]}
    assert ids["svc_A"] in all_ids
    # Never see B's row.
    assert ids["svc_B"] not in all_ids
    # Archived filtered out by default.
    assert ids["svc_A_archived"] not in all_ids


def test_p4_get_income_categories_is_tenant_scoped(client):
    tc, ids = client
    r = tc.get("/api/income-categories")
    assert r.status_code == 200, r.text
    all_ids = {c["id"] for c in r.json()["items"]}
    assert ids["inc_A"] in all_ids
    assert ids["inc_B"] not in all_ids
    assert ids["inc_A_archived"] not in all_ids


# ─────────────────────────────────────────────────────────────
# PATCH persists both ids
# ─────────────────────────────────────────────────────────────
def test_p4_patch_persists_both_ids(client):
    tc, ids = client
    tpl_id = _mk_template(tc)

    r = tc.patch(
        f"/api/recurring-jobs/{tpl_id}",
        json={
            "service_category_id": ids["svc_A"],
            "income_category_id": ids["inc_A"],
        },
    )
    assert r.status_code == 200, r.text

    # Read back the raw doc — verify both ids AND both denorm names
    # are persisted.
    doc = _sync_db().recurring_job_templates.find_one(
        {"id": tpl_id, "tenant_id": TENANT_A}, {"_id": 0},
    )
    assert doc["service_category_id"] == ids["svc_A"]
    assert doc["income_category_id"] == ids["inc_A"]
    assert doc["service_category_name"] == "P4 Weekly Service"
    assert doc["income_category_name"] == "P4 Pool Income"


# ─────────────────────────────────────────────────────────────
# Cross-tenant / archived → 422 w/ P4 code shape
# ─────────────────────────────────────────────────────────────
def test_p4_patch_cross_tenant_service_category_id_is_422(client):
    tc, ids = client
    tpl_id = _mk_template(tc)

    r = tc.patch(
        f"/api/recurring-jobs/{tpl_id}",
        json={"service_category_id": ids["svc_B"]},   # ← Tenant B's id
    )
    assert r.status_code == 422, r.text
    body = r.json()
    # FastAPI wraps HTTPException detail under "detail".
    assert body["detail"]["code"] == "service_category_invalid"
    assert body["detail"]["field"] == "service_category_id"

    # No leak — the doc was NOT partially updated.
    doc = _sync_db().recurring_job_templates.find_one(
        {"id": tpl_id, "tenant_id": TENANT_A}, {"_id": 0},
    )
    assert doc.get("service_category_id") in (None, "")


def test_p4_patch_cross_tenant_income_category_id_is_422(client):
    tc, ids = client
    tpl_id = _mk_template(tc)

    r = tc.patch(
        f"/api/recurring-jobs/{tpl_id}",
        json={"income_category_id": ids["inc_B"]},
    )
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["code"] == "income_category_invalid"


def test_p4_patch_archived_service_category_id_is_422(client):
    """Archived rows behave the same as cross-tenant on write —
    422 with the same code so the frontend can render one error
    branch."""
    tc, ids = client
    tpl_id = _mk_template(tc)

    r = tc.patch(
        f"/api/recurring-jobs/{tpl_id}",
        json={"service_category_id": ids["svc_A_archived"]},
    )
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["code"] == "service_category_invalid"


# ─────────────────────────────────────────────────────────────
# Clear-to-null — both empty string AND JSON null
# ─────────────────────────────────────────────────────────────
def test_p4_patch_empty_string_clears_field(client):
    tc, ids = client
    tpl_id = _mk_template(tc)

    # Set first.
    r = tc.patch(f"/api/recurring-jobs/{tpl_id}",
                     json={"service_category_id": ids["svc_A"]})
    assert r.status_code == 200
    # Clear via "".
    r = tc.patch(f"/api/recurring-jobs/{tpl_id}",
                     json={"service_category_id": ""})
    assert r.status_code == 200, r.text
    doc = _sync_db().recurring_job_templates.find_one(
        {"id": tpl_id, "tenant_id": TENANT_A}, {"_id": 0},
    )
    assert doc["service_category_id"] is None
    assert doc.get("service_category_name") is None


def test_p4_patch_missing_key_is_no_change(client):
    """If a key is OMITTED from the payload, the field must not be
    stamped to null.  Guards against a naïve ``$set`` that drops
    the pre-existing value."""
    tc, ids = client
    tpl_id = _mk_template(tc)

    # Seed both.
    tc.patch(f"/api/recurring-jobs/{tpl_id}", json={
        "service_category_id": ids["svc_A"],
        "income_category_id": ids["inc_A"],
    })
    # Now PATCH with an unrelated key.  Both category fields
    # must survive untouched.
    r = tc.patch(f"/api/recurring-jobs/{tpl_id}",
                     json={"notes": "P4 unrelated update"})
    assert r.status_code == 200, r.text
    doc = _sync_db().recurring_job_templates.find_one(
        {"id": tpl_id, "tenant_id": TENANT_A}, {"_id": 0},
    )
    assert doc["service_category_id"] == ids["svc_A"]
    assert doc["income_category_id"] == ids["inc_A"]
