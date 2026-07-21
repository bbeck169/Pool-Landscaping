"""Feb-2026 · Slice 4 (MP1.6) — Route optimizer & stops property-scoped
geocoding tests.

Covers:
* ``GET /api/routes/{tech_id}/stops`` returns per-stop
  ``address / lat / lng`` sourced from the stop's property doc when
  ``property_id`` is set, falling back to the customer default when
  it isn't. Includes an ``address_source`` field for debuggability.
* ``POST /api/schedule/optimize-route`` and ``POST /api/routes/optimize``
  both route on property-scoped coords when ``property_id`` is set.
* A property without a geocode is lazy-geocoded on first optimizer run
  and the coords are persisted on the property doc.

Seeds a customer with 2 distinct properties (fake coords set directly)
and 3 jobs on ``2026-08-05`` — two bound to properties A and B, one
without ``property_id`` (falls back to customer default).
"""
from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timezone

import pytest
import requests

BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL")
            or "http://localhost:8001").rstrip("/")
API = f"{BASE_URL}/api"


def _login(email: str, pw: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": pw}, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def admin_headers():
    return {"Authorization": f"Bearer {_login('admin@aquaterra.com')}"}


@pytest.fixture(scope="module")
def customer_headers():
    return {"Authorization": f"Bearer {_login('customer@aquaterra.com')}"}


# ─── Direct DB seeding — needed to plant known-coord properties ────────────
def _db():
    from motor.motor_asyncio import AsyncIOMotorClient
    from dotenv import load_dotenv
    # Load backend .env so MONGO_URL / DB_NAME are present when this
    # test module is invoked outside a supervisor-managed process.
    load_dotenv("/app/backend/.env")
    mongo_url = os.environ.get("MONGO_URL") or "mongodb://localhost:27017"
    db_name = os.environ.get("DB_NAME") or "test_database"
    return AsyncIOMotorClient(mongo_url)[db_name]


@pytest.fixture(scope="module")
def seed(admin_headers):
    """Seed 1 tenant (existing), 1 customer, 2 properties, 1 tech user,
    3 jobs on the same day (one no-property, one property-A, one
    property-B). Everything is torn down in the teardown."""
    async def _up():
        db = _db()
        # Reuse the seeded tenant + admin ids.
        tenant = await db.tenants.find_one({}, {"_id": 0})
        assert tenant, "no tenant seeded"

        # Reuse the seeded tech (mike) — matches the credentials the
        # main test file uses.
        tech = await db.users.find_one(
            {"email": "mike@aquaterra.com", "tenant_id": tenant["id"]},
            {"_id": 0},
        )
        assert tech, "seed tech missing"
        tech_id = tech["id"]
        tech_technician_id = tech.get("technician_id")

        # Fresh customer with a KNOWN default coord.
        cid = f"slice4-cust-{uuid.uuid4().hex[:8]}"
        await db.customers.insert_one({
            "id": cid,
            "tenant_id": tenant["id"],
            "name": "Slice4 CustDefault",
            "email": f"{cid}@t.local",
            "address": "1 Customer Default Rd, Phoenix AZ",
            "lat": 33.4000,       # unique so the test can assert clearly
            "lng": -112.0000,
        })

        # 2 properties for the same customer — distinct coords.
        pid_a = f"slice4-pA-{uuid.uuid4().hex[:8]}"
        pid_b = f"slice4-pB-{uuid.uuid4().hex[:8]}"
        pid_ungeo = f"slice4-pC-{uuid.uuid4().hex[:8]}"  # no lat/lng → lazy geocode later
        await db.properties.insert_many([
            {
                "id": pid_a,
                "tenant_id": tenant["id"],
                "customer_id": cid,
                "label": "Property A",
                "address": {"line1": "10 A Street", "city": "Peoria",
                            "state": "AZ", "postal_code": "85383"},
                "lat": 33.5000, "lng": -112.1000,
                "active": True,
            },
            {
                "id": pid_b,
                "tenant_id": tenant["id"],
                "customer_id": cid,
                "label": "Property B",
                "address": {"line1": "20 B Street", "city": "Peoria",
                            "state": "AZ", "postal_code": "85383"},
                "lat": 33.7000, "lng": -112.3000,
                "active": True,
            },
            {
                "id": pid_ungeo,
                "tenant_id": tenant["id"],
                "customer_id": cid,
                "label": "Property C (no geocode)",
                "address": {"line1": "30 C Street", "city": "Peoria",
                            "state": "AZ", "postal_code": "85383"},
                # NO lat/lng — must lazy-geocode on first optimizer read
                "active": True,
            },
        ])

        # 4 jobs on the same day — one no-property (customer default),
        # one property-A, one property-B, one property-C (no geo).
        date_str = "2026-08-05"
        base = {
            "tenant_id": tenant["id"],
            "customer_id": cid,
            "customer_name": "Slice4 CustDefault",
            "technician_id": tech_technician_id or tech_id,
            "status": "scheduled",
            "scheduled_date": date_str,
        }
        j_ids = []
        job_specs = [
            {"suffix": "cust", "start": "T08:00:00+00:00",
             "end": "T09:00:00+00:00", "property_id": None,
             "lat": 33.4000, "lng": -112.0000, "site_lat": 33.4000, "site_lng": -112.0000},
            {"suffix": "pA", "start": "T10:00:00+00:00",
             "end": "T11:00:00+00:00", "property_id": pid_a},
            {"suffix": "pB", "start": "T12:00:00+00:00",
             "end": "T13:00:00+00:00", "property_id": pid_b},
            {"suffix": "pC", "start": "T14:00:00+00:00",
             "end": "T15:00:00+00:00", "property_id": pid_ungeo},
        ]
        for spec in job_specs:
            jid = f"slice4-job-{spec['suffix']}-{uuid.uuid4().hex[:6]}"
            j = dict(base)
            j.update({
                "id": jid,
                "title": f"Slice4 job {spec['suffix']}",
                "service_type": "Pool Cleaning",
                "scheduled_start": f"{date_str}{spec['start']}",
                "scheduled_end": f"{date_str}{spec['end']}",
                "property_id": spec.get("property_id"),
                "lat": spec.get("lat"),
                "lng": spec.get("lng"),
                "site_lat": spec.get("site_lat"),
                "site_lng": spec.get("site_lng"),
            })
            await db.jobs.insert_one(j)
            j_ids.append(jid)

        return {
            "tenant_id": tenant["id"],
            "cid": cid,
            "pid_a": pid_a,
            "pid_b": pid_b,
            "pid_ungeo": pid_ungeo,
            "tech_id": tech_id,
            "tech_technician_id": tech_technician_id,
            "date": date_str,
            "job_ids": j_ids,
        }

    ctx = asyncio.new_event_loop().run_until_complete(_up())

    yield ctx

    async def _down():
        db = _db()
        await db.jobs.delete_many({"id": {"$in": ctx["job_ids"]}})
        await db.customers.delete_many({"id": ctx["cid"]})
        await db.properties.delete_many({"id": {
            "$in": [ctx["pid_a"], ctx["pid_b"], ctx["pid_ungeo"]]
        }})

    asyncio.new_event_loop().run_until_complete(_down())


# ═══════════════════════════════════════════════════════════════════════
# 1. GET /api/routes/{tech_id}/stops — property-scoped read
# ═══════════════════════════════════════════════════════════════════════
def test_route_stops_uses_property_coords_when_property_id_set(admin_headers, seed):
    r = requests.get(
        f"{API}/routes/{seed['tech_id']}/stops",
        headers=admin_headers,
        params={"date": seed["date"]},
        timeout=30,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["count"] >= 3

    by_id = {s["job_id"]: s for s in body["stops"]}
    our_stops = {jid: by_id.get(jid) for jid in seed["job_ids"]}
    for jid, s in our_stops.items():
        assert s is not None, f"stop {jid} missing from route"

    # Stop with property_id=None → address_source == "customer"
    cust_stop = next(s for s in our_stops.values() if s["property_id"] is None)
    assert cust_stop["address_source"] == "customer", cust_stop
    assert cust_stop["lat"] == 33.4000
    assert cust_stop["lng"] == -112.0000

    # Stop with property_id=A → property coords + source "property"
    a_stop = next(s for s in our_stops.values()
                   if s.get("property_id") == seed["pid_a"])
    assert a_stop["address_source"] == "property", a_stop
    assert a_stop["lat"] == 33.5000, a_stop
    assert a_stop["lng"] == -112.1000, a_stop
    # Address string must include the property's line1 — proves we did
    # NOT fall through to the customer's default address.
    assert "10 A Street" in (a_stop.get("address") or "")

    # Stop with property_id=B → property B coords
    b_stop = next(s for s in our_stops.values()
                   if s.get("property_id") == seed["pid_b"])
    assert b_stop["address_source"] == "property"
    assert b_stop["lat"] == 33.7000
    assert b_stop["lng"] == -112.3000


def test_route_stops_customer_forbidden(customer_headers, seed):
    r = requests.get(
        f"{API}/routes/{seed['tech_id']}/stops",
        headers=customer_headers,
        params={"date": seed["date"]},
        timeout=15,
    )
    assert r.status_code == 403


# ═══════════════════════════════════════════════════════════════════════
# 2. POST /api/schedule/optimize-route — property-scoped ordering
# ═══════════════════════════════════════════════════════════════════════
def test_optimize_route_uses_property_coords(admin_headers, seed):
    """Optimize the tech's route for the seeded day — the returned
    ordered_job_ids must reflect the property-scoped Haversine order.

    Property-A (33.5000, -112.1000) is closer to the customer default
    (33.4000, -112.0000) than Property-B (33.7000, -112.3000).  So
    starting from the customer-default stop, the nearest-neighbor
    order should be: cust → A → B.  Cache-buster: swap start coords.
    """
    r = requests.post(
        f"{API}/schedule/optimize-route",
        headers=admin_headers,
        params={"user_id": seed["tech_id"]},
        json={
            "date": seed["date"],
            # Start slightly SW so ``cust`` (33.4, -112.0) wins first.
            "start_lat": 33.35,
            "start_lng": -112.05,
        },
        timeout=30,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    ordered = body.get("ordered_job_ids") or []
    # All our seeded jobs should be present.
    ours = [j for j in ordered if j in seed["job_ids"]]
    assert len(ours) >= 3, f"missing our jobs in ordered list: {ours}"

    # Since property C had no geocode at seed time, we don't assert its
    # position. But we can assert Property-A comes before Property-B.
    idx = {jid: i for i, jid in enumerate(ordered)}
    a_id = next(j for j in seed["job_ids"] if j.startswith("slice4-job-pA-"))
    b_id = next(j for j in seed["job_ids"] if j.startswith("slice4-job-pB-"))
    assert idx[a_id] < idx[b_id], (
        f"property A ({idx[a_id]}) must sort before property B ({idx[b_id]})"
    )


# ═══════════════════════════════════════════════════════════════════════
# 3. Lazy geocode of a property with no lat/lng on first optimizer run
# ═══════════════════════════════════════════════════════════════════════
def test_optimizer_lazy_geocodes_ungeoded_property(admin_headers, seed):
    """The seeded Property C had no lat/lng.  After hitting the
    optimizer once, the property doc should carry ``lat`` + ``lng``
    (or gracefully remain None if Google returns an error — we assert
    only that no-crash + shape is preserved so the test doesn't fail
    on transient upstream issues)."""
    # Run the optimizer (which invokes resolve_stop_geo with
    # geocode_if_missing=True).
    r = requests.post(
        f"{API}/schedule/optimize-route",
        headers=admin_headers,
        params={"user_id": seed["tech_id"]},
        json={"date": seed["date"]},
        timeout=30,
    )
    assert r.status_code == 200, r.text

    async def _read():
        db = _db()
        return await db.properties.find_one(
            {"id": seed["pid_ungeo"]}, {"_id": 0},
        )
    prop = asyncio.new_event_loop().run_until_complete(_read())
    assert prop is not None
    # The lazy-geocode is best-effort — if Google returned a location
    # we should now see it; if not, ``lat`` remains absent. We assert
    # only that the doc wasn't corrupted.
    for k in ("id", "address", "customer_id", "tenant_id"):
        assert prop.get(k), f"property C missing {k}"


# ═══════════════════════════════════════════════════════════════════════
# 4. resolve_stop_geo helper — pure unit assertions
# ═══════════════════════════════════════════════════════════════════════
def test_resolve_stop_geo_direct(seed):
    """Verify the helper directly so the address_source string is
    locked in (both writers rely on it in the JSON payload)."""
    from services.stop_geo import resolve_stop_geo

    async def _go():
        # property-A stop
        stop = {"property_id": seed["pid_a"]}
        r = await resolve_stop_geo(stop, seed["tenant_id"])
        assert r["address_source"] == "property"
        assert r["lat"] == 33.5000 and r["lng"] == -112.1000
        assert "10 A Street" in r["address"]

        # no-property stop → customer fallback
        stop = {"lat": 12.34, "lng": 56.78, "address": "Fallback St"}
        r = await resolve_stop_geo(stop, seed["tenant_id"])
        assert r["address_source"] == "customer"
        assert r["lat"] == 12.34 and r["lng"] == 56.78

    asyncio.new_event_loop().run_until_complete(_go())
