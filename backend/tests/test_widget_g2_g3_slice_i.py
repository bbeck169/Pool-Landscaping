"""Feb-2026 · Slice G2/G3/Slice I — new backend endpoints:
* GET /api/widget/config
* GET /api/tenants/mine/widget-config/denied-requests
* GET/POST /api/customer-portal/walkthrough/{status,complete}
"""
from __future__ import annotations

import asyncio
import os
import uuid

import pytest
import requests

BASE_URL = "http://localhost:8001"
API = f"{BASE_URL}/api"


def _login(email, pw="password123"):
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": pw}, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def super_headers():
    return {"Authorization": f"Bearer {_login('super@aquaterra.com')}"}


@pytest.fixture(scope="module")
def admin_headers():
    return {"Authorization": f"Bearer {_login('admin@aquaterra.com')}"}


@pytest.fixture(scope="module")
def tech_headers():
    return {"Authorization": f"Bearer {_login('mike@aquaterra.com')}"}


@pytest.fixture(scope="module")
def customer_headers():
    return {"Authorization": f"Bearer {_login('customer@aquaterra.com')}"}


_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)


def _run(coro):
    return _LOOP.run_until_complete(coro)


def _rebind_db_to_loop():
    from motor.motor_asyncio import AsyncIOMotorClient
    from dotenv import load_dotenv
    load_dotenv("/app/backend/.env")
    fresh = AsyncIOMotorClient(os.environ["MONGO_URL"], io_loop=_LOOP)
    fresh_db = fresh[os.environ["DB_NAME"]]
    import config as _cfg
    _cfg.db = fresh_db
    import routers.widget_config as _wc
    _wc.db = fresh_db
    import routers.portal_walkthrough as _pw
    _pw.db = fresh_db
    return fresh_db


@pytest.fixture(scope="module", autouse=True)
def _bind_db():
    _rebind_db_to_loop()
    yield
    try:
        from motor.motor_asyncio import AsyncIOMotorClient
        from dotenv import load_dotenv
        load_dotenv("/app/backend/.env")
        fresh = AsyncIOMotorClient(os.environ["MONGO_URL"])
        fresh_db = fresh[os.environ["DB_NAME"]]
        import config as _cfg
        _cfg.db = fresh_db
        import routers.widget_config as _wc
        _wc.db = fresh_db
    except Exception:
        pass


def _widget_key(super_headers):
    r = requests.get(f"{API}/tenants/mine/widget-config",
                      headers=super_headers, timeout=15)
    return r.json()["public_widget_key"]


def _whitelist(super_headers, host):
    r = requests.patch(f"{API}/tenants/mine/widget-config/domains",
                        headers=super_headers,
                        json={"domains": [host]}, timeout=15)
    assert r.status_code == 200


def _widget_headers(key, host):
    return {"X-Widget-Key": key, "Origin": f"https://{host}"}


# ═══════════════════════════════════════════════════════════════════════
# G2 — GET /api/widget/config
# ═══════════════════════════════════════════════════════════════════════
def test_widget_config_returns_public_branding(super_headers):
    host = f"g2-cfg-{uuid.uuid4().hex[:6]}.example.com"
    _whitelist(super_headers, host)
    key = _widget_key(super_headers)
    r = requests.get(f"{API}/widget/config",
                      headers=_widget_headers(key, host), timeout=15)
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["tenant_slug"] == "aquaterra"
    assert b["brand_color"].startswith("#")
    assert "welcome_message" in b
    # Internal fields must not leak.
    assert "widget_allowed_domains" not in b
    assert "public_widget_key" not in b


def test_widget_config_requires_widget_auth():
    r = requests.get(f"{API}/widget/config", timeout=15)
    assert r.status_code == 401


