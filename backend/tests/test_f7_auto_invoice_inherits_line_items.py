"""Phase F7 · Feb-2026 — auto_invoice inherits job.line_items[]."""
from __future__ import annotations

import uuid

from tests._f7_loop_fixture import run_test


def test_f7_auto_invoice_inherits_job_line_items():
    from services.auto_invoice import create_invoice_from_job

    async def _go(db):
        tenant = await db.tenants.find_one({"slug": "aquaterra"},
                                             {"_id": 0, "id": 1})
        tid = tenant["id"]
        pb_id = "TEST_F7_AI_" + uuid.uuid4().hex[:8]
        await db.items.insert_one({
            "id": pb_id, "tenant_id": tid, "name": "TEST_F7_ai_item",
            "category": "Repair", "unit_price": 50.0, "active": True,
        })
        job_id = "TEST_F7_AI_JOB_" + uuid.uuid4().hex[:8]
        job_lines = [
            {
                "id": "li-a", "pricebook_item_id": pb_id,
                "name": "TEST_F7_line_A", "description": "line A",
                "quantity": 2, "unit_price": 75.0, "subtotal": 150.0,
                "category": "Repair",
                "custom_price_override_flag": True,
                "pricebook_writeback_flag": False,
            },
            {
                "id": "li-b", "pricebook_item_id": pb_id,
                "name": "TEST_F7_line_B", "description": "line B",
                "quantity": 3, "unit_price": 20.0, "subtotal": 60.0,
                "category": "Repair",
                "custom_price_override_flag": False,
                "pricebook_writeback_flag": False,
            },
        ]
        await db.jobs.insert_one({
            "id": job_id, "tenant_id": tid,
            "customer_id": "x", "customer_name": "TEST_F7",
            "title": "TEST_F7_ai", "status": "in_progress",
            "line_items": job_lines,
            "price": 999.0,   # legacy — must be IGNORED
        })
        out = {"ok": False}
        try:
            out = await create_invoice_from_job(job_id, tid)
            assert out["ok"], out
            assert out["created"] is True
            assert out["amount_cents"] == 21000, out

            invoice = await db.quotes.find_one(
                {"id": out["invoice_id"]}, {"_id": 0},
            )
            assert invoice is not None
            assert invoice["source"] == "auto_invoice_on_job_complete"
            assert len(invoice["line_items"]) == 2
            assert invoice["line_items"][0]["description"] == "TEST_F7_line_A"
            assert invoice["line_items"][0]["unit_price_cents"] == 7500
            assert invoice["line_items"][0]["line_total_cents"] == 15000
            assert invoice["line_items"][0]["category"] == "Repair"
            assert invoice["line_items"][0]["pricebook_item_id"] == pb_id
            assert invoice["line_items"][0]["kind"] == "job_line_item"
            assert invoice["line_items"][1]["line_total_cents"] == 6000
        finally:
            await db.items.delete_one({"id": pb_id})
            await db.jobs.delete_one({"id": job_id})
            if out.get("invoice_id"):
                await db.quotes.delete_one({"id": out["invoice_id"]})
                await db.auto_invoice_runs.delete_many({"job_id": job_id})

    run_test(_go)


def test_f7_auto_invoice_fallback_when_no_line_items():
    """Empty job.line_items[] → legacy path."""
    from services.auto_invoice import create_invoice_from_job

    async def _go(db):
        tenant = await db.tenants.find_one({"slug": "aquaterra"},
                                             {"_id": 0, "id": 1})
        tid = tenant["id"]
        job_id = "TEST_F7_FALLBACK_" + uuid.uuid4().hex[:8]
        await db.jobs.insert_one({
            "id": job_id, "tenant_id": tid,
            "customer_id": "x", "customer_name": "TEST_F7",
            "title": "TEST_F7_fallback", "status": "in_progress",
            "service_type": "Repair",
            "price": 42.50,
            "line_items": [],
        })
        out = {"ok": False}
        try:
            out = await create_invoice_from_job(job_id, tid)
            assert out["ok"], out
            assert out["created"] is True
            assert out["amount_cents"] == 4250

            invoice = await db.quotes.find_one(
                {"id": out["invoice_id"]}, {"_id": 0},
            )
            assert len(invoice["line_items"]) == 1
            assert invoice["line_items"][0]["kind"] == "service"
            assert invoice["line_items"][0]["unit_price_cents"] == 4250
        finally:
            await db.jobs.delete_one({"id": job_id})
            if out.get("invoice_id"):
                await db.quotes.delete_one({"id": out["invoice_id"]})
                await db.auto_invoice_runs.delete_many({"job_id": job_id})

    run_test(_go)
