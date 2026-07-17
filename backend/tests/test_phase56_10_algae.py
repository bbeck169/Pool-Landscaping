"""Phase 56.10 — Visible-algae observation + AI remediation dosing.

Unit-level tests over `services.pool_dosing.compute` — no HTTP, no DB.
The router glue (`RecommendChemicalsBody.visible_algae`) is exercised
indirectly by the existing pool-recommendations UI + will get its own
integration-level smoke in the Phase 56.10 UI ship report.
"""
import os
import sys
from pathlib import Path

import pytest

# Make `services.pool_dosing` importable without spinning up FastAPI.
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.pool_dosing import compute  # noqa: E402


_GALLONS = 20_000


def _by_category(recs, cat):
    return [r for r in recs if r.get("category") == cat]


def _by_chemical(recs, substr):
    return [r for r in recs if substr.lower() in r["chemical"].lower()]


class TestVisibleAlgaeStates:
    """The three toggle states — none / light / heavy — drive the algae
    remediation branch."""

    def test_none_emits_no_algae_entries(self):
        recs = compute({"free_chlorine": 2.0, "ph": 7.4}, _GALLONS,
                       visible_algae="none")
        assert _by_category(recs, "algae_remediation") == []
        assert _by_category(recs, "ordering_note") == []

    def test_light_emits_one_cal_hypo_entry(self):
        recs = compute({"free_chlorine": 2.0, "ph": 7.4}, _GALLONS,
                       visible_algae="light")
        algae = _by_category(recs, "algae_remediation")
        assert len(algae) == 1, f"expected 1 algae entry, got {len(algae)}: {algae}"
        entry = algae[0]
        assert entry["unit"] == "lbs"
        assert "hypochlorite" in entry["chemical"].lower()
        assert entry["severity"] == "light"
        assert "Brush walls" in entry.get("guidance_note", "")
        assert "24h" in entry.get("guidance_note", "")
        assert "73%" in entry["preferred_form_reason"]

    def test_heavy_emits_cal_hypo_plus_polyquat(self):
        recs = compute({"free_chlorine": 2.0, "ph": 7.4}, _GALLONS,
                       visible_algae="heavy")
        algae = _by_category(recs, "algae_remediation")
        assert len(algae) == 2, algae
        chemicals = {a["chemical"] for a in algae}
        assert any("hypochlorite" in c.lower() for c in chemicals), chemicals
        assert any("polyquat" in c.lower() for c in chemicals), chemicals
        polyquat = _by_chemical(algae, "polyquat")[0]
        cal_hypo = _by_chemical(algae, "hypochlorite")[0]
        assert polyquat["unit"] == "oz"
        assert cal_hypo["unit"] == "lbs"
        # 30 ppm boost → roughly 3× the light dose.
        light_recs = compute({"free_chlorine": 2.0, "ph": 7.4}, _GALLONS,
                             visible_algae="light")
        light_cal_hypo = _by_chemical(_by_category(light_recs, "algae_remediation"),
                                       "hypochlorite")[0]
        # Not strictly 3× because rounding differs, but within 5%.
        ratio = cal_hypo["quantity"] / light_cal_hypo["quantity"]
        assert 2.85 <= ratio <= 3.15, f"expected ~3x scaling, got {ratio}"
        assert "backwash" in cal_hypo.get("guidance_note", "").lower()
        assert "Recheck FC" in cal_hypo.get("guidance_note", "")


class TestHighPhOrderingGuard:
    """When pH > 7.6 AND algae is present, the recommender prepends an
    ordering note telling the tech to drop pH before shocking."""

    def test_high_ph_prepends_ordering_note_on_light(self):
        recs = compute({"free_chlorine": 2.0, "ph": 8.0}, _GALLONS,
                       visible_algae="light")
        notes = _by_category(recs, "ordering_note")
        assert len(notes) == 1, notes
        assert "Lower pH to 7.2" in notes[0]["reason"]
        assert "muriatic acid FIRST" in notes[0]["reason"]
        # The note comes BEFORE the algae shock entry.
        algae_idx = next(i for i, r in enumerate(recs)
                         if r.get("category") == "algae_remediation")
        note_idx = next(i for i, r in enumerate(recs)
                        if r.get("category") == "ordering_note")
        assert note_idx < algae_idx, "ordering note must precede algae entry"

    def test_high_ph_prepends_ordering_note_on_heavy(self):
        recs = compute({"free_chlorine": 2.0, "ph": 7.9}, _GALLONS,
                       visible_algae="heavy")
        notes = _by_category(recs, "ordering_note")
        assert len(notes) == 1

    def test_normal_ph_no_ordering_note(self):
        recs = compute({"free_chlorine": 2.0, "ph": 7.4}, _GALLONS,
                       visible_algae="light")
        assert _by_category(recs, "ordering_note") == []

    def test_high_ph_but_no_algae_no_ordering_note(self):
        # High pH alone must NOT trigger the algae ordering note — the
        # existing muriatic-acid recommendation already handles pH.
        recs = compute({"free_chlorine": 2.0, "ph": 8.0}, _GALLONS,
                       visible_algae="none")
        assert _by_category(recs, "ordering_note") == []


