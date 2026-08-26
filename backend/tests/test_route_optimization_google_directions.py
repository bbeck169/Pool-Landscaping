"""Feb-2026 · Google Directions optimizer swap — dual-endpoint unit tests.

Covers the shared helper ``services.route_optimizer.compute_optimization_v2``
+ its integration into BOTH router surfaces:

  * POST /api/schedule/optimize-route          (route_optimization.py)
  * POST /api/jobs/route-optimization/preview  (route_optimization_approval.py)

Google Routes API is mocked at the ``services.google_maps.directions``
edge so no live HTTP call is made and no ``GOOGLE_MAPS_API_KEY`` is
required to run the suite.

Uses the repo's ``asyncio.run(...)`` convention (see ``test_aeo.py``,
``test_keyword_ideator.py``) rather than ``pytest-asyncio``.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from services.route_optimizer import (
    GOOGLE_DIRECTIONS_MAX_WAYPOINTS,
    compute_optimization,
    compute_optimization_v2,
    try_google_directions_optimize,
)


# ── Fixtures ─────────────────────────────────────────────────────────
def _job(jid: str, lat: float, lng: float, status: str = "scheduled") -> dict:
    return {"id": jid, "status": status, "lat": lat, "lng": lng}


# 5 stops in current order — Google-optimal is [j1, j3, j2, j5, j4]
# per the mock return value below (chosen so it differs from input).
_JOBS_5 = [
    _job("j1", 33.60, -112.10),
    _job("j2", 33.63, -112.10),
    _job("j3", 33.61, -112.10),
    _job("j4", 33.65, -112.10),
    _job("j5", 33.64, -112.10),
]
_START_LAT, _START_LNG = 33.59, -112.10


def _run(coro):
    """Wrapper for the repo's asyncio.run(...) convention."""
    return asyncio.run(coro)


# ═══════════════════════════════════════════════════════════════════
# 1 · Shared helper — try_google_directions_optimize
# ═══════════════════════════════════════════════════════════════════
def test_try_google_directions_returns_ordered_waypoints_on_success():
    fake = AsyncMock(return_value={
        "ordered_indices": [0, 2, 1, 4, 3],
        "polyline": "abcdefg",
        "total_distance_m": 3210,
        "total_duration_s": 456,
        "legs": [
            {"distance_m": 500, "duration_s": 60, "start_address": "", "end_address": ""},
            {"distance_m": 700, "duration_s": 90, "start_address": "", "end_address": ""},
            {"distance_m": 800, "duration_s": 96, "start_address": "", "end_address": ""},
            {"distance_m": 1210, "duration_s": 210, "start_address": "", "end_address": ""},
        ],
    })
    async def _body():
        with patch("services.google_maps.directions.optimize_route", fake):
            return await try_google_directions_optimize(
                start_lat=_START_LAT, start_lng=_START_LNG,
                waypoints=_JOBS_5,
            )
    result = _run(_body())
    assert result is not None
    assert [w["id"] for w in result["ordered_waypoints"]] == ["j1", "j3", "j2", "j5", "j4"]
    assert result["total_distance_m"] == 3210
    assert result["total_duration_s"] == 456
    assert result["total_miles"] == pytest.approx(3210 / 1609.344)
    assert result["total_minutes"] == pytest.approx(456 / 60)


def test_try_google_directions_returns_none_on_over_25_waypoints():
    """Helper short-circuits — never even calls Google when >25."""
    over_limit = [_job(f"j{i}", 33.0 + i * 0.01, -112.0) for i in range(26)]
    fake = AsyncMock()
    async def _body():
        with patch("services.google_maps.directions.optimize_route", fake):
            return await try_google_directions_optimize(
                start_lat=_START_LAT, start_lng=_START_LNG,
                waypoints=over_limit,
            )
    result = _run(_body())
    assert result is None
    fake.assert_not_called()


