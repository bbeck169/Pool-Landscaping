"""Phase D4 · Feb 2026 — resolve_row_label fallback chain unit tests."""
from __future__ import annotations

from routers.industry_checklists import resolve_row_label


def test_exact_locale_hit():
    row = {"key": "k", "label": "English",
             "label_i18n": {"es": "Español", "fr": "Français"}}
    assert resolve_row_label(row, "es") == "Español"
    assert resolve_row_label(row, "fr") == "Français"


def test_missing_locale_falls_back_to_label():
    row = {"key": "k", "label": "English",
             "label_i18n": {"es": "Español"}}
    # ``fr`` missing → falls through to ``en`` intra-i18n (none here)
    # → then to ``label``.
    assert resolve_row_label(row, "fr") == "English"


def test_missing_authoritative_label_falls_back_to_en_in_i18n():
    row = {"key": "k", "label": "",
             "label_i18n": {"en": "From i18n en", "es": "Español"}}
    assert resolve_row_label(row, "fr") == "From i18n en"


def test_missing_all_labels_falls_back_to_key():
    row = {"key": "the_row_key"}
    assert resolve_row_label(row, "es") == "the_row_key"


def test_unknown_locale_collapses_to_en_fallback_chain():
    row = {"key": "k", "label": "English",
             "label_i18n": {"es": "Español", "fr": "Français"}}
    # ``de`` is unsupported → collapses to ``en`` → no ``en`` entry
    # in ``label_i18n`` → falls back to ``label``.
    assert resolve_row_label(row, "de") == "English"


def test_empty_locale_string_treated_as_missing():
    row = {"key": "k", "label": "English",
             "label_i18n": {"es": "", "fr": "Français"}}
    # Empty ``es`` → treated as missing → English fallback.
    assert resolve_row_label(row, "es") == "English"
    # ``fr`` still resolves.
    assert resolve_row_label(row, "fr") == "Français"


def test_non_dict_row_returns_empty_string():
    assert resolve_row_label(None, "en") == ""
    assert resolve_row_label("not a dict", "en") == ""
