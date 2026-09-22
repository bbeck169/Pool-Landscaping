"""Phase P17 · Feb-2026 · P0 HOTFIX — Chemistry Gate Key Unification.

Locks in the unified ALIAS_MAP + real-beats-empty dedupe + zero-carve-out
behavior across ``services/chemistry_gate.py``.  Every alias for the
Required Four must resolve to a single canonical key; the gate must
never block a job when readings are present under any alias
combination.

Phase P17.1 · Feb-2026 — canonical rename.  The Required-Four
canonical for the chlorine field flipped from ``free_chlorine`` to
``chlorine`` end-to-end.  Legacy source spellings
(``free_chlorine``, ``free_cl``, ``freecl``, ``fc``,
``free chlorine``) remain as SOURCE aliases pointing at ``chlorine``
so existing writes and stored docs continue to resolve; the 422
wire contract now emits ``chlorine`` / ``Chlorine`` in
``missing_fields`` / ``missing_labels``.  This suite exercises the
new canonical output shape while still driving payloads under every
legacy alias to prove the alias lookup path stays intact.
"""
from __future__ import annotations

import logging

import pytest
from fastapi import HTTPException

from services.chemistry_gate import (
    ALIAS_MAP,
    CORE_READINGS,
    assert_core_readings_present,
    missing_core_readings,
    normalize_readings,
)


# ═════════════════════════════════════════════════════════════════════
# Item 1 · ALIAS_MAP — every alias for the Required Four resolves to
# its canonical key.
# ═════════════════════════════════════════════════════════════════════
_ALIAS_MATRIX = [
    # ph
    ("ph",              "ph"),
    ("pH",              "ph"),
    ("PH",              "ph"),
    ("Ph",              "ph"),
    ("p_h",             "ph"),
    ("p-h",             "ph"),
    # chlorine — new P17.1 canonical (was free_chlorine under P17)
    ("chlorine",        "chlorine"),
    ("Chlorine",        "chlorine"),
    ("free_chlorine",   "chlorine"),
    ("Free Chlorine",   "chlorine"),
    ("free_cl",         "chlorine"),
    ("Free Cl",         "chlorine"),
    ("FreeCl",          "chlorine"),
    ("FC",              "chlorine"),
    # alkalinity
    ("alkalinity",      "alkalinity"),
    ("Alkalinity",      "alkalinity"),
    ("total_alkalinity","alkalinity"),
    ("Total Alkalinity","alkalinity"),
    ("TA",              "alkalinity"),
    ("ta",              "alkalinity"),
    ("alk",             "alkalinity"),
    # cyanuric_acid
    ("cyanuric_acid",   "cyanuric_acid"),
    ("Cyanuric Acid",   "cyanuric_acid"),
    ("cyanuric",        "cyanuric_acid"),
    ("Cyanuric",        "cyanuric_acid"),
    ("cya",             "cyanuric_acid"),
    ("CYA",             "cyanuric_acid"),
]


@pytest.mark.parametrize("raw_key,canonical", _ALIAS_MATRIX)
def test_every_alias_resolves_to_canonical_via_normalize_readings(
    raw_key, canonical,
):
    """Given ``{raw_key: 1.5}``, normalize_readings emits exactly one
    entry keyed by the canonical name."""
    out = normalize_readings({raw_key: 1.5})
    assert out == {canonical: 1.5}, (
        f"expected {raw_key!r} -> {canonical!r}, got {out!r}"
    )


def test_all_aliases_appear_in_alias_map():
    """Sanity: the ALIAS_MAP module constant contains every alias
    exercised by the parametrized matrix (case-insensitive)."""
    for raw_key, _ in _ALIAS_MATRIX:
        norm = raw_key.strip().lower().replace(" ", "_").replace("-", "_")
        assert norm in ALIAS_MAP, f"{raw_key!r} → {norm!r} missing from ALIAS_MAP"


def test_all_canonical_keys_are_in_core_readings():
    for k in ALIAS_MAP.values():
        assert k in CORE_READINGS, (
            f"ALIAS_MAP points at {k!r} which is not in CORE_READINGS"
        )


# ═════════════════════════════════════════════════════════════════════
# Item 2a · Real-beats-empty for each of the Required Four.
# ═════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("canonical,alias,real_value", [
    ("ph",             "pH",              7.4),
    ("chlorine",       "free_chlorine",   3.0),
    ("alkalinity",     "Total Alkalinity", 90),
    ("cyanuric_acid",  "Cyanuric Acid",   40),
])
def test_real_value_beats_empty_string_under_any_alias(
    canonical, alias, real_value,
):
    out = normalize_readings({canonical: "", alias: real_value})
    assert out == {canonical: real_value}


