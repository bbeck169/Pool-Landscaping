"""MTH-C · Feb-2026 — Auto-approval gate unit tests.

Locks:
  * All 3 conditions True → auto=True, rule_source populated.
  * Any of the 3 False → auto=False with the right reason.
  * Master switch off dominates over allowlist="auto".
  * Missing scope arguments → False with reason=missing_scope.
"""
from __future__ import annotations

from services.ai_employee_actions.auto_approval import (
    should_auto_execute, write_audit,
)
from tests._mth_c_helpers import mth_c_db, seed_rules_doc, run  # noqa: F401


def _rules(*, employee_key: str = "casey",
            employee_on: bool = True,
            action_key: str = "casey.draft_outreach_reply",
            allow: str = "auto"):
    return {
        "tone_voice": {"style": "friendly", "custom_directive": ""},
        "employee_enable_disable": {employee_key: employee_on},
        "working_hours": {"enabled": False, "timezone": "UTC", "windows": []},
        "auto_action_allowlist": {action_key: allow},
        "escalation_rules": [],
    }


def test_all_conditions_true_auto_true(mth_c_db):
    seed_rules_doc(mth_c_db, "t1", _rules(), master=True)
    out = run(should_auto_execute(
        "t1", "casey.draft_outreach_reply", "casey",
    ))
    assert out["auto"] is True
    assert out["reason"] == "ok"
    assert out["rule_source"] in {"tenant", "platform"}


def test_master_switch_off_dominates_allowlist(mth_c_db):
    seed_rules_doc(mth_c_db, "t1", _rules(), master=False)
    out = run(should_auto_execute(
        "t1", "casey.draft_outreach_reply", "casey",
    ))
    assert out["auto"] is False
    assert out["reason"] == "master_switch_off"


def test_employee_disabled_returns_false(mth_c_db):
    seed_rules_doc(mth_c_db, "t1", _rules(employee_on=False), master=True)
    out = run(should_auto_execute(
        "t1", "casey.draft_outreach_reply", "casey",
    ))
    assert out["auto"] is False
    assert out["reason"] == "employee_disabled"


def test_allowlist_admin_approval_returns_false(mth_c_db):
    seed_rules_doc(
        mth_c_db, "t1", _rules(allow="admin_approval"), master=True,
    )
    out = run(should_auto_execute(
        "t1", "casey.draft_outreach_reply", "casey",
    ))
    assert out["auto"] is False
    assert "admin_approval" in out["reason"]


def test_missing_scope_returns_false(mth_c_db):
    out = run(should_auto_execute(None, "x", "y"))
    assert out["auto"] is False
    assert out["reason"] == "missing_scope"


def test_write_audit_persists_row(mth_c_db):
    run(write_audit(
        tenant_id="t1", action_id="a1",
        action_key="casey.draft_outreach_reply",
        employee_key="casey",
        rule_source="tenant",
        reason="auto_action_allowlist",
    ))
    assert len(mth_c_db.ai_action_audit.rows) == 1
    row = mth_c_db.ai_action_audit.rows[0]
    assert row["action_id"] == "a1"
    assert row["kind"] == "auto_approval"
    assert row["rule_source"] == "tenant"
