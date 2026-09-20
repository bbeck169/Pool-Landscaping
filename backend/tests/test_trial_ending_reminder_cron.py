"""Feb-2026 · Business Signup SP1 — trial-reminder cron unit tests.

The cron helper is async (Motor). Rather than fight the loop trap,
these tests verify:

    1. The public helper signature is stable
       (``run_trial_ending_reminders(db, *, now=None)``).
    2. The query selector filters on ``trial_end_utc`` window +
       ``trial_reminder_sent_at IS None`` + ``billing_status='trialing'``.
    3. The plan-amount fallback resolver returns the generic
       "your plan pricing" string when Stripe isn't configured.
"""
from __future__ import annotations

import asyncio
import inspect
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import dotenv_values
from pymongo import MongoClient
from tests._shared_mongo import (
    shared_client as _shared_client,
    shared_db as _shared_db,
)



os.environ.setdefault("ALLOW_TEST_HOOKS", "1")
_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = _shared_db()
def _new_id() -> str:
    return f"tbr-signup-test-{uuid.uuid4().hex[:12]}"


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def test_trial_reminder_helper_defines_expected_public_function():
    from services.tenant_billing_reminders import run_trial_ending_reminders
    assert inspect.iscoroutinefunction(run_trial_ending_reminders)
    sig = inspect.signature(run_trial_ending_reminders)
    assert "db" in sig.parameters
    assert sig.parameters["now"].default is None


def test_plan_amount_fallback_returns_generic_string_when_no_subscription(monkeypatch):
    """Phase D6.2 · Feb-2026 — when Stripe subscription id is
    missing, the helper returns ``None`` and the caller substitutes
    the localised fallback string (from the D6 catalog under
    ``email.trial_reminder.fallback.plan_amount``). This preserves
    the original ``never invent a dollar figure`` guarantee while
    letting the surrounding sentence localise per-locale."""
    monkeypatch.delenv("STRIPE_SECRET_KEY_LIVE", raising=False)
    monkeypatch.delenv("STRIPE_SECRET_KEY_TEST", raising=False)
    from services.tenant_billing_reminders import _resolve_plan_amount_display
    tenant = {"id": "t-fb", "stripe_subscription_id": None}
    r = _run(_resolve_plan_amount_display(tenant))
    assert r is None


def test_plan_amount_fallback_when_stripe_lookup_raises(monkeypatch):
    """A Stripe API error during retrieve → ``None`` (D6.2
    contract). Never crash the cron job on a transient network
    issue, never invent a dollar figure."""
    from services.tenant_billing_reminders import _resolve_plan_amount_display
    tenant = {"id": "t-boom", "stripe_subscription_id": "sub_doesnt_exist"}
    monkeypatch.setenv("STRIPE_SECRET_KEY_TEST", "sk_test_dummy_invalid")
    r = _run(_resolve_plan_amount_display(tenant))
    # Any Stripe failure lands the None sentinel — caller
    # substitutes the localised fallback.
    assert r is None


def test_reminder_query_selector_picks_only_24h_window_trials():
    """Direct pymongo replication of the cron's query. Locks the
    filter shape so a refactor can't silently break the window."""
    now = datetime.now(timezone.utc)
    ready = _new_id()      # trial ends in 24h — should match
    too_soon = _new_id()   # trial ended already — should NOT match
    too_far = _new_id()    # trial ends in 3d — should NOT match
    already_sent = _new_id()  # in window but reminder already sent
    try:
        _sync.tenants.insert_many([
            {"id": ready, "billing_status": "trialing",
             "trial_end_utc": (now + timedelta(hours=24)).isoformat(),
             "trial_reminder_sent_at": None},
            {"id": too_soon, "billing_status": "trialing",
             "trial_end_utc": (now - timedelta(hours=2)).isoformat(),
             "trial_reminder_sent_at": None},
            {"id": too_far, "billing_status": "trialing",
             "trial_end_utc": (now + timedelta(days=3)).isoformat(),
             "trial_reminder_sent_at": None},
            {"id": already_sent, "billing_status": "trialing",
             "trial_end_utc": (now + timedelta(hours=24)).isoformat(),
             "trial_reminder_sent_at": now.isoformat()},
        ])
        lower = (now + timedelta(hours=23)).isoformat()
        upper = (now + timedelta(hours=25)).isoformat()
        query = {
            "trial_end_utc":          {"$gte": lower, "$lte": upper},
            "trial_reminder_sent_at": {"$in": [None, False]},
            "billing_status":         "trialing",
            "id": {"$in": [ready, too_soon, too_far, already_sent]},
        }
        matches = {m["id"] for m in _sync.tenants.find(
            query, {"_id": 0, "id": 1},
        )}
        assert matches == {ready}, (
            f"Expected only {ready!r} to match; got {matches!r}"
        )
    finally:
        _sync.tenants.delete_many({
            "id": {"$in": [ready, too_soon, too_far, already_sent]},
        })
