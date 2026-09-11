"""Feb-2026 · Reports Gap Fill Phase 5a.1 (Part B) — Attrition Report tests.

Contract-locked invariants:
  1. Happy path — customers who transitioned to inactive within
     the window appear in ``rows``; ``inactive_reason`` is derived
     from ``muted_reason`` (or ``"not_specified"``); LTV is the
     sum of paid invoice totals; ``last_service_date`` is the
     latest ``completed_at``.
  2. Window bounds — rows outside the window are excluded on both
     ends.
  3. Attrition rate math — ``total_attrited / at_risk_denominator
     * 100``, rounded to 1dp.
  4. Tenant isolation — non-super-admin caller with ``tenant_id=``
     override → 403.
  5. Bad date format → 400.
"""
from __future__ import annotations

from tests._f7_loop_fixture import run_test
from utils import new_id


def test_attrition_happy_path_row_shape_and_summary():
    from routers import reports_attrition as ar

    async def _go(db):
        tid = new_id()
        # Two customers created BEFORE the window (at-risk denom = 2).
        cid1, cid2 = new_id(), new_id()
        await db.customers.insert_many([
            # cid1: muted in-window with reason → attrited.
            {"id": cid1, "tenant_id": tid, "name": "Muted Mo",
             "is_active": False, "is_muted": True,
             "muted_at": "2026-02-14T10:00:00+00:00",
             "muted_reason": "moved_away",
             "created_at": "2025-11-01T00:00:00+00:00"},
            # cid2: deactivated in-window without a reason → "not_specified".
            {"id": cid2, "tenant_id": tid, "name": "Silent Sam",
             "is_active": False,
             "updated_at": "2026-02-16T15:00:00+00:00",
             "created_at": "2025-11-02T00:00:00+00:00"},
        ])
        # 1 paid invoice for cid1 → LTV=$120; cid2 → LTV=0.
        await db.quotes.insert_one({
            "id": new_id(), "tenant_id": tid, "doc_type": "invoice",
            "payment_status": "paid", "customer_id": cid1, "total": 120,
        })
        # 1 completed job for cid1.
        await db.jobs.insert_one({
            "id": new_id(), "tenant_id": tid, "customer_id": cid1,
            "completed_at": "2026-01-30T09:00:00+00:00",
        })
        try:
            res = await ar.attrition_report(
                start_date="2026-02-01", end_date="2026-02-28",
                tenant_id=None,
                user={"id": "u", "role": "admin"}, tenant={"id": tid},
            )
            # Summary
            assert res["summary"]["total_attrited"] == 2
            # denom = 2 (both created before window) → rate = 100.0
            assert res["summary"]["attrition_rate_pct"] == 100.0
            # avg LTV = (120 + 0) / 2 = 60.0
            assert res["summary"]["avg_ltv_of_attrited"] == 60.0
            # Rows
            by_cid = {r["customer_id"]: r for r in res["rows"]}
            assert by_cid[cid1]["inactive_reason"] == "moved_away"
            assert by_cid[cid1]["lifetime_value"] == 120.0
            assert by_cid[cid1]["last_service_date"] == "2026-01-30T09:00:00+00:00"
            assert by_cid[cid2]["inactive_reason"] == "not_specified"
            assert by_cid[cid2]["lifetime_value"] == 0.0
            # Chart
            assert res["chart"]["reason_counts"] == {
                "moved_away": 1, "not_specified": 1,
            }
        finally:
            await db.customers.delete_many({"tenant_id": tid})
            await db.quotes.delete_many({"tenant_id": tid})
            await db.jobs.delete_many({"tenant_id": tid})

    run_test(_go)


def test_attrition_excludes_rows_outside_window():
    from routers import reports_attrition as ar

    async def _go(db):
        tid = new_id()
        # cid1: muted BEFORE the window — excluded.
        # cid2: muted AFTER  the window — excluded.
        # cid3: muted WITHIN — included.
        cids = [new_id() for _ in range(3)]
        await db.customers.insert_many([
            {"id": cids[0], "tenant_id": tid, "name": "Too Early",
             "is_active": False, "is_muted": True,
             "muted_at": "2026-01-15T00:00:00+00:00",
             "created_at": "2025-11-01T00:00:00+00:00"},
            {"id": cids[1], "tenant_id": tid, "name": "Too Late",
             "is_active": False, "is_muted": True,
             "muted_at": "2026-03-15T00:00:00+00:00",
             "created_at": "2025-11-01T00:00:00+00:00"},
            {"id": cids[2], "tenant_id": tid, "name": "In Window",
             "is_active": False, "is_muted": True,
             "muted_at": "2026-02-15T00:00:00+00:00",
             "muted_reason": "price",
             "created_at": "2025-11-01T00:00:00+00:00"},
        ])
        try:
            res = await ar.attrition_report(
                start_date="2026-02-01", end_date="2026-02-28",
                tenant_id=None,
                user={"id": "u", "role": "admin"}, tenant={"id": tid},
            )
            assert res["summary"]["total_attrited"] == 1
            assert res["rows"][0]["customer_id"] == cids[2]
            assert res["chart"]["reason_counts"] == {"price": 1}
        finally:
            await db.customers.delete_many({"tenant_id": tid})

    run_test(_go)


def test_attrition_rejects_tenant_override_for_non_super_admin():
    from fastapi import HTTPException
    from routers import reports_attrition as ar

    async def _go(_db):
        try:
            await ar.attrition_report(
                start_date="2026-02-01", end_date="2026-02-28",
                tenant_id="OTHER",
                user={"id": "u", "role": "admin"}, tenant={"id": "MINE"},
            )
            assert False, "should have raised 403"
        except HTTPException as exc:
            assert exc.status_code == 403

    run_test(_go)


def test_attrition_bad_date_format_400():
    from fastapi import HTTPException
    from routers import reports_attrition as ar

    async def _go(_db):
        try:
            await ar.attrition_report(
                start_date="bogus", end_date="2026-02-28",
                tenant_id=None,
                user={"id": "u", "role": "admin"}, tenant={"id": "T"},
            )
            assert False, "should have raised 400"
        except HTTPException as exc:
            assert exc.status_code == 400

    run_test(_go)


def test_attrition_empty_window_returns_zero_envelope():
    """No inactive rows in the window → all counts zero, chart empty."""
    from routers import reports_attrition as ar

    async def _go(db):
        tid = new_id()
        # Seed 1 customer that's NOT inactive — must not show up.
        cid = new_id()
        await db.customers.insert_one({
            "id": cid, "tenant_id": tid, "name": "Still Active",
            "is_active": True,
            "created_at": "2025-11-01T00:00:00+00:00",
        })
        try:
            res = await ar.attrition_report(
                start_date="2026-02-01", end_date="2026-02-28",
                tenant_id=None,
                user={"id": "u", "role": "admin"}, tenant={"id": tid},
            )
            assert res["summary"]["total_attrited"] == 0
            assert res["summary"]["attrition_rate_pct"] == 0.0
            assert res["summary"]["avg_ltv_of_attrited"] == 0.0
            assert res["rows"] == []
            assert res["chart"]["reason_counts"] == {}
        finally:
            await db.customers.delete_many({"tenant_id": tid})

    run_test(_go)
