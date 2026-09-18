"""Feb-2026 · Never-end recurrence + partial-index fix.

Sprint 3a · Feb 2026 test-infra migration — this suite was previously
driven by ``requests.post`` against the preview URL with hardcoded
aquaterra tenant + Terry customer ids. Those ids drifted out from
under the tests when the seed data was refreshed, and the sync-HTTP
pattern also collided with the Motor event-loop rebinds on batch
runs. Migrated ONTO the proven ``run_test(coro_factory)`` +
``httpx.ASGITransport`` pattern used by
``tests/test_recurring_job_end_date.py`` +
``tests/test_recurring_jobs_category_patch.py``. Each HTTP test now:

  * seeds a fresh isolated ``test-tenant-recurrence-ne-pi`` tenant +
    customer via sync pymongo,
  * installs dependency overrides so the FastAPI auth chain sees a
    fake super_admin scoped to the test tenant,
  * drives the app in-process via ``httpx.AsyncClient(transport=
    ASGITransport(app=server.app))`` on a fresh event loop with
    Motor rebound to that loop,
  * cleans up on teardown.

The three tests that DON'T hit HTTP (``test_partial_index_exists``,
``test_partial_index_still_dedups_recurring_occurrences``, and
``test_nth_weekday_computation_edge_cases``) stay on sync pymongo /
pure-Python paths — they don't need the ASGI transport and running
them on the batch loop keeps them tidy.
"""
from __future__ import annotations

import os
from datetime import date

import httpx
import pytest
from pymongo import MongoClient

from tests._f7_loop_fixture import run_test


TENANT_ID = "test-tenant-recurrence-ne-pi"
CUSTOMER_ID = "cust-recurrence-ne-pi"
ADMIN_UID = "u-recurrence-ne-pi-admin"


# ── Lazy imports so the file can be collected before FastAPI boots. ──
def _get_app():
    from server import app
    return app


def _sync_db():
    url = os.environ.get("MONGO_URL")
    name = os.environ.get("DB_NAME")
    if not (url and name):
        pytest.skip("MONGO_URL / DB_NAME not configured")
    return MongoClient(url)[name]


# ── Seed + teardown ─────────────────────────────────────────────────
def _seed():
    """Create an isolated test tenant + customer. Idempotent."""
    db = _sync_db()
    db.tenants.delete_many({"id": TENANT_ID})
    db.tenants.insert_one({"id": TENANT_ID, "name": "T-Recurrence-NE-PI"})
    db.recurring_job_templates.delete_many({"tenant_id": TENANT_ID})
    db.jobs.delete_many({"tenant_id": TENANT_ID})
    db.customers.delete_many({"tenant_id": TENANT_ID})
    db.customers.insert_one({
        "id": CUSTOMER_ID, "tenant_id": TENANT_ID,
        "name": "Terry Test", "address": "1 Test Ln",
    })


def _cleanup_between_tests():
    """Wipe recurring templates + jobs between HTTP tests so each
    test starts clean (avoids the K7 partial-unique index colliding
    on stale ``recurring_template_id + scheduled_date`` pairs left
    from earlier tests in the same session)."""
    db = _sync_db()
    db.recurring_job_templates.delete_many({"tenant_id": TENANT_ID})
    db.jobs.delete_many({"tenant_id": TENANT_ID})


def _install_overrides():
    """Install fake-super_admin dependency overrides + return a
    cleanup callable. Super-admin role passes both ``require_admin``
    and ``require_admin_or_manager`` gates so we cover every
    recurring-jobs endpoint uniformly."""
    from utils import (
        require_admin, require_admin_or_manager, get_current_user,
    )
    from routers.tenants import get_current_tenant

    app = _get_app()

    async def _fake_super_admin():
        return {"id": ADMIN_UID, "role": "super_admin",
                "email": "recurrence-admin@test.local",
                "tenant_id": TENANT_ID}

    async def _fake_tenant():
        return {"id": TENANT_ID, "name": "T-Recurrence-NE-PI"}

    for dep in (require_admin, require_admin_or_manager, get_current_user):
        app.dependency_overrides[dep] = _fake_super_admin
    app.dependency_overrides[get_current_tenant] = _fake_tenant

    def _clear():
        for dep in (require_admin, require_admin_or_manager, get_current_user):
            app.dependency_overrides.pop(dep, None)
        app.dependency_overrides.pop(get_current_tenant, None)
    return _clear


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


