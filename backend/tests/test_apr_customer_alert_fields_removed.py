"""APR-II · Feb-2026 — regression lock on the removal of
``CustomerIn.alert_phone`` + ``CustomerIn.alert_email`` and the
collapse of the recap-SMS routing to primary ``phone`` only.
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any, Dict

import httpx
import pytest
from dotenv import dotenv_values
from pymongo import MongoClient

from tests._f7_loop_fixture import run_test


_BE = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
MONGO_URL = _BE.get("MONGO_URL") or os.environ.get("MONGO_URL")
DB_NAME = _BE.get("DB_NAME") or os.environ.get("DB_NAME")


def _get_app():
    from server import app
    return app


@pytest.fixture(scope="module")
def dbc():
    return MongoClient(MONGO_URL)[DB_NAME]


@pytest.fixture(scope="module")
def seeded(dbc):
    tenant_id = f"t_apr2_{uuid.uuid4().hex[:8]}"
    admin = {
        "id": f"u_admin_{uuid.uuid4().hex[:8]}",
        "tenant_id": tenant_id,
        "role": "admin",
        "email": f"admin.{tenant_id[:6]}@test.local",
    }
    dbc.tenants.insert_one({
        "id": tenant_id,
        "slug": f"apr2-{tenant_id[:6]}",
        "name": "APR-II Test Tenant",
    })
    dbc.users.insert_one(admin)
    yield {"tenant_id": tenant_id, "admin": admin}

    dbc.tenants.delete_one({"id": tenant_id})
    dbc.users.delete_many({"tenant_id": tenant_id})
    dbc.customers.delete_many({"tenant_id": tenant_id})


def _install_overrides(user: Dict[str, Any]):
    from utils import get_current_user, require_admin
    from routers.tenants import get_current_tenant
    app = _get_app()

    async def _fake_user():
        return dict(user)

    async def _fake_tenant():
        return {"id": user["tenant_id"], "name": "APR-II"}

    app.dependency_overrides[get_current_user] = _fake_user
    app.dependency_overrides[require_admin] = _fake_user
    app.dependency_overrides[get_current_tenant] = _fake_tenant

    def _clear():
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(require_admin, None)
        app.dependency_overrides.pop(get_current_tenant, None)
    return _clear


# (a) POST /api/customers with legacy keys → silently dropped.
def test_a_post_customers_drops_removed_alert_keys(seeded, dbc):
    clear = _install_overrides(seeded["admin"])
    try:
        holder: Dict[str, Any] = {}

        async def _go(_db):
            transport = httpx.ASGITransport(app=_get_app())
            async with httpx.AsyncClient(transport=transport,
                                          base_url="http://test") as ac:
                body = {
                    "name": "TEST_APR Alice",
                    "email": "alice@example.com",
                    "phone": "+16025550101",
                    "alert_phone": "+16025559999",
                    "alert_email": "alerts@example.com",
                }
                holder["r"] = await ac.post("/api/customers", json=body)

        run_test(_go)
        r = holder["r"]
        assert r.status_code == 200, (
            f"POST /api/customers status={r.status_code}: {r.text[:400]}"
        )
        doc = r.json()
        assert "alert_phone" not in doc, f"alert_phone leaked: {doc}"
        assert "alert_email" not in doc, f"alert_email leaked: {doc}"
        assert doc["phone"] == "+16025550101"
        assert doc["email"] == "alice@example.com"

        stored = dbc.customers.find_one({"id": doc["id"]}, {"_id": 0})
        assert stored is not None, "customer not persisted"
        assert "alert_phone" not in stored
        assert "alert_email" not in stored
    finally:
        clear()


# (b) GET /api/customers/{id} → response has no alert keys.
def test_b_get_customer_response_has_no_alert_keys(seeded, dbc):
    clear = _install_overrides(seeded["admin"])
    try:
        cid = f"c_apr2_{uuid.uuid4().hex[:8]}"
        dbc.customers.insert_one({
            "id": cid,
            "tenant_id": seeded["tenant_id"],
            "name": "TEST_APR Bob",
            "email": "bob@example.com",
            "phone": "+16025550102",
            "deleted_at": None,
        })

        holder: Dict[str, Any] = {}

        async def _go(_db):
            transport = httpx.ASGITransport(app=_get_app())
            async with httpx.AsyncClient(transport=transport,
                                          base_url="http://test") as ac:
                holder["r"] = await ac.get(f"/api/customers/{cid}")

        run_test(_go)
        r = holder["r"]
        assert r.status_code == 200, r.text[:400]
        doc = r.json()
        assert "alert_phone" not in doc
        assert "alert_email" not in doc
    finally:
        clear()


# (c) _send_recap_sms with phone="" and legacy alert_phone populated
# → returns the no-phone branch (dead fallback).
def test_c_send_recap_sms_no_fallback_to_legacy_alert_phone():
    from routers.service_reports import _send_recap_sms

    customer_no_primary = {
        "id": "c-legacy-alert",
        "phone": "",
        "alert_phone": "+16025559999",
    }

    holder: Dict[str, Any] = {}

    async def _go(_db):
        holder["res"] = await _send_recap_sms(
            customer_no_primary, "TEST_APR plain body",
        )

    run_test(_go)
    res = holder["res"]
    assert res["sent"] is False
    assert res["mocked"] is True
    assert "no phone on file" in (res.get("reason") or "").lower(), res


# (d) _send_recap_sms with phone populated → routes to phone.
def test_d_send_recap_sms_routes_to_primary_phone(monkeypatch):
    from routers.service_reports import _send_recap_sms

    captured: Dict[str, Any] = {}

    async def _fake_sms_send(**kwargs):
        captured.update(kwargs)
        return {
            "provider": "ringcentral",
            "provider_status": "queued",
            "provider_response_id": "msg_apr2_test",
        }

    import services.sms.rc_adapter as _rc
    monkeypatch.setattr(_rc, "send", _fake_sms_send)

    customer_primary = {
        "id": "c-primary",
        "phone": "+16025550102",
    }

    holder: Dict[str, Any] = {}

    async def _go(_db):
        holder["res"] = await _send_recap_sms(
            customer_primary, "TEST_APR plain body",
        )

    run_test(_go)
    res = holder["res"]
    assert res["sent"] is True
    assert res["mocked"] is False
    assert captured.get("to") == "+16025550102"
    assert captured.get("customer_id") == "c-primary"
