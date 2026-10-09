"""Phase 9d · Feb-2026 — Customer profile lazy-tabs contract tests.

Locks:
    1. ``GET /api/customers/{cid}?slim=1`` returns core customer
       fields but OMITS the embedded ``jobs`` array (saves a jobs
       find + SR-photo-id enrichment per profile open).
    2. Non-slim ``GET /api/customers/{cid}`` STILL embeds the
       ``jobs`` array (regression lock — slim is strictly opt-in).
    3. ``GET /api/customers/{cid}/summary`` returns the 8-count
       snapshot shape (jobs / invoices / quotes / tasks /
       service_reports / notes / properties / open_invoices).
    4. Summary counts are tenant-scoped — tenant B's records never
       count toward tenant A's customer summary.
    5. Summary 404s cleanly for a missing / cross-tenant customer.
    6. Soft-deleted customer summary is 404 for non-super_admin
       and 409 for super_admin (parity with get_customer).
"""
from __future__ import annotations

import uuid

import pytest

from tests._f7_loop_fixture import run_test


async def _seed_fixtures(db, prefix):
    tenant = await db.tenants.find_one({"slug": "aquaterra"},
                                         {"_id": 0, "id": 1})
    admin = await db.users.find_one({"email": "admin@aquaterra.com"},
                                     {"_id": 0, "id": 1, "role": 1})
    return tenant["id"], admin


async def _cleanup(db, tid, prefix):
    await db.customers.delete_many({"tenant_id": tid,
                                      "id": {"$regex": f"^{prefix}"}})
    await db.jobs.delete_many({"tenant_id": tid,
                                "customer_id": {"$regex": f"^{prefix}"}})
    await db.quotes.delete_many({"tenant_id": tid,
                                   "customer_id": {"$regex": f"^{prefix}"}})
    await db.customer_tasks.delete_many(
        {"tenant_id": tid, "customer_id": {"$regex": f"^{prefix}"}})
    await db.service_reports.delete_many(
        {"tenant_id": tid, "customer_id": {"$regex": f"^{prefix}"}})
    await db.properties.delete_many(
        {"tenant_id": tid, "customer_id": {"$regex": f"^{prefix}"}})


# ═════════════════════════════════════════════════════════════════
# 1 · slim=1 omits the embedded jobs array
# ═════════════════════════════════════════════════════════════════
def test_9d_profile_slim_omits_embedded_jobs():
    from routers.customers import get_customer

    async def _go(db):
        prefix = "TEST_9D_SLIM_" + uuid.uuid4().hex[:6] + "_"
        tid, admin = await _seed_fixtures(db, prefix)
        cid = f"{prefix}CUST"
        await _cleanup(db, tid, prefix)
        await db.customers.insert_one({
            "id": cid, "tenant_id": tid,
            "name": f"{prefix}CUST", "is_active": True,
        })
        # Insert 2 jobs so the non-slim path would embed them.
        for i in range(2):
            await db.jobs.insert_one({
                "id": f"JOB_{prefix}{i:02d}",
                "tenant_id": tid, "customer_id": cid,
                "status": "pending", "scheduled_date": f"2026-03-0{i+1}",
            })
        try:
            slim_doc = await get_customer(
                cid=cid, user=admin, tenant={"id": tid},
                slim=True,
            )
            assert slim_doc["id"] == cid
            assert "jobs" not in slim_doc, (
                "slim=1 leaked the embedded jobs array"
            )
            # Core fields must still render — the UI consumes them.
            assert "name" in slim_doc
        finally:
            await _cleanup(db, tid, prefix)

    run_test(_go)


