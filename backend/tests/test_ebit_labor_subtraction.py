"""Phase 11 · Feb-2026 — EBIT labor subtraction + backwards-compat
contract tests.

Pins the Phase 11 arithmetic change to the EBIT compute:
    ebit = revenue - cogs - opex - depreciation - labor_cost_total

and the new response fields ``recurring_labor_cost`` +
``labor_cost_total``. The Phase 10 ``labor_cost`` field stays
unchanged — hourly + per-pool only — so legacy downstream readers
don't drift.
"""
from __future__ import annotations

import uuid

from tests._f7_loop_fixture import run_test


async def _seed(db):
    tenant = await db.tenants.find_one({"slug": "aquaterra"},
                                         {"_id": 0, "id": 1})
    admin = await db.users.find_one(
        {"email": "admin@aquaterra.com"},
        {"_id": 0, "id": 1, "role": 1})
    return tenant["id"], admin


async def _cleanup_all(db, tid, prefix):
    await db.recurring_labor_costs.delete_many(
        {"tenant_id": tid, "label": {"$regex": f"^{prefix}"}})
    await db.users.delete_many(
        {"tenant_id": tid, "id": {"$regex": f"^{prefix}"}})
    await db.time_entries.delete_many(
        {"tenant_id": tid, "user_id": {"$regex": f"^{prefix}"}})


# ═════════════════════════════════════════════════════════════════
# 1 · New response fields present
# ═════════════════════════════════════════════════════════════════
def test_11_ebit_response_includes_new_fields():
    from services.finance.ebit import compute_ebit

    async def _go(db):
        tid, _admin = await _seed(db)
        r = await compute_ebit(db, tid, "2026-02-01", "2026-02-28",
                                 revenue_basis="cash")
        assert "recurring_labor_cost" in r, (
            "Phase 11 recurring_labor_cost field missing"
        )
        assert "labor_cost_total" in r, (
            "Phase 11 labor_cost_total field missing"
        )
        assert isinstance(r["recurring_labor_cost"], (int, float))
        assert isinstance(r["labor_cost_total"], (int, float))

    run_test(_go)


# ═════════════════════════════════════════════════════════════════
# 2 · Arithmetic subtracts labor_cost_total from ebit bottom line
# ═════════════════════════════════════════════════════════════════
def test_11_ebit_bottom_line_subtracts_labor_cost_total():
    from services.finance.ebit import compute_ebit

    async def _go(db):
        prefix = f"T11_ARI_{uuid.uuid4().hex[:6]}_"
        tid, admin = await _seed(db)
        await _cleanup_all(db, tid, prefix)
        # Seed a recurring entry so there's non-zero labor to
        # subtract.
        await db.recurring_labor_costs.insert_one({
            "id": f"RL_{prefix}",
            "tenant_id": tid,
            "label": f"{prefix}Entry",
            "monthly_amount": "1000.00",
            "start_date": "2026-02-01", "end_date": "2026-02-28",
            "status": "active",
            "created_at": "2026-02-01T00:00:00Z",
            "updated_at": "2026-02-01T00:00:00Z",
        })
        try:
            r = await compute_ebit(db, tid, "2026-02-01", "2026-02-28",
                                     revenue_basis="cash")
            # Reconstruct the bottom line from the parts the
            # response reports.
            expected = round(
                r["revenue"] - r["cogs"] - r["opex"] - r["depreciation"]
                - r["labor_cost_total"],
                2,
            )
            assert r["ebit"] == expected, (
                f"ebit = {r['ebit']} but revenue - cogs - opex "
                f"- depreciation - labor_cost_total = {expected}"
            )
            # The recurring entry contributed something.
            assert r["recurring_labor_cost"] > 0
            assert r["labor_cost_total"] >= r["recurring_labor_cost"]
        finally:
            await _cleanup_all(db, tid, prefix)

    run_test(_go)


# ═════════════════════════════════════════════════════════════════
# 3 · Zero recurring + zero hourly → labor_cost_total = 0
# ═════════════════════════════════════════════════════════════════
def test_11_zero_labor_scenario():
    from services.finance.ebit import compute_ebit

    async def _go(db):
        # Use a synthetic tenant_id with NO data at all so the
        # labor compute returns zero both halves. ebit =
        # revenue - cogs - opex - depreciation - 0.
        tid = f"T11_ZERO_{uuid.uuid4().hex[:6]}"
        r = await compute_ebit(db, tid, "2026-02-01", "2026-02-28",
                                 revenue_basis="cash")
        assert r["recurring_labor_cost"] == 0.0
        assert r["labor_cost"] == 0.0
        assert r["labor_cost_total"] == 0.0
        expected = round(
            r["revenue"] - r["cogs"] - r["opex"] - r["depreciation"],
            2,
        )
        assert r["ebit"] == expected

    run_test(_go)


