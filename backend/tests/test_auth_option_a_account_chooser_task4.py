"""Feb-2026 · Task 4 · Option A account chooser — backend unit tests.

Pins the contract for:
  * ``POST /api/auth/login`` — multi-record branch fires ONLY when
    2+ non-deleted rows password-match with divergent roles.
  * ``POST /api/auth/login/select-account`` — completes the login,
    binds strictly to the ``verified`` claim in the choice_token,
    and rejects replay of the choice_token as a Bearer.
  * Audit rows in ``auth_multi_account_choices`` on both events.
  * Miguel Munoz regression guard — single-record + only-one-matches
    branches keep the pre-Task-4 behaviour.

Scope: NARROW.  Uses stubbed Motor collections so the tests don't
depend on the live DB and don't collide with neighbour suites.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest
import jwt as _jwt

# The real ``passlib`` is available in the env — use it so bcrypt
# hashes verify correctly under the module's ``verify_password``.
from passlib.context import CryptContext
_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class _Cursor:
    def __init__(self, rows): self._rows = list(rows)
    async def to_list(self, length=None): return list(self._rows)


class _Coll:
    def __init__(self, rows=None):
        self.rows: List[Dict[str, Any]] = list(rows or [])
        self.inserts: List[Dict[str, Any]] = []
        self.updates: List[Dict[str, Any]] = []

    def find(self, filt=None, projection=None):
        return _Cursor(self._match(filt or {}))

    async def find_one(self, filt=None, projection=None):
        for r in self._match(filt or {}):
            return r
        return None

    async def count_documents(self, filt=None, *a, **kw):
        return len(self._match(filt or {}))

    async def insert_one(self, doc):
        self.inserts.append(doc); self.rows.append(doc); return {"inserted_id": doc.get("id")}

    async def insert_many(self, docs):
        for d in docs: await self.insert_one(d)

    async def update_one(self, filt, upd):
        for r in self._match(filt or {}):
            r.update((upd.get("$set") or {}))
            self.updates.append({"filter": filt, "update": upd})
            return SimpleNamespace(modified_count=1)
        return SimpleNamespace(modified_count=0)

    async def delete_many(self, filt):
        keep = [r for r in self.rows if r not in self._match(filt or {})]
        deleted = len(self.rows) - len(keep)
        self.rows = keep
        return SimpleNamespace(deleted_count=deleted)

    def _match(self, filt: Dict[str, Any]):
        out = []
        for r in self.rows:
            if self._doc_matches(r, filt): out.append(r)
        return out

    @staticmethod
    def _doc_matches(doc, filt) -> bool:
        for k, v in (filt or {}).items():
            if k == "$or":
                if not any(_Coll._doc_matches(doc, sub) for sub in v):
                    return False
            elif isinstance(v, dict) and "$exists" in v:
                exists = k in doc
                if bool(v["$exists"]) != exists:
                    return False
            elif isinstance(v, dict) and "$in" in v:
                if doc.get(k) not in v["$in"]:
                    return False
            elif isinstance(v, dict) and "$ne" in v:
                if doc.get(k) == v["$ne"]:
                    return False
            else:
                if doc.get(k) != v:
                    return False
        return True


class _DB:
    def __init__(self):
        self.users = _Coll()
        self.tenants = _Coll()
        self.customers = _Coll()
        self.audit_logs = _Coll()
        self.audit_events = _Coll()
        self.auth_multi_account_choices = _Coll()


@pytest.fixture()
def fake_db(monkeypatch):
    fake = _DB()
    from routers import auth as auth_mod
    monkeypatch.setattr(auth_mod, "db", fake)
    import config as cfg_mod
    monkeypatch.setattr(cfg_mod, "db", fake)
    import utils as utils_mod
    monkeypatch.setattr(utils_mod, "db", fake)
    return fake


def _mk_request(ip="1.2.3.4", ua="pytest/1.0"):
    return SimpleNamespace(
        client=SimpleNamespace(host=ip, port=None),
        headers={"user-agent": ua, "x-forwarded-for": ""},
        state=SimpleNamespace(timings=[]),
    )


def _seed_user(fake_db, *, email, role, password, uid=None,
                tenant_id="t-t4-1", **extra):
    uid = uid or str(uuid.uuid4())
    fake_db.users.rows.append({
        "id": uid, "email": email, "role": role,
        "password_hash": _pwd.hash(password),
        "tenant_id": tenant_id, "name": extra.get("name", "Test"),
        **{k: v for k, v in extra.items() if k != "name"},
    })
    return uid


# ═════════════════════════════════════════════════════════════════════
# 1. Single-record login — Miguel Munoz regression: unchanged behaviour.
# ═════════════════════════════════════════════════════════════════════
def test_single_record_login_returns_normal_token(fake_db):
    from routers.auth import login, LoginRequest
    _seed_user(fake_db, email="jane@example.com", role="admin",
                password="pwd-a1b2")
    req = _mk_request()
    out = _run(login(req, LoginRequest(email="jane@example.com",
                                          password="pwd-a1b2")))
    assert "access_token" in out
    assert out["user"]["role"] == "admin"
    assert out.get("status") != "multi_account_choice_required"


# ═════════════════════════════════════════════════════════════════════
# 2. Two records with SAME password, DIFFERENT roles → chooser fires.
# ═════════════════════════════════════════════════════════════════════
def test_multi_record_divergent_roles_triggers_chooser(fake_db):
    from routers.auth import login, LoginRequest
    uid_c = _seed_user(fake_db, email="brian@example.com", role="customer",
                        password="pwd-a1b2", name="Brian Cust",
                        customer_id="c-brian")
    uid_a = _seed_user(fake_db, email="brian@example.com", role="admin",
                        password="pwd-a1b2", name="Brian Admin")
    req = _mk_request()
    out = _run(login(req, LoginRequest(email="brian@example.com",
                                          password="pwd-a1b2")))
    assert out["status"] == "multi_account_choice_required"
    assert "access_token" not in out
    assert "choice_token" in out
    ids = {c["account_id"] for c in out["choices"]}
    assert ids == {uid_c, uid_a}
    roles = sorted(c["role"] for c in out["choices"])
    assert roles == ["admin", "customer"]
    # Audit row written.
    assert len(fake_db.auth_multi_account_choices.inserts) == 1
    row = fake_db.auth_multi_account_choices.inserts[0]
    assert row["event"] == "required"
    assert sorted(row["user_ids"]) == sorted([uid_c, uid_a])


# ═════════════════════════════════════════════════════════════════════
# 3. Two records, only ONE password matches → normal login (no chooser).
#    Preserves the "password differ recovery" behaviour without asking
#    the user to pick.
# ═════════════════════════════════════════════════════════════════════
def test_multi_record_but_one_match_returns_normal(fake_db):
    from routers.auth import login, LoginRequest
    _seed_user(fake_db, email="jane@example.com", role="customer",
                password="different-pwd", customer_id="c-jane")
    uid_a = _seed_user(fake_db, email="jane@example.com", role="admin",
                        password="pwd-a1b2")
    req = _mk_request()
    out = _run(login(req, LoginRequest(email="jane@example.com",
                                          password="pwd-a1b2")))
    assert "access_token" in out
    assert out["user"]["role"] == "admin"
    assert out.get("status") != "multi_account_choice_required"


# ═════════════════════════════════════════════════════════════════════
# 4. Wrong password does NOT leak the chooser and returns 401.
# ═════════════════════════════════════════════════════════════════════
def test_wrong_password_never_leaks_chooser(fake_db):
    from fastapi import HTTPException
    from routers.auth import login, LoginRequest
    _seed_user(fake_db, email="brian@example.com", role="customer",
                password="right", customer_id="c-brian")
    _seed_user(fake_db, email="brian@example.com", role="admin",
                password="right")
    req = _mk_request()
    with pytest.raises(HTTPException) as ei:
        _run(login(req, LoginRequest(email="brian@example.com",
                                        password="wrong")))
    assert ei.value.status_code == 401
    assert fake_db.auth_multi_account_choices.inserts == []


# ═════════════════════════════════════════════════════════════════════
# 5. select-account with valid account_id → normal auth response.
# ═════════════════════════════════════════════════════════════════════
def test_select_account_returns_normal_token(fake_db):
    from routers.auth import (
        login, login_select_account, LoginRequest, _SelectAccountBody,
    )
    uid_c = _seed_user(fake_db, email="brian@example.com", role="customer",
                        password="pwd", customer_id="c-brian")
    _seed_user(fake_db, email="brian@example.com", role="admin",
                password="pwd")
    step1 = _run(login(_mk_request(), LoginRequest(email="brian@example.com",
                                                        password="pwd")))
    tok = step1["choice_token"]
    out = _run(login_select_account(
        _mk_request(),
        _SelectAccountBody(choice_token=tok, account_id=uid_c),
    ))
    assert "access_token" in out
    assert out["user"]["id"] == uid_c
    assert out["user"]["role"] == "customer"
    # ``selected`` audit row exists.
    events = [r["event"] for r in fake_db.auth_multi_account_choices.inserts]
    assert events.count("required") == 1
    assert events.count("selected") == 1


# ═════════════════════════════════════════════════════════════════════
# 6. select-account with account_id NOT in verified list → 401.
# ═════════════════════════════════════════════════════════════════════
def test_select_account_rejects_unverified_id(fake_db):
    from fastapi import HTTPException
    from routers.auth import (
        login, login_select_account, LoginRequest, _SelectAccountBody,
    )
    _seed_user(fake_db, email="brian@example.com", role="customer",
                password="pwd", customer_id="c-brian")
    _seed_user(fake_db, email="brian@example.com", role="admin", password="pwd")
    step1 = _run(login(_mk_request(), LoginRequest(email="brian@example.com",
                                                        password="pwd")))
    with pytest.raises(HTTPException) as ei:
        _run(login_select_account(
            _mk_request(),
            _SelectAccountBody(choice_token=step1["choice_token"],
                                 account_id="attacker-uuid"),
        ))
    assert ei.value.status_code == 401


# ═════════════════════════════════════════════════════════════════════
# 7. Expired choice_token → 401 with expiry message.
# ═════════════════════════════════════════════════════════════════════
def test_select_account_rejects_expired_token(fake_db):
    from fastapi import HTTPException
    from routers.auth import login_select_account, _SelectAccountBody
    from config import JWT_SECRET, JWT_ALGO
    uid = _seed_user(fake_db, email="brian@example.com", role="customer",
                      password="pwd", customer_id="c-brian")
    expired = _jwt.encode(
        {"type": "choice", "email": "brian@example.com",
          "verified": [uid],
          "exp": datetime.now(timezone.utc) - timedelta(minutes=1)},
        JWT_SECRET, algorithm=JWT_ALGO,
    )
    with pytest.raises(HTTPException) as ei:
        _run(login_select_account(
            _mk_request(),
            _SelectAccountBody(choice_token=expired, account_id=uid),
        ))
    assert ei.value.status_code == 401
    assert "expired" in ei.value.detail.lower()


# ═════════════════════════════════════════════════════════════════════
# 8. choice_token payload contains type=choice + NO sub claim.  Security
#    guard against replaying the choice_token as an access token.
# ═════════════════════════════════════════════════════════════════════
def test_choice_token_payload_shape(fake_db):
    from routers.auth import login, LoginRequest
    from config import JWT_SECRET, JWT_ALGO
    _seed_user(fake_db, email="brian@example.com", role="customer",
                password="pwd", customer_id="c-brian")
    _seed_user(fake_db, email="brian@example.com", role="admin", password="pwd")
    step1 = _run(login(_mk_request(), LoginRequest(email="brian@example.com",
                                                        password="pwd")))
    decoded = _jwt.decode(step1["choice_token"], JWT_SECRET,
                           algorithms=[JWT_ALGO])
    # ``type=choice`` distinguishes this from access tokens.
    assert decoded["type"] == "choice"
    # ``sub`` MUST be absent so a naïve drop-in as ``Authorization:
    # Bearer`` fails the ``users.find_one({id: None})`` lookup.
    assert "sub" not in decoded
    assert decoded["email"] == "brian@example.com"
    assert isinstance(decoded["verified"], list)
    assert len(decoded["verified"]) == 2


# ═════════════════════════════════════════════════════════════════════
# 9. Soft-deleted user records are excluded from the chooser candidate
#    set (protects Miguel Munoz fix intent).
# ═════════════════════════════════════════════════════════════════════
def test_soft_deleted_record_excluded(fake_db):
    from routers.auth import login, LoginRequest
    _seed_user(fake_db, email="brian@example.com", role="customer",
                password="pwd", customer_id="c-brian",
                deleted_at="2026-01-01T00:00:00Z")
    _seed_user(fake_db, email="brian@example.com", role="admin", password="pwd")
    out = _run(login(_mk_request(), LoginRequest(email="brian@example.com",
                                                    password="pwd")))
    # Only workforce record survives → normal login.
    assert out.get("status") != "multi_account_choice_required"
    assert out["user"]["role"] == "admin"


# ═════════════════════════════════════════════════════════════════════
# 10. Same-role duplicates → no chooser (first wins, warns).
# ═════════════════════════════════════════════════════════════════════
def test_same_role_duplicates_no_chooser(fake_db):
    from routers.auth import login, LoginRequest
    _seed_user(fake_db, email="dup@example.com", role="admin", password="pwd")
    _seed_user(fake_db, email="dup@example.com", role="admin", password="pwd")
    out = _run(login(_mk_request(), LoginRequest(email="dup@example.com",
                                                    password="pwd")))
    assert out.get("status") != "multi_account_choice_required"
    assert "access_token" in out
    assert out["user"]["role"] == "admin"
