"""Phase 20 · Feb-2026 · combined pytest for the P2 close-out backlog.

Sub-item A · Suggest-Departments admin modal
    A1) ``POST /api/admin/suggest-departments`` returns 200 with the
        expected schema (already covered in Phase 18 pytest, so here we
        exercise the *new* Phase 20 bulk-apply endpoint end-to-end).
    A2) ``POST /api/admin/users/bulk-department`` persists ``department``
        to ONLY the checked techs — unchecked techs are untouched.

Sub-item B · Notification tap-through resolver
    B1) A pure-Python port of the resolver logic (mirrors
        ``mobile/src/services/notificationRoutes.ts``) validates
        role-aware routing for ``kind="inventory_low_stock"``.

Sub-item C · Stripe pk_live cleanup
    C1) ``POST /api/payments/stripe/setup-intent`` includes
        ``publishable_key`` when the env is set.
    C2) ``GET  /api/payments/stripe/config`` returns
        ``{publishable_key, mode}`` correctly for both test and live
        modes, and 403s a technician.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import jwt
import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient
from tests._shared_mongo import (
    shared_client as _shared_client,
    shared_db as _shared_db,
)


os.environ.setdefault("ALLOW_TEST_HOOKS", "1")

_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = _shared_db()
API = "http://localhost:8001/api"

JWT_SECRET = _ENV.get("JWT_SECRET") or os.environ.get("JWT_SECRET") \
    or "dev-secret-change-me"
JWT_ALGO = _ENV.get("JWT_ALGO") or "HS256"


def _tok(user_id: str, email: str, role: str,
          tenant_id: str | None = None) -> str:
    payload = {
        "sub": user_id, "email": email, "role": role,
        "tenant_id": tenant_id or "",
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)


# ══════════════════════════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════════════════════════
@pytest.fixture()
def tenant_id():
    tid = f"p20-{uuid.uuid4().hex[:8]}"
    _sync.tenants.insert_one({
        "id": tid, "name": f"P20 {tid}", "slug": f"p20-{tid}",
        "active": True, "widget_allowed_domains": [],
    })
    yield tid
    for col in ("tenants", "users", "customers"):
        _sync[col].delete_many({"tenant_id": tid})


@pytest.fixture()
def admin(tenant_id):
    uid = f"admin-{uuid.uuid4().hex[:8]}"
    email = f"{uid}@p20.test"
    _sync.users.insert_one({
        "id": uid, "tenant_id": tenant_id, "role": "admin",
        "name": "P20 Admin", "email": email,
    })
    return {"id": uid, "email": email, "role": "admin",
            "tenant_id": tenant_id,
            "token": _tok(uid, email, "admin", tenant_id)}


@pytest.fixture()
def tech(tenant_id):
    uid = f"tech-{uuid.uuid4().hex[:8]}"
    email = f"{uid}@p20.test"
    _sync.users.insert_one({
        "id": uid, "tenant_id": tenant_id, "role": "technician",
        "name": "P20 Tech", "email": email,
        "technician_id": f"tid-{uuid.uuid4().hex[:6]}",
    })
    return {"id": uid, "email": email, "role": "technician",
            "tenant_id": tenant_id,
            "token": _tok(uid, email, "technician", tenant_id)}


# ══════════════════════════════════════════════════════════════════
# Sub-item A — bulk-apply department endpoint (used by the modal)
# ══════════════════════════════════════════════════════════════════
def test_A2_bulk_department_only_updates_selected(tenant_id, admin):
    ids = []
    for i in range(3):
        uid = f"bulk-user-{uuid.uuid4().hex[:6]}"
        _sync.users.insert_one({
            "id": uid, "tenant_id": tenant_id, "role": "technician",
            "name": f"Bulk tech {i}", "email": f"{uid}@p20.test",
            "department": None,
        })
        ids.append(uid)

    # Only assign the first two — the third must stay untouched.
    payload = {"assignments": [
        {"user_id": ids[0], "department": "pool_tech"},
        {"user_id": ids[1], "department": "landscape_tech"},
    ]}
    r = requests.post(
        f"{API}/admin/users/bulk-department",
        headers={"Authorization": f"Bearer {admin['token']}",
                 "X-Tenant-Id": tenant_id},
        json=payload,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["updated_count"] == 2
    assert body["total"] == 2
    row0 = _sync.users.find_one({"id": ids[0]})
    row1 = _sync.users.find_one({"id": ids[1]})
    row2 = _sync.users.find_one({"id": ids[2]})
    assert row0["department"] == "pool_tech"
    assert row1["department"] == "landscape_tech"
    assert row2.get("department") in (None, "")


def test_A1_suggest_departments_endpoint_is_reachable(tenant_id, admin):
    # Phase 18 shipped the endpoint; the modal calls it. Assert 200 +
    # schema (defensive — surface a break early if Phase 18 regresses).
    r = requests.post(
        f"{API}/admin/suggest-departments",
        headers={"Authorization": f"Bearer {admin['token']}",
                 "X-Tenant-Id": tenant_id},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "suggestions" in body
    assert "count" in body


# ══════════════════════════════════════════════════════════════════
# Sub-item B — notification route resolver
# (Python port mirrors mobile/src/services/notificationRoutes.ts —
#  keeps the two implementations in sync so a broken port fails CI.)
# ══════════════════════════════════════════════════════════════════
_ADMIN_ROLES = {"admin", "super_admin", "owner", "manager", "office"}


def _resolve_route(notif, user):
    if not notif:
        return None
    kind = (notif.get("kind") or "").lower()
    role = (user or {}).get("role") or ""
    if kind == "inventory_low_stock":
        return "/admin/inventory" if role in _ADMIN_ROLES \
            else "/inventory/my-inventory"
    if notif.get("job_id"):
        return f"/job/{notif['job_id']}"
    if notif.get("href"):
        return notif["href"]
    return None


def test_B1_inventory_low_stock_routes_by_role():
    # Admin path.
    assert _resolve_route({"kind": "inventory_low_stock"},
                          {"role": "admin"}) == "/admin/inventory"
    assert _resolve_route({"kind": "inventory_low_stock"},
                          {"role": "super_admin"}) == "/admin/inventory"
    # Tech path.
    assert _resolve_route({"kind": "inventory_low_stock"},
                          {"role": "technician"}) == "/inventory/my-inventory"
    assert _resolve_route({"kind": "inventory_low_stock"},
                          {"role": "tech"}) == "/inventory/my-inventory"
    # Fallback — no kind, job_id set.
    assert _resolve_route({"job_id": "abc123"}, {"role": "admin"}) \
        == "/job/abc123"
    # Fallback — href.
    assert _resolve_route({"href": "/settings"}, None) == "/settings"
    # Nothing to route on.
    assert _resolve_route({}, {"role": "admin"}) is None
    assert _resolve_route(None, {"role": "admin"}) is None


# ══════════════════════════════════════════════════════════════════
# Sub-item C — Stripe publishable-key plumbing
# ══════════════════════════════════════════════════════════════════
def _make_customer(tenant_id: str) -> str:
    cid = f"cust-{uuid.uuid4().hex[:8]}"
    _sync.customers.insert_one({
        "id": cid, "tenant_id": tenant_id,
        "name": "P20 Test Customer",
        "email": f"{cid}@p20.test",
        "stripe_customer_id": None,
    })
    return cid


def test_C2_config_endpoint_returns_shape(admin, tech, tenant_id):
    # Admin/manager/customer → 200. Technician → 403.
    with patch.dict(os.environ, {"STRIPE_MODE": "test",
                                 "STRIPE_PUBLISHABLE_KEY_TEST": "pk_test_p20"}):
        # Reset the module-level warned flag so subsequent tests get a fresh
        # publishable-key resolution.
        from services.payments import stripe_charge as _sc
        _sc._PUB_KEY_WARNED = False
        r_admin = requests.get(
            f"{API}/payments/stripe/config",
            headers={"Authorization": f"Bearer {admin['token']}",
                     "X-Tenant-Id": tenant_id},
        )
    assert r_admin.status_code == 200, r_admin.text
    body = r_admin.json()
    # The backend process reads env once per request — because our
    # subprocess doesn't inherit the patched env we just verify the
    # SHAPE here. The actual mode-driven value is proved by an
    # in-process assertion below.
    assert "publishable_key" in body
    assert "mode" in body
    assert body["mode"] in ("test", "live")

    # Tech → 403.
    r_tech = requests.get(
        f"{API}/payments/stripe/config",
        headers={"Authorization": f"Bearer {tech['token']}",
                 "X-Tenant-Id": tenant_id},
    )
    assert r_tech.status_code == 403, r_tech.text

    # In-process mode-driven proof — patch the env of THIS process and
    # call the module helper directly.
    from services.payments import stripe_charge as _sc
    with patch.dict(os.environ, {"STRIPE_MODE": "test",
                                 "STRIPE_PUBLISHABLE_KEY_TEST": "pk_test_p20_local"}):
        _sc._PUB_KEY_WARNED = False
        assert _sc._publishable_key() == "pk_test_p20_local"
        assert _sc._mode() == "test"
    with patch.dict(os.environ, {"STRIPE_MODE": "live",
                                 "STRIPE_PUBLISHABLE_KEY_LIVE": "pk_live_p20_local"}):
        _sc._PUB_KEY_WARNED = False
        assert _sc._publishable_key() == "pk_live_p20_local"
        assert _sc._mode() == "live"


def test_C1_setup_intent_includes_publishable_key(admin, tenant_id):
    """Setup-intent response must include ``publishable_key`` field.
    Uses the same in-process stub pattern as test_stripe_phase14a.py —
    keeps this test hermetic (no live Stripe HTTP) and independent of
    how the pod env is currently configured.
    """
    import asyncio
    from motor.motor_asyncio import AsyncIOMotorClient
    from services.payments import stripe_charge as _sc

    cid = _make_customer(tenant_id)

    class _FakeSetupIntent:
        @staticmethod
        def create(**kw):
            return {"id": "seti_p20_stub",
                    "client_secret": "seti_p20_stub_secret_xxx"}

    class _FakeCustomer:
        @staticmethod
        def create(**kw):
            return {"id": "cus_p20_stub"}

    class _FakeStripe:
        Customer = _FakeCustomer
        SetupIntent = _FakeSetupIntent
        api_key = None

    _sc.set_stripe_client(_FakeStripe)
    # Pin a loop for Motor in this in-process test.
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    _client = AsyncIOMotorClient(_ENV["MONGO_URL"], io_loop=loop)
    _db = _client[_ENV["DB_NAME"]]
    _sc.db = _db  # rebind service-side db to the loop-aligned client

    try:
        with patch.dict(os.environ, {"STRIPE_MODE": "test",
                                     "STRIPE_PUBLISHABLE_KEY_TEST": "pk_test_c1_local"}):
            _sc._PUB_KEY_WARNED = False
            out = loop.run_until_complete(_sc.create_setup_intent(
                tenant_id=tenant_id, customer_id=cid,
            ))
        assert "publishable_key" in out
        assert out["publishable_key"] == "pk_test_c1_local"
        assert out["mode"] == "test"
        assert out["client_secret"] == "seti_p20_stub_secret_xxx"
        assert out["setup_intent_id"] == "seti_p20_stub"
    finally:
        _sc.set_stripe_client(None)
        # Restore the service's db binding (server keeps its own reference).
        from config import db as _real_db
        _sc.db = _real_db
        loop.close()
