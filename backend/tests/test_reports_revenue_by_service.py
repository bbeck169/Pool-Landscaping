"""Feb-2026 · Phase 5a.2 — Revenue by Service tests."""
from __future__ import annotations

from tests._f7_loop_fixture import run_test
from utils import new_id


def test_revenue_by_service_happy_path_rows_and_summary():
    from routers import reports_revenue_by_service as rbs

    async def _go(db):
        tid = new_id()
        # 3 invoices — 2 "Weekly Pool Service", 1 "Deck Repair".
        # Deck is paid, both Weeklies are paid → all count in
        # billed AND collected.
        await db.quotes.insert_many([
            {"id": "i1", "tenant_id": tid, "doc_type": "invoice",
             "title": "Weekly Pool Service", "total": 120,
             "payment_status": "paid", "amount_paid": 120,
             "created_at": "2026-02-10T10:00:00+00:00"},
            {"id": "i2", "tenant_id": tid, "doc_type": "invoice",
             "title": "Weekly Pool Service", "total": 130,
             "payment_status": "paid", "amount_paid": 130,
             "created_at": "2026-02-17T10:00:00+00:00"},
            {"id": "i3", "tenant_id": tid, "doc_type": "invoice",
             "title": "Deck Repair", "total": 500,
             "payment_status": "unpaid", "amount_paid": 0,
             "created_at": "2026-02-20T10:00:00+00:00"},
        ])
        try:
            res = await rbs.revenue_by_service(
                start_date="2026-02-01", end_date="2026-02-28",
                tenant_id=None,
                user={"id": "u", "role": "admin"}, tenant={"id": tid},
            )
            # Summary — 250+500 billed, 250 collected.
            assert res["summary"]["total_billed"] == 750.0
            assert res["summary"]["total_collected"] == 250.0
            # Deck has the higher billed ($500 vs $250) → top.
            assert res["summary"]["top_service_by_revenue"]["name"] == "Deck Repair"
            # Rows sorted by billed desc.
            assert res["rows"][0]["service_name"] == "Deck Repair"
            assert res["rows"][0]["billed_amount"] == 500.0
            assert res["rows"][0]["collected_amount"] == 0.0
            assert res["rows"][0]["job_count"] == 1
            assert res["rows"][0]["avg_ticket"] == 500.0
            assert res["rows"][1]["service_name"] == "Weekly Pool Service"
            assert res["rows"][1]["billed_amount"] == 250.0
            assert res["rows"][1]["collected_amount"] == 250.0
            assert res["rows"][1]["job_count"] == 2
            assert res["rows"][1]["avg_ticket"] == 125.0
            # Chart top_services.
            assert len(res["chart"]["top_services"]) == 2
        finally:
            await db.quotes.delete_many({"tenant_id": tid})

    run_test(_go)


def test_revenue_by_service_out_of_window_excluded():
    from routers import reports_revenue_by_service as rbs

    async def _go(db):
        tid = new_id()
        await db.quotes.insert_many([
            {"id": "in", "tenant_id": tid, "doc_type": "invoice",
             "title": "Pool", "total": 100, "payment_status": "paid",
             "created_at": "2026-02-15T00:00:00+00:00"},
            {"id": "out", "tenant_id": tid, "doc_type": "invoice",
             "title": "Landscape", "total": 300, "payment_status": "paid",
             "created_at": "2026-03-15T00:00:00+00:00"},
        ])
        try:
            res = await rbs.revenue_by_service(
                start_date="2026-02-01", end_date="2026-02-28",
                tenant_id=None,
                user={"id": "u", "role": "admin"}, tenant={"id": tid},
            )
            assert res["summary"]["total_billed"] == 100.0
            assert len(res["rows"]) == 1
            assert res["rows"][0]["service_name"] == "Pool"
        finally:
            await db.quotes.delete_many({"tenant_id": tid})

    run_test(_go)


def test_revenue_by_service_missing_title_becomes_unclassified():
    from routers import reports_revenue_by_service as rbs

    async def _go(db):
        tid = new_id()
        await db.quotes.insert_one({
            "id": "x", "tenant_id": tid, "doc_type": "invoice",
            "total": 60, "payment_status": "paid",
            "created_at": "2026-02-15T00:00:00+00:00",
        })
        try:
            res = await rbs.revenue_by_service(
                start_date="2026-02-01", end_date="2026-02-28",
                tenant_id=None,
                user={"id": "u", "role": "admin"}, tenant={"id": tid},
            )
            assert res["rows"][0]["service_name"] == "Unclassified"
            assert res["rows"][0]["service_id"] == "unclassified"
        finally:
            await db.quotes.delete_many({"tenant_id": tid})

    run_test(_go)


def test_revenue_by_service_rejects_tenant_override_for_non_super_admin():
    from fastapi import HTTPException
    from routers import reports_revenue_by_service as rbs

    async def _go(_db):
        try:
            await rbs.revenue_by_service(
                start_date="2026-02-01", end_date="2026-02-28",
                tenant_id="OTHER",
                user={"id": "u", "role": "admin"}, tenant={"id": "MINE"},
            )
            assert False
        except HTTPException as exc:
            assert exc.status_code == 403

    run_test(_go)


def test_revenue_by_service_empty_returns_zero_envelope():
    from routers import reports_revenue_by_service as rbs

    async def _go(db):
        tid = new_id()
        try:
            res = await rbs.revenue_by_service(
                start_date="2026-02-01", end_date="2026-02-28",
                tenant_id=None,
                user={"id": "u", "role": "admin"}, tenant={"id": tid},
            )
            assert res["summary"]["total_billed"] == 0.0
            assert res["summary"]["total_collected"] == 0.0
            assert res["summary"]["top_service_by_revenue"]["name"] is None
            assert res["rows"] == []
            assert res["chart"]["top_services"] == []
        finally:
            pass

    run_test(_go)