def test_try_google_directions_returns_none_on_api_failure():
    fake = AsyncMock(return_value=None)  # httpx error → None per wrapper contract
    async def _body():
        with patch("services.google_maps.directions.optimize_route", fake):
            return await try_google_directions_optimize(
                start_lat=_START_LAT, start_lng=_START_LNG,
                waypoints=_JOBS_5,
            )
    assert _run(_body()) is None


# ═══════════════════════════════════════════════════════════════════
# 2 · compute_optimization_v2 — algorithm badge + fallback
# ═══════════════════════════════════════════════════════════════════
def test_compute_v2_success_badges_google_directions():
    fake = AsyncMock(return_value={
        "ordered_indices": [0, 2, 1, 4, 3],
        "polyline": "", "total_distance_m": 5000, "total_duration_s": 900,
        "legs": [{"distance_m": 1000, "duration_s": 200,
                    "start_address": "", "end_address": ""} for _ in range(4)],
    })
    async def _body():
        with patch("services.google_maps.directions.optimize_route", fake):
            return await compute_optimization_v2(
                current_order_jobs=_JOBS_5,
                start_lat=_START_LAT, start_lng=_START_LNG,
            )
    result = _run(_body())
    assert result["algorithm"] == "google_directions"
    assert result["proposed_order"] == ["j1", "j3", "j2", "j5", "j4"]
    assert result["no_change"] is False
    assert result["stops_affected"] >= 2


def test_compute_v2_falls_back_to_haversine_on_google_failure():
    fake = AsyncMock(return_value=None)
    async def _body():
        with patch("services.google_maps.directions.optimize_route", fake):
            return await compute_optimization_v2(
                current_order_jobs=_JOBS_5,
                start_lat=_START_LAT, start_lng=_START_LNG,
            )
    result = _run(_body())
    assert result["algorithm"] == "haversine_fallback"
    # Same response shape as compute_optimization — proposed_order populated.
    assert isinstance(result["proposed_order"], list)
    assert set(result["proposed_order"]) == {j["id"] for j in _JOBS_5}
    fake.assert_awaited_once()


def test_compute_v2_trivial_case_badges_haversine_fallback():
    """<2 reshufflable stops never calls Google — badges fallback."""
    fake = AsyncMock()
    async def _body():
        with patch("services.google_maps.directions.optimize_route", fake):
            return await compute_optimization_v2(
                current_order_jobs=[_job("only", 33.5, -112.0)],
                start_lat=_START_LAT, start_lng=_START_LNG,
            )
    result = _run(_body())
    assert result["algorithm"] == "haversine_fallback"
    fake.assert_not_called()


def test_compute_v2_preserves_pinned_slots():
    """Completed / skipped stops keep their route_index; only
    reshufflable stops go through Google."""
    jobs = [
        _job("j1", 33.60, -112.10),
        _job("j2", 33.63, -112.10, status="completed"),  # PINNED at slot 1
        _job("j3", 33.61, -112.10),
        _job("j4", 33.65, -112.10),
    ]
    # Google reorders the 3 reshufflables ([j1, j3, j4]) as [j3, j1, j4].
    fake = AsyncMock(return_value={
        "ordered_indices": [1, 0, 2],
        "polyline": "", "total_distance_m": 4000, "total_duration_s": 700,
        "legs": [{"distance_m": 1300, "duration_s": 230,
                    "start_address": "", "end_address": ""} for _ in range(3)],
    })
    async def _body():
        with patch("services.google_maps.directions.optimize_route", fake):
            return await compute_optimization_v2(
                current_order_jobs=jobs,
                start_lat=_START_LAT, start_lng=_START_LNG,
            )
    result = _run(_body())
    assert result["algorithm"] == "google_directions"
    # j2 stays pinned at index 1; reshufflables fill the other three slots.
    assert result["proposed_order"][1] == "j2"
    assert set(result["pinned_ids"]) == {"j2"}
    non_pinned_positions = [
        result["proposed_order"][i] for i in range(len(result["proposed_order"]))
        if i != 1
    ]
    assert set(non_pinned_positions) == {"j1", "j3", "j4"}


