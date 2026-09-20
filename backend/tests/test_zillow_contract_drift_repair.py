"""Phase P1.1 · Feb 2026 — Zillow adapter contract-drift repair.

Covers:
  1. Both symbols (``get_zillow_client`` + ``ZillowError``) are
     importable from BOTH modules:
       * ``services.property_data.zillow_adapter`` (canonical)
       * ``services.enrichment.zillow`` (re-exports for callers
         that already import from here)
  2. ``ZillowError`` is a real ``Exception`` subclass with a
     ``.status_code`` attribute + a ``.detail`` slug.
  3. Missing-key path: ``get_zillow_client()`` raises
     ``ZillowError(status_code=503, detail="zillow_not_configured")``
     — the ONLY 503 the frontend should ever see for Zillow.
  4. Upstream-5xx path: adapter returns ``{unavailable, reason=
     provider_error}``; the enrichment wrapper translates that to
     ``ZillowError(502, "zillow_upstream_error")``. This is the
     ONLY legitimate 502 path.
  5. 404-shaped miss: ``reason=not_found`` translates to
     ``ZillowError(404, "zillow_address_not_found")`` — NOT a 502.
  6. Rate-limited path: ``reason=quota_exhausted`` translates to
     ``ZillowRateLimited`` (backwards-compat with the existing
     router catch).
  7. The lazy singleton returns the SAME instance on repeat calls.

No live network — every test either mocks the env var or the
``ZillowClient.search_by_address`` coroutine.
"""
from __future__ import annotations

import os
from typing import Any, Dict

import pytest


# ═════════════════════════════════════════════════════════════════════
# Import-surface parity
# ═════════════════════════════════════════════════════════════════════
def test_symbols_importable_from_adapter_module():
    """The canonical location."""
    from services.property_data.zillow_adapter import (
        get_zillow_client, ZillowError,
    )
    assert callable(get_zillow_client)
    assert isinstance(ZillowError, type)


def test_symbols_importable_from_enrichment_module():
    """The enrichment wrapper re-exports both so callers that
    already import from here keep working."""
    from services.enrichment.zillow import get_zillow_client, ZillowError
    assert callable(get_zillow_client)
    assert isinstance(ZillowError, type)


def test_both_modules_expose_the_same_class_identity():
    """Regression: if a future refactor accidentally defines a
    parallel ``ZillowError`` in one of the two modules, the router's
    ``except ZillowError as e`` catch would silently miss the other
    one. Enforce identity via ``is``."""
    from services.property_data.zillow_adapter import (
        ZillowError as _adapter_err, get_zillow_client as _adapter_fac,
    )
    from services.enrichment.zillow import (
        ZillowError as _enrich_err, get_zillow_client as _enrich_fac,
    )
    assert _adapter_err is _enrich_err
    assert _adapter_fac is _enrich_fac


# ═════════════════════════════════════════════════════════════════════
# ZillowError shape
# ═════════════════════════════════════════════════════════════════════
def test_zillow_error_is_exception_subclass_with_status_code():
    from services.property_data.zillow_adapter import ZillowError
    assert issubclass(ZillowError, Exception)
    e = ZillowError(status_code=503, detail="zillow_not_configured")
    assert e.status_code == 503
    assert e.detail == "zillow_not_configured"
    # Message defaults to a readable summary.
    assert "zillow_not_configured" in str(e)
    assert "503" in str(e)


def test_zillow_error_custom_message_wins():
    from services.property_data.zillow_adapter import ZillowError
    e = ZillowError(status_code=429, detail="rl", message="custom")
    assert str(e) == "custom"


# ═════════════════════════════════════════════════════════════════════
# get_zillow_client — configuration surface
# ═════════════════════════════════════════════════════════════════════
def _clear_zillow_env(monkeypatch):
    """Wipe every env var that ``keys_configured()`` inspects so the
    ``keys_missing`` branch fires deterministically regardless of
    what's in the pod's real ``.env``."""
    for name in ("OPENWEB_NINJA_ZILLOW_API_KEY", "OPENWEB_NINJA_API_KEY",
                  "OWN_API_KEY"):
        monkeypatch.delenv(name, raising=False)


def test_get_zillow_client_raises_503_when_key_missing(monkeypatch):
    _clear_zillow_env(monkeypatch)
    from services.property_data.zillow_adapter import (
        get_zillow_client, ZillowError, _reset_singleton_for_tests,
    )
    _reset_singleton_for_tests()
    with pytest.raises(ZillowError) as exc_info:
        get_zillow_client()
    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == "zillow_not_configured"


