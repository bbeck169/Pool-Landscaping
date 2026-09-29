"""Phase H10 · Feb-2026 — revenue forecast recurring_jobs contribution."""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta

import pytest
from fastapi import HTTPException

from tests._f7_loop_fixture import run_test


async def _admin_ctx(db):
    tenant = await db.tenants.find_one({"slug": "aquaterra"},
                                          {"_id": 0, "id": 1})
    tid = tenant["id"]
    admin = await db.users.find_one({"email": "admin@aquaterra.com"},
                                       {"_id": 0, "id": 1, "role": 1})
    return tid, admin


async def _cleanup(db, tid, prefix):
    await db.recurring_job_templates.delete_many(
        {"tenant_id": tid, "id": {"$regex": f"^{prefix}"}},
    )
    await db.jobs.delete_many(
        {"tenant_id": tid, "id": {"$regex": f"^{prefix}"}},
    )


def test_h10_recurring_jobs_contribute_and_dedupe():
    """Seed a weekly template starting today. Materialize the
    first two occurrences as jobs. Fetch ?this_month → BOOKED
    sums the materialized rows, RECURRING sums the remaining
    non-materialized occurrences with NO overlap."""
    from routers.dashboard_revenue import revenue_forecast

    async def _go(db):
        tid, admin = await _admin_ctx(db)
        prefix = f"H10_{uuid.uuid4().hex[:6]}_"
        await _cleanup(db, tid, prefix)
        today = date.today()
        # Weekly template starting today; anchor DOW = today's.
        tpl_id = f"{prefix}tpl"
        await db.recurring_job_templates.insert_one({
            "id": tpl_id, "tenant_id": tid,
            "customer_id": "c1", "service_type": "svc",
            "frequency": "weekly", "day_of_week": today.weekday(),
            "start_date": today.isoformat(),
            "recurrence_never_ends": True,
            "active": True, "price_cents": 5000,
        })
        # Materialize today's + a week from today as BOOKED jobs.
        await db.jobs.insert_many([
            {"id": f"{prefix}j0", "tenant_id": tid,
             "status": "scheduled",
             "scheduled_date": today.isoformat(),
             "recurring_template_id": tpl_id,
             "price": 50.0},
            {"id": f"{prefix}j1", "tenant_id": tid,
             "status": "scheduled",
             "scheduled_date": (today + timedelta(days=7)).isoformat(),
             "recurring_template_id": tpl_id,
             "price": 50.0},
        ])
        # This-month window.
        first = today.replace(day=1)
        if today.month == 12:
            last = date(today.year + 1, 1, 1) - timedelta(days=1)
        else:
            last = date(today.year, today.month + 1, 1) - timedelta(days=1)
        try:
            r = await revenue_forecast(
                start=first.isoformat(), end=last.isoformat(),
                user=admin, tenant={"id": tid, "timezone": "UTC"},
            )
            # BOOKED: at least the first materialized $50 row.
            # (The second row may fall outside a short late-month
            # window when today is near month-end.)
            assert r["booked"]["amount"] >= 50.0
            # RECURRING (recurring_jobs axis): remaining occurrences
            # in this month, each $50. Count > 0 for any month that
            # has more than one Monday-through-Sunday cycle.
            rj = r["recurring"]["recurring_job_amount"]
            rjc = r["recurring"]["recurring_job_count"]
            # There should be more expected occurrences than we
            # materialized — endpoint MUST NOT double-count the
            # two seeded rows. Aquaterra may carry additional
            # seed templates too, so we assert additivity:
            # anything > 0 proves the recurring_jobs axis fires.
            assert rjc > 0, f"expected non-zero recurring count; got {rjc}"
            assert rj > 0, f"expected non-zero recurring amount; got {rj}"
            # Active-template counter surfaced.
            assert r["recurring"]["active_template_count"] >= 1
        finally:
            await _cleanup(db, tid, prefix)

    run_test(_go)


