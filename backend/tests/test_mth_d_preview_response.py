"""MTH-D · Feb-2026 — preview_kind=response tests.

Locks:
  * With a formal-tone overlay the returned prompt_preview
    contains the formal preamble.
  * Sample response comes back through the mocked LLM call.
  * LLM-unavailable path returns ``output.error="llm_unavailable"``
    with a legible message and no crash.
  * The preview call does NOT insert into ``ai_employee_actions``,
    ``ai_employee_messages`` or debit credits.
"""
from __future__ import annotations

from services.tenant_ai_rules.preview import preview_rules
from tests._mth_c_helpers import mth_c_db, seed_rules_doc, run  # noqa: F401


def _base_rules(style="friendly"):
    return {
        "tone_voice": {"style": style, "custom_directive": ""},
        "employee_enable_disable": {},
        "working_hours": {"enabled": False, "timezone": "UTC", "windows": []},
        "auto_action_allowlist": {},
        "escalation_rules": [],
    }


def test_response_preview_uses_pending_formal_tone(mth_c_db, monkeypatch):
    seed_rules_doc(mth_c_db, "t1", _base_rules("friendly"))

    async def _fake_llm(**kw):
        return {
            "raw": "Good afternoon. Your service report is attached.",
            "provider": "emergent",
            "model": "claude-sonnet-4-5",
        }

    monkeypatch.setattr(
        "services.llm_provider.call_llm_with_fallback",
        _fake_llm, raising=True,
    )
    out = run(preview_rules(
        tenant_id="t1",
        category="tone_voice",
        pending_value={"style": "formal", "custom_directive": ""},
        preview_kind="response",
        preview_input={"user_message": "When can you come?"},
    ))
    assert out["preview_kind"] == "response"
    prompt = out["output"]["prompt_preview"]
    assert "Respond with professional" in prompt
    assert out["output"]["sample_response"].startswith("Good afternoon")
    assert out["output"]["provider"] == "emergent"
    # Overlay flagged in the resolved snapshot.
    assert out["resolved_rules_snapshot"]["overlay_applied"] is True


def test_response_preview_llm_error_returns_legible_message(
    mth_c_db, monkeypatch,
):
    seed_rules_doc(mth_c_db, "t1", _base_rules("friendly"))

    async def _fake_llm(**kw):
        return {"error": "openai_disabled", "provider": "openai"}

    monkeypatch.setattr(
        "services.llm_provider.call_llm_with_fallback",
        _fake_llm, raising=True,
    )
    out = run(preview_rules(
        tenant_id="t1",
        category="tone_voice",
        pending_value={"style": "formal", "custom_directive": ""},
        preview_kind="response",
        preview_input={},
    ))
    assert out["output"]["error"] == "llm_unavailable"
    assert "openai_disabled" in out["output"]["message"]
    assert "sample_response" not in out["output"]


def test_response_preview_llm_raises_returns_legible_message(
    mth_c_db, monkeypatch,
):
    seed_rules_doc(mth_c_db, "t1", _base_rules("friendly"))

    async def _boom(**kw):
        raise RuntimeError("network down")

    monkeypatch.setattr(
        "services.llm_provider.call_llm_with_fallback",
        _boom, raising=True,
    )
    out = run(preview_rules(
        tenant_id="t1",
        category="tone_voice",
        pending_value={"style": "friendly", "custom_directive": ""},
        preview_kind="response",
        preview_input={},
    ))
    assert out["output"]["error"] == "llm_unavailable"


def test_response_preview_has_no_side_effects_on_db(mth_c_db, monkeypatch):
    seed_rules_doc(mth_c_db, "t1", _base_rules("friendly"))
    before_actions = list(mth_c_db.ai_employee_actions.rows)
    before_msgs = list(mth_c_db.ai_employee_messages.rows) if hasattr(
        mth_c_db, "ai_employee_messages",
    ) else []

    async def _fake_llm(**kw):
        return {"raw": "hi", "provider": "emergent"}

    monkeypatch.setattr(
        "services.llm_provider.call_llm_with_fallback",
        _fake_llm, raising=True,
    )
    for _ in range(3):
        run(preview_rules(
            tenant_id="t1", category="tone_voice",
            pending_value={"style": "friendly", "custom_directive": ""},
            preview_kind="response",
            preview_input={},
        ))
    assert list(mth_c_db.ai_employee_actions.rows) == before_actions
    if hasattr(mth_c_db, "ai_employee_messages"):
        assert list(mth_c_db.ai_employee_messages.rows) == before_msgs


def test_response_preview_llm_capped_at_max_tokens(mth_c_db, monkeypatch):
    seed_rules_doc(mth_c_db, "t1", _base_rules("friendly"))
    seen_max = {}

    async def _fake_llm(**kw):
        seen_max["max_tokens"] = kw.get("max_tokens")
        return {"raw": "ok", "provider": "emergent"}

    monkeypatch.setattr(
        "services.llm_provider.call_llm_with_fallback",
        _fake_llm, raising=True,
    )
    run(preview_rules(
        tenant_id="t1", category="tone_voice",
        pending_value={"style": "friendly", "custom_directive": ""},
        preview_kind="response", preview_input={},
    ))
    # Contract locked at 400 to keep preview responses short.
    assert seen_max["max_tokens"] == 400
