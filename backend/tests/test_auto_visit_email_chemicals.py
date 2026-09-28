"""CHEM-LOCK · Feb-2026 — Auto-visit email chemical rendering.

Regression coverage for the "chemicals missing on portal-visible
service reports" ticket. Before CHEM-LOCK, ``_pool_body_sections``
read only ``c.get("amount")`` in the chemicals loop — so any row
written with ``quantity`` only (the spec-preferred field per the
handover) silently rendered as blank.

The fix routes every chem row through
``services.chemical_normalizer.normalize_chemical`` which prefers
``quantity``, falls back to ``amount`` (and ``qty``), and skips
genuinely blank rows so the section doesn't emit "Chemical — "
empty <li>s.
"""
from __future__ import annotations

from typing import Any, Dict, List

from services.auto_visit_email import _pool_body_sections


_PALETTE: Dict[str, str] = {
    "primary": "#0F2027",
    "secondary": "#204051",
    "accent": "#3B6978",
    "text": "#1E293B",
    "background": "#F8FAFC",
    "muted": "#64748B",
}


def _chemicals_section(sr: Dict[str, Any]) -> Dict[str, Any] | None:
    """Locate the ``Chemicals added`` section in the render output."""
    for s in _pool_body_sections(sr, _PALETTE):
        if s.get("title") == "Chemicals added":
            return s
    return None


# ─── The core CHEM-LOCK case — amount-only row must render ───────
def test_amount_only_row_renders_in_pool_body_sections():
    """An ``amount``-only chemical (as written by the tech app FE)
    surfaces in the ``Chemicals added`` section. This is the
    ticket-driving regression."""
    sr = {
        "template": "pool",
        "chemical_readings": [],
        "chemicals_added": [
            {"name": "Liquid Chlorine", "amount": "1.5", "unit": "gal"},
        ],
    }
    sec = _chemicals_section(sr)
    assert sec is not None, "Chemicals added section should render"
    assert "Liquid Chlorine" in sec["html"]
    assert "1.5" in sec["html"]
    assert "gal" in sec["html"]
    assert "Liquid Chlorine" in sec["text"]


def test_quantity_only_row_renders():
    """A ``quantity``-only row (post-CHEM-LOCK writer output)
    surfaces without change."""
    sr = {
        "template": "pool",
        "chemical_readings": [],
        "chemicals_added": [
            {"name": "Muriatic Acid", "quantity": "0.25", "unit": "gal"},
        ],
    }
    sec = _chemicals_section(sr)
    assert sec is not None
    assert "Muriatic Acid" in sec["html"]
    assert "0.25" in sec["html"]


def test_both_fields_prefers_quantity():
    """Duplication case: writer wrote both. HTML surfaces ``quantity``,
    NOT the (stale) ``amount``."""
    sr = {
        "template": "pool",
        "chemical_readings": [],
        "chemicals_added": [
            {"name": "Cal Hypo", "quantity": "2", "amount": "999",
             "unit": "lb"},
        ],
    }
    sec = _chemicals_section(sr)
    assert sec is not None
    assert " 2 lb" in sec["html"]
    assert " 999 " not in sec["html"], (
        "stale ``amount`` value should not render when ``quantity`` "
        "is present"
    )


def test_blank_row_skipped_no_empty_li():
    """A row with no name / no qty / no amount renders NOTHING
    (no empty <li>)."""
    sr = {
        "template": "pool",
        "chemical_readings": [],
        "chemicals_added": [
            {},                     # completely empty
            {"name": ""},           # empty name only
            {"amount": 0},          # blank amount
            {"amount": "0"},        # string-zero
        ],
    }
    sec = _chemicals_section(sr)
    # Every row was blank — the section should NOT render at all.
    assert sec is None, "all-blank chemicals list should suppress the section"


def test_mixed_blank_and_valid_only_valid_renders():
    """A list with SOME blanks and SOME valid entries renders only
    the valid ones — no empty <li>s in between."""
    sr = {
        "template": "pool",
        "chemical_readings": [],
        "chemicals_added": [
            {},                                            # skip
            {"name": "Chlorine", "amount": "1", "unit": "gal"},
            {"name": "", "quantity": None},                # skip
            {"name": "Acid", "quantity": "0.5", "unit": "gal"},
        ],
    }
    sec = _chemicals_section(sr)
    assert sec is not None
    assert "Chlorine" in sec["html"]
    assert "Acid" in sec["html"]
    # Exactly TWO <li> rows.
    assert sec["html"].count("<li") == 2


def test_chemical_key_as_name_fallback_renders():
    """``chemical`` (legacy field name) surfaces as the display name."""
    sr = {
        "template": "pool",
        "chemical_readings": [],
        "chemicals_added": [
            {"chemical": "Stabilizer", "amount": "1", "unit": "lb"},
        ],
    }
    sec = _chemicals_section(sr)
    assert sec is not None
    assert "Stabilizer" in sec["html"]


def test_empty_chemicals_list_no_section():
    """An empty list produces NO ``Chemicals added`` section."""
    sr = {"template": "pool", "chemical_readings": [],
          "chemicals_added": []}
    assert _chemicals_section(sr) is None


def test_missing_chemicals_key_no_section():
    """Missing key entirely — no section."""
    sr = {"template": "pool", "chemical_readings": []}
    assert _chemicals_section(sr) is None
