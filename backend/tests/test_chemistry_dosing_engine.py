"""Sprint 3b · Feb-2026 — Chemistry dosing engine unit tests.

Covers the sandboxed evaluator, AZ-default regression against
``services.pool_dosing`` output, and rejection of unsafe / timing-out
formulas.
"""
from __future__ import annotations

import time

import pytest

from services.chemistry_dosing_engine import (
    AZ_DEFAULT_FORMULAS,
    FORMULA_KEYS,
    dry_run_formula,
    evaluate,
)


# ── AZ regression — engine output MUST match pool_dosing.compute() ─
def _target_row(chem: str):
    from services.chemistry_tenant_targets import AZ_DEFAULT_TARGETS
    row = AZ_DEFAULT_TARGETS[chem]
    return {"min": row["min"], "max": row["max"], "ideal": row["ideal"]}


def test_az_default_ph_up_matches_pool_dosing():
    # ph=7.0, ideal 7.4, 10000 gal → 0.8 lbs (hardcoded pool_dosing).
    res = evaluate("ph_up", current=7.0, target_range=_target_row("ph"),
                    volume_gallons=10_000)
    assert res["evaluation_ok"]
    assert res["source"] == "az_default"
    assert res["recommended_dose_oz"] == 0.8


def test_az_default_free_chlorine_matches_pool_dosing():
    # fc=1.0, low-season ideal 2.0, 10000 gal → 0.04 gal.
    res = evaluate("free_chlorine", current=1.0,
                    target_range=_target_row("free_chlorine"),
                    volume_gallons=10_000)
    assert res["evaluation_ok"]
    assert res["recommended_dose_oz"] == 0.04


def test_az_default_salt_up_matches_pool_dosing():
    # salt=2400, ideal 3200, 10000 gal → 66.7 lbs.
    res = evaluate("salt_up", current=2400,
                    target_range=_target_row("salt"),
                    volume_gallons=10_000)
    assert res["evaluation_ok"]
    assert res["recommended_dose_oz"] == 66.7


def test_az_default_alkalinity_up_matches_pool_dosing():
    res = evaluate("alkalinity_up", current=60,
                    target_range=_target_row("alkalinity"),
                    volume_gallons=10_000)
    assert res["evaluation_ok"]
    assert res["recommended_dose_oz"] == 5.2


def test_az_default_cyanuric_acid_up_matches_pool_dosing():
    res = evaluate("cyanuric_acid_up", current=20,
                    target_range=_target_row("cyanuric_acid"),
                    volume_gallons=10_000)
    assert res["evaluation_ok"]
    assert res["recommended_dose_oz"] == 26.0


def test_az_default_calcium_hardness_up_matches_pool_dosing():
    res = evaluate("calcium_hardness_up", current=150,
                    target_range=_target_row("calcium_hardness"),
                    volume_gallons=10_000)
    assert res["evaluation_ok"]
    assert res["recommended_dose_oz"] == 100.0


# ── Custom tenant formula — happy path ─────────────────────────────
def test_custom_formula_evaluates_and_returns_tenant_source():
    formula = "max(0, (avg_target - current) * volume_gallons * 0.00013)"
    res = evaluate("free_chlorine", current=1.0,
                    target_range={"min": 1.0, "max": 3.0, "ideal": 2.0},
                    volume_gallons=10_000, tenant_formula=formula)
    assert res["evaluation_ok"]
    assert res["source"] == "tenant"
    # (2 - 1) * 10000 * 0.00013 = 1.3
    assert abs(res["recommended_dose_oz"] - 1.3) < 1e-9
    assert res["formula_used"] == formula


def test_custom_formula_clips_negative_with_max():
    # current above target → delta negative → max(0, ...) = 0.
    formula = "max(0, (avg_target - current) * volume_gallons * 0.00013)"
    res = evaluate("free_chlorine", current=5.0,
                    target_range={"min": 1.0, "max": 3.0, "ideal": 2.0},
                    volume_gallons=10_000, tenant_formula=formula)
    assert res["evaluation_ok"]
    assert res["source"] == "tenant"
    assert res["recommended_dose_oz"] == 0.0


# ── Sandbox guards — bad / unsafe / timing out formulas ────────────
def test_bad_syntax_falls_back_to_az_default():
    res = evaluate("free_chlorine", current=1.0,
                    target_range={"min": 1.0, "max": 3.0, "ideal": 2.0},
                    volume_gallons=10_000,
                    tenant_formula="(2 + )")
    assert res["evaluation_ok"] is True
    assert res["source"] == "az_default"
    assert "tenant_fallback" in (res.get("error") or "")
    # AZ default: 0.04
    assert res["recommended_dose_oz"] == 0.04


def test_import_attempt_is_blocked_by_preflight():
    res = evaluate("free_chlorine", current=1.0,
                    target_range={"min": 1.0, "max": 3.0, "ideal": 2.0},
                    volume_gallons=10_000,
                    tenant_formula="__import__('os').system('ls')")
    assert res["evaluation_ok"] is True  # falls back
    assert res["source"] == "az_default"
    err = (res.get("error") or "").lower()
    # Either preflight ("forbidden substring") or SimpleEval
    # (unsafe_function / unsafe_construct) blocks it.
    assert any(m in err for m in ("forbidden", "unsafe"))


