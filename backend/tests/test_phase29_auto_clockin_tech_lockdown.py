"""Phase 29 · Feb-2026 — backend enforcement of tech Auto Clock-In.

The mobile settings screen locks the <Switch> to ON for techs and
the background hook short-circuits ``isAutoClockinEnabled`` to
``true``. This suite verifies the third defence layer — the
backend ``PATCH /api/users/me`` endpoint MUST refuse to persist
``auto_clockin_enabled: false`` for a tech-role caller.

Scenarios:
  1. Tech PATCHing ``auto_clockin_enabled: false`` → 403, no DB
     mutation.
  2. Tech PATCHing ``auto_clockin_enabled: true`` (idempotent
     re-enable) → 200.
  3. Non-tech (admin) PATCHing ``auto_clockin_enabled: false`` →
     200 (behaviour unchanged for non-tech roles).
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

os.environ.setdefault("ALLOW_TEST_HOOKS", "1")

_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = MongoClient(_ENV["MONGO_URL"])[_ENV["DB_NAME"]]
API = "http://localhost:8001/api"

JWT_SECRET = _ENV.get("JWT_SECRET") or os.environ.get("JWT_SECRET") \
    or "dev-secret-change-me"
JWT_ALGO = _ENV.get("JWT_ALGO") or "HS256"


def _tok(user_id: str, email: str, role: str,
          tenant_id: str) -> str:
    return jwt.encode(
        {
            "sub": user_id, "email": email, "role": role,
            "tenant_id": tenant_id,
            "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        },
        JWT_SECRET, algorithm=JWT_ALGO,
    )


@pytest.fixture()
def tenant_id():
    tid = f"p29-{uuid.uuid4().hex[:8]}"
    _sync.tenants.insert_one({
        "id": tid, "name": f"P29 {tid}", "slug": f"p29-{tid}",
        "active": True,
    })
    yield tid
    _sync.tenants.delete_many({"tenant_id": tid})
    _sync.users.delete_many({"tenant_id": tid})


def _seed_user(tenant_id: str, role: str, *, ac: bool = True) -> dict:
    uid = f"{role}-{uuid.uuid4().hex[:8]}"
    email = f"{uid}@p29.test"
    _sync.users.insert_one({
        "id": uid, "tenant_id": tenant_id, "role": role,
        "name": f"P29 {role}", "email": email,
        "auto_clockin_enabled": ac,
    })
    return {"id": uid, "email": email, "role": role,
            "tenant_id": tenant_id,
            "token": _tok(uid, email, role, tenant_id)}


def _patch_me(token: str, body: dict) -> requests.Response:
    return requests.patch(
        f"{API}/users/me",
        headers={"Authorization": f"Bearer {token}"},
        json=body,
    )


def test_tech_cannot_disable_auto_clockin_returns_403(tenant_id):
    tech = _seed_user(tenant_id, "technician", ac=True)
    r = _patch_me(tech["token"], {"auto_clockin_enabled": False})
    assert r.status_code == 403, r.text
    # Message must call out the enforcement so the mobile client
    # can surface it to the user if needed.
    assert "enforced" in r.text.lower() \
        or "cannot be disabled" in r.text.lower()
    # DB is untouched — the row still reads True.
    fresh = _sync.users.find_one(
        {"id": tech["id"]},
        {"_id": 0, "auto_clockin_enabled": 1},
    )
    assert fresh["auto_clockin_enabled"] is True


def test_tech_can_still_reaffirm_auto_clockin_true(tenant_id):
    # Idempotent no-op — flipping True is a valid client behaviour
    # (the mobile screen's heal-storage side-effect calls setter
    # with True on mount, which may eventually PATCH the backend
    # too). Must NOT 403.
    tech = _seed_user(tenant_id, "technician", ac=True)
    r = _patch_me(tech["token"], {"auto_clockin_enabled": True})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["user"]["auto_clockin_enabled"] is True


def test_admin_can_still_toggle_auto_clockin_off(tenant_id):
    # Non-tech roles keep their pre-Phase-29 self-toggle behaviour.
    admin = _seed_user(tenant_id, "admin", ac=True)
    r = _patch_me(admin["token"], {"auto_clockin_enabled": False})
    assert r.status_code == 200, r.text
    assert r.json()["user"]["auto_clockin_enabled"] is False


def test_super_admin_can_still_toggle_auto_clockin_off(tenant_id):
    sa = _seed_user(tenant_id, "super_admin", ac=True)
    r = _patch_me(sa["token"], {"auto_clockin_enabled": False})
    assert r.status_code == 200, r.text
    assert r.json()["user"]["auto_clockin_enabled"] is False
