"""Feb-2026 · Slice 3C — Unit tests for ``services.chemistry``.

Every band boundary is asserted for every chemical the spec covers so
a future threshold tweak can't silently regress.

Run with ``pytest backend/tests/test_chemistry.py``.
"""
from __future__ import annotations

import pytest

from services.chemistry import classify_reading, classify_readings


# ── Free Chlorine ────────────────────────────────────────────────────────
# Phase CHEM1 · Feb-2026 — ``total_chlorine`` was removed from the
# chemistry classifier + gate. Aliases still fold onto ``free_chlorine``.
@pytest.mark.parametrize("chem", ["free_chlorine", "chlorine"])
def test_chlorine_below(chem):
    assert classify_reading(chem, 0) == "below"
    assert classify_reading(chem, 1.99) == "below"


@pytest.mark.parametrize("chem", ["free_chlorine", "chlorine"])
def test_chlorine_average_boundary(chem):
    # lower band boundary — 2.0 exactly enters average
    assert classify_reading(chem, 2.0) == "average"
    # upper boundary — spec example: 5.0 → average, 5.01 → above
    assert classify_reading(chem, 5.0) == "average"


@pytest.mark.parametrize("chem", ["free_chlorine", "chlorine"])
def test_chlorine_above(chem):
    assert classify_reading(chem, 5.01) == "above"
    assert classify_reading(chem, 8.0) == "above"


@pytest.mark.parametrize("chem", ["free_chlorine", "chlorine"])
def test_chlorine_elevated(chem):
    assert classify_reading(chem, 8.01) == "elevated"
    assert classify_reading(chem, 20) == "elevated"


# ── pH ───────────────────────────────────────────────────────────────────
def test_ph_below():
    assert classify_reading("ph", 6.9) == "below"
    assert classify_reading("ph", 7.19) == "below"


def test_ph_average_boundary():
    assert classify_reading("ph", 7.2) == "average"
    assert classify_reading("ph", 7.6) == "average"


def test_ph_above_boundary():
    assert classify_reading("ph", 7.61) == "above"
    assert classify_reading("ph", 8.0) == "above"


def test_ph_elevated():
    assert classify_reading("ph", 8.01) == "elevated"
    assert classify_reading("ph", 9.0) == "elevated"


# ── Alkalinity ───────────────────────────────────────────────────────────
def test_alkalinity_bands():
    assert classify_reading("alkalinity", 60) == "below"
    assert classify_reading("alkalinity", 80) == "average"
    assert classify_reading("alkalinity", 120) == "average"
    assert classify_reading("alkalinity", 130) == "above"
    assert classify_reading("alkalinity", 140) == "above"
    assert classify_reading("alkalinity", 141) == "elevated"
    # alias
    assert classify_reading("total_alkalinity", 90) == "average"


# ── CYA ──────────────────────────────────────────────────────────────────
def test_cya_bands():
    assert classify_reading("cya", 10) == "below"
    assert classify_reading("cya", 30) == "average"
    assert classify_reading("cya", 100) == "average"
    assert classify_reading("cya", 101) == "above"
    assert classify_reading("cya", 150) == "above"
    assert classify_reading("cya", 151) == "elevated"
    # alias — service_reports.py uses ``cyanuric`` as the key.
    assert classify_reading("cyanuric", 45) == "average"
    assert classify_reading("cyanuric_acid", 200) == "elevated"


# ── TDS ──────────────────────────────────────────────────────────────────
def test_tds_bands():
    assert classify_reading("tds", 100) == "below"
    assert classify_reading("tds", 500) == "average"
    assert classify_reading("tds", 2000) == "average"
    assert classify_reading("tds", 2001) == "above"
    assert classify_reading("tds", 2500) == "above"
    assert classify_reading("tds", 3000) == "elevated"


# ── Phosphates (no ``below`` band) ───────────────────────────────────────
def test_phosphates_no_below():
    # 0 counts as average per spec
    assert classify_reading("phosphates", 0) == "average"
    assert classify_reading("phosphates", 50) == "average"
    assert classify_reading("phosphates", 100) == "average"
    assert classify_reading("phosphates", 101) == "above"
    assert classify_reading("phosphates", 500) == "above"
    assert classify_reading("phosphates", 501) == "elevated"


# ── Unknown / unsupported inputs ─────────────────────────────────────────
def test_unknown_chemical_returns_none():
    assert classify_reading("salt", 3200) is None
    assert classify_reading("calcium_hardness", 250) is None
    assert classify_reading("water_temp", 80) is None
    # Combined chlorine deliberately NOT mapped — its healthy value is
    # ~0-0.2 ppm, so Total-Cl thresholds would incorrectly flag it.
    assert classify_reading("combined_chlorine", 0.1) is None


def test_none_or_empty_value_returns_none():
    assert classify_reading("ph", None) is None
    assert classify_reading("ph", "") is None
    assert classify_reading("ph", "not a number") is None


def test_string_numeric_value_accepted():
    # Service-report pickers store numbers as strings.
    assert classify_reading("ph", "7.4") == "average"


def test_classify_readings_list():
    readings = [
        {"key": "chlorine", "value": 3.0},
        {"key": "ph", "value": 7.5},
        {"key": "salt", "value": 3200},       # skipped — no threshold
        {"key": "combined_chlorine", "value": 0.1},  # skipped
        {"key": "phosphates", "value": 250},
    ]
    labels = classify_readings(readings)
    assert labels == {
        "chlorine": "average",
        "ph": "average",
        "phosphates": "above",
    }


def test_classify_readings_dict():
    assert classify_readings({"ph": 8.5, "cya": 20}) == {
        "ph": "elevated",
        "cya": "below",
    }
