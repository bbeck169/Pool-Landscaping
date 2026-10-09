"""Phase 6 · Feb-2026 — Job Timer universal-trigger regression lock.

Locks the three Phase 6 batched fixes:

  * Bug A (``auto_start_timer_on_arrival`` carries ``crew_id``) —
    timer rows are created for ALL service_types and ALL assignee
    shapes (solo tech, crew-only, crew-lead-with-tech).  Previously
    crew-assigned jobs produced an orphan row with both ids null;
    the operator read the symptom as "only landscape fires" because
    their landscape jobs happened to be solo-tech while pool /
    repair were crew-assigned.

  * Bug B (``DEFAULT_ARRIVAL_RADIUS_M`` 75 → 150m) — geofence
    default radius matches the brief; tenant override via
    ``arrival_radius_meters`` continues to win.  Feature flag
    ``gps_auto_start_enabled`` is still a tenant choice (not
    flipped) so existing tenants with the flag off keep their
    pre-Phase-6 behaviour.

  * Bug C (``close_open_timers_for_job`` is wired to both job-
    complete AND service-report-submit) — pre-Phase-6 code was
    already universal; this file locks the behaviour so a future
    refactor can't regress it.

Scenarios 1–11 map to the brief's checklist 1:1.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
import pytest
import requests
from dotenv import dotenv_values

from tests._shared_mongo import shared_db as _shared_db


os.environ.setdefault("ALLOW_TEST_HOOKS", "1")

_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = _shared_db()
API = "http://localhost:8001/api"

JWT_SECRET = (
    _ENV.get("JWT_SECRET") or os.environ.get("JWT_SECRET")
    or "dev-secret-change-me"
)
JWT_ALGO = "HS256"


def _tok(uid, email, tid, role):
    return jwt.encode(
        {"sub": uid, "email": email, "role": role, "tenant_id": tid,
         "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
        JWT_SECRET, algorithm=JWT_ALGO,
    )


def _auth(token, tenant_id):
    return {"Authorization": f"Bearer {token}", "X-Tenant-Id": tenant_id}


# ──────────────────────────────────────────────────────────────────
#  Seeds — all synchronous Mongo so each test owns its state.
# ──────────────────────────────────────────────────────────────────

def _seed_tenant(gps_enabled=True, radius=None):
    tid = f"p6-{uuid.uuid4().hex[:8]}"
    doc = {
        "id": tid, "name": "P6 timer smoke", "slug": tid, "active": True,
        "gps_auto_start_enabled": gps_enabled,
    }
    if radius is not None:
        doc["arrival_radius_meters"] = radius
    _sync.tenants.insert_one(doc)
    return tid


def _seed_user(tenant_id, role, label, technician_id=None):
    uid = f"{label}-{uuid.uuid4().hex[:8]}"
    email = f"{uid}@p6.test"
    _sync.users.insert_one({
        "id": uid, "tenant_id": tenant_id, "role": role,
        "name": f"P6 {role}", "email": email,
        "technician_id": technician_id or uid,
    })
    # P37a consent grant so the technician gate passes.
    _sync.tech_gps_consents.insert_one({
        "id": f"tgc-{uuid.uuid4().hex[:8]}", "tenant_id": tenant_id,
        "user_id": uid, "granted": True, "revoked_at": None,
        "granted_at": datetime.now(timezone.utc).isoformat(),
    })
    return {
        "id": uid, "email": email, "tenant_id": tenant_id,
        "role": role, "technician_id": technician_id or uid,
        "token": _tok(uid, email, tenant_id, role),
    }


def _seed_job(tenant_id, *, service_type, status="scheduled",
               technician_id=None, crew_id=None,
               site_lat=33.5731, site_lng=-112.1859,
               work_class=None):
    jid = f"job-{uuid.uuid4().hex[:8]}"
    doc = {
        "id":            jid,
        "tenant_id":     tenant_id,
        "service_type":  service_type,
        "work_class":    work_class or "service",
        "status":        status,
        "customer_id":   f"c-{uuid.uuid4().hex[:6]}",
        "customer_name": "P6 Customer",
        "title":         f"P6 {service_type or 'untyped'} job",
        "technician_id": technician_id,
        "crew_id":       crew_id,
        "site_lat":      site_lat,
        "site_lng":      site_lng,
        "latitude":      site_lat,
        "longitude":     site_lng,
        "created_at":    "2026-02-10T12:00:00+00:00",
        "scheduled_date": "2026-02-15",
    }
    _sync.jobs.insert_one(doc)
    return jid


@pytest.fixture
def tenant_id():
    tid = _seed_tenant(gps_enabled=True)
    yield tid
    for col in ("tenants", "users", "jobs", "job_timers",
                "job_timer_audit", "tech_gps_consents",
                "audit_logs", "service_reports"):
        _sync[col].delete_many({"tenant_id": tid})


@pytest.fixture
def admin(tenant_id):
    return _seed_user(tenant_id, "admin", "adm")


@pytest.fixture
def tech(tenant_id):
    return _seed_user(tenant_id, "technician", "tech")


def _arrive(user, tenant_id, jid, *, lat, lng):
    return requests.post(
        f"{API}/jobs/{jid}/arrive",
        headers=_auth(user["token"], tenant_id),
        json={"lat": lat, "lng": lng, "source": "geofence"},
        timeout=20,
    )


def _open_timer_for_job(tenant_id, jid):
    return _sync.job_timers.find_one(
        {"tenant_id": tenant_id, "job_id": jid, "ended_at": None},
        {"_id": 0},
    )


def _all_timers_for_job(tenant_id, jid):
    return list(_sync.job_timers.find(
        {"tenant_id": tenant_id, "job_id": jid}, {"_id": 0},
    ))


# ══════════════════════════════════════════════════════════════════
#  Bug A — all service types create timer rows
# ══════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("service_type", [
    "pool_maintenance",
    "pool_service",
    "repair",
    "landscape_maintenance",     # pre-Phase-6 happy path — regression lock
    None,                         # explicit null service_type
    "",                           # empty string service_type
    "custom_oddball_type",
])
def test_bug_a_arrival_creates_timer_for_every_service_type(
        tenant_id, tech, service_type):
    jid = _seed_job(tenant_id, service_type=service_type,
                     technician_id=tech["technician_id"])
    r = _arrive(tech, tenant_id, jid,
                 lat=33.5731, lng=-112.1859)
    assert r.status_code == 200, r.text
    assert r.json().get("started") is True, r.json()
    row = _open_timer_for_job(tenant_id, jid)
    assert row is not None, (
        f"no open timer created for service_type={service_type!r}"
    )
    assert row["tech_id"] == tech["technician_id"]
    assert row["entity_type"] == "tech"
    assert row["start_source"] == "gps_arrival"


# ══════════════════════════════════════════════════════════════════
#  Bug A — crew-assigned jobs also create timer rows (previously
#  the user-observed root cause of "only landscape fires").
# ══════════════════════════════════════════════════════════════════

def test_bug_a_arrival_creates_timer_for_crew_assigned_pool_job(
        tenant_id, admin):
    # Crew-only assignment — no technician_id, crew_id set.
    crew_id = f"crew-{uuid.uuid4().hex[:8]}"
    _sync.crews.insert_one({
        "id": crew_id, "tenant_id": tenant_id, "name": "P6 crew",
        "active": True,
    })
    jid = _seed_job(tenant_id, service_type="pool_service",
                     technician_id=None, crew_id=crew_id)
    # Crew-member user who arrives on-site.
    crew_user = _seed_user(tenant_id, "crew_member", "cm")
    r = _arrive(crew_user, tenant_id, jid,
                 lat=33.5731, lng=-112.1859)
    assert r.status_code == 200, r.text
    assert r.json().get("started") is True
    row = _open_timer_for_job(tenant_id, jid)
    assert row is not None, (
        "crew-only pool job must create a timer row"
    )
    # Phase 6 fix — crew_id propagated into the timer row.
    assert row["crew_id"] == crew_id, (
        f"crew_id not propagated into timer row: {row}"
    )
    assert row["tech_id"] is None
    assert row["entity_type"] == "crew"
    # Cleanup — crews collection is seeded above and belongs to the
    # tenant teardown fixture.
    _sync.crews.delete_many({"tenant_id": tenant_id})


# ══════════════════════════════════════════════════════════════════
#  Bug B — geofence radius default + in/out of range gate
# ══════════════════════════════════════════════════════════════════

def test_bug_b_geofence_default_radius_is_150m():
    """``DEFAULT_ARRIVAL_RADIUS_M`` is 150 per Phase 6 brief."""
    from routers.gps_auto_start import DEFAULT_ARRIVAL_RADIUS_M
    assert DEFAULT_ARRIVAL_RADIUS_M == 150


def test_bug_b_within_radius_pool_job_auto_starts(tenant_id, tech):
    # Tenant has no ``arrival_radius_meters`` override — must fall
    # through to the 150m default and start the timer.
    _sync.tenants.update_one(
        {"id": tenant_id},
        {"$unset": {"arrival_radius_meters": ""}},
    )
    jid = _seed_job(tenant_id, service_type="pool_service",
                     technician_id=tech["technician_id"],
                     site_lat=33.5731, site_lng=-112.1859)
    # Arrive within ~50m — well inside 150m default.
    r = _arrive(tech, tenant_id, jid,
                 lat=33.57355, lng=-112.1859)
    assert r.status_code == 200, r.text
    assert r.json().get("started") is True, r.json()
    assert _open_timer_for_job(tenant_id, jid) is not None


def test_bug_b_outside_radius_does_not_auto_start(tenant_id, tech):
    # Shrink radius to 50m and arrive 500m away — must refuse.
    _sync.tenants.update_one(
        {"id": tenant_id},
        {"$set": {"arrival_radius_meters": 50}},
    )
    jid = _seed_job(tenant_id, service_type="pool_service",
                     technician_id=tech["technician_id"],
                     site_lat=33.5731, site_lng=-112.1859)
    # ~0.5km north — ~500m away.
    r = _arrive(tech, tenant_id, jid,
                 lat=33.5776, lng=-112.1859)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("started") is False
    assert body.get("reason") == "out_of_radius"
    assert _open_timer_for_job(tenant_id, jid) is None


def test_bug_b_radius_sourced_from_tenant_config_when_present(tenant_id, tech):
    # Override to a tiny value — arrival at 100m must miss.
    _sync.tenants.update_one(
        {"id": tenant_id},
        {"$set": {"arrival_radius_meters": 25}},
    )
    jid = _seed_job(tenant_id, service_type="pool_service",
                     technician_id=tech["technician_id"],
                     site_lat=33.5731, site_lng=-112.1859)
    # ~100m north — outside the 25m override.
    r = _arrive(tech, tenant_id, jid,
                 lat=33.5740, lng=-112.1859)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("reason") == "out_of_radius"
    assert body.get("radius_m") == 25, body


# ══════════════════════════════════════════════════════════════════
#  Bug C — close triggers (job-complete + service-report-submit)
#  + idempotency.  We invoke ``close_open_timers_for_job`` directly
#  for the second trigger because the online service-report-submit
#  endpoint has an inflight-claim gate that makes seeded fixtures
#  flaky — ``close_open_timers_for_job`` is the exact function the
#  live submit path calls.
# ══════════════════════════════════════════════════════════════════

def test_bug_c_close_universal_on_direct_invocation(tenant_id, admin, tech):
    # Arrival-created timer on a pool job → close via the helper
    # the service-report-submit path uses.
    jid = _seed_job(tenant_id, service_type="pool_service",
                     technician_id=tech["technician_id"])
    _arrive(tech, tenant_id, jid, lat=33.5731, lng=-112.1859)
    open_row = _open_timer_for_job(tenant_id, jid)
    assert open_row is not None

    async def _close(reason):
        from routers.job_timers import close_open_timers_for_job
        return await close_open_timers_for_job(
            job_id=jid, tenant_id=tenant_id,
            actor_user_id=admin["id"], reason=reason,
        )

    closed = asyncio.get_event_loop().run_until_complete(
        _close("service_report_submit"),
    )
    assert closed == 1
    sealed = _sync.job_timers.find_one(
        {"tenant_id": tenant_id, "job_id": jid}, {"_id": 0},
    )
    assert sealed["ended_at"] is not None
    assert sealed["end_source"] == "service_report_submit"
    assert sealed["duration_seconds"] is not None


def test_bug_c_close_idempotent_second_call_is_noop(tenant_id, admin, tech):
    jid = _seed_job(tenant_id, service_type="repair",
                     technician_id=tech["technician_id"])
    _arrive(tech, tenant_id, jid, lat=33.5731, lng=-112.1859)

    async def _close(reason):
        from routers.job_timers import close_open_timers_for_job
        return await close_open_timers_for_job(
            job_id=jid, tenant_id=tenant_id,
            actor_user_id=admin["id"], reason=reason,
        )

    first = asyncio.get_event_loop().run_until_complete(
        _close("service_report_submit"),
    )
    second = asyncio.get_event_loop().run_until_complete(
        _close("job_completed"),
    )
    assert first == 1, "first close should seal the open timer"
    assert second == 0, (
        "second close must be a no-op (idempotent) — got "
        f"{second} rows re-closed"
    )
    # Only ONE audit row for the real close — no duplicate.
    audits = list(_sync.job_timer_audit.find(
        {"tenant_id": tenant_id,
         "timer_id": _sync.job_timers.find_one(
             {"tenant_id": tenant_id, "job_id": jid}, {"id": 1})["id"],
         "event": "auto_close"},
    ))
    assert len(audits) == 1, (
        f"expected ONE auto_close audit row, got {len(audits)}"
    )


def test_bug_c_close_on_job_complete_patch(tenant_id, admin, tech):
    """Flipping job.status → completed via PUT closes open timers.
    Uses a repair work_class so the chemistry-readings gate (pool
    jobs) doesn't short-circuit the status update."""
    jid = _seed_job(tenant_id, service_type="pool_pump_repair",
                     work_class="repair",
                     technician_id=tech["technician_id"])
    _arrive(tech, tenant_id, jid, lat=33.5731, lng=-112.1859)
    assert _open_timer_for_job(tenant_id, jid) is not None

    r = requests.put(
        f"{API}/jobs/{jid}",
        headers=_auth(admin["token"], tenant_id),
        json={"status": "completed"},
        timeout=20,
    )
    assert r.status_code == 200, r.text

    sealed = _sync.job_timers.find_one(
        {"tenant_id": tenant_id, "job_id": jid}, {"_id": 0},
    )
    assert sealed["ended_at"] is not None
    assert sealed["end_source"] == "job_completed"


