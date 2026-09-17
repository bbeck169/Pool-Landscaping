"""Feb-2026 · Job Arrival unify · timer_duration_seconds computation."""
from __future__ import annotations

import os
import time
import uuid
from datetime import date, datetime, timezone

import pytest
from fastapi.testclient import TestClient
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient

from server import app


TENANT_ID = "test-tenant-timer-duration"


def _sync_db():
    url = os.environ.get("MONGO_URL")
    name = os.environ.get("DB_NAME")
    if not (url and name):
        pytest.skip("MONGO_URL / DB_NAME not configured")
    return MongoClient(url)[name]


def _seed_job() -> str:
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
    jid = f"job-{uuid.uuid4().hex[:8]}"
    db.jobs.insert_one({
        "id": jid, "tenant_id": TENANT_ID,
        "customer_id": "cust-1", "technician_id": "t1",
        "status": "scheduled", "service_type": "Landscape Mowing",
        "scheduled_date": date.today().isoformat(),
        "latitude": 33.5, "longitude": -112.0,
    })
    return jid


@pytest.fixture
def client(monkeypatch):
    from utils import get_current_user
    from routers.tenants import get_current_tenant

    async def _u():
        return {"id": "u_admin", "role": "admin", "email": "a@x",
                "tenant_id": TENANT_ID}
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


def test_arrive_then_complete_stamps_timer_duration_within_tolerance(client):
    """End-to-end: /arrive → sleep 2s → PUT status=completed. The
    completion path (``routers/jobs.py::update_job``) auto-computes
    ``timer_duration_seconds`` from ``timer_started_at`` → ``now``.
    Tolerance ±2s absorbs the sleep granularity + wall-clock jitter.
    """
    jid = _seed_job()

    # Arrive first — stamps timer_started_at.
    r = client.post(f"/api/jobs/{jid}/arrive",
                     json={"lat": 33.5, "lng": -112.0})
    assert r.status_code == 200, r.text
    start_iso = r.json()["timer_started_at"]
    start_dt = datetime.fromisoformat(start_iso.replace("Z", "+00:00"))

    # Simulate 2 seconds of service.
    time.sleep(2)

    # Complete the job — completion path auto-stops the timer.
    r2 = client.put(f"/api/jobs/{jid}", json={"status": "completed"})
    assert r2.status_code == 200, r2.text

    doc = _sync_db().jobs.find_one({"id": jid, "tenant_id": TENANT_ID})
    assert doc["timer_stopped_at"], "completion did not stamp timer_stopped_at"
    duration = doc.get("timer_duration_seconds")
    assert duration is not None, "timer_duration_seconds not stamped"
    # Sanity: duration is a non-negative int/float.
    assert isinstance(duration, (int, float)) and duration >= 0
    # Tolerance ±2s around the wall-clock elapsed time.
    stop_dt = datetime.fromisoformat(
        doc["timer_stopped_at"].replace("Z", "+00:00"),
    )
    actual_elapsed = (stop_dt - start_dt).total_seconds()
    assert abs(duration - actual_elapsed) <= 2.0, (
        f"timer_duration_seconds ({duration}) drifted from elapsed "
        f"({actual_elapsed}s)"
    )
    # And the elapsed itself is roughly the sleep (± the tolerance).
    assert 1.0 <= actual_elapsed <= 5.0, (
        f"Test fixture elapsed out of expected 1-5s: {actual_elapsed}s"
    )


def test_complete_without_arrive_does_not_stamp_duration(client):
    """Sanity guard: a job that goes ``scheduled → completed`` with
    no arrival stamps NO ``timer_duration_seconds``. The completion
    path only writes duration when ``timer_started_at`` is set."""
    jid = _seed_job()
    r = client.put(f"/api/jobs/{jid}", json={"status": "completed"})
    assert r.status_code == 200
    doc = _sync_db().jobs.find_one({"id": jid, "tenant_id": TENANT_ID})
    assert doc.get("timer_duration_seconds") is None
    assert doc.get("timer_stopped_at") is None
