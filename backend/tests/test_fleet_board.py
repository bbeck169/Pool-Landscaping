"""FLEET-A · GET /api/fleet/board tests.

The board aggregates every in-fleet tech + their latest location +
their next scheduled job + a live ETA (via snapshot cache).

Coverage
--------
  * RBAC — admin / super_admin OK, technician forbidden.
  * Empty state — no in-fleet techs → ``{"count":0,"techs":[]}``.
  * Populated state — one in-fleet tech with a location + scheduled
    job returns a row with location, next-job, and ETA payload.
  * ``last_ping_age_s`` computed from ``recorded_at``.
  * ETA snapshot cache: fresh snapshot reused, stale one recomputed.
  * Cross-tenant isolation — techs from another tenant do not
    surface on the board.
  * In-progress job wins over a scheduled future job.
"""
from __future__ import annotations

import importlib
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from backend.tests._fleet_helpers import _DB, run


def _iso(dt):
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


@pytest.fixture
def fake_db(monkeypatch):
    fake = _DB()
    fake.fleet_membership.rows = [
        {"id": "m1", "tenant_id": "t1", "tech_user_id": "u-tech",
         "in_fleet": True},
    ]
    fake.users.rows = [
        {"id": "u-tech", "tenant_id": "t1", "name": "Tom Tech",
         "role": "technician"},
    ]
    now = datetime.now(timezone.utc)
    fake.tech_locations.rows = [
        {"id": "loc1", "tenant_id": "t1", "tech_user_id": "u-tech",
         "recorded_at": _iso(now - timedelta(seconds=30)),
         "lat": 33.7897, "lng": -112.3226, "battery_pct": 88.5},
    ]
    fake.jobs.rows = [
        {"id": "job-1", "tenant_id": "t1", "technician_id": "u-tech",
         "title": "Weekly svc", "customer_id": "cust-1",
         "customer_name": "Jane H.",
         "service_address": "123 Main",
         "latitude": 33.8, "longitude": -112.32,
         "status": "scheduled",
         "scheduled_start": _iso(now + timedelta(hours=1))},
    ]
    for mod_name in ["routers.fleet"]:
        mod = importlib.import_module(mod_name)
        monkeypatch.setattr(mod, "db", fake, raising=False)
    return fake


@pytest.fixture
def stub_compute_eta(monkeypatch):
    """Force ``compute_eta`` to a deterministic crow-flies value so
    the board tests don't depend on public OSRM demo availability."""
    from routers import fleet as router
    from services.fleet import eta

    async def _fake(lat1, lng1, lat2, lng2, **kw):
        return eta.ETAResult(
            provider="crowflies", distance_m=1234, duration_s=180,
        )

    monkeypatch.setattr(router, "compute_eta", _fake, raising=True)
    return _fake


# ─── RBAC ───────────────────────────────────────────────────────────

def test_board_forbidden_for_technician(fake_db):
    from routers import fleet
    with pytest.raises(HTTPException) as exc:
        run(fleet.get_board(
            user={"id": "u", "role": "technician", "email": "t@x"},
            tenant={"id": "t1"},
        ))
    assert exc.value.status_code == 403
    assert exc.value.detail["error_code"] == "forbidden"


def test_board_ok_for_admin(fake_db, stub_compute_eta):
    from routers import fleet
    res = run(fleet.get_board(
        user={"id": "u-admin", "role": "admin", "email": "a@x"},
        tenant={"id": "t1"},
    ))
    assert res["count"] == 1
    assert res["techs"][0]["tech_user_id"] == "u-tech"


def test_board_ok_for_super_admin(fake_db, stub_compute_eta):
    from routers import fleet
    res = run(fleet.get_board(
        user={"id": "u-super", "role": "super_admin", "email": "s@x"},
        tenant={"id": "t1"},
    ))
    assert res["count"] == 1


# ─── Payload shape ──────────────────────────────────────────────────

def test_board_empty_when_no_in_fleet(fake_db):
    from routers import fleet
    fake_db.fleet_membership.rows = []
    res = run(fleet.get_board(
        user={"id": "u", "role": "admin", "email": "a@x"},
        tenant={"id": "t1"},
    ))
    assert res == {"count": 0, "techs": []}


def test_board_returns_location_and_job(fake_db, stub_compute_eta):
    from routers import fleet
    res = run(fleet.get_board(
        user={"id": "u", "role": "admin", "email": "a@x"},
        tenant={"id": "t1"},
    ))
    row = res["techs"][0]
    assert row["location"]["lat"] == 33.7897
    assert row["battery_pct"] == 88.5
    assert row["last_ping_age_s"] is not None
    assert row["last_ping_age_s"] <= 120                        # ~30 s
    assert row["current_job"]["id"] == "job-1"
    assert row["current_job"]["customer_name"] == "Jane H."
    assert row["current_job"]["lat"] == 33.8
    assert row["eta"]["provider"] == "crowflies"
    assert row["eta"]["distance_m"] == 1234
    assert row["eta"]["duration_s"] == 180


