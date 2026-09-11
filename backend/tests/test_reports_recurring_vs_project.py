"""Feb-2026 · Phase 5a.2 — Recurring vs. Project Revenue tests."""
from __future__ import annotations

from tests._f7_loop_fixture import run_test
from utils import new_id


def test_rvp_happy_path_split_mirrors_dashboard_predicate():
    from routers import reports_recurring_vs_project as rvp

    async def _go(db):
        tid = new_id()
        # ``recurring`` predicate = any of {"monthly","weekly","recurring"}
        # in invoice.title (dashboard.py:L167).
        await db.quotes.insert_many([
            {"id": "r1", "tenant_id": tid, "doc_type": "invoice",
             "title": "Weekly Pool Service", "total": 100,
             "payment_status": "paid",
             "paid_at": "2026-02-05T10:00:00+00:00"},
            {"id": "r2", "tenant_id": tid, "doc_type": "invoice",
             "title": "Monthly Maintenance", "total": 200,
             "payment_status": "paid",
             "paid_at": "2026-02-12T10:00:00+00:00"},
            {"id": "p1", "tenant_id": tid, "doc_type": "invoice",
             "title": "Deck Repair", "total": 700,
             "payment_status": "paid",
             "paid_at": "2026-02-15T10:00:00+00:00"},
        ])
        try:
            res = await rvp.recurring_vs_project_revenue(
                start_date="2026-02-01", end_date="2026-02-28",
                tenant_id=None,
                user={"id": "u", "role": "admin"}, tenant={"id": tid},
            )
            # 300 recurring + 700 project = 1000 total; 30% recurring.
            assert res["summary"]["total_revenue"] == 1000.0
            assert res["summary"]["recurring_amount"] == 300.0
            assert res["summary"]["project_amount"] == 700.0
            assert res["summary"]["recurring_pct"] == 30.0
            # Donut mirrors the summary.
            assert res["chart"]["donut"] == {
                "recurring": 300.0, "project": 700.0,
            }
            # Monthly rows carry both buckets.
            feb = next(r for r in res["rows"] if r["month"] == "2026-02")
            assert feb["recurring_amount"] == 300.0
            assert feb["project_amount"] == 700.0
            assert feb["total"] == 1000.0
        finally:
            await db.quotes.delete_many({"tenant_id": tid})

    run_test(_go)


def test_rvp_unpaid_invoices_excluded():
    from routers import reports_recurring_vs_project as rvp

    async def _go(db):
        tid = new_id()
        await db.quotes.insert_many([
            {"id": "paid-rec", "tenant_id": tid, "doc_type": "invoice",
             "title": "Weekly Service", "total": 100,
             "payment_status": "paid",
             "paid_at": "2026-02-10T00:00:00+00:00"},
            {"id": "unpaid", "tenant_id": tid, "doc_type": "invoice",
             "title": "Weekly Service", "total": 500,
             "payment_status": "unpaid",
             "created_at": "2026-02-10T00:00:00+00:00"},
        ])
        try:
            res = await rvp.recurring_vs_project_revenue(
                start_date="2026-02-01", end_date="2026-02-28",
                tenant_id=None,
                user={"id": "u", "role": "admin"}, tenant={"id": tid},
            )
            # Only the paid $100 counts.
            assert res["summary"]["total_revenue"] == 100.0
            assert res["summary"]["recurring_amount"] == 100.0
        finally:
            await db.quotes.delete_many({"tenant_id": tid})

    run_test(_go)


def test_rvp_rejects_tenant_override_for_non_super_admin():
    from fastapi import HTTPException
    from routers import reports_recurring_vs_project as rvp

    async def _go(_db):
        try:
            await rvp.recurring_vs_project_revenue(
                start_date="2026-02-01", end_date="2026-02-28",
                tenant_id="OTHER",
                user={"id": "u", "role": "admin"}, tenant={"id": "MINE"},
            )
            assert False
        except HTTPException as exc:
            assert exc.status_code == 403

    run_test(_go)


def test_rvp_predicate_verbatim_parity_with_analytics_helper():
    """The router uses ``analytics._is_recurring_invoice``. Assert
    it accepts monthly/weekly/recurring case-insensitively."""
    from routers.analytics import _is_recurring_invoice
    assert _is_recurring_invoice({"title": "Weekly Service"}) is True
    assert _is_recurring_invoice({"title": "MONTHLY Maintenance"}) is True
    assert _is_recurring_invoice({"title": "recurring chemistry"}) is True
    assert _is_recurring_invoice({"title": "Deck Repair"}) is False
    assert _is_recurring_invoice({}) is False


def test_rvp_bad_date_400():
    from fastapi import HTTPException
    from routers import reports_recurring_vs_project as rvp

    async def _go(_db):
        try:
            await rvp.recurring_vs_project_revenue(
                start_date="bogus", end_date="2026-02-28",
                tenant_id=None,
                user={"id": "u", "role": "admin"}, tenant={"id": "T"},
            )
            assert False
        except HTTPException as exc:
            assert exc.status_code == 400

    run_test(_go)
