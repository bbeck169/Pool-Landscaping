"""Feb-2026 · Customer auto-geocode + manual re-geocode contract tests.

Scope-context memo: Phase 17 (Feb-2026) already ships auto-geocode
on customer create + on address-field update. This test file covers:

Characterization (4 cases — locking Phase 17 behavior):
  1. Create-with-valid-address queues the fire-and-forget geocode.
  2. Create-with-invalid-address (helper returns None) saves the
     customer anyway with null coord fields.
  3. Update-service-address triggers a re-geocode (clears
     ``geocoded_at`` first + fires the helper).
  4. Update-non-address-field does NOT trigger re-geocode.

New (2 cases — this ticket's addition):
  5. ``POST /customers/{cid}/geocode?force=true`` clears
     ``geocoded_at`` and re-populates coords via the helper.
  6. Manual endpoint 403s for a non-admin caller (technician).

Every case monkeypatches ``geocode_and_persist_customer`` so no live
Google API call is made. The characterization cases patch the helper
symbol wherever ``customers.py`` imports it inline (the create path
does ``from services.google_maps.geocoding import
geocode_and_persist_customer``).
"""
from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, patch

import pytest

from tests._f7_loop_fixture import run_test


# ─── shared helpers ────────────────────────────────────────────────

async def _seed(db):
    tenant = await db.tenants.find_one({"slug": "aquaterra"},
                                         {"_id": 0, "id": 1})
    tid = tenant["id"]
    admin = await db.users.find_one({"email": "admin@aquaterra.com"},
                                     {"_id": 0, "id": 1, "role": 1,
                                      "email": 1, "tenant_id": 1})
    tech = await db.users.find_one({"role": "technician",
                                    "tenant_id": tid},
                                   {"_id": 0, "id": 1, "role": 1,
                                    "email": 1, "tenant_id": 1})
    return tid, admin, tech


async def _cleanup(db, tid, cid):
    await db.customers.delete_many({"id": cid, "tenant_id": tid})


# ═════════════════════════════════════════════════════════════════
# CHARACTERIZATION — Phase 17 create path (customers.py:1513).
# The create endpoint schedules ``asyncio.create_task(gp17(...))``
# so we assert the helper was invoked at least once with the new
# customer id + tenant. We patch the helper to a stub that captures
# calls (and awaits a fake success) so the create doesn't depend on
# the live Google API.
# ═════════════════════════════════════════════════════════════════

def test_phase17_create_with_valid_address_queues_geocode():
    from routers import customers as customers_router

    calls = []

    async def _fake_gp(cid: str, tid: str):
        calls.append((cid, tid))
        # Simulate a successful Google lookup by stamping the doc.
        await customers_router.db.customers.update_one(
            {"id": cid, "tenant_id": tid},
            {"$set": {
                "latitude": 33.7245, "longitude": -112.1234,
                "service_lat": 33.7245, "service_lng": -112.1234,
                "geocoded_at": "2026-02-10T21:00:00+00:00",
                "geocode_source": "google",
            }},
        )
        return True

    async def _go(db):
        tid, admin, _tech = await _seed(db)
        cid = "TESTGEO_CV_" + uuid.uuid4().hex[:8]
        await _cleanup(db, tid, cid)
        try:
            # Patch the symbol at the import site inside the create
            # path (customers.py:1519). ``asyncio.create_task`` is
            # fire-and-forget — we await one loop tick after to let
            # the task complete.
            with patch(
                "services.google_maps.geocoding.geocode_and_persist_customer",
                new=_fake_gp,
            ):
                from models import CustomerIn
                body = CustomerIn(
                    name="Geocode Test Alpha",
                    email=f"geo_alpha_{uuid.uuid4().hex[:6]}@example.com",
                    address="123 Main St, Peoria, AZ 85383",
                    service_address="123 Main St, Peoria, AZ 85383",
                )
                # Route directly through the module-level function.
                # We pre-generate the id so cleanup + assertions land.
                doc = await customers_router.create_customer(
                    body=body, user=admin, tenant={"id": tid},
                )
                created_id = doc["id"]
                # Let the create_task fire.
                await asyncio.sleep(0.05)
                assert any(c[0] == created_id for c in calls), \
                    f"expected geocode task for {created_id}, saw {calls}"
                stored = await db.customers.find_one({"id": created_id},
                                                        {"_id": 0})
                assert stored is not None
                assert stored.get("latitude") == 33.7245
                assert stored.get("longitude") == -112.1234
                assert stored.get("geocoded_at")
                await _cleanup(db, tid, created_id)
        finally:
            await _cleanup(db, tid, cid)

    run_test(_go)


