"""Feb-2026 · Phase 5b.2 — Labor Efficiency tests."""
from __future__ import annotations

from tests._f7_loop_fixture import run_test
from utils import new_id


def test_labor_efficiency_happy_path_summary_and_worst_first_sort():
    from routers import reports_labor_efficiency as le

    async def _go(db):
        tid = new_id()
        cid = new_id()
        tech_id = new_id()
        await db.customers.insert_one({
            "id": cid, "tenant_id": tid, "name": "Careful Carol",
        })
        await db.technicians.insert_one({
            "id": tech_id, "tenant_id": tid, "name": "Timely Tim",
        })
        # 3 jobs — one on-budget, one over (worst), one under.
        await db.jobs.insert_many([
            {"id": "j-on", "tenant_id": tid, "customer_id": cid,
             "scheduled_date": "2026-02-05",
             "budgeted_hours": 4, "actual_hours": 4,
             "technician_id": tech_id},
            {"id": "j-over", "tenant_id": tid, "customer_id": cid,
             "scheduled_date": "2026-02-10",
             "budgeted_hours": 4, "actual_hours": 8,   # 50%
             "technician_id": tech_id},
            {"id": "j-under", "tenant_id": tid, "customer_id": cid,
             "scheduled_date": "2026-02-15",
             "budgeted_hours": 6, "actual_hours": 4,   # 150%
             "technician_id": tech_id},
        ])
        try:
            res = await le.labor_efficiency(
                start_date="2026-02-01", end_date="2026-02-28",
                tenant_id=None,
                user={"id": "u", "role": "admin"}, tenant={"id": tid},
            )
            # Summary — sum(budgeted)=14 / sum(actual)=16 = 87.5%.
            assert res["summary"]["jobs_counted"] == 3
            assert res["summary"]["budgeted_hours"] == 14.0
            assert res["summary"]["actual_hours"] == 16.0
            assert res["summary"]["labor_efficiency_pct"] == 87.5
            # Sort — worst-first (asc by efficiency_pct).
            assert [r["job_id"] for r in res["rows"]] == ["j-over", "j-on", "j-under"]
            assert res["rows"][0]["efficiency_pct"] == 50.0
            assert res["rows"][2]["efficiency_pct"] == 150.0
            # Row enrichment.
            assert res["rows"][0]["customer_name"] == "Careful Carol"
            assert res["rows"][0]["technician_name"] == "Timely Tim"
            # Monthly chart row present.
            feb = next(r for r in res["chart"]["monthly_efficiency"]
                          if r["month"] == "2026-02")
            assert feb["efficiency_pct"] == 87.5
        finally:
            await db.jobs.delete_many({"tenant_id": tid})
            await db.customers.delete_many({"tenant_id": tid})
            await db.technicians.delete_many({"tenant_id": tid})

    run_test(_go)


def test_labor_efficiency_zero_actual_dropped_no_divide_by_zero():
    """A job with ``actual_hours=0`` (no time entries logged)
    must be silently dropped — do NOT divide by zero, do NOT
    fabricate a 100%."""
    from routers import reports_labor_efficiency as le

    async def _go(db):
        tid = new_id()
        await db.jobs.insert_many([
            {"id": "unlogged", "tenant_id": tid,
             "scheduled_date": "2026-02-10",
             "budgeted_hours": 4, "actual_hours": 0},
            {"id": "logged", "tenant_id": tid,
             "scheduled_date": "2026-02-12",
             "budgeted_hours": 4, "actual_hours": 4},
        ])
        try:
            res = await le.labor_efficiency(
                start_date="2026-02-01", end_date="2026-02-28",
                tenant_id=None,
                user={"id": "u", "role": "admin"}, tenant={"id": tid},
            )
            assert res["summary"]["jobs_counted"] == 1
            assert [r["job_id"] for r in res["rows"]] == ["logged"]
        finally:
            await db.jobs.delete_many({"tenant_id": tid})

    run_test(_go)


def test_labor_efficiency_fallback_hours_fields():
    """When ``budgeted_hours`` is missing, fall through to
    ``estimated_hours`` then ``duration_hours``."""
    from routers import reports_labor_efficiency as le

    async def _go(db):
        tid = new_id()
        await db.jobs.insert_many([
            {"id": "j-est", "tenant_id": tid,
             "scheduled_date": "2026-02-10",
             "estimated_hours": 3, "actual_hours": 3},   # 100
            {"id": "j-dur", "tenant_id": tid,
             "scheduled_date": "2026-02-12",
             "duration_hours": 2, "actual_hours": 4},    # 50
        ])
        try:
            res = await le.labor_efficiency(
                start_date="2026-02-01", end_date="2026-02-28",
                tenant_id=None,
                user={"id": "u", "role": "admin"}, tenant={"id": tid},
            )
            assert res["summary"]["jobs_counted"] == 2
            row_map = {r["job_id"]: r for r in res["rows"]}
            assert row_map["j-est"]["efficiency_pct"] == 100.0
            assert row_map["j-dur"]["efficiency_pct"] == 50.0
        finally:
            await db.jobs.delete_many({"tenant_id": tid})

    run_test(_go)


def test_labor_efficiency_rejects_tenant_override_for_non_super_admin():
    from fastapi import HTTPException
    from routers import reports_labor_efficiency as le

    async def _go(_db):
        try:
            await le.labor_efficiency(
                start_date="2026-02-01", end_date="2026-02-28",
                tenant_id="OTHER",
                user={"id": "u", "role": "admin"}, tenant={"id": "MINE"},
            )
            assert False
        except HTTPException as exc:
            assert exc.status_code == 403

    run_test(_go)


def test_labor_efficiency_empty_returns_zero_envelope():
    """Insufficient-data path — no rows returned, no divide-by-zero."""
    from routers import reports_labor_efficiency as le

    async def _go(db):
        tid = new_id()
        try:
            res = await le.labor_efficiency(
                start_date="2026-02-01", end_date="2026-02-28",
                tenant_id=None,
                user={"id": "u", "role": "admin"}, tenant={"id": tid},
            )
            assert res["summary"]["jobs_counted"] == 0
            assert res["summary"]["labor_efficiency_pct"] == 0.0
            assert res["rows"] == []
        finally:
            pass

    run_test(_go)