# ═══ Never-end flag on create ═══════════════════════════════════════
def test_create_never_ends_forces_null_end_date():
    _seed()
    _cleanup_between_tests()
    clear = _install_overrides()
    try:
        async def _t(ac, db):
            r = await ac.post(
                "/api/recurring-jobs",
                json={
                    "customer_id": CUSTOMER_ID,
                    "service_type": "test_never_ends_svc",
                    "frequency": "weekly",
                    "day_of_week": 2,
                    "start_date": "2026-08-18",
                    "end_date": "2026-12-31",
                    "recurrence_never_ends": True,
                    "price_cents": 12000,
                },
            )
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["recurrence_never_ends"] is True
            assert body["end_date"] is None
        _run_with_http(_t)
    finally:
        clear()
        _cleanup_between_tests()


def test_backward_compat_flag_absent():
    _seed()
    _cleanup_between_tests()
    clear = _install_overrides()
    try:
        async def _t(ac, db):
            r = await ac.post(
                "/api/recurring-jobs",
                json={
                    "customer_id": CUSTOMER_ID,
                    "service_type": "test_backcompat_svc",
                    "frequency": "weekly",
                    "day_of_week": 3,
                    "start_date": "2026-08-18",
                    "end_date": "2026-12-31",
                    "price_cents": 12000,
                },
            )
            assert r.status_code == 200, r.text
            body = r.json()
            assert body.get("recurrence_never_ends") in (False, None)
            assert body["end_date"] == "2026-12-31"
        _run_with_http(_t)
    finally:
        clear()
        _cleanup_between_tests()


def test_patch_never_ends_clears_end_date():
    _seed()
    _cleanup_between_tests()
    clear = _install_overrides()
    try:
        async def _t(ac, db):
            r = await ac.post(
                "/api/recurring-jobs",
                json={
                    "customer_id": CUSTOMER_ID,
                    "service_type": "test_patch_svc",
                    "frequency": "weekly",
                    "day_of_week": 4,
                    "start_date": "2026-08-18",
                    "end_date": "2026-12-31",
                    "price_cents": 12000,
                },
            )
            tpl_id = r.json()["id"]
            r = await ac.patch(
                f"/api/recurring-jobs/{tpl_id}",
                json={"recurrence_never_ends": True},
            )
            assert r.status_code == 200, r.text
            assert r.json()["end_date"] is None
            assert r.json()["recurrence_never_ends"] is True
        _run_with_http(_t)
    finally:
        clear()
        _cleanup_between_tests()


