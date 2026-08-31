"""Phase F7 · Feb-2026 — auto_invoice pricebook writeback fan-out."""
from __future__ import annotations

import uuid

from tests._f7_loop_fixture import run_test


def test_f7_auto_invoice_writeback_fires_when_flag_set():
    from services.auto_invoice import create_invoice_from_job

    async def _go(db):
        tenant = await db.tenants.find_one({"slug": "aquaterra"},
                                             {"_id": 0, "id": 1})
        tid = tenant["id"]
        pb_id = "TEST_F7_AI_WB_" + uuid.uuid4().hex[:8]
        await db.items.insert_one({
            "id": pb_id, "tenant_id": tid,
            "name": "TEST_F7_ai_wb_item",
            "category": "Repair",
            "unit_price": 50.0, "active": True,
        })
        job_id = "TEST_F7_AI_WB_JOB_" + uuid.uuid4().hex[:8]
        await db.jobs.insert_one({
            "id": job_id, "tenant_id": tid,
            "customer_id": "x", "customer_name": "TEST_F7",
            "title": "TEST_F7_ai_wb", "status": "in_progress",
            "line_items": [{
                "id": "li-wb", "pricebook_item_id": pb_id,
                "name": "TEST_F7_ai_wb_item", "description": "wb line",
                "quantity": 1, "unit_price": 88.0, "subtotal": 88.0,
                "category": "Repair",
                "custom_price_override_flag": True,
                "pricebook_writeback_flag": True,
            }],
        })
        out = {"ok": False}
        try:
            out = await create_invoice_from_job(job_id, tid)
            assert out["ok"], out
            assert out["created"] is True

            events = await db.pricebook_writeback_events.find(
                {"tenant_id": tid, "invoice_id": out["invoice_id"]},
            ).to_list(10)
            assert len(events) >= 1, (
                f"expected ≥1 writeback event on invoice={out['invoice_id']}, "
                f"got {events}"
            )

            pb = await db.items.find_one(
                {"id": pb_id}, {"_id": 0, "unit_price": 1},
            )
            assert float(pb["unit_price"]) == 88.0
        finally:
            await db.items.delete_one({"id": pb_id})
            await db.jobs.delete_one({"id": job_id})
            if out.get("invoice_id"):
                await db.quotes.delete_one({"id": out["invoice_id"]})
                await db.pricebook_writeback_events.delete_many(
                    {"tenant_id": tid, "invoice_id": out["invoice_id"]},
                )
                await db.auto_invoice_runs.delete_many({"job_id": job_id})

    run_test(_go)


def test_f7_auto_invoice_writeback_does_not_fire_when_no_flag():
    from services.auto_invoice import create_invoice_from_job

    async def _go(db):
        tenant = await db.tenants.find_one({"slug": "aquaterra"},
                                             {"_id": 0, "id": 1})
        tid = tenant["id"]
        pb_id = "TEST_F7_AI_NWB_" + uuid.uuid4().hex[:8]
        await db.items.insert_one({
            "id": pb_id, "tenant_id": tid,
            "name": "TEST_F7_ai_nwb_item",
            "category": "Repair", "unit_price": 30.0, "active": True,
        })
        job_id = "TEST_F7_AI_NWB_JOB_" + uuid.uuid4().hex[:8]
        await db.jobs.insert_one({
            "id": job_id, "tenant_id": tid,
            "customer_id": "x", "customer_name": "TEST_F7",
            "title": "TEST_F7_ai_nwb", "status": "in_progress",
            "line_items": [{
                "id": "li-nwb", "pricebook_item_id": pb_id,
                "name": "TEST_F7_ai_nwb_item", "description": "no wb",
                "quantity": 1, "unit_price": 45.0, "subtotal": 45.0,
                "category": "Repair",
                "pricebook_writeback_flag": False,
            }],
        })
        out = {"ok": False}
        try:
            out = await create_invoice_from_job(job_id, tid)
            assert out["ok"], out
            events = await db.pricebook_writeback_events.find(
                {"tenant_id": tid, "invoice_id": out["invoice_id"]},
            ).to_list(10)
            assert events == []
        finally:
            await db.items.delete_one({"id": pb_id})
            await db.jobs.delete_one({"id": job_id})
            if out.get("invoice_id"):
                await db.quotes.delete_one({"id": out["invoice_id"]})
                await db.auto_invoice_runs.delete_many({"job_id": job_id})

    run_test(_go)