# ═════════════════════════════════════════════════════════════════
# 2 · Non-slim path STILL embeds jobs (regression lock)
# ═════════════════════════════════════════════════════════════════
def test_9d_profile_non_slim_regression_embeds_jobs():
    from routers.customers import get_customer

    async def _go(db):
        prefix = "TEST_9D_NONSLIM_" + uuid.uuid4().hex[:6] + "_"
        tid, admin = await _seed_fixtures(db, prefix)
        cid = f"{prefix}CUST"
        await _cleanup(db, tid, prefix)
        await db.customers.insert_one({
            "id": cid, "tenant_id": tid,
            "name": f"{prefix}CUST", "is_active": True,
        })
        await db.jobs.insert_one({
            "id": f"JOB_{prefix}00",
            "tenant_id": tid, "customer_id": cid,
            "status": "pending", "scheduled_date": "2026-03-01",
        })
        try:
            doc = await get_customer(
                cid=cid, user=admin, tenant={"id": tid},
                # slim NOT set — default False
            )
            assert "jobs" in doc, (
                "non-slim regression: embedded jobs array was dropped"
            )
            assert isinstance(doc["jobs"], list)
            assert len(doc["jobs"]) >= 1
        finally:
            await _cleanup(db, tid, prefix)

    run_test(_go)


# ═════════════════════════════════════════════════════════════════
# 3 · /summary returns the 8-count snapshot shape
# ═════════════════════════════════════════════════════════════════
def test_9d_summary_returns_eight_count_shape():
    from routers.customers import get_customer_summary

    async def _go(db):
        prefix = "TEST_9D_SUM_" + uuid.uuid4().hex[:6] + "_"
        tid, admin = await _seed_fixtures(db, prefix)
        cid = f"{prefix}CUST"
        await _cleanup(db, tid, prefix)
        await db.customers.insert_one({
            "id": cid, "tenant_id": tid,
            "name": f"{prefix}CUST", "is_active": True,
        })
        # Seed one of each: job, invoice, quote, task, service_report,
        # service report WITH notes, property, open invoice.
        await db.jobs.insert_one({
            "id": f"JOB_{prefix}", "tenant_id": tid, "customer_id": cid,
        })
        await db.quotes.insert_many([
            {"id": f"INV_{prefix}", "tenant_id": tid, "customer_id": cid,
             "doc_type": "invoice", "status": "paid"},
            {"id": f"QT_{prefix}", "tenant_id": tid, "customer_id": cid,
             "doc_type": "quote", "status": "draft"},
            {"id": f"OINV_{prefix}", "tenant_id": tid, "customer_id": cid,
             "doc_type": "invoice", "status": "sent"},
        ])
        await db.customer_tasks.insert_one({
            "id": f"TASK_{prefix}", "tenant_id": tid, "customer_id": cid,
        })
        await db.service_reports.insert_many([
            {"id": f"SR_{prefix}", "tenant_id": tid, "customer_id": cid},
            {"id": f"SRN_{prefix}", "tenant_id": tid, "customer_id": cid,
             "notes": "chlorine was low"},
        ])
        await db.properties.insert_one({
            "id": f"PROP_{prefix}", "tenant_id": tid, "customer_id": cid,
            "active": True,
        })

        try:
            summary = await get_customer_summary(
                cid=cid, user=admin, tenant={"id": tid},
            )
            assert summary["customer_id"] == cid
            # All eight count keys present.
            for key in ("jobs_count", "invoices_count", "quotes_count",
                        "tasks_count", "service_reports_count",
                        "notes_count", "properties_count",
                        "open_invoices_count"):
                assert key in summary, f"summary missing {key}"
            # Values at least 1 for every seeded bucket.
            assert summary["jobs_count"] >= 1
            assert summary["invoices_count"] >= 2        # paid + sent
            assert summary["quotes_count"] >= 1
            assert summary["tasks_count"] >= 1
            assert summary["service_reports_count"] >= 2
            assert summary["notes_count"] >= 1
            assert summary["properties_count"] >= 1
            # Open invoices: ``sent`` qualifies, ``paid`` does not.
            assert summary["open_invoices_count"] >= 1
        finally:
            await _cleanup(db, tid, prefix)

    run_test(_go)


