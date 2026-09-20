"""Phase G1 · Feb-2026 — Cleanup Sprint backend pytest.

Coverage
--------
* G1.1 — messages unread-count aggregator (happy / zero / cross-channel /
  tenant isolation).
* G1.2 — PATCH default-tenant (happy, invalid tenant, role gate,
  same-tenant no-op).
* G1.3 — pilot-tenants health (happy, orphan detection, role gate).
* G1.6 — currency validation accepts full ISO catalog (JPY, INR, etc.).
"""
from __future__ import annotations

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


@pytest.fixture
def g1_seed():
    tid_a = f"g1-{uuid.uuid4()}"
    tid_b = f"g1-{uuid.uuid4()}"
    admin_uid = f"g1-admin-{uuid.uuid4()}"
    super_uid = f"g1-super-{uuid.uuid4()}"
    tech_uid  = f"g1-tech-{uuid.uuid4()}"
    b_uid     = f"g1-b-{uuid.uuid4()}"

    async def _seed(_db):
        await _db.tenants.insert_many([
            {"id": tid_a, "name": "G1 Tenant A",
              "slug": f"g1-a-{uuid.uuid4().hex[:6]}",
              "active": True, "settings": {}},
            {"id": tid_b, "name": "G1 Tenant B",
              "slug": f"g1-b-{uuid.uuid4().hex[:6]}",
              "active": True, "settings": {}},
        ])
        await _db.users.insert_many([
            {"id": admin_uid, "email": f"{admin_uid}@ex.test",
              "role": "admin", "tenant_id": tid_a,
              "tenant_memberships": [
                  {"tenant_id": tid_a, "role": "admin",
                    "joined_at": datetime.now(timezone.utc).isoformat()},
                  {"tenant_id": tid_b, "role": "admin",
                    "joined_at": datetime.now(timezone.utc).isoformat()},
              ]},
            {"id": super_uid, "email": f"{super_uid}@ex.test",
              "role": "super_admin", "tenant_id": tid_a,
              "tenant_memberships": [
                  {"tenant_id": tid_a, "role": "super_admin",
                    "joined_at": datetime.now(timezone.utc).isoformat()},
              ]},
            {"id": tech_uid, "email": f"{tech_uid}@ex.test",
              "role": "technician", "tenant_id": tid_a},
            {"id": b_uid, "email": f"{b_uid}@ex.test",
              "role": "technician", "tenant_id": tid_b},
        ])

    async def _teardown(_db):
        await _db.tenants.delete_many({"id": {"$in": [tid_a, tid_b]}})
        await _db.users.delete_many({"id": {"$in": [
            admin_uid, super_uid, tech_uid, b_uid]}})
        await _db.chat_conversations.delete_many(
            {"tenant_id": {"$in": [tid_a, tid_b]}})
        await _db.chat_messages.delete_many(
            {"tenant_id": {"$in": [tid_a, tid_b]}})
        await _db.chat_reads.delete_many(
            {"tenant_id": {"$in": [tid_a, tid_b]}})
        await _db.sms_messages.delete_many(
            {"tenant_id": {"$in": [tid_a, tid_b]}})

    run_test(_seed)
    yield {
        "tid_a": tid_a, "tid_b": tid_b,
        "admin_uid": admin_uid, "super_uid": super_uid,
        "tech_uid":  tech_uid,  "b_uid": b_uid,
        "admin_token": _mint(admin_uid, tid_a, "admin"),
        "super_token": _mint(super_uid, tid_a, "super_admin"),
        "tech_token":  _mint(tech_uid,  tid_a, "technician"),
        "b_admin_token": _mint(b_uid, tid_b, "admin"),
    }
    run_test(_teardown)


# ═════════════════════════════════════════════════════════════════════
# G1.1 · Messages unread-count.
# ═════════════════════════════════════════════════════════════════════
def test_unread_count_zero_state(g1_seed):
    S = g1_seed
    app = _get_app()
    out: Dict[str, Any] = {}

    async def _go(_db):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport,
                                        base_url="http://test") as c:
            r = await c.get(
                f"{API}/messages/unread-count",
                headers={"Authorization": f"Bearer {S['admin_token']}"})
            out["status"] = r.status_code
            out["body"] = r.json()

    run_test(_go)
    assert out["status"] == 200, out
    assert out["body"] == {"unread_count": 0, "by_channel": {}}


