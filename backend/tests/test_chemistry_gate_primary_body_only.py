"""Phase CHEM2 · Feb-2026 — primary-body-only Required-Four enforcement.

The CHEM1 rule (Required Four on every readable body) was too strict
for real-world pool service, where a customer may have a spa /
fountain / secondary pool the tech doesn't touch every visit. The
CHEM2 rule narrows enforcement to the PRIMARY body only:

    * A body flagged ``is_primary=True`` wins.
    * Else the first dict entry in ``water_bodies``.
    * If nothing dict-shaped is present, the gate passes trivially.

Additional bodies may be entirely blank without blocking close.

Exception contract preserved byte-identically:
    * ``HTTPException`` class, ``status_code=422``.
    * ``detail`` keys unchanged (``detail``, ``missing_fields``,
      ``missing_labels``, ``bodies``, ``message``).
    * The ``bodies`` array now contains AT MOST ONE offender entry —
      the primary body — reflecting the narrowed enforcement.
"""
from __future__ import annotations

from typing import Any, Dict, List

import pytest
from fastapi import HTTPException

from services.chemistry_gate import (
    assert_bodies_required_readings_present,
    _pick_primary_body,
)


def _body(**kw: Any) -> Dict[str, Any]:
    """Build a pool-typed body dict with a readings payload."""
    defaults = {
        "id": kw.pop("id", f"wb-{kw.get('label', 'anon')}"),
        "type": kw.pop("type", "pool"),
        "label": kw.pop("label", None),
    }
    readings = kw.pop("readings", {})
    return {**defaults, **kw, "readings": readings}


_FULL = {
    "free_chlorine": 2.5,
    "ph":            7.4,
    "alkalinity":    90,
    "cyanuric_acid": 45,
}


# ─── _pick_primary_body ───────────────────────────────────────────

def test_pick_primary_body_prefers_is_primary_flag_over_position():
    b1 = _body(label="Big")
    b2 = _body(label="Small", is_primary=True)
    assert _pick_primary_body([b1, b2]) is b2


def test_pick_primary_body_falls_back_to_first_when_no_flag():
    b1 = _body(label="Big")
    b2 = _body(label="Small")
    assert _pick_primary_body([b1, b2]) is b1


def test_pick_primary_body_returns_none_for_empty_list():
    assert _pick_primary_body([]) is None


def test_pick_primary_body_skips_non_dict_entries():
    b = _body(label="Real")
    assert _pick_primary_body([None, "not a body", b]) is b


def test_pick_primary_body_first_dict_wins_when_only_string_prefix():
    b1 = _body(label="Real 1")
    b2 = _body(label="Real 2", is_primary=True)
    assert _pick_primary_body(["nope", b1, b2]) is b2


# ─── assert_bodies_required_readings_present ──────────────────────

def test_single_body_fully_filled_passes():
    assert_bodies_required_readings_present([_body(readings=dict(_FULL))])


def test_single_body_missing_ph_raises_422_with_ph_in_message():
    partial = {**_FULL, "ph": ""}
    with pytest.raises(HTTPException) as ei:
        assert_bodies_required_readings_present([_body(readings=partial)])
    err = ei.value
    assert err.status_code == 422
    assert err.detail["detail"] == "chemistry_core_readings_missing"
    assert "pH" in err.detail["message"]
    # bodies array unchanged shape — a single-element list post-CHEM2.
    assert isinstance(err.detail["bodies"], list)
    assert len(err.detail["bodies"]) == 1


def test_two_body_report_primary_filled_spa_blank_passes():
    primary = _body(label="Pool", readings=dict(_FULL))
    spa = _body(label="Spa", type="pool", readings={})
    assert_bodies_required_readings_present([primary, spa])


def test_two_body_report_primary_missing_ph_spa_filled_raises_on_primary():
    primary = _body(label="Pool", readings={**_FULL, "ph": ""})
    spa = _body(label="Spa", type="pool", readings=dict(_FULL))
    with pytest.raises(HTTPException) as ei:
        assert_bodies_required_readings_present([primary, spa])
    err = ei.value
    assert err.status_code == 422
    assert "pH" in err.detail["message"]
    # The offender must be the PRIMARY body — not the spa.
    assert len(err.detail["bodies"]) == 1
    assert err.detail["bodies"][0]["label"] == "Pool"


def test_two_body_report_primary_filled_spa_missing_ph_passes():
    primary = _body(label="Pool", readings=dict(_FULL))
    spa = _body(label="Spa", type="pool", readings={**_FULL, "ph": ""})
    # Spa may be blank — the CHEM2 rule says only primary is gated.
    assert_bodies_required_readings_present([primary, spa])


def test_is_primary_flag_on_second_body_moves_enforcement_to_it():
    first = _body(label="Blank first", type="pool", readings={})
    marked = _body(label="Real primary", type="pool",
                    readings=dict(_FULL), is_primary=True)
    # Second body is marked as primary — it's filled → passes.
    # First body is empty but is NOT primary → does NOT block.
    assert_bodies_required_readings_present([first, marked])


