"""Phase 20A.1 · Cross-tenant hardening for `POST /api/schedule/optimize-route`.

These tests complement `test_phase20a.py` (which covers ordering, cache, and
tech-cross-tenant rejection). Here we lock down the admin-override path so
`user_id` cannot be used to peek across tenants or to plan for phantom users.
"""
import uuid
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
    r.raise_for_status()
    return r.json()


@pytest.fixture(scope="module")
def dbc(): return MongoClient(MONGO_URL)[DB_NAME]


@pytest.fixture(scope="module")
def sunbelt_admin_h():
    try:
        return {"Authorization": f"Bearer {_login('admin@sunbelt.com')['access_token']}"}
    except Exception:
        pytest.skip("sunbelt admin missing")


@pytest.fixture(scope="module")
def aquaterra_admin_h():
    return {"Authorization": f"Bearer {_login('admin@aquaterra.com')['access_token']}"}


@pytest.fixture(scope="module")
def aquaterra_tech_h():
    return {"Authorization": f"Bearer {_login('mike@aquaterra.com')['access_token']}"}


def test_optimize_route_cross_tenant_403(sunbelt_admin_h, dbc):
    """Sunbelt admin passing an Aquaterra user_id must be rejected."""
    aqua_u = dbc.users.find_one({"email": "mike@aquaterra.com"})
    assert aqua_u, "expected mike@aquaterra.com to exist in seeded db"
    r = requests.post(f"{API}/schedule/optimize-route?user_id=" + aqua_u["id"],
                      headers=sunbelt_admin_h, json={}, timeout=15)
    assert r.status_code == 403, f"expected 403 cross-tenant, got {r.status_code} {r.text[:200]}"
    assert "not in current tenant" in r.text


def test_optimize_route_nonexistent_user_404(aquaterra_admin_h):
    """Admin passing a fake user_id must be rejected with 404."""
    ghost = str(uuid.uuid4())
    r = requests.post(f"{API}/schedule/optimize-route?user_id=" + ghost,
                      headers=aquaterra_admin_h, json={}, timeout=15)
    assert r.status_code == 404, f"expected 404 ghost user, got {r.status_code} {r.text[:200]}"


def test_optimize_route_tech_cannot_plan_other_user_403(aquaterra_tech_h, dbc):
    """A technician cannot pass a user_id different from their own."""
    other = dbc.users.find_one({"email": "admin@aquaterra.com"})  # same tenant, different user
    assert other, "expected admin@aquaterra.com to exist"
    r = requests.post(f"{API}/schedule/optimize-route?user_id=" + other["id"],
                      headers=aquaterra_tech_h, json={}, timeout=15)
    assert r.status_code == 403, f"expected 403 tech-other-user, got {r.status_code} {r.text[:200]}"
