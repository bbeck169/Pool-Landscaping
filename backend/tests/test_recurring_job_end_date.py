"""Feb-2026 · Recurring Jobs · end_date validation + auto-stop."""
from __future__ import annotations

import os
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient

from server import app


TENANT_ID = "test-tenant-rj-enddate"


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
    db.jobs.delete_many({"tenant_id": TENANT_ID})
    db.customers.delete_many({"tenant_id": TENANT_ID})
    db.customers.insert_one({
        "id": "cust-1", "tenant_id": TENANT_ID,
        "name": "Alice", "address": "1 St",
    })


@pytest.fixture
def client(monkeypatch):
    from utils import require_admin, require_admin_or_manager, get_current_user
    from routers.tenants import get_current_tenant

    async def _fake_admin():
        return {"id": "u_admin", "role": "admin",
                "email": "a@x", "tenant_id": TENANT_ID}

    async def _fake_tenant():
        return {"id": TENANT_ID, "name": "T"}

    for dep in (require_admin, require_admin_or_manager, get_current_user):
        app.dependency_overrides[dep] = _fake_admin
    app.dependency_overrides[get_current_tenant] = _fake_tenant

    _seed()
    import config
    fresh = AsyncIOMotorClient(os.environ["MONGO_URL"], maxPoolSize=50)
    monkeypatch.setattr(config, "client", fresh, raising=False)
    monkeypatch.setattr(config, "db", fresh[os.environ["DB_NAME"]], raising=False)
    import routers.recurring_jobs as _rj
    monkeypatch.setattr(_rj, "db", fresh[os.environ["DB_NAME"]], raising=False)

    tc = TestClient(app)
    yield tc

    for dep in (require_admin, require_admin_or_manager, get_current_user):
        app.dependency_overrides.pop(dep, None)
    app.dependency_overrides.pop(get_current_tenant, None)
    fresh.close()


def _create_body(**over):
    today = date.today()
    base = {
        "customer_id": "cust-1", "service_type": "Weekly Pool",
        "frequency": "weekly", "day_of_week": today.weekday(),
        "start_date": today.isoformat(),
        "price_cents": 10000,
        "is_active": True, "active": True,
    }
    base.update(over)
    return base


def test_post_with_end_date_creates_template(client):
    today = date.today()
    end = today + timedelta(days=30)
    r = client.post("/api/recurring-jobs",
                     json=_create_body(end_date=end.isoformat()))
    assert r.status_code == 200, r.text
    assert r.json()["end_date"] == end.isoformat()


def test_post_end_date_before_start_date_rejected(client):
    today = date.today()
    end = today - timedelta(days=5)
    r = client.post("/api/recurring-jobs",
                     json=_create_body(end_date=end.isoformat()))
    assert r.status_code == 400, r.text
    assert r.json()["detail"]["error"] == "end_date_before_start_date"


def test_post_end_date_equals_start_date_ok(client):
    today = date.today()
    r = client.post("/api/recurring-jobs",
                     json=_create_body(end_date=today.isoformat()))
    assert r.status_code == 200, r.text
    assert r.json()["end_date"] == today.isoformat()


def test_patch_updates_end_date(client):
    r = client.post("/api/recurring-jobs", json=_create_body())
    tpl_id = r.json()["id"]
    new_end = (date.today() + timedelta(days=45)).isoformat()
    r2 = client.patch(f"/api/recurring-jobs/{tpl_id}",
                        json={"end_date": new_end})
    assert r2.status_code == 200, r2.text
    assert r2.json()["end_date"] == new_end


def test_no_end_date_means_infinity_no_stop(client):
    """POST without end_date + call the cron helper — template
    remains active. Auto-stop should NOT fire because end_date is
    ``None``."""
    body = _create_body()
    body.pop("end_date", None)
    r = client.post("/api/recurring-jobs", json=body)
    tpl_id = r.json()["id"]
    # Run generator through a horizon 30 days out.
    through = (date.today() + timedelta(days=30)).isoformat()
    r2 = client.post(f"/api/recurring-jobs/{tpl_id}/generate?through={through}")
    assert r2.status_code == 200, r2.text
    tpl_after = _sync_db().recurring_job_templates.find_one(
        {"id": tpl_id, "tenant_id": TENANT_ID}, {"_id": 0},
    )
    assert tpl_after["active"] is True


def test_materialization_stops_past_end_date_and_transitions(client):
    """Template with end_date 2 days ago + last_generated_through
    already past end_date → next generate call must transition the
    template to inactive (auto-stop)."""
    today = date.today()
    end = today - timedelta(days=2)
    start = today - timedelta(days=30)
    body = _create_body(
        start_date=start.isoformat(),
        end_date=end.isoformat(),
        day_of_week=start.weekday(),
    )
    r = client.post("/api/recurring-jobs", json=body)
    tpl_id = r.json()["id"]
    # Fast-forward the cursor past the end date so ``_next_occurrences``
    # returns [] and the auto-stop branch fires.
    _sync_db().recurring_job_templates.update_one(
        {"id": tpl_id, "tenant_id": TENANT_ID},
        {"$set": {"last_generated_through": end.isoformat()}},
    )
    through = (today + timedelta(days=14)).isoformat()
    r2 = client.post(f"/api/recurring-jobs/{tpl_id}/generate?through={through}")
    assert r2.status_code == 200, r2.text
    assert r2.json()["inserted"] == 0
    tpl_after = _sync_db().recurring_job_templates.find_one(
        {"id": tpl_id, "tenant_id": TENANT_ID}, {"_id": 0},
    )
    assert tpl_after["active"] is False
    assert tpl_after["is_active"] is False
    assert tpl_after.get("stopped_at")


def test_materialization_inclusive_end_date(client):
    """A recurrence whose scheduled_date lands ON the end_date
    should still generate — inclusive semantics."""
    today = date.today()
    # weekly recurrence starting today, ending today → single-shot.
    body = _create_body(
        end_date=today.isoformat(),
    )
    r = client.post("/api/recurring-jobs", json=body)
    tpl_id = r.json()["id"]
    r2 = client.post(f"/api/recurring-jobs/{tpl_id}/generate?through={today.isoformat()}")
    assert r2.status_code == 200, r2.text
    assert r2.json()["inserted"] == 1
    assert r2.json()["dates"] == [today.isoformat()]
