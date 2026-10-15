"""TD-57 · Feb-2026 — ``geocode_and_persist_property`` reads BOTH
address-key schemas (current canonical ``line1 / postal_code`` AND
legacy ``address_line1 / zip``).

Pre-TD-57 the helper only consulted ``address.address_line1 /
address.zip`` — but the current ``routers/properties.py::_AddressIn``
Pydantic validator writes ``address.line1 / address.postal_code`` and
actively nullifies the legacy keys. Net effect: every property
created through the admin endpoint produced a doc whose
``address.address_line1`` / ``address.zip`` were empty, which made the
helper build an empty ``addr`` string, log ``[geocode-property]
method=no_addr``, and return ``False`` without ever hitting Google.
TD-40's fire-and-forget call to this helper (from
``routers/properties.py::create_property`` + ``patch_property``) was
therefore a NO-OP for every newly created property.

TD-57 fix: dual-schema read with ``canonical or legacy`` precedence.
Canonical wins when both are populated (the active writer path emits
canonical; the only docs that still carry legacy keys are
pre-P37-migration rows).

This suite monkey-patches the Google client in the helper to a spy
that records every ``geocode_address`` invocation; the real Google
API is NOT called. Also exercises the full ``POST /api/properties``
endpoint via FastAPI AsyncClient to confirm TD-40's wire-in now
delivers a non-empty address string to the helper on live-writer
paths.
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

PFX = "TESTtd57_"
TENANT = f"{PFX}tenant_A"


def _run(coro):
    asyncio.set_event_loop(_LOOP)
    return _LOOP.run_until_complete(coro)


async def _wipe():
    # Wipe by tenant_id — safer than id-prefix because properties
    # created via POST /api/customers/{cid}/properties (the e2e test)
    # get UUID ids that don't carry the ``TESTtd57_`` prefix. All of
    # this suite's writes are scoped to ``TENANT`` so wiping by
    # tenant_id is both complete and isolated from other suites.
    await _DB.properties.delete_many({"tenant_id": TENANT})
    await _DB.customers.delete_many({"tenant_id": TENANT})


@pytest.fixture(autouse=True)
def _clean():
    _run(_wipe())
    yield
    _run(_wipe())


# ─── Spy harness ──────────────────────────────────────────────────────


class _GeocodeAddressSpy:
    """Records every ``geocode_address(addr, tenant_id=...)``
    invocation inside ``geocode_and_persist_property``. Returns a
    canned Google-shaped hit so the helper proceeds through the
    persistence branch without touching the live API."""
    def __init__(self):
        self.calls: List[Tuple[str, Optional[str]]] = []

    async def __call__(self, addr: str, *, tenant_id: Optional[str] = None):
        self.calls.append((addr, tenant_id))
        return {
            "lat": 33.4484, "lng": -112.0740,
            "precision": "ROOFTOP",
            "place_id": "ChIJ_fake_td57",
            "formatted": addr,
        }


def _install_spy() -> _GeocodeAddressSpy:
    """Replace ``services.google_maps.geocoding.geocode_address``
    with a spy for the duration of a single test. The helper reads
    ``geocode_address`` at CALL time via a module-level import that
    FastAPI resolves on each request, so monkey-patching the module
    attribute is sufficient.

    Also rebinds the module's ``db`` to the test ``_DB`` so the
    helper's ``db.properties.find_one`` / ``db.properties.update_one``
    run on the test event loop (``_LOOP``) instead of the main pytest
    loop — otherwise Motor raises ``RuntimeError: ... attached to a
    different loop`` because the module-level ``from config import
    db`` resolves at import time against whatever loop initialized
    first.

    Lastly, re-pins ``geocode_and_persist_property`` to its real
    implementation. ``test_td40_property_geocode_on_save.py`` monkey-
    patches this attribute to a ``_GeocodeSpy`` class (which short-
    circuits BEFORE the helper's actual address-composition logic
    runs) and never restores it. When the top-level pytest batch runs
    TD-40 BEFORE TD-57, our TD-57 tests would otherwise hit the stale
    TD-40 spy and never exercise the TD-57 fix at all. Reloading the
    attribute from the fresh module import side-steps the leak.
    """
    import importlib
    from services.google_maps import geocoding as _geo_mod

    # Force a reload so ``geocode_and_persist_property`` is pinned to
    # the real symbol (undoes any monkey-patch from a prior test).
    importlib.reload(_geo_mod)
    spy = _GeocodeAddressSpy()
    _geo_mod.geocode_address = spy
    _geo_mod.db = _DB
    return spy


async def _seed_property(address_doc: Dict[str, Any]) -> str:
    """Insert a property row with the given address-dict shape and
    return the property id. ``address_doc`` is written verbatim —
    tests can mix canonical ``line1/postal_code`` and legacy
    ``address_line1/zip`` keys freely to exercise the dual-read
    behavior."""
    pid = f"{PFX}prop_{uuid.uuid4().hex[:10]}"
    await _DB.properties.insert_one({
        "id": pid, "tenant_id": TENANT,
        "active": True, "label": "TD-57 Pool",
        "address": address_doc,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    return pid


# ─── §1 · Dual-schema reads at the helper layer ───────────────────────


def test_geocode_reads_current_canonical_schema():
    """Property persisted via ``routers/properties.py::_AddressIn``
    carries ``address.line1 / address.postal_code``. Helper must
    compose a non-empty address string and fire the geocoder."""
    spy = _install_spy()
    # Import AFTER the spy install so we grab the post-reload symbol.
    from services.google_maps.geocoding import geocode_and_persist_property

    pid = _run(_seed_property({
        "line1": "100 Palm Dr", "city": "Phoenix",
        "state": "AZ", "postal_code": "85001",
    }))

    ok = _run(geocode_and_persist_property(pid, TENANT))
    assert ok is True
    assert len(spy.calls) == 1
    assert spy.calls[0][0] == "100 Palm Dr Phoenix AZ 85001"
    assert spy.calls[0][1] == TENANT


def test_geocode_reads_legacy_shape_as_backstop():
    """A legacy / un-migrated property row still carrying
    ``address.address_line1 / address.zip`` — helper falls back to
    those keys when canonical ones are absent."""
    spy = _install_spy()
    from services.google_maps.geocoding import geocode_and_persist_property

    pid = _run(_seed_property({
        "address_line1": "200 Legacy Rd",
        "city": "Phoenix", "state": "AZ", "zip": "85002",
    }))

    ok = _run(geocode_and_persist_property(pid, TENANT))
    assert ok is True
    assert len(spy.calls) == 1
    assert spy.calls[0][0] == "200 Legacy Rd Phoenix AZ 85002"


def test_geocode_canonical_wins_when_both_schemas_populated():
    """Defensive case — hand-crafted doc with BOTH schemas present.
    Canonical ``line1 / postal_code`` wins (active writer intent;
    legacy keys serve as backstop only, not as a priority
    override)."""
    spy = _install_spy()
    from services.google_maps.geocoding import geocode_and_persist_property

    pid = _run(_seed_property({
        "line1": "300 Canonical St",
        "address_line1": "300 Legacy St",
        "city": "Phoenix", "state": "AZ",
        "postal_code": "85003", "zip": "99999",
    }))

    ok = _run(geocode_and_persist_property(pid, TENANT))
    assert ok is True
    assert len(spy.calls) == 1
    # Canonical line1 + canonical postal_code win over the legacy
    # siblings.
    assert spy.calls[0][0] == "300 Canonical St Phoenix AZ 85003"


def test_geocode_dual_line2_handled():
    """``line2`` / ``address_line2`` also uses the dual-schema
    read — a canonical ``line2`` wins over legacy
    ``address_line2`` when both are populated. The composite
    address string includes both line1 + line2 (space-joined)."""
    spy = _install_spy()
    from services.google_maps.geocoding import geocode_and_persist_property

    pid = _run(_seed_property({
        "line1": "400 Palm Dr", "line2": "Unit 7B",
        "address_line2": "Suite 99",  # Legacy sibling — must lose.
        "city": "Phoenix", "state": "AZ", "postal_code": "85004",
    }))

    ok = _run(geocode_and_persist_property(pid, TENANT))
    assert ok is True
    assert len(spy.calls) == 1
    assert spy.calls[0][0] == "400 Palm Dr Unit 7B Phoenix AZ 85004"


def test_geocode_skipped_when_both_schemas_empty():
    """Neither canonical nor legacy keys present AND no city/state —
    helper logs ``method=no_addr`` and returns False WITHOUT calling
    the geocoder. Belt-and-suspenders: TD-57's dual-schema read must
    NOT inadvertently synthesize an address string from empty
    inputs. Note the helper's composed-string ladder also includes
    ``city`` + ``state`` which share one schema across both
    canonical and legacy — a doc with only ``city`` set still
    composes a (weak) address, so this test seeds a fully empty
    address dict to isolate the empty-addr guard."""
    spy = _install_spy()
    from services.google_maps.geocoding import geocode_and_persist_property

    pid = _run(_seed_property({}))

    ok = _run(geocode_and_persist_property(pid, TENANT))
    assert ok is False
    # No geocode call fired — the empty-address guard still works.
    assert spy.calls == []


def test_geocode_partial_canonical_fills_from_legacy_sibling():
    """Half-migrated row — canonical ``line1`` set but
    ``postal_code`` empty; legacy ``zip`` present. Each subfield
    reads independently: canonical ``line1`` wins for its slot, and
    the empty-canonical ``postal_code`` falls back to the legacy
    ``zip``."""
    spy = _install_spy()
    from services.google_maps.geocoding import geocode_and_persist_property

    pid = _run(_seed_property({
        "line1": "500 Half Migration Rd",
        "zip": "85005",  # Only the legacy sibling for postal.
        "city": "Phoenix", "state": "AZ",
    }))

    ok = _run(geocode_and_persist_property(pid, TENANT))
    assert ok is True
    assert len(spy.calls) == 1
    assert spy.calls[0][0] == "500 Half Migration Rd Phoenix AZ 85005"


# ─── §2 · Integration — TD-40 closes the loop end-to-end ──────────────


def test_td40_fire_and_forget_now_hits_geocoder_with_real_address():
    """End-to-end — fire a real ``POST /api/customers/{cid}/
    properties`` through the FastAPI handler. TD-40 scheduled a
    fire-and-forget ``geocode_and_persist_property`` task after
    insert; TD-57 fixes the helper so the task now composes a
    non-empty address string from the Pydantic-canonical ``address.
    line1 / address.postal_code`` shape and fires the geocoder.

    This test is the regression guard that locks TD-40 + TD-57 as a
    unit — if a future refactor breaks either side (the fire-and-
    forget wire-in in ``create_property`` OR the dual-schema read
    in the helper), this test flips red."""
    from routers import properties as props_mod
    from routers.tenants import get_current_tenant
    from utils import get_current_user, require_admin

    # Install the geocoder spy BEFORE building the app so the handler's
    # lazy ``from services.google_maps.geocoding import ...`` resolves
    # to a geocode_and_persist_property that actually hits our
    # geocode_address spy inside.
    spy = _install_spy()

    user = {"id": f"{PFX}user", "role": "admin", "tenant_id": TENANT}
    tenant = {"id": TENANT}
    app = FastAPI()
    app.include_router(props_mod.router, prefix="/api")
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[require_admin] = lambda: user
    app.dependency_overrides[get_current_tenant] = lambda: tenant
    props_mod.db = _DB

    # Seed the parent customer so the create route's FK check passes.
    cid = f"{PFX}cust_td40_td57"
    _run(_DB.customers.insert_one({
        "id": cid, "tenant_id": TENANT, "name": "TD-40/57 E2E",
        "active": True, "deleted_at": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }))

    async def _hit():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            r = await c.post(f"/api/customers/{cid}/properties", json={
                "label": "TD-40/57 E2E Property",
                "address": {
                    "line1": "888 Composite Blvd",
                    "city": "Phoenix", "state": "AZ",
                    "postal_code": "85088",
                },
            })
            # Yield so the fire-and-forget task gets a chance to run
            # before the test tears down. Without this the task might
            # still be ``pending`` when ``_wipe`` fires.
            await asyncio.sleep(0.1)
        return r

    r = _run(_hit())
    assert r.status_code == 201

    # The fire-and-forget task should have fired exactly one geocode
    # call with the canonical-composed address string. Prior to TD-57
    # this was 0 calls (helper read legacy keys that _AddressIn
    # nullifies).
    assert len(spy.calls) == 1
    assert spy.calls[0][0] == "888 Composite Blvd Phoenix AZ 85088"
    assert spy.calls[0][1] == TENANT
