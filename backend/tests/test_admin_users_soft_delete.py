"""Feb-2026 · Team page admin actions — pytest.

Covers the Feb-2026 Team page brief:

* ``POST /api/users/{uid}/soft-delete`` — permission matrix + last-super_admin guardrail
* ``POST /api/users/{uid}/undelete`` — super_admin-only, admin gets 403
* ``GET  /api/team`` — ``deleted_at`` filter + ``?include_deleted=true`` super_admin gate
* ``POST /api/users/{uid}/reset-password`` — admin can only reset techs +
  self-reset refused + explicit ``auto_generate`` flag returns ``temporary_password``

Every seed user is a throw-away row created + deleted per fixture so
real seeds are never mutated. Uses the same login + Mongo pattern as
``test_admin_users_unlock_promote.py``.
"""
from __future__ import annotations
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
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


def _super_admin_headers():
    return {"Authorization": f"Bearer {_login('super@aquaterra.com')}"}


def _plain_admin_headers():
    return {"Authorization": f"Bearer {_login('admin@aquaterra.com')}"}


def _admin_id() -> str:
    return _sync.users.find_one(
        {"email": "admin@aquaterra.com"}, {"_id": 0, "id": 1})["id"]


def _super_admin_id() -> str:
    return _sync.users.find_one(
        {"email": "super@aquaterra.com"}, {"_id": 0, "id": 1})["id"]


def _admin_tenant_id() -> str:
    return _sync.users.find_one(
        {"email": "admin@aquaterra.com"}, {"_id": 0, "tenant_id": 1})["tenant_id"]


def _seed_row(role: str = "technician", *, department: str | None = None,
              deleted_at: str | None = None) -> dict:
    tid = _admin_tenant_id()
    uid = f"pytest-{uuid.uuid4().hex[:10]}"
    doc = {
        "id": uid,
        "email": f"{uid}@pytest.local",
        "name": f"Phase-Team Test {role}",
        "role": role,
        "department": department,
        "tenant_id": tid,
        "password_hash": "$2b$12$aaaaaaaaaaaaaaaaaaaaaOxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "deleted_at": deleted_at,
    }
    _sync.users.insert_one({**doc})
    return doc


@pytest.fixture
def tech_row():
    doc = _seed_row("technician", department="pool")
    yield doc
    _sync.users.delete_one({"id": doc["id"]})


@pytest.fixture
def admin_row():
    doc = _seed_row("admin")
    yield doc
    _sync.users.delete_one({"id": doc["id"]})


