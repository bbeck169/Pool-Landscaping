"""FLEET-A · POST /api/fleet/ping ingestion tests."""
from __future__ import annotations

import importlib
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from backend.tests._fleet_helpers import _DB, run


@pytest.fixture
def fake_db(monkeypatch):
    fake = _DB()
    # In-fleet member seed.
    fake.fleet_membership.rows = [
        {"id": "m1", "tenant_id": "t1", "tech_user_id": "u-tech",
         "in_fleet": True},
    ]
    for mod_name in ["routers.fleet"]:
        mod = importlib.import_module(mod_name)
        monkeypatch.setattr(mod, "db", fake, raising=False)
    # Reset the in-memory rate limiter between tests.
    from services.fleet import rate_limit
    rate_limit.reset()
    return fake


def _ping_body(**overrides):
    from routers.fleet import PingBody
    payload = {
        "lat": 33.7897, "lng": -112.3226,
        "accuracy_m": 5.0, "battery_pct": 82.5,
    }
    payload.update(overrides)
    return PingBody(**payload)


def _tech_user(uid="u-tech"):
    return {"id": uid, "role": "technician", "email": "t@x", "tenant_id": "t1"}


def test_in_fleet_tech_ping_succeeds(fake_db):
    from routers import fleet
    res = run(fleet.post_ping(
        body=_ping_body(),
        user=_tech_user(),
        tenant={"id": "t1"},
    ))
    assert res["ok"] is True
    assert len(fake_db.tech_locations.rows) == 1
    doc = fake_db.tech_locations.rows[0]
    assert doc["source"] == "gps"
    assert doc["tenant_id"] == "t1"
    assert doc["tech_user_id"] == "u-tech"
    assert doc["lat"] == 33.7897


def test_out_of_fleet_tech_ping_returns_403(fake_db):
    from routers import fleet
    fake_db.fleet_membership.rows = []          # nobody in the fleet
    with pytest.raises(HTTPException) as exc:
        run(fleet.post_ping(
            body=_ping_body(),
            user=_tech_user(),
            tenant={"id": "t1"},
        ))
    assert exc.value.status_code == 403
    assert exc.value.detail["error_code"] == "not_in_fleet"


def test_non_tech_role_forbidden(fake_db):
    from routers import fleet
    with pytest.raises(HTTPException) as exc:
        run(fleet.post_ping(
            body=_ping_body(),
            user={"id": "u", "role": "admin", "email": "a@x",
                  "tenant_id": "t1"},
            tenant={"id": "t1"},
        ))
    assert exc.value.status_code == 403
    assert exc.value.detail["error_code"] == "not_a_technician"


def test_rate_limit_second_ping_within_5s_returns_429(fake_db):
    from routers import fleet
    run(fleet.post_ping(
        body=_ping_body(), user=_tech_user(), tenant={"id": "t1"},
    ))
    with pytest.raises(HTTPException) as exc:
        run(fleet.post_ping(
            body=_ping_body(), user=_tech_user(), tenant={"id": "t1"},
        ))
    assert exc.value.status_code == 429
    assert exc.value.detail["error_code"] == "rate_limited"
    # Only the first ping should have persisted.
    assert len(fake_db.tech_locations.rows) == 1


def test_stale_device_time_rejected(fake_db):
    from routers import fleet
    old = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    with pytest.raises(HTTPException) as exc:
        run(fleet.post_ping(
            body=_ping_body(device_time=old.replace("+00:00", "Z")),
            user=_tech_user(),
            tenant={"id": "t1"},
        ))
    assert exc.value.status_code == 400
    assert exc.value.detail["error_code"] == "stale_ping"
    assert not fake_db.tech_locations.rows


def test_fresh_device_time_accepted(fake_db):
    from routers import fleet
    now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    res = run(fleet.post_ping(
        body=_ping_body(device_time=now_iso),
        user=_tech_user(),
        tenant={"id": "t1"},
    ))
    assert res["ok"] is True


def test_ping_writes_expected_fields(fake_db):
    from routers import fleet
    run(fleet.post_ping(
        body=_ping_body(
            speed_kmh=42.5, heading_deg=180.0, job_id="job-99",
        ),
        user=_tech_user(),
        tenant={"id": "t1"},
    ))
    doc = fake_db.tech_locations.rows[0]
    assert doc["speed_kmh"] == 42.5
    assert doc["heading_deg"] == 180.0
    assert doc["job_id"] == "job-99"
    assert doc["battery_pct"] == 82.5


def test_tenant_scoped_isolation(fake_db):
    """A ping for tenant t1 must NOT be visible when reading with
    tenant t2 context. We simulate this by adding a tenant-A ping
    then reading via the breadcrumbs endpoint scoped to tenant B."""
    from routers import fleet
    fake_db.fleet_membership.rows.append({
        "id": "m2", "tenant_id": "t2", "tech_user_id": "u-tech",
        "in_fleet": True,
    })
    run(fleet.post_ping(
        body=_ping_body(), user=_tech_user(), tenant={"id": "t1"},
    ))
    from services.fleet import rate_limit; rate_limit.reset()

    res = run(fleet.get_breadcrumbs(
        tech_user_id="u-tech", since=None, until=None,
        job_id=None, limit=100,
        user={"id": "u", "role": "admin", "email": "a@x"},
        tenant={"id": "t2"},                                  # ← cross-tenant
    ))
    assert res["count"] == 0                                  # no leak