# ═══ Stop endpoint ══════════════════════════════════════════════════
def test_stop_endpoint_prunes_future_scheduled_only():
    _seed()
    _cleanup_between_tests()
    clear = _install_overrides()
    started_id = "test-stop-started-recurrence-ne"
    try:
        async def _t(ac, db):
            r = await ac.post(
                "/api/recurring-jobs",
                json={
                    "customer_id": CUSTOMER_ID,
                    "service_type": "test_stop_svc",
                    "frequency": "weekly",
                    "day_of_week": 5,
                    "start_date": "2026-08-18",
                    "recurrence_never_ends": True,
                    "price_cents": 12000,
                },
            )
            tpl_id = r.json()["id"]

            r = await ac.post(
                f"/api/recurring-jobs/{tpl_id}/generate"
                f"?through=2026-11-30",
            )
            assert r.status_code == 200, r.text
            inserted = r.json()["inserted"]
            # ``inserted`` may be zero here when the 14-day inline
            # generator already covered every occurrence up to
            # ``through`` — we assert on the total pool of
            # generated jobs below rather than the per-call return.
            _ = inserted

            # Seed a started future job that MUST survive the stop.
            await db.jobs.insert_one({
                "id": started_id,
                "tenant_id": TENANT_ID,
                "recurring_template_id": tpl_id,
                "scheduled_date": "2050-01-01",
                "status": "in_progress",
                "title": "test-stop-started",
            })

            # Count STRICTLY-future scheduled occurrences — mirrors
            # the endpoint's prune predicate exactly:
            #   status == "scheduled" AND scheduled_date > today
            today_iso = date.today().isoformat()
            total_future_scheduled = await db.jobs.count_documents({
                "recurring_template_id": tpl_id,
                "tenant_id": TENANT_ID,
                "status": "scheduled",
                "scheduled_date": {"$gt": today_iso},
            })
            assert total_future_scheduled >= 1, (
                "generate call left no future scheduled occurrences to prune"
            )

            r = await ac.post(f"/api/recurring-jobs/{tpl_id}/stop")
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["template_id"] == tpl_id
            assert body["stopped_at"] == date.today().isoformat()
            assert body["removed_future_jobs"] == total_future_scheduled

            r = await ac.get(f"/api/recurring-jobs/{tpl_id}")
            tpl = r.json()
            assert tpl["active"] is False
            assert tpl["recurrence_never_ends"] is False
            assert tpl["end_date"] == date.today().isoformat()

            survivor = await db.jobs.find_one({"id": started_id})
            assert survivor is not None, (
                "started future job was incorrectly pruned"
            )
        _run_with_http(_t)
    finally:
        _sync_db().jobs.delete_one({"id": started_id})
        clear()
        _cleanup_between_tests()


def test_stop_by_job_id_shim():
    _seed()
    _cleanup_between_tests()
    clear = _install_overrides()
    try:
        async def _t(ac, db):
            r = await ac.post(
                "/api/recurring-jobs",
                json={
                    "customer_id": CUSTOMER_ID,
                    "service_type": "test_stop_shim_svc",
                    "frequency": "weekly",
                    "day_of_week": 1,
                    "start_date": "2026-08-18",
                    "recurrence_never_ends": True,
                    "price_cents": 12000,
                },
            )
            tpl_id = r.json()["id"]
            await ac.post(
                f"/api/recurring-jobs/{tpl_id}/generate"
                f"?through=2026-10-31",
            )
            job = await db.jobs.find_one(
                {"recurring_template_id": tpl_id, "tenant_id": TENANT_ID},
            )
            assert job is not None
            r = await ac.post(f"/api/jobs/{job['id']}/recurrence/stop")
            assert r.status_code == 200, r.text
            assert r.json()["template_id"] == tpl_id
        _run_with_http(_t)
    finally:
        clear()
        _cleanup_between_tests()


def test_stop_by_job_id_shim_rejects_non_recurring():
    """Non-recurring jobs → 400 (they have no recurring_template_id).

    Seed the job directly so the tenant scoping is deterministic — the
    stop-shim endpoint scopes ``db.jobs.find_one`` to the caller's
    tenant.
    """
    _seed()
    _cleanup_between_tests()
    clear = _install_overrides()
    from uuid import uuid4
    jid = f"test-non-recur-{uuid4().hex[:8]}"
    try:
        async def _t(ac, db):
            await db.jobs.insert_one({
                "id": jid,
                "tenant_id": TENANT_ID,
                "customer_id": CUSTOMER_ID,
                "title": "test-not-recurring",
                "service_type": "Pool Cleaning",
                "scheduled_date": "2028-08-25",
                "status": "scheduled",
                # explicitly no recurring_template_id
            })
            r = await ac.post(f"/api/jobs/{jid}/recurrence/stop")
            assert r.status_code == 400, r.text
            assert "recurring" in r.text.lower()
        _run_with_http(_t)
    finally:
        _sync_db().jobs.delete_one({"id": jid})
        clear()
        _cleanup_between_tests()


