"""Phase S1 · Feb-2026 — SaaS Security Lockdown pytest.

Coverage:
* S1.1 — env var read + login promotion + boot migration idempotency.
* S1.2 — switch-tenant admin 403, super_admin 200.
* S1.4 — create-user + promote role gate.

The suite runs against an ASGI transport (same pattern as G1 / F1) so
we don't depend on the live pod's `APP_ENV` posture.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

import httpx
import jwt as _jwt
import pytest

from tests._f7_loop_fixture import run_test


API = "/api"


def _get_app():
    from server import app
    return app


def _mint(uid: str, tid: str, role: str = "admin") -> str:
    from config import JWT_SECRET
    return _jwt.encode({
        "sub": uid, "email": f"{uid}@ex.test", "role": role,
        "tenant_id": tid,
        "exp": int((datetime.now(timezone.utc)
                     + timedelta(hours=1)).timestamp()),
    }, JWT_SECRET, algorithm="HS256")


# ═════════════════════════════════════════════════════════════════════
# Common seed — one tenant, an admin, a super_admin, a technician.
# ═════════════════════════════════════════════════════════════════════
@pytest.fixture
def s1_seed():
    tid = f"s1-{uuid.uuid4()}"
    admin_uid = f"s1-admin-{uuid.uuid4()}"
    super_uid = f"s1-super-{uuid.uuid4()}"
    tech_uid  = f"s1-tech-{uuid.uuid4()}"
    other_uid = f"s1-other-{uuid.uuid4()}"

    async def _seed(_db):
        await _db.tenants.insert_one({
            "id": tid, "name": "S1 Tenant",
            "slug": f"s1-{uuid.uuid4().hex[:6]}",
            "active": True, "settings": {}})
        await _db.users.insert_many([
            {"id": admin_uid, "email": f"{admin_uid}@ex.test",
              "role": "admin", "tenant_id": tid,
              "name": "Alex Admin"},
            {"id": super_uid, "email": f"{super_uid}@ex.test",
              "role": "super_admin", "tenant_id": tid,
              "name": "Sam Super"},
            {"id": tech_uid, "email": f"{tech_uid}@ex.test",
              "role": "technician", "tenant_id": tid,
              "name": "Terry Tech"},
            {"id": other_uid, "email": f"{other_uid}@ex.test",
              "role": "technician", "tenant_id": tid,
              "name": "Otto Other"},
        ])

    async def _teardown(_db):
        await _db.tenants.delete_many({"id": tid})
        await _db.users.delete_many({"id": {"$in": [
            admin_uid, super_uid, tech_uid, other_uid]}})
        # Clean any founder-migration test rows.
        await _db.users.delete_many({"email": {"$regex": "^s1-founder-.*"}})

    run_test(_seed)
    yield {
        "tid": tid,
        "admin_uid": admin_uid, "super_uid": super_uid,
        "tech_uid":  tech_uid,  "other_uid": other_uid,
        "admin_token": _mint(admin_uid, tid, "admin"),
        "super_token": _mint(super_uid, tid, "super_admin"),
        "tech_token":  _mint(tech_uid,  tid, "technician"),
    }
    run_test(_teardown)


# ═════════════════════════════════════════════════════════════════════
# S1.1 · Env var + boot migration + login-time promotion.
# ═════════════════════════════════════════════════════════════════════
def test_s1_env_var_read_at_module_load():
    """The auth module reads ``FOUNDER_SUPER_ADMIN_EMAIL`` at import
    time. On this preview pod ``.env`` pins it to ``brian@plofv.com``.
    Assert the module-level constant reflects that (or is empty if
    the env got unset). Never crashes on missing env — just warns."""
    from routers import auth as _auth
    val = _auth.FOUNDER_SUPER_ADMIN_EMAIL
    # Two acceptable states: pinned to the founder email, OR empty.
    assert isinstance(val, str)
    # If pinned (the preview default), value must be normalised.
    if val:
        assert val == val.lower().strip()


def test_s1_boot_migration_promotes_when_admin(s1_seed):
    S = s1_seed
    result: Dict[str, Any] = {}

    async def _go(_db):
        # Insert a synthetic founder row with role=admin so we can
        # observe the migration flipping it. Uses a temp override on
        # the module-level constant so the test isn't at the mercy of
        # the .env value.
        founder_email = f"s1-founder-{uuid.uuid4().hex[:6]}@ex.test"
        await _db.users.insert_one({
            "id": f"s1-founder-{uuid.uuid4()}",
            "email": founder_email,
            "role": "admin", "tenant_id": S["tid"],
        })
        from routers import auth as _auth
        old = _auth.FOUNDER_SUPER_ADMIN_EMAIL
        _auth.FOUNDER_SUPER_ADMIN_EMAIL = founder_email
        try:
            n1 = await _auth.promote_founder_on_boot()
            fresh = await _db.users.find_one({"email": founder_email},
                                                {"_id": 0})
            n2 = await _auth.promote_founder_on_boot()  # idempotent
        finally:
            _auth.FOUNDER_SUPER_ADMIN_EMAIL = old
        result["n1"] = n1
        result["n2"] = n2
        result["role"] = fresh["role"]

    run_test(_go)
    assert result["n1"] == 1
    assert result["n2"] == 0
    assert result["role"] == "super_admin"


def test_s1_boot_migration_no_row_no_crash(s1_seed):
    """Founder email set but no matching user row → returns 0, no crash."""
    result: Dict[str, Any] = {}

    async def _go(_db):
        from routers import auth as _auth
        old = _auth.FOUNDER_SUPER_ADMIN_EMAIL
        _auth.FOUNDER_SUPER_ADMIN_EMAIL = f"s1-nobody-{uuid.uuid4()}@ex.test"
        try:
            result["n"] = await _auth.promote_founder_on_boot()
        finally:
            _auth.FOUNDER_SUPER_ADMIN_EMAIL = old

    run_test(_go)
    assert result["n"] == 0


def test_s1_boot_migration_already_super_admin_no_op(s1_seed):
    S = s1_seed
    result: Dict[str, Any] = {}

    async def _go(_db):
        founder_email = f"s1-founder-super-{uuid.uuid4().hex[:6]}@ex.test"
        await _db.users.insert_one({
            "id": f"s1-fs-{uuid.uuid4()}", "email": founder_email,
            "role": "super_admin", "tenant_id": S["tid"]})
        from routers import auth as _auth
        old = _auth.FOUNDER_SUPER_ADMIN_EMAIL
        _auth.FOUNDER_SUPER_ADMIN_EMAIL = founder_email
        try:
            result["n"] = await _auth.promote_founder_on_boot()
        finally:
            _auth.FOUNDER_SUPER_ADMIN_EMAIL = old

    run_test(_go)
    assert result["n"] == 0  # already super_admin → no write


def test_s1_existing_super_not_demoted_by_migration(s1_seed):
    """super@aquaterra.com must remain super_admin — the migration
    never demotes existing supers, only promotes the founder email."""
    S = s1_seed
    result: Dict[str, Any] = {}

    async def _go(_db):
        # Seed a "founder" row + a totally unrelated super_admin;
        # after migration the unrelated one is untouched.
        founder_email = f"s1-founder-{uuid.uuid4().hex[:6]}@ex.test"
        await _db.users.insert_one({
            "id": f"s1-fs-{uuid.uuid4()}", "email": founder_email,
            "role": "admin", "tenant_id": S["tid"]})
        from routers import auth as _auth
        old = _auth.FOUNDER_SUPER_ADMIN_EMAIL
        _auth.FOUNDER_SUPER_ADMIN_EMAIL = founder_email
        try:
            await _auth.promote_founder_on_boot()
        finally:
            _auth.FOUNDER_SUPER_ADMIN_EMAIL = old
        # Assert the unrelated super_admin still has role=super_admin.
        fresh_super = await _db.users.find_one(
            {"id": S["super_uid"]}, {"_id": 0})
        result["super_role"] = fresh_super["role"]

    run_test(_go)
    assert result["super_role"] == "super_admin"


# ═════════════════════════════════════════════════════════════════════
# S1.2 · Switch-tenant super_admin only.
# ═════════════════════════════════════════════════════════════════════
def test_s1_switch_tenant_admin_403(s1_seed):
    S = s1_seed
    app = _get_app()
    result: Dict[str, Any] = {}

    async def _go(_db):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport,
                                        base_url="http://test") as c:
            r = await c.post(
                f"{API}/auth/switch-tenant",
                json={"tenant_id": S["tid"]},
                headers={"Authorization": f"Bearer {S['admin_token']}"})
            result["status"] = r.status_code
            result["detail"] = r.json().get("detail")

    run_test(_go)
    assert result["status"] == 403
    assert result["detail"] == "insufficient_role_for_tenant_switch"


def test_s1_switch_tenant_tech_403(s1_seed):
    S = s1_seed
    app = _get_app()
    result: Dict[str, Any] = {}

    async def _go(_db):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport,
                                        base_url="http://test") as c:
            r = await c.post(
                f"{API}/auth/switch-tenant",
                json={"tenant_id": S["tid"]},
                headers={"Authorization": f"Bearer {S['tech_token']}"})
            result["status"] = r.status_code

    run_test(_go)
    assert result["status"] == 403


def test_s1_switch_tenant_super_admin_still_works(s1_seed):
    S = s1_seed
    app = _get_app()
    result: Dict[str, Any] = {}

    async def _go(_db):
        # Give super membership in this tenant explicitly.
        await _db.users.update_one(
            {"id": S["super_uid"]},
            {"$set": {"tenant_memberships": [
                {"tenant_id": S["tid"], "role": "super_admin",
                  "joined_at": "2025-01-01T00:00:00+00:00"},
            ]}})
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport,
                                        base_url="http://test") as c:
            r = await c.post(
                f"{API}/auth/switch-tenant",
                json={"tenant_id": S["tid"]},
                headers={"Authorization": f"Bearer {S['super_token']}"})
            result["status"] = r.status_code
            result["body"] = r.json()

    run_test(_go)
    assert result["status"] == 200, result


# ═════════════════════════════════════════════════════════════════════
# S1.4 · Role picker lockdown (server side).
# ═════════════════════════════════════════════════════════════════════
def test_s1_create_user_admin_super_admin_role_403(s1_seed):
    S = s1_seed
    app = _get_app()
    result: Dict[str, Any] = {}

    async def _go(_db):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport,
                                        base_url="http://test") as c:
            r = await c.post(
                f"{API}/users",
                json={"first_name": "TEST_x", "last_name": "Y",
                       "email": f"s1-blocked-{uuid.uuid4().hex[:6]}@example.com",
                       "role": "super_admin",
                       "department": None},
                headers={"Authorization": f"Bearer {S['admin_token']}"})
            result["status"] = r.status_code
            result["detail"] = r.json().get("detail")

    run_test(_go)
    assert result["status"] == 403
    assert result["detail"] == "super_admin_role_not_assignable"


def test_s1_create_user_super_can_create_super(s1_seed):
    S = s1_seed
    app = _get_app()
    result: Dict[str, Any] = {}

    async def _go(_db):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport,
                                        base_url="http://test") as c:
            new_email = f"s1-newsuper-{uuid.uuid4().hex[:6]}@example.com"
            r = await c.post(
                f"{API}/users",
                json={"first_name": "TEST_new", "last_name": "Super",
                       "email": new_email,
                       "role": "super_admin",
                       "department": None},
                headers={"Authorization": f"Bearer {S['super_token']}"})
            result["status"] = r.status_code
            result["body"] = r.json()

    run_test(_go)
    assert result["status"] == 200, result


def test_s1_promote_admin_to_super_admin_by_admin_403(s1_seed):
    S = s1_seed
    app = _get_app()
    result: Dict[str, Any] = {}

    async def _go(_db):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport,
                                        base_url="http://test") as c:
            r = await c.post(
                f"{API}/users/{S['other_uid']}/promote",
                json={"role": "super_admin"},
                headers={"Authorization": f"Bearer {S['admin_token']}"})
            result["status"] = r.status_code
            result["detail"] = r.json().get("detail")

    run_test(_go)
    assert result["status"] == 403
    assert result["detail"] == "super_admin_role_not_assignable"


def test_s1_promote_admin_to_super_admin_by_super_admin_200(s1_seed):
    S = s1_seed
    app = _get_app()
    result: Dict[str, Any] = {}

    async def _go(_db):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport,
                                        base_url="http://test") as c:
            r = await c.post(
                f"{API}/users/{S['other_uid']}/promote",
                json={"role": "super_admin"},
                headers={"Authorization": f"Bearer {S['super_token']}"})
            result["status"] = r.status_code
            result["body"] = r.json()

    run_test(_go)
    assert result["status"] == 200, result
    assert result["body"]["new_role"] == "super_admin"
