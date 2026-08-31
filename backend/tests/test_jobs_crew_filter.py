"""Phase F6a · Feb-2026 — /api/jobs?crew_id=… filter tests."""
from __future__ import annotations

import uuid

from fastapi import HTTPException

from tests._f7_loop_fixture import run_test


async def _seed(db):
    tenant = await db.tenants.find_one({"slug": "aquaterra"},
                                          {"_id": 0, "id": 1})
    tid = tenant["id"]
    admin = await db.users.find_one({"email": "admin@aquaterra.com"},
                                       {"_id": 0, "id": 1, "role": 1})
    return tid, admin


async def _cleanup(db, tid, cid):
    await db.crews.delete_many({"tenant_id": tid, "id": cid})
    await db.jobs.delete_many({"tenant_id": tid,
                                  "id": {"$regex": "^TEST_F6A_"}})


async def _seed_crew_with_jobs(db, tid, crew_id, member_ids):
    await db.crews.insert_one({
        "id": crew_id, "tenant_id": tid,
        "name": f"F6A crew {crew_id[-4:]}",
        "tech_ids": list(member_ids),
    })
    # 3 jobs assigned individually to member A, 2 to member B,
    # 1 with the crew_id column set, 4 to a stranger.
    inserts = []
    for i in range(3):
        inserts.append({
            "id": f"TEST_F6A_A_{i}_{uuid.uuid4().hex[:4]}",
            "tenant_id": tid, "customer_id": "x",
            "status": "scheduled", "technician_id": member_ids[0],
            "scheduled_date": "2026-02-06T09:00:00+00:00",
        })
    for i in range(2):
        inserts.append({
            "id": f"TEST_F6A_B_{i}_{uuid.uuid4().hex[:4]}",
            "tenant_id": tid, "customer_id": "x",
            "status": "scheduled", "technician_id": member_ids[1],
            "scheduled_date": "2026-02-06T09:00:00+00:00",
        })
    inserts.append({
        "id": f"TEST_F6A_C_{uuid.uuid4().hex[:4]}",
        "tenant_id": tid, "customer_id": "x",
        "status": "in_progress", "crew_id": crew_id,
        "scheduled_date": "2026-02-06T09:00:00+00:00",
    })
    for i in range(4):
        inserts.append({
            "id": f"TEST_F6A_S_{i}_{uuid.uuid4().hex[:4]}",
            "tenant_id": tid, "customer_id": "x",
            "status": "scheduled", "technician_id": f"stranger_{i}",
            "scheduled_date": "2026-02-06T09:00:00+00:00",
        })
    await db.jobs.insert_many(inserts)


def _call(**overrides):
    """Explicit-defaults invocation of list_jobs — see F3.5 for
    why this helper exists (Query() sentinels leak into BSON on
    direct-function calls)."""
    from routers.jobs import list_jobs
    kwargs = dict(
        status=None, technician_id=None,
        customer_id=None, crew_id=None,
        start=None, end=None,
        scheduled_date=None, recurring_template_id=None,
        limit=1000, include_deleted=False,
    )
    kwargs.update(overrides)
    return list_jobs(**kwargs)


def test_f6a_crew_id_returns_member_jobs_only():
    async def _go(db):
        tid, admin = await _seed(db)
        crew_id = "TEST_F6A_CREW_" + uuid.uuid4().hex[:8]
        members = ["tech-A-" + uuid.uuid4().hex[:4],
                   "tech-B-" + uuid.uuid4().hex[:4]]
        await _cleanup(db, tid, crew_id)
        await _seed_crew_with_jobs(db, tid, crew_id, members)
        try:
            res = await _call(
                user=admin, tenant={"id": tid}, crew_id=crew_id,
            )
            ids = [j["id"] for j in res]
            # 3 A + 2 B + 1 crew_id-assigned = 6. No strangers.
            f6_ids = [i for i in ids if i.startswith("TEST_F6A_")]
            assert len(f6_ids) == 6, f"expected 6 crew jobs, got {f6_ids}"
            assert not any(i.startswith("TEST_F6A_S_") for i in f6_ids)
        finally:
            await _cleanup(db, tid, crew_id)

    run_test(_go)


