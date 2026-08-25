"""Feb-2026 · P2→P0 · Identity-mismatch hotfix regression tests.

Guards ``schedule.py::schedule_today`` and
``route_optimization_approval.py::preview`` against the class of bug
where a tech's ``user.id`` differs from their ``user.technician_id``
and jobs on the tenant use BOTH shapes on ``technician_id``.

The bug hid legitimate jobs from techs. Fix: union both identities in
the tech-visibility ``$or`` clauses.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest


# ─── Fixtures ──────────────────────────────────────────────────────
_TENANT_ID = "tenant-idm-fix"
_USER_ID = "usr-mike-001"
_TECHNICIAN_ID = "tid-mike-001"  # deliberately different from user_id

# 3 jobs on 2026-08-24 with MIXED technician_id shapes — legacy
# rows use user.id, newer rows use user.technician_id. Only the fix
# returns all 3.
_MIXED_JOBS_08_24 = [
    {"id": "j1", "tenant_id": _TENANT_ID,
      "technician_id": _USER_ID,         # legacy shape
      "scheduled_date": "2026-08-24T09:00:00+00:00",
      "status": "scheduled"},
    {"id": "j2", "tenant_id": _TENANT_ID,
      "technician_id": _USER_ID,         # legacy shape
      "scheduled_date": "2026-08-24T11:00:00+00:00",
      "status": "scheduled"},
    {"id": "j3", "tenant_id": _TENANT_ID,
      "technician_id": _TECHNICIAN_ID,   # NEW shape (post-bulk-reassign fix)
      "scheduled_date": "2026-08-24T13:00:00+00:00",
      "status": "scheduled"},
]


def _run(coro):
    return asyncio.run(coro)


# ═══════════════════════════════════════════════════════════════════
# 1 · schedule.py :: schedule_today · union tech identities
# ═══════════════════════════════════════════════════════════════════
def _make_users_find_one(user_doc):
    async def _find_one(q, *_a, **_k):
        if q.get("id") == user_doc["id"]:
            return dict(user_doc)
        return None
    return _find_one


class _AsyncCursor:
    """Minimal Motor cursor stub: supports ``sort()`` chain + ``to_list()``."""
    def __init__(self, rows):
        self._rows = list(rows)
    def sort(self, *_a, **_k):
        return self
    async def to_list(self, _n=None):
        return list(self._rows)
    def __aiter__(self):
        self._i = 0
        return self
    async def __anext__(self):
        if self._i >= len(self._rows):
            raise StopAsyncIteration
        r = self._rows[self._i]
        self._i += 1
        return r


def _build_schedule_today_app_and_stubs(user, jobs, crews=None):
    from fastapi import FastAPI
    from routers.schedule import router as _r
    from utils import get_current_user
    from routers.tenants import get_current_tenant
    from routers import schedule as _mod

    app = FastAPI()
    app.include_router(_r, prefix="/api")
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_current_tenant] = lambda: {
        "id": _TENANT_ID,
        "settings": {"tz": "America/Phoenix"},
    }

    # Only return jobs whose (technician_id / assigned_to /
    # assigned_technician_id) match one of the values in the caller's
    # $in expression. Simulate Mongo semantics faithfully.
    def _job_matches(job, q):
        # $and layer — soft-delete branch is ignored in stubs.
        or_clauses = None
        for cond in q.get("$and", []):
            if "$or" in cond:
                or_clauses = cond["$or"]
                break
        # Top-level $or (tech-visibility).
        top_or = q.get("$or") or []
        for cl in top_or:
            for field, expr in cl.items():
                if isinstance(expr, dict) and "$in" in expr:
                    if job.get(field) in expr["$in"]:
                        return True
                else:
                    if job.get(field) == expr:
                        return True
        # If $and provided the tech-visibility instead, retry against it.
        if not top_or and or_clauses:
            for cl in or_clauses:
                for field, expr in cl.items():
                    if isinstance(expr, dict) and "$in" in expr:
                        if job.get(field) in expr["$in"]:
                            return True
                    else:
                        if job.get(field) == expr:
                            return True
        return False

    def _date_matches(job, q):
        # {"scheduled_date": {"$gte": ..., "$lte": ...}}
        sd_expr = q.get("scheduled_date")
        if not isinstance(sd_expr, dict): return True
        sd = job.get("scheduled_date") or ""
        lo, hi = sd_expr.get("$gte"), sd_expr.get("$lte")
        return (lo is None or sd >= lo) and (hi is None or sd <= hi)

    class _Jobs:
        def find(self, q, *_a, **_k):
            # Feb-2026 · union fix — the tech-visibility $or is now
            # composed under $and. Look there FIRST.
            and_or = None
            for cond in q.get("$and", []):
                if "$or" in cond:
                    and_or = cond["$or"]
                    break
            top_or = q.get("$or")
            # If both exist, our new code puts tech-visibility under
            # $and[0] and NO top-level $or. Legacy code puts it at top.
            def _cl_match(job, or_clauses):
                for cl in or_clauses:
                    for field, expr in cl.items():
                        if isinstance(expr, dict) and "$in" in expr:
                            if job.get(field) in expr["$in"]: return True
                        else:
                            if job.get(field) == expr: return True
                return False
            rows = []
            for j in jobs:
                if j.get("tenant_id") != q.get("tenant_id"): continue
                if not _date_matches(j, q): continue
                # tech-visibility clause — check top_or first, then and_or.
                if top_or is not None:
                    if not _cl_match(j, top_or): continue
                elif and_or is not None:
                    if not _cl_match(j, and_or): continue
                rows.append(j)
            return _AsyncCursor(rows)

    class _Crews:
        def find(self, q, *_a, **_k):
            rows = []
            for c in (crews or []):
                if c.get("tenant_id") != q.get("tenant_id"): continue
                tech_ids = c.get("tech_ids") or []
                tech_ids_q = q.get("tech_ids")
                if isinstance(tech_ids_q, dict) and "$in" in tech_ids_q:
                    if any(tid in tech_ids for tid in tech_ids_q["$in"]):
                        rows.append(c)
                elif tech_ids_q in tech_ids:
                    rows.append(c)
            return _AsyncCursor(rows)

    class _Customers:
        def find(self, *_a, **_k): return _AsyncCursor([])

    class _TimeEntries:
        def find(self, *_a, **_k):
            class _C:
                def sort(self, *_a, **_k): return self
                async def to_list(self, _n): return []
            return _C()

    class _DB:
        @property
        def jobs(self): return _Jobs()
        @property
        def crews(self): return _Crews()
        @property
        def customers(self): return _Customers()
        @property
        def time_entries(self): return _TimeEntries()

    return app, _DB()


def test_schedule_today_unions_user_id_AND_technician_id():
    """The core regression: a tenant with mixed-shape technician_id
    values must return ALL of a tech's jobs — not just the legacy or
    just the newer subset."""
    from httpx import AsyncClient, ASGITransport
    from routers import schedule as _mod

    user = {"id": _USER_ID, "role": "technician",
            "tenant_id": _TENANT_ID, "technician_id": _TECHNICIAN_ID}
    app, db_stub = _build_schedule_today_app_and_stubs(user, _MIXED_JOBS_08_24)

    async def _body():
        with patch.object(_mod, "db", db_stub):
            with patch("routers.customers._resolve_service_note",
                        return_value=None):
                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport,
                                        base_url="http://t") as ac:
                    return await ac.get("/api/schedule/today?date=2026-08-24")
    r = _run(_body())
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["items"]) == 3, (
        f"Expected all 3 mixed-shape jobs to be visible, got "
        f"{len(body['items'])}. Union of user.id + user.technician_id "
        f"is not being applied.")
    ids = sorted(i["id"] for i in body["items"])
    assert ids == ["j1", "j2", "j3"]


def test_schedule_today_still_works_when_only_user_id_shape_exists():
    """Legacy tenant regression — every job uses user.id, none use
    user.technician_id. Result set must equal the raw match count."""
    from httpx import AsyncClient, ASGITransport
    from routers import schedule as _mod

    user = {"id": _USER_ID, "role": "technician",
            "tenant_id": _TENANT_ID, "technician_id": _TECHNICIAN_ID}
    legacy_only = [
        j for j in _MIXED_JOBS_08_24 if j["technician_id"] == _USER_ID
    ]
    app, db_stub = _build_schedule_today_app_and_stubs(user, legacy_only)

    async def _body():
        with patch.object(_mod, "db", db_stub):
            with patch("routers.customers._resolve_service_note",
                        return_value=None):
                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport,
                                        base_url="http://t") as ac:
                    return await ac.get("/api/schedule/today?date=2026-08-24")
    r = _run(_body())
    assert r.status_code == 200
    assert len(r.json()["items"]) == 2


def test_schedule_today_still_works_when_only_technician_id_shape_exists():
    """Fresh tenant regression — every job uses user.technician_id."""
    from httpx import AsyncClient, ASGITransport
    from routers import schedule as _mod

    user = {"id": _USER_ID, "role": "technician",
            "tenant_id": _TENANT_ID, "technician_id": _TECHNICIAN_ID}
    modern_only = [
        j for j in _MIXED_JOBS_08_24 if j["technician_id"] == _TECHNICIAN_ID
    ]
    app, db_stub = _build_schedule_today_app_and_stubs(user, modern_only)

    async def _body():
        with patch.object(_mod, "db", db_stub):
            with patch("routers.customers._resolve_service_note",
                        return_value=None):
                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport,
                                        base_url="http://t") as ac:
                    return await ac.get("/api/schedule/today?date=2026-08-24")
    r = _run(_body())
    assert r.status_code == 200
    assert len(r.json()["items"]) == 1


def test_schedule_today_still_works_when_user_has_no_technician_id():
    """Admin-role or a tech row without a technicians doc — must not
    crash on ``None`` when building the identity union."""
    from httpx import AsyncClient, ASGITransport
    from routers import schedule as _mod

    # No technician_id on the user doc — the None gets filtered out.
    user = {"id": _USER_ID, "role": "technician",
            "tenant_id": _TENANT_ID, "technician_id": None}
    app, db_stub = _build_schedule_today_app_and_stubs(user, _MIXED_JOBS_08_24)

    async def _body():
        with patch.object(_mod, "db", db_stub):
            with patch("routers.customers._resolve_service_note",
                        return_value=None):
                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport,
                                        base_url="http://t") as ac:
                    return await ac.get("/api/schedule/today?date=2026-08-24")
    r = _run(_body())
    assert r.status_code == 200
    # Only legacy-shape jobs match when technician_id is missing.
    assert len(r.json()["items"]) == 2


# ═══════════════════════════════════════════════════════════════════
# 2 · route_optimization_approval.py :: preview · union tech identities
# ═══════════════════════════════════════════════════════════════════
def test_approval_preview_unions_user_id_AND_technician_id():
    """Same regression on the mobile approval-flow preview endpoint."""
    from httpx import AsyncClient, ASGITransport
    from routers import route_optimization_approval as _mod

    from fastapi import FastAPI
    from utils import get_current_user
    app = FastAPI()
    app.include_router(_mod.router, prefix="/api")
    caller = {"id": _USER_ID, "role": "technician",
              "tenant_id": _TENANT_ID, "technician_id": _TECHNICIAN_ID}
    app.dependency_overrides[get_current_user] = lambda: caller

    # Stub _load_day_jobs to capture the tech_user_ids argument the
    # router builds — the union assertion is that BOTH ids are in the
    # list, not just one.
    captured = {"tech_user_ids": None}
    async def _load_stub(tenant_id, tech_user_ids, date):
        captured["tech_user_ids"] = list(tech_user_ids)
        return [j for j in _MIXED_JOBS_08_24
                if j["technician_id"] in tech_user_ids
                and j["scheduled_date"].startswith(date)]

    async def _hydrate_stub(jobs, _tid):
        return [{**j, "lat": 33.6 + i * 0.01, "lng": -112.1}
                for i, j in enumerate(jobs)]

    fake_google = AsyncMock(return_value={
        "ordered_indices": [0, 2, 1],
        "polyline": "", "total_distance_m": 3000, "total_duration_s": 400,
        "legs": [{"distance_m": 1500, "duration_s": 200,
                    "start_address": "", "end_address": ""} for _ in range(2)],
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
                            json={"date": "2026-08-24",
                                    "current_lat": 33.59,
                                    "current_lng": -112.10})
    r = _run(_body())
    assert r.status_code == 200, r.text
    body = r.json()
    # The union list must contain BOTH ids.
    assert captured["tech_user_ids"] is not None
    assert set(captured["tech_user_ids"]) == {_USER_ID, _TECHNICIAN_ID}
    # And the proposed order covers all 3 mixed-shape jobs.
    assert set(body["proposed_order"]) == {"j1", "j2", "j3"}


def test_approval_preview_no_crash_when_user_has_no_technician_id():
    """Same defensive check — admin-role / seed drift shouldn't crash."""
    from httpx import AsyncClient, ASGITransport
    from routers import route_optimization_approval as _mod

    from fastapi import FastAPI
    from utils import get_current_user
    app = FastAPI()
    app.include_router(_mod.router, prefix="/api")
    caller = {"id": _USER_ID, "role": "technician",
              "tenant_id": _TENANT_ID, "technician_id": None}
    app.dependency_overrides[get_current_user] = lambda: caller

    captured = {"tech_user_ids": None}
    async def _load_stub(tenant_id, tech_user_ids, date):
        captured["tech_user_ids"] = list(tech_user_ids)
        return [j for j in _MIXED_JOBS_08_24
                if j["technician_id"] in tech_user_ids]
    async def _hydrate_stub(jobs, _tid):
        return [{**j, "lat": 33.6, "lng": -112.1} for j in jobs]

    async def _body():
        with patch.object(_mod, "_load_day_jobs", new=_load_stub):
            with patch.object(_mod, "_hydrate_geo", new=_hydrate_stub):
                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport,
                                        base_url="http://t") as ac:
                    return await ac.post(
                        "/api/jobs/route-optimization/preview",
                        json={"date": "2026-08-24",
                                "current_lat": 33.59,
                                "current_lng": -112.10})
    r = _run(_body())
    # Legacy-only match — still succeeds without a technician_id.
    assert r.status_code in (200, 404)  # 404 when zero reshuffle-worthy jobs
    assert captured["tech_user_ids"] == [_USER_ID]