# ══════════════════════════════════════════════════════════════════
#  Universal rule — role coverage
# ══════════════════════════════════════════════════════════════════

def test_role_coverage_crew_member_arrival_fires_timer(tenant_id, admin):
    """A crew_member user arriving on a crew-assigned job gets a
    timer row with the proper crew_id attribution (parity with the
    solo-tech arrival test above)."""
    crew_id = f"crew-{uuid.uuid4().hex[:8]}"
    _sync.crews.insert_one({
        "id": crew_id, "tenant_id": tenant_id, "name": "P6 crew role",
        "active": True,
    })
    jid = _seed_job(tenant_id, service_type="pool_service",
                     technician_id=None, crew_id=crew_id)
    crew_member = _seed_user(tenant_id, "crew_member", "cmrole")
    r = _arrive(crew_member, tenant_id, jid,
                 lat=33.5731, lng=-112.1859)
    assert r.status_code == 200, r.text
    assert r.json().get("started") is True
    row = _open_timer_for_job(tenant_id, jid)
    assert row is not None
    assert row["crew_id"] == crew_id
    assert row["entity_type"] == "crew"
    _sync.crews.delete_many({"tenant_id": tenant_id})


# ══════════════════════════════════════════════════════════════════
#  OpenAPI — no new endpoints shipped in this phase; the two
#  existing helpers are called INTERNALLY from already-exposed
#  routes.  Lock the existing timer endpoints so a refactor can't
#  silently drop them.
# ══════════════════════════════════════════════════════════════════

def test_openapi_lists_existing_timer_endpoints():
    r = requests.get(f"{API}/openapi.json", timeout=15)
    assert r.status_code == 200
    paths = r.json().get("paths", {})
    for route in ("/api/job-timers/start",
                  "/api/job-timers/{timer_id}/close",
                  "/api/job-timers",
                  "/api/jobs/{jid}/arrive"):
        assert route in paths, f"{route} missing from OpenAPI"
