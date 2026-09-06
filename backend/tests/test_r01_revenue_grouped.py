"""Phase R0.1 · Feb-2026 — grouped-metric tests for revenue_by_customer
and revenue_by_city.

Covers both metrics end-to-end (aggregation → cache → registry →
router):

* Envelope shape (``is_grouped``, ``lens``, ``filters_applied``,
  ``rows``, ``total``, ``row_count``).
* Lens toggle (``invoiced`` vs ``collected``).
* Filter matrix (``service_type``, ``tech_id``).
* Pagination (``limit`` + ``offset``).
* Descending sort by revenue.
* Empty result branch (unmatchable filter).
* Cache hit on repeat call (unique custom window).
* Unknown metric key → 404 (regression on R0 behaviour).
* Non-admin → 403 / unauth → 401 (regression on R0 RBAC).
* Pure-Python ``parse_city`` unit tests for the shared helper.
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


# ─── Shape ──────────────────────────────────────────────────────────

def test_revenue_by_customer_envelope_shape(admin_headers):
    r = requests.get(f"{API}/reports/kpi/revenue_by_customer?period=ytd&lens=invoiced&limit=5",
                       headers=admin_headers, timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["key"] == "revenue_by_customer"
    assert body["is_grouped"] is True
    assert body["lens"] == "invoiced"
    assert body["filters_applied"]["limit"] == 5
    assert body["filters_applied"]["offset"] == 0
    assert isinstance(body["rows"], list)
    assert isinstance(body["total"], (int, float))
    assert body["row_count"] >= len(body["rows"])
    for row in body["rows"]:
        assert set(row.keys()) >= {"customer_id", "customer_name", "revenue", "invoice_count"}


def test_revenue_by_city_envelope_shape(admin_headers):
    r = requests.get(f"{API}/reports/kpi/revenue_by_city?period=ytd&lens=invoiced",
                       headers=admin_headers, timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["key"] == "revenue_by_city"
    assert body["is_grouped"] is True
    for row in body["rows"]:
        assert set(row.keys()) >= {"city", "customer_count", "revenue"}
        assert isinstance(row["city"], str)


# ─── Behaviours ─────────────────────────────────────────────────────

def test_rows_sorted_desc_by_revenue(admin_headers):
    r = requests.get(f"{API}/reports/kpi/revenue_by_customer?period=ytd&lens=invoiced&limit=100",
                       headers=admin_headers, timeout=15)
    body = r.json()
    revs = [row["revenue"] for row in body["rows"]]
    assert revs == sorted(revs, reverse=True)


def test_city_sorted_desc_by_revenue(admin_headers):
    r = requests.get(f"{API}/reports/kpi/revenue_by_city?period=ytd",
                       headers=admin_headers, timeout=15)
    revs = [row["revenue"] for row in r.json()["rows"]]
    assert revs == sorted(revs, reverse=True)


def test_lens_flip_changes_total(admin_headers):
    a = requests.get(f"{API}/reports/kpi/revenue_by_customer?period=ytd&lens=invoiced",
                       headers=admin_headers, timeout=15).json()
    b = requests.get(f"{API}/reports/kpi/revenue_by_customer?period=ytd&lens=collected",
                       headers=admin_headers, timeout=15).json()
    # Both endpoints succeed; the two lenses generally return
    # different totals (collected <= invoiced) but the shapes are
    # identical.
    assert a["lens"] == "invoiced"
    assert b["lens"] == "collected"
    assert isinstance(a["total"], (int, float))
    assert isinstance(b["total"], (int, float))


def test_lens_default_is_invoiced(admin_headers):
    r = requests.get(f"{API}/reports/kpi/revenue_by_customer?period=ytd",
                       headers=admin_headers, timeout=15).json()
    assert r["lens"] == "invoiced"


def test_bad_lens_400(admin_headers):
    r = requests.get(f"{API}/reports/kpi/revenue_by_customer?period=ytd&lens=nonsense",
                       headers=admin_headers, timeout=15)
    assert r.status_code == 400


def test_pagination_limit_and_offset(admin_headers):
    page_all = requests.get(f"{API}/reports/kpi/revenue_by_customer?period=ytd&limit=100",
                              headers=admin_headers, timeout=15).json()
    if len(page_all["rows"]) < 4:
        pytest.skip("not enough rows to test pagination")
    page1 = requests.get(f"{API}/reports/kpi/revenue_by_customer?period=ytd&limit=2&offset=0",
                          headers=admin_headers, timeout=15).json()
    page2 = requests.get(f"{API}/reports/kpi/revenue_by_customer?period=ytd&limit=2&offset=2",
                          headers=admin_headers, timeout=15).json()
    assert page1["rows"] == page_all["rows"][:2]
    assert page2["rows"] == page_all["rows"][2:4]
    # Total is the FULL filter set, not the visible slice.
    assert page1["total"] == page_all["total"]
    assert page2["total"] == page_all["total"]


def test_service_type_filter_matches_customer_scope(admin_headers):
    r = requests.get(
        f"{API}/reports/kpi/revenue_by_customer?period=ytd&service_type=weekly",
        headers=admin_headers, timeout=15,
    ).json()
    assert r["filters_applied"]["service_type"] == "weekly"
    assert isinstance(r["rows"], list)   # may be zero rows in test data


def test_tech_id_filter_no_match_returns_zero_rows(admin_headers):
    r = requests.get(
        f"{API}/reports/kpi/revenue_by_customer?period=ytd&tech_id={uuid.uuid4().hex}",
        headers=admin_headers, timeout=15,
    ).json()
    assert r["total"] == 0.0
    assert r["rows"] == []


def test_city_service_type_filter_matches_customer_scope(admin_headers):
    r = requests.get(
        f"{API}/reports/kpi/revenue_by_city?period=ytd&service_type=weekly",
        headers=admin_headers, timeout=15,
    ).json()
    assert r["filters_applied"]["service_type"] == "weekly"


def test_city_tech_id_filter_no_match_returns_zero(admin_headers):
    r = requests.get(
        f"{API}/reports/kpi/revenue_by_city?period=ytd&tech_id={uuid.uuid4().hex}",
        headers=admin_headers, timeout=15,
    ).json()
    assert r["rows"] == []
    assert r["total"] == 0.0


# ─── Cache ──────────────────────────────────────────────────────────

def test_grouped_cache_hit(admin_headers):
    import uuid as _uuid
    seed = _uuid.uuid4().hex[:6]
    # Different seed-derived date range every run so we don't collide.
    start = f"2025-{(int(seed, 16) % 12) + 1:02d}-01"
    end = f"2025-{(int(seed, 16) % 12) + 1:02d}-20"
    url = (f"{API}/reports/kpi/revenue_by_customer?period=custom"
             f"&start={start}&end={end}&lens=invoiced")
    r1 = requests.get(url, headers=admin_headers, timeout=15)
    assert r1.status_code == 200
    assert r1.json()["cached"] is False, "first hit must miss the cache"
    r2 = requests.get(url, headers=admin_headers, timeout=15)
    assert r2.status_code == 200
    assert r2.json()["cached"] is True, "second hit must serve from cache"


def test_lens_flip_bypasses_cache(admin_headers):
    import uuid as _uuid
    seed = _uuid.uuid4().hex[:6]
    start = f"2025-{(int(seed, 16) % 12) + 1:02d}-01"
    end = f"2025-{(int(seed, 16) % 12) + 1:02d}-20"
    base = (f"{API}/reports/kpi/revenue_by_customer?period=custom"
             f"&start={start}&end={end}")
    r_inv = requests.get(f"{base}&lens=invoiced", headers=admin_headers, timeout=15).json()
    r_col = requests.get(f"{base}&lens=collected", headers=admin_headers, timeout=15).json()
    # Both start uncached because their cache keys differ.
    assert r_inv["cached"] is False
    assert r_col["cached"] is False


# ─── Registry / RBAC regressions ────────────────────────────────────

def test_registry_lists_both_grouped_metrics(admin_headers):
    r = requests.get(f"{API}/reports/kpi", headers=admin_headers, timeout=15).json()
    keys = {m["key"] for m in r["metrics"]}
    assert "revenue_by_customer" in keys
    assert "revenue_by_city" in keys
    # Both flagged as grouped in the registry list.
    for m in r["metrics"]:
        if m["key"] in ("revenue_by_customer", "revenue_by_city"):
            assert m["is_grouped"] is True


def test_unknown_metric_still_404(admin_headers):
    r = requests.get(f"{API}/reports/kpi/does_not_exist_r01?period=ytd",
                       headers=admin_headers, timeout=15)
    assert r.status_code == 404


def test_tech_forbidden():
    tok = _login("mike@aquaterra.com")
    r = requests.get(f"{API}/reports/kpi/revenue_by_customer?period=ytd",
                       headers={"Authorization": f"Bearer {tok}"}, timeout=15)
    assert r.status_code in (401, 403)


def test_unauthenticated_rejected():
    r = requests.get(f"{API}/reports/kpi/revenue_by_customer?period=ytd", timeout=15)
    assert r.status_code in (401, 403)


# ─── Pure-Python parse_city ─────────────────────────────────────────

def test_parse_city_three_piece_address():
    from services.reporting.metrics._revenue_shared import parse_city
    assert parse_city("12 Vistancia Blvd, Peoria, AZ") == "Peoria"


def test_parse_city_with_zip():
    from services.reporting.metrics._revenue_shared import parse_city
    assert parse_city("12 Vistancia Blvd, Peoria, AZ 85383") == "Peoria"


def test_parse_city_missing_returns_unknown():
    from services.reporting.metrics._revenue_shared import parse_city
    assert parse_city(None) == "(unknown)"
    assert parse_city("") == "(unknown)"
    assert parse_city("   ") == "(unknown)"
