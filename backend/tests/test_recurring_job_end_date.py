"""Feb-2026 · Recurring Jobs · end_date validation + auto-stop.

Test-infra note (Feb 2026): This module was migrated OFF the
``fastapi.testclient.TestClient`` pattern (which shared the app's
default Motor loop across tests → ``RuntimeError: Event loop is
closed`` after the first test tore its client down) and ONTO the
``run_test(coro_factory)`` + ``httpx.ASGITransport`` pattern already
proven in ``tests/test_k4_schedule_recurring_appears_on_page.py``.
Each test now runs on its own fresh event loop with Motor DB
handles rebound to that loop, then restored.  No product-code
changes; behaviour identical.
"""
from __future__ import annotations

import os
from datetime import date, timedelta

import httpx
import pytest
from pymongo import MongoClient

from tests._f7_loop_fixture import run_test


TENANT_ID = "test-tenant-rj-enddate"


def _get_app():
    from server import app
    return app


def _sync_db():
    url = os.environ.get("MONGO_URL")
    name = os.environ.get("DB_NAME")
    if not (url and name):
        pytest.skip("MONGO_URL / DB_NAME not configured")
    return MongoClient(url)[name]


def _seed():
    db = _sync_db()
    db.tenants.delete_many({"id": TENANT_ID})
    db.tenants.insert_one({"id": TENANT_ID, "name": "T"})
    db.recurring_job_templates.delete_many({"tenant_id": TENANT_ID})
    db.jobs.delete_many({"tenant_id": TENANT_ID})
    db.customers.delete_many({"tenant_id": TENANT_ID})
    db.customers.insert_one({
        "id": "cust-1", "tenant_id": TENANT_ID,
        "name": "Alice", "address": "1 St",
    })


def _install_overrides():
    """Install fake-admin / fake-tenant dependency overrides + return a
    cleanup callable. Kept sync because ``app.dependency_overrides`` is
    a plain dict; the async coroutine inside ``run_test`` doesn't need
    to touch it."""
    from utils import require_admin, require_admin_or_manager, get_current_user
    from routers.tenants import get_current_tenant

    app = _get_app()

    async def _fake_admin():
        return {"id": "u_admin", "role": "admin",
                "email": "a@x", "tenant_id": TENANT_ID}

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


def _create_body(**over):
    today = date.today()
    base = {
        "customer_id": "cust-1", "service_type": "Weekly Pool",
        "frequency": "weekly", "day_of_week": today.weekday(),
        "start_date": today.isoformat(),
        "price_cents": 10000,
        "is_active": True, "active": True,
    }
    base.update(over)
    return base


def _run_with_http(coro):
    """Wrap ``coro(ac, db)`` so it gets a fresh ASGI async client +
    a loop-bound Motor db handle. ``run_test`` handles the loop
    rebinding; we spin the ``httpx.AsyncClient`` inside so each test
    gets a fresh HTTP session too."""
    async def _go(db):
        transport = httpx.ASGITransport(app=_get_app())
        async with httpx.AsyncClient(transport=transport,
                                             base_url="http://test") as ac:
            await coro(ac, db)
    return run_test(_go)


# ═══════════════════════════════════════════════════════════════════

def test_post_with_end_date_creates_template():
    _seed()
    clear = _install_overrides()
    try:
        async def _t(ac, db):
            today = date.today()
            end = today + timedelta(days=30)
            r = await ac.post("/api/recurring-jobs",
                                json=_create_body(end_date=end.isoformat()))
            assert r.status_code == 200, r.text
            assert r.json()["end_date"] == end.isoformat()
        _run_with_http(_t)
    finally:
        clear()


def test_post_end_date_before_start_date_rejected():
    _seed()
    clear = _install_overrides()
    try:
        async def _t(ac, db):
            today = date.today()
            end = today - timedelta(days=5)
            r = await ac.post("/api/recurring-jobs",
                                json=_create_body(end_date=end.isoformat()))
            assert r.status_code == 400, r.text
            assert r.json()["detail"]["error"] == "end_date_before_start_date"
        _run_with_http(_t)
    finally:
        clear()


def test_post_end_date_equals_start_date_ok():
    _seed()
    clear = _install_overrides()
    try:
        async def _t(ac, db):
            today = date.today()
            r = await ac.post("/api/recurring-jobs",
                                json=_create_body(end_date=today.isoformat()))
            assert r.status_code == 200, r.text
            assert r.json()["end_date"] == today.isoformat()
        _run_with_http(_t)
    finally:
        clear()


