"""Feb-2026 · Chemistry bands helper — unit tests.

20 cases covering the boundary rule (lower inclusive, upper exclusive)
plus every unparseable-value path.  Runs as pure-Python; no DB.
"""
from __future__ import annotations

import pytest

from services.chemistry_bands import band_for_reading


@pytest.mark.parametrize("key,value,expected", [
    # ── Chlorine thresholds: <1 / 1-5 / 5-10 / >=10 ──
    # Phase P17.1 · Feb-2026 — canonical rename: the bands module
    # keys on ``chlorine`` (was ``free_chlorine`` under P17).
    ("chlorine",       0.5,   "Below Average"),
    ("chlorine",       1.0,   "Average"),                # lower bound inclusive
    ("chlorine",       4.99,  "Average"),
    ("chlorine",       5.0,   "Above Average"),          # upper bound exclusive
    ("chlorine",       9.99,  "Above Average"),
    ("chlorine",       10,    "Elevated"),
    # ── pH thresholds: <7.2 / 7.2-7.6 / 7.6-8.2 / >=8.2 ──
    ("ph",             7.4,   "Average"),
    ("ph",             8.2,   "Elevated"),
    ("ph",             8.1999, "Above Average"),
    # ── Alkalinity: <80 / 80-120 / 120-140 / >=140 ──
    ("alkalinity",     100,   "Average"),
    ("alkalinity",     140,   "Elevated"),
    # ── CYA: <30 / 30-80 / 80-150 / >=150 ──
    ("cyanuric_acid",  80,    "Above Average"),
    ("cyanuric_acid",  150,   "Elevated"),
    # ── Not-banded / unparseable → None ──
    ("water_temp",     82,    None),
    ("chlorine",       None,  None),
    ("chlorine",       "",    None),
    ("chlorine",       "not-a-number", None),
    ("chlorine",       "3.5", "Average"),                # stringified numeric parses
    ("chlorine",       0,     "Below Average"),          # zero is a real reading
    ("chlorine",       -1,    "Below Average"),
])
def test_band_for_reading(key, value, expected):
    assert band_for_reading(key, value) == expected
