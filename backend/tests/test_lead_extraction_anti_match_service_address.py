"""Phase L2.5 · Feb-2026 — anti-match rule for label-resolution.

Locks the cross-contamination guard that keeps ``service_address``-
labelled fields from stomping into ``service_interest`` / ``notes``
(and vice versa) when the form ships BOTH kinds of fields.  The
existing precedence test — exact key match ALWAYS wins — is
re-asserted here so anyone extending :data:`_LABEL_ANTI_MATCH`
notices when they break it.

Guarantees enforced
-------------------
1. A form with a field labelled ``"Service Address"`` under an
   auto-generated id (``field_Service Address_5``) resolves ONLY
   to :canonical:`address` — never to :canonical:`service_interest`
   or :canonical:`notes` / :canonical:`message`.
2. Reverse guard: a field labelled ``"Description of Services
   Needed"`` under an auto-generated id resolves ONLY to
   :canonical:`notes` / :canonical:`service_interest` — never to
   :canonical:`address` / :canonical:`service_address`.
3. Full-blown mixed form (address + description + name + phone +
   email) hydrates every canonical without swapping any pair.
4. Anti-match table is table-driven — a new canonical → anti-labels
   row lands without touching :func:`_label_matches_canonical`.
5. Explicit key match ALWAYS wins (precedence regression guard).
"""
from __future__ import annotations

import inspect
from typing import Any, Dict, List

import pytest

from services.lead_extraction import (
    _LABEL_ANTI_MATCH,
    _label_matches_canonical,
    extract_contact_fields_with_schema,
    lead_row_from_form_values_with_schema,
)


# ─── (1) Table shape / extensibility guard ──────────────────────────
def test_anti_match_table_is_extensible_no_hardcoded_branches():
    """Anyone reading ``_LABEL_ANTI_MATCH`` should be able to add a
    new canonical → anti-labels row and have it just work.  Guard
    against a future refactor that hard-codes branches in
    ``_label_matches_canonical``."""
    src = inspect.getsource(_label_matches_canonical)
    # No canonical-name literals should appear in the resolver body.
    for banned in ("service_interest", "service_address",
                    '"address"', '"notes"'):
        assert banned not in src, (
            f"{_label_matches_canonical.__qualname__} references "
            f"{banned!r} directly — anti-match must stay table-driven."
        )
    # Every entry is a list-of-str.
    for canonical, anti_labels in _LABEL_ANTI_MATCH.items():
        assert isinstance(canonical, str)
        assert isinstance(anti_labels, list)
        for a in anti_labels:
            assert isinstance(a, str) and a == a.lower(), (
                f"_LABEL_ANTI_MATCH[{canonical!r}] token {a!r} must "
                "be lower-case (labels are normalized before compare)."
            )


# ─── (2) Direct label→canonical guard ───────────────────────────────
@pytest.mark.parametrize("label,canonical,expected", [
    # Service Address must map to `address` and NOTHING ELSE.
    ("Service Address",   "address",           True),
    ("Service Address",   "service_interest",  False),
    ("Service Address",   "notes",             False),
    ("Property Address",  "address",           True),
    ("Property Address",  "service_interest",  False),
    ("Property Address",  "notes",             False),
    # Service-description labels must map to notes ONLY.
    ("Description of Services Needed", "notes",            True),
    ("Description of Services Needed", "address",          False),
    # Legacy already-working case — no regression.
    ("Phone Address Book", "address", False),
    ("Phone Address Book", "phone",   False),
])
def test_label_matches_canonical_respects_anti_match(label, canonical, expected):
    assert _label_matches_canonical(label, canonical) is expected, (
        f"label={label!r} canonical={canonical!r} expected={expected}"
    )


# ─── (3) End-to-end extractor: mixed-form fixture ──────────────────
def _form_fixture() -> Dict[str, Any]:
    """A representative modern-widget form: every contact field has
    an auto-generated id but a human-readable label."""
    return {
        "fields": [
            {"id": "field_1",                     "label": "Full Name"},
            {"id": "field_2",                     "label": "Email"},
            {"id": "field_3",                     "label": "Phone"},
            {"id": "field_Service Address_5",     "label": "Service Address"},
            {"id": "field_9",                     "label": "Description of Services Needed"},
        ],
        "values": {
            "field_1":                 "Jane Q. Public",
            "field_2":                 "jane@example.com",
            "field_3":                 "555-0100",
            "field_Service Address_5": "42 Wallaby Way, Sydney",
            "field_9":                 "Weekly pool + spa; interested in Betta skimmer install.",
        },
    }


