"""FLEET-A · ETA provider chain tests.

Covers the layered fallback in ``services.fleet.eta``:

  1. Crow-flies (Haversine) is deterministic + purely local — used
     as the golden-baseline for distance / duration math.
  2. Google Distance Matrix — mock the HTTP response and confirm
     ``compute_eta`` picks it when ``GOOGLE_MAPS_API_KEY`` is set.
  3. Google failure → falls through to OSRM.
  4. OSRM failure → falls through to crow-flies.
  5. Google + OSRM both dead → crow-flies always wins the fallback.
  6. Result shape stability — always an ``ETAResult`` with a
     recognised provider name.
"""
from __future__ import annotations

import asyncio
import math
from unittest.mock import patch, AsyncMock

import httpx
import pytest

from services.fleet import eta


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


# ─── Haversine baseline ────────────────────────────────────────────

def test_crowflies_same_point_is_zero():
    r = eta.compute_eta_crowflies(33.7897, -112.3226,
                                     33.7897, -112.3226)
    assert r.provider == "crowflies"
    assert r.distance_m == 0
    assert r.duration_s == 0


def test_crowflies_matches_haversine_math():
    # Two points ~5 km apart in Phoenix — known-quantity fixture.
    d = eta._haversine_m(33.7897, -112.3226, 33.8347, -112.3226)
    assert 4800 < d < 5200                                         # ~5 km
    r = eta.compute_eta_crowflies(33.7897, -112.3226,
                                     33.8347, -112.3226)
    assert r.distance_m == int(round(d))
    # 40 km/h → 5 km takes ~450 s (7.5 min).
    assert 400 < r.duration_s < 500


def test_crowflies_never_raises_on_edge_lats():
    # Polar edge — must not blow up.
    r = eta.compute_eta_crowflies(-89.9, 0.0, 89.9, 0.0)
    assert r.distance_m > 0
    assert r.provider == "crowflies"


# ─── Google ─────────────────────────────────────────────────────────

def test_google_returns_none_without_key(monkeypatch):
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)
    r = _run(eta.compute_eta_google(33.0, -112.0, 34.0, -113.0))
    assert r is None


def test_google_parses_ok_response(monkeypatch):
    class _Resp:
        status_code = 200
        def json(self):
            return {"status": "OK", "rows": [{"elements": [{
                "status": "OK",
                "distance": {"value": 5432},
                "duration": {"value": 813},
            }]}]}

    class _Client:
        async def get(self, url):
            return _Resp()
        async def __aenter__(self): return self
        async def __aexit__(self, *_): return None

    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "AIfake")
    monkeypatch.setattr(httpx, "AsyncClient",
                          lambda *a, **kw: _Client())
    r = _run(eta.compute_eta_google(33.0, -112.0, 34.0, -113.0))
    assert r is not None
    assert r.provider == "google"
    assert r.distance_m == 5432
    assert r.duration_s == 813


def test_google_bad_status_returns_none(monkeypatch):
    class _Resp:
        status_code = 200
        def json(self):
            return {"status": "REQUEST_DENIED"}

    class _Client:
        async def get(self, url):
            return _Resp()
        async def __aenter__(self): return self
        async def __aexit__(self, *_): return None

    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "AIfake")
    monkeypatch.setattr(httpx, "AsyncClient",
                          lambda *a, **kw: _Client())
    assert _run(eta.compute_eta_google(33.0, -112.0, 34.0, -113.0)) is None


def test_google_element_not_ok_returns_none(monkeypatch):
    class _Resp:
        status_code = 200
        def json(self):
            return {"status": "OK", "rows": [{"elements": [{
                "status": "ZERO_RESULTS",
            }]}]}

    class _Client:
        async def get(self, url):
            return _Resp()
        async def __aenter__(self): return self
        async def __aexit__(self, *_): return None

    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "AIfake")
    monkeypatch.setattr(httpx, "AsyncClient",
                          lambda *a, **kw: _Client())
    assert _run(eta.compute_eta_google(33.0, -112.0, 34.0, -113.0)) is None


def test_google_http_error_returns_none(monkeypatch):
    class _Resp:
        status_code = 500
        def json(self):
            return {}

    class _Client:
        async def get(self, url):
            return _Resp()
        async def __aenter__(self): return self
        async def __aexit__(self, *_): return None

    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "AIfake")
    monkeypatch.setattr(httpx, "AsyncClient",
                          lambda *a, **kw: _Client())
    assert _run(eta.compute_eta_google(33.0, -112.0, 34.0, -113.0)) is None


def test_google_exception_returns_none(monkeypatch):
    class _Client:
        async def get(self, url):
            raise RuntimeError("network dead")
        async def __aenter__(self): return self
        async def __aexit__(self, *_): return None

    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "AIfake")
    monkeypatch.setattr(httpx, "AsyncClient",
                          lambda *a, **kw: _Client())
    assert _run(eta.compute_eta_google(33.0, -112.0, 34.0, -113.0)) is None