def test_unread_count_cross_channel(g1_seed):
    S = g1_seed
    app = _get_app()
    out: Dict[str, Any] = {}
    cid = f"g1-conv-{uuid.uuid4()}"

    async def _go(_db):
        # Seed a chat channel with 3 unread messages from a stranger.
        now = datetime.now(timezone.utc).isoformat()
        await _db.chat_conversations.insert_one({
            "id": cid, "tenant_id": S["tid_a"], "type": "channel",
            "name": "general", "slug": "general",
            "member_ids": [S["admin_uid"], S["tech_uid"]],
            "created_by": S["tech_uid"], "is_archived": False,
            "created_at": now, "last_message_at": now,
        })
        await _db.chat_messages.insert_many([
            {"id": f"g1-msg-{i}", "tenant_id": S["tid_a"],
              "conversation_id": cid, "thread_root_id": None,
              "author_user_id": S["tech_uid"],
              "body_markdown": f"hey #{i}",
              "created_at": now, "deleted_at": None}
            for i in range(3)
        ])
        # Seed 2 unread inbound SMS for tenant A.
        await _db.sms_messages.insert_many([
            {"id": f"g1-sms-{i}", "tenant_id": S["tid_a"],
              "direction": "inbound", "body": "ping",
              "created_at": now}
            for i in range(2)
        ])
        # Seed unrelated inbound SMS for tenant B — must NOT count for A.
        await _db.sms_messages.insert_one({
            "id": f"g1-sms-b", "tenant_id": S["tid_b"],
            "direction": "inbound", "body": "ignore",
            "created_at": now})

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport,
                                        base_url="http://test") as c:
            r = await c.get(
                f"{API}/messages/unread-count",
                headers={"Authorization": f"Bearer {S['admin_token']}"})
            out["A"] = r.json()
            r2 = await c.get(
                f"{API}/messages/unread-count",
                headers={"Authorization": f"Bearer {S['b_admin_token']}"})
            out["B"] = r2.json()

    run_test(_go)
    assert out["A"]["unread_count"] == 5
    assert out["A"]["by_channel"] == {"chat": 3, "sms": 2}
    assert out["B"]["unread_count"] == 1
    assert out["B"]["by_channel"] == {"sms": 1}


# ═════════════════════════════════════════════════════════════════════
# G1.2 · PATCH default-tenant.
# ═════════════════════════════════════════════════════════════════════
def test_default_tenant_happy(g1_seed):
    S = g1_seed
    app = _get_app()
    out: Dict[str, Any] = {}

    async def _go(_db):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport,
                                        base_url="http://test") as c:
            r = await c.patch(
                f"{API}/admin/users/{S['admin_uid']}/default-tenant",
                json={"tenant_id": S["tid_b"]},
                headers={"Authorization": f"Bearer {S['super_token']}"})
            out["status"] = r.status_code
            out["body"] = r.json()
        fresh = await _db.users.find_one({"id": S["admin_uid"]},
                                            {"_id": 0})
        out["default"] = fresh["tenant_id"]
        out["active"]  = fresh.get("active_tenant_id")

    run_test(_go)
    assert out["status"] == 200
    assert out["body"]["changed"] is True
    assert out["default"] == S["tid_b"]
    assert out["active"] == S["tid_b"]


def test_default_tenant_invalid(g1_seed):
    S = g1_seed
    app = _get_app()
    out: Dict[str, Any] = {}
    stranger = f"stranger-{uuid.uuid4()}"

    async def _go(_db):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport,
                                        base_url="http://test") as c:
            r = await c.patch(
                f"{API}/admin/users/{S['admin_uid']}/default-tenant",
                json={"tenant_id": stranger},
                headers={"Authorization": f"Bearer {S['super_token']}"})
            out["status"] = r.status_code
            out["detail"] = r.json().get("detail")

    run_test(_go)
    assert out["status"] == 400
    assert out["detail"] == "tenant_not_in_memberships"


def test_default_tenant_role_gate(g1_seed):
    S = g1_seed
    app = _get_app()
    out: Dict[str, Any] = {}

    async def _go(_db):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport,
                                        base_url="http://test") as c:
            r = await c.patch(
                f"{API}/admin/users/{S['admin_uid']}/default-tenant",
                json={"tenant_id": S["tid_b"]},
                headers={"Authorization": f"Bearer {S['admin_token']}"})
            out["status"] = r.status_code
            out["detail"] = r.json().get("detail")

    run_test(_go)
    assert out["status"] == 403
    assert out["detail"] == "insufficient_role_for_membership_mgmt"


