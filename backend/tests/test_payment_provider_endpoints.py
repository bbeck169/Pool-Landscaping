"""Feb-2026 · Payment Processor ticket · settings endpoints.

Uses ``httpx.AsyncClient`` + ``ASGITransport`` with a session-scoped
anyio loop so Motor's process-wide async client stays bound to the
same event loop across every test in this module. Avoids the
"Event loop is closed" flake pattern that TestClient hits when
BaseHTTPMiddleware is in the stack.
"""
from __future__ import annotations

import os

import pytest
from httpx import ASGITransport, AsyncClient
from pymongo import MongoClient

from server import app


TENANT_ID = "test-tenant-pp-endpoints"


def _sync_db():
    url = os.environ.get("MONGO_URL")
    name = os.environ.get("DB_NAME")
    if not (url and name):
        pytest.skip("MONGO_URL / DB_NAME not configured")
    return MongoClient(url)[name]


def _seed_state():
    db = _sync_db()
    db.tenants.delete_many({"id": TENANT_ID})
    db.tenants.insert_one({"id": TENANT_ID, "name": "Test Tenant"})
    db["payment_failover_audit"].delete_many({"tenant_id": TENANT_ID})
    db["payment_provider_test_calls"].delete_many({"tenant_id": TENANT_ID})


@pytest.fixture(scope="module")
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(scope="module", autouse=True)
def _install_overrides():
    from utils import require_admin
    from routers.tenants import get_current_tenant

    async def _fake_admin():
        return {"id": "u_admin", "role": "admin",
                "email": "admin@example.com", "tenant_id": TENANT_ID}

    async def _fake_tenant():
        return {"id": TENANT_ID, "name": "Test Tenant"}

    app.dependency_overrides[require_admin] = _fake_admin
    app.dependency_overrides[get_current_tenant] = _fake_tenant
    yield
    app.dependency_overrides.pop(require_admin, None)
    app.dependency_overrides.pop(get_current_tenant, None)


@pytest.fixture
def _seed():
    _seed_state()
    yield


@pytest.fixture
async def client(_seed, monkeypatch):
    """One fresh motor client per test so every anyio-spawned loop
    gets a Motor whose ``io_loop`` matches. Rebinds the module-level
    ``db`` references the payment-providers router + failover router
    already imported.
    """
    from motor.motor_asyncio import AsyncIOMotorClient
    import config
    import routers.payment_providers_settings as _pp

    fresh_client = AsyncIOMotorClient(
        os.environ["MONGO_URL"], maxPoolSize=50,
    )
    fresh_db = fresh_client[os.environ["DB_NAME"]]
    monkeypatch.setattr(config, "client", fresh_client, raising=False)
    monkeypatch.setattr(config, "db", fresh_db, raising=False)
    monkeypatch.setattr(_pp, "db", fresh_db, raising=False)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac
    fresh_client.close()


@pytest.mark.anyio
async def test_get_returns_defaults_and_available_list(client, monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY_TEST", "sk_test_x")
    r = await client.get("/api/tenants/mine/settings/payment-providers")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["primary_provider"] == "stripe"
    assert body["backup_provider"] is None
    short_names = [o["short_name"] for o in body["available"]]
    assert "stripe" in short_names
    assert "lumino" in short_names
    stripe_opt = next(o for o in body["available"] if o["short_name"] == "stripe")
    assert stripe_opt["is_configured"] is True


@pytest.mark.anyio
async def test_patch_updates_primary_and_backup(client):
    r = await client.patch(
        "/api/tenants/mine/settings/payment-providers",
        json={"primary_provider": "stripe", "backup_provider": "lumino"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["primary_provider"] == "stripe"
    assert r.json()["backup_provider"] == "lumino"


@pytest.mark.anyio
async def test_patch_same_provider_400(client):
    r = await client.patch(
        "/api/tenants/mine/settings/payment-providers",
        json={"primary_provider": "lumino", "backup_provider": "lumino"},
    )
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "same_provider_forbidden"


@pytest.mark.anyio
async def test_patch_unknown_provider_400(client):
    r = await client.patch(
        "/api/tenants/mine/settings/payment-providers",
        json={"primary_provider": "made_up"},
    )
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "unknown_provider"


@pytest.mark.anyio
async def test_patch_backup_none_clears_backup(client):
    await client.patch(
        "/api/tenants/mine/settings/payment-providers",
        json={"primary_provider": "stripe", "backup_provider": "lumino"},
    )
    r = await client.patch(
        "/api/tenants/mine/settings/payment-providers",
        json={"primary_provider": "stripe", "backup_provider": None},
    )
    assert r.status_code == 200
    assert r.json()["backup_provider"] is None


@pytest.mark.anyio
async def test_test_endpoint_returns_ok_for_configured(client, monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY_TEST", "sk_test_x")
    monkeypatch.setenv("PAYMENTS_TESTMODE_MOCK", "1")
    r = await client.post(
        "/api/tenants/mine/payment-providers/test",
        json={"provider": "stripe"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["provider"] == "stripe"
    assert isinstance(body["latency_ms"], int)


@pytest.mark.anyio
async def test_test_endpoint_returns_ok_false_when_unconfigured(client, monkeypatch):
    monkeypatch.delenv("STRIPE_SECRET_KEY_LIVE", raising=False)
    monkeypatch.delenv("STRIPE_SECRET_KEY_TEST", raising=False)
    monkeypatch.delenv("STRIPE_API_KEY", raising=False)
    monkeypatch.delenv("PAYMENTS_TESTMODE_MOCK", raising=False)
    r = await client.post(
        "/api/tenants/mine/payment-providers/test",
        json={"provider": "stripe"},
    )
    assert r.status_code == 200
    assert r.json()["ok"] is False


@pytest.mark.anyio
async def test_test_endpoint_unknown_provider_400(client):
    r = await client.post(
        "/api/tenants/mine/payment-providers/test",
        json={"provider": "nope"},
    )
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "unknown_provider"


@pytest.mark.anyio
async def test_test_endpoint_rate_limit_fires_on_sixth_call(client, monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY_TEST", "sk_test_x")
    monkeypatch.setenv("PAYMENTS_TESTMODE_MOCK", "1")
    for _ in range(5):
        r = await client.post(
            "/api/tenants/mine/payment-providers/test",
            json={"provider": "stripe"},
        )
        assert r.status_code == 200, r.text
    r = await client.post(
        "/api/tenants/mine/payment-providers/test",
        json={"provider": "stripe"},
    )
    assert r.status_code == 429
    assert r.json()["detail"]["code"] == "RATE_LIMITED"