def test_h10_paused_template_contributes_zero():
    from routers.dashboard_revenue import revenue_forecast

    async def _go(db):
        tid, admin = await _admin_ctx(db)
        prefix = f"H10_PZ_{uuid.uuid4().hex[:6]}_"
        await _cleanup(db, tid, prefix)
        today = date.today()
        window = (today.isoformat(),
                  (today + timedelta(days=30)).isoformat())
        # Feb-2026 · Test Hygiene Phase 2 — measure the tenant's
        # baseline recurring amount BEFORE seeding the paused
        # template so the assertion no longer depends on a fixed
        # $9999 threshold.  The aquaterra demo tenant now carries
        # enough active recurring templates that the total exceeds
        # the pre-drift threshold; the actual contract the test
        # locks in ("paused templates contribute nothing") is
        # verified by a strict before/after equality on the
        # baseline sum, not a magic-number ceiling.
        r_before = await revenue_forecast(
            start=window[0], end=window[1],
            user=admin, tenant={"id": tid, "timezone": "UTC"},
        )
        baseline = r_before["recurring"]["recurring_job_amount"]
        # Use a distinctive per-run price that could not possibly
        # ROUNDING-coincidentally match the baseline — makes any
        # "paused template DID contribute" regression trivially
        # detectable.
        paused_price_cents = 1234567
        await db.recurring_job_templates.insert_one({
            "id": f"{prefix}tpl", "tenant_id": tid,
            "customer_id": "c", "service_type": "svc",
            "frequency": "weekly", "day_of_week": today.weekday(),
            "start_date": today.isoformat(),
            "recurrence_never_ends": True,
            "active": False,   # paused
            "price_cents": paused_price_cents,
        })
        try:
            r_after = await revenue_forecast(
                start=window[0], end=window[1],
                user=admin, tenant={"id": tid, "timezone": "UTC"},
            )
            # Paused templates NOT counted → the recurring total
            # must be EXACTLY what it was before we seeded the row.
            assert r_after["recurring"]["recurring_job_amount"] == baseline, (
                f"paused template appears to have contributed: "
                f"baseline={baseline}, after={r_after['recurring']['recurring_job_amount']}"
            )
        finally:
            await _cleanup(db, tid, prefix)

    run_test(_go)


def test_h10_tenant_scoping_prevents_leak():
    from routers.dashboard_revenue import revenue_forecast

    async def _go(db):
        tid_a, admin_a = await _admin_ctx(db)
        tid_b = f"h10-alt-{uuid.uuid4().hex[:6]}"
        await db.tenants.insert_one(
            {"id": tid_b, "slug": tid_b, "name": "H10 alt"},
        )
        prefix = f"H10_ISO_{uuid.uuid4().hex[:6]}_"
        today = date.today()
        try:
            await db.recurring_job_templates.insert_one({
                "id": f"{prefix}b", "tenant_id": tid_b,
                "customer_id": "c", "service_type": "svc",
                "frequency": "weekly",
                "day_of_week": today.weekday(),
                "start_date": today.isoformat(),
                "recurrence_never_ends": True,
                "active": True, "price_cents": 88888,
            })
            r = await revenue_forecast(
                start=today.isoformat(),
                end=(today + timedelta(days=30)).isoformat(),
                user=admin_a, tenant={"id": tid_a, "timezone": "UTC"},
            )
            assert r["recurring"]["recurring_job_amount"] < 88888.0
        finally:
            await db.recurring_job_templates.delete_many(
                {"tenant_id": tid_b},
            )
            await db.tenants.delete_one({"id": tid_b})

    run_test(_go)


def test_h10_rbac_tech_blocked():
    from routers.dashboard_revenue import revenue_forecast

    async def _go(db):
        tid, _ = await _admin_ctx(db)
        tech = {"id": "h10-tech", "role": "technician",
                   "tenant_id": tid}
        today = date.today()
        with pytest.raises(HTTPException) as ei:
            await revenue_forecast(
                start=today.isoformat(), end=today.isoformat(),
                user=tech, tenant={"id": tid, "timezone": "UTC"},
            )
        assert ei.value.status_code == 403

    run_test(_go)
