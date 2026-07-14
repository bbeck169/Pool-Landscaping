"""Phase 20B module B — Referral Revenue tile data contract.

Verifies the dashboard tile can rely on `analytics/v2` returning the
`revenue_attribution.total_usd` and `funnel.converted` fields.
"""
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values

_FE = dotenv_values(Path(__file__).resolve().parents[2] / "frontend" / ".env")
BASE = (_FE.get("EXPO_PUBLIC_BACKEND_URL") or "http://localhost:8001").rstrip("/")
API = f"{BASE}/api"


def _login(email, pw="password123"):
    r = requests.post(f"{API}/auth/login",
                      json={"email": email, "password": pw}, timeout=15)
    r.raise_for_status()
    return r.json()


@pytest.fixture(scope="module")
def admin_h():
    return {"Authorization": f"Bearer {_login('admin@aquaterra.com')['access_token']}"}


def test_referral_revenue_tile_fields_present(admin_h):
    r = requests.get(f"{API}/referrals/admin/analytics/v2",
                     headers=admin_h, timeout=15).json()
    assert "revenue_attribution" in r
    assert "total_usd" in r["revenue_attribution"]
    assert isinstance(r["revenue_attribution"]["total_usd"], (int, float))

    assert "funnel" in r
    assert "converted" in r["funnel"]
    assert isinstance(r["funnel"]["converted"], int)
