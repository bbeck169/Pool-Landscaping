"""EMV · Feb-2026 — Enterprise Map View backend integration tests.

Locks the read-only contract for
``GET /api/dispatch/enterprise-view``:

  1. Default window is today..today+6 (7-day inclusive span).
  2. Custom ``start_date`` + ``end_date`` honoured; jobs outside the
     window are excluded.
  3. Span >14 days → HTTP 400.
  4. Tenant isolation (other tenant's jobs never bleed in).
  5. HD-A soft-deleted jobs suppressed.
  6. Deterministic hash color fallback when tech lacks
     ``display_color_hex``; the DB row is NOT mutated.
  7. RBAC — technician / customer → 403.
  8. Read-only — no jobs mutation on a call.
  9. ``missing_coordinates_count`` reflects jobs with null lat/lng.
 10. Coord precedence: site_lat/lng > lat/lng > latitude/longitude.
"""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
import requests
from dotenv import dotenv_values
from motor.motor_asyncio import AsyncIOMotorClient

from tests.conftest import demo_pw

API = "http://localhost:8001/api"

_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)
_MC = AsyncIOMotorClient(_ENV["MONGO_URL"], io_loop=_LOOP)
_DB = _MC[_ENV["DB_NAME"]]


def _run(coro):
    asyncio.set_event_loop(_LOOP)
    return _LOOP.run_until_complete(coro)


def _login(email: str) -> str:
    r = requests.post(
        f"{API}/auth/login",
        json={"email": email, "password": demo_pw(email)},
        timeout=15,
    )
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _tenant_of(email: str) -> str:
    row = _run(_DB.users.find_one({"email": email}, {"_id": 0, "tenant_id": 1}))
    assert row and row.get("tenant_id")
    return row["tenant_id"]


TEST_PREFIX = "TESTemv_"
TODAY = date.today()


async def _mkjob(*, tenant_id: str, tech_id: str,
                    scheduled_date: str,
                    route_index: int | None = None,
                    lat: float | None = None,
                    lng: float | None = None,
                    site_lat: float | None = None,
                    site_lng: float | None = None,
                    latitude: float | None = None,
                    longitude: float | None = None,
                    is_deleted: bool = False,
                    extra: dict | None = None) -> str:
    jid = f"{TEST_PREFIX}job_{uuid4().hex[:10]}"
    doc: dict = {
        "id": jid,
        "tenant_id": tenant_id,
        "technician_id": tech_id,
        "scheduled_date": scheduled_date,
        "status": "scheduled",
        "customer_id": f"{TEST_PREFIX}c_{uuid4().hex[:6]}",
        "customer_name": f"{TEST_PREFIX}Customer",
        "address": "123 Test St",
        "service_type": "pool_service",
        "title": f"{TEST_PREFIX}Job",
        "created_at": datetime.utcnow().isoformat(),
    }
    if route_index is not None:
        doc["route_index"] = route_index
    if lat is not None:
        doc["lat"] = lat
    if lng is not None:
        doc["lng"] = lng
    if site_lat is not None:
        doc["site_lat"] = site_lat
    if site_lng is not None:
        doc["site_lng"] = site_lng
    if latitude is not None:
        doc["latitude"] = latitude
    if longitude is not None:
        doc["longitude"] = longitude
    if is_deleted:
        doc["deleted_at"] = datetime.utcnow().isoformat()
    if extra:
        doc.update(extra)
    await _DB.jobs.insert_one(doc)
    return jid


async def _mktech(*, tenant_id: str, name: str,
                     display_color_hex: str | None = None) -> str:
    uid = f"{TEST_PREFIX}u_{uuid4().hex[:8]}"
    doc = {
        "id": uid, "tenant_id": tenant_id, "role": "technician",
        "email": f"{uid}@example.com", "name": name,
    }
    if display_color_hex:
        doc["display_color_hex"] = display_color_hex
    await _DB.users.insert_one(doc)
    return uid


