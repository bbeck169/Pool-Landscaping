"""Feb-2026 · Task 5 perf — batched distance_matrix_cache lookup.

Pins two contracts on ``routers.schedule.schedule_today``:

1. **Batched leg-cache lookup**: the handler MUST issue a SINGLE
   ``db.distance_matrix_cache.find({key: {$in: [...]}})`` for every
   consecutive-jobs leg on the day — never a sequential per-pair
   ``find_one``.  The pre-Feb-2026 code fanned out N-1 sequential
   round-trips which becomes the dominant cost on schedules of 15+
   jobs when the cache table is hot.
2. **Server-Timing phase probes**: the response carries the phase
   probes (``crews``, ``jobs``, ``custs``, ``entries``, ``legs``) so
   the FE / ops can diagnose prod slowness without redeploying.

Scope: NARROW.  Calls the router handler directly with fully stubbed
Motor collections + a fake ``Request`` so we don't need the full app
boot and don't collide with the neighbour live-DB test suites.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


# ─────────────────────────────────────────────────────────────────────
# Motor stubs — minimal shape needed by ``schedule_today``.
# ─────────────────────────────────────────────────────────────────────
class _Cursor:
    def __init__(self, rows):
        self._rows = rows

    def sort(self, *a, **kw): return self
    def limit(self, *a, **kw): return self
    def __aiter__(self):
        async def _agen():
            for r in self._rows:
                yield r
        return _agen()
    async def to_list(self, _length):
        return list(self._rows)


class _Coll:
    def __init__(self, rows=None):
        self.rows = rows or []
        # Every ``find`` call is recorded so tests can assert on
        # (a) how many calls fired and (b) the filter payload.
        self.find_calls: List[Dict[str, Any]] = []
        self.find_one_calls: List[Dict[str, Any]] = []

    def find(self, filt=None, projection=None):
        self.find_calls.append(dict(filt or {}))
        return _Cursor(self.rows)

    async def find_one(self, filt=None, projection=None):
        self.find_one_calls.append(dict(filt or {}))
        # Return the first row whose key-set intersects the filter.
        for row in self.rows:
            if all(row.get(k) == v for k, v in (filt or {}).items()
                    if not isinstance(v, dict)):
                return row
        return None

    async def count_documents(self, *a, **kw):
        return len(self.rows)


class _DB:
    def __init__(self, *, jobs, custs, dmc):
        self.crews = _Coll(rows=[])
        self.jobs = _Coll(rows=jobs)
        self.customers = _Coll(rows=custs)
        self.time_entries = _Coll(rows=[])
        self.distance_matrix_cache = _Coll(rows=dmc)


def _seed(monkeypatch, *, jobs, custs=None, dmc=None):
    from routers import schedule as sched
    fake = _DB(jobs=jobs, custs=custs or [], dmc=dmc or [])
    monkeypatch.setattr(sched, "db", fake)
    return sched, fake


def _make_request():
    """A minimal stand-in for ``fastapi.Request`` that satisfies the
    ``request.state.timings`` contract the handler + middleware share.
    Middleware isn't in the loop for this unit test, so we seed the
    list here directly."""
    return SimpleNamespace(state=SimpleNamespace(timings=[]))


def _admin_user():
    return {"id": "u-admin", "role": "admin",
            "tenant_id": "t-perf-1", "technician_id": None}


def _tenant():
    return {"id": "t-perf-1", "settings": {"tz": "America/Phoenix"}}


def _mk_job(i: int, *, lat: float, lng: float, date: str) -> dict:
    return {
        "id": f"job-{i}", "tenant_id": "t-perf-1",
        "technician_id": "u-admin", "customer_id": f"cust-{i}",
        "customer_name": f"Customer {i}", "title": "Weekly Service",
        "service_type": "Weekly Service", "job_type": "Weekly Service",
        "scheduled_date": date, "scheduled_end": None,
        "status": "scheduled", "priority": "normal",
        "site_lat": lat, "site_lng": lng, "route_index": i,
        "site_address": f"{i} Main St", "city": "Phoenix", "state": "AZ",
    }


# ═════════════════════════════════════════════════════════════════════
# Test 1 — batched leg cache: 5 jobs → ONE find on distance_matrix_cache
# ═════════════════════════════════════════════════════════════════════
def test_leg_cache_batched_single_find_call(monkeypatch):
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    jobs = [_mk_job(i, lat=33.0+i*0.01, lng=-112.0+i*0.01, date=today)
             for i in range(5)]

    sched, fake = _seed(monkeypatch, jobs=jobs)
    req = _make_request()
    out = _run(sched.schedule_today(
        request=req, date=None, user=_admin_user(), tenant=_tenant(),
    ))
    # 5 jobs → 4 legs → exactly 1 batched find call w/ $in of 4 keys.
    dmc_calls = fake.distance_matrix_cache.find_calls
    assert len(dmc_calls) == 1, f"expected 1 batched find, got {len(dmc_calls)}: {dmc_calls}"
    payload = dmc_calls[0]
    assert "key" in payload and "$in" in payload["key"]
    assert len(payload["key"]["$in"]) == 4
    # No per-pair find_one calls (that was the pre-batch shape).
    assert fake.distance_matrix_cache.find_one_calls == []
    # Response shape preserved — 4 legs emitted.
    assert len(out["route_legs"]) == 4


# ═════════════════════════════════════════════════════════════════════
# Test 2 — leg cache hits + misses hydrate correctly from the batch
# ═════════════════════════════════════════════════════════════════════
def test_leg_cache_hydrates_hits_from_batched_result(monkeypatch):
    from datetime import datetime, timezone
    from routers.schedule import _cache_key
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    jobs = [_mk_job(i, lat=33.0+i*0.01, lng=-112.0+i*0.01, date=today)
             for i in range(3)]
    # Cache the FIRST leg only; second leg intentionally misses.
    key_first = _cache_key(jobs[0]["site_lat"], jobs[0]["site_lng"],
                            jobs[1]["site_lat"], jobs[1]["site_lng"])
    dmc = [{"key": key_first,
              "distance_meters": 12345, "duration_seconds": 678}]

    sched, fake = _seed(monkeypatch, jobs=jobs, dmc=dmc)
    out = _run(sched.schedule_today(
        request=_make_request(), date=None,
        user=_admin_user(), tenant=_tenant(),
    ))
    legs = out["route_legs"]
    assert len(legs) == 2
    # First leg → cache hit.
    assert legs[0]["cached"] is True
    assert legs[0]["distance_meters"] == 12345
    assert legs[0]["duration_seconds"] == 678
    # Second leg → cache miss, distance fields null.
    assert legs[1]["cached"] is False
    assert legs[1]["distance_meters"] is None
    assert legs[1]["duration_seconds"] is None


# ═════════════════════════════════════════════════════════════════════
# Test 3 — no coord jobs → NO cache call at all
# ═════════════════════════════════════════════════════════════════════
def test_leg_cache_skipped_when_no_coord_pairs(monkeypatch):
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    # Jobs w/o coords must not be considered for legs.
    jobs = [{**_mk_job(1, lat=33.0, lng=-112.0, date=today),
              "site_lat": None, "site_lng": None, "lat": None, "lng": None}]

    sched, fake = _seed(monkeypatch, jobs=jobs)
    out = _run(sched.schedule_today(
        request=_make_request(), date=None,
        user=_admin_user(), tenant=_tenant(),
    ))
    assert out["route_legs"] == []
    # ZERO calls to the cache collection when there are no leg pairs.
    assert fake.distance_matrix_cache.find_calls == []
    assert fake.distance_matrix_cache.find_one_calls == []


# ═════════════════════════════════════════════════════════════════════
# Test 4 — Server-Timing phase probes populate request.state.timings
# ═════════════════════════════════════════════════════════════════════
def test_server_timing_probes_populate_request_state(monkeypatch):
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    jobs = [_mk_job(i, lat=33.0+i*0.01, lng=-112.0+i*0.01, date=today)
             for i in range(3)]
    sched, _ = _seed(monkeypatch, jobs=jobs)
    req = _make_request()
    _run(sched.schedule_today(
        request=req, date=None, user=_admin_user(), tenant=_tenant(),
    ))
    labels = [t.split(";")[0] for t in req.state.timings]
    # All 5 phases MUST be present so ops can bisect prod slowness.
    for expected in ("crews", "jobs", "custs", "entries", "legs"):
        assert expected in labels, f"missing phase probe '{expected}' in {labels}"
    # Each probe is a valid Server-Timing token: name;dur=<num>.
    for t in req.state.timings:
        assert ";dur=" in t and t.split(";dur=")[1].replace(".", "", 1).isdigit()
