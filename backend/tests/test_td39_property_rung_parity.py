"""TD-39 · Feb-2026 — Property-rung parity in the shared coord resolver.

Pre-TD-39 the property rung only lived INLINE in
``routers/jobs.py::list_jobs``; both ``routers/schedule.py`` (GET
``/api/schedule/today``) and ``routers/dispatch_board.py`` (jobs_fallback
branch) bypassed the property rung entirely by calling the 3-rung
``resolve_job_coordinates(job, cust_map)`` directly, so a tenant whose
properties were geocoded but whose customer billing addresses were NOT
would drop pins on the schedule map + dispatch board that ``/api/jobs``
plotted correctly.

TD-39 lifts the inline rung into ``services/geo_resolver.py`` as
``resolve_job_coordinates_with_property(job, cust_map, prop_map)`` and
re-wires all three endpoints — ``schedule.py``, ``dispatch_board.py``,
and ``jobs.py`` (which drops its inline block for the shared helper).

This suite is a pure-function test against the resolver module. It
does NOT exercise the HTTP wire — the three endpoint integration tests
(``test_jobs_map_coord_ladder.py``, ``test_p26_map_endpoints_return_fallback.py``)
cover that surface. Keeping the TD-39 contract pinned at the resolver
layer lets a future refactor (e.g. collapsing all three endpoints
through a shared serializer) rely on the resolver's enum + rung order
staying stable.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

import pytest
from dotenv import dotenv_values
from motor.motor_asyncio import AsyncIOMotorClient

from services.geo_resolver import (
    COORD_SOURCE_CUSTOMER,
    COORD_SOURCE_JOB,
    COORD_SOURCE_PROPERTY,
    build_property_coord_lookup,
    resolve_job_coordinates_with_property,
)

_BE = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
MONGO_URL = _BE.get("MONGO_URL") or os.environ.get("MONGO_URL")
DB_NAME = _BE.get("DB_NAME") or os.environ.get("DB_NAME")

_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)
_MC = AsyncIOMotorClient(MONGO_URL, io_loop=_LOOP)
_DB = _MC[DB_NAME]

PFX = "TESTtd39_"


def _run(coro):
    asyncio.set_event_loop(_LOOP)
    return _LOOP.run_until_complete(coro)


async def _wipe():
    await _DB.properties.delete_many({"id": {"$regex": f"^{PFX}"}})


@pytest.fixture(autouse=True)
def _clean():
    _run(_wipe())
    yield
    _run(_wipe())


# ─── Resolver 4-rung ladder — pure-function assertions ────────────────


def _job(**kw: Any) -> Dict[str, Any]:
    """Build a minimal job dict with sensible defaults — fields are
    additive so tests can toggle just the rung they care about."""
    base: Dict[str, Any] = {
        "id": "j1",
        "tenant_id": "tenant_A",
        "customer_id": None,
        "property_id": None,
    }
    base.update(kw)
    return base


def test_rung1_job_coords_win_over_property_and_customer():
    """Job's own ``latitude`` / ``longitude`` win regardless of what
    the property or customer lookups carry."""
    job = _job(
        latitude=4.0, longitude=4.0,
        property_id="p1", customer_id="c1",
    )
    prop_map = {"p1": {"id": "p1", "latitude": 3.0, "longitude": 3.0}}
    cust_map = {"c1": {"id": "c1", "service_lat": 1.0, "service_lng": 1.0}}
    lat, lng, source = resolve_job_coordinates_with_property(
        job, cust_map, prop_map,
    )
    assert (lat, lng) == (4.0, 4.0)
    assert source == COORD_SOURCE_JOB


def test_rung2_property_wins_when_job_has_no_coords():
    """Property.latitude/longitude wins over customer when the job
    has no own coords. **The TD-39 regression guard** — pre-fix,
    schedule.py + dispatch_board.py would skip this rung and the
    resolver would land on ``"customer"`` here."""
    job = _job(property_id="p1", customer_id="c1")
    prop_map = {"p1": {"id": "p1", "latitude": 3.0, "longitude": 3.0}}
    cust_map = {"c1": {"id": "c1", "service_lat": 1.0, "service_lng": 1.0}}
    lat, lng, source = resolve_job_coordinates_with_property(
        job, cust_map, prop_map,
    )
    assert (lat, lng) == (3.0, 3.0)
    assert source == COORD_SOURCE_PROPERTY


def test_rung2_property_dual_shape_lat_lng_fallback():
    """Property with the flat ``lat`` / ``lng`` shape (legacy write
    path) still resolves — matches ``jobs.py``'s pre-TD-39 inline
    rung behavior where ``latitude`` ?? ``lat`` was consulted."""
    job = _job(property_id="p1", customer_id="c1")
    prop_map = {"p1": {"id": "p1", "lat": 5.5, "lng": 6.5}}
    cust_map = {"c1": {"id": "c1", "service_lat": 1.0, "service_lng": 1.0}}
    lat, lng, source = resolve_job_coordinates_with_property(
        job, cust_map, prop_map,
    )
    assert (lat, lng) == (5.5, 6.5)
    assert source == COORD_SOURCE_PROPERTY


def test_rung3_customer_wins_when_property_has_no_coords():
    """Property is present in the lookup but ungeocoded → fall
    through to customer (same as the pre-TD-39 behavior on jobs.py's
    inline rung — a null-coord property is treated as a miss, not a
    hit)."""
    job = _job(property_id="p1", customer_id="c1")
    # Property exists but lat/lng are None.
    prop_map = {"p1": {"id": "p1", "latitude": None, "longitude": None}}
    cust_map = {"c1": {"id": "c1", "service_lat": 1.0, "service_lng": 1.0}}
    lat, lng, source = resolve_job_coordinates_with_property(
        job, cust_map, prop_map,
    )
    assert (lat, lng) == (1.0, 1.0)
    assert source == COORD_SOURCE_CUSTOMER


def test_rung3_customer_wins_when_property_not_in_lookup():
    """Dangling ``property_id`` (property deleted or cross-tenant
    leak the caller filtered out) → fall through to customer.
    Matches ``jobs.py``'s pre-TD-39 ``p = pmap.get(pid)`` guard."""
    job = _job(property_id="p_dangling", customer_id="c1")
    prop_map = {}  # Empty — simulates cross-tenant filter / deleted FK.
    cust_map = {"c1": {"id": "c1", "service_lat": 1.0, "service_lng": 1.0}}
    lat, lng, source = resolve_job_coordinates_with_property(
        job, cust_map, prop_map,
    )
    assert (lat, lng) == (1.0, 1.0)
    assert source == COORD_SOURCE_CUSTOMER


