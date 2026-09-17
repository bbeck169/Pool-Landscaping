"""Feb-2026 · Job Arrival unify · endpoint contract regression."""
from __future__ import annotations

import os
import uuid
from datetime import date, datetime, timezone

import pytest
from fastapi.testclient import TestClient
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient

from server import app


TENANT_ID = "test-tenant-job-arrive"
TECH_ID = "tech-assigned-42"
TECH_OTHER_ID = "tech-not-assigned-7"


def _sync_db():
    url = os.environ.get("MONGO_URL")
    name = os.environ.get("DB_NAME")
    if not (url and name):
        pytest.skip("MONGO_URL / DB_NAME not configured")
    return MongoClient(url)[name]


def _seed_job(*, status="scheduled") -> str:
    db = _sync_db()
    db.tenants.delete_many({"id": TENANT_ID})
    db.tenants.insert_one({"id": TENANT_ID, "name": "T",
                             "gps_auto_start_enabled": True})
    db.customers.delete_many({"tenant_id": TENANT_ID})
    db.customers.insert_one({
        "id": "cust-1", "tenant_id": TENANT_ID, "name": "A",
        "address": "1 Main St", "latitude": 33.5, "longitude": -112.0,
    })
    db.jobs.delete_many({"tenant_id": TENANT_ID})
    db.gps_consent_grants.delete_many({"tenant_id": TENANT_ID})
    # Bypass P37 consent gate — grant the tech an active consent row.
    db.gps_consent_grants.insert_one({
        "id": uuid.uuid4().hex, "tenant_id": TENANT_ID,
        "user_id": TECH_ID, "state": "granted",
        "granted_at": datetime.now(timezone.utc).isoformat(),
    })
    jid = f"job-{uuid.uuid4().hex[:8]}"
    db.jobs.insert_one({
        "id": jid, "tenant_id": TENANT_ID,
        "customer_id": "cust-1", "technician_id": TECH_ID,
        "status": status, "service_type": "Landscape Mowing",
        "scheduled_date": date.today().isoformat(),
        "latitude": 33.5, "longitude": -112.0,  # site coords
    })
    return jid


def _current_user(*, role, uid=None):
    return {"id": uid or "u_admin", "role": role,
            "email": f"{role}@x", "tenant_id": TENANT_ID}


@pytest.fixture
def client_admin(monkeypatch):
    from utils import get_current_user
    from routers.tenants import get_current_tenant

    async def _u():
        return _current_user(role="admin")
    async def _t():
        return {"id": TENANT_ID, "name": "T",
                "gps_auto_start_enabled": True}
    app.dependency_overrides[get_current_user] = _u
    app.dependency_overrides[get_current_tenant] = _t

    import config
    fresh = AsyncIOMotorClient(os.environ["MONGO_URL"], maxPoolSize=50)
    monkeypatch.setattr(config, "client", fresh, raising=False)
    monkeypatch.setattr(config, "db", fresh[os.environ["DB_NAME"]], raising=False)
    import routers.jobs as _jobs
    import routers.job_timers as _jt
    import utils_idempotency as _uti
    monkeypatch.setattr(_jobs, "db", fresh[os.environ["DB_NAME"]], raising=False)
    monkeypatch.setattr(_jt, "db", fresh[os.environ["DB_NAME"]], raising=False)
    monkeypatch.setattr(_uti, "db", fresh[os.environ["DB_NAME"]], raising=False)

    tc = TestClient(app)
    yield tc

    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(get_current_tenant, None)
    fresh.close()


@pytest.fixture
def client_tech(monkeypatch):
    from utils import get_current_user
    from routers.tenants import get_current_tenant

    async def _u():
        return _current_user(role="technician", uid=TECH_ID)
    async def _t():
        return {"id": TENANT_ID, "name": "T",
                "gps_auto_start_enabled": True}
    app.dependency_overrides[get_current_user] = _u
    app.dependency_overrides[get_current_tenant] = _t

    import config
    fresh = AsyncIOMotorClient(os.environ["MONGO_URL"], maxPoolSize=50)
    monkeypatch.setattr(config, "client", fresh, raising=False)
    monkeypatch.setattr(config, "db", fresh[os.environ["DB_NAME"]], raising=False)
    import routers.jobs as _jobs
    import routers.job_timers as _jt
    import utils_idempotency as _uti
    monkeypatch.setattr(_jobs, "db", fresh[os.environ["DB_NAME"]], raising=False)
    monkeypatch.setattr(_jt, "db", fresh[os.environ["DB_NAME"]], raising=False)
    monkeypatch.setattr(_uti, "db", fresh[os.environ["DB_NAME"]], raising=False)

    tc = TestClient(app)
    yield tc

    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(get_current_tenant, None)
    fresh.close()


