"""Feb-2026 · Phase 5a.2 — Client Lifetime Value tests."""
from __future__ import annotations

from tests._f7_loop_fixture import run_test
from utils import new_id


def test_clv_happy_path_rows_summary_and_histogram():
    from routers import reports_client_lifetime_value as clv

    async def _go(db):
        tid = new_id()
        # 3 customers, mix of client_type + LTV bands.
        cids = [new_id(), new_id(), new_id()]
        names = ["Big Bertha", "Medium Meg", "Small Sam"]
        for cid, name in zip(cids, names):
            await db.customers.insert_one({
                "id": cid, "tenant_id": tid, "name": name,
                "is_active": True,
            })
        # Big Bertha: $6000 recurring (majority) → recurring / $5K+ bucket.
        await db.quotes.insert_many([
            {"id": "b1", "tenant_id": tid, "doc_type": "invoice",
             "customer_id": cids[0], "title": "Monthly Package",
             "total": 3000, "payment_status": "paid"},
            {"id": "b2", "tenant_id": tid, "doc_type": "invoice",
             "customer_id": cids[0], "title": "Weekly Package",
             "total": 3000, "payment_status": "paid"},
            # Medium Meg: $1500 project (Deck) → project / $1K-2.5K.
            {"id": "m1", "tenant_id": tid, "doc_type": "invoice",
             "customer_id": cids[1], "title": "Deck Build",
             "total": 1500, "payment_status": "paid"},
            # Small Sam: $200 project → project / $0-500.
            {"id": "s1", "tenant_id": tid, "doc_type": "invoice",
             "customer_id": cids[2], "title": "One-off Repair",
             "total": 200, "payment_status": "paid"},
        ])
        # Jobs — first/last service dates.
        await db.jobs.insert_many([
            {"id": "j-b", "tenant_id": tid, "customer_id": cids[0],
             "completed_at": "2026-01-10T00:00:00+00:00"},
            {"id": "j-b2", "tenant_id": tid, "customer_id": cids[0],
             "completed_at": "2026-02-10T00:00:00+00:00"},
            {"id": "j-m", "tenant_id": tid, "customer_id": cids[1],
             "completed_at": "2026-01-20T00:00:00+00:00"},
        ])
        try:
            res = await clv.client_lifetime_value(
                start_date=None, end_date=None, tenant_id=None,
                user={"id": "u", "role": "admin"}, tenant={"id": tid},
            )
            by_cid = {r["customer_id"]: r for r in res["rows"]}
            # Row shape.
            assert by_cid[cids[0]]["client_type"] == "recurring"
            assert by_cid[cids[0]]["total_billed"] == 6000.0
            assert by_cid[cids[0]]["total_collected"] == 6000.0
            assert by_cid[cids[0]]["first_service_date"] == "2026-01-10T00:00:00+00:00"
            assert by_cid[cids[0]]["last_service_date"] == "2026-02-10T00:00:00+00:00"
            assert by_cid[cids[0]]["is_active"] is True
            assert by_cid[cids[1]]["client_type"] == "project"
            assert by_cid[cids[2]]["client_type"] == "project"
            # Summary.
            # avg_ltv_recurring = 6000 (only one recurring customer).
            assert res["summary"]["avg_ltv_recurring"] == 6000.0
            # avg_ltv_project = (1500 + 200) / 2 = 850.
            assert res["summary"]["avg_ltv_project"] == 850.0
            # top_10_pct: 3 rows × 10% = ceil(0.3) = 1 → top 1
            # collected / total = 6000 / 7700 = ~77.9%.
            assert res["summary"]["top_10_pct_revenue_share"] == 77.9
            assert res["summary"]["active_client_count"] == 3
            # Histogram — one row per bucket, in canonical order.
            buckets = {b["bucket"]: b["count"] for b in res["chart"]["ltv_buckets"]}
            assert buckets["$0-500"] == 1
            assert buckets["$1K-2.5K"] == 1
            assert buckets["$5K+"] == 1
        finally:
            await db.customers.delete_many({"tenant_id": tid})
            await db.quotes.delete_many({"tenant_id": tid})
            await db.jobs.delete_many({"tenant_id": tid})

    run_test(_go)


def test_clv_parity_with_lifetime_revenue_helper():
    """The new ``_client_lifetime_summary`` MUST agree with
    ``_lifetime_revenue_by_customer`` on the ``collected`` field
    per customer — otherwise Attrition and CLV would drift."""
    from routers.analytics import (
        _client_lifetime_summary, _lifetime_revenue_by_customer,
    )
    invoices = [
        {"customer_id": "c1", "total": 100, "payment_status": "paid",
         "title": "Weekly"},
        {"customer_id": "c1", "total": 50,  "payment_status": "unpaid",
         "title": "Deck"},
        {"customer_id": "c2", "total": 200, "payment_status": "paid",
         "title": "Deck"},
    ]
    ltv = _lifetime_revenue_by_customer(invoices)
    summary = _client_lifetime_summary(invoices)
    # Parity — ``collected`` == ``_lifetime_revenue_by_customer`` output.
    for cid in ltv:
        assert summary[cid]["collected"] == ltv[cid]


def test_clv_windowed_mode_filters_invoices():
    from routers import reports_client_lifetime_value as clv

    async def _go(db):
        tid = new_id()
        cid = new_id()
        await db.customers.insert_one({
            "id": cid, "tenant_id": tid, "name": "Windowed Willy",
            "is_active": True,
        })
        await db.quotes.insert_many([
            {"id": "in", "tenant_id": tid, "doc_type": "invoice",
             "customer_id": cid, "title": "Monthly", "total": 100,
             "payment_status": "paid",
             "created_at": "2026-02-15T00:00:00+00:00"},
            {"id": "out", "tenant_id": tid, "doc_type": "invoice",
             "customer_id": cid, "title": "Monthly", "total": 999,
             "payment_status": "paid",
             "created_at": "2025-09-15T00:00:00+00:00"},
        ])
        try:
            res = await clv.client_lifetime_value(
                start_date="2026-02-01", end_date="2026-02-28",
                tenant_id=None,
                user={"id": "u", "role": "admin"}, tenant={"id": tid},
            )
            by = {r["customer_id"]: r for r in res["rows"]}
            assert by[cid]["total_collected"] == 100.0
        finally:
            await db.customers.delete_many({"tenant_id": tid})
            await db.quotes.delete_many({"tenant_id": tid})

    run_test(_go)


def test_clv_rejects_tenant_override_for_non_super_admin():
    from fastapi import HTTPException
    from routers import reports_client_lifetime_value as clv

    async def _go(_db):
        try:
            await clv.client_lifetime_value(
                start_date=None, end_date=None, tenant_id="OTHER",
                user={"id": "u", "role": "admin"}, tenant={"id": "MINE"},
            )
            assert False
        except HTTPException as exc:
            assert exc.status_code == 403

    run_test(_go)


def test_clv_only_one_of_start_end_provided_400():
    from fastapi import HTTPException
    from routers import reports_client_lifetime_value as clv

    async def _go(_db):
        try:
            await clv.client_lifetime_value(
                start_date="2026-02-01", end_date=None, tenant_id=None,
                user={"id": "u", "role": "admin"}, tenant={"id": "T"},
            )
            assert False
        except HTTPException as exc:
            assert exc.status_code == 400

    run_test(_go)