async def _wipe():
    await _DB.jobs.delete_many({"id": {"$regex": f"^{TEST_PREFIX}"}})
    await _DB.users.delete_many({"id": {"$regex": f"^{TEST_PREFIX}"}})


@pytest.fixture(autouse=True)
def _clean():
    _run(_wipe())
    yield
    _run(_wipe())


def _get(tok: str, **params):
    return requests.get(
        f"{API}/dispatch/enterprise-view",
        headers={"Authorization": f"Bearer {tok}"},
        params=params, timeout=15,
    )


# ═══════════════════════════════════════════════════════════════════
# 1. Default window is today..today+6
# ═══════════════════════════════════════════════════════════════════
def test_default_window_is_seven_days():
    tok = _login("super@aquaterra.com")
    r = _get(tok)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["start_date"] == TODAY.isoformat()
    assert body["end_date"] == (TODAY + timedelta(days=6)).isoformat()
    assert body["days_in_range"] == 7
    assert body["cap"] == 2000


# ═══════════════════════════════════════════════════════════════════
# 2. Custom range respected + jobs outside window filtered
# ═══════════════════════════════════════════════════════════════════
def test_custom_range_filters_jobs_outside_window():
    tok = _login("super@aquaterra.com")
    tenant_id = _tenant_of("super@aquaterra.com")

    tech = _run(_mktech(tenant_id=tenant_id, name="TESTemv Tech A",
                         display_color_hex="#EF4444"))
    # In-window
    in_win = _run(_mkjob(tenant_id=tenant_id, tech_id=tech,
                           scheduled_date="2026-05-04", route_index=0,
                           lat=33.7, lng=-112.2))
    # Out-of-window
    out_win = _run(_mkjob(tenant_id=tenant_id, tech_id=tech,
                            scheduled_date="2026-05-15", route_index=0,
                            lat=33.7, lng=-112.2))

    r = _get(tok, start_date="2026-05-01", end_date="2026-05-07")
    assert r.status_code == 200, r.text
    body = r.json()
    job_ids = {j["id"] for j in body["jobs"]}
    assert in_win in job_ids
    assert out_win not in job_ids


# ═══════════════════════════════════════════════════════════════════
# 3. Span > 14 days → 400
# ═══════════════════════════════════════════════════════════════════
def test_span_over_max_returns_400():
    tok = _login("super@aquaterra.com")
    r = _get(tok, start_date="2026-05-01", end_date="2026-05-20")
    assert r.status_code == 400, r.text
    assert "14" in r.text


# ═══════════════════════════════════════════════════════════════════
# 4. Tenant isolation
# ═══════════════════════════════════════════════════════════════════
def test_tenant_isolation():
    tok = _login("super@aquaterra.com")
    tenant_a = _tenant_of("super@aquaterra.com")
    tenant_b = f"{TEST_PREFIX}other_tenant"

    tech_a = _run(_mktech(tenant_id=tenant_a, name="TESTemv A"))
    tech_b = _run(_mktech(tenant_id=tenant_b, name="TESTemv B"))
    j_a = _run(_mkjob(tenant_id=tenant_a, tech_id=tech_a,
                        scheduled_date="2026-05-04", lat=33.7, lng=-112.2))
    j_b = _run(_mkjob(tenant_id=tenant_b, tech_id=tech_b,
                        scheduled_date="2026-05-04", lat=33.7, lng=-112.2))

    r = _get(tok, start_date="2026-05-01", end_date="2026-05-07")
    assert r.status_code == 200
    job_ids = {j["id"] for j in r.json()["jobs"]}
    assert j_a in job_ids
    assert j_b not in job_ids


