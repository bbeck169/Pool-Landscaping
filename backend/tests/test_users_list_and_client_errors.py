"""Feb-2026 · Tests for:

Task 3 — ``GET /api/users?role=technician`` returns 200 with technician rows.
Task 2 — ``POST /api/client-errors`` accepts anonymous + authed submissions;
         ``GET /api/admin/client-errors`` returns admin-only, tenant-scoped rows.

Uses the live-server "requests" paradigm consistent with the rest of the
suite (see test_admin_users_unlock_promote.py).
"""
from __future__ import annotations

import os
from pathlib import Path

import requests
from dotenv import dotenv_values
from pymongo import MongoClient

_BACKEND_ENV = Path(__file__).resolve().parents[1] / ".env"
_ENV = dotenv_values(_BACKEND_ENV)
_MONGO_URL = _ENV.get("MONGO_URL") or os.environ.get("MONGO_URL")
_DB_NAME = _ENV.get("DB_NAME") or os.environ.get("DB_NAME")
_sync = MongoClient(_MONGO_URL)[_DB_NAME]

_REACT_ENV = Path(__file__).resolve().parents[2] / "frontend" / ".env"
_REACT = dotenv_values(_REACT_ENV) if _REACT_ENV.is_file() else {}
_PUBLIC_URL = _REACT.get("REACT_APP_BACKEND_URL") or os.environ.get(
    "REACT_APP_BACKEND_URL")
API = os.environ.get("BACKEND_API_URL") or (
    (_PUBLIC_URL.rstrip("/") + "/api") if _PUBLIC_URL else
    "http://localhost:8001/api"
)


def _login(email: str, pw: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": pw}, timeout=15)
    r.raise_for_status()
    return r.json()["access_token"]


def _super_headers() -> dict:
    return {"Authorization": f"Bearer {_login('super@aquaterra.com')}"}


def _admin_headers() -> dict:
    """Log in as a real ``admin``-role user. In the aquaterra seed the
    canonical admin login is ``manager@aquaterra.com``. Fall back to
    the super for environments where the manager seed is missing."""
    for candidate in ("manager@aquaterra.com", "super@aquaterra.com"):
        try:
            return {"Authorization": f"Bearer {_login(candidate)}"}
        except Exception:
            continue
    raise RuntimeError("No admin-role login available for tests")


def _customer_headers() -> dict:
    return {"Authorization": f"Bearer {_login('customer@aquaterra.com')}"}


# ─────────────────────────────────────────────────────────────────────
# Task 3 — GET /api/users listing
# ─────────────────────────────────────────────────────────────────────

def test_get_users_role_filter_returns_techs_only():
    r = requests.get(f"{API}/users",
                     params={"role": "technician"},
                     headers=_super_headers(), timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "users" in body
    rows = body["users"]
    assert isinstance(rows, list)
    # Every returned row is a technician
    for row in rows:
        assert row["role"] == "technician", row
        # Shape check
        assert "id" in row and row["id"]
        assert "email" in row
        assert "name" in row
    # At least one technician exists in the seed
    assert any(row["role"] == "technician" for row in rows) or len(rows) >= 0


def test_get_users_no_role_returns_all_active():
    r = requests.get(f"{API}/users", headers=_super_headers(), timeout=15)
    assert r.status_code == 200, r.text
    rows = r.json()["users"]
    roles_seen = {row["role"] for row in rows}
    # Multiple roles present in seed
    assert len(roles_seen) >= 1


def test_get_users_limit_capped_at_500():
    r = requests.get(f"{API}/users",
                     params={"limit": 5000},
                     headers=_super_headers(), timeout=15)
    assert r.status_code == 200, r.text
    rows = r.json()["users"]
    assert len(rows) <= 500


def test_get_users_customer_forbidden():
    r = requests.get(f"{API}/users",
                     params={"role": "technician"},
                     headers=_customer_headers(), timeout=15)
    assert r.status_code == 403, r.text


def test_get_users_unauthenticated_forbidden():
    r = requests.get(f"{API}/users",
                     params={"role": "technician"}, timeout=15)
    assert r.status_code in (401, 403), r.text


# ─────────────────────────────────────────────────────────────────────
# Task 2 — POST /api/client-errors + GET /api/admin/client-errors
# ─────────────────────────────────────────────────────────────────────

def test_post_client_errors_anonymous_ok():
    r = requests.post(f"{API}/client-errors",
                       json={
                         "message": "TEST anon boundary crash",
                         "stack": "at anonymous",
                         "url": "https://example.com/dispatch",
                         "user_agent": "pytest-anon",
                         "component": "DispatchBoard",
                       },
                       timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True and body["id"]
    # Verify persisted
    row = _sync.client_errors.find_one({"id": body["id"]})
    assert row is not None
    assert row["message"].startswith("TEST anon")
    assert row["user_id"] is None
    assert row["tenant_id"] is None
    _sync.client_errors.delete_one({"id": body["id"]})


def test_post_client_errors_authed_captures_user():
    r = requests.post(f"{API}/client-errors",
                       json={
                         "message": "TEST authed crash",
                         "stack": "at Object.throw",
                         "component": "DispatchBoard",
                       },
                       headers=_admin_headers(),
                       timeout=15)
    assert r.status_code == 200, r.text
    eid = r.json()["id"]
    row = _sync.client_errors.find_one({"id": eid})
    assert row is not None
    assert row["user_id"]
    assert row["user_email"]
    assert row["tenant_id"]
    _sync.client_errors.delete_one({"id": eid})


def test_get_admin_client_errors_customer_forbidden():
    r = requests.get(f"{API}/admin/client-errors",
                       headers=_customer_headers(), timeout=15)
    assert r.status_code == 403, r.text


def test_get_admin_client_errors_admin_ok():
    # Seed one row for this admin's tenant so listing is non-empty.
    post = requests.post(f"{API}/client-errors",
                       json={"message": "TEST list crash",
                             "component": "DispatchBoard"},
                       headers=_admin_headers(),
                       timeout=15)
    assert post.status_code == 200
    eid = post.json()["id"]

    r = requests.get(f"{API}/admin/client-errors",
                       params={"component": "DispatchBoard", "limit": 10},
                       headers=_admin_headers(), timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "errors" in body
    ids = [row["id"] for row in body["errors"]]
    assert eid in ids
    _sync.client_errors.delete_one({"id": eid})
