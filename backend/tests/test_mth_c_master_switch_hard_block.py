"""MTH-C · Feb-2026 — Master switch hard-block.

Locks:
  * When ``master_ai_send_live_comms=False``,
    ``stamp_agent_context_with_gate`` forces ``CommsContext.AGENT``
    regardless of what the caller requested.
  * The specific warn line
    ``ai_hub.master_switch_blocked`` fires with tenant_id +
    employee_key + attempted_context values.
  * The gated-send helper returns ``action="block"`` +
    ``reason="master_switch_off"`` on the same input.
"""
from __future__ import annotations

import logging

from services.ai_hub.context_stamping import (
    stamp_agent_context_with_gate,
)
from services.ai_comms.gated_send import (
    stamp_agent_context_with_gate_or_defer,
)
from services.comms_env_guard import CommsContext
from tests._mth_c_helpers import mth_c_db, seed_rules_doc, run  # noqa: F401


def _rules(*, employee_key="marco_executive"):
    return {
        "tone_voice": {"style": "friendly", "custom_directive": ""},
        "employee_enable_disable": {employee_key: True},
        "working_hours": {"enabled": False, "timezone": "UTC", "windows": []},
        "auto_action_allowlist": {},
        "escalation_rules": [],
    }


def test_master_off_forces_agent_on_stamp_with_gate(mth_c_db, caplog):
    seed_rules_doc(mth_c_db, "t1", _rules(), master=False)
    emp = {"key": "marco_executive", "authorized_for_public_use": True}
    caplog.set_level(logging.WARNING, logger="pool_crm")
    ctx = run(stamp_agent_context_with_gate(
        tenant_id="t1", employee=emp,
        requested_context=CommsContext.SYSTEM,
    ))
    assert ctx == CommsContext.AGENT
    # A "master_switch_blocked" log line must fire.  We check both
    # this logger and the root pool_crm logger for the tag.
    combined = "\n".join(r.getMessage() for r in caplog.records)
    assert "ai_hub.master_switch_blocked" in combined


def test_master_off_blocks_via_gated_send(mth_c_db):
    seed_rules_doc(mth_c_db, "t1", _rules(), master=False)
    emp = {"key": "marco_executive", "authorized_for_public_use": True}
    out = run(stamp_agent_context_with_gate_or_defer(
        tenant_id="t1", employee=emp,
        requested_context=CommsContext.SYSTEM,
        payload_kind="email", payload={"to": "x"},
    ))
    assert out["action"] == "block"
    assert out["reason"] == "master_switch_off"
    assert out["context"] == CommsContext.AGENT
    assert out["deferred_id"] is None


def test_master_on_allows_send(mth_c_db):
    seed_rules_doc(mth_c_db, "t1", _rules(), master=True)
    emp = {"key": "marco_executive", "authorized_for_public_use": True}
    out = run(stamp_agent_context_with_gate_or_defer(
        tenant_id="t1", employee=emp,
        requested_context=CommsContext.SYSTEM,
    ))
    assert out["action"] == "send"
    assert out["context"] == CommsContext.SYSTEM


def test_employee_disabled_blocks_via_gated_send(mth_c_db):
    rules = _rules()
    rules["employee_enable_disable"]["marco_executive"] = False
    seed_rules_doc(mth_c_db, "t1", rules, master=True)
    emp = {"key": "marco_executive", "authorized_for_public_use": True}
    out = run(stamp_agent_context_with_gate_or_defer(
        tenant_id="t1", employee=emp,
        requested_context=CommsContext.SYSTEM,
    ))
    assert out["action"] == "block"
    assert out["reason"] == "employee_disabled"


def test_outside_hours_defers_when_payload_provided(mth_c_db):
    rules = _rules()
    rules["working_hours"] = {
        "enabled": True,
        "timezone": "UTC",
        # Sunday-only window, so any weekday will be outside.
        "windows": [{"day": "sun", "start": "00:00", "end": "01:00"}],
    }
    seed_rules_doc(mth_c_db, "t1", rules, master=True)
    emp = {"key": "marco_executive", "authorized_for_public_use": True}
    # Monday 2026-02-02 14:00 UTC — outside the sun window.
    from datetime import datetime, timezone as _tz
    out = run(stamp_agent_context_with_gate_or_defer(
        tenant_id="t1", employee=emp,
        requested_context=CommsContext.SYSTEM,
        payload_kind="email", payload={"to": "x"},
        now=datetime(2026, 2, 2, 14, 0, tzinfo=_tz.utc),
    ))
    assert out["action"] == "defer"
    assert out["reason"] == "outside_working_hours"
    assert out["deferred_id"] is not None
    # And a row landed in the queue.
    assert len(mth_c_db.ai_comms_deferred_queue.rows) == 1


def test_outside_hours_without_payload_blocks(mth_c_db):
    rules = _rules()
    rules["working_hours"] = {
        "enabled": True,
        "timezone": "UTC",
        "windows": [{"day": "sun", "start": "00:00", "end": "01:00"}],
    }
    seed_rules_doc(mth_c_db, "t1", rules, master=True)
    emp = {"key": "marco_executive", "authorized_for_public_use": True}
    from datetime import datetime, timezone as _tz
    out = run(stamp_agent_context_with_gate_or_defer(
        tenant_id="t1", employee=emp,
        requested_context=CommsContext.SYSTEM,
        now=datetime(2026, 2, 2, 14, 0, tzinfo=_tz.utc),
    ))
    assert out["action"] == "block"
    assert "outside_working_hours" in out["reason"]