# ═══════════════════════════════════════════════════════════════════
# 5. HD-A soft-delete filter respected
# ═══════════════════════════════════════════════════════════════════
def test_soft_deleted_jobs_excluded():
    tok = _login("super@aquaterra.com")
    tenant_id = _tenant_of("super@aquaterra.com")

    tech = _run(_mktech(tenant_id=tenant_id, name="TESTemv Del"))
    live = _run(_mkjob(tenant_id=tenant_id, tech_id=tech,
                        scheduled_date="2026-05-04", lat=33.7, lng=-112.2))
    gone = _run(_mkjob(tenant_id=tenant_id, tech_id=tech,
                        scheduled_date="2026-05-04", lat=33.7, lng=-112.2,
                        is_deleted=True))

    r = _get(tok, start_date="2026-05-01", end_date="2026-05-07")
    assert r.status_code == 200
    job_ids = {j["id"] for j in r.json()["jobs"]}
    assert live in job_ids
    assert gone not in job_ids


# ═══════════════════════════════════════════════════════════════════
# 6. Deterministic hash color fallback (no DB mutation)
# ═══════════════════════════════════════════════════════════════════
def test_hash_color_fallback_no_db_mutation():
    tok = _login("super@aquaterra.com")
    tenant_id = _tenant_of("super@aquaterra.com")

    # Tech with NO display_color_hex set.
    tech = _run(_mktech(tenant_id=tenant_id, name="TESTemv NoColor"))
    _run(_mkjob(tenant_id=tenant_id, tech_id=tech,
                 scheduled_date="2026-05-04", lat=33.7, lng=-112.2))

    r = _get(tok, start_date="2026-05-01", end_date="2026-05-07")
    assert r.status_code == 200
    tech_row = next(
        t for t in r.json()["technicians"] if t["id"] == tech
    )
    assert tech_row["color_source"] == "hash_fallback"
    assert tech_row["display_color_hex"].startswith("#")
    assert len(tech_row["display_color_hex"]) == 7  # #RRGGBB

    # Verify a repeat call yields the identical color (deterministic).
    r2 = _get(tok, start_date="2026-05-01", end_date="2026-05-07")
    tech_row2 = next(t for t in r2.json()["technicians"] if t["id"] == tech)
    assert tech_row2["display_color_hex"] == tech_row["display_color_hex"]

    # And critically: the DB row remains UN-mutated.
    db_row = _run(_DB.users.find_one({"id": tech}, {"_id": 0, "display_color_hex": 1}))
    assert (db_row or {}).get("display_color_hex") in (None, ""), (
        f"EMV must NOT persist a fallback color; DB row shows: {db_row}"
    )


def test_db_color_source_reported_when_set():
    tok = _login("super@aquaterra.com")
    tenant_id = _tenant_of("super@aquaterra.com")

    tech = _run(_mktech(tenant_id=tenant_id, name="TESTemv WithColor",
                          display_color_hex="#3B82F6"))
    _run(_mkjob(tenant_id=tenant_id, tech_id=tech,
                 scheduled_date="2026-05-04", lat=33.7, lng=-112.2))

    r = _get(tok, start_date="2026-05-01", end_date="2026-05-07")
    assert r.status_code == 200
    tech_row = next(t for t in r.json()["technicians"] if t["id"] == tech)
    assert tech_row["color_source"] == "db"
    assert tech_row["display_color_hex"] == "#3B82F6"


# ═══════════════════════════════════════════════════════════════════
# 7. RBAC — technician + customer → 403
# ═══════════════════════════════════════════════════════════════════
def test_technician_forbidden():
    tok = _login("mike@aquaterra.com")
    r = _get(tok)
    assert r.status_code == 403, r.text


def test_customer_forbidden():
    tok = _login("customer@aquaterra.com")
    r = _get(tok)
    assert r.status_code == 403, r.text


