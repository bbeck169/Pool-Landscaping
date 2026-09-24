"""Phase P53 · Feb-2026 — Portal "My Referrals" tile counter fix.

Locks the widened semantic of ``conversions`` in
``GET /api/customer-portal/referrals/my``: the field means "friend
actually became a customer" and MUST include every post-close-won
status:

    {"converted", "pending_paid_window", "crediting_in_progress",
     "credited"}

Pre-P53 the counter filtered on ``status == "converted"`` alone,
which silently under-counted every Phase-10 tenant (whose modern
flow lands in ``pending_paid_window`` on close-won and jumps to
``credited`` via the 30-day watcher — the counter never saw
``converted``).

Follows the P50/P52 pattern — sync ``pymongo`` for seeding + a
fresh event loop per test for the SUT call. No live HTTP required;
we invoke the handler function directly to keep the test hermetic.
"""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import List

import pytest
from dotenv import dotenv_values
from pymongo import MongoClient

from tests._phase34_asyncio import batch_safe_run as _run


_BE = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
MONGO_URL = _BE.get("MONGO_URL")
DB_NAME = _BE.get("DB_NAME")

TAG = "p53_pt_"


@pytest.fixture(scope="module")
def dbc() -> MongoClient:
    return MongoClient(MONGO_URL)[DB_NAME]


@pytest.fixture
def cleanup(dbc):
    ids: List[str] = []
    yield ids
    if ids:
        dbc.referrals.delete_many({"id": {"$in": ids}})


def _seed_referral(dbc, tenant_id: str, referrer_cid: str,
                    status: str, ids: List[str]) -> str:
    rid = f"{TAG}{uuid.uuid4().hex[:8]}"
    dbc.referrals.insert_one({
        "id": rid,
        "tenant_id": tenant_id,
        "referrer_customer_id": referrer_cid,
        "status": status,
        "friend_name": f"Friend-{status}",
        "created_at": "2026-02-15T00:00:00Z",
        "updated_at": "2026-02-15T00:00:00Z",
    })
    ids.append(rid)
    return rid


def _call_my_referrals(tenant_id: str, cid: str) -> dict:
    """Invoke the FastAPI handler function directly to keep the test
    hermetic (no live server dependency). ``get_current_user`` is
    a FastAPI dependency but the handler function itself accepts the
    resolved ``user`` dict so we bypass the DI layer.

    Uses the module-shared loop (``tests._shared_loop.LOOP``) so
    Motor's ``AsyncIOMotorClient`` — bound to whichever loop it was
    first used from — stays consistent across every test file."""
    from routers.referral_rewards import my_referrals

    return _run(my_referrals(user={
        "role": "customer",
        "tenant_id": tenant_id,
        "customer_id": cid,
    }))


# ═════════════════════════════════════════════════════════════════════
# Section 1 — Counter includes every post-close-won status
# ═════════════════════════════════════════════════════════════════════
def test_conversions_include_pending_paid_window(dbc, cleanup):
    """Phase-10 modern path lands in ``pending_paid_window`` — must
    be counted (previously the biggest silent under-count)."""
    tid = f"{TAG}tenant-{uuid.uuid4().hex[:6]}"
    cid = f"{TAG}cust-{uuid.uuid4().hex[:6]}"
    _seed_referral(dbc, tid, cid, "pending_paid_window", cleanup)

    res = _call_my_referrals(tid, cid)
    assert res["summary"]["total_referrals"] == 1
    assert res["summary"]["conversions"] == 1


def test_conversions_include_crediting_in_progress(dbc, cleanup):
    """CAS-gate transient state — still counts as a conversion."""
    tid = f"{TAG}tenant-{uuid.uuid4().hex[:6]}"
    cid = f"{TAG}cust-{uuid.uuid4().hex[:6]}"
    _seed_referral(dbc, tid, cid, "crediting_in_progress", cleanup)

    res = _call_my_referrals(tid, cid)
    assert res["summary"]["conversions"] == 1


def test_conversions_include_credited(dbc, cleanup):
    """Terminal Phase-10 state — was invisible to the pre-P53 counter."""
    tid = f"{TAG}tenant-{uuid.uuid4().hex[:6]}"
    cid = f"{TAG}cust-{uuid.uuid4().hex[:6]}"
    _seed_referral(dbc, tid, cid, "credited", cleanup)

    res = _call_my_referrals(tid, cid)
    assert res["summary"]["conversions"] == 1