def test_is_primary_flag_on_second_body_missing_ph_raises_on_it_not_the_first():
    first = _body(label="Blank first", type="pool", readings={})
    marked = _body(label="Real primary", type="pool",
                    readings={**_FULL, "ph": ""}, is_primary=True)
    with pytest.raises(HTTPException) as ei:
        assert_bodies_required_readings_present([first, marked])
    # Enforcement is on the MARKED body — the raise mentions its label.
    assert ei.value.detail["bodies"][0]["label"] == "Real primary"
    assert ei.value.detail["bodies"][0]["id"] == "wb-Real primary"


def test_zero_value_in_free_chlorine_counts_as_filled():
    body = _body(readings={**_FULL, "free_chlorine": 0})
    assert_bodies_required_readings_present([body])
    # And zero as a numeric string.
    body2 = _body(readings={**_FULL, "free_chlorine": "0"})
    assert_bodies_required_readings_present([body2])


@pytest.mark.parametrize("blank", ["", "   ", None])
def test_whitespace_null_empty_do_not_count_as_filled(blank: Any):
    body = _body(readings={**_FULL, "free_chlorine": blank})
    with pytest.raises(HTTPException):
        assert_bodies_required_readings_present([body])


def test_alkalinity_alias_canonicalizes():
    # ``total_alkalinity`` folds onto ``alkalinity``.
    body = _body(readings={
        "free_chlorine": 2.5, "ph": 7.4,
        "total_alkalinity": 90, "cyanuric_acid": 45,
    })
    assert_bodies_required_readings_present([body])


def test_cya_alias_canonicalizes():
    body = _body(readings={
        "free_chlorine": 2.5, "ph": 7.4,
        "alkalinity": 90, "cya": 45,
    })
    assert_bodies_required_readings_present([body])


def test_free_cl_alias_canonicalizes():
    body = _body(readings={
        "free_cl": 2.5, "ph": 7.4,
        "alkalinity": 90, "cyanuric_acid": 45,
    })
    assert_bodies_required_readings_present([body])


def test_empty_bodies_list_passes_trivially_with_log(caplog: Any):
    import logging
    with caplog.at_level(logging.INFO):
        assert_bodies_required_readings_present([])
    assert any("no bodies to enforce" in r.message for r in caplog.records)


def test_falsy_bodies_input_passes(caplog: Any):
    import logging
    with caplog.at_level(logging.INFO):
        assert_bodies_required_readings_present(None)
    assert any("no bodies to enforce" in r.message for r in caplog.records)


def test_non_list_bodies_passes():
    # Malformed input — a dict where a list was expected.
    assert_bodies_required_readings_present({"not": "a list"})


def test_bodies_list_of_non_dicts_passes_with_log(caplog: Any):
    import logging
    with caplog.at_level(logging.INFO):
        assert_bodies_required_readings_present([None, "str", 42])
    assert any("no dict entries" in r.message for r in caplog.records)


def test_missing_message_format_names_primary_label_not_generic_wording():
    body = _body(label="Kids Pool", readings={**_FULL, "ph": ""})
    with pytest.raises(HTTPException) as ei:
        assert_bodies_required_readings_present([body])
    msg = ei.value.detail["message"]
    assert "Kids Pool" in msg
    # Pre-CHEM2 generic wording is gone.
    assert "on one or more water bodies" not in msg


def test_missing_fields_labels_ordering_matches_core_readings():
    # ``chlorine`` before ``ph`` before ``alkalinity`` before
    # ``cyanuric_acid`` per CORE_READINGS ordering. Phase P17.1 ·
    # Feb-2026 flipped the chlorine display label from ``Free Cl``
    # to ``Chlorine``.
    body = _body(readings={})  # ALL four missing
    with pytest.raises(HTTPException) as ei:
        assert_bodies_required_readings_present([body])
    labels = ei.value.detail["missing_labels"]
    assert labels == ["Chlorine", "Alkalinity", "pH", "CYA"]


def test_detail_schema_is_byte_compatible_with_pre_chem2():
    # The ``detail`` dict keys must be exactly this set — any addition
    # or removal is a breaking API change.
    body = _body(readings={})
    with pytest.raises(HTTPException) as ei:
        assert_bodies_required_readings_present([body])
    assert set(ei.value.detail.keys()) == {
        "detail", "missing_fields", "missing_labels", "bodies", "message",
    }
    # ``detail`` string sentinel unchanged for FE consumers keying on it.
    assert ei.value.detail["detail"] == "chemistry_core_readings_missing"


def test_non_pool_primary_body_type_not_gated():
    # A ``feature`` (non-pool) type with no readings passes because
    # READING_REQUIRED has no entry for it.
    body = _body(label="Fountain", type="feature", readings={})
    # Even if the second body is a pool with missing readings, the
    # PRIMARY is the feature (first body) — so we still pass.
    also = _body(label="Real pool", type="pool", readings={})
    assert_bodies_required_readings_present([body, also])
