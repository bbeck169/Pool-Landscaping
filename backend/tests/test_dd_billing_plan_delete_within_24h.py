"""Ticket DD · Feb-2026 — Autobilling plan delete 24h-lock removal pytest.

Locks:
  1. Deletion succeeds when ``next_run`` is within 24h of now()
     (regression lock: the previous 409 "Charge scheduled within
     24h — cancel manually first" is REMOVED).
  2. Deletion succeeds when ``next_run`` is beyond 24h (unchanged).
  3. Deletion succeeds when ``next_run`` is null/missing (unchanged).
  4. Audit row stamps ``was_imminent_charge=True`` for <24h plans.
  5. Audit row stamps ``was_imminent_charge=False`` for >24h plans
     and for plans with no ``next_run``.
  6. ``stripe_subscription_id`` lock is PRESERVED — still 409.
  7. Nonexistent plan still 404.
  8. Cross-tenant 404 (tenant isolation unchanged).
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from dotenv import dotenv_values
from fastapi import HTTPException
from motor.motor_asyncio import AsyncIOMotorClient


_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_ENV = {k: (v.strip().strip('"').strip("'") if isinstance(v, str) else v)
        for k, v in _ENV.items()}
_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)
_MC = AsyncIOMotorClient(_ENV["MONGO_URL"], io_loop=_LOOP)
_DB = _MC[_ENV["DB_NAME"]]


def _run(coro):
    asyncio.set_event_loop(_LOOP)
    return _LOOP.run_until_complete(coro)


def _patch_db():
    import config
    config.db = _DB
    for mod in ("routers.finances",):
        __import__(mod)
        import sys as _sys
        _sys.modules[mod].db = _DB


PREFIX = f"dd-{uuid4().hex[:8]}"
TENANT_A = f"{PREFIX}-ta"
TENANT_B = f"{PREFIX}-tb"
_USER = {"id": f"{PREFIX}-u", "email": "admin@example.com"}


async def _seed_plan(pid, tid, *, next_run=None, stripe_sub_id=None):
    doc = {"id": pid, "tenant_id": tid, "active": True,
             "customer_id": f"{PREFIX}-cust", "amount": 100,
             "frequency": "monthly", "service": "Pool"}
    if next_run:
        doc["next_run"] = next_run
    if stripe_sub_id:
        doc["stripe_subscription_id"] = stripe_sub_id
    await _DB.billing_plans.insert_one(doc)


async def _cleanup():
    rx = {"$regex": f"^{PREFIX}"}
    await _DB.billing_plans.delete_many(
        {"$or": [{"id": rx}, {"tenant_id": rx}]},
    )
    await _DB.audit_log.delete_many(
        {"$or": [{"target_id": rx}, {"tenant_id": rx}]},
    )


@pytest.fixture(autouse=True)
def _clean():
    _patch_db()
    _run(_cleanup())
    yield
    _run(_cleanup())


def _iso(when):
    return when.isoformat().replace("+00:00", "Z")


# ═══════════════════════════════════════════════════════════════════
# 1 · Imminent charge (<24h) now deletes successfully.
# ═══════════════════════════════════════════════════════════════════
def test_delete_with_imminent_charge_succeeds():
    from routers.finances import _perform_soft_delete_plan
    pid = f"{PREFIX}-imminent"
    _run(_seed_plan(pid, TENANT_A,
        next_run=_iso(datetime.now(timezone.utc) + timedelta(hours=6))))
    tenant = {"id": TENANT_A}
    res = _run(_perform_soft_delete_plan(pid, _USER, tenant))
    assert res["ok"] is True
    assert res["was_imminent_charge"] is True
    row = _run(_DB.billing_plans.find_one({"id": pid}, {"_id": 0}))
    assert row["active"] is False
    assert row.get("deleted_at")


# ═══════════════════════════════════════════════════════════════════
# 2 · Audit row stamps was_imminent_charge=True.
# ═══════════════════════════════════════════════════════════════════
def test_delete_with_imminent_charge_audit_flag():
    from routers.finances import _perform_soft_delete_plan
    pid = f"{PREFIX}-imminent-audit"
    nr = _iso(datetime.now(timezone.utc) + timedelta(hours=2))
    _run(_seed_plan(pid, TENANT_A, next_run=nr))
    _run(_perform_soft_delete_plan(pid, _USER, {"id": TENANT_A}))
    audit = _run(_DB.audit_log.find_one(
        {"target_id": pid, "action": "autobilling.soft_delete"},
        {"_id": 0},
    ))
    assert audit is not None
    assert audit["was_imminent_charge"] is True
    assert audit["snapshot_next_run"] == nr


# ═══════════════════════════════════════════════════════════════════
# 3 · Beyond 24h — delete succeeds, audit flag False.
# ═══════════════════════════════════════════════════════════════════
def test_delete_future_charge_audit_flag_false():
    from routers.finances import _perform_soft_delete_plan
    pid = f"{PREFIX}-future"
    _run(_seed_plan(pid, TENANT_A,
        next_run=_iso(datetime.now(timezone.utc) + timedelta(days=10))))
    res = _run(_perform_soft_delete_plan(pid, _USER, {"id": TENANT_A}))
    assert res["was_imminent_charge"] is False
    audit = _run(_DB.audit_log.find_one(
        {"target_id": pid}, {"_id": 0},
    ))
    assert audit["was_imminent_charge"] is False


# ═══════════════════════════════════════════════════════════════════
# 4 · No next_run — delete succeeds, audit flag False, snapshot None.
# ═══════════════════════════════════════════════════════════════════
def test_delete_without_next_run_audit_flag_false():
    from routers.finances import _perform_soft_delete_plan
    pid = f"{PREFIX}-nonr"
    _run(_seed_plan(pid, TENANT_A, next_run=None))
    res = _run(_perform_soft_delete_plan(pid, _USER, {"id": TENANT_A}))
    assert res["was_imminent_charge"] is False
    audit = _run(_DB.audit_log.find_one(
        {"target_id": pid}, {"_id": 0},
    ))
    assert audit["was_imminent_charge"] is False
    assert audit["snapshot_next_run"] is None


# ═══════════════════════════════════════════════════════════════════
# 5 · Stripe-subscription lock is PRESERVED (still 409).
# ═══════════════════════════════════════════════════════════════════
def test_stripe_subscription_lock_still_blocks_delete():
    from routers.finances import _perform_soft_delete_plan
    pid = f"{PREFIX}-stripe"
    _run(_seed_plan(pid, TENANT_A, stripe_sub_id="sub_test123",
        next_run=_iso(datetime.now(timezone.utc) + timedelta(hours=2))))
    with pytest.raises(HTTPException) as exc:
        _run(_perform_soft_delete_plan(pid, _USER, {"id": TENANT_A}))
    assert exc.value.status_code == 409
    assert "Stripe" in str(exc.value.detail)


# ═══════════════════════════════════════════════════════════════════
# 6 · Nonexistent plan still 404.
# ═══════════════════════════════════════════════════════════════════
def test_nonexistent_plan_still_404():
    from routers.finances import _perform_soft_delete_plan
    with pytest.raises(HTTPException) as exc:
        _run(_perform_soft_delete_plan(
            f"{PREFIX}-ghost", _USER, {"id": TENANT_A},
        ))
    assert exc.value.status_code == 404


# ═══════════════════════════════════════════════════════════════════
# 7 · Cross-tenant 404 — tenant isolation preserved.
# ═══════════════════════════════════════════════════════════════════
def test_cross_tenant_delete_returns_404():
    from routers.finances import _perform_soft_delete_plan
    pid = f"{PREFIX}-xtenant"
    _run(_seed_plan(pid, TENANT_A,
        next_run=_iso(datetime.now(timezone.utc) + timedelta(hours=1))))
    with pytest.raises(HTTPException) as exc:
        _run(_perform_soft_delete_plan(pid, _USER, {"id": TENANT_B}))
    assert exc.value.status_code == 404


# ═══════════════════════════════════════════════════════════════════
# 8 · _plan_locked_reason no longer returns the 24h lock string.
# ═══════════════════════════════════════════════════════════════════
def test_plan_locked_reason_removed_24h_lock():
    from routers.finances import _plan_locked_reason
    assert _plan_locked_reason({
        "next_run": _iso(datetime.now(timezone.utc) + timedelta(hours=1)),
    }) is None
    assert _plan_locked_reason({
        "stripe_subscription_id": "sub_x",
    }) is not None
    assert _plan_locked_reason({
        "stripe_subscription_id": "sub_x",
        "next_run": _iso(datetime.now(timezone.utc) + timedelta(hours=1)),
    }) is not None  # Stripe lock still fires regardless of next_run.


# ═══════════════════════════════════════════════════════════════════
# 9 · _plan_has_imminent_charge boundary behaviour.
# ═══════════════════════════════════════════════════════════════════
def test_plan_has_imminent_charge_boundaries():
    from routers.finances import _plan_has_imminent_charge
    now = datetime.now(timezone.utc)
    assert _plan_has_imminent_charge({"next_run": _iso(now + timedelta(hours=1))}) is True
    assert _plan_has_imminent_charge({"next_run": _iso(now + timedelta(hours=25))}) is False
    assert _plan_has_imminent_charge({"next_run": None}) is False
    assert _plan_has_imminent_charge({}) is False
    assert _plan_has_imminent_charge({"next_run": "not-a-date"}) is False
