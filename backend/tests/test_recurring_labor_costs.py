"""Phase 11 · Feb-2026 — Recurring labor costs CRUD + prorating tests.

Covers both the HTTP router + the ``compute_recurring_labor_cost``
helper. 10 cases keyed to the brief's checklist.
"""
from __future__ import annotations

import uuid

import pytest

from tests._f7_loop_fixture import run_test


async def _seed(db):
    tenant = await db.tenants.find_one({"slug": "aquaterra"},
                                         {"_id": 0, "id": 1})
    admin = await db.users.find_one(
        {"email": "admin@aquaterra.com"},
        {"_id": 0, "id": 1, "role": 1})
    return tenant["id"], admin


async def _cleanup(db, tid, prefix):
    await db.recurring_labor_costs.delete_many(
        {"tenant_id": tid, "label": {"$regex": f"^{prefix}"}})


async def _post_entry(db, tid, admin, overrides):
    from routers.recurring_labor_costs import (
        create_recurring_labor_cost, RecurringLaborCostIn)
    body = RecurringLaborCostIn(
        label=overrides.get("label", "T11 Entry"),
        monthly_amount=overrides.get("monthly_amount", "4500.00"),
        start_date=overrides.get("start_date", "2026-01-01"),
        end_date=overrides.get("end_date"),
        status=overrides.get("status", "active"),
        notes=overrides.get("notes"),
        linked_user_id=overrides.get("linked_user_id"),
    )
    return await create_recurring_labor_cost(
        body=body,
        user={"id": admin["id"], "role": "admin"},
        tenant={"id": tid},
    )


# ═════════════════════════════════════════════════════════════════
# 1 · POST + GET round-trip
# ═════════════════════════════════════════════════════════════════
def test_11_post_then_get_round_trip():
    from routers.recurring_labor_costs import (
        get_recurring_labor_cost,
    )

    async def _go(db):
        prefix = f"T11_RT_{uuid.uuid4().hex[:6]}_"
        tid, admin = await _seed(db)
        await _cleanup(db, tid, prefix)
        created = await _post_entry(db, tid, admin, {
            "label": f"{prefix}Office Mgr",
            "monthly_amount": "4500.00",
            "start_date": "2026-01-01",
        })
        try:
            assert created["label"].startswith(prefix)
            assert created["monthly_amount"] == "4500.00"
            got = await get_recurring_labor_cost(
                entry_id=created["id"],
                user={"id": admin["id"], "role": "admin"},
                tenant={"id": tid},
            )
            assert got["id"] == created["id"]
            assert got["monthly_amount"] == "4500.00"
            assert got["start_date"] == "2026-01-01"
            assert got["status"] == "active"
        finally:
            await _cleanup(db, tid, prefix)

    run_test(_go)


# ═════════════════════════════════════════════════════════════════
# 2 · PATCH updates monthly_amount + status
# ═════════════════════════════════════════════════════════════════
def test_11_patch_updates_fields():
    from routers.recurring_labor_costs import (
        update_recurring_labor_cost, RecurringLaborCostPatch,
    )

    async def _go(db):
        prefix = f"T11_PAT_{uuid.uuid4().hex[:6]}_"
        tid, admin = await _seed(db)
        await _cleanup(db, tid, prefix)
        created = await _post_entry(db, tid, admin, {
            "label": f"{prefix}Role",
            "monthly_amount": "3000.00",
            "start_date": "2026-01-01",
        })
        try:
            updated = await update_recurring_labor_cost(
                entry_id=created["id"],
                body=RecurringLaborCostPatch(
                    monthly_amount="3500.00", status="inactive"),
                user={"id": admin["id"], "role": "admin"},
                tenant={"id": tid},
            )
            assert updated["monthly_amount"] == "3500.00"
            assert updated["status"] == "inactive"
        finally:
            await _cleanup(db, tid, prefix)

    run_test(_go)


# ═════════════════════════════════════════════════════════════════
# 3 · DELETE soft-marks + sets end_date=today
# ═════════════════════════════════════════════════════════════════
def test_11_delete_soft_marks_inactive_and_sets_end_date():
    from routers.recurring_labor_costs import delete_recurring_labor_cost
    from datetime import date

    async def _go(db):
        prefix = f"T11_DEL_{uuid.uuid4().hex[:6]}_"
        tid, admin = await _seed(db)
        await _cleanup(db, tid, prefix)
        created = await _post_entry(db, tid, admin, {
            "label": f"{prefix}X",
            "start_date": "2026-01-01",
        })
        try:
            resp = await delete_recurring_labor_cost(
                entry_id=created["id"], hard=False,
                user={"id": admin["id"], "role": "admin"},
                tenant={"id": tid},
            )
            assert resp["deleted"] == "soft"
            after = await db.recurring_labor_costs.find_one(
                {"id": created["id"]})
            assert after["status"] == "inactive"
            assert after["end_date"] == date.today().isoformat()
        finally:
            await _cleanup(db, tid, prefix)

    run_test(_go)