def test_f6a_crew_id_intersects_with_status():
    async def _go(db):
        tid, admin = await _seed(db)
        crew_id = "TEST_F6A_CREW_" + uuid.uuid4().hex[:8]
        members = ["tech-A-" + uuid.uuid4().hex[:4],
                   "tech-B-" + uuid.uuid4().hex[:4]]
        await _cleanup(db, tid, crew_id)
        await _seed_crew_with_jobs(db, tid, crew_id, members)
        try:
            # 5 crew jobs are "scheduled" (3 A + 2 B); the crew_id-assigned
            # row is "in_progress".
            res_sched = await _call(
                user=admin, tenant={"id": tid},
                crew_id=crew_id, status="scheduled",
            )
            f6 = [j for j in res_sched if j["id"].startswith("TEST_F6A_")]
            assert len(f6) == 5
            res_ip = await _call(
                user=admin, tenant={"id": tid},
                crew_id=crew_id, status="in_progress",
            )
            f6b = [j for j in res_ip if j["id"].startswith("TEST_F6A_")]
            assert len(f6b) == 1
        finally:
            await _cleanup(db, tid, crew_id)

    run_test(_go)


def test_f6a_customer_role_cannot_pass_crew_id():
    async def _go(db):
        tid, _admin = await _seed(db)
        cust_user = {"id": "cust-1", "role": "customer",
                       "customer_id": "cust-1", "tenant_id": tid}
        try:
            await _call(user=cust_user, tenant={"id": tid},
                          crew_id="any-crew")
            raise AssertionError("expected 403 for customer role")
        except HTTPException as e:
            assert e.status_code == 403

    run_test(_go)


def test_f6a_tech_not_in_crew_is_403():
    async def _go(db):
        tid, _admin = await _seed(db)
        crew_id = "TEST_F6A_CREW_" + uuid.uuid4().hex[:8]
        await db.crews.insert_one({
            "id": crew_id, "tenant_id": tid,
            "name": "solo crew",
            "tech_ids": ["tech-member-only"],
        })
        stranger = {"id": "tech-stranger", "role": "technician",
                     "tenant_id": tid}
        try:
            try:
                await _call(user=stranger, tenant={"id": tid},
                              crew_id=crew_id)
                raise AssertionError("expected 403 for non-member tech")
            except HTTPException as e:
                assert e.status_code == 403
        finally:
            await db.crews.delete_one({"id": crew_id})

    run_test(_go)


def test_f6a_tech_in_crew_is_200():
    async def _go(db):
        tid, _admin = await _seed(db)
        crew_id = "TEST_F6A_CREW_" + uuid.uuid4().hex[:8]
        member = {"id": "tech-mm-" + uuid.uuid4().hex[:6],
                   "role": "technician", "tenant_id": tid}
        await db.crews.insert_one({
            "id": crew_id, "tenant_id": tid, "name": "team blue",
            "tech_ids": [member["id"]],
        })
        try:
            res = await _call(user=member, tenant={"id": tid},
                                crew_id=crew_id)
            assert isinstance(res, list)   # 200 OK, empty list is fine
        finally:
            await db.crews.delete_one({"id": crew_id})

    run_test(_go)


def test_f6a_crew_id_is_tenant_scoped():
    async def _go(db):
        tid_a, admin_a = await _seed(db)
        tid_b = "TEST_F6A_TENANT_B_" + uuid.uuid4().hex[:6]
        crew_id_a = "TEST_F6A_CREW_" + uuid.uuid4().hex[:8]
        await db.crews.insert_one({
            "id": crew_id_a, "tenant_id": tid_a,
            "name": "team A", "tech_ids": ["tech-A"],
        })
        admin_b = {"id": "admin-B", "role": "admin", "tenant_id": tid_b}
        try:
            try:
                await _call(user=admin_b, tenant={"id": tid_b},
                              crew_id=crew_id_a)
                raise AssertionError("expected 404 cross-tenant crew read")
            except HTTPException as e:
                assert e.status_code == 404
        finally:
            await db.crews.delete_one({"id": crew_id_a})

    run_test(_go)
