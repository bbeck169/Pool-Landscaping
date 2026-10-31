"""Feb-2026 · Issue 2 · Unified clock-state gate — pytest.

Locks the invariants ``services/clock_state.py`` must preserve so
``POST /gps/pings`` recognizes "on shift" from any of the three
clock-state collections (``time_entries`` / ``timeclock_punches``
/ ``job_timers``) while keeping tenant isolation + the AZ-TZ
soft-delete filter from commit ``af5745e58``.

Direct Motor seeds + coroutine invocation via the shipped
``config.db`` loop (same pattern as ``test_job_timers_stale_sweep
.py``).  No HTTP needed — the helper is a service-layer function.
"""
from __future__ import annotations

import asyncio
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import db                                              # noqa: E402


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _iso(dt: datetime) -> str:
    return (dt.astimezone(timezone.utc).isoformat()
              .replace("+00:00", "Z"))


@pytest.fixture()
def seed_prefix():
    prefix = f"cs2-{uuid.uuid4().hex[:8]}"
    yield prefix
    async def _clean():
        rx = {"$regex": f"^{prefix}"}
        for coll in ("time_entries", "timeclock_punches",
                      "job_timers", "users"):
            await db[coll].delete_many({"$or": [
                {"id": rx}, {"tenant_id": rx}, {"user_id": rx},
                {"tech_id": rx},
            ]})
    _run(_clean())


async def _seed_open_time_entry(tenant_id, user_id, hours_ago=1):
    row_id = str(uuid.uuid4())
    await db.time_entries.insert_one({
        "id": row_id, "tenant_id": tenant_id, "user_id": user_id,
        "clock_in_at": _iso(datetime.now(timezone.utc)
                                - timedelta(hours=hours_ago)),
        "clock_out_at": None,
    })
    return row_id


async def _seed_open_timeclock_punch(tenant_id, user_id,
                                        hours_ago=1, deleted=False):
    row_id = str(uuid.uuid4())
    await db.timeclock_punches.insert_one({
        "id": row_id, "tenant_id": tenant_id, "user_id": user_id,
        "punch_type": "in",
        "timestamp": _iso(datetime.now(timezone.utc)
                             - timedelta(hours=hours_ago)),
        "deleted_at": _iso(datetime.now(timezone.utc))
            if deleted else None,
    })
    return row_id


async def _seed_closed_timeclock_pair(tenant_id, user_id,
                                        hours_ago=3):
    in_id = str(uuid.uuid4())
    out_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    await db.timeclock_punches.insert_one({
        "id": in_id, "tenant_id": tenant_id, "user_id": user_id,
        "punch_type": "in", "deleted_at": None,
        "timestamp": _iso(now - timedelta(hours=hours_ago)),
    })
    await db.timeclock_punches.insert_one({
        "id": out_id, "tenant_id": tenant_id, "user_id": user_id,
        "punch_type": "out", "deleted_at": None,
        "timestamp": _iso(now - timedelta(hours=hours_ago - 1)),
    })
    return in_id, out_id


async def _seed_open_job_timer(tenant_id, user_id,
                                hours_ago=1, id_field="tech_id"):
    row_id = str(uuid.uuid4())
    await db.job_timers.insert_one({
        "id": row_id, "tenant_id": tenant_id,
        id_field: user_id,
        "started_at": _iso(datetime.now(timezone.utc)
                              - timedelta(hours=hours_ago)),
        "ended_at": None,
    })
    return row_id


# ═══════════════════════════════════════════════════════════════════
# Matrix — each of the three collections individually → True.
# ═══════════════════════════════════════════════════════════════════
def test_open_time_entry_marks_user_on_shift(seed_prefix):
    tid = f"{seed_prefix}-t"
    uid = f"{seed_prefix}-u"
    _run(_seed_open_time_entry(tid, uid))
    from services.clock_state import is_user_on_shift, find_open_shift_ref
    assert _run(is_user_on_shift(uid, tid)) is True
    ref = _run(find_open_shift_ref(uid, tid))
    assert ref["source"] == "time_entries"
    assert ref["shift_id"]


def test_open_timeclock_punch_marks_user_on_shift(seed_prefix):
    tid = f"{seed_prefix}-t"
    uid = f"{seed_prefix}-u"
    _run(_seed_open_timeclock_punch(tid, uid))
    from services.clock_state import is_user_on_shift, find_open_shift_ref
    assert _run(is_user_on_shift(uid, tid)) is True
    ref = _run(find_open_shift_ref(uid, tid))
    assert ref["source"] == "timeclock_punches"


def test_open_job_timer_marks_user_on_shift(seed_prefix):
    tid = f"{seed_prefix}-t"
    uid = f"{seed_prefix}-u"
    _run(_seed_open_job_timer(tid, uid))
    from services.clock_state import is_user_on_shift, find_open_shift_ref
    assert _run(is_user_on_shift(uid, tid)) is True
    ref = _run(find_open_shift_ref(uid, tid))
    assert ref["source"] == "job_timers"


def test_open_job_timer_via_user_id_field_also_matches(seed_prefix):
    """``auto_start_timer_on_arrival`` writes ``tech_id`` which may
    equal either ``technicians.id`` or ``users.id``; the helper
    accepts either column via its ``$or`` clause."""
    tid = f"{seed_prefix}-t"
    uid = f"{seed_prefix}-u"
    _run(_seed_open_job_timer(tid, uid, id_field="user_id"))
    from services.clock_state import is_user_on_shift
    assert _run(is_user_on_shift(uid, tid)) is True