# ═══ Partial-index migration ═══════════════════════════════════════
def test_partial_index_exists():
    """The migration must have installed the partial-unique index.

    Pure sync — reads ``jobs.index_information`` at the collection
    level; no tenant scoping, no HTTP.
    """
    db = _sync_db()
    info = db.jobs.index_information()
    spec = info.get("recurring_template_id_1_scheduled_date_1")
    assert spec is not None, "partial-unique index missing"
    # ``partialFilterExpression`` presence is the discriminator vs.
    # legacy ``sparse: True`` variant.
    assert spec.get("partialFilterExpression"), (
        f"index not partial: {spec}"
    )


def test_partial_index_allows_multiple_non_recurring_same_date():
    """The Terry-Hernandez repro: multiple non-recurring jobs for the
    same customer on the same date must all succeed. Pre-fix, the
    2nd collided on the sparse-unique index with E11000.
    """
    _seed()
    _cleanup_between_tests()
    clear = _install_overrides()
    ids: list[str] = []
    try:
        async def _t(ac, db):
            for i in range(3):
                r = await ac.post(
                    "/api/jobs",
                    json={
                        "title": f"idx_verify_{i}",
                        "customer_id": CUSTOMER_ID,
                        "service_type": "Pool Cleaning",
                        "scheduled_date": "2028-01-15",
                        "price": 0,
                        "status": "scheduled",
                    },
                )
                assert r.status_code == 200, f"insert {i}: {r.text}"
                ids.append(r.json()["id"])
        _run_with_http(_t)
    finally:
        if ids:
            _sync_db().jobs.delete_many({"id": {"$in": ids}})
        clear()
        _cleanup_between_tests()


def test_partial_index_still_dedups_recurring_occurrences():
    """Two rows with the same (recurring_template_id, scheduled_date)
    must still collide on the partial-unique index.

    Pure sync mongo — the assertion is about the DB index behaviour,
    not the HTTP surface.
    """
    db = _sync_db()
    rtid = "test-partial-idx-tpl-recurrence-ne"
    r1_id = "test-partial-idx-r1-recurrence-ne"
    r2_id = "test-partial-idx-r2-recurrence-ne"
    try:
        db.jobs.insert_one({
            "id": r1_id, "tenant_id": TENANT_ID,
            "recurring_template_id": rtid, "scheduled_date": "2028-02-01",
            "status": "scheduled",
        })
        collided = False
        try:
            db.jobs.insert_one({
                "id": r2_id, "tenant_id": TENANT_ID,
                "recurring_template_id": rtid,
                "scheduled_date": "2028-02-01",
                "status": "scheduled",
            })
        except Exception as e:
            collided = (
                ("E11000" in str(e)) or ("duplicate" in str(e).lower())
            )
        assert collided, (
            "partial-unique index failed to dedup recurring occurrences"
        )
    finally:
        db.jobs.delete_many({"id": {"$in": [r1_id, r2_id]}})


# ═══ Monthly nth-weekday pattern ════════════════════════════════════
def test_nth_weekday_computation_edge_cases():
    """Directly exercise the ``_nth_weekday_of_month`` helper on known
    edge cases so we lock the arithmetic even if the API is
    unreachable.

    Pure Python — no DB, no HTTP.
    """
    from routers.recurring_jobs import _nth_weekday_of_month
    # Friday = weekday 4
    assert _nth_weekday_of_month(2026, 1, "third", 4).isoformat() == "2026-01-16"
    # Wednesday = weekday 2
    assert _nth_weekday_of_month(2028, 2, "last", 2).isoformat() == "2028-02-23"
    # Friday = weekday 4
    assert _nth_weekday_of_month(2026, 2, "last", 4).isoformat() == "2026-02-27"
    # Monday = weekday 0 — only 4 exist in Feb 2026 (2, 9, 16, 23).
    assert _nth_weekday_of_month(2026, 2, "first", 0).isoformat() == "2026-02-02"
    # Sanity: "last" ≠ "fourth" when 5 exist. Fridays in Jan 2026:
    # 2, 9, 16, 23, 30.
    assert _nth_weekday_of_month(2026, 1, "fourth", 4).isoformat() == "2026-01-23"
    assert _nth_weekday_of_month(2026, 1, "last", 4).isoformat() == "2026-01-30"


