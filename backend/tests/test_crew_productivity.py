"""Phase H5 · Feb-2026 — /api/admin/crew-productivity tests.

Contract locked here:
    * Sort order: revenue DESC, name ASC tiebreak
    * F6a attribution: (crew_id == X) OR (technician_id ∈ crew.tech_ids)
    * Terminal-status filter: only ``status == "completed"`` rows
    * Windowed by ``completed_at`` (fallback ``scheduled_date``)
    * Tenant-scoped; RBAC = admin+
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from tests._f7_loop_fixture import run_test


async def _admin_ctx(db):
    tenant = await db.tenants.find_one({"slug": "aquaterra"},
                                          {"_id": 0, "id": 1, "timezone": 1})
    tid = tenant["id"]
    admin = await db.users.find_one({"email": "admin@aquaterra.com"},
                                       {"_id": 0, "id": 1, "role": 1})
    return tid, admin


async def _cleanup(db, tid, prefix):
    await db.crews.delete_many({"tenant_id": tid,
                                    "name": {"$regex": f"^{prefix}"}})
    await db.jobs.delete_many({"tenant_id": tid,
                                    "id": {"$regex": f"^{prefix}"}})


def _iso(dt):
    return dt.astimezone(timezone.utc).isoformat()


def _mid_this_week():
    """Wednesday-noon UTC of the current week — comfortably inside
    the ``this_week`` window regardless of tenant tz."""
    now = datetime.now(timezone.utc).replace(hour=12, minute=0, second=0, microsecond=0)
    # Push to Wednesday (weekday 2) of this Monday-Sunday week.
    return (now - timedelta(days=now.weekday())) + timedelta(days=2)


def _mid_last_week():
    return _mid_this_week() - timedelta(days=7)


def test_h5_happy_path_three_crews_sorted_desc_totals_correct():
    from routers.crew_productivity import crew_productivity

    async def _go(db):
        tid, admin = await _admin_ctx(db)
        prefix = "TEST_H5_HP_" + uuid.uuid4().hex[:6] + "_"
        await _cleanup(db, tid, prefix)
        # 3 crews, no shared tech ids.
        await db.crews.insert_many([
            {"id": f"{prefix}crewA", "tenant_id": tid,
             "name": f"{prefix}A_Alpha", "color": "#111",
             "tech_ids": [f"{prefix}techA"]},
            {"id": f"{prefix}crewB", "tenant_id": tid,
             "name": f"{prefix}B_Bravo", "color": "#222",
             "tech_ids": [f"{prefix}techB1", f"{prefix}techB2"]},
            {"id": f"{prefix}crewC", "tenant_id": tid,
             "name": f"{prefix}C_Charlie", "color": "#333",
             "tech_ids": [f"{prefix}techC"]},
        ])
        wday = _mid_this_week()
        await db.jobs.insert_many([
            # Crew A: 2 jobs, $500 each  → $1000
            {"id": f"{prefix}jA1", "tenant_id": tid, "status": "completed",
             "crew_id": f"{prefix}crewA", "completed_at": _iso(wday),
             "job_totals": {"subtotal": 500.0}},
            {"id": f"{prefix}jA2", "tenant_id": tid, "status": "completed",
             "crew_id": f"{prefix}crewA", "completed_at": _iso(wday),
             "job_totals": {"subtotal": 500.0}},
            # Crew B: 1 job, $2500  → $2500  (top spot)
            {"id": f"{prefix}jB1", "tenant_id": tid, "status": "completed",
             "crew_id": f"{prefix}crewB", "completed_at": _iso(wday),
             "job_totals": {"subtotal": 2500.0}},
            # Crew C: 3 jobs, $100 / $200 / $300  → $600
            {"id": f"{prefix}jC1", "tenant_id": tid, "status": "completed",
             "crew_id": f"{prefix}crewC", "completed_at": _iso(wday),
             "job_totals": {"subtotal": 100.0}},
            {"id": f"{prefix}jC2", "tenant_id": tid, "status": "completed",
             "crew_id": f"{prefix}crewC", "completed_at": _iso(wday),
             "job_totals": {"subtotal": 200.0}},
            {"id": f"{prefix}jC3", "tenant_id": tid, "status": "completed",
             "crew_id": f"{prefix}crewC", "completed_at": _iso(wday),
             "job_totals": {"subtotal": 300.0}},
        ])
        try:
            res = await crew_productivity(
                range="this_week", user=admin,
                tenant={"id": tid, "timezone": "UTC"},
            )
            # Filter to our prefix so preseeded crews don't
            # pollute the fixture.
            rows = [r for r in res["crews"]
                    if r["crew_name"].startswith(prefix)]
            assert [r["crew_name"] for r in rows] == [
                f"{prefix}B_Bravo",
                f"{prefix}A_Alpha",
                f"{prefix}C_Charlie",
            ], f"sort broke; got {[r['crew_name'] for r in rows]}"
            revs = {r["crew_name"]: r["revenue_subtotal"] for r in rows}
            assert revs[f"{prefix}A_Alpha"] == 1000.0
            assert revs[f"{prefix}B_Bravo"] == 2500.0
            assert revs[f"{prefix}C_Charlie"] == 600.0
            jobs = {r["crew_name"]: r["jobs_completed"] for r in rows}
            assert jobs[f"{prefix}A_Alpha"] == 2
            assert jobs[f"{prefix}B_Bravo"] == 1
            assert jobs[f"{prefix}C_Charlie"] == 3
            avgs = {r["crew_name"]: r["avg_job_value"] for r in rows}
            assert avgs[f"{prefix}A_Alpha"] == 500.0
            assert avgs[f"{prefix}B_Bravo"] == 2500.0
            assert avgs[f"{prefix}C_Charlie"] == 200.0
            # member_count carried over from crews.tech_ids.
            mc = {r["crew_name"]: r["member_count"] for r in rows}
            assert mc[f"{prefix}B_Bravo"] == 2
            assert mc[f"{prefix}A_Alpha"] == 1
            # Totals cover our prefix contribution.  Other seed
            # crews may bump the outer total; we only assert the
            # prefix subset lands additively via the response
            # ``totals`` gte our known sum.
            assert res["totals"]["revenue_subtotal"] >= 4100.0
        finally:
            await _cleanup(db, tid, prefix)

    run_test(_go)


def test_h5_range_this_week_vs_last_week_partitions_correctly():
    from routers.crew_productivity import crew_productivity

    async def _go(db):
        tid, admin = await _admin_ctx(db)
        prefix = "TEST_H5_R_" + uuid.uuid4().hex[:6] + "_"
        await _cleanup(db, tid, prefix)
        await db.crews.insert_one({
            "id": f"{prefix}crew", "tenant_id": tid,
            "name": f"{prefix}RangeCrew", "color": "#000",
            "tech_ids": [],
        })
        await db.jobs.insert_many([
            {"id": f"{prefix}jThis", "tenant_id": tid,
             "status": "completed", "crew_id": f"{prefix}crew",
             "completed_at": _iso(_mid_this_week()),
             "job_totals": {"subtotal": 777.0}},
            {"id": f"{prefix}jLast", "tenant_id": tid,
             "status": "completed", "crew_id": f"{prefix}crew",
             "completed_at": _iso(_mid_last_week()),
             "job_totals": {"subtotal": 999.0}},
        ])
        try:
            this_wk = await crew_productivity(
                range="this_week", user=admin,
                tenant={"id": tid, "timezone": "UTC"},
            )
            last_wk = await crew_productivity(
                range="last_week", user=admin,
                tenant={"id": tid, "timezone": "UTC"},
            )
            row_this = next(r for r in this_wk["crews"]
                            if r["crew_name"] == f"{prefix}RangeCrew")
            row_last = next(r for r in last_wk["crews"]
                            if r["crew_name"] == f"{prefix}RangeCrew")
            assert row_this["revenue_subtotal"] == 777.0
            assert row_this["jobs_completed"] == 1
            assert row_last["revenue_subtotal"] == 999.0
            assert row_last["jobs_completed"] == 1
            # Range echoed back for the UI.
            assert this_wk["range"] == "this_week"
            assert last_wk["range"] == "last_week"
            assert this_wk["range_start"] and this_wk["range_end"]
        finally:
            await _cleanup(db, tid, prefix)

    run_test(_go)


def test_h5_tech_only_assignment_counts_via_f6a_union():
    """A job with no ``crew_id`` but a ``technician_id`` belonging to
    the crew's ``tech_ids`` MUST count under that crew — matches the
    F6a filter semantic."""
    from routers.crew_productivity import crew_productivity

    async def _go(db):
        tid, admin = await _admin_ctx(db)
        prefix = "TEST_H5_TU_" + uuid.uuid4().hex[:6] + "_"
        await _cleanup(db, tid, prefix)
        await db.crews.insert_one({
            "id": f"{prefix}crew", "tenant_id": tid,
            "name": f"{prefix}TechUnion", "color": "#000",
            "tech_ids": [f"{prefix}tech1"],
        })
        wday = _mid_this_week()
        await db.jobs.insert_many([
            # Explicit crew_id assignment — counts.
            {"id": f"{prefix}jExplicit", "tenant_id": tid,
             "status": "completed", "crew_id": f"{prefix}crew",
             "completed_at": _iso(wday),
             "job_totals": {"subtotal": 100.0}},
            # No crew_id, but technician_id ∈ tech_ids — counts.
            {"id": f"{prefix}jTechOnly", "tenant_id": tid,
             "status": "completed",
             "technician_id": f"{prefix}tech1",
             "completed_at": _iso(wday),
             "job_totals": {"subtotal": 250.0}},
            # No crew_id + unknown technician — DOES NOT count.
            {"id": f"{prefix}jStranger", "tenant_id": tid,
             "status": "completed",
             "technician_id": f"{prefix}strangerTech",
             "completed_at": _iso(wday),
             "job_totals": {"subtotal": 9999.0}},
        ])
        try:
            res = await crew_productivity(
                range="this_week", user=admin,
                tenant={"id": tid, "timezone": "UTC"},
            )
            row = next(r for r in res["crews"]
                       if r["crew_name"] == f"{prefix}TechUnion")
            assert row["revenue_subtotal"] == 350.0
            assert row["jobs_completed"] == 2
        finally:
            await _cleanup(db, tid, prefix)

    run_test(_go)


def test_h5_tenant_scoping_prevents_leak():
    from routers.crew_productivity import crew_productivity

    async def _go(db):
        tid_a, admin_a = await _admin_ctx(db)
        tid_b = f"h5-alt-{uuid.uuid4().hex[:6]}"
        await db.tenants.insert_one({
            "id": tid_b, "slug": tid_b, "name": "H5 Alt Tenant",
        })
        prefix = "TEST_H5_ISO_" + uuid.uuid4().hex[:6] + "_"
        wday = _mid_this_week()
        try:
            # Same crew name in both tenants so a leak would be
            # obvious in the response payload.
            await db.crews.insert_many([
                {"id": f"{prefix}crewA", "tenant_id": tid_a,
                 "name": f"{prefix}SharedName", "color": "#000",
                 "tech_ids": []},
                {"id": f"{prefix}crewB", "tenant_id": tid_b,
                 "name": f"{prefix}SharedName", "color": "#000",
                 "tech_ids": []},
            ])
            await db.jobs.insert_many([
                {"id": f"{prefix}jA", "tenant_id": tid_a,
                 "status": "completed", "crew_id": f"{prefix}crewA",
                 "completed_at": _iso(wday),
                 "job_totals": {"subtotal": 111.0}},
                {"id": f"{prefix}jB", "tenant_id": tid_b,
                 "status": "completed", "crew_id": f"{prefix}crewB",
                 "completed_at": _iso(wday),
                 "job_totals": {"subtotal": 999.0}},
            ])
            res = await crew_productivity(
                range="this_week", user=admin_a,
                tenant={"id": tid_a, "timezone": "UTC"},
            )
            rows = [r for r in res["crews"]
                    if r["crew_name"].startswith(prefix)]
            assert len(rows) == 1, f"expected 1 crew for tenant A; got {rows}"
            assert rows[0]["revenue_subtotal"] == 111.0
            # And tenant_id echo matches the caller's tenant.
            assert res["tenant_id"] == tid_a
        finally:
            await _cleanup(db, tid_a, prefix)
            await db.crews.delete_many({"tenant_id": tid_b,
                                            "name": {"$regex": f"^{prefix}"}})
            await db.jobs.delete_many({"tenant_id": tid_b,
                                          "id": {"$regex": f"^{prefix}"}})
            await db.tenants.delete_one({"id": tid_b})

    run_test(_go)


def test_h5_only_completed_status_counts_toward_revenue():
    """In-progress / scheduled / cancelled jobs must NOT contribute
    to the revenue rollup — that's how "productivity" is defined."""
    from routers.crew_productivity import crew_productivity

    async def _go(db):
        tid, admin = await _admin_ctx(db)
        prefix = "TEST_H5_TS_" + uuid.uuid4().hex[:6] + "_"
        await _cleanup(db, tid, prefix)
        await db.crews.insert_one({
            "id": f"{prefix}crew", "tenant_id": tid,
            "name": f"{prefix}StatusCrew", "color": "#000",
            "tech_ids": [],
        })
        wday = _mid_this_week()
        await db.jobs.insert_many([
            {"id": f"{prefix}jDone", "tenant_id": tid,
             "status": "completed", "crew_id": f"{prefix}crew",
             "completed_at": _iso(wday),
             "job_totals": {"subtotal": 500.0}},
            {"id": f"{prefix}jScheduled", "tenant_id": tid,
             "status": "scheduled", "crew_id": f"{prefix}crew",
             "scheduled_date": _iso(wday),
             "job_totals": {"subtotal": 9999.0}},
            {"id": f"{prefix}jInProgress", "tenant_id": tid,
             "status": "in_progress", "crew_id": f"{prefix}crew",
             "scheduled_date": _iso(wday),
             "job_totals": {"subtotal": 9999.0}},
            {"id": f"{prefix}jCancelled", "tenant_id": tid,
             "status": "cancelled", "crew_id": f"{prefix}crew",
             "scheduled_date": _iso(wday),
             "job_totals": {"subtotal": 9999.0}},
        ])
        try:
            res = await crew_productivity(
                range="this_week", user=admin,
                tenant={"id": tid, "timezone": "UTC"},
            )
            row = next(r for r in res["crews"]
                       if r["crew_name"] == f"{prefix}StatusCrew")
            assert row["revenue_subtotal"] == 500.0
            assert row["jobs_completed"] == 1
        finally:
            await _cleanup(db, tid, prefix)

    run_test(_go)