def test_get_zillow_client_raises_503_when_key_is_placeholder(monkeypatch):
    _clear_zillow_env(monkeypatch)
    # The placeholder-detection short-circuit — ``REPLACE_ME_...``
    # values are treated as unset.
    monkeypatch.setenv("OPENWEB_NINJA_API_KEY", "REPLACE_ME_ACTUAL_KEY")
    from services.property_data.zillow_adapter import (
        get_zillow_client, ZillowError, _reset_singleton_for_tests,
        _reset_placeholder_warning_for_tests,
    )
    _reset_singleton_for_tests()
    _reset_placeholder_warning_for_tests()
    with pytest.raises(ZillowError) as exc_info:
        get_zillow_client()
    assert exc_info.value.status_code == 503


def test_get_zillow_client_returns_singleton_when_key_present(monkeypatch):
    _clear_zillow_env(monkeypatch)
    monkeypatch.setenv("OPENWEB_NINJA_API_KEY", "own_real_key_deadbeef")
    from services.property_data.zillow_adapter import (
        get_zillow_client, ZillowClient, _reset_singleton_for_tests,
    )
    _reset_singleton_for_tests()
    c1 = get_zillow_client()
    c2 = get_zillow_client()
    assert c1 is c2, "singleton contract broken — factory returned two instances"
    assert isinstance(c1, ZillowClient)


# ═════════════════════════════════════════════════════════════════════
# enrichment/zillow reason → structured error mapping
# ═════════════════════════════════════════════════════════════════════
class _StubClient:
    """Drop-in replacement for :class:`ZillowClient` — returns a
    fixed dict from ``search_by_address`` so tests exercise the
    reason→error mapping in ``fetch_zillow_property`` without a
    network hop."""
    def __init__(self, canned: Dict[str, Any]):
        self._canned = canned

    async def search_by_address(self, address, tenant_id=None):
        return self._canned


def _patch_client(monkeypatch, canned: Dict[str, Any]):
    """Force ``get_zillow_client`` to return a stub with a canned
    return value. Also flips the env so the ``fetch_zillow_property``
    path takes the LIVE branch (not the mock branch)."""
    _clear_zillow_env(monkeypatch)
    monkeypatch.setenv("OPENWEB_NINJA_API_KEY", "own_real_key_test")
    monkeypatch.delenv("ZILLOW_TESTMODE_MOCK", raising=False)
    from services.property_data.zillow_adapter import _reset_singleton_for_tests
    _reset_singleton_for_tests()
    import services.enrichment.zillow as ez
    monkeypatch.setattr(ez, "get_zillow_client",
                          lambda: _StubClient(canned),
                          raising=True)


def _stub_db():
    """In-memory Motor-shaped stub that swallows every call the
    ``fetch_zillow_property`` control path makes (cache read/write +
    rate-limit inc). Returning ``None`` from ``find_one`` forces the
    live-fetch branch."""
    class _Coll:
        def __init__(self):
            self._store: Dict[str, Any] = {}
        async def find_one(self, *a, **kw): return None
        async def update_one(self, *a, **kw): return type("R", (), {"modified_count": 1})()
        async def find_one_and_update(self, filter_, update, **kw):
            # Return a doc with an ok count so the rate-limit check passes.
            return {"count": 1}
    class _DB:
        def __init__(self):
            self._colls: Dict[str, _Coll] = {}
        def __getitem__(self, name):
            return self._colls.setdefault(name, _Coll())
    return _DB()


def test_upstream_5xx_yields_502_zillow_upstream_error(monkeypatch):
    _patch_client(monkeypatch, {
        "unavailable": True,
        "reason": "provider_error",
    })
    from services.enrichment.zillow import (
        fetch_zillow_property, ZillowError,
    )
    import asyncio
    async def _drive():
        with pytest.raises(ZillowError) as exc_info:
            await fetch_zillow_property(
                "123 Fake St", tenant_id="t-p11-1", db=_stub_db(),
            )
        return exc_info.value
    err = asyncio.new_event_loop().run_until_complete(_drive())
    assert err.status_code == 502
    assert err.detail == "zillow_upstream_error"


