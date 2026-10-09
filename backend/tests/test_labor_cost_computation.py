"""Phase 10 · Feb-2026 — Labor cost computation contract tests.

Pins the shape + semantics of ``services.labor_cost.compute_labor_cost``
+ the ``GET /reports/labor-cost`` endpoint role gate.

Cases:
    1. Tech with hourly_rate=25, 10h → hourly_cost=250.
    2. Tech with per_pool_rate=10, 8 pool jobs → per_pool_cost=80.
    3. Tech with BOTH set → correct per-tech + totals sum.
    4. Tech with NEITHER rate set → total_labor_cost=0, no crash.
    5. Non-pool jobs do NOT count toward per_pool_cost (regression
       lock on the Phase 1 ``derive_industry_for_job(strict_mode=True)
       == "pool"`` predicate).
    6. Crew-attributed completions: Phase 1 compute_pool_service
       buckets by ``technician_id``, so each crew member with their
       own ``technician_id`` on the job row gets 1 credit. (We DO
       NOT rebucket by crew_id here — the Phase 1 predicate is the
       single source of truth per the brief.)
    7. Date-window edges — a job on the exact ``start`` and ``end``
       day IS included.
    8. Tenant isolation — hours + pool jobs in tenant B never leak
       into tenant A's labor cost.
    9. ``/reports/labor-cost`` role gate: tech → 403, manager →
       200 (read-only), admin → 200.
   10. EBIT ``labor_cost`` field integrates ``compute_labor_cost``
       for the EBIT window (integration lock).
"""
from __future__ import annotations

import uuid

import pytest

from tests._f7_loop_fixture import run_test


async def _seed_tenant_and_admin(db):
    tenant = await db.tenants.find_one({"slug": "aquaterra"},
                                         {"_id": 0, "id": 1})
    admin = await db.users.find_one({"email": "admin@aquaterra.com"},
                                     {"_id": 0, "id": 1, "role": 1,
                                      "tenant_id": 1})
    return tenant["id"], admin


async def _cleanup(db, tid, prefix):
    await db.users.delete_many(
        {"tenant_id": tid, "id": {"$regex": f"^{prefix}"}})
    await db.time_entries.delete_many(
        {"tenant_id": tid, "user_id": {"$regex": f"^{prefix}"}})
    await db.jobs.delete_many(
        {"tenant_id": tid, "technician_id": {"$regex": f"^{prefix}"}})


async def _seed_tech(db, tid, uid, name, hourly=None, per_pool=None):
    doc = {
        "id": uid, "tenant_id": tid,
        "name": name, "email": f"{uid}@test.local",
        "role": "technician",
        "technician_id": uid,
    }
    if hourly is not None:
        doc["hourly_rate"] = hourly
    if per_pool is not None:
        doc["per_pool_rate"] = per_pool
    await db.users.insert_one(doc)


async def _seed_hours(db, tid, uid, hours, date="2026-02-05"):
    await db.time_entries.insert_one({
        "id": f"TE_{uid}_{uuid.uuid4().hex[:6]}",
        "tenant_id": tid, "user_id": uid,
        "duration_minutes": int(float(hours) * 60),
        "date": date, "started_at": f"{date}T08:00:00Z",
    })


async def _seed_pool_job(db, tid, uid, name, date="2026-02-05",
                          service_type="Pool Cleaning",
                          work_class="service", status="completed",
                          industry=None):
    doc = {
        "id": f"JOB_{uuid.uuid4().hex[:8]}",
        "tenant_id": tid,
        "technician_id": uid, "technician_name": name,
        "service_type": service_type, "work_class": work_class,
        "status": status, "scheduled_date": date,
    }
    if industry:
        doc["industry"] = industry
    await db.jobs.insert_one(doc)


# ═════════════════════════════════════════════════════════════════
# 1 · hourly-only
# ═════════════════════════════════════════════════════════════════
def test_10_hourly_only_tech_computes_correct_hourly_cost():
    from services.labor_cost import compute_labor_cost

    async def _go(db):
        prefix = "T10_HO_" + uuid.uuid4().hex[:6] + "_"
        tid, _admin = await _seed_tenant_and_admin(db)
        uid = f"{prefix}TECH"
        await _cleanup(db, tid, prefix)
        await _seed_tech(db, tid, uid, "T10 Hourly", hourly="25.00")
        await _seed_hours(db, tid, uid, 10, "2026-02-05")
        try:
            r = await compute_labor_cost(tid, "2026-02-01", "2026-02-28", db=db)
            row = next(x for x in r["by_tech"] if x["tech_id"] == uid)
            assert row["hours_worked"] == 10.0
            assert row["hourly_cost"] == 250.0
            assert row["per_pool_cost"] == 0.0
            assert row["total_labor_cost"] == 250.0
        finally:
            await _cleanup(db, tid, prefix)

    run_test(_go)


