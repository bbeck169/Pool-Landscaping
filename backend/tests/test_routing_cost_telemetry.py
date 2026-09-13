"""Feb-2026 · UX Polish Batch B — Routing cost telemetry endpoint.

Locks the contract on ``GET /api/reports/routing-cost-telemetry``:

  1. Endpoint returns 200 with the correct shape for admin.
  2. Technician → 403.
  3. Zero-calls tenant → empty aggregation (zeros, not null).
  4. ``window_days`` param round-trips (7 / 30 / 90).
  5. Cross-tenant isolation — one tenant's calls do NOT leak into
     another tenant's summary.

See /app/memory/FEATURE_SEND_TO_CUSTOMER_AND_COST_TELEMETRY.md.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / "frontend" / ".env")

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    pytest.skip("REACT_APP_BACKEND_URL not set", allow_module_level=True)

REQ_TIMEOUT = 45


def _session(email, password):
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": email, "password": password},
        timeout=REQ_TIMEOUT,
    )
    if r.status_code != 200:
        pytest.skip(f"login failed for {email}: {r.status_code}")
    tok = r.json().get("access_token") or r.json().get("token")
    s = requests.Session()
    s.headers.update({
        "Authorization": f"Bearer {tok}",
        "Content-Type": "application/json",
    })
    return s


@pytest.fixture(scope="module")
def admin_sess():
    return _session("admin@aquaterra.com", "password123")


@pytest.fixture(scope="module")
def tech_sess():
    return _session("mike@aquaterra.com", "password123")


_URL = "/api/reports/routing-cost-telemetry"


# ═════════════════════════════════════════════════════════════════════
# Case 1 · Admin GET → 200 with expected shape.
# ═════════════════════════════════════════════════════════════════════
def test_admin_gets_expected_shape(admin_sess):
    r = admin_sess.get(f"{BASE_URL}{_URL}", timeout=REQ_TIMEOUT)
    assert r.status_code == 200, r.text
    body = r.json()
    for key in (
        "window_days", "tenant_id", "total_calls",
        "traffic_aware_calls", "traffic_unaware_calls",
        "waypoints_billed", "est_traffic_aware_cost_usd",
        "est_baseline_cost_usd",
    ):
        assert key in body, f"missing {key} in response"
    # Non-null zeros, never ``None``.
    assert isinstance(body["total_calls"], int)
    assert isinstance(body["waypoints_billed"], int)
    assert isinstance(body["est_traffic_aware_cost_usd"], (int, float))
    assert isinstance(body["est_baseline_cost_usd"], (int, float))


# ═════════════════════════════════════════════════════════════════════
# Case 2 · Technician → 403.
# ═════════════════════════════════════════════════════════════════════
def test_technician_cannot_read_telemetry(tech_sess):
    r = tech_sess.get(f"{BASE_URL}{_URL}", timeout=REQ_TIMEOUT)
    assert r.status_code == 403, r.text


# ═════════════════════════════════════════════════════════════════════
# Case 3 · Empty aggregation shape when no calls recorded yet.
# ═════════════════════════════════════════════════════════════════════
def test_empty_tenant_returns_zeros_not_null():
    """Pure unit-style — invoke the summarizer directly with a
    tenant id that has no recorded calls. Guards the "never None"
    invariant regardless of the endpoint plumbing.
    """
    from services.routing.telemetry import summarize, _reset_for_tests
    _reset_for_tests()
    out = summarize("phantom-tenant-xyz", window_days=30)
    assert out["total_calls"] == 0
    assert out["traffic_aware_calls"] == 0
    assert out["traffic_unaware_calls"] == 0
    assert out["waypoints_billed"] == 0
    assert out["est_traffic_aware_cost_usd"] == 0.0
    assert out["est_baseline_cost_usd"] == 0.0
    # ``tenant_id`` reflects the caller's request even for empty.
    assert out["tenant_id"] == "phantom-tenant-xyz"


# ═════════════════════════════════════════════════════════════════════
# Case 4 · ``window_days`` param round-trips through the response.
# ═════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("wd", [7, 30, 90])
def test_window_days_param_round_trips(admin_sess, wd):
    r = admin_sess.get(
        f"{BASE_URL}{_URL}", params={"window_days": wd},
        timeout=REQ_TIMEOUT,
    )
    assert r.status_code == 200, r.text
    assert r.json()["window_days"] == wd


# ═════════════════════════════════════════════════════════════════════
# Case 5 · Cross-tenant isolation — one tenant's telemetry MUST NOT
# leak into another tenant's aggregation.
# ═════════════════════════════════════════════════════════════════════
def test_cross_tenant_isolation_in_summarizer():
    """Record a call under one tenant, then summarize under another.
    Locks the ``tenant_id`` filter inside ``summarize``.
    """
    from services.routing.telemetry import (
        summarize, record_routing_call, _reset_for_tests,
    )
    _reset_for_tests()
    record_routing_call(
        "tenant-A", traffic_aware=True, waypoint_count=10, op="optimize",
    )
    record_routing_call(
        "tenant-A", traffic_aware=False, waypoint_count=5, op="baseline",
    )
    a_summary = summarize("tenant-A", window_days=30)
    assert a_summary["total_calls"] == 2
    assert a_summary["traffic_aware_calls"] == 1
    assert a_summary["waypoints_billed"] == 15

    # Different tenant sees zero — no leak.
    b_summary = summarize("tenant-B", window_days=30)
    assert b_summary["total_calls"] == 0
    assert b_summary["waypoints_billed"] == 0
    _reset_for_tests()
