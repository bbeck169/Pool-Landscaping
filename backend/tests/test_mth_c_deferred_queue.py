"""MTH-C · Feb-2026 — Deferred AI-comms queue tests.

Locks:
  * ``compute_next_send_at`` finds the first future window in the
    tenant timezone.
  * ``enqueue_deferred`` persists the row.
  * ``flush_due`` sends entries whose scheduled_send_at is in the
    past.
  * Employee disabled DURING defer → drop with
    ``employee_disabled_during_defer``.
  * Master switch off DURING defer → drop with
    ``master_switch_disabled_during_defer``.
  * ``enabled=False`` on working_hours → deferred=False (caller
    sends immediately).
  * Tenant timezone respected — same UTC "now" gives different
    windows in different tenant tz.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from services.ai_comms.deferred_queue import (
    compute_next_send_at, enqueue_deferred, flush_due,
)
from tests._mth_c_helpers import mth_c_db, seed_rules_doc, run  # noqa: F401


_UTC = timezone.utc


def _wh(*, enabled=True, tz="America/Los_Angeles",
         windows=None):
    if windows is None:
        windows = [
            {"day": "mon", "start": "08:00", "end": "17:00"},
            {"day": "tue", "start": "08:00", "end": "17:00"},
        ]
    return {
        "enabled": enabled,
        "timezone": tz,
        "windows": windows,
    }


def _rules_with_wh(wh, employee_on=True):
    return {
        "tone_voice": {"style": "friendly", "custom_directive": ""},
        "employee_enable_disable": {"casey": employee_on},
        "working_hours": wh,
        "auto_action_allowlist": {},
        "escalation_rules": [],
    }


def test_compute_next_send_at_same_day_window():
    # Monday 2026-02-02 01:00 PT — the same-day 08:00 window is future.
    now = datetime(2026, 2, 2, 9, 0, tzinfo=_UTC)   # 01:00 PT
    nxt = compute_next_send_at(_wh(), deferred_at=now)
    assert nxt is not None
    # 08:00 PT Monday = 16:00 UTC Monday.
    assert nxt.hour == 16
    assert nxt.day == 2


def test_compute_next_send_at_after_hours_rolls_to_next_day():
    # Monday 2026-02-02 20:00 PT — Tuesday window fires next.
    now = datetime(2026, 2, 3, 4, 0, tzinfo=_UTC)   # 20:00 PT Mon
    nxt = compute_next_send_at(_wh(), deferred_at=now)
    assert nxt is not None
    assert nxt.day == 3  # 08:00 PT Tue = 16:00 UTC Tue.


def test_compute_next_send_at_enabled_false_returns_none():
    assert compute_next_send_at(_wh(enabled=False)) is None


def test_compute_next_send_at_no_windows_returns_none():
    assert compute_next_send_at(_wh(windows=[])) is None


def test_enqueue_deferred_persists_row(mth_c_db):
    now = datetime(2026, 2, 3, 4, 0, tzinfo=_UTC)
    r = run(enqueue_deferred(
        tenant_id="t1", employee_key="casey",
        payload_kind="email",
        payload={"to": "x@y.com", "subject": "s", "body": "b"},
        working_hours=_wh(), deferred_at=now,
    ))
    assert r["deferred"] is True
    assert len(mth_c_db.ai_comms_deferred_queue.rows) == 1
    row = mth_c_db.ai_comms_deferred_queue.rows[0]
    assert row["tenant_id"] == "t1"
    assert row["employee_key"] == "casey"
    assert row["deferred_reason"] == "outside_working_hours"


def test_enqueue_deferred_enabled_false_returns_send_now(mth_c_db):
    r = run(enqueue_deferred(
        tenant_id="t1", employee_key="casey",
        payload_kind="email", payload={"to": "a", "subject": "s", "body": "b"},
        working_hours=_wh(enabled=False),
    ))
    assert r["deferred"] is False
    assert r["reason"] == "no_future_window"
    assert mth_c_db.ai_comms_deferred_queue.rows == []


def test_flush_due_drops_when_master_switch_off(mth_c_db, monkeypatch):
    seed_rules_doc(mth_c_db, "t1", _rules_with_wh(_wh()), master=False)
    # Insert a due entry.
    past_ts = (datetime.now(_UTC) - timedelta(minutes=1)).timestamp()
    mth_c_db.ai_comms_deferred_queue.rows.append({
        "id": "e1", "tenant_id": "t1", "employee_key": "casey",
        "payload_kind": "email",
        "payload": {"to": "x", "subject": "s", "body": "b"},
        "scheduled_send_at": "past",
        "scheduled_send_at_ts": past_ts,
        "delivered": False, "delivery_error": None,
    })
    stats = run(flush_due())
    assert stats["dropped_master_switch"] == 1
    row = mth_c_db.ai_comms_deferred_queue.rows[0]
    assert row["delivered"] is False
    assert row["delivery_error"] == "master_switch_disabled_during_defer"


def test_flush_due_drops_when_employee_disabled(mth_c_db):
    seed_rules_doc(
        mth_c_db, "t1",
        _rules_with_wh(_wh(), employee_on=False),
        master=True,
    )
    past_ts = (datetime.now(_UTC) - timedelta(minutes=1)).timestamp()
    mth_c_db.ai_comms_deferred_queue.rows.append({
        "id": "e2", "tenant_id": "t1", "employee_key": "casey",
        "payload_kind": "email",
        "payload": {"to": "x", "subject": "s", "body": "b"},
        "scheduled_send_at": "past",
        "scheduled_send_at_ts": past_ts,
        "delivered": False, "delivery_error": None,
    })
    stats = run(flush_due())
    assert stats["dropped_employee_disabled"] == 1
    row = mth_c_db.ai_comms_deferred_queue.rows[0]
    assert row["delivery_error"] == "employee_disabled_during_defer"


def test_flush_due_delivers_when_all_gates_pass(mth_c_db, monkeypatch):
    seed_rules_doc(mth_c_db, "t1", _rules_with_wh(_wh()), master=True)
    past_ts = (datetime.now(_UTC) - timedelta(minutes=1)).timestamp()
    mth_c_db.ai_comms_deferred_queue.rows.append({
        "id": "e3", "tenant_id": "t1", "employee_key": "casey",
        "payload_kind": "email",
        "payload": {"to": "x@y.com", "subject": "s", "body": "b"},
        "scheduled_send_at": "past",
        "scheduled_send_at_ts": past_ts,
        "delivered": False, "delivery_error": None,
    })
    sent = []

    async def _fake_send_email(**kw):
        sent.append(kw)

    import services.comms_email_adapter as _cea
    monkeypatch.setattr(_cea, "send_email", _fake_send_email,
                          raising=False)
    stats = run(flush_due())
    assert stats["delivered"] == 1
    assert len(sent) == 1
    row = mth_c_db.ai_comms_deferred_queue.rows[0]
    assert row["delivered"] is True


def test_compute_next_send_at_tenant_tz_respected():
    now_utc = datetime(2026, 2, 2, 14, 0, tzinfo=_UTC)  # 06:00 PT Mon / 09:00 ET Mon
    # LA tenant with Mon 08:00 window → next fire is 08:00 PT Mon = 16:00 UTC.
    la_next = compute_next_send_at(
        _wh(tz="America/Los_Angeles"), deferred_at=now_utc,
    )
    ny_next = compute_next_send_at(
        _wh(tz="America/New_York"), deferred_at=now_utc,
    )
    # NY at 14:00 UTC (Mon 09:00 ET) is INSIDE the 08:00 window, so
    # the *next future* Mon 08:00 fire is a WEEK later.  LA still
    # picks up today's 08:00.
    assert la_next is not None and ny_next is not None
    assert la_next != ny_next