# ═════════════════════════════════════════════════════════════════
# 2 · per-pool-only
# ═════════════════════════════════════════════════════════════════
def test_10_per_pool_only_tech_computes_correct_cost():
    from services.labor_cost import compute_labor_cost

    async def _go(db):
        prefix = "T10_PP_" + uuid.uuid4().hex[:6] + "_"
        tid, _admin = await _seed_tenant_and_admin(db)
        uid = f"{prefix}TECH"
        await _cleanup(db, tid, prefix)
        await _seed_tech(db, tid, uid, "T10 PerPool", per_pool="10.00")
        for i in range(8):
            await _seed_pool_job(db, tid, uid, "T10 PerPool",
                                   date=f"2026-02-{(i % 20) + 1:02d}")
        try:
            r = await compute_labor_cost(tid, "2026-02-01", "2026-02-28", db=db)
            row = next(x for x in r["by_tech"] if x["tech_id"] == uid)
            assert row["pool_jobs_completed"] == 8
            assert row["per_pool_cost"] == 80.0
            assert row["hourly_cost"] == 0.0
            assert row["total_labor_cost"] == 80.0
        finally:
            await _cleanup(db, tid, prefix)

    run_test(_go)


# ═════════════════════════════════════════════════════════════════
# 3 · both-set sum + totals
# ═════════════════════════════════════════════════════════════════
def test_10_both_rates_set_sum_and_totals():
    from services.labor_cost import compute_labor_cost

    async def _go(db):
        prefix = "T10_BOTH_" + uuid.uuid4().hex[:6] + "_"
        tid, _admin = await _seed_tenant_and_admin(db)
        uid = f"{prefix}TECH"
        await _cleanup(db, tid, prefix)
        await _seed_tech(db, tid, uid, "T10 Both",
                          hourly="20.00", per_pool="5.00")
        await _seed_hours(db, tid, uid, 10, "2026-02-05")
        for i in range(4):
            await _seed_pool_job(db, tid, uid, "T10 Both",
                                   date=f"2026-02-{(i % 20) + 1:02d}")
        try:
            r = await compute_labor_cost(tid, "2026-02-01", "2026-02-28", db=db)
            row = next(x for x in r["by_tech"] if x["tech_id"] == uid)
            assert row["hourly_cost"] == 200.0        # 10h * 20
            assert row["per_pool_cost"] == 20.0       # 4 jobs * 5
            assert row["total_labor_cost"] == 220.0
            # Totals aggregate this row.
            assert r["totals"]["hours_worked"] >= 10
            assert r["totals"]["pool_jobs_completed"] >= 4
        finally:
            await _cleanup(db, tid, prefix)

    run_test(_go)


# ═════════════════════════════════════════════════════════════════
# 4 · no rates → zero + no crash
# ═════════════════════════════════════════════════════════════════
def test_10_no_rates_set_returns_zero_cost():
    from services.labor_cost import compute_labor_cost

    async def _go(db):
        prefix = "T10_NONE_" + uuid.uuid4().hex[:6] + "_"
        tid, _admin = await _seed_tenant_and_admin(db)
        uid = f"{prefix}TECH"
        await _cleanup(db, tid, prefix)
        await _seed_tech(db, tid, uid, "T10 None")  # no rates
        await _seed_hours(db, tid, uid, 10, "2026-02-05")
        await _seed_pool_job(db, tid, uid, "T10 None", "2026-02-05")
        try:
            r = await compute_labor_cost(tid, "2026-02-01", "2026-02-28", db=db)
            row = next(x for x in r["by_tech"] if x["tech_id"] == uid)
            assert row["hourly_cost"] == 0.0
            assert row["per_pool_cost"] == 0.0
            assert row["total_labor_cost"] == 0.0
        finally:
            await _cleanup(db, tid, prefix)

    run_test(_go)


