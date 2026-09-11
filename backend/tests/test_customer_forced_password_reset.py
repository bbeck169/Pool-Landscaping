"""Feb-2026 · P0 · Customer forced-password-reset loop fix.

Contract:
  1) Customer + first login (role=customer, flag=True,
     has_ever_logged_in=False) → login forks into
     ``password_reset_required``. Consuming the token via
     ``/auth/reset-password`` flips ``must_change_password_on_next_login``
     to False, sets ``has_ever_logged_in=True`` +
     ``first_password_reset_at``, mints a fresh JWT
     (``auto_login=True`` envelope), and writes a
     ``customer.first_login_password_reset`` audit row.
  2) Customer with stale state (flag=True + has_ever_logged_in=True)
     → login does NOT fork; a ``customer.suspicious_forced_reset_flag``
     audit row is written; a normal ``access_token`` is issued.
  3) Non-customer role (admin/tech/super_admin) + flag=True → login
     does NOT fork; a normal ``access_token`` is issued. No
     suspicious-flag audit is emitted (the flag has no meaning for
     these roles).
  4) ``POST /admin/migrations/clear-stale-forced-reset-flags`` dry-run
     reports counts; wet-run flips flags; idempotent on second call.
  5) Migration endpoint role gate: admin → 403, super_admin → 200.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

from passlib.context import CryptContext
_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


# ── Reuse the in-file fake DB pattern from test_customer_temp_password_flow ──
class _Cursor:
    def __init__(self, rows):
        self._rows = list(rows)

    async def to_list(self, length=None):
        return list(self._rows)

    def sort(self, *a, **kw):
        return self

    def __aiter__(self):
        self._iter = iter(self._rows)
        return self

    async def __anext__(self):
        try:
            return next(self._iter)
        except StopIteration:
            raise StopAsyncIteration


class _Coll:
    def __init__(self, rows=None):
        self.rows: List[Dict[str, Any]] = list(rows or [])
        self.inserts: List[Dict[str, Any]] = []
        self.updates: List[Dict[str, Any]] = []

    def find(self, filt=None, projection=None):
        return _Cursor(self._match(filt or {}))

    async def find_one(self, filt=None, projection=None, *a, **kw):
        rows = self._match(filt or {})
        return rows[0] if rows else None

    async def count_documents(self, filt=None, *a, **kw):
        return len(self._match(filt or {}))

    async def insert_one(self, doc):
        self.inserts.append(doc)
        self.rows.append(doc)
        return SimpleNamespace(inserted_id=doc.get("id"))

    async def update_one(self, filt, upd, *a, **kw):
        for r in self._match(filt or {}):
            r.update(upd.get("$set") or {})
            self.updates.append({"filter": filt, "update": upd})
            return SimpleNamespace(modified_count=1)
        return SimpleNamespace(modified_count=0)

    async def update_many(self, filt, upd, *a, **kw):
        n = 0
        for r in self._match(filt or {}):
            r.update(upd.get("$set") or {})
            n += 1
        return SimpleNamespace(modified_count=n)

    def _match(self, filt: Dict[str, Any]):
        return [r for r in self.rows if self._doc_matches(r, filt)]

    @staticmethod
    def _doc_matches(doc, filt) -> bool:
        for k, v in (filt or {}).items():
            if k == "$or":
                if not any(_Coll._doc_matches(doc, sub) for sub in v):
                    return False
            elif k == "$and":
                if not all(_Coll._doc_matches(doc, sub) for sub in v):
                    return False
            elif isinstance(v, dict):
                val = doc.get(k)
                if "$exists" in v:
                    if bool(v["$exists"]) != (k in doc):
                        return False
                if "$in" in v and val not in v["$in"]:
                    return False
                if "$nin" in v and val in v["$nin"]:
                    return False
                if "$ne" in v and val == v["$ne"]:
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
        self.password_reset_tokens = _Coll()


@pytest.fixture()
def fake_db(monkeypatch):
    fake = _DB()
    from routers import auth as auth_mod
    from routers import admin_migrations as am_mod
    import config as cfg_mod
    import utils as utils_mod
    monkeypatch.setattr(auth_mod, "db", fake)
    monkeypatch.setattr(am_mod, "db", fake)
    monkeypatch.setattr(cfg_mod, "db", fake)
    monkeypatch.setattr(utils_mod, "db", fake)
    return fake


def _mk_request(ip="9.9.9.9"):
    return SimpleNamespace(
        client=SimpleNamespace(host=ip, port=None),
        headers={"user-agent": "pytest/1.0", "x-forwarded-for": ""},
        state=SimpleNamespace(timings=[]),
    )


def _seed_user(fake_db, *, role, email, password="tmp-A1a",
                 has_ever_logged_in=False,
                 must_change=True, tenant_id="t-fx1", cid=None):
    uid = str(uuid.uuid4())
    if role == "customer":
        cid = cid or f"c-{uid}"
        fake_db.customers.rows.append({
            "id": cid, "tenant_id": tenant_id,
            "email": email.lower(), "name": "Test Cust",
        })
    row = {
        "id": uid, "email": email.lower(), "role": role,
        "tenant_id": tenant_id, "name": "Test",
        "password_hash": _pwd.hash(password),
        "must_change_password_on_next_login": must_change,
        "has_ever_logged_in": has_ever_logged_in,
        "first_access_at": None,
        "active": True,
    }
    if cid:
        row["customer_id"] = cid
    fake_db.users.rows.append(row)
    return uid


# ═════════════════════════════════════════════════════════════════════
# 1. Customer first login → fork → reset → auto-login envelope
#    with fresh JWT + audit row.
# ═════════════════════════════════════════════════════════════════════
def test_customer_first_login_reset_flips_flags_and_auto_logs_in(fake_db):
    from routers.auth import (login, reset_password,
                                     LoginRequest, ResetPasswordRequest)
    uid = _seed_user(
        fake_db, role="customer", email="c@ex.com",
        password="tmp-A1a", has_ever_logged_in=False, must_change=True,
    )
    req = _mk_request()

    fork = _run(login(req, LoginRequest(email="c@ex.com",
                                             password="tmp-A1a")))
    assert fork["status"] == "password_reset_required"
    assert fork.get("role") == "customer"
    tok = fork["reset_token"]

    out = _run(reset_password(req, ResetPasswordRequest(
        token=tok, new_password="Brand-New-2026",
    )))
    # Auto-login envelope.
    assert out["ok"] is True
    assert out.get("auto_login") is True
    assert isinstance(out.get("access_token"), str) and len(out["access_token"]) > 20
    assert out.get("user", {}).get("id") == uid
    assert out["user"].get("role") == "customer"

    # DB state — flag flipped, first-login stamps set.
    u = fake_db.users.rows[0]
    assert u["must_change_password_on_next_login"] is False
    assert u["has_ever_logged_in"] is True
    assert u.get("first_password_reset_at")
    assert u.get("first_access_at")

    # Audit row for the first-login reset event.
    events = [r.get("event") for r in fake_db.audit_logs.rows]
    assert "customer.first_login_password_reset" in events


# ═════════════════════════════════════════════════════════════════════
# 2. Stale-flag customer (post-fix state) → NO fork + suspicious audit.
# ═════════════════════════════════════════════════════════════════════
def test_customer_stale_flag_no_fork_and_suspicious_audit(fake_db):
    from routers.auth import login, LoginRequest
    _seed_user(
        fake_db, role="customer", email="stale@ex.com",
        password="pwd-A1a",
        # Stale: already logged in, but flag was somehow re-armed.
        has_ever_logged_in=True, must_change=True,
    )
    req = _mk_request()
    out = _run(login(req, LoginRequest(email="stale@ex.com",
                                            password="pwd-A1a")))
    assert out.get("status") != "password_reset_required"
    assert "access_token" in out
    events = [r.get("event") for r in fake_db.audit_logs.rows]
    assert "customer.suspicious_forced_reset_flag" in events


# ═════════════════════════════════════════════════════════════════════
# 3. Non-customer role + flag=True → NO fork, normal login. Also NO
#    suspicious-flag audit (the flag has no meaning for staff).
# ═════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("role", ["admin", "technician", "super_admin"])
def test_non_customer_role_ignores_flag(fake_db, role):
    from routers.auth import login, LoginRequest
    _seed_user(
        fake_db, role=role, email=f"{role}@ex.com",
        password="staff-A1a",
        has_ever_logged_in=False, must_change=True,
    )
    req = _mk_request()
    out = _run(login(req, LoginRequest(email=f"{role}@ex.com",
                                              password="staff-A1a")))
    assert out.get("status") != "password_reset_required"
    assert "access_token" in out
    events = [r.get("event") for r in fake_db.audit_logs.rows]
    assert "customer.suspicious_forced_reset_flag" not in events


# ═════════════════════════════════════════════════════════════════════
# 4. Migration endpoint — dry-run counts + wet-run flip + idempotent.
# ═════════════════════════════════════════════════════════════════════
def test_migration_clear_stale_forced_reset_flags(fake_db):
    from routers.admin_migrations import (
        clear_stale_forced_reset_flags, ClearStaleForcedResetFlagsBody,
    )
    # 2 customers to fix + 1 unaffected (never logged in) + 1 staff
    # with the flag (must NOT be touched).
    _seed_user(fake_db, role="customer", email="a@ex.com",
                 has_ever_logged_in=True, must_change=True)
    _seed_user(fake_db, role="customer", email="b@ex.com",
                 has_ever_logged_in=True, must_change=True)
    _seed_user(fake_db, role="customer", email="never@ex.com",
                 has_ever_logged_in=False, must_change=True)
    _seed_user(fake_db, role="admin", email="admin@ex.com",
                 has_ever_logged_in=True, must_change=True)

    sa = {"id": "sa", "role": "super_admin"}
    tenant = {"id": "t-fx1"}

    # Dry-run: 2 scanned, 0 flipped (skipped), 0 errors.
    dry = _run(clear_stale_forced_reset_flags(
        ClearStaleForcedResetFlagsBody(dry_run=True), user=sa, tenant=tenant,
    ))
    assert dry["ok"] is True
    assert dry["dry_run"] is True
    assert dry["scanned"] == 2
    assert dry["flipped"] == 0
    assert dry["skipped"] == 2

    # Wet-run: 2 flipped.
    wet = _run(clear_stale_forced_reset_flags(
        ClearStaleForcedResetFlagsBody(dry_run=False), user=sa, tenant=tenant,
    ))
    assert wet["dry_run"] is False
    assert wet["scanned"] == 2
    assert wet["flipped"] == 2
    assert wet["errors"] == 0

    # Assert the DB actually reflects the flip on the two customers,
    # and the unaffected + staff rows are untouched.
    users_by_email = {u["email"]: u for u in fake_db.users.rows}
    assert users_by_email["a@ex.com"]["must_change_password_on_next_login"] is False
    assert users_by_email["b@ex.com"]["must_change_password_on_next_login"] is False
    assert users_by_email["never@ex.com"]["must_change_password_on_next_login"] is True
    assert users_by_email["admin@ex.com"]["must_change_password_on_next_login"] is True

    # Idempotent second run.
    again = _run(clear_stale_forced_reset_flags(
        ClearStaleForcedResetFlagsBody(dry_run=False), user=sa, tenant=tenant,
    ))
    assert again["scanned"] == 0
    assert again["flipped"] == 0


# ═════════════════════════════════════════════════════════════════════
# 5. Migration endpoint role gate: admin → 403, super_admin → 200.
# ═════════════════════════════════════════════════════════════════════
def test_migration_role_gate(fake_db):
    from fastapi import HTTPException
    from routers.admin_migrations import (
        clear_stale_forced_reset_flags, ClearStaleForcedResetFlagsBody,
    )
    tenant = {"id": "t-fx1"}
    # Admin → 403.
    with pytest.raises(HTTPException) as ei:
        _run(clear_stale_forced_reset_flags(
            ClearStaleForcedResetFlagsBody(),
            user={"id": "a", "role": "admin"}, tenant=tenant,
        ))
    assert ei.value.status_code == 403
    # Super-admin → 200 (no rows to touch, but endpoint returns ok).
    out = _run(clear_stale_forced_reset_flags(
        ClearStaleForcedResetFlagsBody(),
        user={"id": "sa", "role": "super_admin"}, tenant=tenant,
    ))
    assert out["ok"] is True