def test_nth_weekday_create_and_upcoming():
    """3rd Friday recurring template — upcoming[] should be 3rd
    Friday of the next 3 months."""
    _seed()
    _cleanup_between_tests()
    clear = _install_overrides()
    try:
        async def _t(ac, db):
            r = await ac.post(
                "/api/recurring-jobs",
                json={
                    "customer_id": CUSTOMER_ID,
                    "service_type": "test_nth_third_fri",
                    "frequency": "monthly",
                    "monthly_pattern": "nth_weekday",
                    "monthly_nth_week": "third",
                    "monthly_weekday": 4,  # Friday
                    "start_date": "2026-01-01",
                    "recurrence_never_ends": True,
                    "price_cents": 12000,
                },
            )
            assert r.status_code == 200, r.text
            tpl_id = r.json()["id"]
            r = await ac.get(f"/api/recurring-jobs/{tpl_id}")
            tpl = r.json()
            assert tpl["monthly_pattern"] == "nth_weekday"
            assert tpl["monthly_nth_week"] == "third"
            assert tpl["monthly_weekday"] == 4
            # ``upcoming[]`` is the next 6 3rd-Fridays from today; every
            # entry must be a Friday and its day-of-month must land
            # within the 15-21 window (3rd Friday range).
            assert len(tpl["upcoming"]) > 0
            for iso in tpl["upcoming"]:
                d = date.fromisoformat(iso)
                assert d.weekday() == 4, f"{iso} is not a Friday"
                assert 15 <= d.day <= 21, (
                    f"{iso} not in 3rd-Friday window"
                )
        _run_with_http(_t)
    finally:
        clear()
        _cleanup_between_tests()


def test_nth_weekday_validation_requires_companion_fields():
    """monthly_pattern=nth_weekday without monthly_nth_week → 422."""
    _seed()
    _cleanup_between_tests()
    clear = _install_overrides()
    try:
        async def _t(ac, db):
            r = await ac.post(
                "/api/recurring-jobs",
                json={
                    "customer_id": CUSTOMER_ID,
                    "service_type": "test_nth_invalid",
                    "frequency": "monthly",
                    "monthly_pattern": "nth_weekday",
                    "start_date": "2026-01-01",
                    "price_cents": 100,
                },
            )
            assert r.status_code == 422, r.text
            assert "monthly_nth_week" in r.text
        _run_with_http(_t)
    finally:
        clear()
        _cleanup_between_tests()


def test_monthly_day_of_month_backcompat():
    """Legacy monthly (no monthly_pattern field, day_of_month=15) must
    keep working and default `monthly_pattern` to `day_of_month`."""
    _seed()
    _cleanup_between_tests()
    clear = _install_overrides()
    try:
        async def _t(ac, db):
            r = await ac.post(
                "/api/recurring-jobs",
                json={
                    "customer_id": CUSTOMER_ID,
                    "service_type": "test_monthly_dom_legacy",
                    "frequency": "monthly",
                    "day_of_month": 15,
                    "start_date": "2026-01-01",
                    "price_cents": 100,
                },
            )
            assert r.status_code == 200, r.text
            tpl = r.json()
            tpl_id = tpl["id"]
            assert tpl.get("monthly_pattern") in ("day_of_month", None)
            # GET to get upcoming[].
            r = await ac.get(f"/api/recurring-jobs/{tpl_id}")
            upcoming = r.json().get("upcoming") or []
            for iso in upcoming:
                assert date.fromisoformat(iso).day == 15
        _run_with_http(_t)
    finally:
        clear()
        _cleanup_between_tests()