def test_h5_rejects_bogus_range_value():
    from routers.crew_productivity import crew_productivity

    async def _go(db):
        tid, admin = await _admin_ctx(db)
        with pytest.raises(HTTPException) as ei:
            await crew_productivity(
                range="yesterday", user=admin,
                tenant={"id": tid, "timezone": "UTC"},
            )
        assert ei.value.status_code == 400
        det = ei.value.detail
        assert isinstance(det, dict)
        assert det.get("detail") == "invalid_range"
        assert det.get("range") == "yesterday"
        assert "this_week" in det.get("allowed", [])

    run_test(_go)


def test_h5_rbac_tech_role_blocked():
    """Technician role must 403 — the tile surfaces revenue, which
    the ``workstream`` RBAC rules explicitly hide from techs."""
    from routers.crew_productivity import crew_productivity

    async def _go(db):
        tid, _ = await _admin_ctx(db)
        tech_user = {"id": "test-h5-tech", "role": "technician",
                        "tenant_id": tid}
        with pytest.raises(HTTPException) as ei:
            # require_admin runs at Depends resolution time; call it
            # directly here so the guard fires deterministically in
            # the unit context.
            from utils import require_admin
            require_admin(user=tech_user)
        assert ei.value.status_code == 403

    run_test(_go)
