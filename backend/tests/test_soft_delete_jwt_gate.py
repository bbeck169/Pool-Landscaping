"""Feb-2026 · Team page admin actions · follow-ups — pytest.

Task 1 · JWT ``deleted_at`` enforcement:
    Mint a JWT for a live user, soft-delete the row, then re-hit an
    authenticated endpoint with the same JWT — expect 401
    ``account_deleted``. Regression asserts a non-deleted user with the
    same token pattern still gets 200.

Task 2 · ``GET /api/config/public`` runtime flags:
    Confirm the endpoint publicly returns ``show_demo_logins`` +
    ``brand_name`` alongside the pre-existing Stripe fields.
"""
from __future__ import annotations
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt as _jwt
import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient
from tests._shared_mongo import (
    shared_client as _shared_client,
    shared_db as _shared_db,
)


_BACKEND_ENV = Path(__file__).resolve().parents[1] / ".env"
_ENV = dotenv_values(_BACKEND_ENV)
_MONGO_URL = _ENV.get("MONGO_URL") or os.environ.get("MONGO_URL")
_DB_NAME = _ENV.get("DB_NAME") or os.environ.get("DB_NAME")
_JWT_SECRET = _ENV.get("JWT_SECRET") or os.environ.get("JWT_SECRET")
_JWT_ALGO = "HS256"
_sync = _shared_db()
_REACT_ENV = Path(__file__).resolve().parents[2] / "frontend" / ".env"
_REACT = dotenv_values(_REACT_ENV) if _REACT_ENV.is_file() else {}
_PUBLIC_URL = _REACT.get("REACT_APP_BACKEND_URL") or os.environ.get(
    "REACT_APP_BACKEND_URL")
API = os.environ.get("BACKEND_API_URL") or (
    (_PUBLIC_URL.rstrip("/") + "/api") if _PUBLIC_URL else
    "http://localhost:8001/api"
)


def _admin_tenant_id() -> str:
    return _sync.users.find_one(
        {"email": "admin@aquaterra.com"}, {"_id": 0, "tenant_id": 1})["tenant_id"]


def _mint_jwt(uid: str, role: str = "technician",
                exp_minutes: int = 60) -> str:
    return _jwt.encode(
        {"sub": uid, "role": role,
          "exp": datetime.now(timezone.utc) + timedelta(minutes=exp_minutes)},
        _JWT_SECRET, algorithm=_JWT_ALGO,
    )


@pytest.fixture
def live_user():
    tid = _admin_tenant_id()
    uid = f"pytest-jwt-{uuid.uuid4().hex[:10]}"
    doc = {
        "id": uid,
        "email": f"{uid}@pytest.local",
        "name": "JWT gate test",
        "role": "technician",
        "department": "pool",
        "tenant_id": tid,
        "password_hash": "$2b$12$aaaaaaaaaaaaaaaaaaaaaOxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _sync.users.insert_one({**doc})
    yield doc
    _sync.users.delete_one({"id": uid})


# ─────────────────────────────────────────────────────────────────────
# Task 1 · JWT ``deleted_at`` enforcement
# ─────────────────────────────────────────────────────────────────────
def test_live_user_jwt_is_accepted(live_user):
    """Sanity — a freshly-minted JWT for a live user resolves against
    an authenticated endpoint (``GET /api/auth/me``) with 200. This
    isolates the fixture + JWT signing from the deletion assertion."""
    tok = _mint_jwt(live_user["id"], live_user["role"])
    r = requests.get(f"{API}/auth/me",
                       headers={"Authorization": f"Bearer {tok}"}, timeout=15)
    assert r.status_code == 200, r.text


def test_soft_deleted_user_jwt_is_401_account_deleted(live_user):
    """The core assertion. Mint the JWT BEFORE the soft-delete so the
    token itself is otherwise valid — the 401 must come from the
    ``deleted_at`` gate in ``utils.get_current_user``, not from an
    expiry, signature, or lookup miss."""
    tok = _mint_jwt(live_user["id"], live_user["role"])
    _sync.users.update_one(
        {"id": live_user["id"]},
        {"$set": {"deleted_at": datetime.now(timezone.utc).isoformat(),
                    "roster_hidden": True}},
    )
    r = requests.get(f"{API}/auth/me",
                       headers={"Authorization": f"Bearer {tok}"}, timeout=15)
    assert r.status_code == 401, r.text
    body = r.json()
    assert body.get("detail") == "account_deleted"


def test_undelete_restores_jwt_access(live_user):
    """Post-undelete the same JWT works again — locks the pivot logic
    so a future refactor doesn't invert the check."""
    tok = _mint_jwt(live_user["id"], live_user["role"])
    _sync.users.update_one(
        {"id": live_user["id"]},
        {"$set": {"deleted_at": datetime.now(timezone.utc).isoformat()}},
    )
    r_deleted = requests.get(f"{API}/auth/me",
                                headers={"Authorization": f"Bearer {tok}"}, timeout=15)
    assert r_deleted.status_code == 401
    _sync.users.update_one(
        {"id": live_user["id"]},
        {"$set": {"deleted_at": None}},
    )
    r_ok = requests.get(f"{API}/auth/me",
                          headers={"Authorization": f"Bearer {tok}"}, timeout=15)
    assert r_ok.status_code == 200, r_ok.text


# ─────────────────────────────────────────────────────────────────────
# Task 2 · GET /api/config/public flags
# ─────────────────────────────────────────────────────────────────────
def test_config_public_returns_show_demo_logins():
    r = requests.get(f"{API}/config/public", timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    # Boolean field present + not something surprising.
    assert isinstance(body.get("show_demo_logins"), bool)
    # Existing fields still present — additive contract.
    for key in ("stripe_publishable_key", "stripe_mode", "app_public_url"):
        assert key in body
    # Brand name string is populated (env default kicks in if unset).
    assert isinstance(body.get("brand_name"), str)
    assert body["brand_name"]  # non-empty


def test_config_public_is_public_no_auth_required():
    """No Authorization header — endpoint must respond 200."""
    r = requests.get(f"{API}/config/public", timeout=15)
    assert r.status_code == 200