# ═════════════════════════════════════════════════════════════════
# 5 · non-pool jobs do NOT count (predicate regression lock)
# ═════════════════════════════════════════════════════════════════
def test_10_non_pool_jobs_excluded_from_per_pool_count():
    from services.labor_cost import compute_labor_cost

    async def _go(db):
        prefix = "T10_NONPOOL_" + uuid.uuid4().hex[:6] + "_"
        tid, _admin = await _seed_tenant_and_admin(db)
        uid = f"{prefix}TECH"
        await _cleanup(db, tid, prefix)
        await _seed_tech(db, tid, uid, "T10 NonPool", per_pool="10.00")
        # 1 pool job
        await _seed_pool_job(db, tid, uid, "T10 NonPool", "2026-02-05")
        # 3 landscape jobs — must NOT be counted.
        for i in range(3):
            await _seed_pool_job(
                db, tid, uid, "T10 NonPool",
                date=f"2026-02-{10 + i:02d}",
                service_type="Landscape Maintenance",
                industry="landscape",
            )
        try:
            r = await compute_labor_cost(tid, "2026-02-01", "2026-02-28", db=db)
            row = next(x for x in r["by_tech"] if x["tech_id"] == uid)
            # Only the 1 pool job counts.
            assert row["pool_jobs_completed"] == 1, (
                f"non-pool jobs leaked into per_pool count: "
                f"{row['pool_jobs_completed']}"
            )
            assert row["per_pool_cost"] == 10.0
        finally:
            await _cleanup(db, tid, prefix)

    run_test(_go)


# ═════════════════════════════════════════════════════════════════
# 6 · crew / multi-tech attribution via technician_id
# ═════════════════════════════════════════════════════════════════
def test_10_crew_members_each_get_per_pool_credit_by_technician_id():
    from services.labor_cost import compute_labor_cost

    async def _go(db):
        prefix = "T10_CREW_" + uuid.uuid4().hex[:6] + "_"
        tid, _admin = await _seed_tenant_and_admin(db)
        u1 = f"{prefix}T1"
        u2 = f"{prefix}T2"
        await _cleanup(db, tid, prefix)
        await _seed_tech(db, tid, u1, "T10 Crew-A", per_pool="7.00")
        await _seed_tech(db, tid, u2, "T10 Crew-B", per_pool="7.00")
        # Both techs each have a job attributed to themselves on
        # the same day — Phase 1 compute_pool_service buckets by
        # ``technician_id``, so each gets 1 credit.
        await _seed_pool_job(db, tid, u1, "T10 Crew-A", "2026-02-05")
        await _seed_pool_job(db, tid, u2, "T10 Crew-B", "2026-02-05")
        try:
            r = await compute_labor_cost(tid, "2026-02-01", "2026-02-28", db=db)
            r1 = next(x for x in r["by_tech"] if x["tech_id"] == u1)
            r2 = next(x for x in r["by_tech"] if x["tech_id"] == u2)
            assert r1["pool_jobs_completed"] == 1
            assert r2["pool_jobs_completed"] == 1
            assert r1["per_pool_cost"] == 7.0
            assert r2["per_pool_cost"] == 7.0
        finally:
            await _cleanup(db, tid, prefix)

    run_test(_go)


# ═════════════════════════════════════════════════════════════════
# 7 · window edges INCLUSIVE
# ═════════════════════════════════════════════════════════════════
def test_10_window_edges_inclusive():
    from services.labor_cost import compute_labor_cost

    async def _go(db):
        prefix = "T10_EDGE_" + uuid.uuid4().hex[:6] + "_"
        tid, _admin = await _seed_tenant_and_admin(db)
        uid = f"{prefix}TECH"
        await _cleanup(db, tid, prefix)
        await _seed_tech(db, tid, uid, "T10 Edge",
                          hourly="10.00", per_pool="5.00")
        # Hours on start day
        await _seed_hours(db, tid, uid, 1, "2026-02-01")
        # Pool job on end day
        await _seed_pool_job(db, tid, uid, "T10 Edge", "2026-02-28")
        # Out-of-window hours (just before window)
        await _seed_hours(db, tid, uid, 10, "2026-01-31")
        try:
            r = await compute_labor_cost(tid, "2026-02-01", "2026-02-28", db=db)
            row = next(x for x in r["by_tech"] if x["tech_id"] == uid)
            # Only the in-window hour counts.
            assert row["hours_worked"] == 1.0, (
                f"window edges wrong: hours={row['hours_worked']}"
            )
            assert row["pool_jobs_completed"] == 1
        finally:
            await _cleanup(db, tid, prefix)

    run_test(_go)


