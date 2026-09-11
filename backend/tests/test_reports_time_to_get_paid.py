"""Feb-2026 · Reports Gap Fill Phase 5a.1 (Part B) — Time to Get Paid tests.

Contract-locked invariants:
  1. Happy path — paid invoices in the window contribute to
     ``summary`` (avg/p50/p90/count) + ``rows`` sorted by
     ``days_to_paid`` desc. The trailing-12-month chart is
     independent of the filter and buckets by ``paid_at`` month.
  2. Skip conditions — invoices missing either timestamp OR with
     ``paid_at < sent_at`` are dropped from BOTH summary and rows.
  3. ``sent_at`` fallback — when the invoice doc lacks a distinct
     ``sent_at``, ``created_at`` is used as the issuance floor
     (mirrors ``analytics.churn_risk``).
  4. Tenant isolation — non-super-admin caller with ``tenant_id=``
     override → 403.
  5. Bad date format → 400.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from tests._f7_loop_fixture import run_test
from utils import new_id


def _iso(dt: datetime) -> str:
    return dt.replace(tzinfo=timezone.utc).isoformat()


def test_ttgp_happy_path_summary_and_rows():
    from routers import reports_time_to_get_paid as ttgp

    async def _go(db):
        tid = new_id()
        cid = new_id()
        await db.customers.insert_one({
            "id": cid, "tenant_id": tid, "name": "Payer Pete",
        })
        # 3 valid paid invoices in the window (created_at → paid_at).
        # Deltas: 5, 10, 15 days → avg=10, p50=10, p90=14.
        base = datetime(2026, 2, 1, 12, 0, 0)
        pairs = [(0, 5), (2, 12), (10, 25)]  # (created_offset, paid_offset)
        for i, (co, po) in enumerate(pairs):
            await db.quotes.insert_one({
                "id": f"inv-{i}", "tenant_id": tid,
                "doc_type": "invoice", "payment_status": "paid",
                "customer_id": cid,
                "created_at": _iso(base + timedelta(days=co)),
                "paid_at":    _iso(base + timedelta(days=po)),
                "total": 100,
            })
        try:
            res = await ttgp.time_to_get_paid(
                start_date="2026-02-01", end_date="2026-02-28",
                tenant_id=None,
                user={"id": "u", "role": "admin"}, tenant={"id": tid},
            )
            assert res["summary"]["invoices_counted"] == 3
            # Deltas: 5, 10, 15 days
            assert res["summary"]["avg_days_to_paid"] == 10.0
            assert res["summary"]["p50_days"] == 10.0
            assert res["summary"]["p90_days"] == 14.0
            # Rows sorted by days_to_paid desc.
            assert [r["invoice_id"] for r in res["rows"]] == [
                "inv-2", "inv-1", "inv-0",
            ]
            assert res["rows"][0]["days_to_paid"] == 15.0
            assert res["rows"][0]["customer_name"] == "Payer Pete"
            # Chart carries at least the month of paid_at.
            months = {r["month"] for r in res["chart"]["monthly_avg_days"]}
            assert "2026-02" in months
        finally:
            await db.customers.delete_many({"tenant_id": tid})
            await db.quotes.delete_many({"tenant_id": tid})

    run_test(_go)


def test_ttgp_skips_partials_and_negatives():
    from routers import reports_time_to_get_paid as ttgp

    async def _go(db):
        tid = new_id()
        cid = new_id()
        await db.customers.insert_one({
            "id": cid, "tenant_id": tid, "name": "Payer Pete",
        })
        base = datetime(2026, 2, 10, 12, 0, 0)
        # OK: 4 day delta.
        await db.quotes.insert_one({
            "id": "ok-1", "tenant_id": tid, "doc_type": "invoice",
            "payment_status": "paid", "customer_id": cid,
            "created_at": _iso(base), "paid_at": _iso(base + timedelta(days=4)),
        })
        # Missing paid_at → skipped.
        await db.quotes.insert_one({
            "id": "no-paid", "tenant_id": tid, "doc_type": "invoice",
            "payment_status": "paid", "customer_id": cid,
            "created_at": _iso(base), "paid_at": None,
        })
        # paid_at < created_at → skipped.
        await db.quotes.insert_one({
            "id": "backdated", "tenant_id": tid, "doc_type": "invoice",
            "payment_status": "paid", "customer_id": cid,
            "created_at": _iso(base + timedelta(days=5)),
            "paid_at":    _iso(base),
        })
        try:
            res = await ttgp.time_to_get_paid(
                start_date="2026-02-01", end_date="2026-02-28",
                tenant_id=None,
                user={"id": "u", "role": "admin"}, tenant={"id": tid},
            )
            assert res["summary"]["invoices_counted"] == 1
            assert [r["invoice_id"] for r in res["rows"]] == ["ok-1"]
        finally:
            await db.customers.delete_many({"tenant_id": tid})
            await db.quotes.delete_many({"tenant_id": tid})

    run_test(_go)


def test_ttgp_sent_at_wins_over_created_at_when_present():
    from routers import reports_time_to_get_paid as ttgp

    async def _go(db):
        tid = new_id()
        cid = new_id()
        await db.customers.insert_one({
            "id": cid, "tenant_id": tid, "name": "Payer Pete",
        })
        # created_at=Feb 1, sent_at=Feb 5, paid_at=Feb 10 → delta=5 (not 9).
        await db.quotes.insert_one({
            "id": "sent-vs-created", "tenant_id": tid,
            "doc_type": "invoice", "payment_status": "paid",
            "customer_id": cid,
            "created_at": _iso(datetime(2026, 2, 1, 0, 0, 0)),
            "sent_at":    _iso(datetime(2026, 2, 5, 0, 0, 0)),
            "paid_at":    _iso(datetime(2026, 2, 10, 0, 0, 0)),
        })
        try:
            res = await ttgp.time_to_get_paid(
                start_date="2026-02-01", end_date="2026-02-28",
                tenant_id=None,
                user={"id": "u", "role": "admin"}, tenant={"id": tid},
            )
            assert res["summary"]["invoices_counted"] == 1
            assert res["rows"][0]["days_to_paid"] == 5.0
        finally:
            await db.customers.delete_many({"tenant_id": tid})
            await db.quotes.delete_many({"tenant_id": tid})

    run_test(_go)


def test_ttgp_rejects_tenant_override_for_non_super_admin():
    from fastapi import HTTPException
    from routers import reports_time_to_get_paid as ttgp

    async def _go(_db):
        try:
            await ttgp.time_to_get_paid(
                start_date="2026-02-01", end_date="2026-02-28",
                tenant_id="OTHER",
                user={"id": "u", "role": "admin"}, tenant={"id": "MINE"},
            )
            assert False, "should have raised 403"
        except HTTPException as exc:
            assert exc.status_code == 403

    run_test(_go)


def test_ttgp_bad_date_format_400():
    from fastapi import HTTPException
    from routers import reports_time_to_get_paid as ttgp

    async def _go(_db):
        try:
            await ttgp.time_to_get_paid(
                start_date="2026-02-01", end_date="bogus",
                tenant_id=None,
                user={"id": "u", "role": "admin"}, tenant={"id": "T"},
            )
            assert False, "should have raised 400"
        except HTTPException as exc:
            assert exc.status_code == 400

    run_test(_go)