def test_rung4_null_when_all_rungs_miss():
    """No rung resolves → ``(None, None, None)``. Caller stamps the
    pin as not-geocoded and drops it from the map layer."""
    job = _job(property_id="p1", customer_id="c1")
    prop_map = {"p1": {"id": "p1"}}  # No lat/lng at all.
    cust_map = {"c1": {"id": "c1"}}  # No service_lat/lng.
    lat, lng, source = resolve_job_coordinates_with_property(
        job, cust_map, prop_map,
    )
    assert (lat, lng, source) == (None, None, None)


def test_zero_coord_property_falls_through_to_customer():
    """Phase A.5 (0, 0) filter MUST still apply through the property
    rung — a legacy under-specified property geocoded to the Gulf-
    of-Guinea must NOT pin the job at (0, 0). Falls to customer."""
    job = _job(property_id="p_zero", customer_id="c1")
    prop_map = {"p_zero": {"id": "p_zero", "latitude": 0.0, "longitude": 0.0}}
    cust_map = {"c1": {"id": "c1", "service_lat": 1.0, "service_lng": 1.0}}
    lat, lng, source = resolve_job_coordinates_with_property(
        job, cust_map, prop_map,
    )
    assert (lat, lng) == (1.0, 1.0)
    assert source == COORD_SOURCE_CUSTOMER