@pytest.fixture
def client_other_tech(monkeypatch):
    from utils import get_current_user
    from routers.tenants import get_current_tenant

    async def _u():
        return _current_user(role="technician", uid=TECH_OTHER_ID)
    async def _t():
        return {"id": TENANT_ID, "name": "T",
                "gps_auto_start_enabled": True}
    app.dependency_overrides[get_current_user] = _u
    app.dependency_overrides[get_current_tenant] = _t

    import config
    fresh = AsyncIOMotorClient(os.environ["MONGO_URL"], maxPoolSize=50)
    monkeypatch.setattr(config, "client", fresh, raising=False)
    monkeypatch.setattr(config, "db", fresh[os.environ["DB_NAME"]], raising=False)
    import routers.jobs as _jobs
    import routers.job_timers as _jt
    import utils_idempotency as _uti
    monkeypatch.setattr(_jobs, "db", fresh[os.environ["DB_NAME"]], raising=False)
    monkeypatch.setattr(_jt, "db", fresh[os.environ["DB_NAME"]], raising=False)
    monkeypatch.setattr(_uti, "db", fresh[os.environ["DB_NAME"]], raising=False)

    tc = TestClient(app)
    yield tc

    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(get_current_tenant, None)
    fresh.close()


def _arrive_body(**over):
    body = {"lat": 33.5, "lng": -112.0}
    body.update(over)
    return body


# ── Happy path ────────────────────────────────────────────────────
def test_admin_arrive_stamps_timer_started_at(client_admin):
    jid = _seed_job()
    r = client_admin.post(f"/api/jobs/{jid}/arrive", json=_arrive_body())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["started"] is True
    assert body["already_running"] is False
    assert body["already_arrived"] is False  # alias present on fresh start
    assert body["timer_started_at"]
    doc = _sync_db().jobs.find_one({"id": jid, "tenant_id": TENANT_ID})
    assert doc["timer_started_at"] == body["timer_started_at"]


def test_assigned_tech_can_arrive(client_tech):
    jid = _seed_job()
    r = client_tech.post(f"/api/jobs/{jid}/arrive", json=_arrive_body())
    assert r.status_code == 200, r.text
    assert r.json()["started"] is True


# ── Idempotency (both alias keys present + no overwrite) ──────────
def test_idempotent_second_call_returns_both_alias_flags(client_admin):
    jid = _seed_job()
    r1 = client_admin.post(f"/api/jobs/{jid}/arrive", json=_arrive_body())
    started_at = r1.json()["timer_started_at"]

    r2 = client_admin.post(f"/api/jobs/{jid}/arrive", json=_arrive_body())
    assert r2.status_code == 200
    body2 = r2.json()
    # ── The pinned contract for mobile:
    assert body2["already_running"] is True
    assert body2["already_arrived"] is True
    assert body2["timer_started_at"] == started_at  # no overwrite


def test_idempotent_call_does_not_overwrite_start_stamp(client_admin):
    jid = _seed_job()
    r1 = client_admin.post(f"/api/jobs/{jid}/arrive", json=_arrive_body())
    stored = _sync_db().jobs.find_one({"id": jid})["timer_started_at"]
    for _ in range(3):
        client_admin.post(f"/api/jobs/{jid}/arrive", json=_arrive_body())
    assert _sync_db().jobs.find_one({"id": jid})["timer_started_at"] == stored


# ── Auth ──────────────────────────────────────────────────────────
def test_non_assigned_tech_forbidden(client_other_tech):
    jid = _seed_job()
    r = client_other_tech.post(f"/api/jobs/{jid}/arrive", json=_arrive_body())
    assert r.status_code == 403


# ── Source whitelist ──────────────────────────────────────────────
@pytest.mark.parametrize("src", ["geofence", "manual", "route_start"])
def test_source_whitelist_accepted(client_admin, src):
    jid = _seed_job()
    r = client_admin.post(f"/api/jobs/{jid}/arrive",
                            json=_arrive_body(source=src))
    assert r.status_code == 200, r.text
    doc = _sync_db().jobs.find_one({"id": jid})
    assert doc["timer_start_method"] == src


def test_source_absent_defaults_to_gps_arrival(client_admin):
    """Byte-identical legacy behavior — mobile clients that don't
    send ``source`` still see ``timer_start_method='gps_arrival'``."""
    jid = _seed_job()
    r = client_admin.post(f"/api/jobs/{jid}/arrive", json=_arrive_body())
    assert r.status_code == 200
    doc = _sync_db().jobs.find_one({"id": jid})
    assert doc["timer_start_method"] == "gps_arrival"


def test_source_invalid_value_rejected(client_admin):
    jid = _seed_job()
    r = client_admin.post(f"/api/jobs/{jid}/arrive",
                            json=_arrive_body(source="teleport"))
    assert r.status_code == 400
    assert r.json()["detail"]["error"] == "invalid_source"
    assert set(r.json()["detail"]["allowed"]) == {
        "geofence", "manual", "route_start",
    }


def test_source_empty_string_rejected(client_admin):
    jid = _seed_job()
    r = client_admin.post(f"/api/jobs/{jid}/arrive",
                            json=_arrive_body(source=""))
    assert r.status_code == 400