@pytest.mark.parametrize("canonical,alias,real_value", [
    ("ph",             "pH",              7.4),
    ("chlorine",       "free_chlorine",   3.0),
    ("alkalinity",     "Total Alkalinity", 90),
    ("cyanuric_acid",  "Cyanuric Acid",   40),
])
def test_real_value_beats_none_under_any_alias(
    canonical, alias, real_value,
):
    out = normalize_readings({canonical: None, alias: real_value})
    assert out == {canonical: real_value}


@pytest.mark.parametrize("alias,real_value", [
    ("pH",              7.4),
    ("free_chlorine",   3.0),
    ("Total Alkalinity", 90),
    ("Cyanuric Acid",   40),
])
def test_real_value_beats_string_null_literal_under_any_alias(
    alias, real_value,
):
    """P17 · Feb-2026 — the string ``"null"`` (older mobile builds
    serialised missing readings this way) is treated as empty."""
    canonical = ALIAS_MAP[alias.strip().lower().replace(" ", "_")]
    payload = {alias: real_value, canonical: "null"}
    assert normalize_readings(payload) == {canonical: real_value}


# ═════════════════════════════════════════════════════════════════════
# Item 2b · Zero-carve-out — 0 is empty for pH/alk/CYA, real for
# chlorine.
# ═════════════════════════════════════════════════════════════════════
def test_zero_is_empty_for_ph_when_real_value_present():
    out = normalize_readings({"ph": 0, "pH": 7.4})
    assert out == {"ph": 7.4}


def test_zero_is_empty_for_alkalinity_when_real_value_present():
    out = normalize_readings({"alkalinity": 0, "Total Alkalinity": 90})
    assert out == {"alkalinity": 90}


def test_zero_is_empty_for_cyanuric_when_real_value_present():
    out = normalize_readings({"cyanuric_acid": 0, "CYA": 40})
    assert out == {"cyanuric_acid": 40}


def test_zero_is_a_real_reading_for_chlorine():
    """A fully-consumed pool can legitimately read 0 ppm chlorine — 0
    must NOT be treated as empty for chlorine."""
    out = normalize_readings({"chlorine": 0})
    assert out == {"chlorine": 0}


def test_zero_is_a_real_reading_for_chlorine_under_legacy_alias():
    """Legacy ``free_chlorine`` alias still resolves onto the new
    canonical ``chlorine`` while preserving the zero-carve-out
    inverse (0 is a real reading)."""
    out = normalize_readings({"free_chlorine": 0})
    assert out == {"chlorine": 0}


def test_zero_beats_none_for_chlorine():
    out = normalize_readings({"chlorine": 0, "free_chlorine": None})
    assert out == {"chlorine": 0}


def test_zero_string_is_empty_for_ph():
    """Even a stringified 0 must be treated as empty for pH."""
    out = normalize_readings({"ph": "0", "pH": 7.4})
    assert out == {"ph": 7.4}


def test_missing_core_readings_flags_single_ph_zero():
    """A single ``{ph: 0}`` payload should trigger the gate — 0 is
    not a physically-meaningful pH reading."""
    missing = missing_core_readings({"ph": 0})
    assert "ph" in missing


def test_missing_core_readings_accepts_chlorine_zero():
    """A single ``{chlorine: 0}`` is a valid reading and MUST NOT be
    flagged as missing chlorine."""
    missing = missing_core_readings({
        "chlorine": 0,
        "ph": 7.4,
        "alkalinity": 90,
        "cyanuric_acid": 40,
    })
    assert missing == []


def test_missing_core_readings_accepts_chlorine_zero_under_legacy_alias():
    """P17.1 alias-preservation guard: a legacy write carrying
    ``free_chlorine: 0`` still folds onto the new canonical without
    tripping the gate."""
    missing = missing_core_readings({
        "free_chlorine": 0,
        "ph": 7.4,
        "alkalinity": 90,
        "cyanuric_acid": 40,
    })
    assert missing == []


# ═════════════════════════════════════════════════════════════════════
# Item 3 · Gate integration — a payload with mixed aliases passes.
# ═════════════════════════════════════════════════════════════════════
def test_normalize_readings_accepts_mixed_aliases():
    """The exact payload from the P17 acceptance criterion — every
    reading present under a different alias.  Output uses canonical
    key names; Phase P17.1 flipped the chlorine canonical from
    ``free_chlorine`` → ``chlorine`` so the output is now keyed
    ``chlorine``."""
    out = normalize_readings({
        "pH":                7.4,
        "Total Alkalinity":  90,
        "Cyanuric Acid":     40,
        "Free Chlorine":     3.0,
    })
    assert out == {
        "ph":              7.4,
        "alkalinity":      90,
        "cyanuric_acid":   40,
        "chlorine":        3.0,
    }


def test_gate_passes_with_mixed_aliases():
    """The gate must NOT raise when every reading is present under
    any alias combination."""
    assert_core_readings_present({
        "pH":                7.4,
        "Total Alkalinity":  90,
        "Cyanuric Acid":     40,
        "Free Chlorine":     3.0,
    })


