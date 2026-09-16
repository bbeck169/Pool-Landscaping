"""Phase D1 · Feb 2026 — /api/checklists/industry/{slug} for all 23.

Loops the endpoint across every canonical slug and asserts:
  * HTTP 200
  * response body carries ``industry == slug``
  * ``items`` is a non-empty list (default OR override)
"""
from __future__ import annotations

import os

import pytest

from tests._phase34_http_shim import http

BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or "http://localhost:8001").rstrip("/")
API = f"{BASE_URL}/api"


def _login(email: str, pw: str = "password123") -> str:
    r = http.post(f"{API}/auth/login",
                        json={"email": email, "password": pw}, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def super_headers():
    return {"Authorization": f"Bearer {_login('super@aquaterra.com')}",
            "Content-Type": "application/json"}


ALL_SLUGS = [
    "pool", "landscaping", "hvac", "pest_control",
    "cleaning", "solar", "handyman",
    "plumbing", "electrical", "roofing", "painting",
    "garage_door", "appliance_repair", "locksmith",
    "chimney_sweep", "gutter", "window_cleaning",
    "carpet_cleaning", "pressure_washing", "tree_service",
    "snow_removal", "fencing", "irrigation",
]


@pytest.mark.parametrize("slug", ALL_SLUGS)
def test_get_endpoint_returns_non_empty_template(slug: str, super_headers):
    r = http.get(f"{API}/checklists/industry/{slug}",
                     headers=super_headers, timeout=30)
    assert r.status_code == 200, f"{slug} → {r.status_code} {r.text[:200]}"
    body = r.json()
    assert body["industry"] == slug, (
        f"expected industry={slug!r}, got {body.get('industry')!r}"
    )
    items = body.get("items") or []
    assert isinstance(items, list) and len(items) >= 1, (
        f"{slug} → items empty or malformed: {items!r}"
    )
    # Every item carries the canonical shape.
    for row in items:
        assert isinstance(row, dict), f"{slug}: non-dict row {row!r}"
        assert row.get("key") and row.get("label"), (
            f"{slug}: row missing key/label — {row!r}"
        )
        assert "required" in row, f"{slug}: row missing required flag"