def test_patch_updates_end_date():
    _seed()
    clear = _install_overrides()
    try:
        async def _t(ac, db):
            r = await ac.post("/api/recurring-jobs", json=_create_body())
            tpl_id = r.json()["id"]
            new_end = (date.today() + timedelta(days=45)).isoformat()
            r2 = await ac.patch(f"/api/recurring-jobs/{tpl_id}",
                                    json={"end_date": new_end})
            assert r2.status_code == 200, r2.text
            assert r2.json()["end_date"] == new_end
        _run_with_http(_t)
    finally:
        clear()


def test_no_end_date_means_infinity_no_stop():
    """POST without end_date + call the cron helper — template
    remains active. Auto-stop should NOT fire because end_date is
    ``None``."""
    _seed()
    clear = _install_overrides()
    try:
        async def _t(ac, db):
            body = _create_body()
            body.pop("end_date", None)
            r = await ac.post("/api/recurring-jobs", json=body)
            tpl_id = r.json()["id"]
            # Run generator through a horizon 30 days out.
            through = (date.today() + timedelta(days=30)).isoformat()
            r2 = await ac.post(
                f"/api/recurring-jobs/{tpl_id}/generate?through={through}")
            assert r2.status_code == 200, r2.text
            tpl_after = await db.recurring_job_templates.find_one(
                {"id": tpl_id, "tenant_id": TENANT_ID}, {"_id": 0},
            )
            assert tpl_after["active"] is True
        _run_with_http(_t)
    finally:
        clear()


def test_materialization_stops_past_end_date_and_transitions():
    """Template with end_date 2 days ago + last_generated_through
    already past end_date → next generate call must transition the
    template to inactive (auto-stop)."""
    _seed()
    clear = _install_overrides()
    try:
        async def _t(ac, db):
            today = date.today()
            end = today - timedelta(days=2)
            start = today - timedelta(days=30)
            body = _create_body(
                start_date=start.isoformat(),
                end_date=end.isoformat(),
                day_of_week=start.weekday(),
            )
            r = await ac.post("/api/recurring-jobs", json=body)
            tpl_id = r.json()["id"]
            # Fast-forward the cursor past the end date so
            # ``_next_occurrences`` returns [] and the auto-stop
            # branch fires.
            await db.recurring_job_templates.update_one(
                {"id": tpl_id, "tenant_id": TENANT_ID},
                {"$set": {"last_generated_through": end.isoformat()}},
            )
            through = (today + timedelta(days=14)).isoformat()
            r2 = await ac.post(
                f"/api/recurring-jobs/{tpl_id}/generate?through={through}")
            assert r2.status_code == 200, r2.text
            assert r2.json()["inserted"] == 0
            tpl_after = await db.recurring_job_templates.find_one(
                {"id": tpl_id, "tenant_id": TENANT_ID}, {"_id": 0},
            )
            assert tpl_after["active"] is False
            assert tpl_after["is_active"] is False
            assert tpl_after.get("stopped_at")
        _run_with_http(_t)
    finally:
        clear()


def test_materialization_inclusive_end_date():
    """A recurrence whose scheduled_date lands ON the end_date
    should still generate — inclusive semantics.

    Feb-2026 · P1 Auto-Activate note — the today occurrence is now
    materialized inline by the ``POST /recurring-jobs`` handler
    (14-day instant generator). Assert the outcome (a job exists
    for today) rather than the ``/generate`` return payload so the
    test stays honest to the shipping product behavior.
    """
    _seed()
    clear = _install_overrides()
    try:
        async def _t(ac, db):
            today = date.today()
            # weekly recurrence starting today, ending today → single-shot.
            body = _create_body(end_date=today.isoformat())
            r = await ac.post("/api/recurring-jobs", json=body)
            assert r.status_code == 200, r.text
            tpl_id = r.json()["id"]
            # Inline generation on create honours the inclusive
            # end_date — a job for today should already exist.
            jobs = await db.jobs.find(
                {"recurring_template_id": tpl_id,
                  "tenant_id": TENANT_ID},
                {"_id": 0, "scheduled_date": 1},
            ).to_list(10)
            assert len(jobs) == 1, f"expected 1 job for today, got {jobs!r}"
            assert jobs[0]["scheduled_date"] == today.isoformat()
        _run_with_http(_t)
    finally:
        clear()