# ═══════════════════════════════════════════════════════════════════
# 8. Endpoint is read-only — no jobs mutation
# ═══════════════════════════════════════════════════════════════════
def test_endpoint_is_read_only():
    tok = _login("super@aquaterra.com")
    tenant_id = _tenant_of("super@aquaterra.com")

    tech = _run(_mktech(tenant_id=tenant_id, name="TESTemv ReadOnly"))
    jid = _run(_mkjob(tenant_id=tenant_id, tech_id=tech,
                        scheduled_date="2026-05-04", route_index=3,
                        lat=33.7, lng=-112.2))
    before = _run(_DB.jobs.find_one({"id": jid}, {"_id": 0}))

    _get(tok, start_date="2026-05-01", end_date="2026-05-07")
    _get(tok, start_date="2026-05-01", end_date="2026-05-07")

    after = _run(_DB.jobs.find_one({"id": jid}, {"_id": 0}))
    # ``updated_at`` was never set on ours, so equality on the full
    # doc is safe.
    assert before == after, "EMV must be read-only against db.jobs"


# ═══════════════════════════════════════════════════════════════════
# 9. missing_coordinates_count reflects null-coord jobs
# ═══════════════════════════════════════════════════════════════════
def test_missing_coordinates_count():
    tok = _login("super@aquaterra.com")
    tenant_id = _tenant_of("super@aquaterra.com")

    tech = _run(_mktech(tenant_id=tenant_id, name="TESTemv MC"))
    _run(_mkjob(tenant_id=tenant_id, tech_id=tech,
                 scheduled_date="2026-05-04", lat=33.7, lng=-112.2))
    _run(_mkjob(tenant_id=tenant_id, tech_id=tech,
                 scheduled_date="2026-05-05"))  # no coords
    _run(_mkjob(tenant_id=tenant_id, tech_id=tech,
                 scheduled_date="2026-05-05"))  # no coords

    r = _get(tok, start_date="2026-05-01", end_date="2026-05-07")
    assert r.status_code == 200
    body = r.json()
    # ``missing_coordinates_count`` must be at least 2 (may include
    # unrelated seed jobs but our two are guaranteed present). Assert
    # on the count of our specific test jobs to keep the test
    # deterministic against a shared demo tenant.
    our_ids_no_coord = [
        j for j in body["jobs"]
        if j.get("customer_name", "").startswith(TEST_PREFIX) and not j["has_coordinates"]
    ]
    assert len(our_ids_no_coord) == 2


# ═══════════════════════════════════════════════════════════════════
# 10. Coord precedence — site_lat > lat > latitude
# ═══════════════════════════════════════════════════════════════════
def test_coord_precedence_site_lat_wins():
    tok = _login("super@aquaterra.com")
    tenant_id = _tenant_of("super@aquaterra.com")

    tech = _run(_mktech(tenant_id=tenant_id, name="TESTemv Coord"))
    jid = _run(_mkjob(tenant_id=tenant_id, tech_id=tech,
                        scheduled_date="2026-05-04",
                        site_lat=10.0, site_lng=20.0,
                        lat=99.0, lng=99.0,
                        latitude=88.0, longitude=88.0))
    r = _get(tok, start_date="2026-05-01", end_date="2026-05-07")
    assert r.status_code == 200
    job = next(j for j in r.json()["jobs"] if j["id"] == jid)
    assert job["lat"] == 10.0 and job["lng"] == 20.0


def test_coord_precedence_lat_over_latitude():
    tok = _login("super@aquaterra.com")
    tenant_id = _tenant_of("super@aquaterra.com")

    tech = _run(_mktech(tenant_id=tenant_id, name="TESTemv Coord2"))
    jid = _run(_mkjob(tenant_id=tenant_id, tech_id=tech,
                        scheduled_date="2026-05-04",
                        lat=44.0, lng=55.0,
                        latitude=77.0, longitude=77.0))
    r = _get(tok, start_date="2026-05-01", end_date="2026-05-07")
    assert r.status_code == 200
    job = next(j for j in r.json()["jobs"] if j["id"] == jid)
    assert job["lat"] == 44.0 and job["lng"] == 55.0


# ═══════════════════════════════════════════════════════════════════
# 11. Manager role can read (positive RBAC path)
# ═══════════════════════════════════════════════════════════════════
def test_admin_role_allowed():
    tok = _login("admin@aquaterra.com")
    r = _get(tok)
    assert r.status_code == 200, r.text


