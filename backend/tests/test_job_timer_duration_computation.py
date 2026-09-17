"""Feb-2026 · Job Arrival unify · timer_duration_seconds computation.

Test-infra note: Migrated OFF ``fastapi.testclient.TestClient``
ONTO the ``run_test`` + ``httpx.ASGITransport`` pattern.  Product-
code behaviour unchanged.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from datetime import date, datetime, timezone

import httpx
import pytest
from pymongo import MongoClient

from tests._f7_loop_fixture import run_test


TENANT_ID = "test-tenant-timer-duration"


def _get_app():
    from server import app
    return app


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


def _install_overrides():
    from utils import get_current_user
    from routers.tenants import get_current_tenant

    app = _get_app()

    async def _u():
        return {"id": "u_admin", "role": "admin", "email": "a@x",
                "tenant_id": TENANT_ID}
    async def _t():
        return {"id": TENANT_ID, "name": "T",
                "gps_auto_start_enabled": True}
    app.dependency_overrides[get_current_user] = _u
    app.dependency_overrides[get_current_tenant] = _t

    def _clear():
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(get_current_tenant, None)
    return _clear


def _run_with_http(coro):
    async def _go(db):
        transport = httpx.ASGITransport(app=_get_app())
        async with httpx.AsyncClient(transport=transport,
                                             base_url="http://test") as ac:
            await coro(ac, db)
    return run_test(_go)


def test_arrive_then_complete_stamps_timer_duration_within_tolerance():
    """End-to-end: /arrive → sleep 2s → PUT status=completed. The
    completion path (``routers/jobs.py::update_job``) auto-computes
    ``timer_duration_seconds`` from ``timer_started_at`` → ``now``.
    Tolerance ±2s absorbs the sleep granularity + wall-clock jitter.
    """
    jid = _seed_job()
    clear = _install_overrides()
    try:
        async def _t(ac, db):
            # Arrive first — stamps timer_started_at.
            r = await ac.post(f"/api/jobs/{jid}/arrive",
                                json={"lat": 33.5, "lng": -112.0})
            assert r.status_code == 200, r.text
            start_iso = r.json()["timer_started_at"]
            start_dt = datetime.fromisoformat(
                start_iso.replace("Z", "+00:00"))

            # Simulate 2 seconds of service (async-safe sleep so we
            # don't block the loop).
            await asyncio.sleep(2)

            # Complete the job — completion path auto-stops the timer.
            r2 = await ac.put(f"/api/jobs/{jid}",
                                json={"status": "completed"})
            assert r2.status_code == 200, r2.text

            doc = await db.jobs.find_one(
                {"id": jid, "tenant_id": TENANT_ID})
            assert doc["timer_stopped_at"], \
                "completion did not stamp timer_stopped_at"
            duration = doc.get("timer_duration_seconds")
            assert duration is not None, \
                "timer_duration_seconds not stamped"
            assert isinstance(duration, (int, float)) and duration >= 0
            stop_dt = datetime.fromisoformat(
                doc["timer_stopped_at"].replace("Z", "+00:00"),
            )
            actual_elapsed = (stop_dt - start_dt).total_seconds()
            assert abs(duration - actual_elapsed) <= 2.0, (
                f"timer_duration_seconds ({duration}) drifted from "
                f"elapsed ({actual_elapsed}s)"
            )
            assert 1.0 <= actual_elapsed <= 5.0, (
                f"Test fixture elapsed out of 1-5s: {actual_elapsed}s"
            )
        _run_with_http(_t)
    finally:
        clear()


def test_complete_without_arrive_does_not_stamp_duration():
    """Sanity guard: a job that goes ``scheduled → completed`` with
    no arrival stamps NO ``timer_duration_seconds``. The completion
    path only writes duration when ``timer_started_at`` is set."""
    jid = _seed_job()
    clear = _install_overrides()
    try:
        async def _t(ac, db):
            r = await ac.put(f"/api/jobs/{jid}",
                                json={"status": "completed"})
            assert r.status_code == 200
            doc = await db.jobs.find_one(
                {"id": jid, "tenant_id": TENANT_ID})
            assert doc.get("timer_duration_seconds") is None
            assert doc.get("timer_stopped_at") is None
        _run_with_http(_t)
    finally:
        clear()
