"""Phase H9 · Feb-2026 — Recurring job crew-assignment tests."""
from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

from tests._f7_loop_fixture import run_test


async def _admin_ctx(db):
    tenant = await db.tenants.find_one({"slug": "aquaterra"},
                                          {"_id": 0, "id": 1})
    tid = tenant["id"]
    admin = await db.users.find_one({"email": "admin@aquaterra.com"},
                                       {"_id": 0, "id": 1, "role": 1})
    return tid, admin


async def _make_tpl(db, tid, **overrides):
    from routers.recurring_jobs import RecurringJobIn, create_recurring
    admin = {"id": "test-admin", "role": "admin", "tenant_id": tid}
    cust = await db.customers.find_one(
        {"tenant_id": tid}, {"_id": 0, "id": 1}
    )
    if not cust:
        cust_id = f"cust-h9-{uuid.uuid4().hex[:6]}"
        await db.customers.insert_one({
            "id": cust_id, "tenant_id": tid,
            "name": "H9 cust", "is_active": True,
        })
    else:
        cust_id = cust["id"]
    body = RecurringJobIn(
        customer_id=cust_id, service_type="Weekly service",
        frequency="weekly", day_of_week=0,
        start_date="2026-02-02", price_cents=12000,
        active=True, notes="", recurrence_never_ends=True,
        **overrides,
    )
    return await create_recurring(
        body=body, user=admin, tenant={"id": tid},
    )


def test_h9_patch_sets_crew_id_clears_tech():
    """PUT with crew_id set → persists crew_id, technician_id
    cleared, crew_name denorm stamped."""
    from routers.recurring_jobs import RecurringJobPatch, patch_recurring

    async def _go(db):
        tid, admin = await _admin_ctx(db)
        crew_id = f"h9-crew-{uuid.uuid4().hex[:6]}"
        await db.crews.insert_one({
            "id": crew_id, "tenant_id": tid,
            "name": "H9 Blue Crew", "color": "#000",
            "tech_ids": ["h9-t1"],
        })
        try:
            tpl = await _make_tpl(db, tid,
                                       assigned_tech_id="h9-t1")
            r = await patch_recurring(
                tpl_id=tpl["id"],
                body=RecurringJobPatch(crew_id=crew_id,
                                             assigned_tech_id=None),
                user=admin, tenant={"id": tid},
            )
            assert r["crew_id"] == crew_id
            assert r["assigned_tech_id"] is None
            assert r["crew_name"] == "H9 Blue Crew"
        finally:
            await db.crews.delete_one({"id": crew_id})
            await db.recurring_job_templates.delete_many(
                {"tenant_id": tid, "customer_id": {"$regex": "^cust-h9-"}},
            )

    run_test(_go)


def test_h9_patch_sets_tech_id_clears_crew():
    from routers.recurring_jobs import RecurringJobPatch, patch_recurring

    async def _go(db):
        tid, admin = await _admin_ctx(db)
        crew_id = f"h9-crew-{uuid.uuid4().hex[:6]}"
        await db.crews.insert_one({
            "id": crew_id, "tenant_id": tid,
            "name": "H9 Green Crew", "color": "#000",
            "tech_ids": [],
        })
        try:
            tpl = await _make_tpl(db, tid, crew_id=crew_id)
            r = await patch_recurring(
                tpl_id=tpl["id"],
                body=RecurringJobPatch(assigned_tech_id="h9-t2",
                                             crew_id=None),
                user=admin, tenant={"id": tid},
            )
            assert r["assigned_tech_id"] == "h9-t2"
            assert r["crew_id"] is None
            assert r["crew_name"] is None
        finally:
            await db.crews.delete_one({"id": crew_id})
            await db.recurring_job_templates.delete_many(
                {"tenant_id": tid, "customer_id": {"$regex": "^cust-h9-"}},
            )

    run_test(_go)


def test_h9_patch_rejects_both_tech_and_crew_set():
    from routers.recurring_jobs import RecurringJobPatch, patch_recurring

    async def _go(db):
        tid, admin = await _admin_ctx(db)
        crew_id = f"h9-crew-{uuid.uuid4().hex[:6]}"
        await db.crews.insert_one({
            "id": crew_id, "tenant_id": tid,
            "name": "H9 Both Crew", "tech_ids": [],
        })
        try:
            tpl = await _make_tpl(db, tid)
            with pytest.raises(HTTPException) as ei:
                await patch_recurring(
                    tpl_id=tpl["id"],
                    body=RecurringJobPatch(
                        assigned_tech_id="h9-t3", crew_id=crew_id,
                    ),
                    user=admin, tenant={"id": tid},
                )
            assert ei.value.status_code == 400
            det = ei.value.detail
            assert isinstance(det, dict)
            assert det.get("detail") == "assignment_conflict"
        finally:
            await db.crews.delete_one({"id": crew_id})
            await db.recurring_job_templates.delete_many(
                {"tenant_id": tid, "customer_id": {"$regex": "^cust-h9-"}},
            )

    run_test(_go)


