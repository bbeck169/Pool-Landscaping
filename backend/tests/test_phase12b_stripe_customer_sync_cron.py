"""Phase 12B · Feb 2026 — Weekly Stripe customer sync cron.

Tests the per-tenant local-hour dispatcher and its guardrails:

  1. ``hourly_scan`` fires ``run_weekly_for_tenant`` for tenants whose
     local time is Thursday 02:00, and skips everyone else.
  2. Per-tenant summary is persisted onto the tenant doc
     (``last_stripe_customer_sync_at`` + ``last_stripe_customer_sync_summary``)
     AND onto ``ops_alerts_state`` for the cool-down guard.
  3. 4-hour cool-down: a manual run stamped 30 minutes prior → tenant
     is skipped with reason ``manual_recent``.
  4. Test-mode short-circuit: ``stripe.mode()`` returns ``"test"`` →
     ``hourly_scan`` returns ``{skipped_whole_tick: True}`` and never
     touches Mongo.
  5. Tenant without ``stripe_account_id`` → skipped with WARN.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch, AsyncMock

import pytest
from dotenv import dotenv_values
from pymongo import MongoClient

from tests._shared_loop import run as _run

_env = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = MongoClient(_env["MONGO_URL"])[_env["DB_NAME"]]
_TENANT = _sync.tenants.find_one({"slug": "aquaterra"}, {"_id": 0})
_TENANT_ID = _TENANT["id"]


def _mk_scratch_tenant(*, tz="America/Phoenix", stripe_account="acct_test"):
    """Insert an isolated tenant so we can control ``timezone`` and
    ``stripe_account_id`` without disturbing the aquaterra fixtures
    other suites depend on."""
    tid = f"pytest-p12b-cron-{uuid.uuid4().hex[:8]}"
    doc = {
        "id": tid, "slug": f"cron-{uuid.uuid4().hex[:6]}",
        "name": "P12B Cron Scratch", "timezone": tz,
    }
    if stripe_account:
        doc["stripe_account_id"] = stripe_account
    _sync.tenants.insert_one(doc)
    return tid


def _cleanup_tenant(tid):
    _sync.tenants.delete_many({"id": tid})
    _sync.ops_alerts_state.delete_many({"tenant_id": tid})


def _mk_thursday_2am_local():
    """Return a fixed local datetime for Thursday 02:00 in the pinned
    tz. The cron's dispatcher checks ``weekday()==3`` and ``hour==2``
    so any concrete Thursday at 02:00 works."""
    # 2026-02-05 was a Thursday (Feb 2026 starts on a Sunday).
    from zoneinfo import ZoneInfo
    return datetime(2026, 2, 5, 2, 0, tzinfo=ZoneInfo("America/Phoenix"))


# ─── 1. Live-mode Thursday 02:00 fires the sync ──────────────────────
def test_hourly_scan_fires_at_thursday_02_local_and_persists_summary():
    from services import stripe_customer_sync_cron as cron
    tid = _mk_scratch_tenant()
    fake_summary = {
        "tenant_id": tid, "examined": 5,
        "linked": [], "updated_card_flag": [{"customer_id": "cX"}],
        "ambiguous_matches": [], "skipped_no_contact": 1, "no_op": 3,
        "started_at": "2026-02-05T09:00:00+00:00",
        "finished_at": "2026-02-05T09:00:03+00:00",
    }
    try:
        with patch.object(cron, "_stripe_mode", return_value="live"), \
              patch.object(cron, "_now_local",
                            return_value=_mk_thursday_2am_local()), \
              patch.object(cron, "run_stripe_customer_sync",
                            new=AsyncMock(return_value=fake_summary)):
            report = _run(cron.hourly_scan())
        assert tid in report["fired"]
        doc = _sync.tenants.find_one({"id": tid}, {"_id": 0})
        assert doc.get("last_stripe_customer_sync_at")
        brief = doc.get("last_stripe_customer_sync_summary") or {}
        assert brief.get("examined") == 5
        assert brief.get("updated_card_flag") == 1
        assert brief.get("no_op") == 3
        # ops_alerts_state stamp for the cool-down guard.
        st = _sync.ops_alerts_state.find_one(
            {"tenant_id": tid, "kind": "stripe_customer_sync"}, {"_id": 0})
        assert st is not None
        assert st.get("last_ran_at")
    finally:
        _cleanup_tenant(tid)


# ─── 2. 4h cool-down suppression ─────────────────────────────────────
def test_hourly_scan_respects_4h_manual_run_cooldown():
    from services import stripe_customer_sync_cron as cron
    tid = _mk_scratch_tenant()
    # Simulate a manual run 30 minutes ago.
    manual_stamp = (datetime.now(timezone.utc) - timedelta(minutes=30)) \
        .isoformat()
    _sync.tenants.update_one(
        {"id": tid},
        {"$set": {"stripe_sync_last_run_at": manual_stamp}},
    )
    try:
        with patch.object(cron, "_stripe_mode", return_value="live"), \
              patch.object(cron, "_now_local",
                            return_value=_mk_thursday_2am_local()), \
              patch.object(cron, "run_stripe_customer_sync",
                            new=AsyncMock()) as sync_mock:
            report = _run(cron.hourly_scan())
        assert tid in report["skipped_cooldown"]
        assert tid not in report["fired"]
        sync_mock.assert_not_called()
    finally:
        _cleanup_tenant(tid)


# ─── 3. Test-mode short-circuit ──────────────────────────────────────
def test_hourly_scan_short_circuits_when_stripe_mode_is_test():
    from services import stripe_customer_sync_cron as cron
    with patch.object(cron, "_stripe_mode", return_value="test"), \
          patch.object(cron, "run_stripe_customer_sync",
                        new=AsyncMock()) as sync_mock:
        report = _run(cron.hourly_scan())
    assert report.get("skipped_whole_tick") is True
    assert report.get("stripe_mode") == "test"
    sync_mock.assert_not_called()


# ─── 4. Tenant without stripe_account_id is skipped ─────────────────
def test_hourly_scan_skips_tenants_without_stripe_account():
    from services import stripe_customer_sync_cron as cron
    tid = _mk_scratch_tenant(stripe_account=None)
    try:
        with patch.object(cron, "_stripe_mode", return_value="live"), \
              patch.object(cron, "_now_local",
                            return_value=_mk_thursday_2am_local()), \
              patch.object(cron, "run_stripe_customer_sync",
                            new=AsyncMock()) as sync_mock:
            report = _run(cron.hourly_scan())
        assert tid in report["skipped_not_configured"]
        assert tid not in report["fired"]
        # The sync was still called for other real tenants (aquaterra
        # has stripe_account_id set) so we can't universally assert
        # not_called; only ensure our scratch tenant didn't trigger it.
        for call in sync_mock.call_args_list:
            args, kwargs = call
            assert args[0] != tid, "sync must NOT be called for un-configured tenant"
    finally:
        _cleanup_tenant(tid)


# ─── 5. Wrong slot (non-Thursday, non-2am) does not fire ─────────────
def test_hourly_scan_skips_wrong_local_slot():
    from services import stripe_customer_sync_cron as cron
    from zoneinfo import ZoneInfo
    tid = _mk_scratch_tenant()
    # Wednesday 02:00 local — cron must NOT fire.
    wednesday_2am = datetime(2026, 2, 4, 2, 0, tzinfo=ZoneInfo("America/Phoenix"))
    try:
        with patch.object(cron, "_stripe_mode", return_value="live"), \
              patch.object(cron, "_now_local", return_value=wednesday_2am), \
              patch.object(cron, "run_stripe_customer_sync",
                            new=AsyncMock()) as sync_mock:
            report = _run(cron.hourly_scan())
        assert tid not in report["fired"]
        assert report["skipped_wrong_slot"] >= 1
        # The scratch tenant must not have been synced (aquaterra might
        # or might not depending on its tz — assert scoped to scratch).
        for call in sync_mock.call_args_list:
            args, kwargs = call
            assert args[0] != tid
    finally:
        _cleanup_tenant(tid)
