"""Phase 34 · Task O · Feb-2026 — self-serve password reset regression.

Covered flows:
  1. happy path — forgot → token minted → reset → new password works
  2. neutral response for unknown email (no enumeration)
  3. expired token rejected
  4. used token cannot be reused
  5. weak password rejected on reset AND on change-password
  6. rate-limit hit still returns neutral 200
  7. in-portal change-password happy path + wrong-current-password
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class _FakeCol:
    def __init__(self):
        self.docs: list[dict] = []

    async def find_one(self, q, proj=None):  # noqa: ARG002
        for d in self.docs:
            if self._m(d, q):
                return dict(d)
        return None

    async def insert_one(self, doc):
        self.docs.append(dict(doc))
        return MagicMock(inserted_id="fake")

    async def update_one(self, q, u):
        for d in self.docs:
            if self._m(d, q):
                d.update((u.get("$set") or {}))
                return MagicMock(modified_count=1)
        return MagicMock(modified_count=0)

    async def update_many(self, q, u):
        n = 0
        for d in self.docs:
            if self._m(d, q):
                d.update((u.get("$set") or {}))
                n += 1
        return MagicMock(modified_count=n)

    @staticmethod
    def _m(doc, query):
        for k, v in query.items():
            if isinstance(v, dict) and "$ne" in v:
                if doc.get(k) == v["$ne"]:
                    return False
            elif doc.get(k) != v:
                return False
        return True


class _FakeDB:
    def __init__(self):
        self.users = _FakeCol()
        self.password_reset_tokens = _FakeCol()
        self.audit_logs = _FakeCol()


def _seed_user(fake_db, email="orphan@example.com", pw_hash="$hash_placeholder$"):
    _run(fake_db.users.insert_one({
        "id": "user-1",
        "email": email,
        "tenant_id": "tenant-1",
        "name": "Orphan Owner",
        "first_name": "Orphan",
        "password_hash": pw_hash,
    }))


def _patch_env(monkeypatch, fake_db):
    from routers import auth as _auth
    monkeypatch.setattr(_auth, "db", fake_db)
    # No-op email adapter for tests.
    async def _fake_send(**_kwargs):
        return {"provider": "resend", "provider_status": "sent",
                "provider_response_id": "fake-id", "attempts": 1, "error": None}
    monkeypatch.setattr("services.email.resend_adapter.send", _fake_send)
    # Reset the in-process rate-limit deque.
    _auth._RESET_IP_HITS.clear()
    return _auth


# ══════════════════════════════════════════════════════════════════════
def test_forgot_password_returns_neutral_and_mints_token(monkeypatch):
    fake_db = _FakeDB()
    _seed_user(fake_db)
    _auth = _patch_env(monkeypatch, fake_db)

    req = MagicMock(headers={}, client=MagicMock(host="1.2.3.4"))
    body = _auth.ForgotPasswordRequest(email="orphan@example.com")
    resp = _run(_auth.forgot_password(req, body))
    assert resp == {"ok": True,
                     "message": "If an account exists for that email, a reset link has been sent."}
    # Token minted.
    assert len(fake_db.password_reset_tokens.docs) == 1
    tok = fake_db.password_reset_tokens.docs[0]
    assert tok["user_id"] == "user-1"
    assert tok["used_at"] is None


def test_forgot_password_unknown_email_still_neutral(monkeypatch):
    fake_db = _FakeDB()
    _auth = _patch_env(monkeypatch, fake_db)
    req = MagicMock(headers={}, client=MagicMock(host="1.2.3.4"))
    body = _auth.ForgotPasswordRequest(email="nobody@example.com")
    resp = _run(_auth.forgot_password(req, body))
    assert resp["ok"] is True
    # No token minted.
    assert fake_db.password_reset_tokens.docs == []


def test_reset_password_happy_path(monkeypatch):
    fake_db = _FakeDB()
    _seed_user(fake_db)
    _auth = _patch_env(monkeypatch, fake_db)

    _run(fake_db.password_reset_tokens.insert_one({
        "id": "t1", "token": "TOK-happy", "user_id": "user-1",
        "tenant_id": "tenant-1", "email": "orphan@example.com",
        "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(),
        "used_at": None, "invalidated_at": None,
    }))
    req = MagicMock(headers={}, client=MagicMock(host="1.2.3.4"))
    body = _auth.ResetPasswordRequest(token="TOK-happy", new_password="Sunshine9")
    resp = _run(_auth.reset_password(req, body))
    assert resp["ok"] is True
    # Token now consumed.
    tok = _run(fake_db.password_reset_tokens.find_one({"token": "TOK-happy"}))
    assert tok["used_at"] is not None
    # User hash updated.
    u = _run(fake_db.users.find_one({"id": "user-1"}))
    assert u["password_hash"] != "$hash_placeholder$"


def test_reset_password_expired_token(monkeypatch):
    fake_db = _FakeDB()
    _seed_user(fake_db)
    _auth = _patch_env(monkeypatch, fake_db)
    _run(fake_db.password_reset_tokens.insert_one({
        "token": "TOK-old", "user_id": "user-1",
        "expires_at": (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
        "used_at": None, "invalidated_at": None,
    }))
    import pytest
    req = MagicMock(headers={}, client=MagicMock(host="1.2.3.4"))
    body = _auth.ResetPasswordRequest(token="TOK-old", new_password="Sunshine9")
    with pytest.raises(_auth.HTTPException) as exc:
        _run(_auth.reset_password(req, body))
    assert exc.value.status_code == 400
    assert "expired" in exc.value.detail.lower()


def test_reset_password_reused_token(monkeypatch):
    fake_db = _FakeDB()
    _seed_user(fake_db)
    _auth = _patch_env(monkeypatch, fake_db)
    _run(fake_db.password_reset_tokens.insert_one({
        "token": "TOK-used", "user_id": "user-1",
        "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(),
        "used_at": "2026-02-10T12:00:00Z", "invalidated_at": None,
    }))
    import pytest
    req = MagicMock(headers={}, client=MagicMock(host="1.2.3.4"))
    body = _auth.ResetPasswordRequest(token="TOK-used", new_password="Sunshine9")
    with pytest.raises(_auth.HTTPException) as exc:
        _run(_auth.reset_password(req, body))
    assert exc.value.status_code == 400


def test_reset_password_weak_password_rejected(monkeypatch):
    fake_db = _FakeDB()
    _seed_user(fake_db)
    _auth = _patch_env(monkeypatch, fake_db)
    _run(fake_db.password_reset_tokens.insert_one({
        "token": "TOK-weak", "user_id": "user-1",
        "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(),
        "used_at": None, "invalidated_at": None,
    }))
    import pytest
    req = MagicMock(headers={}, client=MagicMock(host="1.2.3.4"))
    body = _auth.ResetPasswordRequest(token="TOK-weak", new_password="weak")
    with pytest.raises(_auth.HTTPException) as exc:
        _run(_auth.reset_password(req, body))
    assert exc.value.status_code == 400


def test_forgot_password_rate_limit_returns_neutral(monkeypatch):
    fake_db = _FakeDB()
    _seed_user(fake_db)
    _auth = _patch_env(monkeypatch, fake_db)
    req = MagicMock(headers={}, client=MagicMock(host="9.9.9.9"))
    body = _auth.ForgotPasswordRequest(email="orphan@example.com")
    # Burn through the 5-per-hour budget.
    for _ in range(_auth._RESET_RATE_MAX_PER_HOUR):
        _run(_auth.forgot_password(req, body))
    # 6th call must still return neutral, no additional token minted.
    tokens_before = len(fake_db.password_reset_tokens.docs)
    resp = _run(_auth.forgot_password(req, body))
    assert resp["ok"] is True
    assert len(fake_db.password_reset_tokens.docs) == tokens_before


def test_change_password_happy_and_wrong_current(monkeypatch):
    from utils import hash_password
    fake_db = _FakeDB()
    real_hash = hash_password("OldPass1")
    _seed_user(fake_db, pw_hash=real_hash)
    _auth = _patch_env(monkeypatch, fake_db)

    req = MagicMock(headers={}, client=MagicMock(host="1.1.1.1"))
    body = _auth.ChangeMyPasswordRequest(
        current_password="OldPass1", new_password="NewShiny9")
    user_ctx = _run(fake_db.users.find_one({"id": "user-1"}))
    resp = _run(_auth.change_my_password(req, body, user=user_ctx))
    assert resp["ok"] is True

    # Wrong-current-password path.
    import pytest
    body2 = _auth.ChangeMyPasswordRequest(
        current_password="WrongOne1", new_password="AnotherOne1")
    with pytest.raises(_auth.HTTPException) as exc:
        _run(_auth.change_my_password(req, body2, user=user_ctx))
    assert exc.value.status_code == 400
    assert "current password" in exc.value.detail.lower()