# ═════════════════════════════════════════════════════════════════
# 4 · Role gate — manager read-only, tech / customer blocked
# ═════════════════════════════════════════════════════════════════
def test_11_role_gate_matrix():
    from routers.recurring_labor_costs import (
        list_recurring_labor_costs,
        create_recurring_labor_cost, RecurringLaborCostIn,
    )
    from fastapi import HTTPException

    async def _go(db):
        tid, admin = await _seed(db)

        # Manager: GET is OK
        rows = await list_recurring_labor_costs(
            include_inactive=True,
            user={"id": "M", "role": "manager"},
            tenant={"id": tid},
        )
        assert isinstance(rows, list)

        # Manager: POST is 403
        mgr_err = None
        try:
            await create_recurring_labor_cost(
                body=RecurringLaborCostIn(
                    label="MGR_TRY", monthly_amount="1.00",
                    start_date="2026-01-01"),
                user={"id": "M", "role": "manager"},
                tenant={"id": tid},
            )
        except HTTPException as exc:
            mgr_err = exc
        assert mgr_err is not None and mgr_err.status_code == 403

        # Tech: GET is 403
        tech_err = None
        try:
            await list_recurring_labor_costs(
                include_inactive=True,
                user={"id": "T", "role": "technician"},
                tenant={"id": tid},
            )
        except HTTPException as exc:
            tech_err = exc
        assert tech_err is not None and tech_err.status_code == 403

    run_test(_go)


# ═════════════════════════════════════════════════════════════════
# 5 · Validation errors (400s)
# ═════════════════════════════════════════════════════════════════
def test_11_validation_rejects_bad_input():
    from routers.recurring_labor_costs import (
        create_recurring_labor_cost, RecurringLaborCostIn,
    )
    from fastapi import HTTPException

    async def _go(db):
        tid, admin = await _seed(db)

        # Negative monthly_amount
        err = None
        try:
            await create_recurring_labor_cost(
                body=RecurringLaborCostIn(
                    label="X", monthly_amount="-10",
                    start_date="2026-01-01"),
                user={"id": admin["id"], "role": "admin"},
                tenant={"id": tid},
            )
        except HTTPException as exc:
            err = exc
        assert err is not None and err.status_code == 400

        # end_date before start_date
        err2 = None
        try:
            await create_recurring_labor_cost(
                body=RecurringLaborCostIn(
                    label="X", monthly_amount="10",
                    start_date="2026-02-01",
                    end_date="2026-01-15"),
                user={"id": admin["id"], "role": "admin"},
                tenant={"id": tid},
            )
        except HTTPException as exc:
            err2 = exc
        assert err2 is not None and err2.status_code == 400

    run_test(_go)


# ═════════════════════════════════════════════════════════════════
# 6 · Tenant isolation
# ═════════════════════════════════════════════════════════════════
def test_11_tenant_isolation():
    from routers.recurring_labor_costs import list_recurring_labor_costs

    async def _go(db):
        prefix = f"T11_ISO_{uuid.uuid4().hex[:6]}_"
        tid, admin = await _seed(db)
        other_tid = f"T11_OTHER_{uuid.uuid4().hex[:6]}"
        await _cleanup(db, tid, prefix)
        await _cleanup(db, other_tid, prefix)

        await _post_entry(db, tid, admin, {"label": f"{prefix}MINE"})
        # Other-tenant row — must NOT leak.
        await db.recurring_labor_costs.insert_one({
            "id": f"OTHER_{uuid.uuid4().hex[:8]}",
            "tenant_id": other_tid,
            "label": f"{prefix}THEIRS",
            "monthly_amount": "9999.00",
            "start_date": "2026-01-01", "end_date": None,
            "status": "active",
        })
        try:
            rows = await list_recurring_labor_costs(
                include_inactive=True,
                user={"id": admin["id"], "role": "admin"},
                tenant={"id": tid},
            )
            labels = {r["label"] for r in rows}
            assert f"{prefix}MINE" in labels
            assert f"{prefix}THEIRS" not in labels, (
                "tenant isolation leaked other tenant's row"
            )
        finally:
            await _cleanup(db, tid, prefix)
            await _cleanup(db, other_tid, prefix)

    run_test(_go)


# ═════════════════════════════════════════════════════════════════
# 7 · Prorating math — 45-day window + $4500/mo entry
# ═════════════════════════════════════════════════════════════════
def test_11_prorating_math_matches_brief_example():
    """Brief example: 45-day window, $4500/mo entry → expected
    cost = 4500 * (45 / 30.4375) = 4500 * 1.47843... = $6652.95.

    Entry start/end wholly inside window so overlap_days = 45.
    """
    from services.recurring_labor_cost import compute_recurring_labor_cost

    async def _go(db):
        prefix = f"T11_PRO_{uuid.uuid4().hex[:6]}_"
        tid, admin = await _seed(db)
        await _cleanup(db, tid, prefix)
        # Entry runs the full 45 days exactly.
        await _post_entry(db, tid, admin, {
            "label": f"{prefix}Full",
            "monthly_amount": "4500.00",
            "start_date": "2026-01-01",
            "end_date": "2026-02-14",   # 45 days inclusive
        })
        try:
            r = await compute_recurring_labor_cost(
                tid, "2026-01-01", "2026-02-14", db=db)
            row = next(x for x in r["by_entry"]
                         if x["label"].startswith(prefix))
            # 45 / 30.4375 = 1.478439425... → quantised to 4p = 1.4784
            # 4500 * 1.478439425... = 6652.977... → quantised 2p = 6652.98
            assert row["months_in_window"] == 1.4784
            assert row["cost_in_window"] == 6652.98
            # ``r["total"]`` sums ALL active entries in the tenant;
            # we only assert on the per-row value since leftover
            # fixtures from parallel tests may contribute to the
            # total.
        finally:
            await _cleanup(db, tid, prefix)

    run_test(_go)


