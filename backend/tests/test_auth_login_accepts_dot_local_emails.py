"""2026-10-02 · Login-validator asymmetry on reserved TLDs — pytest.

Pins the fix for the Portal Edit Profile followup documented in
``memory/PORTAL_EDIT_PROFILE_FOLLOWUPS.md`` §1: PATCH
``/api/customer-portal/profile`` (which uses the lenient
``_valid_email`` regex) accepted ``.local`` / ``.test`` / ``.example``
emails, but POST ``/api/auth/login`` rejected them via pydantic's
strict ``EmailStr`` + email-validator ``check_deliverability`` policy —
locking out any customer who legitimately stored a primary email on
a reserved TLD (home-lab, dev loopbacks).

Fix: ``LoginRequest.email`` was switched from ``EmailStr`` to ``str``
+ an inline regex ``@field_validator("email")`` mirroring
``customer_portal._valid_email``, so both paths agree on the
acceptance set.

Scope: NARROW. Direct ``login()`` handler calls with monkey-patched
in-memory DB (same pattern as
``test_auth_option_a_account_chooser_task4.py``). The PATCH-side
regression guard is a direct unit assertion on
``customer_portal._valid_email`` — since the PATCH endpoint
delegates to that helper, any accidental tightening of the helper
fires this test instantly; wrapping the assertion in HTTP would add
no additional signal.
"""
from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest
from pydantic import ValidationError

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
        self.inserts.append(doc); self.rows.append(doc)
        return {"inserted_id": doc.get("id")}

    async def insert_many(self, docs):
        for d in docs:
            await self.insert_one(d)

    async def update_one(self, filt, upd):
        for r in self._match(filt or {}):
            r.update(upd.get("$set") or {})
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
            if self._doc_matches(r, filt):
                out.append(r)
        return out

    @staticmethod
    def _doc_matches(doc, filt) -> bool:
        for k, v in (filt or {}).items():
            if k == "$or":
                if not any(_Coll._doc_matches(doc, s) for s in v):
                    return False
            elif isinstance(v, dict) and "$exists" in v:
                if bool(v["$exists"]) != (k in doc):
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


def _seed_user(fake_db, *, email, role, password,
                uid=None, tenant_id="t-asym-1", **extra):
    uid = uid or str(uuid.uuid4())
    fake_db.users.rows.append({
        "id": uid, "email": email, "role": role,
        "password_hash": _pwd.hash(password),
        "tenant_id": tenant_id,
        "name": extra.get("name", "Dot-Local Test"),
        **{k: v for k, v in extra.items() if k != "name"},
    })
    return uid


# 1 · Login accepts .local TLD — primary asymmetry fix.
def test_login_accepts_dot_local_email(fake_db):
    from routers.auth import login, LoginRequest
    _seed_user(fake_db,
                email="test-asymmetry@example.local",
                role="customer",
                password="Pwd-DotLocal-1")
    req = _mk_request()
    out = _run(login(req, LoginRequest(
        email="test-asymmetry@example.local",
        password="Pwd-DotLocal-1",
    )))
    assert "access_token" in out, f"no access_token in response: {out}"
    assert out["user"]["email"] == "test-asymmetry@example.local"


# 2 · Over-loosening guard — ``not-an-email`` still fails.
def test_login_rejects_obviously_malformed_email():
    from routers.auth import LoginRequest
    with pytest.raises(ValidationError):
        LoginRequest(email="not-an-email", password="x")


# 3 · Over-loosening guard — missing-TLD-dot still fails.
def test_login_rejects_missing_tld_dot_email():
    from routers.auth import LoginRequest
    with pytest.raises(ValidationError):
        LoginRequest(email="user@localhost", password="x")


# 4 · Over-loosening guard — missing @ still fails.
def test_login_rejects_missing_at_sign_email():
    from routers.auth import LoginRequest
    with pytest.raises(ValidationError):
        LoginRequest(email="useratdomain.com", password="x")


# 5 · Ordinary .com emails still pass (regression guard).
def test_login_still_accepts_ordinary_com_email(fake_db):
    from routers.auth import login, LoginRequest
    _seed_user(fake_db,
                email="ordinary@aquaterra.com",
                role="customer",
                password="Pwd-Ordinary-1")
    req = _mk_request()
    out = _run(login(req, LoginRequest(
        email="ordinary@aquaterra.com",
        password="Pwd-Ordinary-1",
    )))
    assert "access_token" in out


# 6 · PATCH-side regression guard — customer_portal._valid_email accepts .local.
def test_patch_side_valid_email_helper_accepts_dot_local():
    from routers.customer_portal import _valid_email
    assert _valid_email("another-asymmetry@example.local") is True
    assert _valid_email("home-lab@homelab.local") is True
    assert _valid_email("devbox@my-dev.test") is True


# 7 · PATCH-side regression guard — helper still rejects malformed inputs.
def test_patch_side_valid_email_helper_rejects_malformed():
    from routers.customer_portal import _valid_email
    assert _valid_email("not-an-email") is False
    assert _valid_email("user@localhost") is False
    assert _valid_email("") is False
    assert _valid_email("useratdomain.com") is False