class TestDoseScaling:
    """Cal-hypo linear scaling with pool_gallons and inverse scaling with
    available-chlorine trade strength."""

    def test_cal_hypo_scales_linearly_with_gallons(self):
        light_10k = compute({"free_chlorine": 2.0, "ph": 7.4}, 10_000,
                            visible_algae="light")
        light_30k = compute({"free_chlorine": 2.0, "ph": 7.4}, 30_000,
                            visible_algae="light")
        a = _by_chemical(_by_category(light_10k, "algae_remediation"), "hypochlorite")[0]
        b = _by_chemical(_by_category(light_30k, "algae_remediation"), "hypochlorite")[0]
        assert abs(b["quantity"] / a["quantity"] - 3.0) < 0.05, \
            f"expected 3x for 3x gallons, got {b['quantity']}/{a['quantity']}"

    def test_cal_hypo_dose_at_expected_magnitude(self):
        # 20,000 gal × 10 ppm / 120,000 × (73/73) = 1.666… lbs — round(2) = 1.67
        recs = compute({"free_chlorine": 2.0, "ph": 7.4}, 20_000,
                       visible_algae="light")
        a = _by_chemical(_by_category(recs, "algae_remediation"), "hypochlorite")[0]
        assert 1.6 <= a["quantity"] <= 1.75, a["quantity"]

    def test_cal_hypo_available_chlorine_pct_inverse_scaling(self, monkeypatch):
        # Doubling the trade strength halves the pounds needed.
        import services.pool_dosing as pd
        monkeypatch.setattr(pd, "CAL_HYPO_AVAILABLE_CHLORINE_PCT", 146)  # hypothetical 2x
        recs2 = compute({"free_chlorine": 2.0, "ph": 7.4}, 20_000,
                        visible_algae="light")
        monkeypatch.setattr(pd, "CAL_HYPO_AVAILABLE_CHLORINE_PCT", 73)
        recs1 = compute({"free_chlorine": 2.0, "ph": 7.4}, 20_000,
                        visible_algae="light")
        a1 = _by_chemical(_by_category(recs1, "algae_remediation"), "hypochlorite")[0]
        a2 = _by_chemical(_by_category(recs2, "algae_remediation"), "hypochlorite")[0]
        assert abs(a2["quantity"] * 2 - a1["quantity"]) < 0.05, \
            f"expected inverse scaling: {a1['quantity']} vs {a2['quantity']}"


class TestAlgaeExemptFromSixCap:
    """The 6-item cap does not apply to the algae entries — they always
    ship even when the routine list is already full."""

    def test_algae_appended_over_six_item_cap(self):
        recs = compute(
            {
                "free_chlorine": 0.5, "ph": 8.2, "total_alkalinity": 60,
                "calcium_hardness": 100, "cyanuric_acid": 10, "salt": 2000,
            },
            _GALLONS, visible_algae="heavy",
        )
        # Algae entries must still be present.
        assert len(_by_category(recs, "algae_remediation")) == 2
        # And the ordering note (pH = 8.2 > 7.6).
        assert len(_by_category(recs, "ordering_note")) == 1


class TestNoRegressionOnBaseline:
    """Baseline dosing must still work when `visible_algae` is unset or
    None — Phase 56.10 must not change existing recommendations."""

    def test_default_kwarg_matches_none(self):
        a = compute({"free_chlorine": 0.5}, _GALLONS)
        b = compute({"free_chlorine": 0.5}, _GALLONS, visible_algae="none")
        assert a == b

    def test_no_algae_entries_when_kwarg_unset(self):
        recs = compute({"free_chlorine": 0.5, "ph": 8.2}, _GALLONS)
        assert _by_category(recs, "algae_remediation") == []
        assert _by_category(recs, "ordering_note") == []
