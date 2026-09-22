"""Phase P17.1 · Feb-2026 — chlorine canonical wire-contract flip.

Locks in the 422 wire contract flip from the P17 canonical
``free_chlorine`` / ``free_cl`` / ``Free Cl`` set onto the new
P17.1 canonical ``chlorine`` / ``chlorine`` / ``Chlorine`` set.

Acceptance criteria (product-approved, Feb-2026):

  1. Payload missing chlorine only → 422 with ``missing_fields`` and
     ``missing_labels`` each equal to exactly ``["chlorine"]`` and
     ``["Chlorine"]`` respectively.  The legacy P17 short label
     ``free_cl`` / display label ``Free Cl`` MUST no longer appear.
  2. Payload with ``free_chlorine: 3.0`` (legacy alias) plus the
     remaining three Required Four → gate passes trivially, and the
     normalized output shape is keyed by ``chlorine``.
  3. Payload with ``chlorine: 3.0`` (new canonical) plus the
     remaining three Required Four → gate passes trivially and
     produces IDENTICAL normalized shape to the legacy-alias payload.
  4. Every legacy source alias (``free_chlorine``, ``free_cl``,
     ``freecl``, ``fc``, ``Free Chlorine``, ``Free Cl``) resolves to
     the new canonical ``chlorine`` — proving the backwards-compat
     ALIAS_MAP entry survives the flip.

No data migration is required: stored docs still carrying
``readings.free_chlorine`` continue to satisfy the gate via the
READ-path alias lookup.  This test is a pure-Python contract test
against ``services.chemistry_gate`` — no DB, no HTTP round-trip.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from services.chemistry_gate import (
    ALIAS_MAP,
    CORE_READINGS,
    DISPLAY_LABELS,
    _LABEL,
    assert_core_readings_present,
    missing_core_reading_labels,
    missing_core_readings,
    normalize_readings,
)


# ═════════════════════════════════════════════════════════════════════
# Module-constant snapshots — the P17.1 canonical MUST land here.
# ═════════════════════════════════════════════════════════════════════
def test_core_readings_contains_chlorine_and_not_free_chlorine():
    """The Required Four canonical list carries ``chlorine`` (new
    P17.1 spelling) and NOT the legacy ``free_chlorine``."""
    assert "chlorine" in CORE_READINGS
    assert "free_chlorine" not in CORE_READINGS
    # Exact set — no accidental additions or removals.
    assert set(CORE_READINGS) == {
        "chlorine", "alkalinity", "ph", "cyanuric_acid",
    }


def test_short_label_map_uses_chlorine_not_free_cl():
    """``_LABEL`` (short/machine labels used by
    ``missing_fields``) maps ``chlorine`` → ``"chlorine"`` and no
    longer carries the legacy ``free_cl`` sentinel."""
    assert _LABEL["chlorine"] == "chlorine"
    assert "free_chlorine" not in _LABEL
    assert "free_cl" not in _LABEL.values()


def test_display_label_map_uses_chlorine_not_free_cl():
    """``DISPLAY_LABELS`` (human labels used by ``missing_labels``)
    maps ``chlorine`` → ``"Chlorine"`` and no longer carries the
    legacy ``"Free Cl"`` sentinel."""
    assert DISPLAY_LABELS["chlorine"] == "Chlorine"
    assert "free_chlorine" not in DISPLAY_LABELS
    assert "Free Cl" not in DISPLAY_LABELS.values()


# ═════════════════════════════════════════════════════════════════════
# ALIAS_MAP preserves every legacy source alias pointing at the new
# canonical ``chlorine``.
# ═════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("legacy_alias", [
    "free_chlorine",
    "free_cl",
    "freecl",
    "fc",
])
def test_legacy_chlorine_aliases_still_resolve_to_new_canonical(legacy_alias):
    """Backwards-compat: every legacy source spelling for chlorine
    still folds onto ``chlorine`` via ALIAS_MAP.  No data migration
    required — stored ``readings.free_chlorine`` docs keep resolving."""
    assert ALIAS_MAP[legacy_alias] == "chlorine"


@pytest.mark.parametrize("legacy_alias", [
    "free_chlorine",
    "free_cl",
    "freecl",
    "fc",
    "Free Chlorine",
    "Free Cl",
    "FreeCl",
    "FC",
])
def test_legacy_chlorine_aliases_normalize_to_new_canonical(legacy_alias):
    """End-to-end via ``normalize_readings`` — every legacy source
    spelling (including mixed-case + spaced) resolves to a
    single-entry ``{chlorine: 3.0}`` output."""
    out = normalize_readings({legacy_alias: 3.0})
    assert out == {"chlorine": 3.0}, out


# ═════════════════════════════════════════════════════════════════════
# 422 wire-contract flip — missing chlorine only.
# ═════════════════════════════════════════════════════════════════════
def test_missing_chlorine_only_returns_chlorine_short_label():
    """``missing_core_readings`` on a payload with only chlorine
    missing emits the new short label ``"chlorine"`` — and NEVER
    the legacy ``"free_cl"``."""
    r = missing_core_readings({
        "ph":             7.4,
        "alkalinity":     90,
        "cyanuric_acid":  40,
        # chlorine deliberately missing
    })
    assert r == ["chlorine"], r
    assert "free_cl" not in r


def test_missing_chlorine_only_returns_chlorine_display_label():
    """``missing_core_reading_labels`` on a payload with only
    chlorine missing emits the new display label ``"Chlorine"`` —
    and NEVER the legacy ``"Free Cl"``."""
    r = missing_core_reading_labels({
        "ph":             7.4,
        "alkalinity":     90,
        "cyanuric_acid":  40,
        # chlorine deliberately missing
    })
    assert r == ["Chlorine"], r
    assert "Free Cl" not in r


def test_gate_raise_missing_chlorine_only_exposes_chlorine_labels():
    """The 422 detail payload MUST expose the new canonical short
    + display labels when chlorine is the only missing reading."""
    with pytest.raises(HTTPException) as ei:
        assert_core_readings_present({
            "ph":             7.4,
            "alkalinity":     90,
            "cyanuric_acid":  40,
            # chlorine deliberately missing
        })
    d = ei.value.detail
    assert d["detail"] == "chemistry_core_readings_missing"
    # Short (machine) label — for ``missing_fields`` consumers.
    assert d["missing_fields"] == ["chlorine"]
    # Display (human) label — for ``missing_labels`` consumers.
    assert d["missing_labels"] == ["Chlorine"]
    # Legacy short + display labels are gone from the payload.
    assert "free_cl" not in d["missing_fields"]
    assert "Free Cl" not in d["missing_labels"]


def test_gate_raise_everything_missing_exposes_chlorine_in_full_arrays():
    """When ALL four readings are missing, the 422 payload's
    ``missing_fields`` / ``missing_labels`` arrays include
    ``chlorine`` / ``Chlorine`` (new P17.1 canonical) in the
    :data:`CORE_READINGS` order — and NEVER the legacy
    ``free_cl`` / ``Free Cl`` sentinels."""
    with pytest.raises(HTTPException) as ei:
        assert_core_readings_present({})
    d = ei.value.detail
    assert d["missing_fields"] == ["chlorine", "alkalinity", "ph", "cya"]
    assert d["missing_labels"] == ["Chlorine", "Alkalinity", "pH", "CYA"]
    # Arrays stay index-aligned so callers can zip them.
    assert len(d["missing_fields"]) == len(d["missing_labels"])


# ═════════════════════════════════════════════════════════════════════
# Payload equivalence — free_chlorine vs chlorine produce identical
# stored / reported shape after normalize.
# ═════════════════════════════════════════════════════════════════════
def test_gate_passes_with_legacy_free_chlorine_alias():
    """Backwards-compat: a payload carrying ``free_chlorine: 3.0``
    still satisfies the gate."""
    assert_core_readings_present({
        "free_chlorine":  3.0,
        "ph":             7.4,
        "alkalinity":     90,
        "cyanuric_acid":  40,
    })


def test_gate_passes_with_new_chlorine_canonical():
    """The new ``chlorine: 3.0`` canonical also satisfies the gate."""
    assert_core_readings_present({
        "chlorine":       3.0,
        "ph":             7.4,
        "alkalinity":     90,
        "cyanuric_acid":  40,
    })


def test_legacy_and_canonical_payloads_normalize_to_identical_shape():
    """Both payloads (legacy ``free_chlorine`` alias + new
    ``chlorine`` canonical) produce BYTE-IDENTICAL normalized
    output — proving the wire contract flip preserves stored shape."""
    legacy = normalize_readings({
        "free_chlorine":  3.0,
        "ph":             7.4,
        "alkalinity":     90,
        "cyanuric_acid":  40,
    })
    canonical = normalize_readings({
        "chlorine":       3.0,
        "ph":             7.4,
        "alkalinity":     90,
        "cyanuric_acid":  40,
    })
    assert legacy == canonical == {
        "chlorine":       3.0,
        "ph":             7.4,
        "alkalinity":     90,
        "cyanuric_acid":  40,
    }


def test_legacy_and_canonical_list_shape_payloads_produce_identical_normalize():
    """Same equivalence guarantee for the ``service_reports
    .chemical_readings`` list-of-dicts payload shape."""
    legacy_rows = [
        {"key": "free_chlorine",  "value": 3.0},
        {"key": "ph",             "value": 7.4},
        {"key": "alkalinity",     "value": 90},
        {"key": "cyanuric_acid",  "value": 40},
    ]
    canonical_rows = [
        {"key": "chlorine",       "value": 3.0},
        {"key": "ph",             "value": 7.4},
        {"key": "alkalinity",     "value": 90},
        {"key": "cyanuric_acid",  "value": 40},
    ]
    legacy_norm = normalize_readings(legacy_rows)
    canonical_norm = normalize_readings(canonical_rows)
    assert legacy_norm == canonical_norm == {
        "chlorine":       3.0,
        "ph":             7.4,
        "alkalinity":     90,
        "cyanuric_acid":  40,
    }


# ═════════════════════════════════════════════════════════════════════
# Ordering guarantee — the ``missing_fields`` / ``missing_labels``
# arrays follow :data:`CORE_READINGS` ordering with ``chlorine`` in
# position 0.
# ═════════════════════════════════════════════════════════════════════
def test_missing_fields_ordering_places_chlorine_first():
    """When multiple readings are missing, ``missing_fields`` /
    ``missing_labels`` follow the :data:`CORE_READINGS` order and
    ``chlorine`` / ``Chlorine`` sits in position 0."""
    with pytest.raises(HTTPException) as ei:
        # Only pH filled — chlorine, alkalinity, CYA missing.
        assert_core_readings_present({"ph": 7.4})
    d = ei.value.detail
    assert d["missing_fields"][0] == "chlorine"
    assert d["missing_labels"][0] == "Chlorine"
    # ``ph`` NOT in either array since it's filled.
    assert "ph" not in d["missing_fields"]
    assert "pH" not in d["missing_labels"]
