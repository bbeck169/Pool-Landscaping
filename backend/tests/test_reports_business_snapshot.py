"""Feb-2026 · Reports Gap Fill Phase 5a.1 — Business Snapshot tests.

Contract-locked invariants:
  1. Happy path — GET returns the 4-key envelope with numeric
     tiles and an ISO ``computed_at`` stamp.
  2. Employee-count parity — matches the technician-roster set
     used by ``routers/technicians.py::list_technicians`` (union
     of tech-rows + assignable users, deduped by user_id).
  3. BH-per-week fallback — techs without explicit ``weekly_hours``
     contribute the canonical 40 hrs/week default (mirrors
     ``workforce.overtime_weekly_hours``).
  4. Tenant isolation — non-super_admin caller with ``tenant_id=``
     override → 403.
  5. Super_admin bypass — super_admin caller can query another
     tenant's snapshot.
"""
from __future__ import annotations

from unittest.mock import patch, AsyncMock

from utils import new_id
from tests._f7_loop_fixture import run_test


# ─────────────────────────────────────────────────────────────────
# 1 · Happy path + employee/bh parity
# ─────────────────────────────────────────────────────────────────

def test_business_snapshot_happy_path_and_parity():
    from routers import reports_business_snapshot as bsr

    async def _go(db):
        tid = new_id()
        # Tenant with service_radius set.
        await db.tenants.insert_one({
            "id": tid, "slug": f"probe-{tid[:6]}",
            "name": "Snapshot Probe",
            "service_radius": 25,
        })
        # 2 techs: one with explicit weekly_hours=30, one default 40.
        await db.technicians.insert_one({
            "id": new_id(), "tenant_id": tid,
            "name": "Tech Alpha", "user_id": None,
            "weekly_hours": 30, "active": True,
        })
        u_id = new_id()
        await db.users.insert_one({
            "id": u_id, "tenant_id": tid,
            "email": "beta@probe.example",
            "name": "Tech Beta", "role": "technician",
            "active": True,
        })
        # 1 completed job with distance_miles → drives avg_last_30d.
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        await db.jobs.insert_one({
            "id": new_id(), "tenant_id": tid,
            "customer_id": new_id(), "distance_miles": 12.0,
            "completed_at": now, "created_at": now,
        })
        try:
            res = await bsr.business_snapshot(
                tenant_id=None,
                user={"id": "admin_probe", "role": "admin"},
                tenant={"id": tid},
            )
            assert set(res.keys()) >= {
                "service_radius", "employee_count",
                "bh_per_week_capacity", "computed_at", "tenant_id",
            }
            assert res["tenant_id"] == tid
            assert res["service_radius"]["max_miles"] == 25.0
            assert res["service_radius"]["avg_last_30d_miles"] == 12.0
            # 2 active techs (tech-row + assignable user).
            assert res["employee_count"] == 2
            # 30 (explicit) + 40 (default fallback) = 70.
            assert res["bh_per_week_capacity"] == 70.0
            # ISO-8601 stamp.
            assert "T" in res["computed_at"]
        finally:
            await db.tenants.delete_one({"id": tid})
            await db.technicians.delete_many({"tenant_id": tid})
            await db.users.delete_one({"id": u_id})
            await db.jobs.delete_many({"tenant_id": tid})

    run_test(_go)


# ─────────────────────────────────────────────────────────────────
# 2 · Tenant isolation — non-super-admin cannot override tenant_id
# ─────────────────────────────────────────────────────────────────

def test_business_snapshot_rejects_tenant_override_for_non_super_admin():
    from fastapi import HTTPException
    from routers import reports_business_snapshot as bsr

    async def _go(_db):
        try:
            await bsr.business_snapshot(
                tenant_id="OTHER_TENANT",
                user={"id": "admin_probe", "role": "admin"},
                tenant={"id": "MINE"},
            )
            assert False, "should have raised 403"
        except HTTPException as exc:
            assert exc.status_code == 403
            assert "super_admin" in str(exc.detail).lower()

    run_test(_go)


# ─────────────────────────────────────────────────────────────────
# 3 · Super_admin can query another tenant's snapshot
# ─────────────────────────────────────────────────────────────────

def test_business_snapshot_super_admin_can_override_tenant():
    from routers import reports_business_snapshot as bsr

    async def _go(db):
        tid = new_id()
        await db.tenants.insert_one({
            "id": tid, "slug": f"probe-{tid[:6]}",
            "name": "Other Tenant", "service_radius": 15,
        })
        try:
            res = await bsr.business_snapshot(
                tenant_id=tid,
                user={"id": "sa_probe", "role": "super_admin"},
                tenant={"id": "SA_HOME"},
            )
            assert res["tenant_id"] == tid
            assert res["service_radius"]["max_miles"] == 15.0
            # No techs seeded → both are zero.
            assert res["employee_count"] == 0
            assert res["bh_per_week_capacity"] == 0.0
            # No jobs → avg is None (truthful, not fabricated).
            assert res["service_radius"]["avg_last_30d_miles"] is None
        finally:
            await db.tenants.delete_one({"id": tid})

    run_test(_go)


# ─────────────────────────────────────────────────────────────────
# 4 · 404 when tenant doc missing
# ─────────────────────────────────────────────────────────────────

def test_business_snapshot_404_when_tenant_missing():
    from fastapi import HTTPException
    from routers import reports_business_snapshot as bsr

    async def _go(_db):
        try:
            await bsr.business_snapshot(
                tenant_id="NO_SUCH_TENANT",
                user={"id": "sa_probe", "role": "super_admin"},
                tenant={"id": "SA_HOME"},
            )
            assert False, "should have raised 404"
        except HTTPException as exc:
            assert exc.status_code == 404

    run_test(_go)
