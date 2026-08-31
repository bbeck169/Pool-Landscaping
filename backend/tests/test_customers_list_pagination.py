"""Phase F3.5 · Feb-2026 — /api/customers pagination shape tests."""
from __future__ import annotations

import uuid

from tests._f7_loop_fixture import run_test


async def _seed(db):
    tenant = await db.tenants.find_one({"slug": "aquaterra"},
                                         {"_id": 0, "id": 1})
    tid = tenant["id"]
    admin = await db.users.find_one({"email": "admin@aquaterra.com"},
                                     {"_id": 0, "id": 1, "role": 1})
    return tid, admin


async def _cleanup(db, tid, prefix):
    await db.customers.delete_many({"tenant_id": tid,
                                       "name": {"$regex": f"^{prefix}"}})


def test_f35_paginated_envelope_shape():
    from routers.customers import list_customers

    async def _go(db):
        tid, admin = await _seed(db)
        prefix = "TEST_F35P_" + uuid.uuid4().hex[:6] + "_"
        await _cleanup(db, tid, prefix)
        # Seed 12 customers so we can verify page shape.
        for i in range(12):
            await db.customers.insert_one({
                "id": f"{prefix}{i:02d}", "tenant_id": tid,
                "name": f"{prefix}{i:02d}",
                "email": f"{prefix}{i:02d}@example.com",
                "is_active": True,
                "created_at": f"2026-02-05T00:00:{i:02d}Z",
            })
        try:
            page1 = await list_customers(
                user=admin, tenant={"id": tid},
                page=1, page_size=5,
                tags=[],
            )
            assert isinstance(page1, dict)
            assert "items" in page1 and "total" in page1
            assert "page" in page1 and "page_size" in page1
            assert "total_pages" in page1
            assert page1["page"] == 1
            assert page1["page_size"] == 5
            assert page1["total"] >= 12
            assert len(page1["items"]) == 5

            page3 = await list_customers(
                user=admin, tenant={"id": tid},
                page=3, page_size=5,
                tags=[],
            )
            assert page3["page"] == 3
            # 12 seeded + preview extras; total_pages >= ceil(12 / 5) = 3.
            assert page3["total_pages"] >= 3
        finally:
            await _cleanup(db, tid, prefix)

    run_test(_go)


def test_f35_pagination_is_tenant_scoped():
    from routers.customers import list_customers

    async def _go(db):
        tid, admin = await _seed(db)
        other_tid = "TEST_F35_OTHER_" + uuid.uuid4().hex[:6]
        prefix = "TEST_F35I_" + uuid.uuid4().hex[:6] + "_"
        await _cleanup(db, tid, prefix)
        # Seed 1 row in the caller's tenant + 3 rows in another tenant.
        await db.customers.insert_one({
            "id": f"{prefix}mine", "tenant_id": tid,
            "name": f"{prefix}mine", "is_active": True,
        })
        for i in range(3):
            await db.customers.insert_one({
                "id": f"{prefix}other_{i}", "tenant_id": other_tid,
                "name": f"{prefix}other_{i}", "is_active": True,
            })
        try:
            res = await list_customers(
                user=admin, tenant={"id": tid},
                page=1, page_size=500,
                search=prefix,
                tags=[],
            )
            ids = {c["id"] for c in res["items"]}
            assert f"{prefix}mine" in ids
            for i in range(3):
                assert f"{prefix}other_{i}" not in ids
        finally:
            await _cleanup(db, tid, prefix)
            await db.customers.delete_many({"tenant_id": other_tid})

    run_test(_go)