def test_gate_raises_when_ph_zero_only():
    """Zero-carve-out — the gate raises when the only pH reading
    is a physically-meaningless 0."""
    with pytest.raises(HTTPException) as exc_info:
        assert_core_readings_present({
            "ph":              0,
            "chlorine":        3.0,
            "alkalinity":      90,
            "cyanuric_acid":   40,
        })
    detail = exc_info.value.detail
    assert isinstance(detail, dict)
    assert detail["detail"] == "chemistry_core_readings_missing"
    assert "ph" in detail["missing_fields"]


def test_gate_passes_when_chlorine_zero_and_rest_present():
    """Zero-carve-out inverse — 0 ppm chlorine is a real reading, so
    the gate passes when the other three are present."""
    assert_core_readings_present({
        "chlorine":        0,
        "ph":              7.4,
        "alkalinity":      90,
        "cyanuric_acid":   40,
    })


# ═════════════════════════════════════════════════════════════════════
# Ordering safety — two-pass loop is order-independent.
# ═════════════════════════════════════════════════════════════════════
def test_dedupe_is_order_independent_ph_zero_first():
    forward = normalize_readings({"ph": 0, "pH": 7.4})
    reverse = normalize_readings({"pH": 7.4, "ph": 0})
    assert forward == reverse == {"ph": 7.4}


def test_dedupe_is_order_independent_alkalinity_blank_first():
    forward = normalize_readings({"alkalinity": "", "total_alkalinity": 90})
    reverse = normalize_readings({"total_alkalinity": 90, "alkalinity": ""})
    assert forward == reverse == {"alkalinity": 90}


# ═════════════════════════════════════════════════════════════════════
# Collision WARN log — both aliases carry real values.
# ═════════════════════════════════════════════════════════════════════
def test_both_real_alias_collision_emits_warn_log(caplog):
    caplog.set_level(logging.WARNING, logger="services.chemistry_gate")
    out = normalize_readings({"cyanuric": 99, "cyanuric_acid": 45})
    assert out == {"cyanuric_acid": 45}
    assert any(
        "alias collision" in rec.getMessage()
        and "cyanuric_acid" in rec.getMessage()
        for rec in caplog.records
    ), [rec.getMessage() for rec in caplog.records]


def test_both_real_alias_collision_canonical_wins():
    """When both aliases carry real values, the canonical spelling
    wins regardless of dict iteration order."""
    forward = normalize_readings({"ta": 100, "alkalinity": 90})
    reverse = normalize_readings({"alkalinity": 90, "ta": 100})
    assert forward == reverse == {"alkalinity": 90}


def test_both_real_non_canonical_alphabetically_first_wins():
    """When neither key is the canonical spelling, the alias whose
    normalised key sorts first wins (deterministic tie-break)."""
    # normalised keys: "ta" (t,a) vs "total_alkalinity" (t,o,...).
    # "ta" < "total_alkalinity" alphabetically.
    forward = normalize_readings({"total_alkalinity": 100, "TA": 90})
    reverse = normalize_readings({"TA": 90, "total_alkalinity": 100})
    assert forward == reverse == {"alkalinity": 90}


def test_chlorine_canonical_wins_over_legacy_free_chlorine_when_both_real():
    """P17.1 alias-preservation guard: when both the new canonical
    ``chlorine`` and the legacy ``free_chlorine`` carry real values,
    the canonical spelling wins."""
    forward = normalize_readings({"chlorine": 2.5, "free_chlorine": 3.0})
    reverse = normalize_readings({"free_chlorine": 3.0, "chlorine": 2.5})
    assert forward == reverse == {"chlorine": 2.5}


# ═════════════════════════════════════════════════════════════════════
# List-of-dicts payload shape (service_reports.chemical_readings).
# ═════════════════════════════════════════════════════════════════════
def test_list_shape_normalises_and_dedupes():
    rows = [
        {"key": "pH",               "value": 7.4},
        {"key": "Total Alkalinity", "value": 90},
        {"key": "Cyanuric Acid",    "value": 40},
        {"key": "Free Chlorine",    "value": 3.0},
    ]
    out = normalize_readings(rows)
    assert out == {
        "ph":              7.4,
        "alkalinity":      90,
        "cyanuric_acid":   40,
        "chlorine":        3.0,
    }


def test_list_shape_real_beats_empty():
    rows = [
        {"key": "ph",   "value": ""},
        {"key": "pH",   "value": 7.4},
    ]
    assert normalize_readings(rows) == {"ph": 7.4}


def test_list_shape_zero_carveout_for_ph():
    rows = [
        {"key": "ph",   "value": 0},
        {"key": "pH",   "value": 7.4},
    ]
    assert normalize_readings(rows) == {"ph": 7.4}
