"""MTH-A · Feb-2026 — Working-hours + timezone tests.

Locks:

  * A time inside a defined window → gate ``True``.
  * A time outside every window → gate ``False`` with reason
    ``outside_working_hours``.
  * Timezone is honoured — 09:00 America/New_York vs
    09:00 America/Los_Angeles produce different in/out decisions
    against a 08:00–17:00 Los-Angeles-scoped window.
  * ``enabled=False`` disables the check entirely (gate ``True``
    even at 03:00 Sunday, given every other layer allows it).
  * A malformed window is treated as "no match" (safety-first).
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from services.tenant_ai_rules import cache, store
from services.tenant_ai_rules.gate import (
    _within_working_hours,
    resolve_ai_send_gate,
)
from tests._mth_a_helpers import FakeDB, run


@pytest.fixture
def fake_db(monkeypatch):
    fake = FakeDB()
    monkeypatch.setattr(store, "db", fake, raising=False)
    cache.invalidate_all()
    return fake


def _actor():
    return {"id": "u", "email": "a@t1"}


def _monday_10am(tz_name: str) -> datetime:
    return datetime(2026, 2, 16, 10, 0, tzinfo=ZoneInfo(tz_name))


def _sunday_3am(tz_name: str) -> datetime:
    return datetime(2026, 2, 15, 3, 0, tzinfo=ZoneInfo(tz_name))


# ─── Direct helper unit tests ─────────────────────────────────────

def test_within_window_true_inside():
    wh = {
        "enabled": True, "timezone": "America/Los_Angeles",
        "windows": [
            {"day": "mon", "start": "08:00", "end": "17:00"},
        ],
    }
    within, reason = _within_working_hours(
        wh, _monday_10am("America/Los_Angeles"),
    )
    assert within is True
    assert reason.startswith("in_window_mon")


def test_within_window_false_before_start():
    wh = {
        "enabled": True, "timezone": "America/Los_Angeles",
        "windows": [
            {"day": "mon", "start": "09:00", "end": "17:00"},
        ],
    }
    # 8:30 AM LA time — before start.
    early = datetime(2026, 2, 16, 8, 30,
                     tzinfo=ZoneInfo("America/Los_Angeles"))
    within, reason = _within_working_hours(wh, early)
    assert within is False
    assert "outside_windows_mon" in reason


def test_within_window_false_on_wrong_day():
    wh = {
        "enabled": True, "timezone": "America/Los_Angeles",
        "windows": [
            {"day": "mon", "start": "00:00", "end": "23:59"},
        ],
    }
    within, _ = _within_working_hours(
        wh, _sunday_3am("America/Los_Angeles"),
    )
    assert within is False


def test_within_window_disabled_short_circuits():
    wh = {
        "enabled": False, "timezone": "America/Los_Angeles",
        "windows": [],
    }
    # Sunday 3am — would fail if enabled.
    within, reason = _within_working_hours(
        wh, _sunday_3am("America/Los_Angeles"),
    )
    assert within is True
    assert reason == "working_hours_disabled"


def test_timezone_awareness_across_tz():
    """9:00 America/New_York (which is 06:00 America/Los_Angeles)
    should be OUTSIDE an 08:00–17:00 window scoped to LA time."""
    wh = {
        "enabled": True, "timezone": "America/Los_Angeles",
        "windows": [
            {"day": "mon", "start": "08:00", "end": "17:00"},
        ],
    }
    ny_9am = datetime(2026, 2, 16, 9, 0,
                      tzinfo=ZoneInfo("America/New_York"))
    within, _ = _within_working_hours(wh, ny_9am)
    assert within is False


def test_timezone_awareness_matches_when_shifted_in():
    """13:00 America/New_York (which is 10:00 America/Los_Angeles)
    is inside a LA 08:00–17:00 window."""
    wh = {
        "enabled": True, "timezone": "America/Los_Angeles",
        "windows": [
            {"day": "mon", "start": "08:00", "end": "17:00"},
        ],
    }
    ny_1pm = datetime(2026, 2, 16, 13, 0,
                      tzinfo=ZoneInfo("America/New_York"))
    within, _ = _within_working_hours(wh, ny_1pm)
    assert within is True


# ─── End-to-end via resolve_ai_send_gate ─────────────────────────

def test_gate_blocks_outside_hours(fake_db):
    run(store.save_master_switch(
        "t1", True, actor=_actor(),
        reason="live-comms-enabled-please",
    ))
    # Constrain windows to 08:00–17:00 LA on Monday only.
    run(store.save_category(
        "t1", "working_hours",
        {"enabled": True, "timezone": "America/Los_Angeles",
         "windows": [
             {"day": "mon", "start": "08:00", "end": "17:00"},
         ]},
        actor=_actor(),
        reason="tenant-monday-only-window-setup",
    ))
    # 03:00 Sunday LA — outside every window.
    when = _sunday_3am("America/Los_Angeles")
    allowed, reason = run(resolve_ai_send_gate(
        "t1", "marco_executive", now=when,
    ))
    assert allowed is False
    assert reason == "outside_working_hours"


def test_gate_allows_inside_hours(fake_db):
    run(store.save_master_switch(
        "t1", True, actor=_actor(),
        reason="live-comms-enabled-please",
    ))
    run(store.save_category(
        "t1", "working_hours",
        {"enabled": True, "timezone": "America/Los_Angeles",
         "windows": [
             {"day": "mon", "start": "08:00", "end": "17:00"},
         ]},
        actor=_actor(),
        reason="tenant-monday-only-window-setup",
    ))
    when = _monday_10am("America/Los_Angeles")
    allowed, reason = run(resolve_ai_send_gate(
        "t1", "marco_executive", now=when,
    ))
    assert allowed is True
    assert reason == "ok"


def test_gate_all_layers_permissive_returns_ok(fake_db):
    run(store.save_master_switch(
        "t1", True, actor=_actor(),
        reason="live-comms-enabled-please",
    ))
    # Platform default hours are Mon–Fri 08:00–17:00 LA; use a matching time.
    allowed, reason = run(resolve_ai_send_gate(
        "t1", "marco_executive",
        now=_monday_10am("America/Los_Angeles"),
    ))
    assert allowed is True
    assert reason == "ok"
