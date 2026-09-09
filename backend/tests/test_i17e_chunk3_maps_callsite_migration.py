"""Phase I1.7.e · Chunk 3 · Feb-2026 — Maps callsite migration.

Covers the invariants the ship plan promises:

1. **Feature-flag gate**. When ``MAPS_BYO_ENABLED=false`` every
   migrated shim behaves exactly as it did pre-Chunk-3 — no BYO
   probe, no cap enforcement, raw platform httpx call. When
   ``MAPS_BYO_ENABLED=true`` AND ``tenant_id`` is supplied, the shim
   routes through :mod:`services.maps.dispatcher`.
2. **New dispatcher op** — ``dispatch_maps_reverse_geocode`` with its
   own cap key ``reverse_geocode``. Falls back to platform when the
   BYO adapter returns ``None`` (base-class default).
3. **``cap_http`` helpers** translate ``TenantMapsRequestCapExceeded``
   → ``HTTPException(429)``. Legacy-shim result dicts with a
   ``cap_exceeded=True`` flag also translate cleanly.
4. **Testmode short-circuit**. ``MAPS_TESTMODE_MOCK=true`` at the
   dispatcher layer produces deterministic mock envelopes for every
   op (both BYO and platform branches).
5. **Boot guardrail**. ``MAPS_TESTMODE_MOCK=true`` in
   ``APP_ENV=production`` refuses to boot the process. Import fails
   with ``RuntimeError``.
6. **AST guard** — the retired rogue ``routers/property.py::
   maps_reverse_geocode`` no longer contains an inline ``httpx``
   call to ``maps.googleapis.com``.
7. **P0 sibling** — the checklist load path (``routers/jobs.py``)
   contains ZERO Maps callsites. Mirror of
   ``test_p0_checklist_429_leak_regression`` for AI.
"""
from __future__ import annotations

import ast
import asyncio
import importlib
import os
import sys
from pathlib import Path
from typing import Any

import pytest


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


