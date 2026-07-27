"""Phase 34 · Task W · Feb-2026 — enum-safe /auth/forgot-password.

Locks the invariant that hitting the endpoint with a NONEXISTENT
email still returns the neutral 200 payload — so no attacker can
enumerate registered accounts by looking at status codes or
response bodies.
"""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class _FakeCol:
    def __init__(self):
        self.docs = []

    async def find_one(self, q, proj=None):  # noqa: ARG002
        return None  # no user matches

    async def insert_one(self, doc):
        self.docs.append(dict(doc))
        return MagicMock()

    async def update_many(self, *_a, **_k):
        return MagicMock()

    async def update_one(self, *_a, **_k):
        return MagicMock()


class _FakeDB:
    def __init__(self):
        self.users = _FakeCol()
        self.password_reset_tokens = _FakeCol()
        self.audit_logs = _FakeCol()


def test_forgot_password_unknown_email_returns_neutral_200(monkeypatch):
    from routers import auth as _auth

    fake_db = _FakeDB()
    monkeypatch.setattr(_auth, "db", fake_db)
    _auth._RESET_IP_HITS.clear()

    req = MagicMock(headers={}, client=MagicMock(host="1.2.3.4"))
    body = _auth.ForgotPasswordRequest(email="ghost@example.com")
    resp = _run(_auth.forgot_password(req, body))

    # Neutral response — never disclose whether the email is known.
    assert resp["ok"] is True
    assert "If an account exists for that email" in resp["message"]
    # And NO reset token was minted for the nonexistent account.
    assert fake_db.password_reset_tokens.docs == []
