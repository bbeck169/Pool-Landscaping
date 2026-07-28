"""Task RR/SS Phase 2 follow-on · Feb 2026 — persona ``avatar_url`` wire-up tests.

Covers:
  1. ``GET /api/admin/ai-personas-scope`` includes ``avatar_url`` on
     every canonical persona row, matching the ``/avatars/personas/<key>.jpg``
     convention.
  2. ``PATCH /api/ai-employees/{eid}`` accepts + persists ``avatar_url``.
"""
from __future__ import annotations

import asyncio
import os

import pytest
import requests

BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or "http://localhost:8001").rstrip("/")
API = f"{BASE_URL}/api"

CANONICAL_KEYS = {
    "casey", "emmie", "buddy", "vizzy", "dexter",
    "soshie", "scouty", "commet", "skedra", "billy",
}


def _sync(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _login(email: str, pw: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login",
                        json={"email": email, "password": pw}, timeout=30)
    r.raise_for_status()
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def admin_headers():
    return {"Authorization": f"Bearer {_login('manager@aquaterra.com')}"}


@pytest.fixture(scope="module")
def super_headers():
    return {"Authorization": f"Bearer {_login('super@aquaterra.com')}"}


def test_personas_scope_response_includes_avatar_url(admin_headers):
    r = requests.get(f"{API}/admin/ai-personas-scope",
                        headers=admin_headers, timeout=30)
    assert r.status_code == 200, r.text
    items = r.json().get("items") or []
    assert len(items) >= 10, f"expected ≥10 personas, got {len(items)}"
    keys_seen = set()
    for row in items:
        assert "avatar_url" in row, f"missing avatar_url on {row.get('key')}"
        if row["key"] in CANONICAL_KEYS:
            keys_seen.add(row["key"])
            assert row["avatar_url"] == f"/avatars/personas/{row['key']}.jpg", (
                f"unexpected avatar_url on {row['key']}: {row['avatar_url']!r}"
            )
    # All 10 canonical personas surfaced.
    assert keys_seen == CANONICAL_KEYS, f"missing keys: {CANONICAL_KEYS - keys_seen}"


def test_patch_avatar_url_persists(super_headers):
    # Grab any persona id.
    r = requests.get(f"{API}/admin/ai-personas-scope",
                        headers=super_headers, timeout=30)
    r.raise_for_status()
    row = next(x for x in r.json()["items"] if x["key"] == "skedra")
    eid = row["id"]
    original = row.get("avatar_url")
    try:
        new_url = "/avatars/personas/skedra.jpg?v=test"
        pr = requests.patch(
            f"{API}/ai-employees/{eid}",
            headers={**super_headers, "Content-Type": "application/json"},
            json={"avatar_url": new_url}, timeout=30,
        )
        assert pr.status_code == 200, pr.text
        assert pr.json().get("avatar_url") == new_url
        # Read back via the scope endpoint too — verify projection matches.
        rr = requests.get(f"{API}/admin/ai-personas-scope",
                            headers=super_headers, timeout=30)
        rr.raise_for_status()
        again = next(x for x in rr.json()["items"] if x["id"] == eid)
        assert again["avatar_url"] == new_url
    finally:
        # Restore.
        requests.patch(
            f"{API}/ai-employees/{eid}",
            headers={**super_headers, "Content-Type": "application/json"},
            json={"avatar_url": original}, timeout=30,
        )


def test_patch_rejects_avatar_url_over_max_length(super_headers):
    r = requests.get(f"{API}/admin/ai-personas-scope",
                        headers=super_headers, timeout=30)
    r.raise_for_status()
    eid = next(x["id"] for x in r.json()["items"] if x["key"] == "casey")
    # 1025 chars — one over the Pydantic max_length ceiling.
    too_long = "/" + ("a" * 1025)
    pr = requests.patch(
        f"{API}/ai-employees/{eid}",
        headers={**super_headers, "Content-Type": "application/json"},
        json={"avatar_url": too_long}, timeout=30,
    )
    assert pr.status_code in (400, 422), pr.text