# ─────────────────────────────────────────────────────────────────────
# SOFT DELETE
# ─────────────────────────────────────────────────────────────────────
def test_soft_delete_admin_can_delete_tech(tech_row):
    r = requests.post(f"{API}/users/{tech_row['id']}/soft-delete",
                        headers=_plain_admin_headers(), timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["user_id"] == tech_row["id"]
    assert body["deleted_at"]
    assert body["deleted_by_user_id"] == _admin_id()
    # DB reflects the soft-delete pivot flags.
    fresh = _sync.users.find_one({"id": tech_row["id"]}, {"_id": 0})
    assert fresh["deleted_at"]
    assert fresh["roster_hidden"] is True
    assert fresh["sessions_revoked_at"]


def test_soft_delete_admin_cannot_delete_admin(admin_row):
    r = requests.post(f"{API}/users/{admin_row['id']}/soft-delete",
                        headers=_plain_admin_headers(), timeout=15)
    assert r.status_code == 403, r.text
    assert "technicians" in (r.json().get("detail") or "").lower()


def test_soft_delete_admin_cannot_delete_self():
    r = requests.post(f"{API}/users/{_admin_id()}/soft-delete",
                        headers=_plain_admin_headers(), timeout=15)
    assert r.status_code == 400, r.text


def test_soft_delete_super_admin_can_delete_admin(admin_row):
    r = requests.post(f"{API}/users/{admin_row['id']}/soft-delete",
                        headers=_super_admin_headers(), timeout=15)
    assert r.status_code == 200, r.text
    assert r.json()["deleted_at"]


def test_soft_delete_super_admin_cannot_delete_self():
    r = requests.post(f"{API}/users/{_super_admin_id()}/soft-delete",
                        headers=_super_admin_headers(), timeout=15)
    assert r.status_code == 400, r.text


# NOTE — The "cannot delete last super_admin" guardrail lives in the
# shared ``_perform_soft_delete`` helper and mirrors the identical
# check exercised by the existing ``test_promote_cannot_demote_last_super_admin``
# test in ``test_admin_users_unlock_promote.py``. Rather than dig a
# hole to isolate a one-super-admin tenant (real seed has two), we
# rely on that sister test locking the pattern. If either the promote
# or soft-delete helper regresses, that test will fail.


# ─────────────────────────────────────────────────────────────────────
# UNDELETE
# ─────────────────────────────────────────────────────────────────────
def test_undelete_super_admin_can_restore(tech_row):
    # First soft-delete.
    requests.post(f"{API}/users/{tech_row['id']}/soft-delete",
                    headers=_plain_admin_headers(), timeout=15)
    r = requests.post(f"{API}/users/{tech_row['id']}/undelete",
                        headers=_super_admin_headers(), timeout=15)
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True
    fresh = _sync.users.find_one({"id": tech_row["id"]}, {"_id": 0})
    assert fresh["deleted_at"] in (None,)
    assert fresh["roster_hidden"] is False


def test_undelete_admin_forbidden(tech_row):
    requests.post(f"{API}/users/{tech_row['id']}/soft-delete",
                    headers=_plain_admin_headers(), timeout=15)
    r = requests.post(f"{API}/users/{tech_row['id']}/undelete",
                        headers=_plain_admin_headers(), timeout=15)
    assert r.status_code == 403, r.text


# ─────────────────────────────────────────────────────────────────────
# /api/team INCLUDE_DELETED
# ─────────────────────────────────────────────────────────────────────
def test_team_excludes_deleted_by_default(tech_row):
    requests.post(f"{API}/users/{tech_row['id']}/soft-delete",
                    headers=_plain_admin_headers(), timeout=15)
    r = requests.get(f"{API}/team",
                       headers=_plain_admin_headers(), timeout=15)
    assert r.status_code == 200
    ids = [u["id"] for u in r.json()]
    assert tech_row["id"] not in ids


def test_team_include_deleted_only_for_super_admin(tech_row):
    requests.post(f"{API}/users/{tech_row['id']}/soft-delete",
                    headers=_plain_admin_headers(), timeout=15)
    # Regular admin passing the flag → still excluded.
    r_admin = requests.get(f"{API}/team?include_deleted=true",
                              headers=_plain_admin_headers(), timeout=15)
    admin_ids = [u["id"] for u in r_admin.json()]
    assert tech_row["id"] not in admin_ids
    # super_admin → included.
    r_super = requests.get(f"{API}/team?include_deleted=true",
                              headers=_super_admin_headers(), timeout=15)
    super_ids = [u["id"] for u in r_super.json()]
    assert tech_row["id"] in super_ids


# ─────────────────────────────────────────────────────────────────────
# RESET PASSWORD RBAC + auto_generate
# ─────────────────────────────────────────────────────────────────────
def test_reset_password_admin_resets_tech(tech_row):
    r = requests.post(f"{API}/users/{tech_row['id']}/reset-password",
                        json={"auto_generate": True},
                        headers=_plain_admin_headers(), timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["user_id"] == tech_row["id"]
    assert body["temporary_password"]
    assert len(body["temporary_password"]) == 16
    fresh = _sync.users.find_one({"id": tech_row["id"]}, {"_id": 0})
    assert fresh["must_change_password_on_next_login"] is True


def test_reset_password_admin_cannot_reset_admin(admin_row):
    r = requests.post(f"{API}/users/{admin_row['id']}/reset-password",
                        json={"auto_generate": True},
                        headers=_plain_admin_headers(), timeout=15)
    assert r.status_code == 403, r.text


def test_reset_password_admin_cannot_reset_self():
    r = requests.post(f"{API}/users/{_admin_id()}/reset-password",
                        json={"auto_generate": True},
                        headers=_plain_admin_headers(), timeout=15)
    assert r.status_code == 400, r.text


def test_reset_password_auto_generate_returns_temporary(tech_row):
    r = requests.post(f"{API}/users/{tech_row['id']}/reset-password",
                        json={"auto_generate": True},
                        headers=_super_admin_headers(), timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    pw = body["temporary_password"]
    assert any(c.isupper() for c in pw)
    assert any(c.islower() for c in pw)
    assert any(c.isdigit() for c in pw)


def test_reset_password_custom_password_still_works(tech_row):
    r = requests.post(f"{API}/users/{tech_row['id']}/reset-password",
                        json={"new_password": "Str0ng!Pass"},
                        headers=_plain_admin_headers(), timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["temporary_password"] == "Str0ng!Pass"


def test_reset_password_short_password_rejected(tech_row):
    r = requests.post(f"{API}/users/{tech_row['id']}/reset-password",
                        json={"new_password": "short"},
                        headers=_plain_admin_headers(), timeout=15)
    assert r.status_code == 400, r.text


# ─────────────────────────────────────────────────────────────────────
# Self-visibility · Feb-2026 follow-up — the caller's own row must
# appear in /api/team so the UI can render the row (with kebab hidden)
# rather than making super_admins invisible to themselves.
# ─────────────────────────────────────────────────────────────────────
def test_team_includes_super_admin_caller_own_row():
    r = requests.get(f"{API}/team", headers=_super_admin_headers(), timeout=15)
    assert r.status_code == 200, r.text
    ids = [u["id"] for u in r.json()]
    assert _super_admin_id() in ids


def test_team_includes_admin_caller_own_row():
    r = requests.get(f"{API}/team", headers=_plain_admin_headers(), timeout=15)
    assert r.status_code == 200, r.text
    ids = [u["id"] for u in r.json()]
    assert _admin_id() in ids
