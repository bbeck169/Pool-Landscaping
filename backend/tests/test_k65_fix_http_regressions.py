"""Phase K65.fix — HTTP-level regression tests via public preview URL.

Verifies review items:
 1. GET /api/technicians shape (active_jobs / repair / service on every doc)
 2. GET /api/jobs?start&end returns sorted rows
 3. POST /api/admin/perf/explain-schedule -> 404 when flag off
 4. GET  /api/admin/perf/explain-schedule/status -> 403 tech, 200 super_admin
 5. Flag ON: status returns enabled=true, POST returns executionStats
 6. Adjacent K63 endpoints still work (resend-notifications + dispatch-log)
"""
from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values

_FE_ENV = dotenv_values(Path("/app/frontend/.env"))
BASE_URL = _FE_ENV["REACT_APP_BACKEND_URL"].rstrip("/")

SUPER = {"email": "super@aquaterra.com", "password": "password123"}
TECH = {"email": "mike@aquaterra.com", "password": "password123"}


# ─── helpers ────────────────────────────────────────────────────────────
def _login(creds):
    last = None
    for _ in range(3):
        try:
            r = requests.post(f"{BASE_URL}/api/auth/login", json=creds, timeout=45)
            if r.status_code == 200:
                return r.json()["access_token"]
            last = f"{r.status_code} {r.text[:200]}"
        except Exception as e:
            last = repr(e)
        time.sleep(2)
    raise AssertionError(f"login failed for {creds['email']}: {last}")


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture(scope="module")
def super_token():
    return _login(SUPER)


@pytest.fixture(scope="module")
def tech_token():
    return _login(TECH)


def _set_perf_flag(value: str):
    """Set FEATURE_PERF_EXPLAIN in backend .env and restart backend."""
    subprocess.run(
        ["sed", "-i", f's/^FEATURE_PERF_EXPLAIN=.*/FEATURE_PERF_EXPLAIN="{value}"/', "/app/backend/.env"],
        check=True,
    )
    subprocess.run(["sudo", "supervisorctl", "restart", "backend"], check=True)
    # Wait for backend to be back up
    deadline = time.time() + 30
    while time.time() < deadline:
        try:
            r = requests.get(f"{BASE_URL}/api/health", timeout=5)
            if r.status_code < 500:
                time.sleep(1)
                return
        except Exception:
            pass
        time.sleep(1)


# ─── 1 · /api/technicians shape ─────────────────────────────────────────
def test_technicians_response_shape_preserved(super_token):
    r = requests.get(f"{BASE_URL}/api/technicians", headers=_hdr(super_token), timeout=30)
    assert r.status_code == 200, r.text[:300]
    rows = r.json()
    assert isinstance(rows, list) and len(rows) > 0, "expected at least 1 technician row"
    for d in rows:
        for k in ("active_jobs", "active_jobs_repair", "active_jobs_service"):
            assert k in d, f"missing {k} in {d.get('id')}"
        assert d["active_jobs"] == d["active_jobs_repair"] + d["active_jobs_service"], d


# ─── 2 · /api/jobs window sort ──────────────────────────────────────────
def test_jobs_window_returns_sorted_rows(super_token):
    r = requests.get(
        f"{BASE_URL}/api/jobs",
        params={"start": "2026-01-01", "end": "2026-12-31"},
        headers=_hdr(super_token),
        timeout=30,
    )
    assert r.status_code == 200, r.text[:300]
    rows = r.json()
    assert isinstance(rows, list)
    if len(rows) < 2:
        pytest.skip(f"only {len(rows)} rows in window — sort assertion needs >=2")

    def _key(d):
        sd = d.get("scheduled_date") or ""
        day = sd[:10] if isinstance(sd, str) else ""
        ri = d.get("route_index")
        ri_val = ri if isinstance(ri, (int, float)) else 999999
        return (day, ri_val, sd, d.get("created_at") or "")

    keys = [_key(d) for d in rows]
    assert keys == sorted(keys), "K65.fix sort contract violated"


# ─── 3 · perf-explain 404 with flag OFF ─────────────────────────────────
def test_perf_explain_post_404_with_flag_off(super_token):
    r = requests.post(
        f"{BASE_URL}/api/admin/perf/explain-schedule",
        headers=_hdr(super_token),
        json={},
        timeout=15,
    )
    assert r.status_code == 404, f"expected 404, got {r.status_code}: {r.text[:200]}"


def test_perf_explain_status_super_admin_flag_off(super_token):
    r = requests.get(
        f"{BASE_URL}/api/admin/perf/explain-schedule/status",
        headers=_hdr(super_token),
        timeout=15,
    )
    assert r.status_code == 200, r.text[:200]
    body = r.json()
    assert body.get("enabled") is False, body


def test_perf_explain_status_technician_forbidden(tech_token):
    r = requests.get(
        f"{BASE_URL}/api/admin/perf/explain-schedule/status",
        headers=_hdr(tech_token),
        timeout=15,
    )
    assert r.status_code == 403, f"expected 403, got {r.status_code}: {r.text[:200]}"


# ─── 4 · perf-explain flag ON (flip + reset) ────────────────────────────
def test_perf_explain_flag_on_full_flow():
    _set_perf_flag("1")
    try:
        # re-login (module-scoped token still valid across restart, but safer)
        tok = _login(SUPER)
        s = requests.get(
            f"{BASE_URL}/api/admin/perf/explain-schedule/status",
            headers=_hdr(tok),
            timeout=15,
        )
        assert s.status_code == 200, s.text[:200]
        assert s.json().get("enabled") is True, s.json()

        p = requests.post(
            f"{BASE_URL}/api/admin/perf/explain-schedule",
            headers=_hdr(tok),
            json={},
            timeout=45,
        )
        assert p.status_code == 200, f"expected 200, got {p.status_code}: {p.text[:400]}"
        body = p.json()
        results = body.get("results") or {}
        for leg in ("jobs_pipeline", "technician_count", "service_reports_lookup"):
            assert leg in results, f"missing leg {leg} in {list(results.keys())}"
            leg_body = results[leg]
            assert isinstance(leg_body, dict), f"{leg} is not a dict"
            blob = str(leg_body)
            assert "executionStats" in blob or "stages" in blob or "queryPlanner" in blob, (
                f"{leg} has no explain-y content: {blob[:300]}"
            )
    finally:
        _set_perf_flag("")


# ─── 5 · Adjacent K63 endpoints still work ──────────────────────────────
def test_k63_dispatch_log_still_reachable(super_token):
    r = requests.get(
        f"{BASE_URL}/api/admin/notification-dispatch-log",
        headers=_hdr(super_token),
        timeout=20,
    )
    # 200 or 200 with empty rows — anything other than 5xx / 404 is fine
    assert r.status_code == 200, f"got {r.status_code}: {r.text[:200]}"


def test_k63_resend_notifications_404_for_missing_lead(super_token):
    # We don't want to mutate a real lead — a bogus id should give
    # 404 (or 400), NOT a 500 which would signal a regression.
    r = requests.post(
        f"{BASE_URL}/api/admin/leads/nonexistent-k65-fix-probe/resend-notifications",
        headers=_hdr(super_token),
        timeout=20,
    )
    assert r.status_code in (400, 404), f"unexpected {r.status_code}: {r.text[:200]}"