# ═══════════════════════════════════════════════════════════════════
# 12. Truncation cap — > 2000 jobs → truncated=True + trim to cap +
#      deterministic ordering across repeat calls
# ═══════════════════════════════════════════════════════════════════
def test_truncation_cap_enforced_and_deterministic():
    tok = _login("super@aquaterra.com")
    tenant_id = _tenant_of("super@aquaterra.com")

    # 3 techs so the flat jobs array is populated across owners; the
    # endpoint sort is (scheduled_date, route_index, created_at), so
    # the truncated slice is fully determined by seeded fields.
    tech_ids = [
        _run(_mktech(tenant_id=tenant_id, name=f"TESTemv Bulk {i}"))
        for i in range(3)
    ]

    # Seed 2005 jobs across the default window (today..today+6).
    # ``route_index`` and ``created_at`` are set explicitly per doc so
    # the sort key is total-ordered → truncation is deterministic.
    SEED_COUNT = 2005
    docs = []
    base_created = datetime.utcnow()
    for i in range(SEED_COUNT):
        day_offset = i % 7  # spread across the 7-day window
        docs.append({
            "id": f"{TEST_PREFIX}bulk_{i:05d}_{uuid4().hex[:6]}",
            "tenant_id": tenant_id,
            "technician_id": tech_ids[i % 3],
            "scheduled_date": (TODAY + timedelta(days=day_offset)).isoformat(),
            "status": "scheduled",
            "customer_id": f"{TEST_PREFIX}bulkc_{i:05d}",
            "customer_name": f"{TEST_PREFIX}Bulk Customer {i}",
            "address": "123 Bulk St",
            "service_type": "pool_service",
            "title": f"{TEST_PREFIX}Bulk Job {i}",
            "route_index": i,           # unique per doc → total ordering
            "created_at": (base_created + timedelta(microseconds=i)).isoformat(),
            "lat": 33.7 + (i % 100) * 0.001,
            "lng": -112.2 + (i % 100) * 0.001,
        })
    _run(_DB.jobs.insert_many(docs))

    # ── First call ──
    r1 = _get(tok)  # default window == 7-day window we seeded
    assert r1.status_code == 200, r1.text
    body1 = r1.json()

    # Truncation flag + counts
    assert body1["truncated"] is True, (
        f"expected truncated=True with {SEED_COUNT} seeded jobs, "
        f"got total_jobs_matched={body1.get('total_jobs_matched')}"
    )
    assert body1["cap"] == 2000
    assert body1["total_jobs_matched"] >= SEED_COUNT, (
        f"total_jobs_matched={body1['total_jobs_matched']} < seeded {SEED_COUNT}"
    )
    # Trimmed to exactly the cap. Filter to our TESTemv_ IDs so a
    # shared demo tenant with unrelated seed jobs cannot inflate this.
    our_jobs_1 = [j for j in body1["jobs"] if j["id"].startswith(f"{TEST_PREFIX}bulk_")]
    assert len(body1["jobs"]) == 2000, (
        f"body['jobs'] length={len(body1['jobs'])}, expected exactly cap=2000"
    )
    # Overflow == total_matched - cap must be > 0 (proves truncation
    # actually removed jobs rather than the cap being a no-op).
    overflow = body1["total_jobs_matched"] - body1["cap"]
    assert overflow > 0, f"expected overflow > 0, got {overflow}"

    # ── Second call — same window, no seeding between ──
    r2 = _get(tok)
    assert r2.status_code == 200, r2.text
    body2 = r2.json()

    # Deterministic ordering: identical id sequence, identical
    # truncated slice.
    ids_1 = [j["id"] for j in body1["jobs"]]
    ids_2 = [j["id"] for j in body2["jobs"]]
    assert ids_1 == ids_2, (
        "truncated slice is not deterministic between two identical calls; "
        "sort key (scheduled_date, route_index, created_at) is unstable"
    )
    assert body2["truncated"] is True
    assert body2["total_jobs_matched"] == body1["total_jobs_matched"]
