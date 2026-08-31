"""Phase F5 · Feb-2026 — alias priority contract.

Documents (and locks) the resolution priority between direct
aliases and role-specific fallbacks.  Keeps the extractor
predictable when a form ships BOTH a broad ``name`` field AND
per-part ``first_name`` / ``last_name`` fields.
"""
from __future__ import annotations

from services import lead_extraction as le


def _fields(v):
    return le.extract_contact_fields(v)


def test_name_priority_direct_beats_first_last():
    r = _fields({"name": "Direct", "first_name": "Composed", "last_name": "Also"})
    assert r["name"] == "Direct"


def test_name_priority_full_name_beats_first_last():
    r = _fields({"full_name": "Direct", "first_name": "Composed", "last_name": "Also"})
    assert r["name"] == "Direct"


def test_phone_priority_first_alias_wins():
    """Multiple phone aliases on the same doc — the FIRST match in
    the priority list wins.  ``phone`` beats ``cell_phone`` when
    both are present because ``phone`` is more likely the intended
    field per the alias-list order."""
    r = _fields({"phone": "111", "cell_phone": "222"})
    assert r["phone"] == "111"


def test_phone_priority_fallback_when_direct_empty():
    """If the leading alias is present but empty, the extractor
    keeps scanning."""
    r = _fields({"phone": "", "cell_phone": "222"})
    assert r["phone"] == "222"


def test_message_priority_message_over_description():
    r = _fields({"message": "M", "description": "D"})
    assert r["message"] == "M"


def test_address_priority_direct_over_street():
    r = _fields({"address": "A", "street": "S"})
    assert r["address"] == "A"


def test_service_interest_priority_first_match_wins():
    r = _fields({"service_interest": "pool", "service": "landscape"})
    assert r["service_interest"] == "pool"
