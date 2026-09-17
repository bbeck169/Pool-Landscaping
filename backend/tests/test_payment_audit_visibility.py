"""Feb-2026 · Payment Processor ticket · audit endpoint isolation."""
from __future__ import annotations

import os
from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient

from server import app


TENANT_A = "test-tenant-audit-A"
TENANT_B = "test-tenant-audit-B"

_active_tenant: dict = {"id": TENANT_A}


def _sync_db():
    url = os.environ.get("MONGO_URL")
    name = os.environ.get("DB_NAME")
    if not (url and name):
        pytest.skip("MONGO_URL / DB_NAME not configured")
    return MongoClient(url)[name]


def _seed_state():
    db = _sync_db()
    now = datetime.now(timezone.utc).isoformat()
    for tid in (TENANT_A, TENANT_B):
        db["payment_failover_audit"].delete_many({"tenant_id": tid})
        db.tenants.delete_many({"id": tid})
        db.tenants.insert_one({"id": tid, "name": tid})
    rows_a = [{
        "id": f"aud_{TENANT_A}_{i}", "tenant_id": TENANT_A,
        "operation": "create_charge", "primary_provider": "stripe",
        "backup_provider": "lumino", "error_from_primary": "simulated",
        "resolution": "backup_used", "timestamp": now,
    } for i in range(3)]
    rows_b = [{
        "id": f"aud_{TENANT_B}_{i}", "tenant_id": TENANT_B,
        "operation": "create_charge", "primary_provider": "stripe",
        "backup_provider": "lumino", "error_from_primary": "simulated",
        "resolution": "backup_used", "timestamp": now,
    } for i in range(5)]
    db["payment_failover_audit"].insert_many(rows_a + rows_b)


@pytest.fixture(scope="module")
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(scope="module", autouse=True)
def _install_overrides():
    from utils import require_admin
    from routers.tenants import get_current_tenant

    async def _fake_admin():
        return {"id": "u_admin", "role": "admin", "email": "a@x",
                "tenant_id": _active_tenant["id"]}

    async def _fake_tenant():
        return {"id": _active_tenant["id"], "name": _active_tenant["id"]}

    app.dependency_overrides[require_admin] = _fake_admin
    app.dependency_overrides[get_current_tenant] = _fake_tenant
    yield
    app.dependency_overrides.pop(require_admin, None)
    app.dependency_overrides.pop(get_current_tenant, None)


@pytest.fixture
async def client(monkeypatch):
    """One fresh motor client per test so every anyio-spawned loop
    gets a Motor whose ``io_loop`` matches."""
    _seed_state()

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


def _as_tenant(tid):
    _active_tenant["id"] = tid


@pytest.mark.anyio
async def test_audit_returns_only_current_tenant_rows(client):
    _as_tenant(TENANT_A)
    r = await client.get("/api/tenants/mine/payment-audit")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 3
    for row in body["rows"]:
        assert row["tenant_id"] == TENANT_A

    _as_tenant(TENANT_B)
    r = await client.get("/api/tenants/mine/payment-audit")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 5
    for row in body["rows"]:
        assert row["tenant_id"] == TENANT_B


@pytest.mark.anyio
async def test_audit_respects_limit_and_skip(client):
    _as_tenant(TENANT_B)
    r = await client.get("/api/tenants/mine/payment-audit?limit=2&skip=1")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 5
    assert len(body["rows"]) == 2
    for row in body["rows"]:
        assert row["tenant_id"] == TENANT_B


@pytest.mark.anyio
async def test_audit_rows_never_leak_cross_tenant_after_empty(client):
    _sync_db()["payment_failover_audit"].delete_many({"tenant_id": TENANT_A})
    _as_tenant(TENANT_A)
    r = await client.get("/api/tenants/mine/payment-audit")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 0
    assert body["rows"] == []
