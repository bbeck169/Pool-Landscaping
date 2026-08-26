"""Feb-2026 · ``POST /api/schedule/optimize-route`` response contract.

Locks the canonical response shape emitted by ``routers/route_optimization.py``
per the docstring on ``optimize_route``. These tests mock Google Routes API
v2 at ``services.google_maps.directions.optimize_route`` so no live HTTP is
made and no ``GOOGLE_MAPS_API_KEY`` is required.

Companion to ``test_route_optimization_google_directions.py`` (which asserts
per-leg breakdown + ordering). This file focuses on **every** response
carrying the same 4 canonical keys (``ordered_job_ids``, ``total_distance_m``,
``total_duration_s``, ``algorithm``) plus the algorithm-string ↔ warnings
mapping.

Uses the repo's ``asyncio.run(...)`` convention.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from httpx import AsyncClient, ASGITransport


# ── Small helpers ───────────────────────────────────────────────────
_REQUIRED_KEYS = {
    "ordered_job_ids", "total_distance_m", "total_duration_s", "algorithm",
}


def _run(coro):
    return asyncio.run(coro)


def _build_app(user, tenant, seeded_jobs, route_opt_cache=None):
    """Mirror of the harness in test_route_optimization_google_directions.py
    — kept private so this file stays self-contained if the sibling
    is refactored."""
    from fastapi import FastAPI
    from routers.route_optimization import router as _r
    from utils import get_current_user
    from routers.tenants import get_current_tenant

    app = FastAPI()
    app.include_router(_r, prefix="/api")
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_current_tenant] = lambda: tenant

    class _AsyncCursor:
        def __init__(self, rows): self._rows = rows
        def sort(self, *_a, **_k): return self
        async def to_list(self, _n): return list(self._rows)

    cache = route_opt_cache if route_opt_cache is not None else {}

    class _DB:
        @property
        def users(self):
            class _U:
                async def find_one(self, q, *_a, **_k):
                    if q.get("id") == user["id"]:
                        return dict(user)
                    return None
            return _U()
        @property
        def jobs(self):
            def _find(*_a, **_k): return _AsyncCursor(seeded_jobs)
            class _J: pass
            j = _J(); j.find = _find; return j
        @property
        def route_optimizations(self):
            class _RO:
                async def find_one(self, q, *_a, **_k):
                    return cache.get(q.get("waypoints_hash"))
                async def insert_one(self, doc):
                    cache[doc.get("waypoints_hash")] = dict(doc)
            return _RO()

    return app, _DB()


async def _resolve_stub(j, _tid, **_kw):
    return {"lat": j.get("site_lat"), "lng": j.get("site_lng"),
            "address_source": "customer"}


# ═══════════════════════════════════════════════════════════════════
# 1 · Every response carries the 4 required keys.
# ═══════════════════════════════════════════════════════════════════
def test_response_shape_has_all_required_keys_on_google_success():
    """Google-success path — required keys present, correct types."""
    from routers import route_optimization as _mod

    user = {"id": "u_tech", "role": "technician",
            "tenant_id": "tenant-c1", "technician_id": "t_tech"}
    tenant = {"id": "tenant-c1"}
    jobs = [
        {"id": "j1", "site_lat": 33.60, "site_lng": -112.10,
         "tenant_id": "tenant-c1", "technician_id": "u_tech"},
        {"id": "j2", "site_lat": 33.63, "site_lng": -112.10,
         "tenant_id": "tenant-c1", "technician_id": "u_tech"},
        {"id": "j3", "site_lat": 33.61, "site_lng": -112.10,
         "tenant_id": "tenant-c1", "technician_id": "u_tech"},
    ]
    app, db_stub = _build_app(user, tenant, jobs)

    fake_google = AsyncMock(return_value={
        "ordered_indices": [0, 2, 1],
        "polyline": "",
        "total_distance_m": 3210,
        "total_duration_s": 456,
        "legs": [{"distance_m": 1600, "duration_s": 220,
                  "start_address": "", "end_address": ""},
                 {"distance_m": 1610, "duration_s": 236,
                  "start_address": "", "end_address": ""}],
    })

    async def _body():
        with patch.object(_mod, "db", db_stub):
            with patch("routers.realtime.bus.broadcast", new=AsyncMock()):
                with patch.object(_mod, "resolve_stop_geo",
                                    new=AsyncMock(side_effect=_resolve_stub)):
                    with patch("services.google_maps.directions.optimize_route",
                                fake_google):
                        transport = ASGITransport(app=app)
                        async with AsyncClient(transport=transport,
                                                base_url="http://t") as ac:
                            return await ac.post(
                                "/api/schedule/optimize-route",
                                json={"date": "2026-06-01"},
                            )
    r = _run(_body())
    assert r.status_code == 200, r.text
    body = r.json()

    # Every required key present.
    missing = _REQUIRED_KEYS - set(body.keys())
    assert not missing, f"missing keys: {missing} · body={body}"
    # Types correct.
    assert isinstance(body["ordered_job_ids"], list)
    assert all(isinstance(x, str) for x in body["ordered_job_ids"])
    assert isinstance(body["total_distance_m"], (int, float))
    assert isinstance(body["total_duration_s"], int)
    assert isinstance(body["algorithm"], str)


def test_response_shape_has_all_required_keys_on_haversine_fallback():
    """Google-failure path — required keys still present, correct types."""
    from routers import route_optimization as _mod

    user = {"id": "u_tech", "role": "technician",
            "tenant_id": "tenant-c2", "technician_id": "t_tech"}
    tenant = {"id": "tenant-c2"}
    jobs = [
        {"id": "j1", "site_lat": 33.60, "site_lng": -112.10,
         "tenant_id": "tenant-c2", "technician_id": "u_tech"},
        {"id": "j2", "site_lat": 33.63, "site_lng": -112.10,
         "tenant_id": "tenant-c2", "technician_id": "u_tech"},
    ]
    app, db_stub = _build_app(user, tenant, jobs)

    async def _body():
        with patch.object(_mod, "db", db_stub):
            with patch("routers.realtime.bus.broadcast", new=AsyncMock()):
                with patch.object(_mod, "resolve_stop_geo",
                                    new=AsyncMock(side_effect=_resolve_stub)):
                    with patch("services.google_maps.directions.optimize_route",
                                new=AsyncMock(return_value=None)):
                        transport = ASGITransport(app=app)
                        async with AsyncClient(transport=transport,
                                                base_url="http://t") as ac:
                            return await ac.post(
                                "/api/schedule/optimize-route",
                                json={"date": "2026-06-02"},
                            )
    r = _run(_body())
    assert r.status_code == 200, r.text
    body = r.json()

    missing = _REQUIRED_KEYS - set(body.keys())
    assert not missing, f"missing keys: {missing} · body={body}"
    assert isinstance(body["ordered_job_ids"], list)
    assert isinstance(body["total_distance_m"], (int, float))
    assert isinstance(body["total_duration_s"], int)


# ═══════════════════════════════════════════════════════════════════
# 2 · Algorithm string mapping — Google success + ORION warnings.
# ═══════════════════════════════════════════════════════════════════
def test_algorithm_is_directions_v2_orion_bias_when_orion_emits_warnings():
    """Jobs without ZIP data → ORION appends the "no ZIP data"
    warning → algorithm badge is the composite ``directions_v2+orion_bias``.
    ``ordered_job_ids`` matches Google's returned order (ORION doesn't
    reshuffle when it can't identify same-zip clusters)."""
    from routers import route_optimization as _mod

    user = {"id": "u_tech", "role": "technician",
            "tenant_id": "tenant-c3", "technician_id": "t_tech"}
    tenant = {"id": "tenant-c3"}
    # No ``address``, no ``zip`` on any job → ORION emits the
    # "no ZIP data available" warning, which flips the badge.
    jobs = [
        {"id": "j1", "site_lat": 33.60, "site_lng": -112.10,
         "tenant_id": "tenant-c3", "technician_id": "u_tech"},
        {"id": "j2", "site_lat": 33.63, "site_lng": -112.10,
         "tenant_id": "tenant-c3", "technician_id": "u_tech"},
        {"id": "j3", "site_lat": 33.61, "site_lng": -112.10,
         "tenant_id": "tenant-c3", "technician_id": "u_tech"},
    ]
    app, db_stub = _build_app(user, tenant, jobs)

    fake_google = AsyncMock(return_value={
        "ordered_indices": [0, 2, 1],
        "polyline": "",
        "total_distance_m": 4321,
        "total_duration_s": 550,
        "legs": [{"distance_m": 2000, "duration_s": 250,
                  "start_address": "", "end_address": ""},
                 {"distance_m": 2321, "duration_s": 300,
                  "start_address": "", "end_address": ""}],
    })

    async def _body():
        with patch.object(_mod, "db", db_stub):
            with patch("routers.realtime.bus.broadcast", new=AsyncMock()):
                with patch.object(_mod, "resolve_stop_geo",
                                    new=AsyncMock(side_effect=_resolve_stub)):
                    with patch("services.google_maps.directions.optimize_route",
                                fake_google):
                        transport = ASGITransport(app=app)
                        async with AsyncClient(transport=transport,
                                                base_url="http://t") as ac:
                            return await ac.post(
                                "/api/schedule/optimize-route",
                                json={"date": "2026-06-03"},
                            )
    r = _run(_body())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["algorithm"] == "directions_v2+orion_bias"
    # ``ordered_job_ids`` matches Google's ordered output — ORION
    # doesn't reshuffle when ZIPs are missing, it only warns.
    assert body["ordered_job_ids"] == ["j1", "j3", "j2"]
    # ORION warning made it out to the client so the modal can render
    # the yellow banner.
    assert isinstance(body.get("warnings"), list)
    assert any("zip" in w.lower() for w in body["warnings"]), body["warnings"]


