"""Phase 2 rework addendum · Feb-2026 — GPS read lockdown.

Verifies that Tech and Customer roles are BLOCKED from reading GPS
data across the whole feature area (live positions, stops, route,
geofences, scorecard, settings, etc.) while Manager / Admin / Super
Admin retain 200 access.

Also verifies that ``POST /api/gps/pings`` — the tech mobile app's
ping ingest — is NOT gated (returns anything other than 403).
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import dotenv_values

_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
API = os.environ.get("BACKEND_API_URL") or "http://localhost:8001/api"


def _login(email: str) -> str:
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": "password123"},
                       timeout=10)
    r.raise_for_status()
    return r.json()["access_token"]


# Representative GPS READ endpoints (one per gated router file).
_READ_ENDPOINTS = [
    ("GET",  "/gps/live-positions"),
    ("GET",  "/gps/stops"),
    ("GET",  "/admin/gps/settings"),
    ("GET",  f"/gps/route?user_id=whatever&from={datetime.now(timezone.utc).strftime('%Y-%m-%dT00:00:00Z')}&to={datetime.now(timezone.utc).strftime('%Y-%m-%dT23:59:59Z')}"),
    ("GET",  "/geofences"),
    ("GET",  "/geofence-events?limit=1"),
    ("GET",  "/admin/gps/attribution/settings"),
    ("GET",  "/admin/gps/scorecard/leaderboard?range=this_week"),
]


def _hit(method: str, path: str, tok: str) -> int:
    hdrs = {"Authorization": f"Bearer {tok}"}
    if method == "GET":
        return requests.get(f"{API}{path}", headers=hdrs, timeout=10).status_code
    return requests.post(f"{API}{path}", headers=hdrs, json={}, timeout=10).status_code


def test_tech_forbidden_on_all_gps_reads():
    tok = _login("landscaper@aquaterra.com")  # role=technician
    for m, p in _READ_ENDPOINTS:
        code = _hit(m, p, tok)
        assert code == 403, f"tech should get 403 on {m} {p}, got {code}"


def test_customer_forbidden_on_all_gps_reads():
    tok = _login("customer@aquaterra.com")  # role=customer
    for m, p in _READ_ENDPOINTS:
        code = _hit(m, p, tok)
        assert code == 403, f"customer should get 403 on {m} {p}, got {code}"


def test_admin_allowed_on_all_gps_reads():
    tok = _login("manager@aquaterra.com")  # role=admin per seed
    for m, p in _READ_ENDPOINTS:
        code = _hit(m, p, tok)
        # 200 (or 4xx for a missing query dep) — the important thing is
        # NOT 403. A tenant with no data will 200 with empty {items:[]},
        # and 422 from validation is also fine because that means the
        # handler was reached.
        assert code not in (401, 403), \
            f"admin unexpectedly blocked on {m} {p}: {code}"


def test_super_admin_allowed_on_all_gps_reads():
    tok = _login("super@aquaterra.com")  # role=super_admin
    for m, p in _READ_ENDPOINTS:
        code = _hit(m, p, tok)
        assert code not in (401, 403), \
            f"super_admin unexpectedly blocked on {m} {p}: {code}"


def test_tech_can_still_post_gps_pings():
    """The tech mobile app ingest must NOT be blocked by the GPS read
    lockdown. Any status other than 403 means the guard did not run —
    payload validation errors (422) are acceptable here."""
    tok = _login("landscaper@aquaterra.com")
    r = requests.post(
        f"{API}/gps/pings",
        headers={"Authorization": f"Bearer {tok}",
                  "Content-Type": "application/json"},
        json={"lat": 33.7, "lon": -112.3, "accuracy_m": 10,
               "captured_at": datetime.now(timezone.utc).isoformat()},
        timeout=10,
    )
    assert r.status_code != 403, \
        f"tech POST /gps/pings should NOT be locked down, got {r.status_code}: {r.text}"