def test_default_tenant_idempotent(g1_seed):
    S = g1_seed
    app = _get_app()
    out: Dict[str, Any] = {}

    async def _go(_db):
        # Set active_tenant_id to current default first so both fields
        # match the requested tenant → idempotent path.
        await _db.users.update_one(
            {"id": S["admin_uid"]},
            {"$set": {"active_tenant_id": S["tid_a"]}})
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport,
                                        base_url="http://test") as c:
            r = await c.patch(
                f"{API}/admin/users/{S['admin_uid']}/default-tenant",
                json={"tenant_id": S["tid_a"]},
                headers={"Authorization": f"Bearer {S['super_token']}"})
            out["status"] = r.status_code
            out["body"] = r.json()

    run_test(_go)
    assert out["status"] == 200
    assert out["body"]["changed"] is False


# ═════════════════════════════════════════════════════════════════════
# G1.3 · Pilot tenants health.
# ═════════════════════════════════════════════════════════════════════
def test_pilots_health_super_admin_ok(g1_seed):
    S = g1_seed
    app = _get_app()
    out: Dict[str, Any] = {}

    async def _go(_db):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport,
                                        base_url="http://test") as c:
            r = await c.get(
                f"{API}/admin/tenants/pilots/health",
                headers={"Authorization": f"Bearer {S['super_token']}"})
            out["status"] = r.status_code
            out["body"] = r.json()

    run_test(_go)
    assert out["status"] == 200
    body = out["body"]
    assert set(p["slug"] for p in body["pilots"]) == {"pool", "landscaping"}
    for p in body["pilots"]:
        # In this pod both pilots must exist (created by
        # scripts.create_pilot_tenants + kept alive by the G1 test
        # migration guarantee).
        assert isinstance(p["orphan_memberships"], int)
        assert p["orphan_memberships"] == 0, (
            f"orphan memberships detected for {p['slug']}: {p}")


def test_pilots_health_role_gate(g1_seed):
    S = g1_seed
    app = _get_app()
    out: Dict[str, Any] = {}

    async def _go(_db):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport,
                                        base_url="http://test") as c:
            r = await c.get(
                f"{API}/admin/tenants/pilots/health",
                headers={"Authorization": f"Bearer {S['admin_token']}"})
            out["status"] = r.status_code

    run_test(_go)
    assert out["status"] == 403


# ═════════════════════════════════════════════════════════════════════
# G1.6 · Full ISO catalog validation.
# ═════════════════════════════════════════════════════════════════════
def test_currency_accepts_iso_code_beyond_shortlist(g1_seed):
    S = g1_seed
    app = _get_app()
    out: Dict[str, Any] = {}

    async def _go(_db):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport,
                                        base_url="http://test") as c:
            # JPY is NOT in the F1 shortlist but IS a real ISO 4217.
            r = await c.patch(
                f"{API}/tenants/mine/settings/business",
                json={"currency": "JPY"},
                headers={"Authorization": f"Bearer {S['admin_token']}"})
            out["status"] = r.status_code
            out["body"] = r.json()

    run_test(_go)
    assert out["status"] == 200
    assert out["body"]["currency"] == "JPY"
    assert out["body"]["currency_symbol"] == "¥"


def test_currency_rejects_random_codes(g1_seed):
    S = g1_seed
    app = _get_app()
    out: Dict[str, Any] = {}

    async def _go(_db):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport,
                                        base_url="http://test") as c:
            r = await c.patch(
                f"{API}/tenants/mine/settings/business",
                json={"currency": "ZZZ"},
                headers={"Authorization": f"Bearer {S['admin_token']}"})
            out["status"] = r.status_code
            out["detail"] = r.json()["detail"]

    run_test(_go)
    assert out["status"] == 400
    assert out["detail"]["error"] == "unsupported_currency"
    assert out["detail"]["attempted"] == "ZZZ"


def test_reference_currencies_endpoint(g1_seed):
    S = g1_seed
    app = _get_app()
    out: Dict[str, Any] = {}

    async def _go(_db):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport,
                                        base_url="http://test") as c:
            r = await c.get(
                f"{API}/reference/currencies",
                headers={"Authorization": f"Bearer {S['tech_token']}"})
            out["status"] = r.status_code
            data = r.json()
            out["count"] = len(data.get("currencies") or [])
            out["codes"] = {c["code"] for c in data["currencies"]}

    run_test(_go)
    assert out["status"] == 200
    # pycountry ships ~181 ISO 4217 codes. Assert we're well beyond
    # the F1 shortlist and that the shortlist itself is still in there.
    assert out["count"] > 100, out
    assert {"USD", "EUR", "GBP", "JPY", "INR"} <= out["codes"]
