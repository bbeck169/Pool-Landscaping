"""Phase F6c · Feb-2026 — /api/customers ?is_active filter tests.

Audit outcome: the backend is NOT a silent no-op.  ``is_active`` is
declared, plumbed, and honored (see routers/customers.py:367-388).
These tests pin the contract so any future regression trips loudly.
"""
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


def test_f6c_is_active_true_returns_only_active():
    from routers.customers import list_customers

    async def _go(db):
        tid, admin = await _seed(db)
        prefix = "TEST_F6C_A_" + uuid.uuid4().hex[:6] + "_"
        await _cleanup(db, tid, prefix)
        # 3 active + 2 inactive + 1 legacy field-missing (Phase 34f
        # semantics: missing = active).
        for i in range(3):
            await db.customers.insert_one({
                "id": f"{prefix}on_{i}", "tenant_id": tid,
                "name": f"{prefix}on_{i}", "is_active": True,
            })
        for i in range(2):
            await db.customers.insert_one({
                "id": f"{prefix}off_{i}", "tenant_id": tid,
                "name": f"{prefix}off_{i}", "is_active": False,
            })
        await db.customers.insert_one({
            "id": f"{prefix}legacy", "tenant_id": tid,
            "name": f"{prefix}legacy",
            # note: no ``is_active`` field at all.
        })
        try:
            res = await list_customers(
                user=admin, tenant={"id": tid},
                page=1, page_size=100,
                is_active=True, search=prefix, tags=[],
            )
            names = {c["name"] for c in res["items"]}
            # 3 explicit True + 1 field-missing = 4.
            assert len(names) == 4, (
                f"expected 4 active rows, got {sorted(names)}"
            )
            assert not any("off_" in n for n in names)
        finally:
            await _cleanup(db, tid, prefix)

    run_test(_go)


def test_f6c_is_active_false_returns_only_inactive():
    from routers.customers import list_customers

    async def _go(db):
        tid, admin = await _seed(db)
        prefix = "TEST_F6C_B_" + uuid.uuid4().hex[:6] + "_"
        await _cleanup(db, tid, prefix)
        for i in range(3):
            await db.customers.insert_one({
                "id": f"{prefix}on_{i}", "tenant_id": tid,
                "name": f"{prefix}on_{i}", "is_active": True,
            })
        for i in range(2):
            await db.customers.insert_one({
                "id": f"{prefix}off_{i}", "tenant_id": tid,
                "name": f"{prefix}off_{i}", "is_active": False,
            })
        try:
            res = await list_customers(
                user=admin, tenant={"id": tid},
                page=1, page_size=100,
                is_active=False, search=prefix, tags=[],
            )
            names = {c["name"] for c in res["items"]}
            assert len(names) == 2
            assert all("off_" in n for n in names)
        finally:
            await _cleanup(db, tid, prefix)

    run_test(_go)


def test_f6c_no_param_returns_all():
    from routers.customers import list_customers

    async def _go(db):
        tid, admin = await _seed(db)
        prefix = "TEST_F6C_ALL_" + uuid.uuid4().hex[:6] + "_"
        await _cleanup(db, tid, prefix)
        for i in range(3):
            await db.customers.insert_one({
                "id": f"{prefix}on_{i}", "tenant_id": tid,
                "name": f"{prefix}on_{i}", "is_active": True,
            })
        for i in range(2):
            await db.customers.insert_one({
                "id": f"{prefix}off_{i}", "tenant_id": tid,
                "name": f"{prefix}off_{i}", "is_active": False,
            })
        try:
            res = await list_customers(
                user=admin, tenant={"id": tid},
                page=1, page_size=100,
                is_active=None, search=prefix, tags=[],
            )
            names = {c["name"] for c in res["items"]}
            assert len(names) == 5
        finally:
            await _cleanup(db, tid, prefix)

    run_test(_go)


def test_f6c_is_active_is_tenant_scoped():
    from routers.customers import list_customers

    async def _go(db):
        tid, admin = await _seed(db)
        other_tid = "TEST_F6C_OTHER_" + uuid.uuid4().hex[:6]
        prefix = "TEST_F6C_ISO_" + uuid.uuid4().hex[:6] + "_"
        await _cleanup(db, tid, prefix)
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
                page=1, page_size=100,
                is_active=True, search=prefix, tags=[],
            )
            ids = {c["id"] for c in res["items"]}
            assert f"{prefix}mine" in ids
            for i in range(3):
                assert f"{prefix}other_{i}" not in ids
        finally:
            await _cleanup(db, tid, prefix)
            await db.customers.delete_many({"tenant_id": other_tid})

    run_test(_go)


def test_f6c_is_active_combines_with_pagination_and_search():
    from routers.customers import list_customers

    async def _go(db):
        tid, admin = await _seed(db)
        prefix = "TEST_F6C_P_" + uuid.uuid4().hex[:6] + "_"
        await _cleanup(db, tid, prefix)
        for i in range(12):
            await db.customers.insert_one({
                "id": f"{prefix}on_{i:02d}", "tenant_id": tid,
                "name": f"{prefix}on_{i:02d}", "is_active": True,
            })
        for i in range(3):
            await db.customers.insert_one({
                "id": f"{prefix}off_{i:02d}", "tenant_id": tid,
                "name": f"{prefix}off_{i:02d}", "is_active": False,
            })
        try:
            # Search + is_active + pagination all stack.
            page1 = await list_customers(
                user=admin, tenant={"id": tid},
                page=1, page_size=5,
                is_active=True, search=prefix, tags=[],
            )
            assert page1["page"] == 1
            assert page1["page_size"] == 5
            assert page1["total"] == 12
            assert len(page1["items"]) == 5
            page2 = await list_customers(
                user=admin, tenant={"id": tid},
                page=2, page_size=5,
                is_active=True, search=prefix, tags=[],
            )
            assert page2["page"] == 2
            assert len(page2["items"]) == 5
        finally:
            await _cleanup(db, tid, prefix)

    run_test(_go)