# ═════════════════════════════════════════════════════════════════
# 8 · tenant isolation
# ═════════════════════════════════════════════════════════════════
def test_10_tenant_isolation():
    from services.labor_cost import compute_labor_cost

    async def _go(db):
        prefix = "T10_ISO_" + uuid.uuid4().hex[:6] + "_"
        tid, _admin = await _seed_tenant_and_admin(db)
        other_tid = f"T10_OTHER_{uuid.uuid4().hex[:6]}"
        uid = f"{prefix}MINE"
        other_uid = f"{prefix}THEIRS"
        await _cleanup(db, tid, prefix)
        await _cleanup(db, other_tid, prefix)

        await _seed_tech(db, tid, uid, "T10 Mine", hourly="10.00")
        await _seed_hours(db, tid, uid, 1, "2026-02-05")

        # Other tenant has a tech with 100h — must NOT leak.
        await _seed_tech(db, other_tid, other_uid, "T10 Theirs",
                          hourly="100.00")
        await _seed_hours(db, other_tid, other_uid, 100, "2026-02-05")

        try:
            r = await compute_labor_cost(tid, "2026-02-01", "2026-02-28", db=db)
            tech_ids = {x["tech_id"] for x in r["by_tech"]}
            assert uid in tech_ids
            assert other_uid not in tech_ids, (
                "tenant isolation broken — leaked other tenant's tech"
            )
            # Totals must reflect only tenant A.
            assert r["totals"]["hourly_cost"] >= 10.0
            assert r["totals"]["hourly_cost"] < 1000.0, (
                f"totals include other tenant hours: "
                f"{r['totals']['hourly_cost']}"
            )
        finally:
            await _cleanup(db, tid, prefix)
            await _cleanup(db, other_tid, prefix)

    run_test(_go)


# ═════════════════════════════════════════════════════════════════
# 9 · role gate on /reports/labor-cost
# ═════════════════════════════════════════════════════════════════
def test_10_role_gate_on_labor_cost_endpoint():
    from routers.reports import get_labor_cost_report
    from fastapi import HTTPException

    async def _go(db):
        tid, admin = await _seed_tenant_and_admin(db)

        # Tech → 403
        tech_user = {"id": "T10_FAKE_TECH", "role": "technician"}
        err = None
        try:
            await get_labor_cost_report(
                start="2026-02-01", end="2026-02-28",
                tech_id=None,
                user=tech_user, tenant={"id": tid},
            )
        except HTTPException as exc:
            err = exc
        assert err is not None and err.status_code == 403, (
            f"tech must be 403, got {err}"
        )

        # Admin → 200 (dict response, no exception)
        resp = await get_labor_cost_report(
            start="2026-02-01", end="2026-02-28",
            tech_id=None,
            user={"id": admin["id"], "role": "admin"},
            tenant={"id": tid},
        )
        assert isinstance(resp, dict)
        assert "by_tech" in resp and "totals" in resp

        # Manager → 200 (read-only parity)
        resp_mgr = await get_labor_cost_report(
            start="2026-02-01", end="2026-02-28",
            tech_id=None,
            user={"id": "T10_FAKE_MGR", "role": "manager"},
            tenant={"id": tid},
        )
        assert isinstance(resp_mgr, dict)

    run_test(_go)


# ═════════════════════════════════════════════════════════════════
# 10 · EBIT labor_cost integration
# ═════════════════════════════════════════════════════════════════
def test_10_ebit_labor_cost_field_wired():
    from services.finance.ebit import compute_ebit

    async def _go(db):
        prefix = "T10_EBIT_" + uuid.uuid4().hex[:6] + "_"
        tid, _admin = await _seed_tenant_and_admin(db)
        uid = f"{prefix}TECH"
        await _cleanup(db, tid, prefix)
        await _seed_tech(db, tid, uid, "T10 EBIT", hourly="30.00")
        await _seed_hours(db, tid, uid, 5, "2026-02-05")

        try:
            ebit = await compute_ebit(db, tid, "2026-02-01", "2026-02-28",
                                        revenue_basis="cash")
            # Field exists at the top of the response.
            assert "labor_cost" in ebit, (
                "Phase 10 ebit.labor_cost field missing"
            )
            # And carries the computed amount — 5h * $30 = $150.
            assert ebit["labor_cost"] >= 150.0, (
                f"ebit.labor_cost did not include tech activity: "
                f"{ebit['labor_cost']}"
            )
            # Phase 10 does NOT subtract labor_cost from the EBIT
            # bottom line (Phase 11 owns that step). The response
            # must still include an unchanged ``ebit`` computed
            # from (revenue - cogs - opex - depreciation).
            assert "ebit" in ebit
        finally:
            await _cleanup(db, tid, prefix)

    run_test(_go)
