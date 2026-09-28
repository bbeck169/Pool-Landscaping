"""MTH-A · Feb-2026 — Escalation keyword + regex tests.

Locks the contract for
:func:`services.tenant_ai_rules.gate.match_escalation`:

  * Default keyword mode: case-insensitive substring match on the
    message text.
  * Opt-in ``is_regex=True``: keyword compiled and matched via
    :func:`re.search` (case-insensitive).
  * First matching rule wins (rule order matters).
  * Malformed regex → skipped (WARN) — never crashes the gate.
  * No match → ``None``.
  * Validation rejects invalid regex at save time so admins spot
    the typo before rollout.
"""
from __future__ import annotations

import logging

import pytest

from services.tenant_ai_rules import cache, store
from services.tenant_ai_rules.gate import match_escalation
from services.tenant_ai_rules.schema import validate_category_payload
from tests._mth_a_helpers import FakeDB, run


@pytest.fixture
def fake_db(monkeypatch):
    fake = FakeDB()
    monkeypatch.setattr(store, "db", fake, raising=False)
    cache.invalidate_all()
    return fake


def test_keyword_substring_case_insensitive():
    rules = [
        {"keyword": "REFUND", "is_regex": False,
         "target_role": "admin", "sla_minutes": 5,
         "notify_channel": "email"},
    ]
    hit = match_escalation("Please issue a refund now.", rules)
    assert hit is not None
    assert hit["keyword"] == "REFUND"


def test_regex_matches_with_is_regex_true():
    rules = [
        {"keyword": r"charge\s*back", "is_regex": True,
         "target_role": "super", "sla_minutes": 5,
         "notify_channel": "sms"},
    ]
    hit = match_escalation(
        "Customer filed a CHARGEBACK on invoice 42", rules,
    )
    assert hit is not None
    assert hit["target_role"] == "super"


def test_first_match_wins_and_order_matters():
    rules = [
        {"keyword": "cancel", "is_regex": False,
         "target_role": "admin", "sla_minutes": 15,
         "notify_channel": "email"},
        {"keyword": "refund", "is_regex": False,
         "target_role": "super", "sla_minutes": 5,
         "notify_channel": "both"},
    ]
    hit = match_escalation(
        "Please cancel and refund the invoice", rules,
    )
    assert hit["keyword"] == "cancel"          # first rule wins


def test_no_match_returns_none():
    rules = [
        {"keyword": "urgent", "is_regex": False,
         "target_role": "admin", "sla_minutes": 5,
         "notify_channel": "email"},
    ]
    assert match_escalation("all good, thanks!", rules) is None


def test_empty_text_or_rules_returns_none():
    assert match_escalation("", [{"keyword": "x"}]) is None
    assert match_escalation("something", []) is None
    assert match_escalation("something", None) is None


def test_malformed_regex_skipped_with_warn(caplog):
    caplog.set_level(logging.WARNING)
    rules = [
        {"keyword": "[bad(regex", "is_regex": True,
         "target_role": "admin", "sla_minutes": 5,
         "notify_channel": "email"},
        {"keyword": "refund", "is_regex": False,
         "target_role": "super", "sla_minutes": 5,
         "notify_channel": "email"},
    ]
    hit = match_escalation("Please issue a refund", rules)
    assert hit is not None
    assert hit["keyword"] == "refund"
    assert any("escalation regex compile failed" in r.getMessage()
               for r in caplog.records)


def test_validation_rejects_invalid_regex_at_save_time():
    with pytest.raises(Exception) as exc:
        validate_category_payload("escalation_rules", [
            {"keyword": "[bad(regex", "is_regex": True,
             "target_role": "admin", "sla_minutes": 5,
             "notify_channel": "email"},
        ])
    msg = str(exc.value).lower()
    assert "regex" in msg


def test_validation_rejects_bad_channel():
    with pytest.raises(Exception) as exc:
        validate_category_payload("escalation_rules", [
            {"keyword": "refund", "target_role": "admin",
             "sla_minutes": 5, "notify_channel": "carrier_pigeon"},
        ])
    assert "notify_channel" in str(exc.value)


def test_end_to_end_via_stored_rules(fake_db):
    run(store.save_category(
        "t1", "escalation_rules",
        [{"keyword": r"\bcharge\s*back\b", "is_regex": True,
          "target_role": "super", "sla_minutes": 15,
          "notify_channel": "both"}],
        actor={"id": "u", "email": "a@t1"},
        reason="adding-chargeback-regex-esc-rule",
    ))
    head = run(store.get_tenant_rules("t1"))
    hit = match_escalation(
        "Watch out — chargeback filed on this account",
        head["rules"]["escalation_rules"],
    )
    assert hit is not None
    assert hit["notify_channel"] == "both"