# ═════════════════════════════════════════════════════════════════
# Fixtures
# ═════════════════════════════════════════════════════════════════
@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Every test starts with a known feature-flag/testmode state."""
    monkeypatch.delenv("MAPS_BYO_ENABLED", raising=False)
    monkeypatch.delenv("MAPS_TESTMODE_MOCK", raising=False)
    yield


# ═════════════════════════════════════════════════════════════════
# 1 · Feature-flag reader
# ═════════════════════════════════════════════════════════════════
class TestMapsFeatureFlag:
    def test_default_false(self, monkeypatch):
        monkeypatch.delenv("MAPS_BYO_ENABLED", raising=False)
        from services.maps.feature_flag import maps_byo_enabled
        assert maps_byo_enabled() is False

    @pytest.mark.parametrize("val", ["true", "TRUE", "1", "yes", "Yes"])
    def test_truthy(self, monkeypatch, val):
        monkeypatch.setenv("MAPS_BYO_ENABLED", val)
        from services.maps.feature_flag import maps_byo_enabled
        assert maps_byo_enabled() is True

    @pytest.mark.parametrize("val", ["false", "0", "no", "", "off"])
    def test_falsy(self, monkeypatch, val):
        monkeypatch.setenv("MAPS_BYO_ENABLED", val)
        from services.maps.feature_flag import maps_byo_enabled
        assert maps_byo_enabled() is False


# ═════════════════════════════════════════════════════════════════
# 2 · Testmode helpers + boot guardrail
# ═════════════════════════════════════════════════════════════════
class TestMapsTestmode:
    def test_is_maps_testmode_default_false(self, monkeypatch):
        monkeypatch.delenv("MAPS_TESTMODE_MOCK", raising=False)
        from services.maps.testmode import is_maps_testmode
        assert is_maps_testmode() is False

    def test_is_maps_testmode_true_when_set(self, monkeypatch):
        monkeypatch.setenv("MAPS_TESTMODE_MOCK", "true")
        from services.maps.testmode import is_maps_testmode
        assert is_maps_testmode() is True

    def test_mock_geocode_is_deterministic(self):
        from services.maps.testmode import mock_geocode_result
        a = mock_geocode_result(tenant_id="t1", address="123 Main St")
        b = mock_geocode_result(tenant_id="t1", address="123 Main St")
        assert a.lat == b.lat and a.lng == b.lng
        assert "testmode-mock" in a.formatted_address

    def test_mock_reverse_geocode_is_deterministic(self):
        from services.maps.testmode import mock_reverse_geocode_result
        a = mock_reverse_geocode_result(tenant_id="t1", lat=40.7, lng=-74.0)
        b = mock_reverse_geocode_result(tenant_id="t1", lat=40.7, lng=-74.0)
        assert a.provider_response_id == b.provider_response_id

    def test_mock_route_has_leg_per_destination(self):
        from services.maps.testmode import mock_route_result
        r = mock_route_result(
            tenant_id="t1", origin=(0.0, 0.0),
            destinations=[(1.0, 1.0), (2.0, 2.0), (3.0, 3.0)],
        )
        assert len(r.legs) == 3
        assert r.total_distance_m == 3000
        assert r.ordered_indices == [0, 1, 2]

    def test_boot_guardrail_raises_in_production(self, monkeypatch):
        """Boot guardrail: MAPS_TESTMODE_MOCK=true + APP_ENV=production
        must raise RuntimeError at module-import time. We call the
        internal helper directly rather than re-importing the module
        (which is cached in sys.modules)."""
        monkeypatch.setenv("APP_ENV", "production")
        monkeypatch.setenv("MAPS_TESTMODE_MOCK", "true")
        from services.maps.testmode import _assert_boot_safe
        with pytest.raises(RuntimeError, match="MAPS_TESTMODE_MOCK"):
            _assert_boot_safe()

    def test_boot_guardrail_passes_when_flag_off(self, monkeypatch):
        monkeypatch.setenv("APP_ENV", "production")
        monkeypatch.setenv("MAPS_TESTMODE_MOCK", "false")
        from services.maps.testmode import _assert_boot_safe
        _assert_boot_safe()  # no raise

    def test_boot_guardrail_passes_in_preview(self, monkeypatch):
        monkeypatch.setenv("APP_ENV", "preview")
        monkeypatch.setenv("MAPS_TESTMODE_MOCK", "true")
        from services.maps.testmode import _assert_boot_safe
        _assert_boot_safe()  # no raise


# ═════════════════════════════════════════════════════════════════
# 3 · cap_http helpers
# ═════════════════════════════════════════════════════════════════
class TestCapHttp:
    def test_is_cap_exceeded_true_on_flag(self):
        from services.maps.cap_http import is_maps_cap_exceeded
        assert is_maps_cap_exceeded({"cap_exceeded": True}) is True

    def test_is_cap_exceeded_true_on_error_code(self):
        from services.maps.cap_http import is_maps_cap_exceeded
        assert is_maps_cap_exceeded(
            {"error": "maps_spend_cap_exceeded"}) is True

    def test_is_cap_exceeded_true_on_http_status(self):
        from services.maps.cap_http import is_maps_cap_exceeded
        assert is_maps_cap_exceeded({"http_status": 429}) is True

    def test_is_cap_exceeded_false_on_none(self):
        from services.maps.cap_http import is_maps_cap_exceeded
        assert is_maps_cap_exceeded(None) is False

    def test_is_cap_exceeded_false_on_success(self):
        from services.maps.cap_http import is_maps_cap_exceeded
        assert is_maps_cap_exceeded(
            {"lat": 40.7, "lng": -74.0}) is False

    def test_raise_if_cap_exceeded_raises(self):
        from services.maps.cap_http import (
            raise_if_maps_cap_exceeded, CAP_EXCEEDED_HTTP_STATUS,
        )
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            raise_if_maps_cap_exceeded({"cap_exceeded": True})
        assert exc.value.status_code == CAP_EXCEEDED_HTTP_STATUS

    def test_raise_if_cap_exceeded_noop(self):
        from services.maps.cap_http import raise_if_maps_cap_exceeded
        raise_if_maps_cap_exceeded({"lat": 1.0, "lng": 2.0})
        raise_if_maps_cap_exceeded(None)
        raise_if_maps_cap_exceeded({"error": "other_reason"})

    def test_translate_tenant_exception(self):
        from fastapi import HTTPException
        from services.maps.cap_http import (
            translate_tenant_maps_cap_exception,
            CAP_EXCEEDED_HTTP_STATUS,
        )
        from services.maps.models import TenantMapsRequestCapExceeded
        exc = TenantMapsRequestCapExceeded(
            provider="google", cap=100, used=100,
        )
        http = translate_tenant_maps_cap_exception(exc)
        assert isinstance(http, HTTPException)
        assert http.status_code == CAP_EXCEEDED_HTTP_STATUS


# ═════════════════════════════════════════════════════════════════
# 4 · Dispatcher — reverse_geocode op + testmode short-circuit
# ═════════════════════════════════════════════════════════════════
class TestDispatcherReverseGeocode:
    def test_operations_include_reverse_geocode(self):
        from services.maps.models import OPERATIONS
        assert "reverse_geocode" in OPERATIONS

    def test_dispatch_op_symbol_exported(self):
        from services.maps import dispatch_maps_reverse_geocode  # noqa: F401

    def test_testmode_short_circuits_reverse_geocode(self, monkeypatch):
        monkeypatch.setenv("MAPS_TESTMODE_MOCK", "true")
        # No BYO row → hits _platform_reverse_geocode which short-
        # circuits on MAPS_TESTMODE_MOCK before doing any HTTP.
        from services.maps.dispatcher import _platform_reverse_geocode

        async def _run():
            return await _platform_reverse_geocode(
                tenant_id="t-xyz", lat=40.7, lng=-74.0,
            )
        res = asyncio.get_event_loop().run_until_complete(_run()) \
              if not asyncio.get_event_loop().is_running() \
              else asyncio.new_event_loop().run_until_complete(_run())
        assert res.provider_used == "platform:testmode_mock"
        assert res.tenant_id == "t-xyz"

    def test_testmode_short_circuits_geocode(self, monkeypatch):
        monkeypatch.setenv("MAPS_TESTMODE_MOCK", "true")
        from services.maps.dispatcher import _platform_geocode

        async def _run():
            return await _platform_geocode(
                tenant_id="t-abc", address="1600 Pennsylvania Ave",
            )
        loop = asyncio.new_event_loop()
        try:
            res = loop.run_until_complete(_run())
        finally:
            loop.close()
        assert res.provider_used == "platform:testmode_mock"
        assert res.tenant_id == "t-abc"


# ═════════════════════════════════════════════════════════════════
# 5 · Flag-OFF byte-identical behavior — shim doesn't touch dispatcher
# ═════════════════════════════════════════════════════════════════
class TestFlagOffBytewiseIdentical:
    def test_geocode_address_flag_off_never_dispatches(self, monkeypatch):
        """With MAPS_BYO_ENABLED=false, geocode_address() must NEVER
        call dispatch_maps_geocode — it goes straight to the raw
        platform httpx impl. Monkeypatch the dispatcher to raise if
        called; then invoke with tenant_id and confirm no raise."""
        monkeypatch.setenv("MAPS_BYO_ENABLED", "false")
        called = {"n": 0}

        async def _boom(**kwargs):
            called["n"] += 1
            raise AssertionError("dispatcher must NOT fire when flag off")

        async def _stub_platform(address):
            return {"lat": 1.0, "lng": 2.0,
                    "formatted_address": "STUB", "place_id": "x",
                    "precision": "ROOFTOP"}

        import services.google_maps.geocoding as gc
        monkeypatch.setattr(gc, "_platform_geocode_http", _stub_platform)
        # Bypass cache read/write by monkey-patching the module's ``db``.
        class _FakeCol:
            async def find_one(self, *a, **kw): return None
            async def update_one(self, *a, **kw): return None
        class _FakeDB:
            geocode_cache = _FakeCol()
        monkeypatch.setattr(gc, "db", _FakeDB())
        # If dispatcher were invoked it'd raise — this line proves it
        # doesn't get invoked.
        import services.maps.dispatcher as disp
        monkeypatch.setattr(disp, "dispatch_maps_geocode", _boom)

        loop = asyncio.new_event_loop()
        try:
            res = loop.run_until_complete(
                gc.geocode_address("123 Test St", tenant_id="t-1"),
            )
        finally:
            loop.close()
        assert res == {"lat": 1.0, "lng": 2.0, "formatted_address": "STUB",
                        "place_id": "x", "precision": "ROOFTOP"}
        assert called["n"] == 0

    def test_reverse_geocode_flag_off_never_dispatches(self, monkeypatch):
        monkeypatch.setenv("MAPS_BYO_ENABLED", "false")
        monkeypatch.setenv("MAPBOX_ACCESS_TOKEN", "fake-token")

        called = {"n": 0}

        async def _boom(**kwargs):
            called["n"] += 1
            raise AssertionError("dispatcher must NOT fire when flag off")

        async def _stub_platform(*, lat, lng, tenant_id):
            return {"status": "resolved",
                    "address": {"formatted": "STUB 40.7,-74.0"}}

        import services.reverse_geocoder as rg
        monkeypatch.setattr(rg, "_platform_reverse_geocode_http",
                                _stub_platform)
        # Bypass cache
        class _FakeCol:
            async def find_one(self, *a, **kw): return None
            async def update_one(self, *a, **kw): return None
        class _FakeDB:
            reverse_geocode_cache = _FakeCol()
        monkeypatch.setattr(rg, "db", _FakeDB())
        import services.maps.dispatcher as disp
        monkeypatch.setattr(disp,
                                "dispatch_maps_reverse_geocode", _boom)

        loop = asyncio.new_event_loop()
        try:
            res = loop.run_until_complete(
                rg.reverse_geocode(40.7, -74.0, "t-1"),
            )
        finally:
            loop.close()
        assert res["status"] == "resolved"
        assert res["address"]["formatted"] == "STUB 40.7,-74.0"
        assert called["n"] == 0


# ═════════════════════════════════════════════════════════════════
# 6 · Flag-ON path — shim routes through dispatcher
# ═════════════════════════════════════════════════════════════════
class TestFlagOnRoutesThroughDispatcher:
    def test_geocode_address_flag_on_calls_dispatcher(self, monkeypatch):
        monkeypatch.setenv("MAPS_BYO_ENABLED", "true")
        called = {"n": 0, "kwargs": None}

        from services.maps.models import MapsGeocodeResult

        async def _fake_dispatch(**kwargs):
            called["n"] += 1
            called["kwargs"] = kwargs
            return MapsGeocodeResult(
                address=kwargs["address"], lat=99.9, lng=-99.9,
                formatted_address="DISPATCHED",
                provider_response_id="pid-dispatched",
                provider_key="maps_platform",
                provider_used="platform:mock_via_dispatcher",
                tenant_id=kwargs["tenant_id"],
                raw={"via_dispatcher": True},
            )

        import services.google_maps.geocoding as gc
        # Patch cache to always miss + no-op write
        class _FakeCol:
            async def find_one(self, *a, **kw): return None
            async def update_one(self, *a, **kw): return None
        class _FakeDB:
            geocode_cache = _FakeCol()
        monkeypatch.setattr(gc, "db", _FakeDB())
        # Patch the LOCAL binding used inside geocode_address
        import services.maps.dispatcher as disp
        monkeypatch.setattr(disp, "dispatch_maps_geocode", _fake_dispatch)

        loop = asyncio.new_event_loop()
        try:
            res = loop.run_until_complete(
                gc.geocode_address("123 Real St", tenant_id="tenant-99"),
            )
        finally:
            loop.close()
        assert called["n"] == 1
        assert called["kwargs"]["tenant_id"] == "tenant-99"
        assert res["formatted_address"] == "DISPATCHED"
        assert res["place_id"] == "pid-dispatched"

    def test_reverse_geocode_flag_on_calls_dispatcher(self, monkeypatch):
        monkeypatch.setenv("MAPS_BYO_ENABLED", "true")
        called = {"n": 0}

        from services.maps.models import MapsGeocodeResult

        async def _fake_dispatch(**kwargs):
            called["n"] += 1
            return MapsGeocodeResult(
                address=f"reverse:{kwargs['lat']},{kwargs['lng']}",
                lat=float(kwargs["lat"]), lng=float(kwargs["lng"]),
                formatted_address="REVERSED",
                provider_response_id=None,
                provider_key="maps_platform",
                provider_used="platform:mock_via_dispatcher",
                tenant_id=kwargs["tenant_id"],
                raw={"address": {"formatted": "REVERSED"}},
            )

        import services.reverse_geocoder as rg
        class _FakeCol:
            async def find_one(self, *a, **kw): return None
            async def update_one(self, *a, **kw): return None
        class _FakeDB:
            reverse_geocode_cache = _FakeCol()
        monkeypatch.setattr(rg, "db", _FakeDB())
        import services.maps.dispatcher as disp
        monkeypatch.setattr(disp,
                                "dispatch_maps_reverse_geocode", _fake_dispatch)

        loop = asyncio.new_event_loop()
        try:
            res = loop.run_until_complete(
                rg.reverse_geocode(40.7, -74.0, "tenant-99"),
            )
        finally:
            loop.close()
        assert called["n"] == 1
        assert res["status"] == "resolved"
        assert res["address"]["formatted"] == "REVERSED"


# ═════════════════════════════════════════════════════════════════
# 7 · Cap-exceeded posture — best-effort callers log & continue
# ═════════════════════════════════════════════════════════════════
class TestCapExceededPosture:
    def test_geocode_address_returns_none_on_cap(self, monkeypatch):
        monkeypatch.setenv("MAPS_BYO_ENABLED", "true")
        from services.maps.models import TenantMapsRequestCapExceeded

        async def _cap(**kw):
            raise TenantMapsRequestCapExceeded(
                provider="google", cap=100, used=100,
            )

        import services.google_maps.geocoding as gc
        class _FakeCol:
            async def find_one(self, *a, **kw): return None
            async def update_one(self, *a, **kw): return None
        class _FakeDB:
            geocode_cache = _FakeCol()
        monkeypatch.setattr(gc, "db", _FakeDB())
        import services.maps.dispatcher as disp
        monkeypatch.setattr(disp, "dispatch_maps_geocode", _cap)

        loop = asyncio.new_event_loop()
        try:
            res = loop.run_until_complete(
                gc.geocode_address("X", tenant_id="t-1"),
            )
        finally:
            loop.close()
        assert res is None  # best-effort → log & skip

    def test_reverse_geocode_returns_cap_exceeded_on_cap(self, monkeypatch):
        monkeypatch.setenv("MAPS_BYO_ENABLED", "true")
        from services.maps.models import TenantMapsRequestCapExceeded

        async def _cap(**kw):
            raise TenantMapsRequestCapExceeded(
                provider="mapbox", cap=50, used=50,
            )

        import services.reverse_geocoder as rg
        class _FakeCol:
            async def find_one(self, *a, **kw): return None
            async def update_one(self, *a, **kw): return None
        class _FakeDB:
            reverse_geocode_cache = _FakeCol()
        monkeypatch.setattr(rg, "db", _FakeDB())
        import services.maps.dispatcher as disp
        monkeypatch.setattr(disp,
                                "dispatch_maps_reverse_geocode", _cap)

        loop = asyncio.new_event_loop()
        try:
            res = loop.run_until_complete(
                rg.reverse_geocode(40.7, -74.0, "t-1"),
            )
        finally:
            loop.close()
        assert res["status"] == "cap_exceeded"
        assert res["cap_exceeded"] is True
        assert res["http_status"] == 429
        # Transactional caller can now:
        from services.maps.cap_http import raise_if_maps_cap_exceeded
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            raise_if_maps_cap_exceeded(res)
        assert exc.value.status_code == 429


# ═════════════════════════════════════════════════════════════════
# 8 · AST guards — legacy modules + rogue caller
# ═════════════════════════════════════════════════════════════════
class TestASTGuards:
    def test_rogue_property_caller_no_longer_hits_googleapis_directly(self):
        """The Feb-2026 refactor retired the inline httpx.get to
        maps.googleapis.com inside
        routers/property.py::maps_reverse_geocode. It now delegates
        to services.reverse_geocoder.reverse_geocode."""
        src = (BACKEND_ROOT / "routers" / "property.py").read_text()
        # Find the maps_reverse_geocode function body.
        tree = ast.parse(src)
        func = None
        for node in ast.walk(tree):
            if (isinstance(node, ast.AsyncFunctionDef)
                    and node.name == "maps_reverse_geocode"):
                func = node
                break
        assert func is not None, "maps_reverse_geocode not found"
        body_src = ast.get_source_segment(src, func) or ""
        assert "maps.googleapis.com/maps/api/geocode/json" not in body_src, (
            "rogue direct-httpx caller still present in "
            "routers/property.py::maps_reverse_geocode")
        assert "services.reverse_geocoder" in body_src, (
            "maps_reverse_geocode must route through "
            "services.reverse_geocoder.reverse_geocode")

    @pytest.mark.parametrize("caller_file,expected_kw", [
        ("routers/directories.py", "tenant_id=tenant"),
        ("routers/dispatch_board.py", "tenant_id=tenant"),
        ("routers/on_my_way.py", "tenant_id=tenant_id"),
        ("routers/route_optimization.py", 'tenant_id=tenant["id"]'),
        ("routers/route_optimization_approval.py", "tenant_id=tenant_id"),
    ])
    def test_caller_threads_tenant_id_in_source(self, caller_file, expected_kw):
        src = (BACKEND_ROOT / caller_file).read_text()
        assert expected_kw in src, (
            f"{caller_file} must thread {expected_kw!r} into its "
            f"migrated Maps callsite (Chunk 3 · Feb-2026)")


# ═════════════════════════════════════════════════════════════════
# 9 · P0 sibling — checklist load path is Maps-free
# ═════════════════════════════════════════════════════════════════
class TestP0ChecklistNoMaps:
    def test_jobs_router_has_no_maps_dispatch(self):
        """The service-report / checklist load endpoints in
        routers/jobs.py MUST NOT touch any Maps callsite. Ensures a
        tenant's Maps cap-exceeded state can never 429 the checklist
        surface. Sibling of test_p0_checklist_429_leak_regression."""
        src = (BACKEND_ROOT / "routers" / "jobs.py").read_text()
        forbidden = [
            "dispatch_maps_",
            "geocode_address(",
            "reverse_geocode(",
            "optimize_route(",
            "compute_route_no_optimize(",
        ]
        for token in forbidden:
            assert token not in src, (
                f"routers/jobs.py must not contain {token!r} — this "
                f"path serves checklist load and must be Maps-free.")


# ═════════════════════════════════════════════════════════════════
# 10 · Dispatcher — BYO adapter returning None falls back to platform
# ═════════════════════════════════════════════════════════════════
class TestBYOReverseGeocodeFallback:
    def test_byo_returning_none_falls_back_to_platform(self, monkeypatch):
        """A BYO adapter that doesn't implement reverse_geocode
        returns ``None`` from the abstract base class. The dispatcher
        must then invoke the platform fallback WITHOUT charging the
        tenant's BYO cap."""
        from services.maps import dispatcher as disp
        from services.maps.tenant_base import MapsProvider

        class _StubProvider(MapsProvider):
            provider_key = "maps_google"

            async def geocode(self, **kw):
                raise NotImplementedError

            async def route(self, **kw):
                raise NotImplementedError

            def static_map_url(self, **kw):
                raise NotImplementedError

            async def test_connection(self, **kw):
                raise NotImplementedError

            # reverse_geocode is INHERITED from the base class and
            # returns None by default → dispatcher must fall back.

        async def _fake_get_tenant_provider(tenant_id, db=None):
            return _StubProvider()

        async def _fake_platform_reverse(**kw):
            from services.maps.models import MapsGeocodeResult
            return MapsGeocodeResult(
                address=f"reverse:{kw['lat']},{kw['lng']}",
                lat=kw["lat"], lng=kw["lng"],
                formatted_address="PLATFORM_FALLBACK",
                provider_response_id=None,
                provider_key="maps_platform",
                provider_used="platform:mapbox",
                tenant_id=kw["tenant_id"],
                raw={"platform": True},
            )

        record_calls = {"n": 0}

        async def _fake_enforce_cap(**kw):
            return None

        async def _fake_record_usage(**kw):
            record_calls["n"] += 1

        monkeypatch.setattr(disp, "get_tenant_maps_provider",
                                _fake_get_tenant_provider)
        monkeypatch.setattr(disp, "_platform_reverse_geocode",
                                _fake_platform_reverse)
        monkeypatch.setattr(disp, "enforce_cap_or_raise",
                                _fake_enforce_cap)
        monkeypatch.setattr(disp, "record_usage", _fake_record_usage)

        loop = asyncio.new_event_loop()
        try:
            res = loop.run_until_complete(
                disp.dispatch_maps_reverse_geocode(
                    tenant_id="t-x", lat=1.0, lng=2.0,
                ),
            )
        finally:
            loop.close()
        assert res.formatted_address == "PLATFORM_FALLBACK"
        # CRITICAL: usage NOT recorded on the tenant's BYO row when
        # the BYO adapter returned None.
        assert record_calls["n"] == 0
