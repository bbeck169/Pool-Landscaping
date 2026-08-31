"""Phase F8 · Feb-2026 — Service-notes classifier vocab widen.

Direct unit tests on ``routers/customers.py::_classify_service_type``
and ``_resolve_service_note`` covering the widened keyword vocab.
Bypasses HTTP so it runs in <1s and doesn't share the K2/F7 HTTP
timeout flakiness.
"""
from __future__ import annotations

import pytest

from routers.customers import (
    _classify_service_type,
    _resolve_service_note,
    _POOL_KEYWORDS,
    _LANDSCAPE_KEYWORDS,
)


# ═══ _classify_service_type — pure classifier tests ═══════════════════

@pytest.mark.parametrize("service_type,expected", [
    # Pool group — new vocab.
    ("Pool Cleaning",       "pool"),
    ("Weekly Pool",         "pool"),
    ("Chemical Balance",    "pool"),   # NEW — was "other" pre-widen
    ("Filter Clean",        "pool"),   # NEW
    ("Shock Treatment",     "pool"),   # NEW
    ("Backwash",            "pool"),   # NEW
    ("Algae Bloom Service", "pool"),   # NEW
    # Landscape group — new vocab.
    ("Landscaping",         "landscape"),
    ("Landscape Design",    "landscape"),
    ("Lawn Mow",            "landscape"),   # NEW
    ("Yard Cleanup",        "landscape"),   # NEW
    ("Tree Removal",        "landscape"),   # NEW
    ("Hedge Trimming",      "landscape"),   # NEW · matches both "hedge" AND "trim"
    ("Irrigation Repair",   "landscape"),   # NEW
    # Neither group.
    ("Inspection",          None),
    ("Repair",              None),
    ("Installation",        None),
    ("",                    None),
    (None,                  None),
    ("   ",                 None),
])
def test_classify_service_type_widened_vocab(service_type, expected):
    assert _classify_service_type(service_type) == expected


def test_landscape_wins_when_both_groups_would_match():
    """Determinism guardrail: landscape keywords are checked first
    (see module comment). Any dual-match resolves to landscape."""
    # "Yard Cleanup" — "yard" (landscape) + "clean" (pool) → landscape.
    # This is the semantic anchor case — "Yard Cleanup" MUST classify
    # as landscape or techs will see the wrong pill on landscape jobs.
    assert _classify_service_type("Yard Cleanup") == "landscape"
    # "Landscape Cleanup" — "landscap" + "clean" → landscape.
    assert _classify_service_type("Landscape Cleanup") == "landscape"
    # Contrived — "Clean the yard pool" hits landscape first.
    assert _classify_service_type("Clean the yard pool") == "landscape"


# ═══ _resolve_service_note — end-to-end with the widened classifier ══

def _cust(pool=None, landscape=None):
    sn = {}
    if pool is not None:
        sn["pool"] = pool
    if landscape is not None:
        sn["landscape"] = landscape
    return {"service_notes": sn} if sn else {}


def test_resolve_pool_note_via_widened_vocab():
    """'Filter Clean' → resolves to the pool note (F8 primary win)."""
    cust = _cust(pool="pH slightly high, use less shock",
                  landscape="Trim hedges around the pool cage")
    assert (_resolve_service_note(cust, "Filter Clean")
            == "pH slightly high, use less shock")


def test_resolve_landscape_note_via_widened_vocab():
    """'Hedge Trimming' → resolves to the landscape note."""
    cust = _cust(pool="pool-p", landscape="landscape-l")
    assert _resolve_service_note(cust, "Hedge Trimming") == "landscape-l"


def test_resolve_none_when_service_type_matches_but_note_absent():
    """'Filter Clean' classifies to pool, but customer has no pool
    note → return None (do NOT accidentally leak the landscape one)."""
    cust = _cust(landscape="landscape-l")
    assert _resolve_service_note(cust, "Filter Clean") is None


def test_resolve_none_for_out_of_group_service_type():
    """'Repair' matches neither group → None (specialty fallback also
    None when user is omitted)."""
    cust = _cust(pool="pool-p", landscape="landscape-l")
    assert _resolve_service_note(cust, "Repair") is None


def test_specialty_fallback_still_works():
    """Legacy fallback preserved — 'Repair' + tech.specialties=['pool']
    → returns pool note."""
    cust = _cust(pool="pool-p")
    assert (_resolve_service_note(cust, "Repair", user={"specialties": ["pool"]})
            == "pool-p")


def test_no_service_notes_field_returns_none():
    """Customer with no service_notes at all → None (no crash)."""
    assert _resolve_service_note({}, "Weekly Pool") is None


def test_keyword_lists_are_the_documented_vocab():
    """Guardrail: the exported vocab lists match the widened set from
    the user brief.  Any drift is a spec violation — bump the
    docstring in customers.py::_POOL_KEYWORDS + this test in lockstep."""
    assert set(_POOL_KEYWORDS) == {
        "pool", "chemical", "filter", "clean", "shock", "backwash", "algae",
    }
    assert set(_LANDSCAPE_KEYWORDS) == {
        "landscap", "lawn", "yard", "tree", "trim", "mow", "hedge",
        "irrigation",
    }