# ─── OSRM ───────────────────────────────────────────────────────────

def test_osrm_parses_route_response(monkeypatch):
    class _Resp:
        status_code = 200
        def json(self):
            return {"routes": [{"distance": 7777.0, "duration": 999.0}]}

    class _Client:
        async def get(self, url):
            return _Resp()
        async def __aenter__(self): return self
        async def __aexit__(self, *_): return None

    monkeypatch.setattr(httpx, "AsyncClient",
                          lambda *a, **kw: _Client())
    r = _run(eta.compute_eta_osrm(33.0, -112.0, 34.0, -113.0,
                                     base_url="http://osrm.test"))
    assert r is not None
    assert r.provider == "osrm"
    assert r.distance_m == 7777
    assert r.duration_s == 999


def test_osrm_empty_routes_returns_none(monkeypatch):
    class _Resp:
        status_code = 200
        def json(self):
            return {"routes": []}

    class _Client:
        async def get(self, url):
            return _Resp()
        async def __aenter__(self): return self
        async def __aexit__(self, *_): return None

    monkeypatch.setattr(httpx, "AsyncClient",
                          lambda *a, **kw: _Client())
    assert _run(eta.compute_eta_osrm(33.0, -112.0, 34.0, -113.0)) is None


def test_osrm_http_error_returns_none(monkeypatch):
    class _Resp:
        status_code = 502
        def json(self):
            return {}

    class _Client:
        async def get(self, url):
            return _Resp()
        async def __aenter__(self): return self
        async def __aexit__(self, *_): return None

    monkeypatch.setattr(httpx, "AsyncClient",
                          lambda *a, **kw: _Client())
    assert _run(eta.compute_eta_osrm(33.0, -112.0, 34.0, -113.0)) is None


def test_osrm_exception_returns_none(monkeypatch):
    class _Client:
        async def get(self, url):
            raise TimeoutError("timeout")
        async def __aenter__(self): return self
        async def __aexit__(self, *_): return None

    monkeypatch.setattr(httpx, "AsyncClient",
                          lambda *a, **kw: _Client())
    assert _run(eta.compute_eta_osrm(33.0, -112.0, 34.0, -113.0)) is None


# ─── Fallback chain ─────────────────────────────────────────────────

def test_fallback_google_success_wins(monkeypatch):
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "AIfake")

    async def _fake_google(*a, **kw):
        return eta.ETAResult(provider="google",
                              distance_m=5000, duration_s=600)

    async def _fake_osrm(*a, **kw):
        pytest.fail("OSRM must not be called when Google succeeds")

    monkeypatch.setattr(eta, "compute_eta_google", _fake_google)
    monkeypatch.setattr(eta, "compute_eta_osrm", _fake_osrm)

    r = _run(eta.compute_eta(33.0, -112.0, 34.0, -113.0))
    assert r.provider == "google"


def test_fallback_google_fail_osrm_wins(monkeypatch):
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "AIfake")

    async def _fake_google(*a, **kw):
        return None

    async def _fake_osrm(*a, **kw):
        return eta.ETAResult(provider="osrm",
                              distance_m=6000, duration_s=720)

    monkeypatch.setattr(eta, "compute_eta_google", _fake_google)
    monkeypatch.setattr(eta, "compute_eta_osrm", _fake_osrm)

    r = _run(eta.compute_eta(33.0, -112.0, 34.0, -113.0))
    assert r.provider == "osrm"


def test_fallback_both_fail_crowflies_wins(monkeypatch):
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "AIfake")

    async def _dead(*a, **kw):
        return None

    monkeypatch.setattr(eta, "compute_eta_google", _dead)
    monkeypatch.setattr(eta, "compute_eta_osrm", _dead)

    r = _run(eta.compute_eta(33.7897, -112.3226,
                                33.8347, -112.3226))
    assert r.provider == "crowflies"
    assert r.distance_m > 0
    assert r.duration_s > 0


def test_fallback_no_google_key_skips_to_osrm(monkeypatch):
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)

    async def _fake_google(*a, **kw):
        pytest.fail("Google must not be called when key is missing")

    async def _fake_osrm(*a, **kw):
        return eta.ETAResult(provider="osrm",
                              distance_m=8000, duration_s=900)

    monkeypatch.setattr(eta, "compute_eta_google", _fake_google)
    monkeypatch.setattr(eta, "compute_eta_osrm", _fake_osrm)

    r = _run(eta.compute_eta(33.0, -112.0, 34.0, -113.0))
    assert r.provider == "osrm"


def test_compute_eta_always_returns_result(monkeypatch):
    """Contract: even with every provider dead, ``compute_eta`` MUST
    return an ``ETAResult`` — never raise, never return None."""
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)

    async def _dead(*a, **kw):
        return None

    monkeypatch.setattr(eta, "compute_eta_osrm", _dead)
    r = _run(eta.compute_eta(33.0, -112.0, 33.0, -112.0))
    assert isinstance(r, eta.ETAResult)
    assert r.provider in ("google", "osrm", "crowflies")
