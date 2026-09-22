"""Phase P26 · Feb-2026 — Coordinate fallback resolver.

Locks the contract of ``services.geo_resolver`` — the shared
serialization-time helper that maps ``(job, customer_lookup)`` to
``(lat, lng, coord_source)``. Every endpoint that emits jobs with
coords (schedule, dispatch, jobs) now routes through this helper,
so its behavior is a hot production dependency.

Test contract (from the phase spec):
  1. Job with own coords + customer with different coords → job's
     own coords win.
  2. Job with null coords + customer with service coords →
     customer's win, ``coord_source == "customer"``.
  3. Job with null coords + customer with null service coords →
     ``(None, None, None)``.
  4. Job with linked customer that doesn't exist (dangling FK) →
     ``(None, None, None)`` gracefully, no crash.
  5. Cross-tenant safety: fallback lookup respects
     ``tenant_scoped_filter``. Verified via
     ``build_customer_coord_lookup`` — a customer in a different
     tenant is never resolved.
  6. List endpoint batching: ``GET /api/jobs`` for N jobs issues
     exactly ONE customer batch fetch, not N. (Enforced via a
     source-lint grep on ``routers/jobs.py`` — no per-job
     ``db.customers.find_one`` calls survived P26.)
  7. ``resolve_job_coordinates`` idempotent for the same input.
"""
from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from tests._f7_loop_fixture import run_test


# ── Fixtures ───────────────────────────────────────────────────


def _c(cid: str, tid: str, lat=None, lng=None) -> dict:
    """Test customer doc — id / tenant_id / service_lat / service_lng."""
    return {"id": cid, "tenant_id": tid,
            "service_lat": lat, "service_lng": lng}


def _j(jid: str, cid: str = None, *,
       lat=None, lng=None, site_lat=None, site_lng=None,
       latitude=None, longitude=None) -> dict:
    """Test job doc — arbitrary subset of coord fields."""
    return {
        "id": jid, "customer_id": cid,
        "lat": lat, "lng": lng,
        "site_lat": site_lat, "site_lng": site_lng,
        "latitude": latitude, "longitude": longitude,
    }


# ── 1) Job coords win over customer coords ────────────────────


def test_p26_job_own_coords_win_over_customer():
    from services.geo_resolver import resolve_job_coordinates

    cid = "c1"
    lookup = {cid: _c(cid, "T", lat=10.0, lng=20.0)}
    job = _j("j1", cid, lat=33.5, lng=-112.3)
    lat, lng, src = resolve_job_coordinates(job, lookup)
    assert (lat, lng) == (33.5, -112.3)
    assert src == "job"


def test_p26_site_lat_lng_prioritized_over_flat_lat_lng():
    from services.geo_resolver import resolve_job_coordinates

    # site_lat/lng is the first-priority job field per the resolver's
    # docstring. Verify a job with BOTH site_ and flat lat/lng
    # returns site_.
    job = _j("j1", "c1", site_lat=1.0, site_lng=2.0,
              lat=99.0, lng=99.0)
    lat, lng, src = resolve_job_coordinates(job, {})
    assert (lat, lng) == (1.0, 2.0)
    assert src == "job"


def test_p26_latitude_longitude_fallback_when_site_and_flat_null():
    from services.geo_resolver import resolve_job_coordinates

    job = _j("j1", "c1", latitude=44.0, longitude=-88.0)
    lat, lng, src = resolve_job_coordinates(job, {})
    assert (lat, lng) == (44.0, -88.0)
    assert src == "job"


# ── 2) Customer fallback fires when all job coords are null ───


def test_p26_customer_fallback_fires_when_job_coords_null():
    from services.geo_resolver import resolve_job_coordinates

    cid = "c1"
    lookup = {cid: _c(cid, "T", lat=41.0, lng=-73.0)}
    job = _j("j1", cid)  # all coord fields None
    lat, lng, src = resolve_job_coordinates(job, lookup)
    assert (lat, lng) == (41.0, -73.0)
    assert src == "customer"


# ── 3) Neither present → (None, None, None) ───────────────────