def test_h9_patch_cross_tenant_crew_returns_404():
    from routers.recurring_jobs import RecurringJobPatch, patch_recurring

    async def _go(db):
        tid_a, admin_a = await _admin_ctx(db)
        tid_b = f"h9-alt-{uuid.uuid4().hex[:6]}"
        await db.tenants.insert_one(
            {"id": tid_b, "slug": tid_b, "name": "H9 alt"},
        )
        crew_b = f"h9-crew-{uuid.uuid4().hex[:6]}"
        await db.crews.insert_one({
            "id": crew_b, "tenant_id": tid_b,
            "name": "H9 alt-crew", "tech_ids": [],
        })
        try:
            tpl = await _make_tpl(db, tid_a)
            with pytest.raises(HTTPException) as ei:
                await patch_recurring(
                    tpl_id=tpl["id"],
                    body=RecurringJobPatch(crew_id=crew_b,
                                                 assigned_tech_id=None),
                    user=admin_a, tenant={"id": tid_a},
                )
            assert ei.value.status_code == 404
        finally:
            await db.crews.delete_one({"id": crew_b})
            await db.tenants.delete_one({"id": tid_b})
            await db.recurring_job_templates.delete_many(
                {"tenant_id": tid_a, "customer_id": {"$regex": "^cust-h9-"}},
            )

    run_test(_go)


def test_h9_generator_preserves_crew_id_on_materialized_jobs():
    """When a template carries crew_id, the generator MUST stamp
    it on the produced ``jobs`` row so the F6a schedule filter
    resolves the specific tech at schedule time."""
    from routers.recurring_jobs import _generate_from_template

    async def _go(db):
        tid, admin = await _admin_ctx(db)
        crew_id = f"h9-crew-{uuid.uuid4().hex[:6]}"
        await db.crews.insert_one({
            "id": crew_id, "tenant_id": tid,
            "name": "H9 Gen Crew", "tech_ids": ["h9-tg1"],
        })
        try:
            tpl = await _make_tpl(db, tid, crew_id=crew_id)
            from datetime import date, timedelta
            through = date.today() + timedelta(days=21)
            r = await _generate_from_template(
                tpl=tpl, through=through,
            )
            assert r["inserted"] >= 1, r
            job = await db.jobs.find_one(
                {"tenant_id": tid,
                 "recurring_template_id": tpl["id"]},
                {"_id": 0, "crew_id": 1, "crew_name": 1,
                 "technician_id": 1},
            )
            assert job is not None
            assert job["crew_id"] == crew_id
            assert job["crew_name"] == "H9 Gen Crew"
            assert job["technician_id"] is None
        finally:
            await db.jobs.delete_many(
                {"tenant_id": tid,
                 "recurring_template_id": tpl["id"]},
            )
            await db.crews.delete_one({"id": crew_id})
            await db.recurring_job_templates.delete_many(
                {"tenant_id": tid, "customer_id": {"$regex": "^cust-h9-"}},
            )

    run_test(_go)


def test_h9_create_with_crew_id_stamps_denorm_and_persists():
    async def _go(db):
        tid, _ = await _admin_ctx(db)
        crew_id = f"h9-crew-{uuid.uuid4().hex[:6]}"
        await db.crews.insert_one({
            "id": crew_id, "tenant_id": tid,
            "name": "H9 Create Crew", "tech_ids": [],
        })
        try:
            tpl = await _make_tpl(db, tid, crew_id=crew_id)
            assert tpl["crew_id"] == crew_id
            assert tpl["crew_name"] == "H9 Create Crew"
            assert tpl["assigned_tech_id"] is None
            # Persisted row carries the denorm too so a list-page
            # render doesn't need a crew lookup.
            row = await db.recurring_job_templates.find_one(
                {"id": tpl["id"], "tenant_id": tid}, {"_id": 0},
            )
            assert row["crew_id"] == crew_id
            assert row["crew_name"] == "H9 Create Crew"
        finally:
            await db.crews.delete_one({"id": crew_id})
            await db.recurring_job_templates.delete_many(
                {"tenant_id": tid, "customer_id": {"$regex": "^cust-h9-"}},
            )

    run_test(_go)