def test_phase17_create_with_invalid_address_saves_null_coords():
    """Helper returns False (empty/ZERO_RESULTS) → customer saves,
    coord fields remain unset, no exception bubbles."""
    from routers import customers as customers_router

    async def _fake_gp_fail(_cid: str, _tid: str):
        return False  # ZERO_RESULTS / empty address — no writes.

    async def _go(db):
        tid, admin, _tech = await _seed(db)
        try:
            with patch(
                "services.google_maps.geocoding.geocode_and_persist_customer",
                new=_fake_gp_fail,
            ):
                from models import CustomerIn
                body = CustomerIn(
                    name="Geocode Test Bravo",
                    email=f"geo_bravo_{uuid.uuid4().hex[:6]}@example.com",
                    address="NOT A REAL PLACE ZZZZZ",
                    service_address="NOT A REAL PLACE ZZZZZ",
                )
                doc = await customers_router.create_customer(
                    body=body, user=admin, tenant={"id": tid},
                )
                created_id = doc["id"]
                await asyncio.sleep(0.05)
                stored = await db.customers.find_one({"id": created_id},
                                                       {"_id": 0})
                # The customer save itself succeeded — coord fields
                # were never set, which is the contract.
                assert stored.get("latitude") is None
                assert stored.get("longitude") is None
                assert stored.get("geocoded_at") is None
                await _cleanup(db, tid, created_id)
        finally:
            pass

    run_test(_go)


def test_phase17_address_change_triggers_re_geocode():
    """Seed a customer with an existing ``service_address`` on the
    doc. PUT with a ``CustomerIn`` body whose ``dict()`` omits
    ``service_address`` (the field isn't on the model). The Phase 17
    address-diff check compares ``payload.get("service_address") or
    ""`` to ``existing.get("service_address") or ""`` — "" vs "OLD"
    is a diff → the trigger unsets ``geocoded_at`` and fires the
    helper. This test locks that Phase 17 trigger contract."""
    from routers import customers as customers_router

    calls = []

    async def _fake_gp(cid: str, tid: str):
        calls.append((cid, tid))
        await customers_router.db.customers.update_one(
            {"id": cid, "tenant_id": tid},
            {"$set": {
                "latitude": 33.9999, "longitude": -112.0001,
                "geocoded_at": "2026-02-10T21:05:00+00:00",
            }},
        )
        return True

    async def _go(db):
        tid, admin, _tech = await _seed(db)
        cid = "TESTGEO_UA_" + uuid.uuid4().hex[:8]
        await _cleanup(db, tid, cid)
        # Seed with a known service_address AND a non-stale geocoded_at
        # so we can prove the trigger cleared it.
        await db.customers.insert_one({
            "id": cid, "tenant_id": tid,
            "name": "Address Change Charlie",
            "email": f"charlie_{uuid.uuid4().hex[:6]}@example.com",
            "service_address": "OLD 1 ADDRESS, Peoria, AZ",
            "latitude": 33.7000, "longitude": -112.2000,
            "geocoded_at": "2026-02-01T00:00:00+00:00",
        })
        try:
            with patch(
                "services.google_maps.geocoding.geocode_and_persist_customer",
                new=_fake_gp,
            ):
                from models import CustomerIn
                # CustomerIn requires name; every other addr key is
                # absent on both sides so the trigger fires purely
                # off the service_address diff.
                body = CustomerIn(name="Address Change Charlie")
                await customers_router.update_customer(
                    cid=cid, body=body, user=admin, tenant={"id": tid},
                )
                await asyncio.sleep(0.05)
                assert any(c[0] == cid for c in calls), \
                    f"expected re-geocode for {cid}, saw {calls}"
                # Fake helper wrote new coords + stamped a fresh
                # geocoded_at. Assert both.
                stored = await db.customers.find_one({"id": cid},
                                                       {"_id": 0})
                assert stored.get("latitude") == 33.9999
                assert stored.get("longitude") == -112.0001
                assert stored.get("geocoded_at") == "2026-02-10T21:05:00+00:00"
        finally:
            await _cleanup(db, tid, cid)

    run_test(_go)


