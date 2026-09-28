"""MTH-C · Feb-2026 — Escalation detector unit tests.

Locks:
  * Substring match (case-insensitive) when ``is_regex=False``.
  * Regex match when ``is_regex=True``.
  * Malformed regex → skipped, no crash.
  * First matching rule wins.
  * No match returns None.
"""
from __future__ import annotations

from services.tenant_ai_rules.gate import match_escalation


def test_substring_match_case_insensitive():
    rules = [{"keyword": "REFUND", "is_regex": False,
                "target_role": "admin", "sla_minutes": 5,
                "notify_channel": "email"}]
    hit = match_escalation("I want a refund now", rules)
    assert hit is not None
    assert hit["keyword"] == "REFUND"


def test_regex_match_when_flag_set():
    rules = [{"keyword": r"\brefund|cancel\b", "is_regex": True,
                "target_role": "admin", "sla_minutes": 5,
                "notify_channel": "email"}]
    assert match_escalation("please cancel my plan", rules) is not None
    assert match_escalation("no changes needed", rules) is None


def test_malformed_regex_is_skipped():
    rules = [
        {"keyword": "(unclosed", "is_regex": True,
         "target_role": "admin", "sla_minutes": 5,
         "notify_channel": "email"},
        {"keyword": "urgent", "is_regex": False,
         "target_role": "admin", "sla_minutes": 5,
         "notify_channel": "email"},
    ]
    hit = match_escalation("urgent request", rules)
    assert hit is not None
    assert hit["keyword"] == "urgent"


def test_first_match_wins():
    rules = [
        {"keyword": "refund", "is_regex": False,
         "target_role": "admin", "sla_minutes": 5,
         "notify_channel": "email"},
        {"keyword": "cancel", "is_regex": False,
         "target_role": "super", "sla_minutes": 10,
         "notify_channel": "sms"},
    ]
    hit = match_escalation("cancel then refund", rules)
    assert hit["keyword"] == "refund"


def test_no_match_returns_none():
    rules = [{"keyword": "refund", "is_regex": False,
                "target_role": "admin", "sla_minutes": 5,
                "notify_channel": "email"}]
    assert match_escalation("hello there", rules) is None


def test_empty_text_returns_none():
    rules = [{"keyword": "x"}]
    assert match_escalation("", rules) is None


def test_bad_rules_shape_returns_none():
    assert match_escalation("hi", "not-a-list") is None
    assert match_escalation("hi", [None, {"keyword": ""}]) is None
