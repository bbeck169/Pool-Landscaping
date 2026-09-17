"""Feb-2026 · Recurring Jobs · category PATCH happy path + validation."""
from __future__ import annotations

import os
import uuid
from datetime import date

import pytest
from fastapi.testclient import TestClient
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient

from server import app


TENANT_ID = "test-tenant-rj-catpatch"


def _sync_db():
    url = os.environ.get("MONGO_URL")
    name = os.environ.get("DB_NAME")
    if not (url and name):
        pytest.skip("MONGO_URL / DB_NAME not configured")
    return MongoClient(url)[name]


def _seed_state():
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

    ids = _seed_state()
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


def _mk_template(client):
    today = date.today()
    r = client.post("/api/recurring-jobs", json={
        "customer_id": "c1", "service_type": "Weekly", "frequency": "weekly",
        "day_of_week": today.weekday(), "start_date": today.isoformat(),
        "price_cents": 10000, "is_active": True, "active": True,
    })
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_patch_sets_service_category_and_income_category(client):
    tc, (inc_id, svc_id) = client
    tpl_id = _mk_template(tc)
    r = tc.patch(f"/api/recurring-jobs/{tpl_id}", json={
        "service_category_id": svc_id, "income_category_id": inc_id,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["service_category_id"] == svc_id
    assert body["income_category_id"] == inc_id
    assert body["service_category_name"] == "Weekly Service"
    assert body["income_category_name"] == "Pool"


def test_patch_unknown_category_id_404(client):
    tc, _ = client
    tpl_id = _mk_template(tc)
    r = tc.patch(f"/api/recurring-jobs/{tpl_id}", json={
        "service_category_id": "does-not-exist",
    })
    assert r.status_code == 404, r.text
    assert "not_found" in r.json()["detail"]["error"]


def test_patch_archived_category_404(client):
    tc, (inc_id, svc_id) = client
    _sync_db().service_categories.update_one(
        {"id": svc_id, "tenant_id": TENANT_ID}, {"$set": {"is_archived": True}},
    )
    tpl_id = _mk_template(tc)
    r = tc.patch(f"/api/recurring-jobs/{tpl_id}", json={
        "service_category_id": svc_id,
    })
    assert r.status_code == 404


def test_patch_empty_string_clears_category(client):
    tc, (inc_id, svc_id) = client
    tpl_id = _mk_template(tc)
    tc.patch(f"/api/recurring-jobs/{tpl_id}", json={
        "income_category_id": inc_id,
    })
    r = tc.patch(f"/api/recurring-jobs/{tpl_id}", json={
        "income_category_id": "",
    })
    assert r.status_code == 200, r.text
    assert r.json()["income_category_id"] is None
    assert r.json()["income_category_name"] is None


def test_patch_over_80_chars_rejected(client):
    tc, _ = client
    tpl_id = _mk_template(tc)
    r = tc.patch(f"/api/recurring-jobs/{tpl_id}", json={
        "service_category_id": "x" * 81,
    })
    assert r.status_code == 422


def test_patch_html_in_category_rejected(client):
    tc, _ = client
    tpl_id = _mk_template(tc)
    r = tc.patch(f"/api/recurring-jobs/{tpl_id}", json={
        "service_category_id": "<script>alert(1)</script>",
    })
    assert r.status_code == 422