# ═══════════════════════════════════════════════════════════════════
# Negative cases.
# ═══════════════════════════════════════════════════════════════════
def test_no_rows_anywhere_returns_false(seed_prefix):
    tid = f"{seed_prefix}-t"
    uid = f"{seed_prefix}-u"
    from services.clock_state import is_user_on_shift, find_open_shift_ref
    assert _run(is_user_on_shift(uid, tid)) is False
    assert _run(find_open_shift_ref(uid, tid)) is None


def test_cross_tenant_row_is_ignored(seed_prefix):
    tid_a = f"{seed_prefix}-a"
    tid_b = f"{seed_prefix}-b"
    uid = f"{seed_prefix}-u"
    _run(_seed_open_time_entry(tid_b, uid))
    _run(_seed_open_timeclock_punch(tid_b, uid))
    _run(_seed_open_job_timer(tid_b, uid))
    from services.clock_state import is_user_on_shift
    assert _run(is_user_on_shift(uid, tid_a)) is False


def test_soft_deleted_punch_does_not_mark_on_shift(seed_prefix):
    """AZ-TZ fix regression lock — ``deleted_at != None`` must
    exclude a tombstoned punch from the open-shift probe."""
    tid = f"{seed_prefix}-t"
    uid = f"{seed_prefix}-u"
    _run(_seed_open_timeclock_punch(tid, uid, deleted=True))
    from services.clock_state import is_user_on_shift
    assert _run(is_user_on_shift(uid, tid)) is False


def test_closed_timeclock_pair_does_not_mark_on_shift(seed_prefix):
    tid = f"{seed_prefix}-t"
    uid = f"{seed_prefix}-u"
    _run(_seed_closed_timeclock_pair(tid, uid))
    from services.clock_state import is_user_on_shift
    assert _run(is_user_on_shift(uid, tid)) is False


# ═══════════════════════════════════════════════════════════════════
# Naive-tz ``at`` normalization.
# ═══════════════════════════════════════════════════════════════════
def test_naive_tz_at_timestamp_is_handled_as_utc(seed_prefix):
    """Historical bug: comparing a naive ``datetime`` against an
    aware ISO cutoff crashed the whole gate (same shape as the
    ``dashboard_service_category`` tz-naive repair).  Helper
    accepts a naive ``at`` and treats it as UTC."""
    tid = f"{seed_prefix}-t"
    uid = f"{seed_prefix}-u"
    _run(_seed_open_time_entry(tid, uid, hours_ago=2))
    naive_now = datetime.utcnow()  # tzinfo=None
    from services.clock_state import is_user_on_shift
    assert _run(is_user_on_shift(uid, tid, at=naive_now)) is True


def test_at_before_shift_start_returns_false(seed_prefix):
    tid = f"{seed_prefix}-t"
    uid = f"{seed_prefix}-u"
    _run(_seed_open_time_entry(tid, uid, hours_ago=1))
    before = datetime.now(timezone.utc) - timedelta(hours=5)
    from services.clock_state import is_user_on_shift
    assert _run(is_user_on_shift(uid, tid, at=before)) is False


# ═══════════════════════════════════════════════════════════════════
# GPS ingest wiring — the ingest-layer gate now uses the unified
# reader via ``_get_open_shift``.  Verifies the end-to-end
# refactor hasn't dropped the ``clock_in_id`` correlation.
# ═══════════════════════════════════════════════════════════════════
def test_gps_ingest_get_open_shift_matches_any_collection(seed_prefix):
    tid = f"{seed_prefix}-t"
    uid = f"{seed_prefix}-u"
    # Only a timeclock_punches row — pre-ticket this returned None.
    _run(_seed_open_timeclock_punch(tid, uid))
    from routers.gps_ingest import _get_open_shift
    shift = _run(_get_open_shift(tid, uid))
    assert shift is not None, (
        "GPS ingest open-shift probe must accept timeclock_punches "
        "under the unified gate"
    )
    assert shift.get("id")
    assert shift.get("source") == "timeclock_punches"


def test_gps_ingest_get_open_shift_prefers_time_entries(seed_prefix):
    """When multiple collections carry an open row, the shipped
    precedence (time_entries → timeclock_punches → job_timers)
    must be preserved so pre-ticket ``clock_in_id`` values on
    existing pings stay the same across the refactor."""
    tid = f"{seed_prefix}-t"
    uid = f"{seed_prefix}-u"
    te_id = _run(_seed_open_time_entry(tid, uid))
    _run(_seed_open_timeclock_punch(tid, uid))
    _run(_seed_open_job_timer(tid, uid))
    from routers.gps_ingest import _get_open_shift
    shift = _run(_get_open_shift(tid, uid))
    assert shift["source"] == "time_entries"
    assert shift["id"] == te_id


def test_gps_ingest_get_open_shift_returns_none_when_off_shift(seed_prefix):
    tid = f"{seed_prefix}-t"
    uid = f"{seed_prefix}-u"
    from routers.gps_ingest import _get_open_shift
    assert _run(_get_open_shift(tid, uid)) is None
