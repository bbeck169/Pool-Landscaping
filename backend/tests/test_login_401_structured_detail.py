"""Phase P3 · Deliverable 3 · Feb-2026 — Structured 401 detail bodies.

Uses the same Motor-shaped in-memory stub pattern as the L3 suite so
we sidestep the ``event loop is closed`` trap that comes from sharing
the app's process-wide client with pytest's per-test loop.

Coverage:

* Wrong password (existing account) → 401
  ``detail={"code":"invalid_credentials", ...}``.
* Locked account (``lockout_until`` in the future) → 401
  ``detail={"code":"account_locked", "locked_until":"<ISO>", ...}``.
  Status code was changed from 429 → 401 per the P3 spec so a single
  frontend handler covers both branches.
* Unknown email → 401 ``code=invalid_credentials``, identical shape +
  message to the wrong-password branch (enumeration guard).
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient


def _run(coro): return asyncio.run(coro)


# ── Motor-shaped stub ─────────────────────────────────────────────
class _Cursor:
    def __init__(self, rows): self._rows = list(rows)
    async def to_list(self, n=None):
        return list(self._rows) if n is None else list(self._rows)[:n]
    def __aiter__(self): self._i = 0; return self
    async def __anext__(self):
        if self._i >= len(self._rows): raise StopAsyncIteration
        r = self._rows[self._i]; self._i += 1; return r


class _UsersColl:
    def __init__(self, rows=None):
        self.rows: List[Dict[str, Any]] = list(rows or [])

    async def find_one(self, q, p=None):
        for r in self.rows:
            if _match(r, q): return dict(r)
        return None

    def find(self, q=None, p=None):
        return _Cursor([r for r in self.rows if _match(r, q or {})])

    async def update_one(self, q, upd):
        for r in self.rows:
            if _match(r, q):
                r.update(upd.get("$set", {}))
                return type("R", (), {"matched_count": 1})()
        return type("R", (), {"matched_count": 0})()


def _match(row, q):
    for k, v in (q or {}).items():
        if k == "$or":
            if not any(_match(row, s) for s in v): return False
            continue
        rv = row.get(k)
        if isinstance(v, dict):
            if "$exists" in v and (k in row) != v["$exists"]:
                return False
            if "$in" in v and rv not in v["$in"]:
                return False
            # "$ne" etc. handled ad-hoc if needed
        elif rv != v:
            return False
    return True


def _build_app_with_users(users_rows):
    from routers import auth as auth_router
    stub = _UsersColl(users_rows)
    class _StubDB:
        def __getattr__(self, name):
            if name == "users": return stub
            # Return a permissive no-op stub for any other collection
            # touched by the login handler (audit + tenant lookups).
            outer = self
            class _NoOp:
                def find(self, *a, **kw): return _Cursor([])
                async def find_one(self, *a, **kw): return None
                async def insert_one(self, *a, **kw):
                    return type("R", (), {"inserted_id": "x"})()
                async def update_one(self, *a, **kw):
                    return type("R", (), {"matched_count": 0})()
                async def delete_many(self, *a, **kw): return None
                async def count_documents(self, *a, **kw): return 0
            return _NoOp()
    _StubDB.users = stub  # type: ignore
    # Rebind ``db`` on the auth module so its handler uses the stub.
    auth_router.db = _StubDB()

    app = FastAPI()
    app.include_router(auth_router.router, prefix="/api")
    return app, stub


def _seed_user(*, email, password_hash, locked_until=None):
    row = {
        "id": f"u-{email}",
        "email": email.lower(),
        "password_hash": password_hash,
        "role": "admin",
        "tenant_id": "t-p3",
        "failed_login_attempts": 0,
        "deleted_at": None,
    }
    if locked_until is not None:
        row["lockout_until"] = locked_until
    return row


# ═════════════════════════ tests ══════════════════════════════════
def test_login_wrong_password_returns_structured_invalid_credentials():
    async def run():
        from utils import hash_password
        rows = [_seed_user(email="p3-wrong@example.com",
                            password_hash=hash_password("correct-horse"))]
        app, _ = _build_app_with_users(rows)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://t",
        ) as ac:
            r = await ac.post(
                "/api/auth/login",
                json={"email": "p3-wrong@example.com",
                      "password": "wrong-password"},
            )
        assert r.status_code == 401, r.text
        detail = r.json()["detail"]
        assert isinstance(detail, dict), detail
        assert detail["code"] == "invalid_credentials"
        assert "wrong email" in detail["message"].lower() \
            or "invalid" in detail["message"].lower()
        # No lock leakage.
        assert "locked_until" not in detail

    _run(run())


def test_login_locked_account_returns_401_with_lock_detail():
    async def run():
        from utils import hash_password
        future = (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()
        rows = [_seed_user(email="p3-locked@example.com",
                            password_hash=hash_password("password123"),
                            locked_until=future)]
        app, _ = _build_app_with_users(rows)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://t",
        ) as ac:
            r = await ac.post(
                "/api/auth/login",
                json={"email": "p3-locked@example.com",
                      "password": "password123"},
            )
        # P3 changed status from 429 → 401 so the client has ONE handler.
        assert r.status_code == 401, r.text
        detail = r.json()["detail"]
        assert isinstance(detail, dict)
        assert detail["code"] == "account_locked"
        assert detail["locked_until"] == future
        assert "account locked" in detail["message"].lower()

    _run(run())


def test_login_unknown_email_matches_wrong_password_shape():
    """Enumeration guard — an attacker can't tell an unknown email
    apart from a wrong password."""
    async def run():
        from utils import hash_password
        rows = [_seed_user(email="p3-known@example.com",
                            password_hash=hash_password("password123"))]
        app, _ = _build_app_with_users(rows)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://t",
        ) as ac:
            r_wrong = await ac.post(
                "/api/auth/login",
                json={"email": "p3-known@example.com",
                      "password": "wrong"},
            )
            r_unknown = await ac.post(
                "/api/auth/login",
                json={"email": "p3-nobody@example.com",
                      "password": "anything"},
            )
        assert r_wrong.status_code == 401
        assert r_unknown.status_code == 401
        d1 = r_wrong.json()["detail"]
        d2 = r_unknown.json()["detail"]
        assert d1["code"] == d2["code"] == "invalid_credentials"
        assert d1["message"] == d2["message"]

    _run(run())