# ═══════════════════════════════════════════════════════════════════════
# G3 — denied requests ring buffer
# ═══════════════════════════════════════════════════════════════════════
def test_denied_ring_admin_read_scoped_to_tenant(admin_headers, super_headers):
    # Trigger a rejection (foreign origin) under aquaterra's key.
    host = f"g3-ring-{uuid.uuid4().hex[:6]}.example.com"
    _whitelist(super_headers, host)
    key = _widget_key(super_headers)
    requests.get(f"{API}/widget/config",
                  headers={"X-Widget-Key": key,
                            "Origin": "https://foreign-attacker.example"},
                  timeout=15)

    r = requests.get(f"{API}/tenants/mine/widget-config/denied-requests",
                      headers=admin_headers, timeout=15)
    assert r.status_code == 200
    denied = r.json().get("denied", [])
    # At least one row exists; the most recent should be our foreign_origin.
    assert len(denied) >= 1
    assert any(row.get("reason") == "foreign_origin"
                and row.get("origin") == "https://foreign-attacker.example"
                for row in denied)


def test_denied_ring_tech_forbidden(tech_headers):
    r = requests.get(f"{API}/tenants/mine/widget-config/denied-requests",
                      headers=tech_headers, timeout=15)
    assert r.status_code in (401, 403)


def test_denied_ring_customer_forbidden(customer_headers):
    r = requests.get(f"{API}/tenants/mine/widget-config/denied-requests",
                      headers=customer_headers, timeout=15)
    assert r.status_code in (401, 403)


def test_denied_ring_never_leaks_invalid_key_rows(admin_headers):
    """Rejections with an unresolvable widget key are stored under an
    ``__unknown__`` bucket, NEVER under a tenant. Admin reads only
    their own tenant's bucket. Verifies foreign hits can't leak."""
    # Trigger an invalid_key rejection.
    requests.get(f"{API}/widget/config",
                  headers={"X-Widget-Key": "pk_definitelynotreal",
                            "Origin": "https://foreign.evil"},
                  timeout=15)
    r = requests.get(f"{API}/tenants/mine/widget-config/denied-requests",
                      headers=admin_headers, timeout=15)
    denied = r.json().get("denied", [])
    for row in denied:
        # Aquaterra's ring must not contain invalid_key entries — those
        # went to __unknown__.
        assert row.get("reason") != "invalid_key", row


# ═══════════════════════════════════════════════════════════════════════
# Slice I — walkthrough endpoints
# ═══════════════════════════════════════════════════════════════════════
def test_walkthrough_status_returns_grandfathered_for_existing(customer_headers):
    r = requests.get(f"{API}/customer-portal/walkthrough/status",
                      headers=customer_headers, timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    # Existing demo customer was grandfathered by boot backfill.
    assert body["completed"] is True
    assert body["should_show"] is False
    assert body["completed_at"] in ("grandfathered",) or \
        isinstance(body["completed_at"], str)


def test_walkthrough_complete_marks_flag(customer_headers):
    """POST /complete flips the flag to an ISO timestamp (used by
    fresh customers who see the tour for the first time)."""

    async def _reset():
        from routers.portal_walkthrough import db as pw_db
        r = requests.get(f"{API}/auth/me",
                          headers=customer_headers, timeout=15)
        cust_id = r.json().get("customer_id")
        tenant_id = r.json().get("tenant_id")
        await pw_db.customers.update_one(
            {"id": cust_id, "tenant_id": tenant_id},
            {"$unset": {"portal_walkthrough_completed_at": ""}},
        )
        return cust_id
    cid = _run(_reset())

    r = requests.get(f"{API}/customer-portal/walkthrough/status",
                      headers=customer_headers, timeout=15)
    assert r.json()["should_show"] is True

    r = requests.post(f"{API}/customer-portal/walkthrough/complete",
                       headers=customer_headers, timeout=15)
    assert r.status_code == 200, r.text
    ts = r.json()["completed_at"]
    assert ts.startswith("20"), ts        # ISO year prefix

    # Status now reports completed.
    r = requests.get(f"{API}/customer-portal/walkthrough/status",
                      headers=customer_headers, timeout=15)
    assert r.json()["should_show"] is False


def test_walkthrough_status_forbidden_for_admin(admin_headers):
    r = requests.get(f"{API}/customer-portal/walkthrough/status",
                      headers=admin_headers, timeout=15)
    assert r.status_code == 403
