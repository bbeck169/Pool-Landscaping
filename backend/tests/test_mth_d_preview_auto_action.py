"""MTH-D · Feb-2026 — preview_kind=auto_action_walkthrough tests."""
from __future__ import annotations

from services.tenant_ai_rules.preview import preview_rules
from tests._mth_c_helpers import mth_c_db, seed_rules_doc, run  # noqa: F401


def _base_rules(*, employee_key="marco_executive",
                 action_key="marco.create_admin_todo",
                 employee_on=True, allow="auto"):
    return {
        "tone_voice": {"style": "friendly", "custom_directive": ""},
        "employee_enable_disable": {employee_key: employee_on},
        "working_hours": {"enabled": False, "timezone": "UTC", "windows": []},
        "auto_action_allowlist": {action_key: allow},
        "escalation_rules": [],
    }


def test_all_pass_reason_chain_has_three_ok_entries(mth_c_db):
    seed_rules_doc(mth_c_db, "t1", _base_rules(), master=True)
    out = run(preview_rules(
        tenant_id="t1", category="auto_action_allowlist",
        pending_value={"marco.create_admin_todo": "auto"},
        preview_kind="auto_action_walkthrough",
        preview_input={
            "employee_key": "marco_executive",
            "action_key": "marco.create_admin_todo",
        },
    ))
    chain = out["output"]["reason_chain"]
    assert len(chain) == 3
    assert [c["check"] for c in chain] == [
        "master_switch", "employee_enabled", "action_allowlist",
    ]
    assert all(c["ok"] for c in chain)
    assert out["output"]["would_auto_execute"] is True
    assert "auto-executes" in out["output"]["final_verdict"]


def test_master_off_short_circuits_at_first_check(mth_c_db):
    seed_rules_doc(mth_c_db, "t1", _base_rules(), master=False)
    out = run(preview_rules(
        tenant_id="t1", category="auto_action_allowlist",
        pending_value={"marco.create_admin_todo": "auto"},
        preview_kind="auto_action_walkthrough",
        preview_input={
            "employee_key": "marco_executive",
            "action_key": "marco.create_admin_todo",
        },
    ))
    chain = out["output"]["reason_chain"]
    assert len(chain) == 1
    assert chain[0]["check"] == "master_switch"
    assert chain[0]["ok"] is False
    assert out["output"]["would_auto_execute"] is False


def test_employee_disabled_short_circuits_at_second_check(mth_c_db):
    seed_rules_doc(
        mth_c_db, "t1",
        _base_rules(employee_on=False), master=True,
    )
    out = run(preview_rules(
        tenant_id="t1", category="auto_action_allowlist",
        pending_value={"marco.create_admin_todo": "auto"},
        preview_kind="auto_action_walkthrough",
        preview_input={
            "employee_key": "marco_executive",
            "action_key": "marco.create_admin_todo",
        },
    ))
    chain = out["output"]["reason_chain"]
    assert len(chain) == 2
    assert chain[-1]["check"] == "employee_enabled"
    assert chain[-1]["ok"] is False


def test_allowlist_admin_approval_marks_final_check_failed(mth_c_db):
    seed_rules_doc(
        mth_c_db, "t1",
        _base_rules(allow="admin_approval"), master=True,
    )
    out = run(preview_rules(
        tenant_id="t1", category="auto_action_allowlist",
        pending_value={"marco.create_admin_todo": "admin_approval"},
        preview_kind="auto_action_walkthrough",
        preview_input={
            "employee_key": "marco_executive",
            "action_key": "marco.create_admin_todo",
        },
    ))
    chain = out["output"]["reason_chain"]
    assert chain[-1]["check"] == "action_allowlist"
    assert chain[-1]["ok"] is False
    assert out["output"]["would_auto_execute"] is False


def test_missing_scope_in_preview_input_raises_422(mth_c_db):
    seed_rules_doc(mth_c_db, "t1", _base_rules(), master=True)
    import pytest
    from services.tenant_ai_rules.preview import PreviewError
    with pytest.raises(PreviewError) as excinfo:
        run(preview_rules(
            tenant_id="t1", category="auto_action_allowlist",
            pending_value={"marco.create_admin_todo": "auto"},
            preview_kind="auto_action_walkthrough",
            preview_input={},
        ))
    assert excinfo.value.http_status == 422