# ═══════════════════════════════════════════════════════════════════
# 3 · Algorithm string mapping — Haversine fallback + warnings.
# ═══════════════════════════════════════════════════════════════════
def test_algorithm_is_haversine_fallback_and_warning_present_on_google_failure():
    """When Google returns None (mocked) the router falls back to
    the pure-Python nearest-neighbour Haversine loop. Locks:
      * ``algorithm == "haversine_fallback"`` (matches source verbatim).
      * ``warnings`` contains the "Directions unavailable" message so
        the client can render its yellow banner.
      * ``ordered_job_ids`` still covers every input job.
    """
    from routers import route_optimization as _mod

    user = {"id": "u_tech", "role": "technician",
            "tenant_id": "tenant-c4", "technician_id": "t_tech"}
    tenant = {"id": "tenant-c4"}
    jobs = [
        {"id": "j1", "site_lat": 33.60, "site_lng": -112.10,
         "tenant_id": "tenant-c4", "technician_id": "u_tech"},
        {"id": "j2", "site_lat": 33.63, "site_lng": -112.10,
         "tenant_id": "tenant-c4", "technician_id": "u_tech"},
        {"id": "j3", "site_lat": 33.61, "site_lng": -112.10,
         "tenant_id": "tenant-c4", "technician_id": "u_tech"},
    ]
    app, db_stub = _build_app(user, tenant, jobs)

    async def _body():
        with patch.object(_mod, "db", db_stub):
            with patch("routers.realtime.bus.broadcast", new=AsyncMock()):
                with patch.object(_mod, "resolve_stop_geo",
                                    new=AsyncMock(side_effect=_resolve_stub)):
                    with patch("services.google_maps.directions.optimize_route",
                                new=AsyncMock(return_value=None)):
                        transport = ASGITransport(app=app)
                        async with AsyncClient(transport=transport,
                                                base_url="http://t") as ac:
                            return await ac.post(
                                "/api/schedule/optimize-route",
                                json={"date": "2026-06-04"},
                            )
    r = _run(_body())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["algorithm"] == "haversine_fallback"
    # Every input job represented in the ordering.
    assert set(body["ordered_job_ids"]) == {"j1", "j2", "j3"}
    # Warnings list carries the exact "Directions unavailable" message
    # documented in the router docstring — the client keys off the
    # substring, so we assert on that substring.
    assert isinstance(body.get("warnings"), list) and body["warnings"]
    joined = " ".join(body["warnings"]).lower()
    assert "directions unavailable" in joined
    assert "haversine" in joined