def test_zero_coord_property_falls_through_to_null_when_no_customer():
    """(0, 0) property + no customer rung → ``(None, None, None)``.
    Pin DROPS instead of landing on the Gulf-of-Guinea landmark."""
    job = _job(property_id="p_zero", customer_id="c_missing")
    prop_map = {"p_zero": {"id": "p_zero", "latitude": 0.0, "longitude": 0.0}}
    cust_map = {}
    lat, lng, source = resolve_job_coordinates_with_property(
        job, cust_map, prop_map,
    )
    assert (lat, lng, source) == (None, None, None)


def test_job_without_property_id_still_resolves_customer_rung():
    """A job that never had a ``property_id`` (common for legacy
    tenants pre-MP1) must still land on the customer rung — the
    property lookup is a NO-OP for that job."""
    job = _job(customer_id="c1")  # No property_id.
    prop_map = {"p_ignored": {"id": "p_ignored", "latitude": 9.9, "longitude": 9.9}}
    cust_map = {"c1": {"id": "c1", "service_lat": 1.0, "service_lng": 1.0}}
    lat, lng, source = resolve_job_coordinates_with_property(
        job, cust_map, prop_map,
    )
    assert (lat, lng) == (1.0, 1.0)
    assert source == COORD_SOURCE_CUSTOMER


# ─── build_property_coord_lookup — cross-tenant isolation guard ───────


def test_build_property_coord_lookup_filters_by_tenant():
    """The property batch helper MUST filter by ``tenant_id`` — a
    caller passing a stale/attacker-controlled tenant_id must not
    receive another tenant's property coords. Mirrors the identical
    contract on ``build_customer_coord_lookup``."""
    async def _seed_and_fetch():
        prop_a = {
            "id": f"{PFX}prop_A", "tenant_id": "tenant_A",
            "latitude": 10.0, "longitude": 20.0,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        prop_b = {
            "id": f"{PFX}prop_B", "tenant_id": "tenant_B",
            "latitude": 30.0, "longitude": 40.0,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        await _DB.properties.insert_many([prop_a, prop_b])
        # Caller holds tenant_A context; attacker-crafted request body
        # supplies both IDs. Only tenant_A's property comes back.
        return await build_property_coord_lookup(
            _DB, "tenant_A", [prop_a["id"], prop_b["id"]],
        )

    lookup = _run(_seed_and_fetch())
    assert f"{PFX}prop_A" in lookup
    assert f"{PFX}prop_B" not in lookup
    assert lookup[f"{PFX}prop_A"]["latitude"] == 10.0
    assert lookup[f"{PFX}prop_A"]["longitude"] == 20.0


def test_build_property_coord_lookup_empty_input_short_circuits():
    """Empty / falsy ``property_ids`` → no DB round trip, empty dict."""
    out = _run(build_property_coord_lookup(_DB, "tenant_A", []))
    assert out == {}
    out = _run(build_property_coord_lookup(_DB, "tenant_A", None))
    assert out == {}
    # Falsy entries (None, empty string) are filtered too.
    out = _run(build_property_coord_lookup(
        _DB, "tenant_A", [None, "", None],
    ))
    assert out == {}


def test_build_property_coord_lookup_dedupes_repeated_ids():
    """N jobs sharing a property only cost one ``$in`` slot. Lookup
    is keyed by id so a repeated input still produces one entry."""
    async def _seed_and_fetch():
        prop = {
            "id": f"{PFX}prop_shared", "tenant_id": "tenant_A",
            "latitude": 7.0, "longitude": 8.0,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        await _DB.properties.insert_one(prop)
        return await build_property_coord_lookup(
            _DB, "tenant_A",
            # Simulate 5 jobs on 2 properties where 4 share the same id.
            [prop["id"], prop["id"], prop["id"], prop["id"], f"{PFX}prop_missing"],
        )

    lookup = _run(_seed_and_fetch())
    assert len(lookup) == 1
    assert f"{PFX}prop_shared" in lookup
