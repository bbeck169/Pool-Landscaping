"""TD-65 · Feb-2026 — BE defense-in-depth comma-locale tolerance.

Mobile Phase 2a (``b856d35d6``) migrated the three missed chemistry
input surfaces (`ChemicalDropdownStack`, `ChemicalPickerSheet`,
`MaintenanceLog`) onto ``sanitizeDecimalInput`` so iOS / EU-locale
readings arrive at the API with the comma already normalized to a
dot.  This test suite locks the BE belt-and-suspenders: any value
that arrives from a surface we might miss in future — a 3rd-party
water-test kit webhook, a CSV import, an off-platform integration —
is now tolerated at the parse boundary instead of silently dropping
through ``float("7,6")`` → ``ValueError`` → ``None`` classification.

Scope of the widening:
  * Fast-path values (float / int / dot-string) take EXACTLY the
    same path as before — no behavior change for US-locale callers.
  * Comma-only strings (``"7,6"``) get normalized once at the parse
    boundary in both ``classify_reading`` + ``pool_dosing._normalize``.
  * Values with BOTH comma and dot (``"1,000.5"``) are left alone so
    the thousands-separator ambiguity still rejects cleanly (we would
    rather drop a reading than silently miscount by a factor of 1000).
  * Double-dot / letters / junk continue to return ``None``.
"""
from __future__ import annotations

import pytest

from services.chemistry import classify_reading
from services.pool_dosing import _normalize


# ─────────────────────────────────────────────────────────────────
# 1 · US-locale fast path — regression lock.
# ─────────────────────────────────────────────────────────────────
class TestUSLocaleFastPathUnchanged:
    """Values the pre-TD-65 code already handled must behave
    identically — no silent widening of 'average' / 'above' bands,
    no change to the band ordering."""

    def test_float_7_6_still_classifies_above_mid_for_ph(self):
        # pH thresholds: lo=7.2, mid=7.6, hi=7.8 (from chemistry.py).
        # 7.6 is exactly on the mid ceiling → "average".
        assert classify_reading("ph", 7.6) == "average"

    def test_float_7_7_still_above(self):
        assert classify_reading("ph", 7.7) == "above"

    def test_float_7_9_still_above(self):
        # pH thresholds: lo=7.2, mid=7.6, hi=8.0.  7.9 > mid 7.6 but
        # 7.9 <= hi 8.0, so this stays "above" (NOT "elevated").
        assert classify_reading("ph", 7.9) == "above"

    def test_float_8_01_elevated(self):
        # Strictly above the hi=8.0 ceiling → "elevated".
        assert classify_reading("ph", 8.01) == "elevated"

    def test_dot_string_7_6_matches_float_7_6(self):
        assert classify_reading("ph", "7.6") == classify_reading("ph", 7.6)

    def test_int_passthrough(self):
        # Chlorine (free): lo=1, mid=3, hi=5.  Integer 2 → "average".
        assert classify_reading("chlorine", 2) == "average"


# ─────────────────────────────────────────────────────────────────
# 2 · TD-65 NEW — comma-locale strings now classify correctly.
# ─────────────────────────────────────────────────────────────────
class TestCommaLocaleTolerance:
    """iOS / EU-locale strings arriving via a 3rd-party integration
    (CSV, webhook, legacy fat client) that was NOT running through
    ``sanitizeDecimalInput`` on the way in must now round-trip
    through the BE parse boundary without dropping."""

    def test_comma_string_7_6_classifies_same_as_dot_string(self):
        assert classify_reading("ph", "7,6") == classify_reading("ph", "7.6")
        assert classify_reading("ph", "7,6") == "average"

    def test_comma_string_7_7_above(self):
        assert classify_reading("ph", "7,7") == "above"

    def test_comma_string_8_01_elevated(self):
        assert classify_reading("ph", "8,01") == "elevated"

    def test_comma_string_0_5_chlorine_below(self):
        # Chlorine lo=2, mid=5, hi=8.  0.5 is below the lo ceiling.
        assert classify_reading("chlorine", "0,5") == "below"

    def test_comma_string_100_5_alkalinity(self):
        # Alkalinity: lo=80, mid=120, hi=140.  100.5 → "average".
        assert classify_reading("alkalinity", "100,5") == "average"

    def test_leading_trailing_whitespace_still_strips(self):
        assert classify_reading("ph", "   7,6   ") == "average"
        assert classify_reading("ph", "\t7.6\n")   == "average"