def test_end_to_end_extractor_hydrates_address_and_notes_without_swap():
    fx = _form_fixture()
    out = extract_contact_fields_with_schema(fx["values"], fx["fields"])
    assert out["name"] == "Jane Q. Public"
    assert out["email"] == "jane@example.com"
    assert out["phone"] == "555-0100"
    # The classic L2.5 anti-match: address wins the "Service Address" label.
    assert out["address"] == "42 Wallaby Way, Sydney"
    # ``message`` (aka notes canonical) resolves to the description
    # field — NOT to the service address.
    assert out["message"] == (
        "Weekly pool + spa; interested in Betta skimmer install."
    )
    # Reverse guard: address must not leak into notes.
    assert "42 Wallaby Way" not in (out["message"] or "")


def test_lead_row_from_form_values_with_schema_populates_both_slots():
    fx = _form_fixture()
    row = lead_row_from_form_values_with_schema(
        tid="t-anti-match", vals=fx["values"],
        source_label="AntiMatch Widget",
        schema_fields=fx["fields"],
    )
    assert row["address"] == "42 Wallaby Way, Sydney"
    assert row["service_address"] == "42 Wallaby Way, Sydney"
    assert row["notes"] == (
        "Weekly pool + spa; interested in Betta skimmer install."
    )
    # Critical anti-match invariant: the SERVICE ADDRESS value must
    # never leak into service_interest (that was the classic L2.5
    # bug — a "Service Address" label fuzzy-matched via the bare
    # "service" token in the service_interest synonym list).
    assert (row["service_interest"] or "") != "42 Wallaby Way, Sydney"
    assert "Wallaby Way" not in (row["service_interest"] or "")
    # Whole row still has the pre-L2 keys populated.
    assert row["name"] == "Jane Q. Public"
    assert row["email"] == "jane@example.com"


# ─── (4) Explicit-key precedence regression guard ──────────────────
def test_explicit_key_beats_label_match_even_with_anti_match():
    """When the value dict has a bare canonical key (``address``),
    the pre-L2 key path resolves it BEFORE label matching runs.
    Anti-match rules must never break this precedence."""
    fields = [
        # A label that would fuzzy-match address if key resolution
        # didn't already win.
        {"id": "field_7", "label": "Service Address"},
    ]
    values = {
        "address": "Direct key wins · 100 Main St",
        # ``field_7`` also has an address value — the anti-match
        # would let it through as an address candidate normally,
        # but the explicit key must still win.
        "field_7": "Label match losing · 200 Backup Ave",
    }
    out = extract_contact_fields_with_schema(values, fields)
    assert out["address"] == "Direct key wins · 100 Main St"


# ─── (5) Notes anti-match reverse guard ─────────────────────────────
def test_service_address_label_does_not_hijack_notes():
    """Direct assertion of the reverse guard: a form with ONLY a
    Service-Address field must not populate ``notes`` / ``message``
    with the address string."""
    fields = [{"id": "field_addr", "label": "Service Address"}]
    values = {"field_addr": "1234 Elm St, Springfield, IL"}
    out = extract_contact_fields_with_schema(values, fields)
    assert out["address"] == "1234 Elm St, Springfield, IL"
    assert out["message"] is None
    assert out["service_interest"] is None


def test_description_label_does_not_hijack_address():
    """Symmetric to the previous test: a form with ONLY a
    description-style field must not populate ``address`` with the
    description string."""
    fields = [{"id": "field_desc",
                "label": "Description of Services Needed"}]
    values = {"field_desc": "Water pressure is low; check filter."}
    out = extract_contact_fields_with_schema(values, fields)
    assert out["address"] is None
    assert out["message"] == "Water pressure is low; check filter."


# ─── (6) Anti-match table has the expected canonical rows ──────────
def test_service_interest_and_notes_and_address_all_have_anti_labels():
    for canonical in ("address", "notes", "service_interest"):
        assert canonical in _LABEL_ANTI_MATCH, (
            f"_LABEL_ANTI_MATCH missing canonical row {canonical!r}"
        )
        assert _LABEL_ANTI_MATCH[canonical], (
            f"_LABEL_ANTI_MATCH[{canonical!r}] is empty — Phase L2.5"
            " requires anti-labels on all three canonicals."
        )
    # Belt & braces: the classic address labels must all be present
    # in the ``service_interest`` anti-match list.
    for label_frag in ("service address", "property address",
                        "street address"):
        assert label_frag in _LABEL_ANTI_MATCH["service_interest"]
    # And the description labels are anti-matched from ``address``.
    for label_frag in ("service interest", "description of services needed"):
        assert label_frag in _LABEL_ANTI_MATCH["address"]
