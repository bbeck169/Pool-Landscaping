"""Feb-2026 · Recurring Jobs · category PATCH audit trail."""
from __future__ import annotations

import os
import uuid
from datetime import date

import pytest
from fastapi.testclient import TestClient
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient

from server import app


TENANT_ID = "test-tenant-rj-catpatch-audit"


def _sync_db():
    url = os.environ.get("MONGO_URL")
    name = os.environ.get("DB_NAME")
    if not (url and name):
        pytest.skip("MONGO_URL / DB_NAME not configured")
    return MongoClient(url)[name]


def _seed():
    db = _sync_db()
    db.tenants.delete_many({"id": TENANT_ID})
    db.tenants.insert_one({"id": TENANT_ID, "name": "T"})
    db.recurring_job_templates.delete_many({"tenant_id": TENANT_ID})
    db.customers.delete_many({"tenant_id": TENANT_ID})
    db.customers.insert_one({
        "id": "c1", "tenant_id": TENANT_ID, "name": "A", "address": "1 St",
    })
    db.income_categories.delete_many({"tenant_id": TENANT_ID})
    db.service_categories.delete_many({"tenant_id": TENANT_ID})
    db.audit_logs.delete_many(
        {"tenant_id": TENANT_ID, "event": "recurring_job.recategorize"},
    )
    inc_id = str(uuid.uuid4())
    svc_id = str(uuid.uuid4())
    db.income_categories.insert_one({
        "id": inc_id, "tenant_id": TENANT_ID, "name": "Pool",
        "is_archived": False,
    })
    db.service_categories.insert_one({
        "id": svc_id, "tenant_id": TENANT_ID, "name": "Weekly Service",
        "is_archived": False,
    })
    return inc_id, svc_id


@pytest.fixture
def client(monkeypatch):
    from utils import require_admin, require_admin_or_manager, get_current_user
    from routers.tenants import get_current_tenant

    async def _fake_admin():
        return {"id": "u_admin", "role": "admin", "email": "a@x",
                "tenant_id": TENANT_ID}
    async def _fake_tenant():
        return {"id": TENANT_ID, "name": "T"}
    for dep in (require_admin, require_admin_or_manager, get_current_user):
        app.dependency_overrides[dep] = _fake_admin
    app.dependency_overrides[get_current_tenant] = _fake_tenant

    ids = _seed()
    import config
    fresh = AsyncIOMotorClient(os.environ["MONGO_URL"], maxPoolSize=50)
    monkeypatch.setattr(config, "client", fresh, raising=False)
    monkeypatch.setattr(config, "db", fresh[os.environ["DB_NAME"]], raising=False)
    import routers.recurring_jobs as _rj
    monkeypatch.setattr(_rj, "db", fresh[os.environ["DB_NAME"]], raising=False)

    tc = TestClient(app)
    yield tc, ids

    for dep in (require_admin, require_admin_or_manager, get_current_user):
        app.dependency_overrides.pop(dep, None)
    app.dependency_overrides.pop(get_current_tenant, None)
    fresh.close()


def _mk(tc):
    today = date.today()
    r = tc.post("/api/recurring-jobs", json={
        "customer_id": "c1", "service_type": "W",
        "frequency": "weekly", "day_of_week": today.weekday(),
        "start_date": today.isoformat(),
        "price_cents": 10000, "is_active": True, "active": True,
    })
    return r.json()["id"]


def test_patch_writes_recategorize_audit_row(client):
    tc, (inc_id, svc_id) = client
    tpl_id = _mk(tc)
    r = tc.patch(f"/api/recurring-jobs/{tpl_id}", json={
        "service_category_id": svc_id, "income_category_id": inc_id,
    })
    assert r.status_code == 200
    row = _sync_db().audit_logs.find_one(
        {"tenant_id": TENANT_ID,
          "event": "recurring_job.recategorize",
          "recurring_template_id": tpl_id},
        {"_id": 0},
    )
    assert row is not None
    assert row["diff"]["service_category_id"]["after"] == svc_id
    assert row["diff"]["income_category_id"]["after"] == inc_id
    assert row["diff"]["service_category_name"]["after"] == "Weekly Service"
    assert row["actor_email"] == "a@x"


def test_patch_no_category_change_no_audit_row(client):
    tc, _ = client
    tpl_id = _mk(tc)
    r = tc.patch(f"/api/recurring-jobs/{tpl_id}", json={
        "notes": "just a note update",
    })
    assert r.status_code == 200
    count = _sync_db().audit_logs.count_documents(
        {"tenant_id": TENANT_ID,
          "event": "recurring_job.recategorize",
          "recurring_template_id": tpl_id},
    )
    assert count == 0


def test_patch_same_category_idempotent_no_new_audit(client):
    tc, (inc_id, _) = client
    tpl_id = _mk(tc)
    tc.patch(f"/api/recurring-jobs/{tpl_id}",
                json={"income_category_id": inc_id})
    tc.patch(f"/api/recurring-jobs/{tpl_id}",
                json={"income_category_id": inc_id})
    count = _sync_db().audit_logs.count_documents(
        {"tenant_id": TENANT_ID,
          "event": "recurring_job.recategorize",
          "recurring_template_id": tpl_id},
    )
    # First call writes 1. Second is a no-op diff so no new row.
    assert count == 1