# ─────────────────────────────────────────────────────────────────
# 3 · Rejection surface — unchanged + ambiguous shapes.
# ─────────────────────────────────────────────────────────────────
class TestRejectionSurfaceUnchanged:
    """Everything that returned ``None`` pre-TD-65 must continue
    to return ``None``.  The widening MUST NOT accidentally start
    accepting junk that would mis-classify."""

    def test_double_dot_rejected(self):
        assert classify_reading("ph", "7.6.5") is None

    def test_double_comma_rejected(self):
        assert classify_reading("ph", "7,6,5") is None

    def test_letters_rejected(self):
        assert classify_reading("ph", "abc") is None

    def test_mixed_letters_and_numeric_rejected(self):
        assert classify_reading("ph", "7.6a") is None

    def test_none_returns_none(self):
        assert classify_reading("ph", None) is None

    def test_empty_string_returns_none(self):
        assert classify_reading("ph", "") is None

    def test_whitespace_only_returns_none(self):
        # str("   ").strip() == "" → float("") → ValueError → None.
        assert classify_reading("ph", "   ") is None

    def test_thousands_separator_ambiguity_still_rejected(self):
        # "1,000.5" carries both comma + dot → ambiguous → reject
        # rather than silently miscount by 1000x.
        assert classify_reading("alkalinity", "1,000.5") is None

    def test_unknown_chemical_returns_none(self):
        assert classify_reading("fake_chem", "7.6") is None


# ─────────────────────────────────────────────────────────────────
# 4 · ``pool_dosing._normalize`` mirror — same tolerance surface.
# ─────────────────────────────────────────────────────────────────
class TestPoolDosingNormalizeMirror:
    """``_normalize`` and ``classify_reading`` MUST widen in sync —
    otherwise the band classifier and the dosing recommender will
    disagree on which readings survived parsing."""

    def test_dot_string_round_trip(self):
        assert _normalize({"ph": "7.6"}) == {"ph": 7.6}

    def test_comma_string_normalizes(self):
        # TD-65 NEW — pre-TD-65 this dropped the reading silently.
        assert _normalize({"ph": "7,6"}) == {"ph": 7.6}

    def test_mixed_dot_and_comma_readings_in_one_dict(self):
        # NB: ``pool_dosing._ALIASES`` canonicalizes ``alkalinity`` →
        # ``total_alkalinity``; different alias set than
        # ``chemistry._ALIASES``.  The two helpers can disagree on
        # output key names but MUST agree on which rows survive.
        got = _normalize({"ph": "7,6", "chlorine": "2.5", "alkalinity": 100})
        assert got == {"ph": 7.6, "chlorine": 2.5, "total_alkalinity": 100.0}

    def test_junk_still_skipped_without_poisoning_siblings(self):
        got = _normalize({
            "ph": "abc",       # junk — must be skipped
            "chlorine": "2,5", # TD-65 NEW — must survive
            "alkalinity": 100, # fast path — must survive (as ``total_alkalinity``)
        })
        assert "ph" not in got
        assert got["chlorine"] == 2.5
        assert got["total_alkalinity"] == 100.0

    def test_empty_and_none_values_skipped(self):
        got = _normalize({
            "ph": None,
            "chlorine": "",
            "alkalinity": "   ",
            "cyanuric_acid": "45,2",   # canonical key in pool_dosing._ALIASES
        })
        # pre-TD-65 lock: empty / None drop cleanly; TD-65 adds the
        # whitespace-trim to the comma-string path.
        assert "ph" not in got
        assert "chlorine" not in got
        # str("   ").strip() == "" → float("") raises → skipped.
        assert "total_alkalinity" not in got
        # cyanuric_acid is its own canonical in pool_dosing._ALIASES
        # (NB: ``services/chemistry.py`` uses ``cya`` as canonical;
        # the two helpers deliberately differ on alias target).
        assert got.get("cyanuric_acid") == 45.2

    def test_thousands_separator_ambiguity_in_normalize_also_rejected(self):
        got = _normalize({"alkalinity": "1,000.5"})
        assert "alkalinity" not in got

    def test_unknown_key_skipped_without_affecting_siblings(self):
        got = _normalize({"not_a_chemical": "7,6", "ph": "7,6"})
        assert "not_a_chemical" not in got
        assert got.get("ph") == 7.6


# ─────────────────────────────────────────────────────────────────
# 5 · Band ordering under the new tolerance — parametrized sweep.
# ─────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("value_str, expected_band", [
    ("7,0",  "below"),      # pH 7.0 < lo 7.2
    ("7,2",  "average"),    # pH 7.2 == lo → average
    ("7,5",  "average"),    # mid-range
    ("7,6",  "average"),    # TD-65 operator-example value (== mid 7.6)
    ("7,61", "above"),      # strictly above mid 7.6
    ("7,8",  "above"),      # mid-range of the "above" band
    ("8,0",  "above"),      # == hi 8.0, still "above" (strictly above triggers elevated)
    ("8,01", "elevated"),   # strictly above hi 8.0
])
def test_ph_band_parity_across_comma_strings(value_str, expected_band):
    assert classify_reading("ph", value_str) == expected_band
