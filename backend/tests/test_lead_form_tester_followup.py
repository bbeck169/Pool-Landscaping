"""Feb-2026 · Lead-form tester follow-up — three fixes locked:

  1. ``service_interest`` whitelist widened — free-form phrases
     like "Pool cleaning" are persisted verbatim (truncated to
     120 chars) instead of being coerced to ``null``.
  2. Address state-parser tightened — "123 Test St" no longer
     auto-rejects with ``rejected_state: "ST"`` (a street-suffix
     false positive). Only real US state codes are honored.
  3. Explicit ``state`` field on the lead must be a real US
     state to be trusted (was previously any 2-letter alpha).
"""
from __future__ import annotations

import pytest

from services.leads_side_effects import _extract_state, _US_STATE_CODES
from routers.leads import _normalize_interest


# ─── Fix 1 — service_interest widened acceptance ────────────────

def test_normalize_interest_passes_free_form_verbatim():
    """Free-form phrases from the tester recipe MUST land on the
    lead row verbatim — not coerced to ``null`` because they miss
    the historical ``{Pool,Landscape,Both}`` enum."""
    assert _normalize_interest("Pool cleaning") == "Pool cleaning"
    assert (_normalize_interest(
        "Landscape design + monthly maintenance")
        == "Landscape design + monthly maintenance")
    # Legacy enum values still pass through unchanged.
    assert _normalize_interest("Pool") == "Pool"
    assert _normalize_interest("Both") == "Both"


def test_normalize_interest_trims_whitespace_and_caps_length():
    """Whitespace-only → None. Long free-form phrases truncated to
    120 chars so the column stays indexable."""
    assert _normalize_interest("   ") is None
    assert _normalize_interest("") is None
    assert _normalize_interest(None) is None
    long = "A" * 500
    out = _normalize_interest(long)
    assert out is not None and len(out) == 120


# ─── Fix 2 — state parser rejects street-suffix false positives ──

@pytest.mark.parametrize("addr", [
    "123 Test St",
    "456 Main St",
    "789 Oak Rd",
    "10 Elm Ave",
    "22 Pine Dr",
    "33 Maple Pl",
])
def test_state_parser_ignores_street_suffix_tokens(addr):
    """The historical parser uppercased the whole address and
    matched ``\\b[A-Z]{2}\\b`` at end-of-string, which promoted
    "St" / "Rd" / "Ave" / "Dr" / "Pl" tail suffixes to state
    codes like "ST" / "RD" and auto-rejected legitimate leads.
    The whitelist blocks every one of those."""
    assert _extract_state({"service_address": addr}) is None


def test_state_parser_matches_real_state_at_tail():
    """A real US state code at end-of-string still matches — the
    tightening only rejects non-state 2-letter tokens."""
    assert _extract_state({"service_address": "123 Main St, Peoria AZ"}) == "AZ"
    assert _extract_state(
        {"service_address": "Peoria AZ 85383"}) == "AZ"
    assert _extract_state(
        {"service_address": "1 Palace Ln, Sacramento CA 95814"}) == "CA"


def test_state_parser_rejects_lowercase_st_in_raw_address():
    """The parser now runs against the RAW address (case
    preserved), so a "St" street suffix (title case) can never
    hit the ``[A-Z]{2}`` regex in the first place."""
    # No state token, no ZIP — the raw match yields nothing.
    assert _extract_state({"service_address": "123 test st"}) is None


def test_state_parser_ignores_non_state_uppercase_two_letter_tokens():
    """Even at end-of-string, arbitrary uppercase 2-letter codes
    that aren't real states drop out."""
    # "ZZ" and "XX" aren't states.
    assert _extract_state({"service_address": "123 Main St ZZ"}) is None
    assert _extract_state({"service_address": "42 Elm Rd XX"}) is None


# ─── Fix 3 — explicit ``state`` field also validated ────────────

def test_state_parser_explicit_state_must_be_real_us_code():
    """The lead doc may carry a separate ``state`` field. It must
    also survive the whitelist — historical code trusted any
    2-letter alpha input which meant a bad admin entry ("XX")
    could quietly auto-reject the lead."""
    # Real state — trusted.
    assert _extract_state({"state": "az"}) == "AZ"
    # Fake state — parser returns None (no auto-reject fires).
    assert _extract_state({"state": "XX"}) is None
    assert _extract_state({"state": "ST"}) is None


def test_state_parser_whitelist_covers_51_codes():
    """DC + 50 states — sanity guard on the whitelist itself."""
    assert len(_US_STATE_CODES) == 51
    assert "CA" in _US_STATE_CODES
    assert "TX" in _US_STATE_CODES
    assert "DC" in _US_STATE_CODES
    # Street suffixes NEVER slip in.
    for _suffix in ("ST", "RD", "AV", "PL", "DR", "LN"):
        assert _suffix not in _US_STATE_CODES, _suffix