# ═════════════════════════════════════════════════════════════════
# 4 · Summary counts are tenant-scoped
# ═════════════════════════════════════════════════════════════════
def test_9d_summary_tenant_isolation():
    from routers.customers import get_customer_summary

    async def _go(db):
        prefix = "TEST_9D_ISO_" + uuid.uuid4().hex[:6] + "_"
        tid, admin = await _seed_fixtures(db, prefix)
        other_tid = "TEST_9D_OTHER_" + uuid.uuid4().hex[:6]
        cid = f"{prefix}CUST"
        await _cleanup(db, tid, prefix)
        await _cleanup(db, other_tid, prefix)

        # Caller's tenant: 1 job.
        await db.customers.insert_one({
            "id": cid, "tenant_id": tid,
            "name": f"{prefix}CUST", "is_active": True,
        })
        await db.jobs.insert_one({
            "id": f"JOB_{prefix}_MINE", "tenant_id": tid, "customer_id": cid,
        })
        # Other tenant: SAME customer_id but DIFFERENT tenant +
        # 10 extra jobs that MUST NOT leak into the summary.
        await db.customers.insert_one({
            "id": cid, "tenant_id": other_tid,
            "name": f"{prefix}CUST_OTHER", "is_active": True,
        })
        for i in range(10):
            await db.jobs.insert_one({
                "id": f"JOB_{prefix}_OTHER_{i}", "tenant_id": other_tid,
                "customer_id": cid,
            })

        try:
            summary = await get_customer_summary(
                cid=cid, user=admin, tenant={"id": tid},
            )
            # Must only see the one job in the caller's tenant.
            assert summary["jobs_count"] == 1, (
                f"tenant isolation broken: expected 1 job, got "
                f"{summary['jobs_count']}"
            )
        finally:
            await _cleanup(db, tid, prefix)
            await _cleanup(db, other_tid, prefix)

    run_test(_go)


# ═════════════════════════════════════════════════════════════════
# 5 · Summary 404s for missing / cross-tenant customer
# ═════════════════════════════════════════════════════════════════
def test_9d_summary_404_on_missing_customer():
    from routers.customers import get_customer_summary
    from fastapi import HTTPException

    async def _go(db):
        tid = (await db.tenants.find_one({"slug": "aquaterra"},
                                           {"_id": 0, "id": 1}))["id"]
        admin = await db.users.find_one(
            {"email": "admin@aquaterra.com"},
            {"_id": 0, "id": 1, "role": 1})
        cid = "TEST_9D_404_" + uuid.uuid4().hex[:8]
        raised = None
        try:
            await get_customer_summary(
                cid=cid, user=admin, tenant={"id": tid},
            )
        except HTTPException as exc:
            raised = exc
        assert raised is not None, (
            "summary endpoint did not 404 on missing customer"
        )
        assert raised.status_code == 404

    run_test(_go)


# ═════════════════════════════════════════════════════════════════
# 6 · Soft-deleted customer: 404 for non-super_admin, 409 for super_admin
# ═════════════════════════════════════════════════════════════════
def test_9d_summary_soft_delete_two_branch_gate():
    from routers.customers import get_customer_summary
    from fastapi import HTTPException

    async def _go(db):
        prefix = "TEST_9D_SOFT_" + uuid.uuid4().hex[:6] + "_"
        tid, admin = await _seed_fixtures(db, prefix)
        cid = f"{prefix}CUST"
        await _cleanup(db, tid, prefix)
        await db.customers.insert_one({
            "id": cid, "tenant_id": tid,
            "name": f"{prefix}CUST", "is_active": False,
            "deleted_at": "2026-02-10T00:00:00Z",
        })
        try:
            # Admin: 404.
            admin_err = None
            try:
                await get_customer_summary(
                    cid=cid, user=admin, tenant={"id": tid},
                )
            except HTTPException as exc:
                admin_err = exc
            assert admin_err is not None
            assert admin_err.status_code == 404

            # Super_admin: 409 (same gate as get_customer).
            super_admin_user = {"id": admin["id"], "role": "super_admin"}
            sa_err = None
            try:
                await get_customer_summary(
                    cid=cid, user=super_admin_user, tenant={"id": tid},
                )
            except HTTPException as exc:
                sa_err = exc
            assert sa_err is not None
            assert sa_err.status_code == 409
            # 409 detail carries the ``customer_soft_deleted`` code.
            assert isinstance(sa_err.detail, dict)
            assert sa_err.detail.get("detail") == "customer_soft_deleted"
        finally:
            await _cleanup(db, tid, prefix)

    run_test(_go)