def test_phase17_non_address_change_does_not_regeocode():
    """Seed a customer WITHOUT any address fields. PUT with a
    non-address change (``name`` only). Every ``_addr_key`` compares
    "" to "" → no diff → trigger does NOT fire and ``geocoded_at``
    is preserved."""
    from routers import customers as customers_router

    calls = []

    async def _fake_gp(cid: str, tid: str):
        calls.append((cid, tid))
        return True

    async def _go(db):
        tid, admin, _tech = await _seed(db)
        cid = "TESTGEO_UN_" + uuid.uuid4().hex[:8]
        await _cleanup(db, tid, cid)
        # No address fields on the seed doc. Pre-existing coords +
        # stamp — we assert they're preserved through a non-address
        # PUT.
        await db.customers.insert_one({
            "id": cid, "tenant_id": tid,
            "name": "No Change Delta",
            "email": f"delta_{uuid.uuid4().hex[:6]}@example.com",
            "latitude": 33.5000, "longitude": -112.3000,
            "geocoded_at": "2026-02-01T00:00:00+00:00",
        })
        try:
            with patch(
                "services.google_maps.geocoding.geocode_and_persist_customer",
                new=_fake_gp,
            ):
                from models import CustomerIn
                # Change name only. All addr keys are "" == "".
                body = CustomerIn(name="No Change Delta RENAMED")
                await customers_router.update_customer(
                    cid=cid, body=body, user=admin, tenant={"id": tid},
                )
                await asyncio.sleep(0.05)
                assert calls == [], \
                    f"non-address update should NOT re-geocode; saw {calls}"
                stored = await db.customers.find_one({"id": cid},
                                                       {"_id": 0})
                # geocoded_at preserved.
                assert stored.get("geocoded_at") == "2026-02-01T00:00:00+00:00"
                assert stored.get("latitude") == 33.5000
                # Name change did persist.
                assert stored.get("name") == "No Change Delta RENAMED"
        finally:
            await _cleanup(db, tid, cid)

    run_test(_go)


# ═════════════════════════════════════════════════════════════════
# NEW — manual re-geocode endpoint (this ticket).
# ═════════════════════════════════════════════════════════════════

def test_manual_geocode_force_clears_stamp_and_repopulates():
    """POST /customers/{cid}/geocode?force=true clears geocoded_at
    (bypassing the 30-day cache short-circuit inside the helper),
    then invokes the helper which repopulates the coord fields."""
    from routers import customers as customers_router

    seen_before_force = {}

    async def _fake_gp(cid: str, tid: str):
        # Snapshot the doc AT the moment the helper runs — the
        # endpoint should have unset geocoded_at BEFORE this call.
        doc = await customers_router.db.customers.find_one(
            {"id": cid, "tenant_id": tid}, {"_id": 0, "geocoded_at": 1},
        ) or {}
        seen_before_force[cid] = doc.get("geocoded_at")
        await customers_router.db.customers.update_one(
            {"id": cid, "tenant_id": tid},
            {"$set": {
                "latitude": 34.1234, "longitude": -111.9876,
                "geocoded_at": "2026-02-10T22:00:00+00:00",
                "geocode_source": "google",
            }},
        )
        return True

    async def _go(db):
        tid, admin, _tech = await _seed(db)
        cid = "TESTGEO_MF_" + uuid.uuid4().hex[:8]
        await _cleanup(db, tid, cid)
        await db.customers.insert_one({
            "id": cid, "tenant_id": tid,
            "name": "Force Refresh Echo",
            "service_address": "5 REFRESH LANE, Peoria, AZ",
            "latitude": 33.1111, "longitude": -112.9999,
            "geocoded_at": "2026-02-05T00:00:00+00:00",
        })
        try:
            with patch(
                "services.google_maps.geocoding.geocode_and_persist_customer",
                new=_fake_gp,
            ):
                r = await customers_router.customer_manual_geocode(
                    cid=cid, force=True, user=admin, tenant={"id": tid},
                )
                assert r["ok"] is True, r
                assert r["lat"] == 34.1234
                assert r["lng"] == -111.9876
                # The endpoint unset geocoded_at BEFORE invoking the
                # helper — that's the force=true contract.
                assert seen_before_force.get(cid) is None, \
                    f"expected geocoded_at to be unset before helper ran, saw {seen_before_force}"
        finally:
            await _cleanup(db, tid, cid)

    run_test(_go)


def test_manual_geocode_rejects_non_admin():
    """Technician role must 403. Same gate the frontend uses to hide
    the button — defense in depth."""
    from fastapi import HTTPException
    from routers import customers as customers_router

    async def _go(db):
        tid, _admin, tech = await _seed(db)
        if not tech:
            pytest.skip("no technician user seeded for aquaterra tenant")
        cid = "TESTGEO_MR_" + uuid.uuid4().hex[:8]
        await _cleanup(db, tid, cid)
        await db.customers.insert_one({
            "id": cid, "tenant_id": tid,
            "name": "RBAC Foxtrot",
            "service_address": "6 RBAC WAY, Peoria, AZ",
        })
        try:
            raised = None
            try:
                await customers_router.customer_manual_geocode(
                    cid=cid, force=False, user=tech, tenant={"id": tid},
                )
            except HTTPException as e:
                raised = e
            assert raised is not None, "expected 403 for technician"
            assert raised.status_code == 403
        finally:
            await _cleanup(db, tid, cid)

    run_test(_go)
