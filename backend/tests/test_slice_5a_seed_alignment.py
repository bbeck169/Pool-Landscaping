"""Phase 5A follow-up · Feb 2026 — seed alignment tests.

Verifies that the boot-time seed:
    * Places ``mike@aquaterra.com`` in the POOL department (returns the
      7-item pool checklist).
    * Places ``carlos@aquaterra.com`` in the LANDSCAPE department (returns
      the 10-item landscape checklist).
    * Provisions ``manager@aquaterra.com`` (role=manager, password123)
      and Workstream is denied to that role.

These tests intentionally hit the shared demo tenant — no per-test
tenant seeding — so a drift regression fires on the first CI run.
"""
from __future__ import annotations

import requests
import pytest

API = "http://localhost:8001/api"


def _login(email: str, pw: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login",
                        json={"email": email, "password": pw}, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _hdr(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}",
             "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def mike_hdr():
    return _hdr(_login("mike@aquaterra.com"))


@pytest.fixture(scope="module")
def carlos_hdr():
    return _hdr(_login("carlos@aquaterra.com"))


@pytest.fixture(scope="module")
def manager_hdr():
    return _hdr(_login("manager@aquaterra.com"))


POOL_LABELS = [
    "Skimmed Pool", "Brush Pool", "Checked Skimmer Basket",
    "Checked Pump Basket", "Tested Chemicals", "Checked Equipment",
    "Secured all Gates",
]
LANDSCAPE_LABELS = [
    "Sprayed or Pulled Weeds", "Checked Irrigation", "Trimmed Bushes",
    "Mowed Grass", "Edged Grass", "Blow Property", "Raked Rocks",
    "Locked Gate", "Trimmed Trees", "Irrigation Repair",
]


def test_mike_pool_department_daily_checklist(mike_hdr):
    r = requests.get(f"{API}/checklists/daily",
                        headers=mike_hdr, timeout=15)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["service_line"] == "pool"
    labels = [it["label"] for it in j["items"]]
    assert labels == POOL_LABELS
    assert j["count"] == 7


def test_carlos_landscape_department_daily_checklist(carlos_hdr):
    r = requests.get(f"{API}/checklists/daily",
                        headers=carlos_hdr, timeout=15)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["service_line"] == "landscape"
    labels = [it["label"] for it in j["items"]]
    assert labels == LANDSCAPE_LABELS
    assert j["count"] == 10


def test_manager_login_and_workstream_denied(manager_hdr):
    # Manager login itself already succeeded via the fixture.
    r = requests.get(f"{API}/workstream/jobs",
                        headers=manager_hdr, timeout=15)
    assert r.status_code == 403, r.text


def test_manager_role_shape():
    """Sanity: /api/auth/me exposes the manager role verbatim so
    front-end guards + tests key off the correct string."""
    tok = _login("manager@aquaterra.com")
    r = requests.get(f"{API}/auth/me", headers=_hdr(tok), timeout=15)
    assert r.status_code == 200, r.text
    me = r.json()
    assert me["email"] == "manager@aquaterra.com"
    assert me["role"] == "manager"
