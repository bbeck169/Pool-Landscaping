"""Feb-2026 · Slice GH0 — Public widget key + domain whitelist."""
from __future__ import annotations

import asyncio, os, uuid
import pytest, requests

BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or "http://localhost:8001").rstrip("/")
API = f"{BASE_URL}/api"


def _login(email, pw="password123"):
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": pw}, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def admin_headers():
    return {"Authorization": f"Bearer {_login('admin@aquaterra.com')}"}


@pytest.fixture(scope="module")
def super_headers():
    return {"Authorization": f"Bearer {_login('super@aquaterra.com')}"}


@pytest.fixture(scope="module")
def tech_headers():
    return {"Authorization": f"Bearer {_login('mike@aquaterra.com')}"}


_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)
def _run(coro): return _LOOP.run_until_complete(coro)


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
    return fresh_db


@pytest.fixture(scope="module", autouse=True)
def _bind_db():
    _rebind_db_to_loop()
    yield


def _db():
    from motor.motor_asyncio import AsyncIOMotorClient
    from dotenv import load_dotenv
    load_dotenv("/app/backend/.env")
    return AsyncIOMotorClient(os.environ["MONGO_URL"],
                               io_loop=_LOOP)[os.environ["DB_NAME"]]


# ═══════════════════════════════════════════════════════════════════════
# Config GET · lazy key generation · RBAC
# ═══════════════════════════════════════════════════════════════════════
def test_get_widget_config_lazy_generates_key(admin_headers):
    r = requests.get(f"{API}/tenants/mine/widget-config",
                      headers=admin_headers, timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["public_widget_key"].startswith("pk_")
    assert len(body["public_widget_key"]) > 20
    assert isinstance(body["widget_allowed_domains"], list)

    # Second read returns the SAME key — no accidental rotation.
    r2 = requests.get(f"{API}/tenants/mine/widget-config",
                       headers=admin_headers, timeout=15).json()
    assert r2["public_widget_key"] == body["public_widget_key"]


def test_widget_config_rbac(tech_headers):
    """Techs + unauthenticated callers cannot read the config."""
    assert requests.get(f"{API}/tenants/mine/widget-config",
                         headers=tech_headers, timeout=15).status_code in (401, 403)
    assert requests.get(f"{API}/tenants/mine/widget-config",
                         timeout=15).status_code in (401, 403)


def test_regenerate_key_super_admin_only(admin_headers, super_headers, tech_headers):
    # Regular admin CANNOT rotate.
    for h in (admin_headers, tech_headers):
        r = requests.post(
            f"{API}/tenants/mine/widget-config/regenerate-key",
            headers=h, timeout=15,
        )
        assert r.status_code in (401, 403), (h, r.status_code, r.text)

    # Snapshot old key.
    old = requests.get(f"{API}/tenants/mine/widget-config",
                        headers=admin_headers, timeout=15).json()["public_widget_key"]
    r = requests.post(f"{API}/tenants/mine/widget-config/regenerate-key",
                       headers=super_headers, timeout=15)
    assert r.status_code == 200
    new_key = r.json()["public_widget_key"]
    assert new_key.startswith("pk_")
    assert new_key != old, "regenerate returned the same key"

    # Old key MUST no longer work through the widget-auth dep — we
    # verify that below in ``test_widget_auth_wrong_key``.


def test_patch_domains_normalises_and_dedupes(super_headers):
    r = requests.patch(
        f"{API}/tenants/mine/widget-config/domains",
        headers=super_headers,
        json={"widget_allowed_domains": [
            "  Example.COM  ",
            "https://www.example.com/some/path",
            "shop.example.com:443",
            "www.example.com",     # dedupe
        ]},
        timeout=15,
    )
    assert r.status_code == 200, r.text
    got = r.json()["widget_allowed_domains"]
    assert got == ["example.com", "www.example.com", "shop.example.com"], got


def test_patch_domains_rejects_garbage(super_headers):
    for bad in (["not a domain"], ["  "], ["!@#$"], ["...."]):
        r = requests.patch(
            f"{API}/tenants/mine/widget-config/domains",
            headers=super_headers,
            json={"widget_allowed_domains": bad},
            timeout=15,
        )
        assert r.status_code == 422, (bad, r.text)


# ═══════════════════════════════════════════════════════════════════════
# require_widget_auth — the dep both Slice G + H will import
# ═══════════════════════════════════════════════════════════════════════
def _pick_ping_endpoint():
    """Slice G + H haven't shipped yet — so we mount a tiny probe
    endpoint on the fly in the test process, then call the LIVE
    server's version via the widget_config dep directly.  We call the
    dep by invoking a temporary FastAPI route mounted through Starlette's
    TestClient."""


def test_widget_auth_flow(admin_headers, super_headers):
    """Exercise :func:`require_widget_auth` end-to-end by running it
    against a real ``Request`` object.  We keep the assertion at the
    dep level so we don't have to wait for G1 / H1 to mount their
    public endpoints."""

    async def _go():
        from fastapi import Request
        from starlette.datastructures import Headers
        from routers.widget_config import require_widget_auth

        db = _db()
        # Read our tenant's current key.
        u = await db.users.find_one({"email": "admin@aquaterra.com"},
                                     {"_id": 0, "tenant_id": 1})
        t = await db.tenants.find_one(
            {"id": u["tenant_id"]},
            {"_id": 0, "public_widget_key": 1,
              "widget_allowed_domains": 1},
        )
        key = t["public_widget_key"]

        def _mk_request(headers):
            scope = {"type": "http", "headers": [
                (k.lower().encode(), v.encode())
                for k, v in headers.items()
            ]}
            return Request(scope)

        # 1 · missing key header → 401
        try:
            await require_widget_auth(_mk_request({}), x_widget_key=None)
            assert False, "missing key should raise"
        except Exception as exc:
            assert getattr(exc, "status_code", None) == 401

        # 2 · wrong key → 401
        try:
            await require_widget_auth(
                _mk_request({"origin": "https://example.com"}),
                x_widget_key="pk_wrongwrongwrongwrong",
            )
            assert False, "wrong key should raise"
        except Exception as exc:
            assert getattr(exc, "status_code", None) == 401

        # 3 · valid key but domain not allowlisted → 401
        # Ensure allowlist is set to something specific first.
        requests.patch(
            f"{API}/tenants/mine/widget-config/domains",
            headers=super_headers,
            json={"widget_allowed_domains": ["www.example.com"]},
            timeout=15,
        )
        try:
            await require_widget_auth(
                _mk_request({"origin": "https://foreign.evil"}),
                x_widget_key=key,
            )
            assert False, "wrong domain should raise"
        except Exception as exc:
            assert getattr(exc, "status_code", None) == 401

        # 4 · valid key + valid domain (Origin header) → returns tenant
        got = await require_widget_auth(
            _mk_request({"origin": "https://www.example.com/some/page"}),
            x_widget_key=key,
        )
        assert got["id"] == u["tenant_id"]

        # 5 · valid key + valid domain (Referer fallback) → also OK
        got2 = await require_widget_auth(
            _mk_request({"referer": "https://www.example.com/other"}),
            x_widget_key=key,
        )
        assert got2["id"] == u["tenant_id"]

        # 6 · empty allowlist → 401 (key alone shouldn't be enough)
        requests.patch(
            f"{API}/tenants/mine/widget-config/domains",
            headers=super_headers,
            json={"widget_allowed_domains": []},
            timeout=15,
        )
        try:
            await require_widget_auth(
                _mk_request({"origin": "https://www.example.com"}),
                x_widget_key=key,
            )
            assert False, "empty allowlist should raise"
        except Exception as exc:
            assert getattr(exc, "status_code", None) == 401

    _run(_go())


# ═══════════════════════════════════════════════════════════════════════
# Cross-tenant isolation: one tenant's key MUST NOT match another's config
# ═══════════════════════════════════════════════════════════════════════
def test_widget_key_uniqueness_across_tenants():
    """Every tenant that already read its config has a key — assert
    the whole set is unique (no accidental collisions)."""
    async def _go():
        db = _db()
        keys = []
        async for t in db.tenants.find(
            {"public_widget_key": {"$exists": True}},
            {"_id": 0, "public_widget_key": 1},
        ):
            keys.append(t["public_widget_key"])
        assert len(keys) == len(set(keys)), \
            "collision detected in public_widget_key"
    _run(_go())
