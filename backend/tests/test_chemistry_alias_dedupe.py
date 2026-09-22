"""Phase CHEM2 · Feb-2026 — Cyanuric alias dedupe.

Locks in ``normalize_readings``'s "prefer-value-over-blank" merge for
alias pairs already declared in ``_ALIASES``. Rules:

  1. If one side is blank and the other non-blank → keep the non-blank
     value under the canonical key. Alias key is dropped from the
     output entirely.
  2. If both sides are non-blank → the value stored under the
     canonical key wins; the collision is logged.
  3. If both sides are blank → a single blank sits under the canonical
     key, alias key is dropped.
  4. If neither side is present → passthrough unchanged.

Same rule fires for every alias pair the module already tracks
(``chlorine``/``free_chlorine``, ``total_alkalinity``/``alkalinity``,
``cya``/``cyanuric_acid``, …).
"""
from __future__ import annotations

import logging

import pytest

from services.chemistry_gate import normalize_readings


# ═════════════════════════════════════════════════════════════════════
# Cyanuric — the headline pair for this phase.
# ═════════════════════════════════════════════════════════════════════
def test_cyanuric_alias_blank_and_canonical_filled_keeps_filled():
    r = normalize_readings({"cyanuric": "", "cyanuric_acid": "45"})
    assert r == {"cyanuric_acid": "45"}
    assert "cyanuric" not in r


def test_cyanuric_alias_filled_and_canonical_blank_keeps_filled():
    r = normalize_readings({"cyanuric": 42, "cyanuric_acid": None})
    assert r == {"cyanuric_acid": 42}
    assert "cyanuric" not in r


def test_cyanuric_both_filled_canonical_wins_and_logs(caplog):
    caplog.set_level(logging.INFO, logger="services.chemistry_gate")
    r = normalize_readings({"cyanuric": 99, "cyanuric_acid": 45})
    assert r == {"cyanuric_acid": 45}
    assert "cyanuric" not in r
    # Log line captured (loose match — the exact phrasing is
    # asserted by the collision-log format alone).
    assert any(
        "alias collision" in rec.getMessage()
        and "cyanuric_acid" in rec.getMessage()
        for rec in caplog.records
    ), [rec.getMessage() for rec in caplog.records]


def test_cyanuric_both_blank_produces_single_blank_under_canonical():
    r = normalize_readings({"cyanuric": "", "cyanuric_acid": None})
    assert list(r.keys()) == ["cyanuric_acid"]
    assert "cyanuric" not in r


def test_no_alias_present_is_passthrough_unchanged():
    """Regression guard: a payload with NO alias overlap comes out
    exactly as before (canonical keys only, unknown keys dropped —
    ``calcium_hardness`` is not in ``CORE_READINGS`` or ``_ALIASES``
    so it never survived the normalizer).

    Phase P17.1 · Feb-2026 — the chlorine canonical flipped from
    ``free_chlorine`` to ``chlorine``. The input ``free_chlorine``
    remains a valid SOURCE alias that folds onto ``chlorine``."""
    r = normalize_readings({
        "free_chlorine":  2.5,
        "ph":             7.4,
        "alkalinity":     100,
        "cyanuric_acid":  40,
        "not_a_reading":  "ignored",
    })
    assert r == {
        "chlorine":       2.5,
        "ph":             7.4,
        "alkalinity":     100,
        "cyanuric_acid":  40,
    }


# ═════════════════════════════════════════════════════════════════════
# Coverage for the OTHER alias pairs the module already tracks.
# ═════════════════════════════════════════════════════════════════════
def test_alkalinity_alias_pair_prefers_non_blank_regardless_of_order():
    # ``total_alkalinity`` (legacy) blank, ``alkalinity`` (canonical) filled.
    r1 = normalize_readings({"total_alkalinity": "", "alkalinity": 100})
    assert r1 == {"alkalinity": 100}
    # Reverse — legacy filled, canonical blank.
    r2 = normalize_readings({"total_alkalinity": 90, "alkalinity": None})
    assert r2 == {"alkalinity": 90}


def test_chlorine_alias_pair_prefers_non_blank_regardless_of_order():
    # Phase P17.1 · Feb-2026 — canonical rename: the chlorine
    # canonical is now ``chlorine`` (was ``free_chlorine`` under
    # P17). Legacy ``free_chlorine`` remains a SOURCE alias.
    # Legacy ``free_chlorine`` blank, canonical ``chlorine`` filled.
    r1 = normalize_readings({"free_chlorine": "", "chlorine": 2.5})
    assert r1 == {"chlorine": 2.5}
    # Reverse — legacy filled, canonical blank.
    r2 = normalize_readings({"free_chlorine": 2.0, "chlorine": None})
    assert r2 == {"chlorine": 2.0}


def test_alias_dedupe_works_on_list_shape_too():
    """``chemical_readings`` list-of-dicts shape gets the same merge."""
    r = normalize_readings([
        {"key": "cyanuric",       "value": None},
        {"key": "cyanuric_acid",  "value": 45},
    ])
    assert r == {"cyanuric_acid": 45}

    r_rev = normalize_readings([
        {"key": "cyanuric",       "value": 42},
        {"key": "cyanuric_acid",  "value": ""},
    ])
    assert r_rev == {"cyanuric_acid": 42}