def test_board_snapshot_cache_reused_when_fresh(fake_db,
                                                   monkeypatch):
    """Second call within stale-window should return the exact same
    snapshot; ``compute_eta`` must be invoked at most once."""
    from routers import fleet as router
    from services.fleet import eta

    call_count = {"n": 0}

    async def _stub(lat1, lng1, lat2, lng2, **kw):
        call_count["n"] += 1
        return eta.ETAResult(provider="crowflies",
                              distance_m=1000, duration_s=100)

    monkeypatch.setattr(router, "compute_eta", _stub, raising=True)

    run(router.get_board(
        user={"id": "u", "role": "admin", "email": "a@x"},
        tenant={"id": "t1"},
    ))
    run(router.get_board(
        user={"id": "u", "role": "admin", "email": "a@x"},
        tenant={"id": "t1"},
    ))
    assert call_count["n"] == 1
    # Snapshot persisted.
    assert len(fake_db.fleet_eta_snapshots.rows) == 1


def test_board_recomputes_when_snapshot_stale(fake_db, monkeypatch):
    from routers import fleet as router
    from services.fleet import eta

    call_count = {"n": 0}

    async def _stub(lat1, lng1, lat2, lng2, **kw):
        call_count["n"] += 1
        return eta.ETAResult(provider="crowflies",
                              distance_m=1000, duration_s=100)

    monkeypatch.setattr(router, "compute_eta", _stub, raising=True)

    # Prime an already-stale snapshot in the DB (stale_at in the past).
    past = datetime.now(timezone.utc) - timedelta(minutes=5)
    fake_db.fleet_eta_snapshots.rows = [{
        "id": "s-old", "tenant_id": "t1", "job_id": "job-1",
        "tech_user_id": "u-tech",
        "computed_at": _iso(past),
        "computed_at_dt": past,
        "stale_at_dt": past + timedelta(seconds=60),         # < now
        "provider": "google",
        "distance_m": 999, "duration_s": 111,
        "eta_arrival_at": _iso(past + timedelta(seconds=111)),
    }]
    res = run(router.get_board(
        user={"id": "u", "role": "admin", "email": "a@x"},
        tenant={"id": "t1"},
    ))
    assert call_count["n"] == 1
    # Fresh recompute wins over the stale snapshot.
    assert res["techs"][0]["eta"]["provider"] == "crowflies"
    assert res["techs"][0]["eta"]["distance_m"] == 1000


# ─── Isolation + variance ───────────────────────────────────────────

def test_board_cross_tenant_isolation(fake_db, stub_compute_eta):
    """Add an in-fleet tech in tenant t2 — MUST NOT show on the t1 board."""
    from routers import fleet
    fake_db.fleet_membership.rows.append({
        "id": "m2", "tenant_id": "t2", "tech_user_id": "u-other",
        "in_fleet": True,
    })
    res = run(fleet.get_board(
        user={"id": "u", "role": "admin", "email": "a@x"},
        tenant={"id": "t1"},
    ))
    ids = {t["tech_user_id"] for t in res["techs"]}
    assert ids == {"u-tech"}


def test_board_in_progress_job_wins_over_scheduled(fake_db,
                                                     stub_compute_eta):
    """When both an in-progress and a future-scheduled job exist for
    the tech, the current-job payload must be the in-progress one."""
    from routers import fleet
    now = datetime.now(timezone.utc)
    fake_db.jobs.rows.append({
        "id": "job-live", "tenant_id": "t1",
        "technician_id": "u-tech",
        "customer_name": "Live Job", "status": "in_progress",
        "latitude": 33.9, "longitude": -112.4,
        "scheduled_start": _iso(now - timedelta(hours=1)),
    })
    res = run(fleet.get_board(
        user={"id": "u", "role": "admin", "email": "a@x"},
        tenant={"id": "t1"},
    ))
    assert res["techs"][0]["current_job"]["id"] == "job-live"


def test_board_eta_omitted_when_job_lacks_coords(fake_db,
                                                   stub_compute_eta):
    from routers import fleet
    # Strip job coords — ETA must be None.
    fake_db.jobs.rows[0].pop("latitude", None)
    fake_db.jobs.rows[0].pop("longitude", None)
    res = run(fleet.get_board(
        user={"id": "u", "role": "admin", "email": "a@x"},
        tenant={"id": "t1"},
    ))
    row = res["techs"][0]
    assert row["current_job"]["id"] == "job-1"
    assert row["eta"] is None
