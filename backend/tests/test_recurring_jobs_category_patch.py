"""Feb-2026 · Recurring Jobs · category PATCH happy path + validation.

Test-infra note (Feb 2026): Migrated OFF ``fastapi.testclient.
TestClient`` (shared Motor loop across tests → ``RuntimeError:
Event loop is closed``) ONTO the ``run_test(coro_factory)`` +
``httpx.ASGITransport`` pattern proven in
``tests/test_k4_schedule_recurring_appears_on_page.py``.  Each test
runs on its own fresh loop with Motor DB handles rebound.  No
product-code changes.
"""
from __future__ import annotations

import os
import uuid
from datetime import date

import httpx
import pytest
from pymongo import MongoClient

from tests._f7_loop_fixture import run_test


TENANT_ID = "test-tenant-rj-catpatch"


def _get_app():
    from server import app
    return app


def _sync_db():
    url = os.environ.get("MONGO_URL")
    name = os.environ.get("DB_NAME")
    if not (url and name):
        pytest.skip("MONGO_URL / DB_NAME not configured")
    return MongoClient(url)[name]


def _seed_state():
    """Reset the tenant + reseed the customer / category rows.
    Returns ``(inc_id, svc_id)``."""
    db = _sync_db()
    db.tenants.delete_many({"id": TENANT_ID})
    db.tenants.insert_one({"id": TENANT_ID, "name": "T"})
    db.recurring_job_templates.delete_many({"tenant_id": TENANT_ID})
    db.customers.delete_many({"tenant_id": TENANT_ID})
    db.customers.insert_one({
        "id": "c1", "tenant_id": TENANT_ID, "name": "A", "address": "1 St",
    })
    db.income_categories.delete_many({"tenant_id": TENANT_ID})
    db.service_categories.delete_many({"tenant_id": TENANT_ID})
    inc_id = str(uuid.uuid4())
    svc_id = str(uuid.uuid4())
    db.income_categories.insert_one({
        "id": inc_id, "tenant_id": TENANT_ID, "name": "Pool",
        "is_archived": False,
    })
    db.service_categories.insert_one({
        "id": svc_id, "tenant_id": TENANT_ID, "name": "Weekly Service",
        "is_archived": False,
    })
    return inc_id, svc_id


def _install_overrides():
    from utils import require_admin, require_admin_or_manager, get_current_user
    from routers.tenants import get_current_tenant

    app = _get_app()

    async def _fake_admin():
        return {"id": "u_admin", "role": "admin", "email": "a@x",
                "tenant_id": TENANT_ID}

    async def _fake_tenant():
        return {"id": TENANT_ID, "name": "T"}

    for dep in (require_admin, require_admin_or_manager, get_current_user):
        app.dependency_overrides[dep] = _fake_admin
    app.dependency_overrides[get_current_tenant] = _fake_tenant

    def _clear():
        for dep in (require_admin, require_admin_or_manager, get_current_user):
            app.dependency_overrides.pop(dep, None)
        app.dependency_overrides.pop(get_current_tenant, None)
    return _clear


async def _mk_template(ac):
    today = date.today()
    r = await ac.post("/api/recurring-jobs", json={
        "customer_id": "c1", "service_type": "Weekly", "frequency": "weekly",
        "day_of_week": today.weekday(), "start_date": today.isoformat(),
        "price_cents": 10000, "is_active": True, "active": True,
    })
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _run_with_http(coro):
    """Wrap ``coro(ac, db)`` so it gets a fresh ASGI async client +
    a loop-bound Motor db handle."""
    async def _go(db):
        transport = httpx.ASGITransport(app=_get_app())
        async with httpx.AsyncClient(transport=transport,
                                             base_url="http://test") as ac:
            await coro(ac, db)
    return run_test(_go)


# ═══════════════════════════════════════════════════════════════════

def test_patch_sets_service_category_and_income_category():
    inc_id, svc_id = _seed_state()
    clear = _install_overrides()
    try:
        async def _t(ac, db):
            tpl_id = await _mk_template(ac)
            r = await ac.patch(f"/api/recurring-jobs/{tpl_id}", json={
                "service_category_id": svc_id, "income_category_id": inc_id,
            })
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["service_category_id"] == svc_id
            assert body["income_category_id"] == inc_id
            assert body["service_category_name"] == "Weekly Service"
            assert body["income_category_name"] == "Pool"
        _run_with_http(_t)
    finally:
        clear()


def test_patch_unknown_category_id_404():
    _seed_state()
    clear = _install_overrides()
    try:
        async def _t(ac, db):
            tpl_id = await _mk_template(ac)
            r = await ac.patch(f"/api/recurring-jobs/{tpl_id}", json={
                "service_category_id": "does-not-exist",
            })
            assert r.status_code == 404, r.text
            assert "not_found" in r.json()["detail"]["error"]
        _run_with_http(_t)
    finally:
        clear()


def test_patch_archived_category_404():
    _, svc_id = _seed_state()
    _sync_db().service_categories.update_one(
        {"id": svc_id, "tenant_id": TENANT_ID},
        {"$set": {"is_archived": True}},
    )
    clear = _install_overrides()
    try:
        async def _t(ac, db):
            tpl_id = await _mk_template(ac)
            r = await ac.patch(f"/api/recurring-jobs/{tpl_id}", json={
                "service_category_id": svc_id,
            })
            assert r.status_code == 404
        _run_with_http(_t)
    finally:
        clear()


def test_patch_empty_string_clears_category():
    inc_id, _ = _seed_state()
    clear = _install_overrides()
    try:
        async def _t(ac, db):
            tpl_id = await _mk_template(ac)
            # Set the category first.
            r0 = await ac.patch(f"/api/recurring-jobs/{tpl_id}", json={
                "income_category_id": inc_id,
            })
            assert r0.status_code == 200, r0.text
            # Empty string clears.
            r = await ac.patch(f"/api/recurring-jobs/{tpl_id}", json={
                "income_category_id": "",
            })
            assert r.status_code == 200, r.text
            assert r.json()["income_category_id"] is None
            assert r.json()["income_category_name"] is None
        _run_with_http(_t)
    finally:
        clear()


def test_patch_over_80_chars_rejected():
    _seed_state()
    clear = _install_overrides()
    try:
        async def _t(ac, db):
            tpl_id = await _mk_template(ac)
            r = await ac.patch(f"/api/recurring-jobs/{tpl_id}", json={
                "service_category_id": "x" * 81,
            })
            assert r.status_code == 422
        _run_with_http(_t)
    finally:
        clear()


def test_patch_html_in_category_rejected():
    _seed_state()
    clear = _install_overrides()
    try:
        async def _t(ac, db):
            tpl_id = await _mk_template(ac)
            r = await ac.patch(f"/api/recurring-jobs/{tpl_id}", json={
                "service_category_id": "<script>alert(1)</script>",
            })
            assert r.status_code == 422
        _run_with_http(_t)
    finally:
        clear()
