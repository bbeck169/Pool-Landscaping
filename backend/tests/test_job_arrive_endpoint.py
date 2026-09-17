"""Feb-2026 · Job Arrival unify · endpoint contract regression.

Test-infra note (Feb 2026): Migrated OFF ``fastapi.testclient.
TestClient`` (shared Motor loop → ``RuntimeError: Event loop is
closed``) ONTO the ``run_test(coro_factory)`` + ``httpx.
ASGITransport`` pattern.  No product-code changes.
"""
from __future__ import annotations

import os
import uuid
from datetime import date, datetime, timezone

import httpx
import pytest
from pymongo import MongoClient

from tests._f7_loop_fixture import run_test


TENANT_ID = "test-tenant-job-arrive"
TECH_ID = "tech-assigned-42"
TECH_OTHER_ID = "tech-not-assigned-7"


def _get_app():
    from server import app
    return app


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
    # Bypass P37 consent gate — grant the tech an active consent row.
    # NOTE: the endpoint reads ``db.tech_gps_consents`` with
    # ``{granted: True, revoked_at: None}``.  Pre-P1 seeds targeted
    # a legacy ``gps_consent_grants`` collection (never wired), which
    # is why the ``test_assigned_tech_can_arrive`` case only reached
    # green in isolation.  Seeded here on the correct collection so
    # the tech gate resolves ``consent_state=active``.
    db.tech_gps_consents.delete_many({"tenant_id": TENANT_ID})
    db.tech_gps_consents.insert_one({
        "id": uuid.uuid4().hex, "tenant_id": TENANT_ID,
        "user_id": TECH_ID, "granted": True, "revoked_at": None,
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


def _install_overrides(*, role, uid=None):
    """Install fake current-user + tenant deps. Returns a cleanup fn."""
    from utils import get_current_user
    from routers.tenants import get_current_tenant

    app = _get_app()

    async def _u():
        return _current_user(role=role, uid=uid)
    async def _t():
        return {"id": TENANT_ID, "name": "T",
                "gps_auto_start_enabled": True}
    app.dependency_overrides[get_current_user] = _u
    app.dependency_overrides[get_current_tenant] = _t

    def _clear():
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(get_current_tenant, None)
    return _clear


def _arrive_body(**over):
    body = {"lat": 33.5, "lng": -112.0}
    body.update(over)
    return body


def _run_as(role, coro, *, uid=None):
    """Wrap ``coro(ac, db)`` on a fresh loop with the requested role's
    dependency overrides installed."""
    clear = _install_overrides(role=role, uid=uid)
    try:
        async def _go(db):
            transport = httpx.ASGITransport(app=_get_app())
            async with httpx.AsyncClient(transport=transport,
                                                 base_url="http://test") as ac:
                await coro(ac, db)
        run_test(_go)
    finally:
        clear()


# ── Happy path ────────────────────────────────────────────────────
def test_admin_arrive_stamps_timer_started_at():
    jid = _seed_job()
    async def _t(ac, db):
        r = await ac.post(f"/api/jobs/{jid}/arrive", json=_arrive_body())
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["started"] is True
        assert body["already_running"] is False
        assert body["already_arrived"] is False  # alias present on fresh start
        assert body["timer_started_at"]
        doc = await db.jobs.find_one({"id": jid, "tenant_id": TENANT_ID})
        assert doc["timer_started_at"] == body["timer_started_at"]
    _run_as("admin", _t)


def test_assigned_tech_can_arrive():
    jid = _seed_job()
    async def _t(ac, db):
        r = await ac.post(f"/api/jobs/{jid}/arrive", json=_arrive_body())
        assert r.status_code == 200, r.text
        assert r.json()["started"] is True, f"body={r.json()!r}"
    _run_as("technician", _t, uid=TECH_ID)


# ── Idempotency (both alias keys present + no overwrite) ──────────
def test_idempotent_second_call_returns_both_alias_flags():
    jid = _seed_job()
    async def _t(ac, db):
        r1 = await ac.post(f"/api/jobs/{jid}/arrive", json=_arrive_body())
        started_at = r1.json()["timer_started_at"]
        # Reset the per-(user,job) 60s rate-limit cache between calls
        # so the second POST reaches the ``already_running`` branch
        # instead of the throttle gate.
        from routers.gps_auto_start import _RATE_LIMIT_CACHE
        _RATE_LIMIT_CACHE.clear()
        r2 = await ac.post(f"/api/jobs/{jid}/arrive", json=_arrive_body())
        assert r2.status_code == 200
        body2 = r2.json()
        # ── The pinned contract for mobile:
        assert body2["already_running"] is True
        assert body2["already_arrived"] is True
        assert body2["timer_started_at"] == started_at  # no overwrite
    _run_as("admin", _t)


def test_idempotent_call_does_not_overwrite_start_stamp():
    jid = _seed_job()
    async def _t(ac, db):
        from routers.gps_auto_start import _RATE_LIMIT_CACHE
        r1 = await ac.post(f"/api/jobs/{jid}/arrive", json=_arrive_body())
        assert r1.status_code == 200, r1.text
        stored = (await db.jobs.find_one({"id": jid}))["timer_started_at"]
        for _ in range(3):
            # Reset the throttle cache before each replay so we
            # actually reach the ``already_running`` branch.
            _RATE_LIMIT_CACHE.clear()
            await ac.post(f"/api/jobs/{jid}/arrive", json=_arrive_body())
        again = await db.jobs.find_one({"id": jid})
        assert again["timer_started_at"] == stored
    _run_as("admin", _t)


# ── Auth ──────────────────────────────────────────────────────────
def test_non_assigned_tech_forbidden():
    jid = _seed_job()
    async def _t(ac, db):
        r = await ac.post(f"/api/jobs/{jid}/arrive", json=_arrive_body())
        assert r.status_code == 403
    _run_as("technician", _t, uid=TECH_OTHER_ID)


# ── Source whitelist ──────────────────────────────────────────────
@pytest.mark.parametrize("src", ["geofence", "manual", "route_start"])
def test_source_whitelist_accepted(src):
    jid = _seed_job()
    async def _t(ac, db):
        r = await ac.post(f"/api/jobs/{jid}/arrive",
                            json=_arrive_body(source=src))
        assert r.status_code == 200, r.text
        doc = await db.jobs.find_one({"id": jid})
        assert doc["timer_start_method"] == src
    _run_as("admin", _t)


def test_source_absent_defaults_to_gps_arrival():
    """Byte-identical legacy behavior — mobile clients that don't
    send ``source`` still see ``timer_start_method='gps_arrival'``."""
    jid = _seed_job()
    async def _t(ac, db):
        r = await ac.post(f"/api/jobs/{jid}/arrive", json=_arrive_body())
        assert r.status_code == 200
        doc = await db.jobs.find_one({"id": jid})
        assert doc["timer_start_method"] == "gps_arrival"
    _run_as("admin", _t)


def test_source_invalid_value_rejected():
    jid = _seed_job()
    async def _t(ac, db):
        r = await ac.post(f"/api/jobs/{jid}/arrive",
                            json=_arrive_body(source="teleport"))
        assert r.status_code == 400
        assert r.json()["detail"]["error"] == "invalid_source"
        assert set(r.json()["detail"]["allowed"]) == {
            "geofence", "manual", "route_start",
        }
    _run_as("admin", _t)


def test_source_empty_string_rejected():
    jid = _seed_job()
    async def _t(ac, db):
        r = await ac.post(f"/api/jobs/{jid}/arrive",
                            json=_arrive_body(source=""))
        assert r.status_code == 400
    _run_as("admin", _t)
