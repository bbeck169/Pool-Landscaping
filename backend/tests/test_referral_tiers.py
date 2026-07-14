"""Phase 20B.4 — Referral tiered rewards + advanced analytics."""
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

_FE = dotenv_values(Path(__file__).resolve().parents[2] / "frontend" / ".env")
_BE = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
BASE = (_FE.get("EXPO_PUBLIC_BACKEND_URL") or "http://localhost:8001").rstrip("/")
API = f"{BASE}/api"
MONGO_URL = _BE.get("MONGO_URL"); DB_NAME = _BE.get("DB_NAME")


def _login(email, pw="password123"):
    r = requests.post(f"{API}/auth/login",
                      json={"email": email, "password": pw}, timeout=15)
    r.raise_for_status(); return r.json()


@pytest.fixture(scope="module")
def dbc(): return MongoClient(MONGO_URL)[DB_NAME]

@pytest.fixture(scope="module")
def admin_h(): return {"Authorization": f"Bearer {_login('admin@aquaterra.com')['access_token']}"}


def test_settings_get_default_and_put(admin_h, dbc):
    g = requests.get(f"{API}/referrals/settings", headers=admin_h, timeout=15).json()
    assert "tiers" in g and len(g["tiers"]) >= 1

    # Set 3 tiers
    body = {"tiers": [
        {"conversion_min": 1, "conversion_max": 1, "credit_pct": 25, "credit_months": 1},
        {"conversion_min": 2, "conversion_max": 3, "credit_pct": 50, "credit_months": 1},
        {"conversion_min": 4, "conversion_max": 999, "credit_pct": 50, "credit_months": 2},
    ]}
    p = requests.put(f"{API}/referrals/settings", headers=admin_h,
                     json=body, timeout=15).json()
    assert len(p["tiers"]) == 3


def test_settings_reject_overlap(admin_h):
    body = {"tiers": [
        {"conversion_min": 1, "conversion_max": 5, "credit_pct": 25, "credit_months": 1},
        {"conversion_min": 3, "conversion_max": 10, "credit_pct": 50, "credit_months": 1},
    ]}
    r = requests.put(f"{API}/referrals/settings", headers=admin_h,
                     json=body, timeout=15)
    assert r.status_code == 400


def test_tier_picker_returns_correct_tier(admin_h):
    # Set the 3-tier config first.
    requests.put(f"{API}/referrals/settings", headers=admin_h, json={"tiers": [
        {"conversion_min": 1, "conversion_max": 1, "credit_pct": 25, "credit_months": 1},
        {"conversion_min": 2, "conversion_max": 3, "credit_pct": 50, "credit_months": 1},
        {"conversion_min": 4, "conversion_max": 999, "credit_pct": 50, "credit_months": 2},
    ]}, timeout=15)
    # Import the picker directly.
    from routers.referral_tiers import pick_tier
    settings = {"tiers": [
        {"conversion_min": 1, "conversion_max": 1, "credit_pct": 25, "credit_months": 1},
        {"conversion_min": 2, "conversion_max": 3, "credit_pct": 50, "credit_months": 1},
        {"conversion_min": 4, "conversion_max": 999, "credit_pct": 50, "credit_months": 2},
    ]}
    assert pick_tier(settings, 1)["credit_pct"] == 25
    assert pick_tier(settings, 2)["credit_pct"] == 50
    assert pick_tier(settings, 3)["credit_pct"] == 50
    assert pick_tier(settings, 3)["credit_months"] == 1
    assert pick_tier(settings, 4)["credit_months"] == 2
    assert pick_tier(settings, 100)["credit_months"] == 2


def test_analytics_v2_returns_all_sections(admin_h):
    r = requests.get(f"{API}/referrals/admin/analytics/v2",
                     headers=admin_h, timeout=15).json()
    assert set(r.keys()) >= {"funnel", "revenue_attribution", "cohort_curve", "leaderboard"}
    fun = r["funnel"]
    for k in ("invites", "signups", "converted", "credits_redeemed"):
        assert k in fun and isinstance(fun[k], int)
    lb = r["leaderboard"]
    assert lb["page"] == 1 and lb["size"] == 10 and "rows" in lb
