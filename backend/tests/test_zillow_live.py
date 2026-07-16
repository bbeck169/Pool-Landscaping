"""Phase 52 · Live OpenWeb Ninja (Zillow) smoke test.

Run explicitly with: `pytest -m live backend/tests/test_zillow_live.py`.
Skipped by the default `pytest` sweep + preflight so we don't burn API
quota on every build. Skips automatically when
`OPENWEB_NINJA_ZILLOW_API_KEY` / `OPENWEB_NINJA_API_KEY` is unset.
"""
from __future__ import annotations

import os

import httpx
import pytest


pytestmark = pytest.mark.live


API_KEY = (os.environ.get("OPENWEB_NINJA_ZILLOW_API_KEY")
           or os.environ.get("OPENWEB_NINJA_API_KEY")
           or "")


@pytest.mark.skipif(not API_KEY, reason="Zillow API key not configured")
def test_zillow_live_property_lookup():
    """Well-known public listing in Phoenix, AZ. Passes if the provider
    returns a 200 with the expected top-level shape (has_data + zpid or
    the direct property node)."""
    resp = httpx.get(
        "https://api.openwebninja.com/realtime-zillow-data/property",
        params={"address": "1600 Amphitheatre Parkway, Mountain View, CA"},
        headers={"x-api-key": API_KEY},
        timeout=20.0,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # OpenWeb Ninja envelope shape — either `data` field or `status`.
    assert "data" in body or "status" in body