# ═══════════════════════════════════════════════════════════════════
# 3 · route_optimization.py — full router with mocked Directions.
# ═══════════════════════════════════════════════════════════════════
def _build_app_for_route_optimization(user, tenant, seeded_jobs,
                                        route_opt_cache=None):
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

    return app, _DB(), cache


def test_router_optimize_route_badges_algorithm_field():
    from httpx import AsyncClient, ASGITransport
    from routers import route_optimization as _mod

    user = {"id": "u_tech", "role": "technician",
            "tenant_id": "tenant-a", "technician_id": "t_tech"}
    tenant = {"id": "tenant-a"}
    seeded_jobs = [
        {"id": "j1", "site_lat": 33.60, "site_lng": -112.10,
          "tenant_id": "tenant-a", "technician_id": "u_tech"},
        {"id": "j2", "site_lat": 33.63, "site_lng": -112.10,
          "tenant_id": "tenant-a", "technician_id": "u_tech"},
        {"id": "j3", "site_lat": 33.61, "site_lng": -112.10,
          "tenant_id": "tenant-a", "technician_id": "u_tech"},
    ]
    app, db_stub, cache = _build_app_for_route_optimization(
        user, tenant, seeded_jobs)

    fake_google = AsyncMock(return_value={
        "ordered_indices": [0, 2, 1],
        "polyline": "", "total_distance_m": 4321,
        "total_duration_s": 550,
        "legs": [{"distance_m": 2000, "duration_s": 250,
                    "start_address": "", "end_address": ""},
                 {"distance_m": 2321, "duration_s": 300,
                    "start_address": "", "end_address": ""}],
    })
    async def _resolve_stub(j, _tid, **_kw):
        return {"lat": j.get("site_lat"), "lng": j.get("site_lng"),
                "address_source": "customer"}

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
                            r1 = await ac.post("/api/schedule/optimize-route",
                                                json={"date": "2026-05-01"})
                            r2 = await ac.post("/api/schedule/optimize-route",
                                                json={"date": "2026-05-01"})
                        return r1, r2, fake_google.await_count
    r1, r2, first_pass_calls = _run(_body())

    assert r1.status_code == 200, r1.text
    body1 = r1.json()
    # Feb-2026 · Router now always runs the ORION zip-cluster pass —
    # when jobs have no ZIP data the pass emits an informational
    # warning, which flips the badge from "google_directions" to
    # "directions_v2+orion_bias". These seeded jobs have no addresses
    # so the missing-ZIP warning fires and the composite badge is
    # canonical. See routers/route_optimization.py response contract.
    assert body1["algorithm"] == "directions_v2+orion_bias"
    assert body1["ordered_job_ids"] == ["j1", "j3", "j2"]
    assert body1["total_distance_m"] == 4321
    assert body1["total_duration_s"] == 550
    assert body1["cached"] is False

    # Second call — cache hit, Google was only called once total.
    assert r2.status_code == 200
    body2 = r2.json()
    assert body2["cached"] is True
    assert body2["algorithm"] == "directions_v2+orion_bias"
    assert first_pass_calls == 1


def test_router_optimize_route_falls_back_to_haversine_on_google_failure():
    from httpx import AsyncClient, ASGITransport
    from routers import route_optimization as _mod

    user = {"id": "u_tech", "role": "technician",
            "tenant_id": "tenant-b", "technician_id": "t_tech"}
    tenant = {"id": "tenant-b"}
    seeded_jobs = [
        {"id": "j1", "site_lat": 33.60, "site_lng": -112.10,
          "tenant_id": "tenant-b", "technician_id": "u_tech"},
        {"id": "j2", "site_lat": 33.63, "site_lng": -112.10,
          "tenant_id": "tenant-b", "technician_id": "u_tech"},
    ]
    app, db_stub, _ = _build_app_for_route_optimization(
        user, tenant, seeded_jobs)

    async def _resolve_stub(j, _tid, **_kw):
        return {"lat": j.get("site_lat"), "lng": j.get("site_lng"),
                "address_source": "customer"}

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
                            return await ac.post("/api/schedule/optimize-route",
                                                    json={"date": "2026-05-02"})
    r = _run(_body())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["algorithm"] == "haversine_fallback"
    assert set(body["ordered_job_ids"]) == {"j1", "j2"}