# ═════════════════════════════════════════════════════════════════
# 4 · Hourly + recurring both contribute to labor_cost_total
# ═════════════════════════════════════════════════════════════════
def test_11_hourly_plus_recurring_sum_to_total():
    from services.finance.ebit import compute_ebit

    async def _go(db):
        prefix = f"T11_SUM_{uuid.uuid4().hex[:6]}_"
        tid, admin = await _seed(db)
        await _cleanup_all(db, tid, prefix)
        # Phase 10 side: tech with hourly rate + hours.
        uid = f"{prefix}TECH"
        await db.users.insert_one({
            "id": uid, "tenant_id": tid,
            "name": "T11 Hourly",
            "email": f"{uid}@test.local",
            "role": "technician", "technician_id": uid,
            "hourly_rate": "20.00",
        })
        await db.time_entries.insert_one({
            "id": f"TE_{uid}", "tenant_id": tid, "user_id": uid,
            "duration_minutes": 300,  # 5 hours
            "date": "2026-02-10", "started_at": "2026-02-10T08:00:00Z",
        })
        # Phase 11 side: recurring entry fully inside the window.
        await db.recurring_labor_costs.insert_one({
            "id": f"RL_{prefix}",
            "tenant_id": tid,
            "label": f"{prefix}Entry",
            "monthly_amount": "1000.00",
            "start_date": "2026-02-01", "end_date": "2026-02-28",
            "status": "active",
            "created_at": "2026-02-01T00:00:00Z",
            "updated_at": "2026-02-01T00:00:00Z",
        })
        try:
            r = await compute_ebit(db, tid, "2026-02-01", "2026-02-28",
                                     revenue_basis="cash")
            # Phase 10 hourly = 5h * $20 = $100. Phase 11 recurring
            # for Feb (28 days) = 1000 * (28/30.4375) = 919.84 (approx).
            # Total = ~$1019.84.
            assert r["labor_cost"] >= 100.0
            assert r["recurring_labor_cost"] > 900.0
            # labor_cost_total = hourly + recurring (within rounding).
            summed = round(r["labor_cost"] + r["recurring_labor_cost"], 2)
            assert abs(r["labor_cost_total"] - summed) < 0.02, (
                f"labor_cost_total {r['labor_cost_total']} != "
                f"labor_cost + recurring_labor_cost {summed}"
            )
        finally:
            await _cleanup_all(db, tid, prefix)

    run_test(_go)


# ═════════════════════════════════════════════════════════════════
# 5 · Backwards-compat: labor_cost field unchanged (Phase 10 lock)
# ═════════════════════════════════════════════════════════════════
def test_11_backwards_compat_labor_cost_field_unchanged():
    """``labor_cost`` is the Phase 10 hourly+per-pool number only.
    Phase 11 adds a separate ``labor_cost_total`` and leaves the
    legacy field alone so any pre-Phase-11 downstream reader
    continues to work.
    """
    from services.finance.ebit import compute_ebit

    async def _go(db):
        prefix = f"T11_BC_{uuid.uuid4().hex[:6]}_"
        tid, admin = await _seed(db)
        await _cleanup_all(db, tid, prefix)
        uid = f"{prefix}TECH"
        await db.users.insert_one({
            "id": uid, "tenant_id": tid,
            "name": "T11 BC", "email": f"{uid}@test.local",
            "role": "technician", "technician_id": uid,
            "hourly_rate": "30.00",
        })
        await db.time_entries.insert_one({
            "id": f"TE_{uid}", "tenant_id": tid, "user_id": uid,
            "duration_minutes": 120,  # 2 hours
            "date": "2026-02-10", "started_at": "2026-02-10T08:00:00Z",
        })
        # BIG recurring entry — must NOT bleed into legacy
        # labor_cost field.
        await db.recurring_labor_costs.insert_one({
            "id": f"RL_{prefix}", "tenant_id": tid,
            "label": f"{prefix}BigRec",
            "monthly_amount": "99999.00",
            "start_date": "2026-02-01", "end_date": "2026-02-28",
            "status": "active",
            "created_at": "2026-02-01T00:00:00Z",
            "updated_at": "2026-02-01T00:00:00Z",
        })
        try:
            r = await compute_ebit(db, tid, "2026-02-01", "2026-02-28",
                                     revenue_basis="cash")
            # Legacy labor_cost = 2h * $30 = $60. Must be the
            # Phase-10 number ONLY — big recurring entry is in
            # recurring_labor_cost, not here.
            assert r["labor_cost"] == 60.0, (
                f"legacy labor_cost regressed: expected 60.0 "
                f"(hourly only), got {r['labor_cost']}"
            )
            # Recurring went to the Phase-11 field.
            assert r["recurring_labor_cost"] > 90000.0
        finally:
            await _cleanup_all(db, tid, prefix)

    run_test(_go)
