"""Phase D1 · Feb 2026 — derivation regression across all 23 industries.

One case per canonical slug. Every case uses a plausible
``service_type`` string a real dispatcher might enter.

Compound-keyword regression cases are the critical bit:
  * "Window Cleaning" → ``window_cleaning`` (NOT ``cleaning``)
  * "Carpet Steam Cleaning" → ``carpet_cleaning`` (NOT ``cleaning``)
  * "Pressure Washing" → ``pressure_washing`` (NOT ``cleaning``)
  * "Solar Panel Cleaning" → ``solar`` (existing Phase MI1 guarantee
    preserved)
  * "Pool Chemical Balance" → ``pool`` (existing guarantee preserved)
"""
from __future__ import annotations

import pytest

from routers.industry_checklists import (
    INDUSTRY_SLUGS, derive_industry_for_job,
)


# ─── One case per canonical slug ─────────────────────────────────────
CASES = {
    # Existing MI1 industries — MUST stay byte-identical.
    "pool":            "Weekly pool service",
    "landscaping":     "Landscape maintenance",
    "hvac":            "HVAC Tune-Up",
    "pest_control":    "Pest control quarterly",
    "cleaning":        "Deep house cleaning",
    "solar":           "Solar Panel Cleaning",
    "handyman":        "Handyman fence board fix",
    # Phase D1 new industries.
    "plumbing":        "Emergency Plumbing Repair",
    "electrical":      "Electrical panel upgrade",
    "roofing":         "Roof leak inspection",
    "painting":        "Interior painting job",
    "garage_door":     "Garage door spring replacement",
    "appliance_repair":"Appliance repair — washer",
    "locksmith":       "Locksmith rekey house",
    "chimney_sweep":   "Chimney sweep annual",
    "gutter":          "Gutter clean-out",
    "window_cleaning": "Window Cleaning residential",
    "carpet_cleaning": "Carpet Steam Cleaning",
    "pressure_washing":"Pressure Washing driveway",
    "tree_service":    "Tree trimming service",
    "snow_removal":    "Snow removal contract",
    "fencing":         "Wood fence install",
    "irrigation":      "Sprinkler zone repair",
}


@pytest.mark.parametrize("expected,service_type", list(CASES.items()))
def test_derive_per_industry(expected: str, service_type: str):
    got = derive_industry_for_job({"service_type": service_type}, None)
    assert got == expected, (
        f"service_type={service_type!r} expected={expected!r} got={got!r}"
    )


# ─── Guard: every canonical slug MUST have a positive test ──────────
def test_all_canonical_slugs_have_a_case():
    """A future addition to :data:`INDUSTRY_SLUGS` without a
    corresponding positive test would silently ship an unproven
    industry. Fail fast in that case."""
    covered = set(CASES.keys())
    canonical = set(INDUSTRY_SLUGS)
    missing = canonical - covered
    assert not missing, (
        f"CASES is missing positive derivation coverage for: "
        f"{sorted(missing)}"
    )
    extras = covered - canonical
    assert not extras, (
        f"CASES has cases for non-canonical slugs (drift?): "
        f"{sorted(extras)}"
    )


# ─── Compound-keyword regression cases ──────────────────────────────
COMPOUND_CASES = [
    ("Window Cleaning",             "window_cleaning"),
    ("Window cleaning service",     "window_cleaning"),
    ("Carpet Steam Cleaning",       "carpet_cleaning"),
    ("Carpet & upholstery",         "carpet_cleaning"),
    ("Pressure Washing driveway",   "pressure_washing"),
    ("Power wash siding",           "pressure_washing"),
    ("Solar Panel Cleaning",        "solar"),
    ("Pool Chemical Balance",       "pool"),
    ("Garage Door Opener Install",  "garage_door"),
    ("Chimney sweep annual",        "chimney_sweep"),
    ("Tree removal",                "tree_service"),
    ("Snow plow visit",             "snow_removal"),
]


@pytest.mark.parametrize("service_type,expected", COMPOUND_CASES)
def test_compound_keywords_win_over_component_keywords(
    service_type: str, expected: str,
):
    got = derive_industry_for_job({"service_type": service_type}, None)
    assert got == expected


# ─── Existing MI1 guarantees preserved ──────────────────────────────
def test_explicit_industry_override_still_wins():
    assert derive_industry_for_job(
        {"industry": "hvac", "service_type": "Window Cleaning"}, None,
    ) == "hvac"


def test_tenant_primary_industry_backfill_still_works():
    assert derive_industry_for_job({}, {"industries": ["plumbing"]}) == "plumbing"
    assert derive_industry_for_job({}, {"industry": "pools"}) == "pool"