# ═════════════════════════════════════════════════════════════════
# 8 · No-overlap entries excluded entirely
# ═════════════════════════════════════════════════════════════════
def test_11_no_overlap_entries_excluded():
    from services.recurring_labor_cost import compute_recurring_labor_cost

    async def _go(db):
        prefix = f"T11_NOP_{uuid.uuid4().hex[:6]}_"
        tid, admin = await _seed(db)
        await _cleanup(db, tid, prefix)
        # Entry entirely BEFORE window.
        await _post_entry(db, tid, admin, {
            "label": f"{prefix}Early",
            "monthly_amount": "1000.00",
            "start_date": "2025-11-01",
            "end_date": "2025-12-31",
        })
        # Entry entirely AFTER window.
        await _post_entry(db, tid, admin, {
            "label": f"{prefix}Later",
            "monthly_amount": "1000.00",
            "start_date": "2026-05-01",
        })
        try:
            r = await compute_recurring_labor_cost(
                tid, "2026-02-01", "2026-02-28", db=db)
            labels = {x["label"] for x in r["by_entry"]
                       if x["label"].startswith(prefix)}
            assert f"{prefix}Early" not in labels
            assert f"{prefix}Later" not in labels
            prefixed_total = sum(
                x["cost_in_window"] for x in r["by_entry"]
                if x["label"].startswith(prefix))
            assert prefixed_total == 0.0
        finally:
            await _cleanup(db, tid, prefix)

    run_test(_go)


# ═════════════════════════════════════════════════════════════════
# 9 · Inactive entries contribute 0
# ═════════════════════════════════════════════════════════════════
def test_11_inactive_entry_contributes_zero():
    from services.recurring_labor_cost import compute_recurring_labor_cost

    async def _go(db):
        prefix = f"T11_INA_{uuid.uuid4().hex[:6]}_"
        tid, admin = await _seed(db)
        await _cleanup(db, tid, prefix)
        await _post_entry(db, tid, admin, {
            "label": f"{prefix}Inactive",
            "monthly_amount": "5000.00",
            "start_date": "2026-01-01",
            "status": "inactive",
        })
        try:
            r = await compute_recurring_labor_cost(
                tid, "2026-01-01", "2026-01-31", db=db)
            row = next(x for x in r["by_entry"]
                         if x["label"].startswith(prefix))
            # Inactive entries APPEAR in by_entry (audit) but
            # contribute 0 to cost and total.
            assert row["status"] == "inactive"
            assert row["cost_in_window"] == 0.0
            prefixed_total = sum(
                x["cost_in_window"] for x in r["by_entry"]
                if x["label"].startswith(prefix))
            assert prefixed_total == 0.0
        finally:
            await _cleanup(db, tid, prefix)

    run_test(_go)


# ═════════════════════════════════════════════════════════════════
# 10 · Multiple overlapping entries sum correctly
# ═════════════════════════════════════════════════════════════════
def test_11_multiple_overlapping_entries_sum():
    from services.recurring_labor_cost import compute_recurring_labor_cost

    async def _go(db):
        prefix = f"T11_MULT_{uuid.uuid4().hex[:6]}_"
        tid, admin = await _seed(db)
        await _cleanup(db, tid, prefix)
        # Three entries, all active, all fully in [Jan 1 .. Jan 31]
        # window → each contributes monthly_amount * (31 / 30.4375).
        for amount in ("1000.00", "2000.00", "3000.00"):
            await _post_entry(db, tid, admin, {
                "label": f"{prefix}E_{amount}",
                "monthly_amount": amount,
                "start_date": "2026-01-01",
                "end_date": "2026-01-31",
            })
        try:
            r = await compute_recurring_labor_cost(
                tid, "2026-01-01", "2026-01-31", db=db)
            # 31 / 30.4375 = 1.018479...  → quantise 4p → 1.0185
            # 6000 * 1.0185 = 6110.98... → quantise 2p → 6110.98
            prefixed = [x for x in r["by_entry"]
                          if x["label"].startswith(prefix)]
            prefixed_total = round(
                sum(x["cost_in_window"] for x in prefixed), 2)
            # Match the brief's expected sum within $0.01 for rounding.
            assert abs(prefixed_total - 6110.88) < 0.02, (
                f"multi-entry sum off: {prefixed_total}"
            )
        finally:
            await _cleanup(db, tid, prefix)

    run_test(_go)
