"""TD-40 · Feb-2026 — Geocode-on-save for property create + patch.

Pre-TD-40 ``POST /api/customers/{cid}/properties`` and
``PATCH /api/properties/{pid}`` saved the doc but never fired
``services/google_maps/geocoding.py::geocode_and_persist_property``.
Lazy backfill in ``services/stop_geo.py:65-102`` caught the gap on
first job use, so operators who created a property via the admin UI
would see the row render with null coords on the Schedule Map +
Dispatch Board until a job was scheduled against it.

TD-40 adds a fire-and-forget ``asyncio.create_task(...)`` call after
each successful insert / update (address-changing patch only — label-
only edits do NOT re-geocode so bulk label-renames don't melt the
geocoding quota). On an address change the stale ``geocoded_at`` /
``latitude`` / ``longitude`` are cleared BEFORE the update so the
helper's 30-day cache check doesn't short-circuit on the old coord.

This suite monkey-patches ``geocode_and_persist_property`` to a spy
and asserts the scheduling + cache-clearing behavior at the HTTP
boundary. The real geocoder is NOT called — tests remain fast,
deterministic, and don't require live Google API credit.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pytest
from dotenv import dotenv_values
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from motor.motor_asyncio import AsyncIOMotorClient

_BE = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
MONGO_URL = _BE.get("MONGO_URL") or os.environ.get("MONGO_URL")
DB_NAME = _BE.get("DB_NAME") or os.environ.get("DB_NAME")

_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)
_MC = AsyncIOMotorClient(MONGO_URL, io_loop=_LOOP)
_DB = _MC[DB_NAME]

PFX = "TESTtd40_"
TENANT = f"{PFX}tenant_A"


def _run(coro):
    asyncio.set_event_loop(_LOOP)
    return _LOOP.run_until_complete(coro)


async def _wipe():
    await _DB.properties.delete_many({"id": {"$regex": f"^{PFX}"}})
    await _DB.customers.delete_many({"id": {"$regex": f"^{PFX}"}})


@pytest.fixture(autouse=True)
def _clean():
    _run(_wipe())
    yield
    _run(_wipe())


# ─── Spy harness ──────────────────────────────────────────────────────


class _GeocodeSpy:
    """Records every ``geocode_and_persist_property(pid, tenant_id)``
    invocation. The real helper is NOT called — tests only verify
    scheduling intent + argument correctness."""
    def __init__(self):
        self.calls: List[Tuple[str, str]] = []

    async def __call__(self, property_id: str, tenant_id: str) -> bool:
        self.calls.append((property_id, tenant_id))
        return False  # Match the helper's "nothing persisted" return.


def _build_app(spy: _GeocodeSpy, *, role: str = "admin") -> FastAPI:
    """Mount ``routers.properties.router`` under ``/api``, override
    auth dependencies for a tenant-scoped admin, and monkey-patch the
    geocoder to the ``spy`` instance. Also monkey-patches
    ``routers.properties.db`` so inserts land in the test DB."""
    from routers import properties as props_mod
    from routers.tenants import get_current_tenant
    from utils import get_current_user, require_admin
    from services.google_maps import geocoding as _geo_mod

    user = {"id": f"{PFX}user", "role": role, "tenant_id": TENANT}
    tenant = {"id": TENANT}
    app = FastAPI()
    app.include_router(props_mod.router, prefix="/api")
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[require_admin] = lambda: user
    app.dependency_overrides[get_current_tenant] = lambda: tenant
    props_mod.db = _DB
    # The handler re-imports the geocoder lazily inside the try/except
    # (``from services.google_maps.geocoding import
    # geocode_and_persist_property``) — monkey-patch the module
    # attribute so the re-import resolves to the spy.
    _geo_mod.geocode_and_persist_property = spy
    return app


async def _seed_customer(cid: str) -> None:
    await _DB.customers.insert_one({
        "id": cid, "tenant_id": TENANT, "name": "TD-40 Cust",
        "active": True, "deleted_at": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })


async def _post_property(
    app: FastAPI, cid: str, body: Dict[str, Any],
) -> Tuple[int, Dict[str, Any]]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post(f"/api/customers/{cid}/properties", json=body)
    return r.status_code, r.json()


async def _patch_property(
    app: FastAPI, pid: str, body: Dict[str, Any],
) -> Tuple[int, Dict[str, Any]]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.patch(f"/api/properties/{pid}", json=body)
    return r.status_code, r.json()


# ─── §1 · Create — fire-and-forget geocode ────────────────────────────


def test_create_property_with_address_schedules_geocode():
    """Happy path — new property with an address string → one
    ``geocode_and_persist_property(pid, tenant_id)`` call scheduled."""
    spy = _GeocodeSpy()
    app = _build_app(spy)
    cid = f"{PFX}cust_1"
    _run(_seed_customer(cid))

    status, created = _run(_post_property(app, cid, {
        "label": "Main Pool",
        "address": {
            "line1": "123 Palm Dr",
            "city": "Phoenix",
            "state": "AZ",
            "postal_code": "85001",
        },
    }))
    assert status == 201
    assert created["label"] == "Main Pool"
    # Spy received exactly one call for this property + tenant.
    assert len(spy.calls) == 1
    assert spy.calls[0] == (created["id"], TENANT)


def test_create_property_with_empty_address_still_schedules_geocode():
    """Address body present but empty (all subfields None) — the
    helper's internal ``no_addr`` guard will log + skip, but the
    router MUST still schedule the task. Belt-and-suspenders: this
    guards against a future tightening of the router that would skip
    scheduling for empty-address payloads and accidentally break the
    lazy-backfill contract."""
    spy = _GeocodeSpy()
    app = _build_app(spy)
    cid = f"{PFX}cust_2"
    _run(_seed_customer(cid))

    status, created = _run(_post_property(app, cid, {
        "label": "No Address Yet",
        "address": {},
    }))
    assert status == 201
    # Task scheduled; the helper's internal ``no_addr`` log line
    # will emit when the task runs against the empty address.
    assert len(spy.calls) == 1
    assert spy.calls[0] == (created["id"], TENANT)


# ─── §2 · Patch — address change triggers re-geocode ──────────────────


def test_patch_property_address_change_reclears_cache_and_regeocodes():
    """Patching ``address.line1`` → stale ``geocoded_at`` + ``latitude``
    + ``longitude`` cleared, re-geocode scheduled."""
    spy = _GeocodeSpy()
    app = _build_app(spy)
    cid = f"{PFX}cust_3"
    pid = f"{PFX}prop_3"
    _run(_seed_customer(cid))
    # Seed a property that previously geocoded.
    _run(_DB.properties.insert_one({
        "id": pid, "tenant_id": TENANT, "customer_id": cid,
        "active": True, "label": "Backyard Pool",
        "address": {
            "line1": "100 Old Street", "city": "Phoenix",
            "state": "AZ", "postal_code": "85001",
        },
        "latitude": 33.1, "longitude": -112.1,
        "geocoded_at": datetime.now(timezone.utc).isoformat(),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }))

    status, patched = _run(_patch_property(app, pid, {
        "address": {
            "line1": "200 New Avenue", "city": "Phoenix",
            "state": "AZ", "postal_code": "85001",
        },
    }))
    assert status == 200
    # Stale cache cleared so the helper won't short-circuit.
    assert patched["geocoded_at"] is None
    assert patched["latitude"] is None
    assert patched["longitude"] is None
    # Re-geocode scheduled.
    assert len(spy.calls) == 1
    assert spy.calls[0] == (pid, TENANT)


def test_patch_property_label_only_does_not_regeocode():
    """Cosmetic label edit → NO re-geocode. Keeps bulk label-rename
    flights from melting the Google geocoding quota + preserves the
    existing coords so the Schedule Map doesn't flicker to "not
    geocoded" between the patch and the next geocode task."""
    spy = _GeocodeSpy()
    app = _build_app(spy)
    cid = f"{PFX}cust_4"
    pid = f"{PFX}prop_4"
    _run(_seed_customer(cid))
    geocoded_at_iso = datetime.now(timezone.utc).isoformat()
    _run(_DB.properties.insert_one({
        "id": pid, "tenant_id": TENANT, "customer_id": cid,
        "active": True, "label": "Old Label",
        "address": {
            "line1": "100 Palm Dr", "city": "Phoenix",
            "state": "AZ", "postal_code": "85001",
        },
        "latitude": 33.1, "longitude": -112.1,
        "geocoded_at": geocoded_at_iso,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }))

    status, patched = _run(_patch_property(app, pid, {
        "label": "New Fancy Label",
    }))
    assert status == 200
    assert patched["label"] == "New Fancy Label"
    # Coords + geocoded_at preserved.
    assert patched["latitude"] == 33.1
    assert patched["longitude"] == -112.1
    assert patched["geocoded_at"] == geocoded_at_iso
    # Spy NOT called.
    assert spy.calls == []


