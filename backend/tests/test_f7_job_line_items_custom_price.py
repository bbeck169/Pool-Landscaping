"""Phase F7 · Feb-2026 — Custom-price override on job line items."""
from __future__ import annotations

import uuid

from tests._f7_loop_fixture import run_test


async def _seed(db, pb_price=100.0):
    tenant = await db.tenants.find_one({"slug": "aquaterra"},
                                         {"_id": 0, "id": 1})
    tid = tenant["id"]
    admin = await db.users.find_one({"email": "admin@aquaterra.com"},
                                     {"_id": 0, "id": 1, "role": 1, "email": 1})
    tech = await db.users.find_one({"email": "mike@aquaterra.com"},
                                     {"_id": 0, "id": 1, "role": 1, "email": 1,
                                      "technician_id": 1})
    tech_id = tech.get("technician_id") or tech.get("id")
    pb_id = "TEST_F7_PRICE_" + uuid.uuid4().hex[:8]
    await db.items.insert_one({
        "id": pb_id, "tenant_id": tid, "name": "TEST_F7_price_item",
        "category": "Repair", "unit_price": pb_price, "active": True,
    })
    job_id = "TEST_F7_PRICE_JOB_" + uuid.uuid4().hex[:8]
    await db.jobs.insert_one({
        "id": job_id, "tenant_id": tid, "customer_id": "x",
        "title": "TEST_F7", "status": "scheduled",
        "technician_id": tech_id, "line_items": [],
    })
    return tid, admin, tech, pb_id, job_id


async def _cleanup(db, tid, pb_id, job_id):
    await db.items.delete_one({"id": pb_id})
    await db.jobs.delete_one({"id": job_id})


def test_f7_add_with_custom_price_sets_flag_and_subtotal():
    from routers.job_media_line_items import add_line_item, LineItemIn

    async def _go(db):
        tid, admin, _tech, pb_id, job_id = await _seed(db, pb_price=100.0)
        try:
            out = await add_line_item(
                jid=job_id,
                body=LineItemIn(pricebook_item_id=pb_id, quantity=2,
                                 unit_price=75.0),
                user=admin, tenant={"id": tid},
            )
            assert out["unit_price"] == 75.0
            assert out["custom_price_override_flag"] is True
            assert out["subtotal"] == 150.0
        finally:
            await _cleanup(db, tid, pb_id, job_id)

    run_test(_go)


def test_f7_add_without_custom_price_flag_is_false():
    from routers.job_media_line_items import add_line_item, LineItemIn

    async def _go(db):
        tid, admin, _tech, pb_id, job_id = await _seed(db, pb_price=100.0)
        try:
            out = await add_line_item(
                jid=job_id,
                body=LineItemIn(pricebook_item_id=pb_id, quantity=1),
                user=admin, tenant={"id": tid},
            )
            assert out["unit_price"] == 100.0
            assert out["custom_price_override_flag"] is False
            assert out["subtotal"] == 100.0
        finally:
            await _cleanup(db, tid, pb_id, job_id)

    run_test(_go)


def test_f7_admin_patch_unit_price_flips_flag():
    from routers.job_media_line_items import (
        add_line_item, patch_line_item, LineItemIn, LineItemPatch,
    )

    async def _go(db):
        tid, admin, _tech, pb_id, job_id = await _seed(db, pb_price=100.0)
        try:
            row = await add_line_item(
                jid=job_id,
                body=LineItemIn(pricebook_item_id=pb_id, quantity=2),
                user=admin, tenant={"id": tid},
            )
            assert row["custom_price_override_flag"] is False
            updated = await patch_line_item(
                jid=job_id, lid=row["id"],
                body=LineItemPatch(unit_price=80.0),
                user=admin, tenant={"id": tid},
            )
            assert updated["unit_price"] == 80.0
            assert updated["custom_price_override_flag"] is True
            assert updated["subtotal"] == 160.0
        finally:
            await _cleanup(db, tid, pb_id, job_id)

    run_test(_go)


def test_f7_tech_patch_unit_price_is_dropped():
    """Tech never writes price server-side."""
    from routers.job_media_line_items import (
        add_line_item, patch_line_item, LineItemIn, LineItemPatch,
    )

    async def _go(db):
        tid, admin, tech, pb_id, job_id = await _seed(db, pb_price=100.0)
        try:
            row = await add_line_item(
                jid=job_id,
                body=LineItemIn(pricebook_item_id=pb_id, quantity=1),
                user=tech, tenant={"id": tid},
            )
            updated = await patch_line_item(
                jid=job_id, lid=row["id"],
                body=LineItemPatch(unit_price=1.0),
                user=tech, tenant={"id": tid},
            )
            stored = await db.jobs.find_one(
                {"id": job_id}, {"_id": 0, "line_items": 1},
            )
            li = next(x for x in stored["line_items"] if x["id"] == row["id"])
            assert li["unit_price"] == 100.0
            assert li.get("custom_price_override_flag") is False
            assert "unit_price" not in updated
        finally:
            await _cleanup(db, tid, pb_id, job_id)

    run_test(_go)
