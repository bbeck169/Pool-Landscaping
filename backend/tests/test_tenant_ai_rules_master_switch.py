"""MTH-A · Feb-2026 — Master safety switch tests.

Locks:

  * Default state is OFF (``master_ai_send_live_comms=False``) for
    every tenant.
  * Every master-switch flip writes a revision snapshot.
  * OFF → :func:`resolve_ai_send_gate` refuses regardless of
    per-employee or working-hours state.
  * Reason < 8 chars → ``reason_too_short``.
  * Non-boolean value → ``invalid_master_switch_value``.
"""
from __future__ import annotations

import pytest

from services.tenant_ai_rules import cache, store
from services.tenant_ai_rules.gate import resolve_ai_send_gate
from services.tenant_ai_rules.resolver import resolve_rules_for_tenant
from tests._mth_a_helpers import FakeDB, run


@pytest.fixture
def fake_db(monkeypatch):
    fake = FakeDB()
    monkeypatch.setattr(store, "db", fake, raising=False)
    cache.invalidate_all()
    return fake


def _actor():
    return {"id": "u-super", "email": "super@ops",
            "name": "Sam Super"}


def test_default_master_switch_is_off(fake_db):
    resolved = run(resolve_rules_for_tenant("t1"))
    assert resolved["master_ai_send_live_comms"] is False


def test_flip_master_switch_writes_revision(fake_db):
    run(store.save_master_switch(
        "t1", True, actor=_actor(),
        reason="tenant-go-live-with-ai-comms",
    ))
    head = run(store.get_tenant_rules("t1"))
    assert head["master_ai_send_live_comms"] is True
    assert head["revision_number"] == 1
    revs = run(store.list_revisions("t1"))
    assert revs[0]["master_ai_send_live_comms"] is True


def test_master_switch_off_blocks_gate(fake_db):
    """Even with EVERY other condition permissive, master=False
    forces the gate closed."""
    run(store.save_master_switch(
        "t1", False, actor=_actor(),
        reason="temporary-halt-of-ai-comms-req",
    ))
    allowed, reason = run(resolve_ai_send_gate("t1", None))
    assert allowed is False
    assert reason == "master_switch_off"


def test_master_switch_on_still_needs_hours_and_employee(fake_db):
    # Master ON, out-of-hours + unknown employee → still blocked.
    run(store.save_master_switch(
        "t1", True, actor=_actor(),
        reason="tenant-goes-live-with-ai-comms",
    ))
    run(store.save_category(
        "t1", "working_hours",
        {"enabled": True, "timezone": "UTC",
         "windows": [
             {"day": "mon", "start": "00:00", "end": "23:59"},
         ]},
        actor=_actor(),
        reason="setting-working-hours-mon-only",
    ))
    # An unknown employee_key → gate refuses.
    allowed, reason = run(resolve_ai_send_gate(
        "t1", "nonexistent_employee",
    ))
    assert allowed is False
    assert reason == "employee_disabled"


def test_short_reason_rejected(fake_db):
    with pytest.raises(store.RuleStoreError) as exc:
        run(store.save_master_switch(
            "t1", True, actor=_actor(), reason="tiny",
        ))
    assert exc.value.error_code == "reason_too_short"


def test_non_bool_rejected(fake_db):
    with pytest.raises(store.RuleStoreError) as exc:
        run(store.save_master_switch(
            "t1", "yes", actor=_actor(),
            reason="attempt-to-set-string-value",
        ))
    assert exc.value.error_code == "invalid_master_switch_value"


def test_flip_off_then_on_leaves_two_revisions(fake_db):
    run(store.save_master_switch(
        "t1", True, actor=_actor(),
        reason="first-turn-on-ai-comms-batch",
    ))
    run(store.save_master_switch(
        "t1", False, actor=_actor(),
        reason="incident-response-shutdown-req",
    ))
    revs = run(store.list_revisions("t1"))
    assert [r["revision_number"] for r in revs] == [2, 1]
    assert revs[0]["master_ai_send_live_comms"] is False
    assert revs[1]["master_ai_send_live_comms"] is True
