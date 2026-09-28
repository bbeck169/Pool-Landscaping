"""FLEET-A · POST /api/fleet/checkin — manual on-the-way / arrived tests.

Coverage
--------
  * ``kind="on_the_way"``  → invokes the notification pipeline and
    persists a ``manual_on_the_way`` tech_location row.
  * ``kind="arrived"``    → patches ``job.actual_start_time`` when
    unset, never overwrites, and does NOT fire notifications.
  * Cross-tenant job lookup → 404 ``job_not_found``.
  * Non-tech role → 403 ``not_a_technician``.
  * Out-of-fleet tech → 403 ``not_in_fleet``.
  * The notification pipeline mock is invoked with the exact
    tenant/tech/job triple + tech coordinates.

Uses the same in-memory Motor stub (``_DB``) as
``test_fleet_ping_ingestion.py`` to stay isolated from live Mongo.
"""
from __future__ import annotations

import importlib

import pytest
from fastapi import HTTPException

from backend.tests._fleet_helpers import _DB, run


@pytest.fixture
def fake_db(monkeypatch):
    fake = _DB()
    fake.fleet_membership.rows = [
        {"id": "m1", "tenant_id": "t1", "tech_user_id": "u-tech",
         "in_fleet": True},
    ]
    fake.jobs.rows = [
        {"id": "job-1", "tenant_id": "t1", "customer_id": "cust-1",
         "title": "Weekly svc",
         "latitude": 33.6, "longitude": -112.4},
        {"id": "job-2", "tenant_id": "t1", "customer_id": "cust-1",
         "title": "Started already",
         "actual_start_time": "2026-02-01T00:00:00Z",
         "latitude": 33.7, "longitude": -112.3},
    ]
    fake.customers.rows = [
        {"id": "cust-1", "tenant_id": "t1", "name": "Jane Homeowner",
         "email": "jane@example.com", "email_opt_in": True,
         "phone": "+16025551234", "sms_opt_in": False},
    ]
    fake.tenants.rows = [
        {"id": "t1", "name": "AquaTerra"},
    ]
    fake.users.rows = [
        {"id": "u-tech", "tenant_id": "t1", "name": "Tom Tech",
         "role": "technician"},
    ]
    for mod_name in ["routers.fleet"]:
        mod = importlib.import_module(mod_name)
        monkeypatch.setattr(mod, "db", fake, raising=False)
    # Reset the in-memory rate limiter between tests (checkin does
    # not consume it but ping tests share the module).
    from services.fleet import rate_limit
    rate_limit.reset()
    return fake


def _tech_user(uid="u-tech"):
    return {"id": uid, "role": "technician", "email": "t@x", "tenant_id": "t1"}


def _checkin_body(**overrides):
    from routers.fleet import CheckinBody
    payload = {"kind": "on_the_way", "job_id": "job-1",
               "lat": 33.7897, "lng": -112.3226}
    payload.update(overrides)
    return CheckinBody(**payload)


# ─── on_the_way ─────────────────────────────────────────────────────

def test_on_the_way_fires_notification_pipeline(fake_db, monkeypatch):
    from routers import fleet

    called = {}

    async def _stub(*, tenant_id, tech_user_id, job_id,
                     tech_lat, tech_lng):
        called["args"] = dict(
            tenant_id=tenant_id, tech_user_id=tech_user_id,
            job_id=job_id, tech_lat=tech_lat, tech_lng=tech_lng,
        )
        from services.fleet.notifications import NotifyOutcome
        return NotifyOutcome(
            sent=True, reason="sent", eta_minutes=6,
            provider="crowflies",
            channels={"email": {"status": "sent"},
                      "sms": {"status": "skipped_opt_out_or_missing"}},
        )

    monkeypatch.setattr(fleet, "maybe_send_on_the_way", _stub,
                        raising=True)

    res = run(fleet.post_checkin(
        body=_checkin_body(),
        user=_tech_user(),
        tenant={"id": "t1"},
    ))
    assert res["ok"] is True
    assert res["kind"] == "on_the_way"
    assert res["notification"]["sent"] is True
    assert res["notification"]["eta_minutes"] == 6
    assert res["notification"]["provider"] == "crowflies"
    # tech_locations row persisted with the manual source tag.
    assert len(fake_db.tech_locations.rows) == 1
    row = fake_db.tech_locations.rows[0]
    assert row["source"] == "manual_on_the_way"
    assert row["tech_user_id"] == "u-tech"
    assert row["tenant_id"] == "t1"
    # Notification args echoed the request.
    assert called["args"]["tenant_id"] == "t1"
    assert called["args"]["tech_user_id"] == "u-tech"
    assert called["args"]["job_id"] == "job-1"
    assert called["args"]["tech_lat"] == 33.7897
    assert called["args"]["tech_lng"] == -112.3226


