"""Phase D5 · Feb-2026 — resolve_notification_body fallback + merge-var tests."""
from __future__ import annotations

import pytest

from services.i18n_notifications import (
    MissingMergeVarError,
    TemplateNotFoundError,
    resolve_notification_body,
    extract_placeholders,
    clear_cache,
)


@pytest.fixture(autouse=True)
def _fresh_cache():
    clear_cache()
    yield
    clear_cache()


def test_exact_locale_match_returns_expected_body():
    out = resolve_notification_body(
        "completion_sms", "es",
        context={
            "first_name": "Diego",
            "job_title": "Servicio de piscina",
            "business_name": "Piscinas del Valle",
            "portal_link": "https://p.example/xyz",
        },
    )
    assert "body_text" in out
    assert "Hola Diego" in out["body_text"]
    assert "Piscinas del Valle" in out["body_text"]
    assert "https://p.example/xyz" in out["body_text"]


def test_missing_locale_falls_back_to_en_when_locale_file_absent(
    tmp_path, monkeypatch,
):
    # We can't easily delete a real es file, so instead point the
    # loader at an isolated tmp tree that has an en-only template.
    from services import i18n_notifications as _mod
    root = tmp_path / "templates"
    (root / "en").mkdir(parents=True)
    (root / "en" / "custom_only_en.sms.txt").write_text(
        "Hi {name}", encoding="utf-8",
    )
    monkeypatch.setattr(_mod, "_TEMPLATE_ROOT", root)
    _mod._FILE_CACHE.clear()
    out = resolve_notification_body(
        "custom_only_en", "es", context={"name": "Ana"},
    )
    assert out == {"body_text": "Hi Ana"}


def test_unknown_locale_normalises_to_en():
    # Requesting a locale outside en/es/fr coerces to en.
    out = resolve_notification_body(
        "completion_sms", "de",
        context={
            "first_name": "Klaus", "job_title": "Pool service",
            "business_name": "Vistancia Pools",
            "portal_link": "https://p.example/z",
        },
    )
    assert "Hi Klaus" in out["body_text"]


def test_missing_template_key_raises():
    with pytest.raises(TemplateNotFoundError):
        resolve_notification_body(
            "does_not_exist_anywhere", "en", context={},
        )


def test_missing_merge_var_raises_clear_error():
    with pytest.raises(MissingMergeVarError) as exc_info:
        resolve_notification_body(
            "completion_sms", "en",
            context={"first_name": "X"},  # missing job_title, business_name, portal_link
        )
    msg = str(exc_info.value)
    assert "completion_sms" in msg
    # First missing var wins — Python's format walks left-to-right.
    assert any(tok in msg for tok in
                ("job_title", "business_name", "portal_link"))


def test_merge_vars_substitute_across_all_three_locales():
    ctx = {
        "first_name": "Ana",
        "job_title": "Service visit",
        "business_name": "Acme",
        "portal_link": "https://p.example/abc",
    }
    for loc in ("en", "es", "fr"):
        out = resolve_notification_body("completion_sms", loc, context=ctx)
        assert "Ana" in out["body_text"]
        assert "Acme" in out["body_text"]
        assert "https://p.example/abc" in out["body_text"]
        # And no literal {token} leaked through.
        assert "{" not in out["body_text"]


def test_extract_placeholders_finds_all_named_tokens():
    tokens = extract_placeholders(
        "Hi {first_name}, your {job_title} with {business_name} is complete! "
        "View here: {portal_link}"
    )
    assert tokens == {
        "first_name", "job_title", "business_name", "portal_link",
    }
