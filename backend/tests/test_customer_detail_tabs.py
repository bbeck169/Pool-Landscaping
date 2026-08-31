"""Phase F3.5 · Feb-2026 — customer detail tabs are backed by
customer-scoped API paths (no more tenant-wide job fetch)."""
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


async def _cleanup(db, tid, cid):
    await db.customers.delete_many({"id": cid})
    await db.jobs.delete_many({"tenant_id": tid, "customer_id": cid})


def test_f35_jobs_endpoint_honours_customer_id_filter():
    from routers.jobs import list_jobs

    async def _go(db):
        tid, admin = await _seed(db)
        cid = "TEST_F35C_" + uuid.uuid4().hex[:8]
        other_cid = "TEST_F35O_" + uuid.uuid4().hex[:8]
        await _cleanup(db, tid, cid)
        await _cleanup(db, tid, other_cid)
        await db.customers.insert_many([
            {"id": cid, "tenant_id": tid, "name": "test cust A"},
            {"id": other_cid, "tenant_id": tid, "name": "test cust B"},
        ])
        for i in range(3):
            await db.jobs.insert_one({
                "id": f"F35J_A_{i}", "tenant_id": tid, "customer_id": cid,
                "status": "scheduled",
                "scheduled_date": f"2026-02-0{i+1}T09:00:00+00:00",
                "created_at": f"2026-02-0{i+1}T09:00:00+00:00",
            })
        for i in range(4):
            await db.jobs.insert_one({
                "id": f"F35J_B_{i}", "tenant_id": tid,
                "customer_id": other_cid, "status": "scheduled",
                "scheduled_date": f"2026-02-0{i+1}T09:00:00+00:00",
                "created_at": f"2026-02-0{i+1}T09:00:00+00:00",
            })
        try:
            res_a = await list_jobs(
                user=admin, tenant={"id": tid},
                status=None, technician_id=None,
                customer_id=cid, crew_id=None,
                start=None, end=None,
                scheduled_date=None, recurring_template_id=None,
                limit=1000, include_deleted=False,
            )
            ids_a = {j["id"] for j in res_a}
            assert all(i.startswith("F35J_A_") for i in ids_a), \
                f"customer_id=cid returned foreign rows: {ids_a}"
            assert len(ids_a) == 3
            # And a call without the filter returns rows from BOTH customers
            # (verifying the filter is opt-in, not always-on).
            res_all = await list_jobs(
                user=admin, tenant={"id": tid},
                status=None, technician_id=None,
                customer_id=None, crew_id=None,
                start=None, end=None,
                scheduled_date=None, recurring_template_id=None,
                limit=1000, include_deleted=False,
            )
            all_ids = {j["id"] for j in res_all}
            assert any(i.startswith("F35J_A_") for i in all_ids)
            assert any(i.startswith("F35J_B_") for i in all_ids)
        finally:
            await _cleanup(db, tid, cid)
            await _cleanup(db, tid, other_cid)

    run_test(_go)


def test_f35_customer_role_cannot_read_other_customers_jobs():
    """A ``role=customer`` user can never widen ``customer_id`` past
    their own row — verifies the F3.5 defence-in-depth check."""
    from fastapi import HTTPException
    from routers.jobs import list_jobs

    async def _go(db):
        tid, _admin = await _seed(db)
        # Fake customer user for tenant A
        cust_user = {
            "id": "cust-A", "role": "customer",
            "customer_id": "F35_CUST_A",
            "tenant_id": tid,
        }
        try:
            await list_jobs(
                user=cust_user, tenant={"id": tid},
                status=None, technician_id=None,
                customer_id="F35_CUST_B", crew_id=None,
                start=None, end=None,
                scheduled_date=None, recurring_template_id=None,
                limit=1000, include_deleted=False,
            )
            raise AssertionError("expected 403 for cross-customer read")
        except HTTPException as e:
            assert e.status_code == 403

    run_test(_go)


def test_f35_perf_customers_migration_is_idempotent():
    from services.migrations.perf_customers_indexes import run

    async def _go(db):
        # Reset sentinel so this test always exercises the fresh path.
        await db.migration_status.delete_many({"key": "perf_customers_v1"})
        first = await run(db)
        assert first["ok"] is True
        # Second run must be a no-op.
        second = await run(db)
        assert second["skipped"] is True
        assert second["reason"] == "already_ran"

    run_test(_go)