def test_not_found_yields_404_not_502(monkeypatch):
    _patch_client(monkeypatch, {
        "unavailable": True, "reason": "not_found",
    })
    from services.enrichment.zillow import (
        fetch_zillow_property, ZillowError,
    )
    import asyncio
    async def _drive():
        with pytest.raises(ZillowError) as exc_info:
            await fetch_zillow_property(
                "0 Nowhere Rd", tenant_id="t-p11-2", db=_stub_db(),
            )
        return exc_info.value
    err = asyncio.new_event_loop().run_until_complete(_drive())
    assert err.status_code == 404
    assert err.detail == "zillow_address_not_found"


def test_quota_exhausted_yields_zillow_rate_limited(monkeypatch):
    """Backwards-compat: existing router already catches
    ``ZillowRateLimited`` and returns 429 with retry-hints. We map
    ``reason=quota_exhausted`` to that same exception so the router
    stays unchanged for the rate-limit case."""
    _patch_client(monkeypatch, {
        "unavailable": True, "reason": "quota_exhausted",
    })
    from services.enrichment.zillow import (
        fetch_zillow_property, ZillowRateLimited,
    )
    import asyncio
    async def _drive():
        with pytest.raises(ZillowRateLimited):
            await fetch_zillow_property(
                "1 Rate Ln", tenant_id="t-p11-3", db=_stub_db(),
            )
    asyncio.new_event_loop().run_until_complete(_drive())


def test_keys_not_configured_reason_yields_zillow_not_configured(monkeypatch):
    """The adapter may return ``keys_not_configured`` per-call even
    after ``get_zillow_client`` succeeded (env can be cleared mid-
    process). Map it to the historical exception the router catches."""
    _patch_client(monkeypatch, {
        "unavailable": True, "reason": "keys_not_configured",
    })
    from services.enrichment.zillow import (
        fetch_zillow_property, ZillowNotConfigured,
    )
    import asyncio
    async def _drive():
        with pytest.raises(ZillowNotConfigured):
            await fetch_zillow_property(
                "2 Keys Ave", tenant_id="t-p11-4", db=_stub_db(),
            )
    asyncio.new_event_loop().run_until_complete(_drive())


def test_test_scope_refused_yields_403_zillow_test_scope_refused(monkeypatch):
    _patch_client(monkeypatch, {
        "unavailable": True, "reason": "test_scope_refused",
    })
    from services.enrichment.zillow import (
        fetch_zillow_property, ZillowError,
    )
    import asyncio
    async def _drive():
        with pytest.raises(ZillowError) as exc_info:
            await fetch_zillow_property(
                "3 Preview Way", tenant_id="t-p11-5", db=_stub_db(),
            )
        return exc_info.value
    err = asyncio.new_event_loop().run_until_complete(_drive())
    assert err.status_code == 403
    assert err.detail == "zillow_test_scope_refused"


# ═════════════════════════════════════════════════════════════════════
# Happy-path — ensure the `{unavailable: False, data: {...}}` return
# is unwrapped correctly and does NOT raise anything.
# ═════════════════════════════════════════════════════════════════════
def test_happy_path_unwraps_data_field(monkeypatch):
    canned = {
        "unavailable": False,
        "cached": False,
        "data": {
            # Shape OpenWebNinja returns for /property-details-address.
            "results": [{
                "zpid": "12345", "address": "42 Real St",
                "zestimate": 620_000, "livingArea": 2100,
                "lotAreaValue": 6200, "bedrooms": 4, "bathrooms": 2.5,
                "yearBuilt": 1992,
            }],
        },
    }
    _patch_client(monkeypatch, canned)
    from services.enrichment.zillow import fetch_zillow_property
    import asyncio
    async def _drive():
        return await fetch_zillow_property(
            "42 Real St", tenant_id="t-p11-6", db=_stub_db(),
        )
    prop = asyncio.new_event_loop().run_until_complete(_drive())
    assert prop.zpid == "12345"
    assert prop.estimated_value == 620_000
    assert prop.sqft == 2100
    assert prop.bed_count == 4.0
    assert prop.bath_count == 2.5
    assert prop.mock is False
    assert prop.cached is False


# ═════════════════════════════════════════════════════════════════════
# OpenAPI regression guard — the change adds no new endpoints, but
# a broken import at module-top would 500 the schema too.
# ═════════════════════════════════════════════════════════════════════
def test_openapi_schema_resolves():
    from server import app
    schema = app.openapi()
    assert isinstance(schema, dict)
    assert schema.get("openapi", "").startswith("3.")
    paths = schema.get("paths") or {}
    # The two D2D Zillow paths that consume the reconciled contract.
    assert "/api/d2d/zillow-lookup" in paths
    assert "/api/d2d/prospects/{prospect_id}/enrich-zillow" in paths
