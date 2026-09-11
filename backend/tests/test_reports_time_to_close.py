"""Feb-2026 · Phase 5b.1 — Time to Close tests."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from tests._f7_loop_fixture import run_test
from utils import new_id


def _iso(dt: datetime) -> str:
    return dt.replace(tzinfo=timezone.utc).isoformat()


def test_ttc_happy_path_summary_and_rows_sorted_desc():
    from routers import reports_time_to_close as ttc

    async def _go(db):
        tid = new_id()
        cid = new_id()
        await db.customers.insert_one({
            "id": cid, "tenant_id": tid, "name": "Lucky Larry",
        })
        # 3 valid leads closed in the window with deltas 5/10/15.
        base = datetime(2026, 2, 1, 12, 0, 0)
        pairs = [(0, 5), (2, 12), (5, 20)]
        for i, (co, po) in enumerate(pairs):
            await db.leads.insert_one({
                "id": f"L-{i}", "tenant_id": tid, "customer_id": cid,
                "status": "closed_won",
                "created_at": _iso(base + timedelta(days=co)),
                "closed_at":  _iso(base + timedelta(days=po)),
            })
        try:
            res = await ttc.time_to_close(
                start_date="2026-02-01", end_date="2026-02-28",
                tenant_id=None,
                user={"id": "u", "role": "admin"}, tenant={"id": tid},
            )
            # Deltas 5/10/15 → avg=10, p50=10, p90=14.
            assert res["summary"]["leads_counted"] == 3
            assert res["summary"]["avg_days_to_close"] == 10.0
            assert res["summary"]["p50_days"] == 10.0
            assert res["summary"]["p90_days"] == 14.0
            # Rows sorted desc by days_to_close.
            assert [r["lead_id"] for r in res["rows"]] == ["L-2","L-1","L-0"]
            assert res["rows"][0]["days_to_close"] == 15.0
            assert res["rows"][0]["outcome"] == "won"
            assert res["rows"][0]["customer_name"] == "Lucky Larry"
        finally:
            await db.leads.delete_many({"tenant_id": tid})
            await db.customers.delete_many({"tenant_id": tid})

    run_test(_go)


def test_ttc_skips_open_leads_and_partials_and_negatives():
    from routers import reports_time_to_close as ttc

    async def _go(db):
        tid = new_id()
        base = datetime(2026, 2, 10, 12, 0, 0)
        # OK.
        await db.leads.insert_one({
            "id": "ok", "tenant_id": tid, "status": "closed_lost",
            "created_at": _iso(base),
            "closed_at":  _iso(base + timedelta(days=3)),
        })
        # Missing closed_at.
        await db.leads.insert_one({
            "id": "no-close", "tenant_id": tid, "status": "contacted",
            "created_at": _iso(base), "closed_at": None,
        })
        # Open lead with stray closed_at populated → excluded.
        await db.leads.insert_one({
            "id": "still-open", "tenant_id": tid, "status": "contacted",
            "created_at": _iso(base),
            "closed_at":  _iso(base + timedelta(days=5)),
        })
        # Negative delta.
        await db.leads.insert_one({
            "id": "neg", "tenant_id": tid, "status": "closed_won",
            "created_at": _iso(base + timedelta(days=5)),
            "closed_at":  _iso(base),
        })
        try:
            res = await ttc.time_to_close(
                start_date="2026-02-01", end_date="2026-02-28",
                tenant_id=None,
                user={"id": "u", "role": "admin"}, tenant={"id": tid},
            )
            assert res["summary"]["leads_counted"] == 1
            assert [r["lead_id"] for r in res["rows"]] == ["ok"]
            assert res["rows"][0]["outcome"] == "lost"
        finally:
            await db.leads.delete_many({"tenant_id": tid})

    run_test(_go)


def test_ttc_status_normalization_legacy_titlecase():
    """Legacy ``Closed Won`` / ``Closed Lost`` must be counted."""
    from routers import reports_time_to_close as ttc

    async def _go(db):
        tid = new_id()
        base = datetime(2026, 2, 10, 12, 0, 0)
        await db.leads.insert_many([
            {"id": "legacy-won", "tenant_id": tid, "status": "Closed Won",
             "created_at": _iso(base),
             "closed_at":  _iso(base + timedelta(days=4))},
            {"id": "legacy-lost", "tenant_id": tid, "status": "Closed Lost",
             "created_at": _iso(base),
             "closed_at":  _iso(base + timedelta(days=8))},
        ])
        try:
            res = await ttc.time_to_close(
                start_date="2026-02-01", end_date="2026-02-28",
                tenant_id=None,
                user={"id": "u", "role": "admin"}, tenant={"id": tid},
            )
            assert res["summary"]["leads_counted"] == 2
            outcomes = sorted(r["outcome"] for r in res["rows"])
            assert outcomes == ["lost", "won"]
        finally:
            await db.leads.delete_many({"tenant_id": tid})

    run_test(_go)


def test_ttc_rejects_tenant_override_for_non_super_admin():
    from fastapi import HTTPException
    from routers import reports_time_to_close as ttc

    async def _go(_db):
        try:
            await ttc.time_to_close(
                start_date="2026-02-01", end_date="2026-02-28",
                tenant_id="OTHER",
                user={"id": "u", "role": "admin"}, tenant={"id": "MINE"},
            )
            assert False
        except HTTPException as exc:
            assert exc.status_code == 403

    run_test(_go)


def test_ttc_bad_date_400():
    from fastapi import HTTPException
    from routers import reports_time_to_close as ttc

    async def _go(_db):
        try:
            await ttc.time_to_close(
                start_date="2026-02-01", end_date="bogus",
                tenant_id=None,
                user={"id": "u", "role": "admin"}, tenant={"id": "T"},
            )
            assert False
        except HTTPException as exc:
            assert exc.status_code == 400

    run_test(_go)
