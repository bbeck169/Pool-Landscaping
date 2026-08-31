"""Phase F7 · Feb-2026 — Pricebook writeback from job line items."""
from __future__ import annotations

import uuid

from tests._f7_loop_fixture import run_test


async def _seed(db):
    tenant = await db.tenants.find_one({"slug": "aquaterra"},
                                         {"_id": 0, "id": 1})
    tid = tenant["id"]
    admin = await db.users.find_one({"email": "admin@aquaterra.com"},
                                     {"_id": 0, "id": 1, "role": 1, "email": 1})
    pb_id = "TEST_F7_WB_" + uuid.uuid4().hex[:8]
    await db.items.insert_one({
        "id": pb_id, "tenant_id": tid, "name": "TEST_F7_wb_item",
        "category": "Repair", "unit_price": 50.0, "active": True,
    })
    job_id = "TEST_F7_WB_JOB_" + uuid.uuid4().hex[:8]
    await db.jobs.insert_one({
        "id": job_id, "tenant_id": tid, "customer_id": "x",
        "title": "TEST_F7_wb", "status": "scheduled", "line_items": [],
    })
    return tid, admin, pb_id, job_id


async def _cleanup(db, tid, pb_id, job_id):
    await db.items.delete_one({"id": pb_id})
    await db.jobs.delete_one({"id": job_id})
    await db.pricebook_writeback_events.delete_many(
        {"tenant_id": tid, "invoice_id": job_id},
    )


def test_f7_add_with_writeback_flag_fires_event():
    from routers.job_media_line_items import add_line_item, LineItemIn

    async def _go(db):
        tid, admin, pb_id, job_id = await _seed(db)
        try:
            out = await add_line_item(
                jid=job_id,
                body=LineItemIn(
                    pricebook_item_id=pb_id, quantity=1,
                    unit_price=75.0,
                    pricebook_writeback=True,
                ),
                user=admin, tenant={"id": tid},
            )
            assert out["pricebook_writeback_flag"] is True
            events = await db.pricebook_writeback_events.find(
                {"tenant_id": tid, "invoice_id": job_id},
            ).to_list(10)
            assert len(events) >= 1, (
                f"expected ≥1 writeback event for job={job_id}, got {events}"
            )
            pb = await db.items.find_one({"id": pb_id},
                                          {"_id": 0, "unit_price": 1})
            assert float(pb["unit_price"]) == 75.0
        finally:
            await _cleanup(db, tid, pb_id, job_id)

    run_test(_go)


def test_f7_add_without_writeback_flag_no_event():
    from routers.job_media_line_items import add_line_item, LineItemIn

    async def _go(db):
        tid, admin, pb_id, job_id = await _seed(db)
        try:
            await add_line_item(
                jid=job_id,
                body=LineItemIn(
                    pricebook_item_id=pb_id, quantity=1,
                    unit_price=42.0,
                ),
                user=admin, tenant={"id": tid},
            )
            events = await db.pricebook_writeback_events.find(
                {"tenant_id": tid, "invoice_id": job_id},
            ).to_list(10)
            assert events == []
        finally:
            await _cleanup(db, tid, pb_id, job_id)

    run_test(_go)


def test_f7_patch_flip_writeback_fires_event():
    from routers.job_media_line_items import (
        add_line_item, patch_line_item, LineItemIn, LineItemPatch,
    )

    async def _go(db):
        tid, admin, pb_id, job_id = await _seed(db)
        try:
            row = await add_line_item(
                jid=job_id,
                body=LineItemIn(pricebook_item_id=pb_id, quantity=1,
                                 unit_price=60.0),
                user=admin, tenant={"id": tid},
            )
            assert row["pricebook_writeback_flag"] is False
            await patch_line_item(
                jid=job_id, lid=row["id"],
                body=LineItemPatch(pricebook_writeback=True),
                user=admin, tenant={"id": tid},
            )
            events = await db.pricebook_writeback_events.find(
                {"tenant_id": tid, "invoice_id": job_id},
            ).to_list(10)
            assert len(events) >= 1
        finally:
            await _cleanup(db, tid, pb_id, job_id)

    run_test(_go)