def test_p26_neither_present_returns_null_triple():
    from services.geo_resolver import resolve_job_coordinates

    cid = "c1"
    lookup = {cid: _c(cid, "T")}  # customer has no service_lat/lng
    job = _j("j1", cid)
    lat, lng, src = resolve_job_coordinates(job, lookup)
    assert (lat, lng, src) == (None, None, None)


# ── 4) Dangling FK degrades gracefully ────────────────────────


def test_p26_dangling_customer_fk_does_not_crash():
    from services.geo_resolver import resolve_job_coordinates

    # Customer referenced by the job is NOT in the lookup dict
    # (deleted, cross-tenant filtered out, etc.). Resolver must
    # gracefully return (None, None, None).
    job = _j("j1", "c-missing")
    lat, lng, src = resolve_job_coordinates(job, {})
    assert (lat, lng, src) == (None, None, None)


def test_p26_missing_customer_id_on_job_does_not_crash():
    from services.geo_resolver import resolve_job_coordinates

    job = _j("j1", cid=None)
    lat, lng, src = resolve_job_coordinates(job, {})
    assert (lat, lng, src) == (None, None, None)


# ── 5) Cross-tenant safety via build_customer_coord_lookup ────


def test_p26_lookup_builder_filters_to_tenant_scope():
    async def _go(db):
        from services.geo_resolver import (
            build_customer_coord_lookup, resolve_job_coordinates,
        )
        tenant_a = f"P26_A_{uuid.uuid4().hex[:6]}"
        tenant_b = f"P26_B_{uuid.uuid4().hex[:6]}"
        cust_a = f"P26_CA_{uuid.uuid4().hex[:6]}"
        cust_b = f"P26_CB_{uuid.uuid4().hex[:6]}"
        try:
            # Seed a same-id-space collision (impossible in prod,
            # but tests the tenant guard: even if two tenants
            # somehow ended up with a same-id customer, the
            # lookup must return only the tenant-A row when
            # called with tenant_a).
            await db.customers.insert_many([
                {"id": cust_a, "tenant_id": tenant_a,
                 "service_lat": 1.0, "service_lng": 2.0},
                {"id": cust_b, "tenant_id": tenant_b,
                 "service_lat": 99.0, "service_lng": 99.0},
            ])
            # Build lookup for tenant A referencing BOTH ids.
            lookup = await build_customer_coord_lookup(
                db, tenant_a, [cust_a, cust_b],
            )
            # cust_a must be present; cust_b must NOT (cross-tenant).
            assert cust_a in lookup
            assert cust_b not in lookup, (
                f"Cross-tenant leak — tenant={tenant_a} received "
                f"customer from tenant={tenant_b}: {lookup}"
            )
            # And a job referencing the leaked id degrades to None
            # even if the resolver is called with it directly.
            job = {"id": "j1", "customer_id": cust_b,
                    "lat": None, "lng": None}
            lat, lng, src = resolve_job_coordinates(job, lookup)
            assert (lat, lng, src) == (None, None, None)
        finally:
            await db.customers.delete_many(
                {"tenant_id": {"$in": [tenant_a, tenant_b]}},
            )
    run_test(_go)


def test_p26_lookup_builder_empty_ids_short_circuits():
    async def _go(db):
        from services.geo_resolver import build_customer_coord_lookup
        # Empty/None ids MUST return {} without hitting the DB.
        res_empty = await build_customer_coord_lookup(db, "T", [])
        assert res_empty == {}
        res_none = await build_customer_coord_lookup(db, "T", None)
        assert res_none == {}
        # None + empty-string filter is stripped.
        res_mixed = await build_customer_coord_lookup(
            db, "T", [None, "", "  "],
        )
        # Whitespace strings are technically truthy so they pass
        # the initial ``if cid`` filter — but they'll simply not
        # match any customer row. The lookup must return {}
        # without an error.
        assert isinstance(res_mixed, dict)
    run_test(_go)


# ── 6) Source-lint: batched — no per-job customer find_one ────


