"""Phase F7 · Feb-2026 — Job line-items category validation."""
from __future__ import annotations

import uuid

import pytest

from tests._f7_loop_fixture import run_test


async def _seed(db):
    tenant = await db.tenants.find_one({"slug": "aquaterra"}, {"_id": 0, "id": 1})
    tid = tenant["id"]
    admin = await db.users.find_one({"email": "admin@aquaterra.com"},
                                     {"_id": 0, "id": 1, "role": 1, "email": 1})
    pb_id = "TEST_F7_CAT_" + uuid.uuid4().hex[:8]
    await db.items.insert_one({
        "id": pb_id, "tenant_id": tid, "name": "TEST_F7_cat_item",
        "category": "Repair", "unit": "each", "unit_price": 50.0,
        "taxable": False, "active": True,
    })
    job_id = "TEST_F7_JOB_" + uuid.uuid4().hex[:8]
    await db.jobs.insert_one({
        "id": job_id, "tenant_id": tid,
        "customer_id": "no-cust", "customer_name": "TEST_F7",
        "title": "TEST_F7", "status": "scheduled",
        "service_type": "Repair", "line_items": [],
    })
    return tid, admin, pb_id, job_id


async def _cleanup(db, tid, pb_id, job_id):
    await db.items.delete_one({"id": pb_id, "tenant_id": tid})
    await db.jobs.delete_one({"id": job_id, "tenant_id": tid})


def test_f7_add_with_archived_category_returns_4xx():
    from fastapi import HTTPException
    from routers.job_media_line_items import add_line_item, LineItemIn

    async def _go(db):
        tid, admin, pb_id, job_id = await _seed(db)
        try:
            body = LineItemIn(
                pricebook_item_id=pb_id, quantity=1,
                category=f"TEST_F7_ARCHIVED_{uuid.uuid4().hex[:5]}",
            )
            with pytest.raises(HTTPException) as ei:
                await add_line_item(
                    jid=job_id, body=body,
                    user=admin, tenant={"id": tid},
                )
            detail = ei.value.detail
            assert ei.value.status_code == 400
            assert detail["error_code"] == "archived_category"
            assert detail["line_index"] == 0
            assert detail["attempted_category"].startswith("TEST_F7_ARCHIVED_")
            assert "available_categories" in detail
            assert detail["field"] == "line_items[0].category"
        finally:
            await _cleanup(db, tid, pb_id, job_id)

    run_test(_go)


def test_f7_patch_with_archived_category_returns_4xx():
    from fastapi import HTTPException
    from routers.job_media_line_items import (
        add_line_item, patch_line_item, LineItemIn, LineItemPatch,
    )

    async def _go(db):
        tid, admin, pb_id, job_id = await _seed(db)
        try:
            good = await add_line_item(
                jid=job_id,
                body=LineItemIn(pricebook_item_id=pb_id, quantity=1,
                                 category="Repair"),
                user=admin, tenant={"id": tid},
            )
            lid = good["id"]
            with pytest.raises(HTTPException) as ei:
                await patch_line_item(
                    jid=job_id, lid=lid,
                    body=LineItemPatch(
                        category=f"TEST_F7_BAD_{uuid.uuid4().hex[:5]}",
                    ),
                    user=admin, tenant={"id": tid},
                )
            detail = ei.value.detail
            assert ei.value.status_code == 400
            assert detail["error_code"] == "archived_category"
            assert detail["line_index"] == 0
        finally:
            await _cleanup(db, tid, pb_id, job_id)

    run_test(_go)


def test_f7_add_without_category_is_allowed_when_pricebook_lacks_one():
    """Uncategorised is not fatal for job lines."""
    from routers.job_media_line_items import add_line_item, LineItemIn

    async def _go(db):
        tenant = await db.tenants.find_one({"slug": "aquaterra"},
                                             {"_id": 0, "id": 1})
        tid = tenant["id"]
        admin = await db.users.find_one({"email": "admin@aquaterra.com"},
                                          {"_id": 0, "id": 1, "role": 1,
                                           "email": 1})
        pb_id = "TEST_F7_NOCAT_" + uuid.uuid4().hex[:8]
        await db.items.insert_one({
            "id": pb_id, "tenant_id": tid,
            "name": "TEST_F7_nocat_item",
            "unit_price": 25.0, "active": True,
        })
        job_id = "TEST_F7_NOCAT_JOB_" + uuid.uuid4().hex[:8]
        await db.jobs.insert_one({
            "id": job_id, "tenant_id": tid,
            "customer_id": "x", "title": "TEST_F7_nocat",
            "status": "scheduled", "line_items": [],
        })
        try:
            out = await add_line_item(
                jid=job_id,
                body=LineItemIn(pricebook_item_id=pb_id, quantity=1),
                user=admin, tenant={"id": tid},
            )
            assert out["category"] is None
        finally:
            await db.items.delete_one({"id": pb_id})
            await db.jobs.delete_one({"id": job_id})

    run_test(_go)