def test_patch_property_address_subfield_change_detects_partial_mutation():
    """Changing only ``address.postal_code`` (city + state + line1
    unchanged) still triggers re-geocode. Each of the four geocoding-
    material subfields independently signals an address change."""
    spy = _GeocodeSpy()
    app = _build_app(spy)
    cid = f"{PFX}cust_5"
    pid = f"{PFX}prop_5"
    _run(_seed_customer(cid))
    _run(_DB.properties.insert_one({
        "id": pid, "tenant_id": TENANT, "customer_id": cid,
        "active": True, "label": "Pool",
        "address": {
            "line1": "100 Palm Dr", "city": "Phoenix",
            "state": "AZ", "postal_code": "85001",
        },
        "latitude": 33.1, "longitude": -112.1,
        "geocoded_at": datetime.now(timezone.utc).isoformat(),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }))

    # Only postal_code differs.
    status, patched = _run(_patch_property(app, pid, {
        "address": {
            "line1": "100 Palm Dr", "city": "Phoenix",
            "state": "AZ", "postal_code": "85099",
        },
    }))
    assert status == 200
    assert patched["geocoded_at"] is None
    assert patched["latitude"] is None
    assert len(spy.calls) == 1
    assert spy.calls[0] == (pid, TENANT)


def test_patch_property_address_identical_subfields_no_regeocode():
    """Patching with the SAME address subfields (e.g. a full-form
    submit on a cosmetic edit flow that bundles the address field in
    the update dict) → NO re-geocode. Only actual value changes
    trigger the task."""
    spy = _GeocodeSpy()
    app = _build_app(spy)
    cid = f"{PFX}cust_6"
    pid = f"{PFX}prop_6"
    _run(_seed_customer(cid))
    geocoded_at_iso = datetime.now(timezone.utc).isoformat()
    _run(_DB.properties.insert_one({
        "id": pid, "tenant_id": TENANT, "customer_id": cid,
        "active": True, "label": "Pool",
        "address": {
            "line1": "100 Palm Dr", "city": "Phoenix",
            "state": "AZ", "postal_code": "85001",
        },
        "latitude": 33.1, "longitude": -112.1,
        "geocoded_at": geocoded_at_iso,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }))

    status, patched = _run(_patch_property(app, pid, {
        "address": {
            "line1": "100 Palm Dr", "city": "Phoenix",
            "state": "AZ", "postal_code": "85001",
        },
    }))
    assert status == 200
    # Cache preserved.
    assert patched["latitude"] == 33.1
    assert patched["longitude"] == -112.1
    assert patched["geocoded_at"] == geocoded_at_iso
    assert spy.calls == []


def test_patch_property_without_address_in_body_no_regeocode():
    """A PATCH that omits the ``address`` key entirely (e.g.
    toggling ``active``) must not consult the DB for the old
    address + must not re-geocode."""
    spy = _GeocodeSpy()
    app = _build_app(spy)
    cid = f"{PFX}cust_7"
    pid = f"{PFX}prop_7"
    _run(_seed_customer(cid))
    _run(_DB.properties.insert_one({
        "id": pid, "tenant_id": TENANT, "customer_id": cid,
        "active": True, "label": "Pool",
        "address": {
            "line1": "100 Palm Dr", "city": "Phoenix",
            "state": "AZ", "postal_code": "85001",
        },
        "latitude": 33.1, "longitude": -112.1,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }))

    status, patched = _run(_patch_property(app, pid, {
        "notes": "Access via side gate",
    }))
    assert status == 200
    assert patched["latitude"] == 33.1
    assert spy.calls == []
