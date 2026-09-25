"""Feb-2026 · Band-label casing fix (batch follow-up A).

Regression coverage for the ``_band_style`` case-insensitive lookup.

Before this fix the ``_BAND_HEX_MAP`` lookup was case-sensitive on
Title-Case strings (``"Below Average"`` etc.). The customer-safe
redact pipeline (``routers.service_reports._redact_report_for_customer``)
stamps the lowercase short strings ``chemistry.classify_reading``
emits (``"below" / "average" / "above" / "elevated"``) onto every
reading's ``label``.  The branded template consumed those lowercase
tokens and — finding no match — fell through to the ``Average``
palette for every pill.  Visible impact: EVERY chemistry cell
rendered as the green "Average" chip regardless of actual band.

This suite pins the alias table and re-runs the pool metrics
composer end-to-end so a customer with mixed readings sees the
correct four colors (sky / emerald / amber / red).
"""
from __future__ import annotations

from typing import Any, Dict, List

from services import auto_visit_email as ave
from services.auto_visit_email import (
    _band_style, _BAND_HEX_MAP, _BAND_ALIAS,
    _render_pool_metrics_card, render_email,
)


# ══════════════════════════════════════════════════════════════════
# _band_style — table-driven casing coverage
# ══════════════════════════════════════════════════════════════════
def test_band_style_lowercase_short_tokens_map_correctly():
    """The four tokens the redact pipeline emits map to the four
    hex buckets, not the ``Average`` fallback."""
    cases = [
        ("below",    _BAND_HEX_MAP["Below Average"]),
        ("average",  _BAND_HEX_MAP["Average"]),
        ("above",    _BAND_HEX_MAP["Above Average"]),
        ("elevated", _BAND_HEX_MAP["Elevated"]),
    ]
    for token, expected in cases:
        assert _band_style(token) is expected, token


def test_band_style_title_case_tokens_still_map_correctly():
    """``chemistry_bands.band_for_reading`` returns Title-Case;
    keep that side of the vocabulary working."""
    cases = [
        ("Below Average", _BAND_HEX_MAP["Below Average"]),
        ("Average",       _BAND_HEX_MAP["Average"]),
        ("Above Average", _BAND_HEX_MAP["Above Average"]),
        ("Elevated",      _BAND_HEX_MAP["Elevated"]),
    ]
    for token, expected in cases:
        assert _band_style(token) is expected, token


def test_band_style_high_and_low_legacy_aliases_covered():
    """Legacy seed rows and older UI code sometimes stamp ``"high"``
    / ``"low"`` — the alias map treats them as ``Elevated`` /
    ``Below Average``."""
    assert _band_style("high") is _BAND_HEX_MAP["Elevated"]
    assert _band_style("low") is _BAND_HEX_MAP["Below Average"]


def test_band_style_whitespace_and_case_variants_resolve():
    assert _band_style("  BELOW  ") is _BAND_HEX_MAP["Below Average"]
    assert _band_style("Below AVERAGE") is _BAND_HEX_MAP["Below Average"]


def test_band_style_unknown_falls_back_to_average():
    """The historical fallback contract stays intact — unknown
    tokens don't blank the pill, they render as ``Average``."""
    assert _band_style("plaid") is _BAND_HEX_MAP["Average"]
    assert _band_style(None) is _BAND_HEX_MAP["Average"]
    assert _band_style("") is _BAND_HEX_MAP["Average"]


def test_band_alias_covers_every_classify_reading_return_value():
    """Belt-and-suspenders: pin the exact set ``chemistry.classify_reading``
    can emit today (see ``services/chemistry.py:125-133``). If a
    new value is ever added there, this test breaks immediately."""
    from services import chemistry
    import re
    source = open(chemistry.__file__).read()
    returns = set(re.findall(r'return\s+"([a-z ]+)"', source))
    # ``classify_reading`` is the only site returning a Band string.
    for band in returns:
        assert band in _BAND_ALIAS, (
            f"chemistry.classify_reading emits {band!r} but "
            f"_BAND_ALIAS has no entry — the email would fall back "
            f"to the Average palette for that band."
        )


# ══════════════════════════════════════════════════════════════════
# End-to-end — mixed lowercase labels render as four DIFFERENT chips
# ══════════════════════════════════════════════════════════════════
def _readings_with_bands(pre_labels: List[str]) -> List[Dict[str, Any]]:
    """Build a customer-redact-shape readings list where each row
    already carries a pre-computed lowercase ``label``.  Values
    are stripped by the redact so we omit them here — the render
    loop should still pick up the label."""
    keys = ["chlorine", "alkalinity", "ph", "cyanuric_acid"]
    rows = []
    for k, lbl in zip(keys, pre_labels):
        rows.append({"key": k, "name": None, "unit": None,
                     "label": lbl, "value": 1.0})
    return rows


def test_branded_template_metric_pills_map_lowercase_labels_to_bands():
    """End-to-end: four readings with four different lowercase
    labels render four different chip colors — not the Average
    fallback across the board."""
    tenant = {"name": "T",
              "settings": {"auto_visit_email": {"enabled": True}}}
    job = {"id": "j", "customer_id": "c", "address": "x",
           "service_type": "pool"}
    sr = {
        "id": "sr", "kind": "pool",
        "chemical_readings": _readings_with_bands(
            ["below", "average", "above", "elevated"],
        ),
    }
    out = render_email(tenant, job, sr, {"email": "c@x.com"})
    html = out["html"]
    # All four band hex colors show up in the composed HTML — the
    # bug was every cell rendering as #10B981 (Average green).
    assert "#0EA5E9" in html, "Below Average sky pill missing"
    assert "#10B981" in html, "Average emerald pill missing"
    assert "#F59E0B" in html, "Above Average amber pill missing"
    assert "#EF4444" in html, "Elevated red pill missing"
    # Plain-text sibling should also honor the four labels.
    text = out["text"]
    assert "Below" in text
    assert "Average" in text
    assert "Above Avg" in text
    assert "Elevated" in text


def test_branded_template_pill_hex_matches_portal_hex_for_lowercase():
    """The 2x2 grid card composer picks the right hex for a
    lowercase-labelled row (Below Average → sky #0EA5E9)."""
    sr = {
        "id": "sr", "kind": "pool",
        "chemical_readings": [
            {"key": "chlorine", "label": "below", "value": 0.3},
        ],
    }
    card = _render_pool_metrics_card(sr, {
        "primary": "#000", "secondary": "#000", "accent": "#000",
    })
    assert "#0EA5E9" in card
    # NOT the average fallback.
    assert card.count("#10B981") == 0 or "Average" not in card