def test_conversions_include_legacy_converted(dbc, cleanup):
    """Backward compat — legacy immediate-credit path still counted."""
    tid = f"{TAG}tenant-{uuid.uuid4().hex[:6]}"
    cid = f"{TAG}cust-{uuid.uuid4().hex[:6]}"
    _seed_referral(dbc, tid, cid, "converted", cleanup)

    res = _call_my_referrals(tid, cid)
    assert res["summary"]["conversions"] == 1


# ═════════════════════════════════════════════════════════════════════
# Section 2 — Counter EXCLUDES voided + pre-close-won states
# ═════════════════════════════════════════════════════════════════════
def test_conversions_exclude_voided(dbc, cleanup):
    """Refund/dispute void — friend converted but reward was
    revoked. Must NOT be in the conversion count."""
    tid = f"{TAG}tenant-{uuid.uuid4().hex[:6]}"
    cid = f"{TAG}cust-{uuid.uuid4().hex[:6]}"
    _seed_referral(dbc, tid, cid, "voided", cleanup)

    res = _call_my_referrals(tid, cid)
    assert res["summary"]["total_referrals"] == 1
    assert res["summary"]["conversions"] == 0


def test_conversions_exclude_pre_close_won(dbc, cleanup):
    """Pre-close-won states (``pending``, ``pending_conversion``,
    or any other pre-conversion label) MUST be excluded — the friend
    hasn't become a customer yet."""
    tid = f"{TAG}tenant-{uuid.uuid4().hex[:6]}"
    cid = f"{TAG}cust-{uuid.uuid4().hex[:6]}"
    _seed_referral(dbc, tid, cid, "pending", cleanup)
    _seed_referral(dbc, tid, cid, "pending_conversion", cleanup)

    res = _call_my_referrals(tid, cid)
    assert res["summary"]["total_referrals"] == 2
    assert res["summary"]["conversions"] == 0


# ═════════════════════════════════════════════════════════════════════
# Section 3 — Mixed rows tally correctly
# ═════════════════════════════════════════════════════════════════════
def test_conversions_mixed_bag_tallies_correctly(dbc, cleanup):
    tid = f"{TAG}tenant-{uuid.uuid4().hex[:6]}"
    cid = f"{TAG}cust-{uuid.uuid4().hex[:6]}"
    _seed_referral(dbc, tid, cid, "pending", cleanup)               # ✗
    _seed_referral(dbc, tid, cid, "pending_paid_window", cleanup)   # ✓
    _seed_referral(dbc, tid, cid, "crediting_in_progress", cleanup)  # ✓
    _seed_referral(dbc, tid, cid, "credited", cleanup)              # ✓
    _seed_referral(dbc, tid, cid, "converted", cleanup)             # ✓
    _seed_referral(dbc, tid, cid, "voided", cleanup)                # ✗

    res = _call_my_referrals(tid, cid)
    assert res["summary"]["total_referrals"] == 6
    assert res["summary"]["conversions"] == 4


# ═════════════════════════════════════════════════════════════════════
# Section 4 — Tenant isolation
# ═════════════════════════════════════════════════════════════════════
def test_conversions_cross_tenant_isolation(dbc, cleanup):
    """A referrer's rows in tenant A must not leak into tenant B."""
    tid_a = f"{TAG}tenA-{uuid.uuid4().hex[:6]}"
    tid_b = f"{TAG}tenB-{uuid.uuid4().hex[:6]}"
    cid = f"{TAG}cust-shared-{uuid.uuid4().hex[:6]}"

    _seed_referral(dbc, tid_a, cid, "credited", cleanup)
    _seed_referral(dbc, tid_a, cid, "converted", cleanup)
    _seed_referral(dbc, tid_b, cid, "credited", cleanup)

    res_a = _call_my_referrals(tid_a, cid)
    res_b = _call_my_referrals(tid_b, cid)

    assert res_a["summary"]["total_referrals"] == 2
    assert res_a["summary"]["conversions"] == 2
    assert res_b["summary"]["total_referrals"] == 1
    assert res_b["summary"]["conversions"] == 1
