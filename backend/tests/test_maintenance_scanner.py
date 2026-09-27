"""LDM-C · Feb-2026 — Predictive Maintenance Scanner tests.

Locks the ten acceptance cases from
``memory/SPEC_LIVE_DISPATCHER_AND_MAINTENANCE.md`` §LDM-C:

    (a) Overdue filter → cross_sell_filter action drafted with the
        correct shape (LDM-C fields + compat surface).
    (b) Overdue salt cell → cross_sell_salt_cell action drafted.
    (c) Non-overdue customer → NOT flagged.
    (d) Customer without pool subscription → NOT scanned.
    (e) Cross-tenant isolation — tenant A's overdue doesn't leak
        into tenant B's actions queue.
    (f) Custom interval respected — tenant A 3mo vs tenant B 12mo
        against the same last-service date yields different outcomes.
    (g) Duplicate scan → dedupe holds (no second action row).
    (h) No last-service history → action drafted with "No ... history
        found" reason.
    (i) Existing ``pending`` action from prior scan → new scan skips.
    (j) Completed action (``status="done"``) from prior scan → new
        scan re-drafts.

Testing style
─────────────
Real Motor DB via a per-test asyncio loop (same convention as
test_automation_rules.py / test_live_dispatcher.py). Every write is
LDMC_-tagged so the cleanup fixture can drop everything it seeded.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest
from dotenv import dotenv_values
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient


_BE = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
MONGO_URL = _BE.get("MONGO_URL")
DB_NAME = _BE.get("DB_NAME")

TAG = "LDMC_"
_FIXED_NOW = datetime(2026, 2, 15, 15, 0, tzinfo=timezone.utc)


def _fresh(prefix: str) -> str:
    return f"{TAG}{prefix}_{uuid.uuid4().hex[:8]}"


def _iso_date(d: date) -> str:
    return d.isoformat()


def _months_ago(months: int) -> date:
    """Return a date roughly ``months`` calendar months ago from
    _FIXED_NOW. Uses 30.44 days-per-month (matches the scanner's
    overdue math) so the tests are deterministic regardless of
    which month boundary _FIXED_NOW crosses."""
    days = int(months * 30.44)
    return (_FIXED_NOW.date() - timedelta(days=days))


# ═════════════════════════════════════════════════════════════════════
# Fixtures
# ═════════════════════════════════════════════════════════════════════
@pytest.fixture(scope="module")
def dbc() -> MongoClient:
    return MongoClient(MONGO_URL)[DB_NAME]


@pytest.fixture
def seeded(dbc):
    tenants: List[str] = []
    customers: List[str] = []
    plans: List[str] = []
    trackers: List[str] = []
    action_ids: List[str] = []
    yield {
        "tenants": tenants, "customers": customers,
        "plans": plans, "trackers": trackers,
        "action_ids": action_ids,
    }
    if tenants:
        dbc.tenants.delete_many({"id": {"$in": tenants}})
        # Wipe every LDMC-scoped action row by tenant so nothing
        # leaks between tests even if the scanner insert didn't
        # go through our tracker.
        dbc.ai_employee_actions.delete_many(
            {"tenant_id": {"$in": tenants}},
        )
    if customers:
        dbc.customers.delete_many({"id": {"$in": customers}})
    if plans:
        dbc.billing_plans.delete_many({"id": {"$in": plans}})
    if trackers:
        dbc.equipment_service_trackers.delete_many(
            {"id": {"$in": trackers}},
        )
    if action_ids:
        dbc.ai_employee_actions.delete_many({"id": {"$in": action_ids}})


# ═════════════════════════════════════════════════════════════════════
# Seed helpers.
# ═════════════════════════════════════════════════════════════════════
def _seed_tenant(dbc, seeded, *, rules: Optional[dict] = None) -> str:
    tid = _fresh("TEN")
    doc: Dict[str, Any] = {
        "id": tid,
        "name": f"LDMC tenant {tid[-6:]}",
        "timezone": "America/New_York",
    }
    if rules is not None:
        doc["settings"] = {"automation_rules": rules}
    dbc.tenants.insert_one(doc)
    seeded["tenants"].append(tid)
    return tid


def _seed_customer(dbc, seeded, tenant_id: str,
                    *, name: str = "LDMC Customer") -> str:
    cid = _fresh("CUS")
    dbc.customers.insert_one({
        "id": cid,
        "tenant_id": tenant_id,
        "name": name,
    })
    seeded["customers"].append(cid)
    return cid


def _seed_pool_plan(dbc, seeded, tenant_id: str, customer_id: str,
                      *, service: str = "Monthly Pool Service",
                      active: bool = True) -> str:
    pid = _fresh("PLAN")
    dbc.billing_plans.insert_one({
        "id": pid,
        "tenant_id": tenant_id,
        "customer_id": customer_id,
        "service": service,
        "active": active,
        "frequency": "monthly",
        "amount": 120.0,
    })
    seeded["plans"].append(pid)
    return pid


def _seed_tracker(dbc, seeded, tenant_id: str, customer_id: str,
                   *, tracker_type: str,
                   last_cleaned_at: Optional[date],
                   is_active: bool = True) -> str:
    trid = _fresh("TRK")
    dbc.equipment_service_trackers.insert_one({
        "id": trid,
        "tenant_id": tenant_id,
        "customer_id": customer_id,
        "tracker_type": tracker_type,
        "is_active": is_active,
        "last_cleaned_at": (_iso_date(last_cleaned_at)
                              if last_cleaned_at else None),
    })
    seeded["trackers"].append(trid)
    return trid


def _seed_existing_action(dbc, seeded, tenant_id: str, customer_id: str,
                           *, action_type: str, status: str) -> str:
    aid = _fresh("ACT")
    dbc.ai_employee_actions.insert_one({
        "id": aid,
        "tenant_id": tenant_id,
        "customer_id": customer_id,
        "action_type": action_type,
        "status": status,
        "drafted_by": "marco_executive",
        "employee_key": "marco_executive",
        "action": f"marco.{action_type}",
    })
    seeded["action_ids"].append(aid)
    return aid


def _run(coro_factory):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    client = AsyncIOMotorClient(MONGO_URL, io_loop=loop)
    adb = client[DB_NAME]
    try:
        return loop.run_until_complete(coro_factory(adb))
    finally:
        try:
            client.close()
        except Exception:
            pass
        try:
            loop.close()
        except Exception:
            pass


# ═════════════════════════════════════════════════════════════════════
# (a) Overdue filter → cross_sell_filter action drafted.
# ═════════════════════════════════════════════════════════════════════
def test_a_overdue_filter_drafts_action(dbc, seeded):
    tid = _seed_tenant(dbc, seeded)
    cid = _seed_customer(dbc, seeded, tid, name="Jane Doe")
    _seed_pool_plan(dbc, seeded, tid, cid)
    # Default filter interval is 6mo; last cleaned 9mo ago → 3mo overdue.
    _seed_tracker(dbc, seeded, tid, cid,
                   tracker_type="filter",
                   last_cleaned_at=_months_ago(9))
    # Also seed a fresh salt-cell so we don't accidentally flag that one.
    _seed_tracker(dbc, seeded, tid, cid,
                   tracker_type="salt_cell",
                   last_cleaned_at=_months_ago(2))

    async def _apply(adb):
        from services.maintenance_scanner import scan
        return await scan(adb, now=_FIXED_NOW)

    stats = _run(_apply)
    assert stats["filter_overdue"] == 1
    assert stats["salt_cell_overdue"] == 0
    assert stats["actions_drafted"] == 1
    action = dbc.ai_employee_actions.find_one(
        {"tenant_id": tid, "customer_id": cid,
         "action_type": "cross_sell_filter"},
        {"_id": 0},
    )
    assert action is not None
    assert action["status"] == "pending"
    assert action["drafted_by"] == "marco_executive"
    assert action["employee_key"] == "marco_executive"
    assert action["action"] == "marco.cross_sell_filter"
    assert "Overdue" in action["due_reason"]
    assert action["customer_last_service_at"]
    assert action["suggested_price_range"] is None
    assert action["source"] == "maintenance_scanner"
    assert action["params"]["tracker_type"] == "filter"
    assert "Jane Doe" in action["title"]


# ═════════════════════════════════════════════════════════════════════
# (b) Overdue salt cell → cross_sell_salt_cell action drafted.
# ═════════════════════════════════════════════════════════════════════
def test_b_overdue_salt_cell_drafts_action(dbc, seeded):
    tid = _seed_tenant(dbc, seeded)
    cid = _seed_customer(dbc, seeded, tid)
    _seed_pool_plan(dbc, seeded, tid, cid)
    _seed_tracker(dbc, seeded, tid, cid,
                   tracker_type="filter",
                   last_cleaned_at=_months_ago(2))
    # Default salt cell interval is 36 mo; seed 40 mo ago → 4 mo overdue.
    _seed_tracker(dbc, seeded, tid, cid,
                   tracker_type="salt_cell",
                   last_cleaned_at=_months_ago(40))

    async def _apply(adb):
        from services.maintenance_scanner import scan
        return await scan(adb, now=_FIXED_NOW)

    stats = _run(_apply)
    assert stats["salt_cell_overdue"] == 1
    assert stats["filter_overdue"] == 0
    action = dbc.ai_employee_actions.find_one(
        {"tenant_id": tid, "customer_id": cid,
         "action_type": "cross_sell_salt_cell"},
        {"_id": 0},
    )
    assert action is not None
    assert action["params"]["tracker_type"] == "salt_cell"
    assert action["action"] == "marco.cross_sell_salt_cell"


# ═════════════════════════════════════════════════════════════════════
# (c) Not-overdue customer → skipped.
# ═════════════════════════════════════════════════════════════════════
def test_c_not_overdue_customer_skipped(dbc, seeded):
    tid = _seed_tenant(dbc, seeded)
    cid = _seed_customer(dbc, seeded, tid)
    _seed_pool_plan(dbc, seeded, tid, cid)
    # 2mo ago on filter (default interval 6mo — well within window)
    _seed_tracker(dbc, seeded, tid, cid,
                   tracker_type="filter",
                   last_cleaned_at=_months_ago(2))
    # 12mo ago on salt cell (default interval 36mo — plenty of headroom)
    _seed_tracker(dbc, seeded, tid, cid,
                   tracker_type="salt_cell",
                   last_cleaned_at=_months_ago(12))

    async def _apply(adb):
        from services.maintenance_scanner import scan
        return await scan(adb, now=_FIXED_NOW)

    stats = _run(_apply)
    assert stats["actions_drafted"] == 0
    assert stats["filter_overdue"] == 0
    assert stats["salt_cell_overdue"] == 0
    assert dbc.ai_employee_actions.count_documents(
        {"tenant_id": tid, "customer_id": cid,
         "action_type": {"$in": [
             "cross_sell_filter", "cross_sell_salt_cell",
         ]}},
    ) == 0


# ═════════════════════════════════════════════════════════════════════
# (d) Customer without a pool subscription → skipped.
# ═════════════════════════════════════════════════════════════════════
def test_d_no_pool_subscription_skipped(dbc, seeded):
    tid = _seed_tenant(dbc, seeded)
    cid = _seed_customer(dbc, seeded, tid)
    # Landscape plan — NOT a pool subscription. Scanner must ignore.
    _seed_pool_plan(dbc, seeded, tid, cid,
                     service="Landscape Maintenance")
    _seed_tracker(dbc, seeded, tid, cid,
                   tracker_type="filter",
                   last_cleaned_at=_months_ago(24))  # extremely overdue

    async def _apply(adb):
        from services.maintenance_scanner import scan
        return await scan(adb, now=_FIXED_NOW)

    stats = _run(_apply)
    assert stats["subscriptions_checked"] == 0
    assert stats["actions_drafted"] == 0


# ═════════════════════════════════════════════════════════════════════
# (e) Cross-tenant isolation.
# ═════════════════════════════════════════════════════════════════════
def test_e_cross_tenant_isolation(dbc, seeded):
    ta = _seed_tenant(dbc, seeded)
    tb = _seed_tenant(dbc, seeded)
    # Tenant A — overdue filter (fresh salt_cell to isolate this test
    # from the "no history" pathway covered by case h).
    a_cid = _seed_customer(dbc, seeded, ta)
    _seed_pool_plan(dbc, seeded, ta, a_cid)
    _seed_tracker(dbc, seeded, ta, a_cid,
                   tracker_type="filter",
                   last_cleaned_at=_months_ago(9))
    _seed_tracker(dbc, seeded, ta, a_cid,
                   tracker_type="salt_cell",
                   last_cleaned_at=_months_ago(2))
    # Tenant B — both trackers CURRENT so nothing should draft. The
    # test question is strictly: does tenant A's overdue leak into
    # tenant B's actions queue?
    b_cid = _seed_customer(dbc, seeded, tb)
    _seed_pool_plan(dbc, seeded, tb, b_cid)
    _seed_tracker(dbc, seeded, tb, b_cid,
                   tracker_type="filter",
                   last_cleaned_at=_months_ago(1))
    _seed_tracker(dbc, seeded, tb, b_cid,
                   tracker_type="salt_cell",
                   last_cleaned_at=_months_ago(2))

    async def _apply(adb):
        from services.maintenance_scanner import scan
        return await scan(adb, now=_FIXED_NOW)

    _run(_apply)
    assert dbc.ai_employee_actions.count_documents(
        {"tenant_id": ta, "customer_id": a_cid,
         "action_type": "cross_sell_filter"},
    ) == 1
    assert dbc.ai_employee_actions.count_documents(
        {"tenant_id": tb, "customer_id": b_cid},
    ) == 0
    # Belt & braces — no rows on tenant B at all under LDMC action_types.
    assert dbc.ai_employee_actions.count_documents(
        {"tenant_id": tb, "action_type": {"$in": [
            "cross_sell_filter", "cross_sell_salt_cell",
        ]}},
    ) == 0


# ═════════════════════════════════════════════════════════════════════
# (f) Tenant-custom interval respected.
# ═════════════════════════════════════════════════════════════════════
def test_f_custom_interval_respected(dbc, seeded):
    """Same 6-month-ago cleaning:
       Tenant A (3mo interval) → OVERDUE.
       Tenant B (12mo interval) → not overdue."""
    ta = _seed_tenant(dbc, seeded, rules={
        "dispatch_delay_threshold_mins": 20,
        "dispatch_sms_customer_count": 3,
        "filter_clean_interval_months": 3,
        "salt_cell_replacement_months": 36,
    })
    tb = _seed_tenant(dbc, seeded, rules={
        "dispatch_delay_threshold_mins": 20,
        "dispatch_sms_customer_count": 3,
        "filter_clean_interval_months": 12,
        "salt_cell_replacement_months": 36,
    })
    for tid in (ta, tb):
        cid = _seed_customer(dbc, seeded, tid)
        _seed_pool_plan(dbc, seeded, tid, cid)
        _seed_tracker(dbc, seeded, tid, cid,
                       tracker_type="filter",
                       last_cleaned_at=_months_ago(6))
        _seed_tracker(dbc, seeded, tid, cid,
                       tracker_type="salt_cell",
                       last_cleaned_at=_months_ago(2))

    async def _apply(adb):
        from services.maintenance_scanner import scan
        return await scan(adb, now=_FIXED_NOW)

    _run(_apply)
    assert dbc.ai_employee_actions.count_documents(
        {"tenant_id": ta, "action_type": "cross_sell_filter"},
    ) == 1
    assert dbc.ai_employee_actions.count_documents(
        {"tenant_id": tb, "action_type": "cross_sell_filter"},
    ) == 0


# ═════════════════════════════════════════════════════════════════════
# (g) Duplicate scan → dedupe holds.
# ═════════════════════════════════════════════════════════════════════
def test_g_duplicate_scan_deduped(dbc, seeded):
    tid = _seed_tenant(dbc, seeded)
    cid = _seed_customer(dbc, seeded, tid)
    _seed_pool_plan(dbc, seeded, tid, cid)
    _seed_tracker(dbc, seeded, tid, cid,
                   tracker_type="filter",
                   last_cleaned_at=_months_ago(12))
    # Fresh salt_cell so this test focuses on the filter dedupe path
    # without the no-history pathway (case h) contaminating counts.
    _seed_tracker(dbc, seeded, tid, cid,
                   tracker_type="salt_cell",
                   last_cleaned_at=_months_ago(2))

    async def _apply(adb):
        from services.maintenance_scanner import scan
        s1 = await scan(adb, now=_FIXED_NOW)
        s2 = await scan(adb, now=_FIXED_NOW + timedelta(hours=1))
        return s1, s2

    s1, s2 = _run(_apply)
    assert s1["actions_drafted"] == 1
    assert s2["actions_drafted"] == 0
    assert s2["actions_deduped"] == 1
    # Exactly one row exists after both runs.
    assert dbc.ai_employee_actions.count_documents(
        {"tenant_id": tid, "customer_id": cid,
         "action_type": "cross_sell_filter"},
    ) == 1


# ═════════════════════════════════════════════════════════════════════
# (h) No last-service history → action drafted with "no history" reason.
# ═════════════════════════════════════════════════════════════════════
def test_h_no_history_flags_as_overdue(dbc, seeded):
    tid = _seed_tenant(dbc, seeded)
    cid = _seed_customer(dbc, seeded, tid)
    _seed_pool_plan(dbc, seeded, tid, cid)
    # NO tracker rows at all. Customer is on a pool plan but the
    # equipment_service_trackers collection has nothing for them.

    async def _apply(adb):
        from services.maintenance_scanner import scan
        return await scan(adb, now=_FIXED_NOW)

    stats = _run(_apply)
    # Both tracker types flagged with "no history" reason.
    assert stats["filter_overdue"] == 1
    assert stats["salt_cell_overdue"] == 1
    assert stats["no_history_flagged"] == 2
    assert stats["actions_drafted"] == 2
    for action_type in ("cross_sell_filter", "cross_sell_salt_cell"):
        act = dbc.ai_employee_actions.find_one(
            {"tenant_id": tid, "customer_id": cid,
             "action_type": action_type},
            {"_id": 0},
        )
        assert act is not None
        assert "history" in act["due_reason"].lower()
        assert act["customer_last_service_at"] is None


# ═════════════════════════════════════════════════════════════════════
# (i) Existing pending action from prior scan → new scan skips.
# ═════════════════════════════════════════════════════════════════════
def test_i_existing_pending_action_skipped(dbc, seeded):
    tid = _seed_tenant(dbc, seeded)
    cid = _seed_customer(dbc, seeded, tid)
    _seed_pool_plan(dbc, seeded, tid, cid)
    _seed_tracker(dbc, seeded, tid, cid,
                   tracker_type="filter",
                   last_cleaned_at=_months_ago(12))
    # Fresh salt_cell so the no-history pathway (case h) doesn't
    # contaminate the filter-focused counts.
    _seed_tracker(dbc, seeded, tid, cid,
                   tracker_type="salt_cell",
                   last_cleaned_at=_months_ago(2))
    # Pre-existing pending row.
    _seed_existing_action(dbc, seeded, tid, cid,
                            action_type="cross_sell_filter",
                            status="pending")

    async def _apply(adb):
        from services.maintenance_scanner import scan
        return await scan(adb, now=_FIXED_NOW)

    stats = _run(_apply)
    assert stats["actions_drafted"] == 0
    assert stats["actions_deduped"] == 1
    # No second row inserted.
    assert dbc.ai_employee_actions.count_documents(
        {"tenant_id": tid, "customer_id": cid,
         "action_type": "cross_sell_filter"},
    ) == 1


# ═════════════════════════════════════════════════════════════════════
# (j) Completed action from prior scan → new scan re-drafts.
# ═════════════════════════════════════════════════════════════════════
def test_j_completed_action_allows_redraft(dbc, seeded):
    tid = _seed_tenant(dbc, seeded)
    cid = _seed_customer(dbc, seeded, tid)
    _seed_pool_plan(dbc, seeded, tid, cid)
    _seed_tracker(dbc, seeded, tid, cid,
                   tracker_type="filter",
                   last_cleaned_at=_months_ago(12))
    # Fresh salt_cell so the no-history pathway (case h) doesn't
    # contaminate the filter-focused counts.
    _seed_tracker(dbc, seeded, tid, cid,
                   tracker_type="salt_cell",
                   last_cleaned_at=_months_ago(2))
    # Prior scan drafted an action that the admin already actioned.
    _seed_existing_action(dbc, seeded, tid, cid,
                            action_type="cross_sell_filter",
                            status="done")

    async def _apply(adb):
        from services.maintenance_scanner import scan
        return await scan(adb, now=_FIXED_NOW)

    stats = _run(_apply)
    # Done actions don't suppress — new draft lands.
    assert stats["actions_drafted"] == 1
    assert stats["actions_deduped"] == 0
    # Two rows now — one done, one pending.
    counts = list(dbc.ai_employee_actions.find(
        {"tenant_id": tid, "customer_id": cid,
         "action_type": "cross_sell_filter"},
    ))
    statuses = sorted(r["status"] for r in counts)
    assert statuses == ["done", "pending"], (
        f"expected [done, pending], got {statuses}"
    )


# ═════════════════════════════════════════════════════════════════════
# Extra smoke — inactive billing plan is ignored.
# ═════════════════════════════════════════════════════════════════════
def test_inactive_plan_is_ignored(dbc, seeded):
    tid = _seed_tenant(dbc, seeded)
    cid = _seed_customer(dbc, seeded, tid)
    _seed_pool_plan(dbc, seeded, tid, cid, active=False)
    _seed_tracker(dbc, seeded, tid, cid,
                   tracker_type="filter",
                   last_cleaned_at=_months_ago(24))

    async def _apply(adb):
        from services.maintenance_scanner import scan
        return await scan(adb, now=_FIXED_NOW)

    stats = _run(_apply)
    assert stats["subscriptions_checked"] == 0
    assert stats["actions_drafted"] == 0