def test_router_optimize_route_over_25_waypoints_returns_400():
    from httpx import AsyncClient, ASGITransport
    from routers import route_optimization as _mod

    user = {"id": "u_tech", "role": "technician",
            "tenant_id": "tenant-c", "technician_id": "t_tech"}
    tenant = {"id": "tenant-c"}
    over_limit_jobs = [
        {"id": f"j{i}", "site_lat": 33.60 + i * 0.001,
          "site_lng": -112.10, "tenant_id": "tenant-c",
          "technician_id": "u_tech"} for i in range(26)
    ]
    app, db_stub, _ = _build_app_for_route_optimization(
        user, tenant, over_limit_jobs)

    async def _resolve_stub(j, _tid, **_kw):
        return {"lat": j.get("site_lat"), "lng": j.get("site_lng"),
                "address_source": "customer"}

    async def _body():
        with patch.object(_mod, "db", db_stub):
            with patch.object(_mod, "resolve_stop_geo",
                                new=AsyncMock(side_effect=_resolve_stub)):
                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport,
                                        base_url="http://t") as ac:
                    return await ac.post("/api/schedule/optimize-route",
                                            json={"date": "2026-05-03"})
    r = _run(_body())
    assert r.status_code == 400, r.text
    detail = r.json().get("detail") or {}
    assert detail.get("code") == "too_many_stops"
    assert detail.get("max_waypoints") == GOOGLE_DIRECTIONS_MAX_WAYPOINTS
    assert detail.get("actual") == 26


# ═══════════════════════════════════════════════════════════════════
# 4 · route_optimization_approval.py — preview endpoint contract.
# ═══════════════════════════════════════════════════════════════════
def _build_app_for_approval(user):
    from fastapi import FastAPI
    from routers.route_optimization_approval import router as _r
    from utils import get_current_user

    app = FastAPI()
    app.include_router(_r, prefix="/api")
    app.dependency_overrides[get_current_user] = lambda: user
    return app


def test_approval_preview_carries_algorithm_field_on_google_success():
    from httpx import AsyncClient, ASGITransport
    from routers import route_optimization_approval as _mod

    user = {"id": "u_tech", "role": "technician", "tenant_id": "tenant-d"}
    app = _build_app_for_approval(user)

    seeded_jobs = [
        {"id": "j1", "status": "scheduled", "lat": 33.60, "lng": -112.10,
          "tenant_id": "tenant-d", "tech_user_id": "u_tech"},
        {"id": "j2", "status": "scheduled", "lat": 33.63, "lng": -112.10,
          "tenant_id": "tenant-d", "tech_user_id": "u_tech"},
        {"id": "j3", "status": "scheduled", "lat": 33.61, "lng": -112.10,
          "tenant_id": "tenant-d", "tech_user_id": "u_tech"},
    ]

    async def _load_stub(*_a, **_k): return seeded_jobs
    async def _hydrate_stub(jobs, _tid): return [{**j} for j in jobs]

    fake_google = AsyncMock(return_value={
        "ordered_indices": [0, 2, 1],
        "polyline": "", "total_distance_m": 4200,
        "total_duration_s": 540,
        "legs": [{"distance_m": 2000, "duration_s": 250,
                    "start_address": "", "end_address": ""},
                 {"distance_m": 2200, "duration_s": 290,
                    "start_address": "", "end_address": ""}],
    })

    async def _body():
        with patch.object(_mod, "_load_day_jobs", new=_load_stub):
            with patch.object(_mod, "_hydrate_geo", new=_hydrate_stub):
                with patch("services.google_maps.directions.optimize_route",
                            fake_google):
                    transport = ASGITransport(app=app)
                    async with AsyncClient(transport=transport,
                                            base_url="http://t") as ac:
                        return await ac.post(
                            "/api/jobs/route-optimization/preview",
                            json={"date": "2026-05-01",
                                    "current_lat": 33.59,
                                    "current_lng": -112.10})
    r = _run(_body())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["algorithm"] == "google_directions"
    assert body["proposed_order"] == ["j1", "j3", "j2"]
    # Response contract preserved.
    assert "estimated_miles_saved" in body
    assert "estimated_minutes_saved" in body
    assert body["origin"]["source"] == "device_gps"


