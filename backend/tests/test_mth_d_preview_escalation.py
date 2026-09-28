"""MTH-D · Feb-2026 — preview_kind=escalation_match tests."""
from __future__ import annotations

from services.tenant_ai_rules.preview import preview_rules
from tests._mth_c_helpers import mth_c_db, seed_rules_doc, run  # noqa: F401


def _base_rules():
    return {
        "tone_voice": {"style": "friendly", "custom_directive": ""},
        "employee_enable_disable": {},
        "working_hours": {"enabled": False, "timezone": "UTC", "windows": []},
        "auto_action_allowlist": {},
        "escalation_rules": [],
    }


def test_pending_regex_rule_detects_test_messages(mth_c_db):
    seed_rules_doc(mth_c_db, "t1", _base_rules())
    pending = [{
        "keyword": r"\brefund|cancel\b", "is_regex": True,
        "target_role": "admin", "sla_minutes": 5,
        "notify_channel": "email",
    }]
    out = run(preview_rules(
        tenant_id="t1", category="escalation_rules",
        pending_value=pending,
        preview_kind="escalation_match",
        preview_input={"test_messages": [
            "please cancel my subscription",
            "no changes needed",
            "REFUND now",
        ]},
    ))
    results = out["output"]["results"]
    assert results[0]["matched_rule"] is not None
    assert "regex" in results[0]["reasoning"]
    assert results[1]["matched_rule"] is None
    assert results[2]["matched_rule"] is not None


def test_malformed_regex_surfaces_warning(mth_c_db):
    seed_rules_doc(mth_c_db, "t1", _base_rules())
    pending = [
        {"keyword": "(unclosed", "is_regex": True,
         "target_role": "admin", "sla_minutes": 5,
         "notify_channel": "email"},
        {"keyword": "urgent", "is_regex": False,
         "target_role": "admin", "sla_minutes": 5,
         "notify_channel": "email"},
    ]
    out = run(preview_rules(
        tenant_id="t1", category="escalation_rules",
        pending_value=pending,
        preview_kind="escalation_match",
        preview_input={"test_messages": ["urgent request"]},
    ))
    # Malformed regex on rule[0] flagged.
    assert any("rule[0]" in w and "malformed" in w for w in out["warnings"])
    # Second rule still matches.
    assert out["output"]["results"][0]["matched_rule"]["keyword"] == "urgent"


def test_first_match_wins_multi_rule(mth_c_db):
    seed_rules_doc(mth_c_db, "t1", _base_rules())
    pending = [
        {"keyword": "refund", "is_regex": False,
         "target_role": "admin", "sla_minutes": 5,
         "notify_channel": "email"},
        {"keyword": "cancel", "is_regex": False,
         "target_role": "super", "sla_minutes": 10,
         "notify_channel": "sms"},
    ]
    out = run(preview_rules(
        tenant_id="t1", category="escalation_rules",
        pending_value=pending,
        preview_kind="escalation_match",
        preview_input={"test_messages": ["cancel then refund"]},
    ))
    hit = out["output"]["results"][0]["matched_rule"]
    assert hit["keyword"] == "refund"


def test_over_5_messages_caps_and_warns(mth_c_db):
    seed_rules_doc(mth_c_db, "t1", _base_rules())
    pending = [{"keyword": "hi", "is_regex": False,
                "target_role": "admin", "sla_minutes": 5,
                "notify_channel": "email"}]
    out = run(preview_rules(
        tenant_id="t1", category="escalation_rules",
        pending_value=pending,
        preview_kind="escalation_match",
        preview_input={
            "test_messages": ["hi 1", "hi 2", "hi 3", "hi 4", "hi 5", "hi 6"],
        },
    ))
    assert len(out["output"]["results"]) == 5
    assert any("capped at 5" in w for w in out["warnings"])
