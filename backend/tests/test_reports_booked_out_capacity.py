"""Feb-2026 · Phase 5b.2 — Booked Out / Capacity tests.

The critical parity requirement: ``weekly_capacity_hours`` from
this report MUST equal ``bh_per_week_capacity`` from Business
Snapshot for the same tenant. The single unit-test invariant
``test_booked_out_reuses_business_snapshot_capacity_helpers``
locks the parity at the helper level (same functions imported)
AND at the number level (same output).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from tests._f7_loop_fixture import run_test
from utils import new_id


def _monday_of(d: date) -> date:
    return d - timedelta(days=d.weekday())


async def _seed_two_active_techs(db, tid: str) -> None:
    """40 hr/week per tech → 2 techs = 80 hr/week capacity.
    Fixture used by multiple tests in this file."""
    await db.technicians.insert_many([
        {"id": new_id(), "tenant_id": tid, "name": "Alice",
         "active": True},
        {"id": new_id(), "tenant_id": tid, "name": "Bob",
         "active": True},
    ])


def test_booked_out_reuses_business_snapshot_capacity_helpers():
    """Parity requirement (dispatch spec) — the capacity number
    surfaced by Booked Out MUST equal Business Snapshot's, and
    the two must share the same helper functions."""
    # Helper identity check — the imports at the top of
    # ``reports_booked_out_capacity`` must resolve to the exact
    # same function objects.
    from routers import reports_booked_out_capacity as boc
    from routers import reports_business_snapshot as bs
    assert boc._active_technicians_for_tenant is bs._active_technicians_for_tenant
    assert boc._weekly_hours_for is bs._weekly_hours_for

    async def _go(db):
        tid = new_id()
        await db.tenants.insert_one({"id": tid, "name": "P5b2 Tenant"})
        await _seed_two_active_techs(db, tid)
        try:
            b = await bs.business_snapshot(
                tenant_id=None,
                user={"id": "u", "role": "admin"}, tenant={"id": tid},
            )
            r = await boc.booked_out_capacity(
                weeks_ahead=8, tenant_id=None,
                user={"id": "u", "role": "admin"}, tenant={"id": tid},
            )
            # Number-level parity — same value on both surfaces.
            assert r["summary"]["weekly_capacity_hours"] == b["bh_per_week_capacity"]
            # 2 techs × 40 hr = 80 (Business Snapshot default).
            assert r["summary"]["weekly_capacity_hours"] == 80.0
        finally:
            await db.tenants.delete_many({"id": tid})
            await db.technicians.delete_many({"tenant_id": tid})

    run_test(_go)


def test_booked_out_happy_path_row_shape_and_first_available():
    from routers import reports_booked_out_capacity as boc

    async def _go(db):
        tid = new_id()
        await db.tenants.insert_one({"id": tid, "name": "P5b2 Tenant"})
        await _seed_two_active_techs(db, tid)
        # This week: 100 booked hours (over-capacity → 125% util).
        # Next week: 20 booked hours (under 80% → first available).
        today = datetime.now(timezone.utc).date()
        this_mon = _monday_of(today)
        next_mon = this_mon + timedelta(weeks=1)
        await db.jobs.insert_many([
            {"id": "wk0", "tenant_id": tid,
             "scheduled_date": this_mon.isoformat(),
             "budgeted_hours": 100},
            {"id": "wk1", "tenant_id": tid,
             "scheduled_date": next_mon.isoformat(),
             "budgeted_hours": 20},
        ])
        try:
            r = await boc.booked_out_capacity(
                weeks_ahead=4, tenant_id=None,
                user={"id": "u", "role": "admin"}, tenant={"id": tid},
            )
            # Row shape.
            assert len(r["rows"]) == 4
            row0 = r["rows"][0]
            assert row0["week_start"] == this_mon.isoformat()
            assert row0["booked_hours"] == 100.0
            assert row0["capacity_hours"] == 80.0
            assert row0["utilization_pct"] == 125.0
            assert row0["jobs_count"] == 1
            row1 = r["rows"][1]
            assert row1["booked_hours"] == 20.0
            assert row1["utilization_pct"] == 25.0
            # first_available_week — next week (25% < 80%).
            yr, wk, _ = next_mon.isocalendar()
            assert r["summary"]["first_available_week"] == f"{yr:04d}-W{wk:02d}"
            # Chart labels.
            assert r["chart"]["weekly_bookings"][0]["week_label"] == "This week"
            assert r["chart"]["weekly_bookings"][1]["week_label"] == "+1 weeks"
        finally:
            await db.tenants.delete_many({"id": tid})
            await db.technicians.delete_many({"tenant_id": tid})
            await db.jobs.delete_many({"tenant_id": tid})

    run_test(_go)


def test_booked_out_fully_booked_returns_null_first_available():
    """When every week in the window is at ≥80% utilization, the
    endpoint returns ``first_available_week=None`` — truthful null
    rather than fabricated."""
    from routers import reports_booked_out_capacity as boc

    async def _go(db):
        tid = new_id()
        await db.tenants.insert_one({"id": tid, "name": "P5b2 Tenant"})
        await _seed_two_active_techs(db, tid)  # 80 hr/week
        # Slam 80 hours into each of the next 4 weeks.
        today = datetime.now(timezone.utc).date()
        this_mon = _monday_of(today)
        for i in range(4):
            await db.jobs.insert_one({
                "id": f"slam-{i}", "tenant_id": tid,
                "scheduled_date": (this_mon + timedelta(weeks=i)).isoformat(),
                "budgeted_hours": 80,
            })
        try:
            r = await boc.booked_out_capacity(
                weeks_ahead=4, tenant_id=None,
                user={"id": "u", "role": "admin"}, tenant={"id": tid},
            )
            assert r["summary"]["first_available_week"] is None
            assert r["summary"]["avg_weekly_utilization_pct"] == 100.0
        finally:
            await db.tenants.delete_many({"id": tid})
            await db.technicians.delete_many({"tenant_id": tid})
            await db.jobs.delete_many({"tenant_id": tid})

    run_test(_go)


def test_booked_out_rejects_tenant_override_for_non_super_admin():
    from fastapi import HTTPException
    from routers import reports_booked_out_capacity as boc

    async def _go(_db):
        try:
            await boc.booked_out_capacity(
                weeks_ahead=8, tenant_id="OTHER",
                user={"id": "u", "role": "admin"}, tenant={"id": "MINE"},
            )
            assert False
        except HTTPException as exc:
            assert exc.status_code == 403

    run_test(_go)


def test_booked_out_weeks_ahead_bounds_enforced_by_fastapi():
    """FastAPI's ``ge/le`` on Query surfaces a 422 on out-of-range
    values in HTTP. We can only verify the underlying default and
    max here at the call level."""
    from routers import reports_booked_out_capacity as boc

    async def _go(db):
        tid = new_id()
        await db.tenants.insert_one({"id": tid, "name": "P5b2 Tenant"})
        await _seed_two_active_techs(db, tid)
        try:
            # Default weeks_ahead=8 produces 8 rows.
            r = await boc.booked_out_capacity(
                weeks_ahead=8, tenant_id=None,
                user={"id": "u", "role": "admin"}, tenant={"id": tid},
            )
            assert len(r["rows"]) == 8
            # 24 is the documented max.
            r24 = await boc.booked_out_capacity(
                weeks_ahead=24, tenant_id=None,
                user={"id": "u", "role": "admin"}, tenant={"id": tid},
            )
            assert len(r24["rows"]) == 24
        finally:
            await db.tenants.delete_many({"id": tid})
            await db.technicians.delete_many({"tenant_id": tid})

    run_test(_go)
