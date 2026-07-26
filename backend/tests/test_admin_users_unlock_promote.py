"""Feb-2026 · Phase 26 Path B · super_admin ops endpoints — pytest.

Covers ``POST /api/users/{uid}/unlock`` + ``POST /api/users/{uid}/promote``:

* Auth gate: non-super_admin → 403 on both.
* Unlock: seeded lockout is cleared; returns ``was_locked=true``.
* Unlock: idempotent — ``was_locked=false`` on already-unlocked user.
* Unlock: 400 for unknown user.
* Promote: happy path admin → super_admin.
* Promote: self-role change refused.
* Promote: last remaining super_admin cannot be demoted.
* Promote: invalid role rejected with 400.
* Promote: 400 for unknown user.
"""
from __future__ import annotations
import os
import uuid
from datetime import datetime, timedelta, timezone
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


def _admin_tenant_id() -> str:
    return _sync.users.find_one(
        {"email": "admin@aquaterra.com"}, {"_id": 0, "tenant_id": 1})["tenant_id"]


@pytest.fixture
def seed_user():
    """Seed a fresh throw-away user in the aquaterra tenant. Yields the
    doc and deletes it on teardown so tests never mutate real seeds."""
    tid = _admin_tenant_id()
    uid = f"pytest-{uuid.uuid4().hex[:10]}"
    doc = {
        "id": uid,
        "email": f"{uid}@pytest.local",
        "name": "Phase 26B Test",
        "role": "admin",
        "tenant_id": tid,
        "password_hash": "$2b$12$aaaaaaaaaaaaaaaaaaaaaOxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
        "failed_login_attempts": 0,
        "lockout_until": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _sync.users.insert_one({**doc})
    yield doc
    _sync.users.delete_one({"id": uid})


# ─────────────────────────────────────────────────────────────────────
# UNLOCK
# ─────────────────────────────────────────────────────────────────────
def test_unlock_requires_super_admin(seed_user):
    r = requests.post(f"{API}/users/{seed_user['id']}/unlock",
                        headers=_plain_admin_headers(), timeout=15)
    assert r.status_code == 403, r.text


def test_unlock_clears_a_locked_account(seed_user):
    """Seed a lockout, hit /unlock as super_admin, verify both fields cleared."""
    _sync.users.update_one(
        {"id": seed_user["id"]},
        {"$set": {"failed_login_attempts": 5,
                    "lockout_until": (datetime.now(timezone.utc)
                                        + timedelta(minutes=15)).isoformat()}},
    )
    r = requests.post(f"{API}/users/{seed_user['id']}/unlock",
                        headers=_super_admin_headers(), timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["user_id"] == seed_user["id"]
    assert body["was_locked"] is True
    assert body["cleared_at"]
    row = _sync.users.find_one({"id": seed_user["id"]})
    assert row["failed_login_attempts"] == 0
    assert row["lockout_until"] is None
    assert row["unlocked_at"] == body["cleared_at"]


def test_unlock_is_idempotent(seed_user):
    """Calling unlock on an already-unlocked user returns was_locked=false."""
    r = requests.post(f"{API}/users/{seed_user['id']}/unlock",
                        headers=_super_admin_headers(), timeout=15)
    assert r.status_code == 200, r.text
    assert r.json()["was_locked"] is False


def test_unlock_400_when_user_missing():
    bogus = f"does-not-exist-{uuid.uuid4().hex[:8]}"
    r = requests.post(f"{API}/users/{bogus}/unlock",
                        headers=_super_admin_headers(), timeout=15)
    assert r.status_code == 400, r.text
    assert "not found" in r.text.lower()


# ─────────────────────────────────────────────────────────────────────
# PROMOTE
# ─────────────────────────────────────────────────────────────────────
def test_promote_requires_super_admin(seed_user):
    r = requests.post(f"{API}/users/{seed_user['id']}/promote",
                        headers=_plain_admin_headers(),
                        json={"role": "super_admin"}, timeout=15)
    assert r.status_code == 403, r.text


def test_promote_happy_path_admin_to_super_admin(seed_user):
    r = requests.post(f"{API}/users/{seed_user['id']}/promote",
                        headers=_super_admin_headers(),
                        json={"role": "super_admin"}, timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["old_role"] == "admin"
    assert body["new_role"] == "super_admin"
    row = _sync.users.find_one({"id": seed_user["id"]})
    assert row["role"] == "super_admin"
    assert row["role_changed_at"]


def test_promote_refuses_self_role_change():
    """super@aquaterra.com trying to change their OWN role → 400."""
    super_row = _sync.users.find_one({"email": "super@aquaterra.com"},
                                        {"_id": 0, "id": 1})
    r = requests.post(f"{API}/users/{super_row['id']}/promote",
                        headers=_super_admin_headers(),
                        json={"role": "admin"}, timeout=15)
    assert r.status_code == 400, r.text
    assert "your own role" in r.text.lower()


def test_promote_refuses_demoting_last_super_admin():
    """Seed an isolated pytest tenant containing exactly ONE super_admin,
    then attempt to demote them via the aquaterra super@ caller. The
    ``last super_admin`` guardrail counts other super_admins in the
    TARGET's tenant, so it should fire regardless of the caller's tenant.
    """
    pytest_tenant = f"pytest-tenant-{uuid.uuid4().hex[:10]}"
    target_id = f"pytest-lone-super-{uuid.uuid4().hex[:8]}"
    pw_hash = _sync.users.find_one(
        {"email": "super@aquaterra.com"}, {"_id": 0, "password_hash": 1}
    )["password_hash"]
    _sync.users.insert_one({
        "id": target_id,
        "email": f"{target_id}@pytest.local",
        "name": "Lone super in pytest tenant",
        "role": "super_admin",
        "tenant_id": pytest_tenant,
        "password_hash": pw_hash,
        "failed_login_attempts": 0,
        "lockout_until": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    try:
        # Sanity: this user IS the only super_admin in that tenant.
        assert _sync.users.count_documents({
            "tenant_id": pytest_tenant, "role": "super_admin",
        }) == 1
        r = requests.post(f"{API}/users/{target_id}/promote",
                            headers=_super_admin_headers(),
                            json={"role": "admin"}, timeout=15)
        assert r.status_code == 400, r.text
        assert "last" in r.text.lower()
        # Confirm the record wasn't mutated.
        row = _sync.users.find_one({"id": target_id})
        assert row["role"] == "super_admin"
    finally:
        _sync.users.delete_one({"id": target_id})


def test_promote_rejects_invalid_role(seed_user):
    r = requests.post(f"{API}/users/{seed_user['id']}/promote",
                        headers=_super_admin_headers(),
                        json={"role": "wizard"}, timeout=15)
    assert r.status_code == 400, r.text
    assert "invalid role" in r.text.lower()


def test_promote_400_when_user_missing():
    bogus = f"does-not-exist-{uuid.uuid4().hex[:8]}"
    r = requests.post(f"{API}/users/{bogus}/promote",
                        headers=_super_admin_headers(),
                        json={"role": "admin"}, timeout=15)
    assert r.status_code == 400, r.text
    assert "not found" in r.text.lower()
