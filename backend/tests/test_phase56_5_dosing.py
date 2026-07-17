"""Phase 56.5 — Seasonal chlorine targets + tabs-preferred dosing tests."""
from datetime import date

import pytest

from services.pool_dosing import compute, resolve_chlorine_target


@pytest.mark.parametrize("m", [3, 4, 5, 6, 7, 8, 9])
def test_high_season_target_and_range(m):
    tgt, (lo, hi, ideal), season = resolve_chlorine_target(date(2026, m, 15))
    assert season == "high"
    assert tgt == 5.0
    assert ideal == 5.0
    assert lo == 4.5 and hi == 5.5


@pytest.mark.parametrize("m", [1, 2, 10, 11, 12])
def test_low_season_target_and_range(m):
    tgt, (lo, hi, ideal), season = resolve_chlorine_target(date(2026, m, 15))
    assert season == "low"
    assert (lo, hi) == (1.0, 3.0)
    assert 1.9 <= ideal <= 2.1


def _fc_rec(recs):
    return next((r for r in recs if r.get("reading_key") == "free_chlorine"), None)


def test_high_season_prefers_tabs_when_slightly_low():
    # High-season, fc slightly low (below the 4.5–5.5 band) — tabs preferred.
    recs = compute(
        {"free_chlorine": 4.0}, pool_gallons=20_000,
        service_date=date(2026, 6, 15),
    )
    rec = _fc_rec(recs)
    assert rec is not None
    assert rec["season"] == "high"
    assert rec["preferred_form"] == "tabs"
    assert rec["unit"] == "tabs"
    assert isinstance(rec["quantity"], (int, float)) and rec["quantity"] >= 1
    assert rec["target_ppm"] == 5.0


def test_rapid_boost_still_prefers_tabs_after_phase56_9():
    # Phase 56.9 — tabs are the ALWAYS-default now. Rapid boost no
    # longer demotes to liquid; the operator must explicitly opt in via
    # `chemical_preferences.prefer_liquid_chlorine` (see next test) or
    # trigger the Phase 56.10 algae-remediation path.
    recs = compute(
        {"free_chlorine": 2.0}, pool_gallons=20_000,
        service_date=date(2026, 7, 1),
    )
    rec = _fc_rec(recs)
    assert rec is not None
    assert rec["preferred_form"] == "tabs"
    assert rec["unit"] == "tabs"


def test_no_tabs_customer_flag_forces_liquid():
    recs = compute(
        {"free_chlorine": 4.0}, pool_gallons=20_000,
        service_date=date(2026, 6, 15),
        customer={"chemical_preferences": {"no_tabs": True}},
    )
    rec = _fc_rec(recs)
    assert rec["preferred_form"] == "liquid"
    assert rec["unit"] == "gal"


def test_prefer_liquid_chlorine_override_forces_liquid():
    # Phase 56.9 — explicit operator opt-in on the customer profile.
    recs = compute(
        {"free_chlorine": 4.0}, pool_gallons=20_000,
        service_date=date(2026, 6, 15),
        customer={"chemical_preferences": {"prefer_liquid_chlorine": True}},
    )
    rec = _fc_rec(recs)
    assert rec["preferred_form"] == "liquid"
    assert rec["unit"] == "gal"
    assert "operator override" in rec["preferred_form_reason"].lower()


def test_tab_rotation_no_longer_forces_liquid_after_phase56_9():
    # Phase 56.9 — rotation-to-liquid guard REMOVED. Tabs stay the
    # default even if used in the last N visits; operator can override
    # per-visit via `prefer_liquid_chlorine`.
    recent = [
        {"chemicals_added": [{"chemical": "Chlorine tabs (3\" trichlor)"}]},
        {"chemicals_added": [{"chemical": "Chlorine tabs (3\" trichlor)"}]},
        {"chemicals_added": [{"chemical": "Chlorine tabs (3\" trichlor)"}]},
    ]
    recs = compute(
        {"free_chlorine": 4.0}, pool_gallons=20_000,
        service_date=date(2026, 6, 15),
        recent_service_reports=recent,
    )
    rec = _fc_rec(recs)
    assert rec["preferred_form"] == "tabs"


def test_low_season_target_prefers_tabs_by_default():
    recs = compute(
        {"free_chlorine": 0.5}, pool_gallons=20_000,
        service_date=date(2026, 12, 15),
    )
    rec = _fc_rec(recs)
    assert rec["season"] == "low"
    # In low season the rapid-boost guard does NOT trip — tabs preferred.
    assert rec["preferred_form"] == "tabs"
    assert rec["unit"] == "tabs"
    # Range shipped to the client is 1–3.
    assert rec["target_range"] == [1.0, 3.0]


def test_muriatic_acid_in_gallons():
    # pH high in low season — muriatic acid should ship in gal, 2dp.
    recs = compute(
        {"ph": 8.0}, pool_gallons=20_000,
        service_date=date(2026, 12, 15),
    )
    ph_rec = next(r for r in recs if r["reading_key"] == "ph")
    assert ph_rec["unit"] == "gal"
    assert isinstance(ph_rec["quantity"], (int, float))
    # 20k gallons + pH 8.0 vs 7.4 → ~24 fl-oz → ~0.19 gal.
    assert 0.1 <= ph_rec["quantity"] <= 0.5


def test_liquid_chlorine_units_are_gallons():
    # Phase 56.9 — tabs is the default even at rapid-boost gaps. Force
    # liquid via the operator override so we can assert gal units on
    # the liquid path.
    recs = compute(
        {"free_chlorine": 2.0}, pool_gallons=20_000,
        service_date=date(2026, 7, 1),
        customer={"chemical_preferences": {"prefer_liquid_chlorine": True}},
    )
    rec = _fc_rec(recs)
    assert rec["preferred_form"] == "liquid"
    assert rec["unit"] == "gal"
    # 20k gallons, 3 ppm delta, 10 fl-oz per +2 ppm per 10k gal ⇒ ~30 oz
    # → ~0.23 gal. Loose bounds to survive rounding.
    assert 0.1 <= rec["quantity"] <= 0.5
