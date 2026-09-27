"""Feb-2026 · MARCO · Sub-phase D — task parser tests.

Locks the 6 utterance fixtures + non-todo rejection + past-date
rejection contracts for
``services.marco_task_parser.parse_todo_intent``.

LLM call is stubbed via monkeypatching
``call_llm_with_fallback`` so the tests are deterministic and
never touch the Emergent LLM key.  The stub returns whatever
JSON the fixture supplies; the parser then normalises the
``due_at`` via ``dateparser`` and coerces the priority via the
keyword sanity check.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ── Reference "now" for all fixtures ──────────────────────────────
# Wed 2026-02-11 15:00 UTC = Wed 2026-02-11 10:00 EST.
_FIXED_NOW = datetime(2026, 2, 11, 15, 0, tzinfo=timezone.utc)


def _stub_llm(monkeypatch, response: Dict[str, Any],
                error: Optional[str] = None):
    """Route ``call_llm_with_fallback`` through a stub.  The stub
    always returns the given parsed dict (mimics a well-behaved
    LLM in JSON-mode).  Set ``error`` to simulate an LLM failure
    and force the regex fallback path.
    """
    async def _fake(*_args, **_kwargs):
        if error:
            return {"error": error, "parsed": None}
        return {"error": None, "parsed": dict(response),
                  "raw": {"text": ""}}
    monkeypatch.setattr(
        "services.llm_provider.call_llm_with_fallback", _fake,
    )


# ══════════════════════════════════════════════════════════════════
# 1) "Remind me to call the Johnson family tomorrow at 3pm, high
#    priority"
# ══════════════════════════════════════════════════════════════════
def test_parse_johnson_family_tomorrow_3pm_high_priority(monkeypatch):
    from services.marco_task_parser import parse_todo_intent

    _stub_llm(monkeypatch, {
        "title": "Call the Johnson family",
        "due_at": "tomorrow 3pm",
        "priority": "high",
        "notes": "",
    })

    utter = ("Remind me to call the Johnson family tomorrow at 3pm,"
              " high priority")
    r = _run(parse_todo_intent(utter,
                                  user_tz="America/New_York",
                                  now=_FIXED_NOW))
    assert r is not None
    assert "Johnson family" in r["title"]
    assert r["priority"] == "high"
    # Due at should be within ±1 day of Feb-12 20:00 UTC
    # (2026-02-12 15:00 EST = 20:00 UTC).
    due = datetime.fromisoformat(r["due_at"].replace("Z", "+00:00"))
    expected = datetime(2026, 2, 12, 20, 0, tzinfo=timezone.utc)
    assert abs((due - expected).total_seconds()) < 86_400, (
        f"due_at {due} not within 1 day of {expected}"
    )


# ══════════════════════════════════════════════════════════════════
# 2) "Add a task: quarterly tax filing due end of month"
# ══════════════════════════════════════════════════════════════════
def test_parse_quarterly_tax_filing_end_of_month(monkeypatch):
    from services.marco_task_parser import parse_todo_intent

    _stub_llm(monkeypatch, {
        "title": "Quarterly tax filing",
        "due_at": "end of month",
        "priority": "med",
        "notes": "",
    })
    utter = "Add a task: quarterly tax filing due end of month"
    r = _run(parse_todo_intent(utter,
                                  user_tz="America/New_York",
                                  now=_FIXED_NOW))
    assert r is not None
    assert "tax filing" in r["title"].lower()
    assert r["priority"] == "med"
    # End of Feb is Feb 28, within a couple weeks of the fixed
    # reference.
    due = datetime.fromisoformat(r["due_at"].replace("Z", "+00:00"))
    assert due > _FIXED_NOW


# ══════════════════════════════════════════════════════════════════
# 3) "Follow up with Aqua Terra estimate next Tuesday morning"
# ══════════════════════════════════════════════════════════════════
def test_parse_aqua_terra_next_tuesday_morning(monkeypatch):
    from services.marco_task_parser import parse_todo_intent

    _stub_llm(monkeypatch, {
        "title": "Follow up with Aqua Terra estimate",
        "due_at": "next Tuesday 9am",
        "priority": "med",
        "notes": "",
    })
    utter = ("Follow up with Aqua Terra estimate next Tuesday"
              " morning")
    r = _run(parse_todo_intent(utter,
                                  user_tz="America/New_York",
                                  now=_FIXED_NOW))
    assert r is not None
    assert "Aqua Terra" in r["title"]
    # "next Tuesday" from Wed Feb 11 → Tue Feb 17.
    due = datetime.fromisoformat(r["due_at"].replace("Z", "+00:00"))
    expected = datetime(2026, 2, 17, 14, 0, tzinfo=timezone.utc)
    assert abs((due - expected).total_seconds()) < 86_400


# ══════════════════════════════════════════════════════════════════
# 4) "Urgent: check the pump at 456 Oak by end of day"
#    Priority keyword-based UPGRADE to urgent even if the LLM
#    stubbed 'med'.
# ══════════════════════════════════════════════════════════════════
def test_parse_urgent_pump_by_eod_keyword_upgrade(monkeypatch):
    from services.marco_task_parser import parse_todo_intent

    _stub_llm(monkeypatch, {
        "title": "Check the pump at 456 Oak",
        "due_at": "end of day",
        # LLM missed the 'urgent' cue — the keyword sanity check
        # bumps it up anyway.
        "priority": "med",
        "notes": "",
    })
    utter = "Urgent: check the pump at 456 Oak by end of day"
    r = _run(parse_todo_intent(utter,
                                  user_tz="America/New_York",
                                  now=_FIXED_NOW))
    assert r is not None
    assert r["priority"] == "urgent", (
        f"expected 'urgent' via keyword upgrade, got"
        f" {r['priority']!r}"
    )
    # Due within the same day (Feb 11 EOD EST → Feb 12 04:59 UTC).
    due = datetime.fromisoformat(r["due_at"].replace("Z", "+00:00"))
    assert due > _FIXED_NOW
    assert (due - _FIXED_NOW).total_seconds() < 86_400


# ══════════════════════════════════════════════════════════════════
# 5) "Schedule a review of Q1 marketing metrics in two weeks"
# ══════════════════════════════════════════════════════════════════
def test_parse_q1_marketing_metrics_in_two_weeks(monkeypatch):
    from services.marco_task_parser import parse_todo_intent

    _stub_llm(monkeypatch, {
        "title": "Review Q1 marketing metrics",
        "due_at": "in 2 weeks",
        "priority": "med",
        "notes": "",
    })
    utter = ("Schedule a review of Q1 marketing metrics in two"
              " weeks")
    r = _run(parse_todo_intent(utter,
                                  user_tz="America/New_York",
                                  now=_FIXED_NOW))
    assert r is not None
    assert "Q1 marketing" in r["title"]
    # +2 weeks from Feb 11 = Feb 25.
    due = datetime.fromisoformat(r["due_at"].replace("Z", "+00:00"))
    expected = _FIXED_NOW + timedelta(weeks=2)
    assert abs((due - expected).total_seconds()) < 86_400


# ══════════════════════════════════════════════════════════════════
# 6) "Note to self, buy office coffee this week"
# ══════════════════════════════════════════════════════════════════
def test_parse_note_to_self_office_coffee_this_week(monkeypatch):
    from services.marco_task_parser import parse_todo_intent

    _stub_llm(monkeypatch, {
        "title": "Buy office coffee",
        "due_at": "this Friday",
        "priority": "low",
        "notes": "",
    })
    utter = "Note to self, buy office coffee this week"
    r = _run(parse_todo_intent(utter,
                                  user_tz="America/New_York",
                                  now=_FIXED_NOW))
    assert r is not None
    assert r["title"] == "Buy office coffee"
    assert r["priority"] == "low"


# ══════════════════════════════════════════════════════════════════
# 7) Non-todo utterance — heuristic filter short-circuits, LLM
#    never called.
# ══════════════════════════════════════════════════════════════════
def test_parse_returns_none_for_non_todo_utterance(monkeypatch):
    from services.marco_task_parser import parse_todo_intent

    _llm_called = {"n": 0}
    async def _spy_llm(*_a, **_k):
        _llm_called["n"] += 1
        return {"error": None, "parsed": {}}
    monkeypatch.setattr(
        "services.llm_provider.call_llm_with_fallback", _spy_llm,
    )

    r = _run(parse_todo_intent("What's the weather today?",
                                  user_tz="America/New_York",
                                  now=_FIXED_NOW))
    assert r is None
    # Heuristic short-circuited — no LLM call fired.
    assert _llm_called["n"] == 0


# ══════════════════════════════════════════════════════════════════
# 8) Past-date rejection — due_at more than 5 min in the past.
# ══════════════════════════════════════════════════════════════════
def test_due_at_is_in_past_helper_rejects_stale_timestamps():
    from services.marco_task_parser import due_at_is_in_past

    now = datetime(2026, 2, 11, 15, 0, tzinfo=timezone.utc)

    # 10 minutes ago — REJECT.
    past = (now - timedelta(minutes=10)).isoformat().replace(
        "+00:00", "Z",
    )
    assert due_at_is_in_past(past, now=now) is True

    # 3 minutes ago — WITHIN 5-min tolerance, ACCEPT.
    edge = (now - timedelta(minutes=3)).isoformat().replace(
        "+00:00", "Z",
    )
    assert due_at_is_in_past(edge, now=now) is False

    # Future — ACCEPT.
    future = (now + timedelta(hours=1)).isoformat().replace(
        "+00:00", "Z",
    )
    assert due_at_is_in_past(future, now=now) is False


# ══════════════════════════════════════════════════════════════════
# 9) Priority keyword-based DOWNGRADE — "whenever" → low.
# ══════════════════════════════════════════════════════════════════
def test_parse_priority_keyword_downgrade_whenever(monkeypatch):
    from services.marco_task_parser import parse_todo_intent

    _stub_llm(monkeypatch, {
        "title": "Update the vendor list",
        "due_at": "this Friday",
        "priority": "med",
        "notes": "",
    })
    r = _run(parse_todo_intent(
        "Remind me to update the vendor list whenever, no rush",
        user_tz="America/New_York", now=_FIXED_NOW,
    ))
    assert r is not None
    assert r["priority"] == "low"


# ══════════════════════════════════════════════════════════════════
# 10) LLM failure → regex fallback still returns a plausible todo.
# ══════════════════════════════════════════════════════════════════
def test_parse_falls_back_to_regex_when_llm_fails(monkeypatch):
    from services.marco_task_parser import parse_todo_intent

    _stub_llm(monkeypatch, {}, error="cap_exceeded")

    r = _run(parse_todo_intent(
        "Remind me to call the plumber tomorrow at 10am",
        user_tz="America/New_York", now=_FIXED_NOW,
    ))
    # Regex fallback picks up "tomorrow at 10am" and dateparser
    # resolves it.  Title is the raw utterance minus filler.
    assert r is not None
    assert r["due_at"], "regex-fallback path must resolve a due_at"
    due = datetime.fromisoformat(r["due_at"].replace("Z", "+00:00"))
    assert due > _FIXED_NOW
