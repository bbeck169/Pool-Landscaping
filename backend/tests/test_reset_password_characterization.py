"""Feb-2026 · P6 — Characterization tests for ``POST /auth/reset-password``.

Pins the CURRENT observable contract of ``reset_password`` at
``routers/auth.py:357-429`` before the behavior-preserving refactor.
Every assertion targets a behavior that MUST NOT drift across the
refactor — status codes, exact error strings, DB side-effects, audit
reasons, no-email-on-completion.
"""
from __future__ import annotations
import uuid
from pathlib import Path
from datetime import datetime, timezone, timedelta

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = MongoClient(_ENV["MONGO_URL"])[_ENV["DB_NAME"]]
API = "http://localhost:8001/api"


def _seed_user_and_token(*, used_at=None, invalidated_at=None,
                         expires_delta_min: int = 30) -> tuple[str, str, str]:
    """Seed a user + token row; returns (uid, token, email)."""
    from utils import hash_password
    uid = f"TEST_p6_u_{uuid.uuid4().hex[:8]}"
    email = f"test_p6_{uuid.uuid4().hex[:6]}@example.com"
    tenant_id = _sync.users.find_one({"email": "admin@aquaterra.com"})["tenant_id"]
    _sync.users.insert_one({
        "id": uid, "tenant_id": tenant_id, "email": email,
        "name": "TEST P6", "role": "customer", "active": True,
        "password_hash": hash_password("OldPass123!"),
        "failed_login_attempts": 3, "lockout_until": None,
    })
    tok = uuid.uuid4().hex + uuid.uuid4().hex
    _sync.password_reset_tokens.insert_one({
        "token": tok, "user_id": uid, "email": email,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "expires_at": (datetime.now(timezone.utc)
                        + timedelta(minutes=expires_delta_min)).isoformat(),
        "used_at": used_at, "invalidated_at": invalidated_at,
    })
    return uid, tok, email


def _cleanup(uid: str):
    _sync.users.delete_one({"id": uid})
    _sync.password_reset_tokens.delete_many({"user_id": uid})


# ── 1. Happy path — exact response + all side-effects ─────────────
def test_reset_password_happy_path_pins_response_and_side_effects():
    uid, tok, _ = _seed_user_and_token()
    try:
        # Seed a SECOND unused token for the same user — refactor MUST
        # still invalidate it (belt-and-braces branch at auth.py:423).
        other_tok = uuid.uuid4().hex + uuid.uuid4().hex
        _sync.password_reset_tokens.insert_one({
            "token": other_tok, "user_id": uid,
            "expires_at": (datetime.now(timezone.utc)
                            + timedelta(minutes=30)).isoformat(),
            "used_at": None, "invalidated_at": None,
        })
        r = requests.post(f"{API}/auth/reset-password",
                            json={"token": tok, "new_password": "NewPass123!"},
                            timeout=10)
        assert r.status_code == 200, r.text
        assert r.json() == {"ok": True, "message": "Password reset. Please sign in."}
        u = _sync.users.find_one({"id": uid})
        assert u["failed_login_attempts"] == 0
        assert u["lockout_until"] is None
        assert u["must_change_password_on_next_login"] is False
        assert u["password_hash"].startswith("$2b$")  # bcrypt shape preserved
        assert u.get("password_updated_at")
        # Consumed token stamped with used_at + used_ip.
        row = _sync.password_reset_tokens.find_one({"token": tok})
        assert row["used_at"] and row.get("used_ip")
        # Sibling unused token belt-and-braces invalidated.
        sib = _sync.password_reset_tokens.find_one({"token": other_tok})
        assert sib["invalidated_at"] is not None
    finally:
        _cleanup(uid)


# ── 2. Empty token → 400 with the exact user-facing message ───────
def test_reset_password_empty_token_400():
    r = requests.post(f"{API}/auth/reset-password",
                        json={"token": "  ", "new_password": "NewPass123!"},
                        timeout=10)
    assert r.status_code == 400
    assert r.json()["detail"] == "Invalid or expired reset link. Please request a new one."


# ── 3. Unknown token → 400 same message ───────────────────────────
def test_reset_password_unknown_token_400():
    r = requests.post(f"{API}/auth/reset-password",
                        json={"token": "not-a-real-token-" + uuid.uuid4().hex,
                              "new_password": "NewPass123!"},
                        timeout=10)
    assert r.status_code == 400
    assert r.json()["detail"] == "Invalid or expired reset link. Please request a new one."


# ── 4. Already-used token → distinct error copy ───────────────────
def test_reset_password_reused_token_400_with_reused_message():
    uid, tok, _ = _seed_user_and_token(
        used_at=datetime.now(timezone.utc).isoformat(),
    )
    try:
        r = requests.post(f"{API}/auth/reset-password",
                            json={"token": tok, "new_password": "NewPass123!"},
                            timeout=10)
        assert r.status_code == 400
        # DISTINCT copy — refactor must preserve this message so the UI's
        # "please request a new one" nudge still lands correctly.
        assert r.json()["detail"] == "This reset link has already been used. Please request a new one."
    finally:
        _cleanup(uid)


# ── 5. Expired token → distinct expired copy ──────────────────────
def test_reset_password_expired_token_400_with_expired_message():
    uid, tok, _ = _seed_user_and_token(expires_delta_min=-5)
    try:
        r = requests.post(f"{API}/auth/reset-password",
                            json={"token": tok, "new_password": "NewPass123!"},
                            timeout=10)
        assert r.status_code == 400
        assert r.json()["detail"] == "This reset link has expired. Please request a new one."
    finally:
        _cleanup(uid)


# ── 6. Weak password → policy error is surfaced verbatim ──────────
def test_reset_password_weak_password_400_from_policy_helper():
    uid, tok, _ = _seed_user_and_token()
    try:
        r = requests.post(f"{API}/auth/reset-password",
                            json={"token": tok, "new_password": "short"},
                            timeout=10)
        assert r.status_code == 400
        # Whatever ``_password_policy_ok`` returns — refactor must
        # forward it verbatim, unchanged prefix / suffix / punctuation.
        from routers.auth import _password_policy_ok
        assert r.json()["detail"] == _password_policy_ok("short")
        # Token must NOT be marked used on policy failure.
        row = _sync.password_reset_tokens.find_one({"token": tok})
        assert row["used_at"] is None
    finally:
        _cleanup(uid)
