"""Feb-2026 · Customer temp password + first-access tracking.

Backend contract tests for:
  * ``routers.portal_admin._upsert_customer_user`` — stamps
    ``must_change_password_on_next_login=True`` + records
    ``temp_password_issued_at`` on both create + update paths.
  * ``POST /api/auth/login`` — when a matched user carries
    ``must_change_password_on_next_login=True``, the endpoint
    returns ``{status: "password_reset_required", reset_token,
    user_id, token_ttl_minutes: 15}`` with NO ``access_token``,
    mints a single-use row in ``password_reset_tokens``, and does
    NOT stamp portal-login denorms.
  * ``POST /api/auth/reset-password`` — consuming the token via the
    pre-existing Task-O primitive clears the flag (via
    ``_apply_new_password``) so the customer's SUBSEQUENT login
    completes normally + stamps ``first_access_at`` /
    ``has_ever_logged_in`` + the customer denorm
    ``portal_first_login_at`` exactly once.
  * ``GET /api/customers?first_access=never|any`` — the filter
    partitions correctly and rejects unknown values with 400.
  * The temp password itself does NOT expire — even after the
    15-min mid-flow token lapses, re-login with the same temp
    password succeeds and mints a fresh reset_token.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest

from passlib.context import CryptContext
_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class _Cursor:
    def __init__(self, rows):
        self._rows = list(rows)

    async def to_list(self, length=None):
        return list(self._rows)

    def sort(self, *a, **kw):
        return self


class _Coll:
    def __init__(self, rows=None):
        self.rows: List[Dict[str, Any]] = list(rows or [])
        self.inserts: List[Dict[str, Any]] = []
        self.updates: List[Dict[str, Any]] = []

    def find(self, filt=None, projection=None):
        return _Cursor(self._match(filt or {}))

    async def find_one(self, filt=None, projection=None, *a, **kw):
        rows = self._match(filt or {})
        sort = kw.get("sort")
        if sort:
            for key, direction in reversed(sort):
                rows = sorted(rows, key=lambda r: r.get(key) or "",
                                reverse=(direction == -1))
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
        self.updates.append({"filter": filt, "update": upd, "modified": n})
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
    from routers import portal_admin as pa_mod
    import config as cfg_mod
    import utils as utils_mod
    monkeypatch.setattr(auth_mod, "db", fake)
    monkeypatch.setattr(pa_mod, "db", fake)
    monkeypatch.setattr(cfg_mod, "db", fake)
    monkeypatch.setattr(utils_mod, "db", fake)
    return fake


def _mk_request(ip="1.2.3.4", ua="pytest/1.0"):
    return SimpleNamespace(
        client=SimpleNamespace(host=ip, port=None),
        headers={"user-agent": ua, "x-forwarded-for": ""},
        state=SimpleNamespace(timings=[]),
    )


def _seed_customer(fake_db, *, cid, tenant_id, email, name="Test Cust"):
    fake_db.customers.rows.append({
        "id": cid, "tenant_id": tenant_id, "email": email.lower(),
        "name": name,
    })


def _seed_temp_password_user(fake_db, *, email, password,
                                 uid=None, cid=None,
                                 tenant_id="t-tp-1"):
    """Simulates a portal user provisioned by an admin — carries the
    ``must_change_password_on_next_login`` flag + a matching customer
    row so the denorm branch is exercised."""
    uid = uid or str(uuid.uuid4())
    cid = cid or f"c-{uid}"
    _seed_customer(fake_db, cid=cid, tenant_id=tenant_id, email=email)
    fake_db.users.rows.append({
        "id": uid, "email": email.lower(), "role": "customer",
        "tenant_id": tenant_id, "name": "Test Cust",
        "customer_id": cid,
        "password_hash": _pwd.hash(password),
        "must_change_password_on_next_login": True,
        "temp_password_issued_at": "2026-02-01T00:00:00+00:00",
        "has_ever_logged_in": False,
        "first_access_at": None,
        "active": True,
    })
    return uid, cid


# ═════════════════════════════════════════════════════════════════════
# 1. ``_upsert_customer_user`` stamps the temp flag on both branches.
# ═════════════════════════════════════════════════════════════════════
def test_upsert_customer_user_stamps_temp_flag_on_create(fake_db):
    from routers.portal_admin import _upsert_customer_user
    _seed_customer(fake_db, cid="c-1", tenant_id="t-1",
                     email="new@example.com", name="New Cust")
    _run(_upsert_customer_user("c-1", "t-1", "new@example.com", "pwd-a1b2C"))
    users = fake_db.users.rows
    assert len(users) == 1
    u = users[0]
    assert u["must_change_password_on_next_login"] is True
    assert u.get("temp_password_issued_at")
    assert u.get("has_ever_logged_in") is False
    assert u.get("first_access_at") is None


def test_upsert_customer_user_stamps_temp_flag_on_update(fake_db):
    from routers.portal_admin import _upsert_customer_user
    _seed_customer(fake_db, cid="c-2", tenant_id="t-1",
                     email="old@example.com", name="Old Cust")
    # Pre-existing user row — reset flag should flip to True on rotate.
    fake_db.users.rows.append({
        "id": "u-old", "tenant_id": "t-1", "customer_id": "c-2",
        "email": "old@example.com", "role": "customer",
        "password_hash": _pwd.hash("old-pwd"),
        "must_change_password_on_next_login": False,
        "active": True,
    })
    _run(_upsert_customer_user("c-2", "t-1", "old@example.com", "new-pwd-A1"))
    u = fake_db.users.rows[0]
    assert u["must_change_password_on_next_login"] is True
    assert u.get("temp_password_issued_at")


# ═════════════════════════════════════════════════════════════════════
# 2. Login with temp password → password_reset_required (no token).
# ═════════════════════════════════════════════════════════════════════
def test_login_with_temp_password_returns_reset_required(fake_db):
    from routers.auth import login, LoginRequest
    uid, cid = _seed_temp_password_user(
        fake_db, email="brian@example.com", password="tmp-pass-A1")
    req = _mk_request()
    out = _run(login(req, LoginRequest(email="brian@example.com",
                                          password="tmp-pass-A1")))
    assert out["status"] == "password_reset_required"
    assert out["user_id"] == uid
    assert isinstance(out["reset_token"], str) and len(out["reset_token"]) > 20
    assert out["token_ttl_minutes"] == 15
    assert "access_token" not in out
    # Token row was minted.
    assert len(fake_db.password_reset_tokens.inserts) == 1
    row = fake_db.password_reset_tokens.inserts[0]
    assert row["user_id"] == uid
    assert row["source"] == "temp_password_login"
    assert row["used_at"] is None
    # Portal-login denorm NOT stamped on the customer.
    cust = fake_db.customers.rows[0]
    assert "last_portal_login_at" not in cust
    assert "portal_first_login_at" not in cust
    # first_access flags on the user remain untouched.
    u = fake_db.users.rows[0]
    assert u.get("has_ever_logged_in") is False
    assert u.get("first_access_at") is None


# ═════════════════════════════════════════════════════════════════════
# 3. Wrong password on a temp-password account still 401s.
# ═════════════════════════════════════════════════════════════════════
def test_wrong_password_on_temp_user_still_401(fake_db):
    from fastapi import HTTPException
    from routers.auth import login, LoginRequest
    _seed_temp_password_user(fake_db, email="brian@example.com",
                                 password="tmp-pass-A1")
    req = _mk_request()
    with pytest.raises(HTTPException) as ei:
        _run(login(req, LoginRequest(email="brian@example.com",
                                          password="WRONG")))
    assert ei.value.status_code == 401


# ═════════════════════════════════════════════════════════════════════
# 4. Full flow — temp password login → reset → normal login stamps
#    first-access denorms exactly ONCE.
# ═════════════════════════════════════════════════════════════════════
def test_temp_password_then_reset_then_login_stamps_first_access(fake_db):
    from routers.auth import (login, reset_password,
                                     LoginRequest, ResetPasswordRequest)
    uid, cid = _seed_temp_password_user(
        fake_db, email="linda@example.com", password="tmp-pass-A1")
    req = _mk_request()
    # Step 1 — temp password login → password_reset_required.
    fork = _run(login(req, LoginRequest(email="linda@example.com",
                                             password="tmp-pass-A1")))
    reset_token = fork["reset_token"]

    # Step 2 — consume the token via the existing Task-O endpoint.
    out = _run(reset_password(req, ResetPasswordRequest(
        token=reset_token, new_password="Brand-New-Pw-2026",
    )))
    assert out["ok"] is True
    # ``_apply_new_password`` cleared the flag.
    u = fake_db.users.rows[0]
    assert u["must_change_password_on_next_login"] is False

    # Step 3 — normal login with the new password.
    out2 = _run(login(req, LoginRequest(email="linda@example.com",
                                              password="Brand-New-Pw-2026")))
    assert "access_token" in out2
    assert out2.get("status") != "password_reset_required"
    # First-access denorms are now stamped.
    u = fake_db.users.rows[0]
    assert u["has_ever_logged_in"] is True
    assert u["first_access_at"]
    cust = fake_db.customers.rows[0]
    assert cust.get("portal_first_login_at") == u["first_access_at"]
    assert cust.get("last_portal_login_at")

    # Step 4 — a SECOND login must not overwrite portal_first_login_at.
    first_stamp = cust["portal_first_login_at"]
    out3 = _run(login(req, LoginRequest(email="linda@example.com",
                                              password="Brand-New-Pw-2026")))
    assert "access_token" in out3
    assert fake_db.customers.rows[0]["portal_first_login_at"] == first_stamp


# ═════════════════════════════════════════════════════════════════════
# 5. Temp password itself does NOT expire — even if the mid-flow
#    reset_token would time out, a re-login mints a fresh one.
# ═════════════════════════════════════════════════════════════════════
def test_temp_password_never_expires_relogin_mints_fresh_token(fake_db):
    from routers.auth import login, LoginRequest
    _seed_temp_password_user(fake_db, email="brian@example.com",
                                 password="tmp-pass-A1")
    req = _mk_request()
    first = _run(login(req, LoginRequest(email="brian@example.com",
                                              password="tmp-pass-A1")))
    # Force the first token to look "expired" — simulate 15+ min lapse
    # by rewriting its expires_at in the fake collection.
    fake_db.password_reset_tokens.rows[0]["expires_at"] = (
        (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    )
    # A second login with the SAME temp password still succeeds and
    # mints a FRESH token — the temp password itself never expired.
    second = _run(login(req, LoginRequest(email="brian@example.com",
                                                password="tmp-pass-A1")))
    assert second["status"] == "password_reset_required"
    assert second["reset_token"] != first["reset_token"]
    # Prior token was invalidated so a replay is dead.
    prior = fake_db.password_reset_tokens.rows[0]
    assert prior.get("invalidated_at")


# ═════════════════════════════════════════════════════════════════════
# 6. ``GET /api/customers?first_access=never|any`` partitions correctly.
# ═════════════════════════════════════════════════════════════════════
def test_customers_first_access_filter_partitions(fake_db, monkeypatch):
    from routers import customers as cust_mod
    monkeypatch.setattr(cust_mod, "db", fake_db)
    _seed_customer(fake_db, cid="c-a", tenant_id="t-t4",
                     email="a@example.com", name="A")
    _seed_customer(fake_db, cid="c-b", tenant_id="t-t4",
                     email="b@example.com", name="B")
    # C has completed a first login.
    fake_db.customers.rows[1]["portal_first_login_at"] = (
        "2026-02-10T09:00:00+00:00"
    )

    admin = {"id": "u-adm", "role": "admin", "tenant_id": "t-t4"}
    tenant = {"id": "t-t4"}

    never_rows = _run(cust_mod.list_customers(
        user=admin, tenant=tenant, first_access="never",
        # explicit defaults for kwargs the function needs
        search=None, tag=None, tags=None, city=None, waitlisted=None,
        unscheduled=None, is_active=None, missing_card=None,
        missing_email=False, missing_phone=False,
        missing_address=False, portal_activated=None,
        portal_status=None, is_muted=None, has_payment_method=None,
        count_only=False, include_deleted=False, include_merged=False,
        page=None, page_size=None, sort="created_desc",
    ))
    never_ids = {r["id"] for r in never_rows}
    assert never_ids == {"c-a"}

    any_rows = _run(cust_mod.list_customers(
        user=admin, tenant=tenant, first_access="any",
        search=None, tag=None, tags=None, city=None, waitlisted=None,
        unscheduled=None, is_active=None, missing_card=None,
        missing_email=False, missing_phone=False,
        missing_address=False, portal_activated=None,
        portal_status=None, is_muted=None, has_payment_method=None,
        count_only=False, include_deleted=False, include_merged=False,
        page=None, page_size=None, sort="created_desc",
    ))
    any_ids = {r["id"] for r in any_rows}
    assert any_ids == {"c-b"}


def test_customers_first_access_invalid_value_rejected(fake_db, monkeypatch):
    from fastapi import HTTPException
    from routers import customers as cust_mod
    monkeypatch.setattr(cust_mod, "db", fake_db)
    admin = {"id": "u-adm", "role": "admin", "tenant_id": "t-t4"}
    tenant = {"id": "t-t4"}
    with pytest.raises(HTTPException) as ei:
        _run(cust_mod.list_customers(
            user=admin, tenant=tenant, first_access="bogus",
            search=None, tag=None, tags=None, city=None,
            waitlisted=None, unscheduled=None, is_active=None,
            missing_card=None, missing_email=False, missing_phone=False,
            missing_address=False, portal_activated=None,
            portal_status=None, is_muted=None, has_payment_method=None,
            count_only=False, include_deleted=False, include_merged=False,
            page=None, page_size=None, sort="created_desc",
        ))
    assert ei.value.status_code == 400
    assert "invalid_first_access" in str(ei.value.detail)
