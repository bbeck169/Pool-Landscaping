"""Phase B · Feb-2026 — ``POST /schedule/optimize-route`` enrichment:
``dropped_job_ids`` + actionable trivial-branch warning.

Operator reported "Optimize Route modal shows 0h 0m · 0.0mi · trivial,
does not reorder" — the trivial branch fires when fewer than 2 jobs
have resolvable coords (``jobs_with_geo < 2``). The underlying data
quality issue is addressed by Phase A.5 (property geocoding backfill).
This phase additionally surfaces the drop set on EVERY response branch
so the Reorder modal can render an actionable yellow banner even on
the trivial envelope.

Covers (6 cases):
  1. Trivial branch (< 2 geocoded) → `dropped_job_ids` carries the
     IDs that had no coords; warning text mentions "Property Geocoding
     Health".
  2. Trivial branch + zero geocoded → `dropped_job_ids` carries all N
     ids; `ordered_job_ids == []`.
  3. Haversine fallback branch → `dropped_job_ids` present (even when
     empty) + reflects any geo-less inputs.
  4. Google-success branch → `dropped_job_ids` present on cache miss.
  5. Cache bypass when `dropped_job_ids` non-empty — second call
     recomputes rather than serving a stale drop set.
  6. Cross-tenant target → 403 (regression guard: new field doesn't
     weaken the existing tenant guard).

Mocks `services.google_maps.directions.optimize_route` so no live
Google traffic.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from httpx import AsyncClient, ASGITransport


def _run(coro):
    return asyncio.run(coro)


def _build_app(user, tenant, seeded_jobs, route_opt_cache=None,
                extra_users=None):
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
        def __aiter__(self):
            self._i = 0; return self
        async def __anext__(self):
            if self._i >= len(self._rows):
                raise StopAsyncIteration
            r = self._rows[self._i]; self._i += 1; return r
        async def to_list(self, _n): return list(self._rows)

    cache = route_opt_cache if route_opt_cache is not None else {}
    _extra = extra_users or {}

    class _DB:
        @property
        def users(self):
            class _U:
                async def find_one(self, q, *_a, **_k):
                    if q.get("id") == user["id"]:
                        return dict(user)
                    if q.get("id") in _extra:
                        return dict(_extra[q["id"]])
                    return None
                def find(self, *_a, **_k):
                    return _AsyncCursor([])
            return _U()
        @property
        def technicians(self):
            class _T:
                async def find_one(self, *_a, **_k): return None
                def find(self, *_a, **_k): return _AsyncCursor([])
            return _T()
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


# ``resolve_stop_geo`` stub: honours whatever site_lat/lng is already
# on the job dict. Jobs without site_lat/site_lng return a None pair
# so they slide into ``dropped_no_coords``.
async def _resolve_stub(j, _tid, **_kw):
    lat = j.get("site_lat")
    lng = j.get("site_lng")
    return {"lat": lat, "lng": lng, "address_source": "customer"}


# ═══════════════════════════════════════════════════════════════════
# 1 · Trivial branch — < 2 geocoded → drop set carries the missing ids
# ═══════════════════════════════════════════════════════════════════


def test_trivial_branch_surfaces_dropped_job_ids_and_actionable_warning():
    from routers import route_optimization as _mod

    user = {"id": "u_tech", "role": "technician",
            "tenant_id": "tenant-pb1", "technician_id": "t1"}
    tenant = {"id": "tenant-pb1"}
    # 1 geocoded, 2 with no coords → trivial branch fires + drop list
    # carries the 2 ids.
    jobs = [
        {"id": "j1", "site_lat": 33.60, "site_lng": -112.10,
         "tenant_id": "tenant-pb1", "technician_id": "u_tech"},
        {"id": "j2", "site_lat": None, "site_lng": None,
         "tenant_id": "tenant-pb1", "technician_id": "u_tech"},
        {"id": "j3", "site_lat": None, "site_lng": None,
         "tenant_id": "tenant-pb1", "technician_id": "u_tech"},
    ]
    app, db_stub, _ = _build_app(user, tenant, jobs)

    async def _body():
        with patch.object(_mod, "db", db_stub):
            with patch("routers.realtime.bus.broadcast", new=AsyncMock()):
                with patch.object(_mod, "resolve_stop_geo",
                                    new=AsyncMock(side_effect=_resolve_stub)):
                    transport = ASGITransport(app=app)
                    async with AsyncClient(transport=transport,
                                            base_url="http://t") as ac:
                        return await ac.post(
                            "/api/schedule/optimize-route",
                            json={"date": "2026-06-10"},
                        )
    r = _run(_body())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["algorithm"] == "trivial"
    assert body["total_distance_m"] == 0
    assert body["total_duration_s"] == 0
    # The 2 geo-less jobs land in the drop set.
    assert set(body["dropped_job_ids"]) == {"j2", "j3"}, body
    # Only the geocoded job rides the ordered list.
    assert body["ordered_job_ids"] == ["j1"], body
    # Warning text points operators at the Phase A.5 remediation UI.
    joined = " ".join(body.get("warnings") or [])
    assert "Property Geocoding Health" in joined, joined


# ═══════════════════════════════════════════════════════════════════
# 2 · Trivial branch — zero geocoded → all N ids dropped
# ═══════════════════════════════════════════════════════════════════


def test_trivial_branch_zero_geocoded_drops_all_jobs():
    from routers import route_optimization as _mod

    user = {"id": "u_tech", "role": "technician",
            "tenant_id": "tenant-pb2", "technician_id": "t2"}
    tenant = {"id": "tenant-pb2"}
    jobs = [
        {"id": "j1", "site_lat": None, "site_lng": None,
         "tenant_id": "tenant-pb2", "technician_id": "u_tech"},
        {"id": "j2", "site_lat": None, "site_lng": None,
         "tenant_id": "tenant-pb2", "technician_id": "u_tech"},
    ]
    app, db_stub, _ = _build_app(user, tenant, jobs)

    async def _body():
        with patch.object(_mod, "db", db_stub):
            with patch("routers.realtime.bus.broadcast", new=AsyncMock()):
                with patch.object(_mod, "resolve_stop_geo",
                                    new=AsyncMock(side_effect=_resolve_stub)):
                    transport = ASGITransport(app=app)
                    async with AsyncClient(transport=transport,
                                            base_url="http://t") as ac:
                        return await ac.post(
                            "/api/schedule/optimize-route",
                            json={"date": "2026-06-11"},
                        )
    r = _run(_body())
    body = r.json()
    assert body["algorithm"] == "trivial"
    assert body["ordered_job_ids"] == []
    assert set(body["dropped_job_ids"]) == {"j1", "j2"}


# ═══════════════════════════════════════════════════════════════════
# 3 · Haversine-fallback branch — dropped_job_ids present
# ═══════════════════════════════════════════════════════════════════


def test_haversine_fallback_includes_dropped_job_ids_field():
    from routers import route_optimization as _mod

    user = {"id": "u_tech", "role": "technician",
            "tenant_id": "tenant-pb3", "technician_id": "t3"}
    tenant = {"id": "tenant-pb3"}
    # 2 geocoded + 1 geo-less → Haversine branch runs on the 2
    # geocoded + drops the 1.
    jobs = [
        {"id": "j1", "site_lat": 33.60, "site_lng": -112.10,
         "tenant_id": "tenant-pb3", "technician_id": "u_tech"},
        {"id": "j2", "site_lat": 33.63, "site_lng": -112.10,
         "tenant_id": "tenant-pb3", "technician_id": "u_tech"},
        {"id": "j3", "site_lat": None, "site_lng": None,
         "tenant_id": "tenant-pb3", "technician_id": "u_tech"},
    ]
    app, db_stub, _ = _build_app(user, tenant, jobs)

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
                                json={"date": "2026-06-12"},
                            )
    r = _run(_body())
    body = r.json()
    assert body["algorithm"] == "haversine_fallback"
    assert "dropped_job_ids" in body
    assert body["dropped_job_ids"] == ["j3"], body
    assert set(body["ordered_job_ids"]) == {"j1", "j2"}


# ═══════════════════════════════════════════════════════════════════
# 4 · Google-success branch — dropped_job_ids present on cache miss
# ═══════════════════════════════════════════════════════════════════


def test_google_success_includes_dropped_job_ids_field():
    from routers import route_optimization as _mod

    user = {"id": "u_tech", "role": "technician",
            "tenant_id": "tenant-pb4", "technician_id": "t4"}
    tenant = {"id": "tenant-pb4"}
    jobs = [
        {"id": "j1", "site_lat": 33.60, "site_lng": -112.10,
         "tenant_id": "tenant-pb4", "technician_id": "u_tech"},
        {"id": "j2", "site_lat": 33.63, "site_lng": -112.10,
         "tenant_id": "tenant-pb4", "technician_id": "u_tech"},
    ]
    app, db_stub, _ = _build_app(user, tenant, jobs)

    fake_google = AsyncMock(return_value={
        "ordered_indices": [1, 0],
        "polyline": "",
        "total_distance_m": 5000,
        "total_duration_s": 600,
        "legs": [{"distance_m": 5000, "duration_s": 600,
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
                                json={"date": "2026-06-13"},
                            )
    r = _run(_body())
    body = r.json()
    assert body["algorithm"] == "directions_v2+orion_bias"
    assert "dropped_job_ids" in body
    assert body["dropped_job_ids"] == []


# ═══════════════════════════════════════════════════════════════════
# 5 · Cache bypass when dropped_job_ids non-empty
# ═══════════════════════════════════════════════════════════════════


def test_cache_bypassed_when_dropped_job_ids_non_empty():
    from routers import route_optimization as _mod

    user = {"id": "u_tech", "role": "technician",
            "tenant_id": "tenant-pb5", "technician_id": "t5"}
    tenant = {"id": "tenant-pb5"}
    jobs = [
        {"id": "j1", "site_lat": 33.60, "site_lng": -112.10,
         "tenant_id": "tenant-pb5", "technician_id": "u_tech"},
        {"id": "j2", "site_lat": 33.63, "site_lng": -112.10,
         "tenant_id": "tenant-pb5", "technician_id": "u_tech"},
        {"id": "j3", "site_lat": None, "site_lng": None,
         "tenant_id": "tenant-pb5", "technician_id": "u_tech"},
    ]
    cache = {}
    app, db_stub, cache = _build_app(user, tenant, jobs,
                                       route_opt_cache=cache)

    # Pre-seed a stale cache entry at the same waypoints_hash so a
    # successful cache hit would otherwise short-circuit the branch
    # that recomputes dropped_job_ids. The cache row contains
    # ``dropped_job_ids: []`` — i.e. a pre-Phase-B stale row. If
    # cache-bypass works, the response we observe will NOT be this
    # stale row; it will have ``dropped_job_ids == ["j3"]``.
    import hashlib
    h = hashlib.sha256("j1|j2|None|None".encode()).hexdigest()[:16]
    cache[h] = {
        "ordered_job_ids": ["j1", "j2"],
        "total_distance_m": 999, "total_duration_s": 999,
        "legs": [], "algorithm": "stale-cache-marker",
        "dropped_job_ids": [], "cached": True,
        "waypoints_hash": h,
    }

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
                                json={"date": "2026-06-14"},
                            )
    r = _run(_body())
    body = r.json()
    # Cache would have returned "stale-cache-marker"; a cache bypass
    # recomputes via Haversine.
    assert body["algorithm"] != "stale-cache-marker", body
    assert body["dropped_job_ids"] == ["j3"]


# ═══════════════════════════════════════════════════════════════════
# 6 · Cross-tenant target → 403 (new field doesn't weaken guard)
# ═══════════════════════════════════════════════════════════════════


def test_cross_tenant_target_still_403_after_phase_b_enrichment():
    from routers import route_optimization as _mod

    user = {"id": "u_admin", "role": "admin",
            "tenant_id": "tenant-pb6"}
    tenant = {"id": "tenant-pb6"}
    # Target user is in a DIFFERENT tenant → guard must still fire.
    cross_user = {"id": "u_other", "tenant_id": "tenant-OTHER",
                  "technician_id": "t_other"}
    jobs = []
    app, db_stub, _ = _build_app(
        user, tenant, jobs, extra_users={"u_other": cross_user},
    )

    async def _body():
        with patch.object(_mod, "db", db_stub):
            with patch("routers.realtime.bus.broadcast", new=AsyncMock()):
                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport,
                                        base_url="http://t") as ac:
                    return await ac.post(
                        "/api/schedule/optimize-route",
                        json={"date": "2026-06-15",
                              "technician_id": "u_other"},
                    )
    r = _run(_body())
    assert r.status_code == 403, r.text
