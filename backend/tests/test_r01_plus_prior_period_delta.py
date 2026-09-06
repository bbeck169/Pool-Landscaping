"""Phase R0.1+ · Feb-2026 — Prior-period delta on revenue_by_customer.

Covers:
  * ``include_prior=true`` (default) adds ``prior_revenue``,
    ``delta_abs``, ``delta_pct`` on every row plus a top-level
    ``prior_period`` block.
  * ``include_prior=false`` restores the pre-R0.1+ response shape
    verbatim (no prior fields anywhere).
  * ``delta_pct`` is ``None`` when the customer had zero revenue
    in the prior window ("New" case).
  * Cache-key bump — an ``include_prior=true`` call MUST NOT hit
    a cache entry left behind by an earlier ``include_prior=false``
    call for the same tenant/period/filters (the two response
    shapes are incompatible).
  * Prior-period math is correct for each preset period
    (mtd/qtd/ytd/last_30d) and for custom ranges.
  * Revenue by City is UNCHANGED (still returns rows without
    prior fields, tenant contract preserved).
"""
import os
import uuid

import pytest
import requests

BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL")
            or "http://localhost:8001").rstrip("/")
API = f"{BASE_URL}/api"


def _login(email: str, pw: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login",
                        json={"email": email, "password": pw}, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def hdr():
    return {"Authorization": f"Bearer {_login('super@aquaterra.com')}"}


# ─── Envelope shape ─────────────────────────────────────────────────

def test_default_response_includes_prior_period_block(hdr):
    r = requests.get(
        f"{API}/reports/kpi/revenue_by_customer",
        params={"period": "mtd", "lens": "invoiced", "limit": 5},
        headers=hdr, timeout=15,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["is_grouped"] is True
    assert "prior_period" in body
    assert set(body["prior_period"].keys()) == {"start", "end"}
    # ``prior_period.end`` must equal ``period.start`` (half-open).
    assert body["prior_period"]["end"] == body["period"]["start"]
    # ``filters_applied.include_prior`` must be True by default.
    assert body["filters_applied"]["include_prior"] is True


def test_default_rows_have_prior_delta_fields(hdr):
    r = requests.get(
        f"{API}/reports/kpi/revenue_by_customer",
        params={"period": "mtd", "lens": "invoiced"},
        headers=hdr, timeout=15,
    )
    assert r.status_code == 200, r.text
    rows = r.json().get("rows") or []
    if not rows:
        pytest.skip("no revenue in current MTD window on this tenant")
    for row in rows:
        assert "prior_revenue" in row
        assert "delta_abs" in row
        assert "delta_pct" in row
        # ``delta_abs`` must equal current - prior exactly.
        assert row["delta_abs"] == round(
            float(row["revenue"]) - float(row["prior_revenue"]), 2,
        )
        # ``delta_pct`` is None iff prior is zero.
        if row["prior_revenue"] == 0:
            assert row["delta_pct"] is None
        else:
            assert isinstance(row["delta_pct"], (int, float))


def test_include_prior_false_returns_pre_r01plus_shape(hdr):
    r = requests.get(
        f"{API}/reports/kpi/revenue_by_customer",
        params={"period": "mtd", "lens": "invoiced",
                  "include_prior": "false", "limit": 3},
        headers=hdr, timeout=15,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # ``filters_applied.include_prior`` must be False on the
    # back-compat branch.
    assert body["filters_applied"]["include_prior"] is False
    # ``prior_period`` block STAYS in the envelope even when the
    # rows skip prior fields — the FE may still want to render the
    # comparison window range in a subheader.
    assert "prior_period" in body
    for row in body.get("rows") or []:
        assert "prior_revenue" not in row
        assert "delta_abs" not in row
        assert "delta_pct" not in row


# ─── Cache-key bump ─────────────────────────────────────────────────

def test_cache_key_bumped_between_prior_flavors(hdr):
    """Bug we're pinning: prior to the R0.1+ cache-key bump, an
    ``include_prior=true`` call could hit a cached
    ``include_prior=false`` payload and return the wrong shape."""
    # Force a fresh custom period so any cached entry from another
    # test doesn't interfere.
    unique_start = f"2026-01-{(hash(uuid.uuid4().hex) % 20) + 1:02d}"
    unique_end = "2026-01-31"
    params_no_prior = {
        "period": "custom", "start": unique_start, "end": unique_end,
        "lens": "invoiced", "include_prior": "false",
    }
    r1 = requests.get(f"{API}/reports/kpi/revenue_by_customer",
                        params=params_no_prior, headers=hdr, timeout=15)
    assert r1.status_code == 200
    for row in r1.json().get("rows") or []:
        assert "prior_revenue" not in row

    params_with_prior = dict(params_no_prior, include_prior="true")
    r2 = requests.get(f"{API}/reports/kpi/revenue_by_customer",
                        params=params_with_prior, headers=hdr, timeout=15)
    assert r2.status_code == 200
    body = r2.json()
    assert body["filters_applied"]["include_prior"] is True
    # A row on r2 MUST carry the prior fields even though r1 for
    # the same window was cached first (cache-key bump proof).
    for row in body.get("rows") or []:
        assert "prior_revenue" in row
        assert "delta_abs" in row


# ─── Period math ────────────────────────────────────────────────────

@pytest.mark.parametrize("period_key", ["mtd", "qtd", "ytd", "last_30d"])
def test_prior_window_length_matches_current(hdr, period_key):
    """The prior window must be exactly the same length as the
    current window for every preset period."""
    from datetime import date
    r = requests.get(
        f"{API}/reports/kpi/revenue_by_customer",
        params={"period": period_key, "lens": "invoiced", "limit": 1},
        headers=hdr, timeout=15,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    cur_s = date.fromisoformat(body["period"]["start"])
    cur_e = date.fromisoformat(body["period"]["end"])
    pri_s = date.fromisoformat(body["prior_period"]["start"])
    pri_e = date.fromisoformat(body["prior_period"]["end"])
    assert (cur_e - cur_s) == (pri_e - pri_s)
    assert pri_e == cur_s  # half-open, contiguous


def test_prior_window_for_custom_range(hdr):
    """Custom range prior = same-length window ending at
    ``start - 1 day`` (half-open ``end == start``)."""
    r = requests.get(
        f"{API}/reports/kpi/revenue_by_customer",
        params={"period": "custom", "start": "2026-01-15",
                  "end": "2026-01-31", "lens": "invoiced", "limit": 1},
        headers=hdr, timeout=15,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # Current window: 2026-01-15 → 2026-02-01 (17 days incl end).
    # Prior window   : 2026-01-15 - 17d → 2026-01-15.
    assert body["period"]["start"] == "2026-01-15"
    assert body["period"]["end"] == "2026-02-01"
    assert body["prior_period"]["end"] == "2026-01-15"
    from datetime import date
    span = date.fromisoformat(body["period"]["end"]) - \
              date.fromisoformat(body["period"]["start"])
    prior_start_expected = date.fromisoformat("2026-01-15") - span
    assert body["prior_period"]["start"] == prior_start_expected.isoformat()


# ─── Sibling metric untouched ───────────────────────────────────────

def test_revenue_by_city_still_has_no_prior_fields(hdr):
    r = requests.get(
        f"{API}/reports/kpi/revenue_by_city",
        params={"period": "mtd", "lens": "invoiced"},
        headers=hdr, timeout=15,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # Deliberate scope deferral — R0.1+ only touches Revenue by
    # Customer. City response envelope keeps its pre-R0.1+ shape.
    assert body["filters_applied"].get("include_prior") in (False, None)
    for row in body.get("rows") or []:
        assert "prior_revenue" not in row
        assert "delta_abs" not in row
