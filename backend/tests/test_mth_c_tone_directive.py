"""MTH-C · Feb-2026 — tone directive builder unit tests."""
import pytest
from services.tenant_ai_rules.prompt_injection import (
    build_tone_directive,
    CUSTOM_DIRECTIVE_MAX,
)


def _rules(style=None, directive=None):
    tv = {}
    if style is not None:
        tv["style"] = style
    if directive is not None:
        tv["custom_directive"] = directive
    return {"tone_voice": tv}


def test_formal_style_emits_expected_preamble():
    out = build_tone_directive(_rules(style="formal"))
    assert "Respond with professional" in out
    assert "Avoid contractions" in out


def test_friendly_style_emits_expected_preamble():
    out = build_tone_directive(_rules(style="friendly"))
    assert "Respond conversationally" in out
    assert "warm and approachable" in out


def test_technical_style_emits_expected_preamble():
    out = build_tone_directive(_rules(style="technical"))
    assert "Respond precisely and technically" in out
    assert "industry" in out


def test_missing_style_falls_back_to_friendly():
    out = build_tone_directive(_rules())
    assert "Respond conversationally" in out


def test_invalid_style_falls_back_to_friendly():
    out = build_tone_directive(_rules(style="chaotic"))
    assert "Respond conversationally" in out


def test_directive_appended_when_set():
    out = build_tone_directive(
        _rules(style="formal", directive="Cite Platinum tier"),
    )
    assert "Tenant directive: Cite Platinum tier" in out


def test_directive_truncated_at_cap():
    long = "x" * (CUSTOM_DIRECTIVE_MAX + 200)
    out = build_tone_directive(_rules(directive=long))
    # The directive line appears exactly once, ≤ 500 xs.
    ln = [ln for ln in out.splitlines() if ln.startswith("Tenant directive")]
    assert len(ln) == 1
    payload = ln[0].removeprefix("Tenant directive: ")
    assert len(payload) == CUSTOM_DIRECTIVE_MAX


def test_empty_directive_is_omitted():
    out = build_tone_directive(_rules(style="formal", directive="   "))
    assert "Tenant directive" not in out


def test_none_rules_falls_back_gracefully():
    out = build_tone_directive(None)
    assert "Respond conversationally" in out


def test_bad_shape_falls_back_gracefully():
    out = build_tone_directive({"tone_voice": "not-a-dict"})
    assert "Respond conversationally" in out
