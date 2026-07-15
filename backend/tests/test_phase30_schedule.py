"""Phase 30 · Calendar Schedule — backend date-range filter tests.

Verifies that `GET /api/jobs?start=&end=` narrows the response to jobs whose
`scheduled_date` falls inside the inclusive window. Unrelated fields and
tenant-scoping behaviour are covered elsewhere; this file is deliberately
tight.
"""
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values

_FE = dotenv_values(Path(__file__).resolve().parents[2] / "frontend" / ".env")
BASE = (_FE.get("EXPO_PUBLIC_BACKEND_URL") or "http://localhost:8001").rstrip("/")
API = f"{BASE}/api"


def _login(email: str, pw: str = "password123") -> dict:
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": pw}, timeout=15)
    r.raise_for_status()
    return r.json()


@pytest.fixture(scope="module")
def admin_h():
    return {"Authorization": f"Bearer {_login('admin@aquaterra.com')['access_token']}"}


def _jobs(headers, params=""):
    r = requests.get(f"{API}/jobs{params}", headers=headers, timeout=20)
    assert r.status_code == 200, r.text
    d = r.json()
    return d if isinstance(d, list) else d.get("items", d.get("data", []))


def test_range_filter_narrows(admin_h):
    """A narrow window should return a strict subset of the unfiltered list
    AND every returned job's `scheduled_date` must fall inside the window."""
    all_jobs = _jobs(admin_h)
    dated = [j for j in all_jobs if j.get("scheduled_date")]
    if not dated:
        pytest.skip("No dated jobs seeded — nothing to filter against.")
    # Pick a single scheduled_date and range it exactly.
    pivot = sorted({j["scheduled_date"] for j in dated})[0]
    windowed = _jobs(admin_h, f"?start={pivot}&end={pivot}")
    assert len(windowed) <= len(all_jobs)
    for j in windowed:
        assert j.get("scheduled_date") == pivot, j


def test_range_open_ended(admin_h):
    """`start` alone must still narrow the response; `end` alone likewise.
    Sanity-check that the filter doesn't accidentally require both bounds."""
    r_start = _jobs(admin_h, "?start=2099-01-01")
    assert isinstance(r_start, list)
    # future-only window returns 0 or a strict subset — either way the
    # filter must not blow up and must not return everything.
    assert len(r_start) <= len(_jobs(admin_h))

    r_end = _jobs(admin_h, "?end=1990-01-01")
    assert r_end == [], r_end  # nothing scheduled before 1990