def test_approval_preview_over_25_reshufflable_returns_400():
    from httpx import AsyncClient, ASGITransport
    from routers import route_optimization_approval as _mod

    user = {"id": "u_tech", "role": "technician", "tenant_id": "tenant-e"}
    app = _build_app_for_approval(user)

    over_limit = [
        {"id": f"j{i}", "status": "scheduled",
          "lat": 33.60 + i * 0.001, "lng": -112.10,
          "tenant_id": "tenant-e", "tech_user_id": "u_tech"}
        for i in range(26)
    ]

    async def _load_stub(*_a, **_k): return over_limit
    async def _hydrate_stub(jobs, _tid): return [{**j} for j in jobs]

    async def _body():
        with patch.object(_mod, "_load_day_jobs", new=_load_stub):
            with patch.object(_mod, "_hydrate_geo", new=_hydrate_stub):
                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport,
                                        base_url="http://t") as ac:
                    return await ac.post(
                        "/api/jobs/route-optimization/preview",
                        json={"date": "2026-05-02",
                                "current_lat": 33.59,
                                "current_lng": -112.10})
    r = _run(_body())
    assert r.status_code == 400, r.text
    detail = r.json().get("detail") or {}
    assert detail.get("code") == "too_many_stops"
    assert detail.get("max_waypoints") == GOOGLE_DIRECTIONS_MAX_WAYPOINTS
    assert detail.get("actual") == 26


def test_approval_preview_falls_back_to_haversine_on_google_failure():
    from httpx import AsyncClient, ASGITransport
    from routers import route_optimization_approval as _mod

    user = {"id": "u_tech", "role": "technician", "tenant_id": "tenant-f"}
    app = _build_app_for_approval(user)

    seeded_jobs = [
        {"id": "j1", "status": "scheduled", "lat": 33.60, "lng": -112.10,
          "tenant_id": "tenant-f", "tech_user_id": "u_tech"},
        {"id": "j2", "status": "scheduled", "lat": 33.63, "lng": -112.10,
          "tenant_id": "tenant-f", "tech_user_id": "u_tech"},
        {"id": "j3", "status": "scheduled", "lat": 33.61, "lng": -112.10,
          "tenant_id": "tenant-f", "tech_user_id": "u_tech"},
    ]

    async def _load_stub(*_a, **_k): return seeded_jobs
    async def _hydrate_stub(jobs, _tid): return [{**j} for j in jobs]

    async def _body():
        with patch.object(_mod, "_load_day_jobs", new=_load_stub):
            with patch.object(_mod, "_hydrate_geo", new=_hydrate_stub):
                # Google helper returns None → helper falls back to Haversine.
                with patch("services.google_maps.directions.optimize_route",
                            new=AsyncMock(return_value=None)):
                    transport = ASGITransport(app=app)
                    async with AsyncClient(transport=transport,
                                            base_url="http://t") as ac:
                        return await ac.post(
                            "/api/jobs/route-optimization/preview",
                            json={"date": "2026-05-04",
                                    "current_lat": 33.59,
                                    "current_lng": -112.10})
    r = _run(_body())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["algorithm"] == "haversine_fallback"
    assert set(body["proposed_order"]) == {"j1", "j2", "j3"}
