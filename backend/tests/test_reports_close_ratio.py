"""Feb-2026 · Phase 5b.1 — Close Ratio tests."""
from __future__ import annotations

from tests._f7_loop_fixture import run_test
from utils import new_id


def test_close_ratio_happy_path_and_normalization():
    """Legacy title-case status values must normalize into the
    canonical enum so old writes don't fall out of the count."""
    from routers import reports_close_ratio as cr

    async def _go(db):
        tid = new_id()
        # 5 leads created in Feb 2026:
        #   2 canonical closed_won
        #   1 legacy "Closed Won" (title-case)
        #   1 canonical closed_lost
        #   1 open ("contacted") — excluded from ratio denominator
        base = "2026-02-{d:02d}T10:00:00+00:00"
        await db.leads.insert_many([
            {"id": "L1", "tenant_id": tid, "status": "closed_won",
             "created_at": base.format(d=5)},
            {"id": "L2", "tenant_id": tid, "status": "closed_won",
             "created_at": base.format(d=8)},
            {"id": "L3", "tenant_id": tid, "status": "Closed Won",
             "created_at": base.format(d=10)},
            {"id": "L4", "tenant_id": tid, "status": "closed_lost",
             "created_at": base.format(d=12)},
            {"id": "L5", "tenant_id": tid, "status": "contacted",
             "created_at": base.format(d=14)},
        ])
        try:
            res = await cr.close_ratio(
                start_date="2026-02-01", end_date="2026-02-28",
                tenant_id=None,
                user={"id": "u", "role": "admin"}, tenant={"id": tid},
            )
            # 5 created, 3 won (2 canonical + 1 legacy), 1 lost.
            # ratio = 3/(3+1) = 75.0%.
            assert res["summary"]["leads_created"] == 5
            assert res["summary"]["leads_closed_won"] == 3
            assert res["summary"]["leads_closed_lost"] == 1
            assert res["summary"]["close_ratio_pct"] == 75.0
            # Feb 2026 row present with the same numbers.
            feb = next(r for r in res["rows"] if r["month"] == "2026-02")
            assert feb["leads_created"] == 5
            assert feb["closed_won"] == 3
            assert feb["closed_lost"] == 1
            assert feb["close_ratio_pct"] == 75.0
            # Monthly chart mirrors the row.
            assert res["chart"]["monthly_close_ratio"][0]["close_ratio_pct"] == 75.0
        finally:
            await db.leads.delete_many({"tenant_id": tid})

    run_test(_go)


def test_close_ratio_out_of_window_excluded():
    from routers import reports_close_ratio as cr

    async def _go(db):
        tid = new_id()
        await db.leads.insert_many([
            {"id": "in-win", "tenant_id": tid, "status": "closed_won",
             "created_at": "2026-02-15T00:00:00+00:00"},
            {"id": "before", "tenant_id": tid, "status": "closed_won",
             "created_at": "2026-01-15T00:00:00+00:00"},
            {"id": "after", "tenant_id": tid, "status": "closed_won",
             "created_at": "2026-03-15T00:00:00+00:00"},
        ])
        try:
            res = await cr.close_ratio(
                start_date="2026-02-01", end_date="2026-02-28",
                tenant_id=None,
                user={"id": "u", "role": "admin"}, tenant={"id": tid},
            )
            assert res["summary"]["leads_created"] == 1
            assert res["summary"]["leads_closed_won"] == 1
        finally:
            await db.leads.delete_many({"tenant_id": tid})

    run_test(_go)


def test_close_ratio_all_open_returns_zero_not_error():
    """Denominator = 0 (no won or lost yet) → ratio safely returns
    0.0 without dividing by zero."""
    from routers import reports_close_ratio as cr

    async def _go(db):
        tid = new_id()
        await db.leads.insert_many([
            {"id": "o1", "tenant_id": tid, "status": "new",
             "created_at": "2026-02-05T00:00:00+00:00"},
            {"id": "o2", "tenant_id": tid, "status": "contacted",
             "created_at": "2026-02-10T00:00:00+00:00"},
        ])
        try:
            res = await cr.close_ratio(
                start_date="2026-02-01", end_date="2026-02-28",
                tenant_id=None,
                user={"id": "u", "role": "admin"}, tenant={"id": tid},
            )
            assert res["summary"]["leads_created"] == 2
            assert res["summary"]["leads_closed_won"] == 0
            assert res["summary"]["leads_closed_lost"] == 0
            assert res["summary"]["close_ratio_pct"] == 0.0
        finally:
            await db.leads.delete_many({"tenant_id": tid})

    run_test(_go)


def test_close_ratio_rejects_tenant_override_for_non_super_admin():
    from fastapi import HTTPException
    from routers import reports_close_ratio as cr

    async def _go(_db):
        try:
            await cr.close_ratio(
                start_date="2026-02-01", end_date="2026-02-28",
                tenant_id="OTHER",
                user={"id": "u", "role": "admin"}, tenant={"id": "MINE"},
            )
            assert False
        except HTTPException as exc:
            assert exc.status_code == 403

    run_test(_go)


def test_close_ratio_bad_date_400():
    from fastapi import HTTPException
    from routers import reports_close_ratio as cr

    async def _go(_db):
        try:
            await cr.close_ratio(
                start_date="bogus", end_date="2026-02-28",
                tenant_id=None,
                user={"id": "u", "role": "admin"}, tenant={"id": "T"},
            )
            assert False
        except HTTPException as exc:
            assert exc.status_code == 400

    run_test(_go)