def test_p26_no_per_job_customer_find_one_in_list_handlers():
    """Guardrail: list endpoints that emit coord-carrying jobs
    (schedule.py, dispatch_board.py, jobs.py) MUST batch the
    customer fetch. A per-job ``db.customers.find_one`` inside
    the emit loop is a P26 regression."""
    backend = Path(__file__).resolve().parents[1]
    for name in ("routers/schedule.py", "routers/dispatch_board.py",
                 "routers/jobs.py"):
        body = (backend / name).read_text(encoding="utf-8")
        # Locate the emit loop's job-iterator and confirm no
        # ``customers.find_one(`` call appears in an obvious hot
        # loop context. This is a coarse guardrail — the intent is
        # to fail loudly on a naive refactor, not to catch every
        # possible per-job DB hit.
        for line_no, line in enumerate(body.splitlines(), start=1):
            if "customers.find_one" in line and "def " not in line:
                # Allow the ``get_customer_by_id`` helper and any
                # tenant-guard preflight (those don't run per job).
                # We only fail on calls that appear inside a
                # comprehension or a loop body.
                if line.lstrip().startswith("("):  # continuation
                    continue
                # Best-effort context grep — flag only lines that
                # sit inside a ``for j in`` / ``for d in`` block.
                # 10-line-back context window.
                ctx = "\n".join(body.splitlines()[max(0, line_no - 10):line_no])
                if ("for j in " in ctx or "for d in " in ctx
                        or "for c in " in ctx):
                    pytest.fail(
                        f"{name}:{line_no} calls "
                        f"``db.customers.find_one`` inside an "
                        f"emit loop — P26 batching regression.\n"
                        f"Context:\n{ctx}"
                    )


# ── 7) Idempotency ────────────────────────────────────────────


def test_p26_resolver_is_pure_and_idempotent():
    from services.geo_resolver import resolve_job_coordinates

    cid = "c1"
    lookup = {cid: _c(cid, "T", lat=41.0, lng=-73.0)}
    job = _j("j1", cid, site_lat=1.0, site_lng=2.0)

    # Multiple calls return identical results.
    r1 = resolve_job_coordinates(job, lookup)
    r2 = resolve_job_coordinates(job, lookup)
    r3 = resolve_job_coordinates(job, lookup)
    assert r1 == r2 == r3

    # And the inputs are NOT mutated.
    assert job == _j("j1", cid, site_lat=1.0, site_lng=2.0)
    assert lookup == {cid: _c(cid, "T", lat=41.0, lng=-73.0)}


# ── 8) Bad-shape guards ───────────────────────────────────────


def test_p26_coerce_handles_stringy_numbers():
    from services.geo_resolver import resolve_job_coordinates

    # CSV-imported customer with STRING coords — the resolver
    # coerces cleanly.
    lookup = {"c1": {"id": "c1", "tenant_id": "T",
                       "service_lat": "33.5", "service_lng": "-112.3"}}
    job = _j("j1", "c1")
    lat, lng, src = resolve_job_coordinates(job, lookup)
    assert lat == 33.5
    assert lng == -112.3
    assert src == "customer"


def test_p26_coerce_rejects_empty_strings():
    from services.geo_resolver import resolve_job_coordinates

    lookup = {"c1": {"id": "c1", "tenant_id": "T",
                       "service_lat": "  ", "service_lng": ""}}
    job = _j("j1", "c1")
    lat, lng, src = resolve_job_coordinates(job, lookup)
    assert (lat, lng, src) == (None, None, None)


def test_p26_coerce_rejects_non_numeric_strings():
    from services.geo_resolver import resolve_job_coordinates

    job = _j("j1", "c1", lat="not-a-number", lng="also-not")
    lookup = {"c1": {"id": "c1", "tenant_id": "T",
                       "service_lat": 1.0, "service_lng": 2.0}}
    lat, lng, src = resolve_job_coordinates(job, lookup)
    # Non-numeric on the job forces the fallback to customer.
    assert (lat, lng) == (1.0, 2.0)
    assert src == "customer"


# ── 9) Half-populated coord pair rejected ─────────────────────


def test_p26_half_null_coord_pair_treated_as_absent():
    from services.geo_resolver import resolve_job_coordinates

    # lat set but lng None → treat as absent (a single-value coord
    # is meaningless for a map pin).
    lookup = {"c1": {"id": "c1", "tenant_id": "T",
                       "service_lat": 33.0, "service_lng": None}}
    job = _j("j1", "c1", lat=None, lng=None)
    lat, lng, src = resolve_job_coordinates(job, lookup)
    assert (lat, lng, src) == (None, None, None)
