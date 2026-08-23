"""D2-hotfix · Feb-2026 — customer portal home 500 regression.

**Root cause**: ``routers/dashboard.py`` used to import
``not_deleted_filter as _nd`` inside the ``technician`` branch only.
Customer and admin branches both referenced ``_nd()`` further down, so
Python raised ``UnboundLocalError`` (``_nd`` was treated as a local
because it was assigned inside the same function) — which surfaced as
HTTP 500 on the mobile customer portal home screen (``app/portal/home.tsx``
``load()`` fires ``GET /dashboard`` in a ``Promise.all`` and it is the
only one of the four requests without a ``.catch()`` fallback).

**Fix**: hoist the import to module level.

This test locks in the fix by hitting ``/api/dashboard`` as each of the
three roles that exercise a different branch:

* ``customer@aquaterra.com`` — the reported repro (line 50 branch).
* ``carlos@aquaterra.com`` — technician branch (should never regress).
* ``super@aquaterra.com`` — admin/super_admin branch (line 113,
  latent same-bug that would fire once the technician branch is
  bypassed).

If the module-scope import is ever regressed back into a nested branch,
whichever branch's caller runs will 500 and this test will catch it.
"""
from __future__ import annotations

import requests

API = "http://localhost:8001/api"


def _login(email: str) -> str:
    r = requests.post(
        f"{API}/auth/login",
        json={"email": email, "password": "password123"},
        timeout=30,
    )
    assert r.status_code == 200, f"login failed for {email}: {r.status_code} {r.text}"
    return r.json()["access_token"]


def _dashboard(email: str) -> dict:
    tok = _login(email)
    r = requests.get(
        f"{API}/dashboard",
        headers={"Authorization": f"Bearer {tok}"},
        timeout=30,
    )
    assert r.status_code == 200, (
        f"/api/dashboard as {email} returned {r.status_code} — "
        f"D2 hotfix regressed. Body: {r.text[:400]}"
    )
    return r.json()


def test_dashboard_customer_role_no_500():
    """Reproduces the exact failure reported from mobile portal home."""
    data = _dashboard("customer@aquaterra.com")
    assert data.get("role") == "customer"
    # Shape sanity: the four fields consumed by mobile portal home.tsx
    # (outstanding, active_jobs, completed_jobs, next_service) must be
    # present so the RN screen can render without secondary crashes.
    for key in ("outstanding", "active_jobs", "completed_jobs"):
        assert key in data, f"customer dashboard missing key: {key}"
    # next_service may be None (no upcoming job) but the key must exist.
    assert "next_service" in data


def test_dashboard_technician_role_no_500():
    """Technician branch was the only one importing _nd — must still work."""
    data = _dashboard("carlos@aquaterra.com")
    assert data.get("role") == "technician"
    assert "upcoming_jobs" in data


def test_dashboard_admin_role_no_500():
    """Admin branch also referenced _nd() (line 113) — same latent bug."""
    data = _dashboard("super@aquaterra.com")
    assert data.get("role") in ("admin", "super_admin")
    assert "revenue" in data
    assert "revenue_by_service" in data
