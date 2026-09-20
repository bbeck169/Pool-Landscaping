"""Phase 30 · Feb 2026 — belt-and-suspenders check that removing the
demo-accounts UI did NOT change the backend auth flow. Manual login
with the three seed accounts must still work.

Tests run against the live preview backend so the flow exercises the
same code path that prod runs. If the seed rows don't exist in the
preview DB (early bootstrap), the test is skipped rather than failing
— since backend auth is not what changed.
"""
from __future__ import annotations

import os
from pathlib import Path

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
_sync = _shared_db()
@pytest.fixture(scope="module")
def api_base():
    frontend_env = Path(__file__).resolve().parents[2] / "frontend" / ".env"
    react = dotenv_values(frontend_env) if frontend_env.is_file() else {}
    public = (react.get("REACT_APP_BACKEND_URL")
              or os.environ.get("REACT_APP_BACKEND_URL"))
    return ((public.rstrip("/") + "/api") if public else
            "http://localhost:8001/api")


SEED_ACCOUNTS = [
    ("admin@aquaterra.com", "password123"),
    ("mike@aquaterra.com", "password123"),
    ("customer@aquaterra.com", "password123"),
]


@pytest.mark.parametrize("email,password", SEED_ACCOUNTS)
def test_seed_account_manual_login_still_returns_valid_jwt(api_base, email, password):
    # Skip when the row is absent from this preview DB.
    row = _sync.users.find_one({"email": email},
                                  {"_id": 0, "id": 1, "role": 1})
    if not row:
        pytest.skip(f"seed account {email} not present in this env")
    r = requests.post(f"{api_base}/auth/login",
                       json={"email": email, "password": password},
                       timeout=15)
    assert r.status_code == 200, f"{email} → {r.status_code}: {r.text}"
    tok = r.json().get("access_token")
    assert tok and isinstance(tok, str) and len(tok) > 20
    # Sanity — hitting /auth/me with the token resolves the user.
    r2 = requests.get(f"{api_base}/auth/me",
                       headers={"Authorization": f"Bearer {tok}"}, timeout=15)
    assert r2.status_code == 200
    assert (r2.json().get("email") or "").lower() == email.lower()
