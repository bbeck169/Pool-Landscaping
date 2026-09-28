"""CHEM-LOCK · Feb-2026 — Unit tests for the chemical read-boundary
normalizer.

Every renderer that emits a chemical row goes through
:func:`services.chemical_normalizer.normalize_chemical`. These tests
lock the semantics in place so a future refactor can't silently
regress ``quantity``-preference, blank-row skipping, or duplication
logging.
"""
from __future__ import annotations

import logging
import pytest

from services.chemical_normalizer import (
    format_chemical_line,
    normalize_chemical,
)


# ─── Preference order — the core semantic ────────────────────────
def test_quantity_only_row_renders():
    """A row with only ``quantity`` (spec-preferred field) surfaces
    that value under the canonical ``quantity`` key."""
    out = normalize_chemical(
        {"name": "Chlorine", "quantity": "1.5", "unit": "gal"},
    )
    assert out is not None
    assert out["name"] == "Chlorine"
    assert out["quantity"] == "1.5"
    assert out["unit"] == "gal"
    assert out["raw_label"] is None


def test_amount_only_row_renders():
    """A row with only ``amount`` (legacy tech-app writer field)
    surfaces that value under ``quantity``. This is the failing case
    that was silently dropped by ``auto_visit_email`` before CHEM-LOCK.
    """
    out = normalize_chemical(
        {"name": "Muriatic Acid", "amount": "0.25", "unit": "gal"},
    )
    assert out is not None
    assert out["name"] == "Muriatic Acid"
    assert out["quantity"] == "0.25"
    assert out["unit"] == "gal"


def test_both_quantity_and_amount_prefers_quantity(caplog):
    """When both are present, ``quantity`` wins AND a debug line
    is logged so ops can dedupe on the writer side later."""
    caplog.set_level(logging.DEBUG, logger="")
    out = normalize_chemical(
        {"name": "Cal Hypo", "quantity": "2", "amount": "999",
         "unit": "lb"},
    )
    assert out is not None
    # quantity wins.
    assert out["quantity"] == "2"
    # Debug log emitted when the two values disagree.
    debug_lines = [r for r in caplog.records
                    if "chem-normalize" in r.getMessage()]
    assert debug_lines, "expected duplicate quantity/amount debug line"


def test_both_quantity_and_amount_matching_no_debug(caplog):
    """Matching values (writer wrote both keys with the same value —
    exactly the forward-compat migration path CHEM-LOCK recommends)
    do NOT emit a debug line."""
    caplog.set_level(logging.DEBUG, logger="")
    out = normalize_chemical(
        {"name": "Cal Hypo", "quantity": "2", "amount": "2",
         "unit": "lb"},
    )
    assert out is not None
    assert out["quantity"] == "2"
    debug_lines = [r for r in caplog.records
                    if "chem-normalize" in r.getMessage()]
    assert not debug_lines, "matching quantity/amount should NOT log"


# ─── Blank-row skip semantics ────────────────────────────────────
def test_all_blank_row_returns_none():
    """No name, no quantity, no amount, no raw_label → skip render."""
    assert normalize_chemical({}) is None
    assert normalize_chemical({"name": "", "quantity": None,
                                "amount": None, "unit": ""}) is None
    assert normalize_chemical({"name": "", "amount": 0,
                                "quantity": 0}) is None
    assert normalize_chemical({"name": "", "amount": "0",
                                "quantity": "0"}) is None


def test_name_only_row_renders():
    """A named row with no quantity is still meaningful — the tech
    may have noted a chemical without a dose (rare but valid)."""
    out = normalize_chemical({"name": "Algaecide"})
    assert out is not None
    assert out["name"] == "Algaecide"
    assert out["quantity"] is None
    assert out["unit"] is None


def test_raw_label_only_row_renders():
    """Freeform label with no other fields — the tech typed something
    but hasn't yet mapped it to a catalog entry. Preserve it so the
    renderer can show the typed text."""
    out = normalize_chemical({"raw_label": "1/2 cup of stabilizer"})
    assert out is not None
    assert out["raw_label"] == "1/2 cup of stabilizer"
    assert out["name"] is None
    assert out["quantity"] is None


# ─── Name / unit / qty type variants ─────────────────────────────
def test_chemical_key_as_name_fallback():
    """Older writers used ``chemical`` instead of ``name``."""
    out = normalize_chemical({"chemical": "Chlorine", "amount": "1"})
    assert out is not None
    assert out["name"] == "Chlorine"
    assert out["quantity"] == "1"


def test_qty_third_fallback():
    """Portal FE historically wrote a ``qty`` alias — accept it as
    the LAST fallback so old writes still render."""
    out = normalize_chemical({"name": "Chlorine", "qty": "3", "unit": "oz"})
    assert out is not None
    assert out["quantity"] == "3"


def test_unit_whitespace_trimmed():
    out = normalize_chemical({"name": "X", "amount": "1", "unit": "  lb  "})
    assert out["unit"] == "lb"


def test_numeric_quantity_preserved():
    """Numeric qty (float / int) preserved without stringification."""
    out = normalize_chemical({"name": "X", "quantity": 1.5, "unit": "gal"})
    assert out["quantity"] == 1.5


def test_non_dict_entry_returns_none():
    """Defensive — a garbled row (string, None, list) returns None."""
    assert normalize_chemical(None) is None
    assert normalize_chemical("not a dict") is None
    assert normalize_chemical(["also not a dict"]) is None
    assert normalize_chemical(42) is None


# ─── format_chemical_line convenience helper ─────────────────────
def test_format_chemical_line_amount_only():
    line = format_chemical_line(
        {"name": "Chlorine", "amount": "1.5", "unit": "gal"},
    )
    assert line == "Chlorine — 1.5 gal"


def test_format_chemical_line_prefers_quantity():
    line = format_chemical_line(
        {"name": "Cal Hypo", "quantity": "2", "amount": "999", "unit": "lb"},
    )
    assert line == "Cal Hypo — 2 lb"


def test_format_chemical_line_blank_row_returns_none():
    assert format_chemical_line({}) is None
    assert format_chemical_line({"name": "", "amount": 0}) is None


def test_format_chemical_line_no_unit():
    line = format_chemical_line({"name": "Algaecide", "amount": "1"})
    assert line == "Algaecide — 1"


def test_format_chemical_line_name_only():
    line = format_chemical_line({"name": "Algaecide"})
    assert line == "Algaecide"
