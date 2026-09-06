"""Phase R0 · Feb-2026 — Reporting suite foundation tests.

Covers the ``GET /api/reports/kpi/{metric_key}`` endpoint plus the
supporting pieces (metric registry, cache-hit signalling, RBAC).

Backend must be running (``supervisorctl start backend``); tests
hit the live surface via HTTP so the tenant + auth stack is
exercised end-to-end.
"""
from __future__ import annotations

import os
import uuid

import pytest
import requests

BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL")
            or "http://localhost:8001").rstrip("/")
API = f"{BASE_URL}/api"


def _login(email: str, pw: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": pw}, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def admin_headers():
    return {"Authorization": f"Bearer {_login('super@aquaterra.com')}"}


@pytest.fixture(scope="module")
def _flush_cache():
    """Clear the module-level ``report_cache`` singleton so
    cache-hit tests can rely on a known starting state without
    racing other tests in the same module."""
    from services.reporting import report_cache
    report_cache.clear()
    yield
    report_cache.clear()


# ─── Happy path ─────────────────────────────────────────────────────

def test_kpi_revenue_total_ytd_shape(admin_headers, _flush_cache):
    r = requests.get(f"{API}/reports/kpi/revenue_total?period=ytd",
                       headers=admin_headers, timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    # Envelope fields.
    assert body["key"] == "revenue_total"
    assert body["label"] == "Total Revenue"
    assert body["format"] == "currency"
    assert body["direction"] == "up_is_good"
    # ``cached`` is envelope-level truthy/falsy; the dedicated
    # cache-hit test asserts the transition — this test only cares
    # about SHAPE, so accept either state (the server may have
    # cached the ytd result on a previous test-run within the TTL).
    assert body["cached"] in (True, False)
    # Period envelope.
    assert body["period"]["key"] == "ytd"
    assert body["period"]["start"].endswith("-01-01")
    # Value envelope.
    assert isinstance(body["value"], (int, float))
    assert isinstance(body["prior_value"], (int, float))
    assert body["delta_pct"] is None or isinstance(body["delta_pct"], (int, float))
    assert isinstance(body["sparkline"], list)
    for point in body["sparkline"]:
        assert "t" in point and "v" in point


def test_kpi_period_variants_all_resolve(admin_headers):
    for p in ("mtd", "qtd", "ytd", "last_30d"):
        r = requests.get(f"{API}/reports/kpi/revenue_total?period={p}",
                           headers=admin_headers, timeout=15)
        assert r.status_code == 200, f"{p}: {r.text}"
        assert r.json()["period"]["key"] == p


def test_kpi_custom_period_requires_start_and_end(admin_headers):
    r = requests.get(f"{API}/reports/kpi/revenue_total?period=custom",
                       headers=admin_headers, timeout=15)
    assert r.status_code == 400


def test_kpi_custom_period_returns_range_label(admin_headers):
    r = requests.get(
        f"{API}/reports/kpi/revenue_total?period=custom&start=2026-01-01&end=2026-06-30",
        headers=admin_headers, timeout=15,
    )
    assert r.status_code == 200
    p = r.json()["period"]
    assert p["key"] == "custom"
    assert p["start"] == "2026-01-01"
    # End boundary is exclusive-day-after inside the engine — the
    # response echoes it back so R1 tests can round-trip.
    assert p["end"] == "2026-07-01"


# ─── Cache ──────────────────────────────────────────────────────────

def test_kpi_cache_hit_second_call(admin_headers, _flush_cache):
    """Use a unique custom range so the server's in-memory cache is
    guaranteed to miss on the first hit and serve from cache on the
    second. The ``_flush_cache`` fixture clears the local process's
    ``report_cache`` singleton so pure-Python unit tests don't
    inherit residue — the tests below hit the LIVE backend, whose
    cache is separate, hence the unique-key strategy."""
    import uuid as _uuid
    # Deterministic-ish window seeded from a uuid so re-runs don't collide.
    seed = int(_uuid.uuid4().int % 90)
    start = f"2025-{(seed % 12) + 1:02d}-01"
    end = f"2025-{(seed % 12) + 1:02d}-15"
    url = (f"{API}/reports/kpi/revenue_total?period=custom"
             f"&start={start}&end={end}")
    r1 = requests.get(url, headers=admin_headers, timeout=15)
    assert r1.status_code == 200
    assert r1.json()["cached"] is False, "first hit must miss the cache"
    r2 = requests.get(url, headers=admin_headers, timeout=15)
    assert r2.status_code == 200
    assert r2.json()["cached"] is True, "second hit must serve from cache"
    v1, v2 = r1.json(), r2.json()
    for f in ("value", "prior_value", "delta_pct", "sparkline"):
        assert v1[f] == v2[f]


# ─── Errors ─────────────────────────────────────────────────────────

def test_kpi_unknown_metric_404(admin_headers):
    r = requests.get(f"{API}/reports/kpi/{uuid.uuid4().hex}?period=mtd",
                       headers=admin_headers, timeout=15)
    assert r.status_code == 404


def test_kpi_bad_period_400(admin_headers):
    r = requests.get(f"{API}/reports/kpi/revenue_total?period=eternity",
                       headers=admin_headers, timeout=15)
    assert r.status_code == 400


# ─── RBAC ───────────────────────────────────────────────────────────

def test_kpi_tech_forbidden():
    tok = _login("mike@aquaterra.com")
    r = requests.get(f"{API}/reports/kpi/revenue_total?period=mtd",
                       headers={"Authorization": f"Bearer {tok}"}, timeout=15)
    assert r.status_code in (401, 403)


def test_kpi_unauthenticated_rejected():
    r = requests.get(f"{API}/reports/kpi/revenue_total?period=mtd", timeout=15)
    assert r.status_code in (401, 403)


def test_kpi_registry_list_returns_at_least_revenue_total(admin_headers):
    r = requests.get(f"{API}/reports/kpi", headers=admin_headers, timeout=15)
    assert r.status_code == 200
    keys = {m["key"] for m in r.json()["metrics"]}
    assert "revenue_total" in keys


# ─── Unit tests for the pure Python primitives ──────────────────────
#
# These do not require the backend to be running — they exercise
# ``services.reporting.period`` + ``services.reporting.cache`` + the
# registry directly.

def test_period_mtd_prior_window_shape():
    from datetime import date
    from services.reporting.period import resolve_period
    p = resolve_period("mtd", _today=date(2026, 2, 15))
    assert p.start == "2026-02-01"
    assert p.end == "2026-02-16"          # inclusive-of-today
    # Prior window is same length ending at start.
    assert p.prior_start == "2026-01-17"
    assert p.prior_end == "2026-02-01"


def test_period_ytd_prior_window_shape():
    from datetime import date
    from services.reporting.period import resolve_period
    p = resolve_period("ytd", _today=date(2026, 3, 10))
    assert p.start == "2026-01-01"
    assert p.end == "2026-03-11"


def test_period_last_30d_shape():
    from datetime import date
    from services.reporting.period import resolve_period
    p = resolve_period("last_30d", _today=date(2026, 2, 15))
    assert p.start == "2026-01-17"
    assert p.end == "2026-02-16"


def test_cache_tenant_scope_isolation():
    from services.reporting.cache import ReportCache
    c = ReportCache(ttl_seconds=60)
    c.set(c.make_key("tenant-a", "kpi", "rev", "mtd"), {"v": 1})
    c.set(c.make_key("tenant-b", "kpi", "rev", "mtd"), {"v": 2})
    assert c.get(c.make_key("tenant-a", "kpi", "rev", "mtd")) == {"v": 1}
    assert c.get(c.make_key("tenant-b", "kpi", "rev", "mtd")) == {"v": 2}
    cleared = c.clear_tenant("tenant-a")
    assert cleared == 1
    assert c.get(c.make_key("tenant-a", "kpi", "rev", "mtd")) is None
    assert c.get(c.make_key("tenant-b", "kpi", "rev", "mtd")) == {"v": 2}


def test_registry_rejects_duplicate_key():
    from services.reporting.registry import Metric, register_metric, REGISTRY
    # Snapshot + clean up so test ordering isn't load-bearing.
    class _DupA(Metric):
        key = "r0_test_dup_metric"
        label = "A"
        format = "number"
        direction = "up_is_good"

    register_metric(_DupA)
    try:
        class _DupB(Metric):
            key = "r0_test_dup_metric"
            label = "B"
            format = "number"
            direction = "up_is_good"

        with pytest.raises(ValueError):
            register_metric(_DupB)
    finally:
        REGISTRY.pop("r0_test_dup_metric", None)


def test_registry_rejects_invalid_format():
    from services.reporting.registry import Metric, register_metric

    class _Bad(Metric):
        key = "r0_test_bad_format"
        label = "Bad"
        format = "banana"
        direction = "up_is_good"

    with pytest.raises(ValueError):
        register_metric(_Bad)