def test_on_the_way_when_notification_skips_far_eta(fake_db, monkeypatch):
    from routers import fleet
    from services.fleet.notifications import NotifyOutcome

    async def _stub(**kwargs):
        return NotifyOutcome(
            sent=False, reason="eta_too_far", eta_minutes=42,
            provider="crowflies",
        )

    monkeypatch.setattr(fleet, "maybe_send_on_the_way", _stub,
                        raising=True)
    res = run(fleet.post_checkin(
        body=_checkin_body(),
        user=_tech_user(),
        tenant={"id": "t1"},
    ))
    assert res["notification"]["sent"] is False
    assert res["notification"]["reason"] == "eta_too_far"
    assert res["notification"]["eta_minutes"] == 42


# ─── arrived ────────────────────────────────────────────────────────

def test_arrived_sets_actual_start_time_when_unset(fake_db, monkeypatch):
    from routers import fleet

    calls = {"count": 0}

    async def _stub(**kwargs):
        calls["count"] += 1
        from services.fleet.notifications import NotifyOutcome
        return NotifyOutcome(sent=True, reason="sent")

    monkeypatch.setattr(fleet, "maybe_send_on_the_way", _stub,
                        raising=True)
    res = run(fleet.post_checkin(
        body=_checkin_body(kind="arrived", job_id="job-1"),
        user=_tech_user(),
        tenant={"id": "t1"},
    ))
    assert res["ok"] is True
    assert res["kind"] == "arrived"
    assert res["actual_start_time_patched"] is True
    # Notification NOT invoked on arrived.
    assert calls["count"] == 0
    # Job now carries actual_start_time.
    job = next(j for j in fake_db.jobs.rows if j["id"] == "job-1")
    assert job.get("actual_start_time")


def test_arrived_never_overwrites_existing_start(fake_db):
    from routers import fleet
    res = run(fleet.post_checkin(
        body=_checkin_body(kind="arrived", job_id="job-2"),
        user=_tech_user(),
        tenant={"id": "t1"},
    ))
    assert res["actual_start_time_patched"] is False
    # Original start time still there.
    job = next(j for j in fake_db.jobs.rows if j["id"] == "job-2")
    assert job["actual_start_time"] == "2026-02-01T00:00:00Z"


def test_arrived_persists_tech_location_row(fake_db):
    from routers import fleet
    run(fleet.post_checkin(
        body=_checkin_body(kind="arrived", job_id="job-1"),
        user=_tech_user(),
        tenant={"id": "t1"},
    ))
    row = fake_db.tech_locations.rows[0]
    assert row["source"] == "manual_arrived"


# ─── error paths ────────────────────────────────────────────────────

def test_non_tech_role_forbidden(fake_db):
    from routers import fleet
    with pytest.raises(HTTPException) as exc:
        run(fleet.post_checkin(
            body=_checkin_body(),
            user={"id": "u", "role": "admin", "email": "a@x",
                  "tenant_id": "t1"},
            tenant={"id": "t1"},
        ))
    assert exc.value.status_code == 403
    assert exc.value.detail["error_code"] == "not_a_technician"


def test_out_of_fleet_forbidden(fake_db):
    from routers import fleet
    fake_db.fleet_membership.rows = []
    with pytest.raises(HTTPException) as exc:
        run(fleet.post_checkin(
            body=_checkin_body(),
            user=_tech_user(),
            tenant={"id": "t1"},
        ))
    assert exc.value.status_code == 403
    assert exc.value.detail["error_code"] == "not_in_fleet"


def test_cross_tenant_job_returns_404(fake_db):
    from routers import fleet
    # Job exists in tenant t1 but the checkin is fired under t2.
    fake_db.fleet_membership.rows.append({
        "id": "m2", "tenant_id": "t2", "tech_user_id": "u-tech",
        "in_fleet": True,
    })
    with pytest.raises(HTTPException) as exc:
        run(fleet.post_checkin(
            body=_checkin_body(),                                # job-1
            user=_tech_user(),
            tenant={"id": "t2"},                                 # ← wrong tenant
        ))
    assert exc.value.status_code == 404
    assert exc.value.detail["error_code"] == "job_not_found"


def test_missing_job_returns_404(fake_db):
    from routers import fleet
    with pytest.raises(HTTPException) as exc:
        run(fleet.post_checkin(
            body=_checkin_body(job_id="no-such-job"),
            user=_tech_user(),
            tenant={"id": "t1"},
        ))
    assert exc.value.status_code == 404