def test_attribute_access_is_blocked():
    res = evaluate("free_chlorine", current=1.0,
                    target_range={"min": 1.0, "max": 3.0, "ideal": 2.0},
                    volume_gallons=10_000,
                    tenant_formula="current.real")
    assert res["evaluation_ok"] is True
    assert res["source"] == "az_default"


def test_lambda_is_blocked_by_preflight():
    res = evaluate("free_chlorine", current=1.0,
                    target_range={"min": 1.0, "max": 3.0, "ideal": 2.0},
                    volume_gallons=10_000,
                    tenant_formula="(lambda: 42)()")
    assert res["evaluation_ok"] is True
    assert res["source"] == "az_default"
    err = (res.get("error") or "").lower()
    assert "forbidden" in err or "unsafe" in err


def test_pathological_power_is_capped():
    # ``x ** y`` with y > 100 raises NumberTooHigh under simpleeval
    # (see MAX_POWER=100 at module load).
    res = evaluate("free_chlorine", current=1.0,
                    target_range={"min": 1.0, "max": 3.0, "ideal": 2.0},
                    volume_gallons=10_000,
                    tenant_formula="2 ** 2 ** 2 ** 2 ** 2")
    assert res["evaluation_ok"] is True
    assert res["source"] == "az_default"
    err = (res.get("error") or "").lower()
    # Either "number_too_high" from simpleeval, or timeout — both
    # are acceptable fail-closed outcomes.
    assert any(m in err for m in ("number_too_high", "timeout"))


def test_dry_run_formula_accepts_valid():
    ok = dry_run_formula("max(0, (avg_target - current) * volume_gallons / 256000)")
    assert ok["ok"] is True
    assert isinstance(ok["sample_result"], float)


def test_dry_run_formula_rejects_bad_syntax():
    bad = dry_run_formula("(2 + )")
    assert bad["ok"] is False
    assert "bad_syntax" in (bad["error"] or "")


def test_dry_run_formula_rejects_unknown_name():
    bad = dry_run_formula("unknown_variable * 2")
    assert bad["ok"] is False
    assert "unknown_name" in (bad["error"] or "")


def test_dry_run_formula_rejects_forbidden_substring():
    bad = dry_run_formula("__import__('os')")
    assert bad["ok"] is False
    assert "forbidden" in (bad["error"] or "")


def test_dry_run_formula_rejects_too_long():
    long_formula = "1 + " * 60 + "1"  # 240+ chars
    bad = dry_run_formula(long_formula)
    assert bad["ok"] is False
    assert "max length" in (bad["error"] or "").lower()


def test_unknown_chemical_returns_error():
    res = evaluate("plutonium", current=1.0,
                    target_range={"min": 1.0, "max": 3.0, "ideal": 2.0},
                    volume_gallons=10_000)
    assert res["evaluation_ok"] is False
    assert "unknown_chemical" in (res.get("error") or "")


def test_all_formula_keys_have_az_defaults():
    for k in FORMULA_KEYS:
        assert k in AZ_DEFAULT_FORMULAS
        assert AZ_DEFAULT_FORMULAS[k].strip() != ""


# ── Full compute() regression via pool_dosing ──────────────────────
def test_pool_dosing_compute_is_unchanged_without_tenant_overrides():
    """AZ-default tenants (no tenant_targets / tenant_formulas) MUST
    produce byte-identical dose recommendations to the pre-Sprint-3b
    codepath. Regression guard for the callsite refactor."""
    from datetime import date
    from services.pool_dosing import compute

    readings = {
        "free_chlorine": 1.0, "ph": 7.0, "total_alkalinity": 60,
        "cyanuric_acid": 20, "calcium_hardness": 150, "salt": 2400,
    }
    sd = date(2026, 1, 15)  # low season
    without = compute(readings, 10_000, service_date=sd)
    with_empty = compute(readings, 10_000, service_date=sd,
                          tenant_targets={}, tenant_formulas={})
    assert without == with_empty


def test_pool_dosing_compute_uses_tenant_formula_when_provided():
    """When the tenant supplies a custom formula, compute() MUST
    emit the tenant-authored dose instead of the AZ default."""
    from datetime import date
    from services.pool_dosing import compute

    readings = {"ph": 7.0}  # only ph_up will fire
    formulas = {"ph_up": "round((avg_target - current) * volume_gallons * 0.0001, 1)"}
    # avg_target=7.4, current=7.0, volume=10000 → 0.4 * 10000 * 0.0001 = 0.4
    out = compute(readings, 10_000, service_date=date(2026, 1, 15),
                    tenant_targets={}, tenant_formulas=formulas)
    ph_recs = [r for r in out if r["reading_key"] == "ph"]
    assert len(ph_recs) == 1
    assert ph_recs[0]["quantity"] == 0.4


def test_pool_dosing_compute_falls_back_when_tenant_formula_is_bad():
    """A bad tenant formula MUST NOT poison the compute() output —
    the AZ default takes over silently (with an internal WARN log)."""
    from datetime import date
    from services.pool_dosing import compute

    readings = {"ph": 7.0}
    out = compute(readings, 10_000, service_date=date(2026, 1, 15),
                    tenant_targets={},
                    tenant_formulas={"ph_up": "(2 + )"})
    ph_recs = [r for r in out if r["reading_key"] == "ph"]
    assert len(ph_recs) == 1
    # AZ default expects 0.8 lbs for these inputs.
    assert ph_recs[0]["quantity"] == 0.8
