"""Feb-2026 · Public "Get a Free Quote" — street-address + service_interest
explicit-field passthrough for ``lead_extraction``.

The frontend now emits both ``address`` (modern) and
``service_address`` (legacy) alongside ``service_interest`` in the
public-form POST body. Verify that structured field values ALWAYS
win over any downstream heuristic — no NLP mangling for values that
came from a labeled input.
"""
from __future__ import annotations

import pytest

from services.lead_extraction import (
    extract_contact_fields,
    lead_row_from_form_values,
)


# ─── Acceptance 1 — structured ``address`` + ``service_interest`` mapping ─

def test_extractor_maps_address_and_service_interest_verbatim():
    """Given the exact dispatch payload — ``{address, service_interest}`` —
    the extracted contact record must carry those values verbatim on
    the canonical ``address`` and ``service_interest`` fields. No
    trimming beyond the whitespace guard, no rewriting."""
    payload = {
        "name":             "Jane Doe",
        "email":            "jane@example.com",
        "address":          "123 Main St, Peoria AZ",
        "service_interest": "Pool cleaning",
    }
    out = extract_contact_fields(payload)
    assert out["address"] == "123 Main St, Peoria AZ"
    assert out["service_interest"] == "Pool cleaning"


def test_extractor_lead_row_persists_address_and_service_interest():
    """``lead_row_from_form_values`` (the public-form insert helper)
    must materialize both fields on the insert doc. The legacy
    denormalized ``service_address`` sibling stays populated too so
    downstream reports that key on either field keep working."""
    payload = {
        "name":             "Jane Doe",
        "email":            "jane@example.com",
        "address":          "123 Main St, Peoria AZ",
        "service_interest": "Pool cleaning",
    }
    row = lead_row_from_form_values(tid="t1", vals=payload,
                                       source_label="Web Form")
    assert row["address"] == "123 Main St, Peoria AZ"
    assert row["service_address"] == "123 Main St, Peoria AZ"
    assert row["service_interest"] == "Pool cleaning"
    assert row["name"] == "Jane Doe"


# ─── Acceptance 2 — legacy ``service_address`` alias still resolves ─────

def test_extractor_service_address_legacy_alias_resolves_to_address():
    """The pre-Feb-2026 frontend emitted ``service_address``. That
    alias must still land on the canonical ``address`` field so
    downstream consumers only ever need to read one key."""
    payload = {
        "name":             "Jane",
        "service_address":  "456 Legacy Blvd, Peoria AZ",
        "service_interest": "Landscape",
    }
    out = extract_contact_fields(payload)
    assert out["address"] == "456 Legacy Blvd, Peoria AZ"
    assert out["service_interest"] == "Landscape"


# ─── Acceptance 3 — explicit field wins over free-text heuristics ───────

def test_explicit_address_wins_over_freeform_notes_heuristic():
    """A ``notes`` / ``message`` field may contain an address-like
    string ("I live at 999 Elm St"). The structured ``address``
    input MUST win — the extractor never runs a heuristic over
    free text that overwrites a labeled field.

    This is the "structured form values ALWAYS win" acceptance rule.
    """
    payload = {
        "name":             "Jane Doe",
        "address":          "123 Main St, Peoria AZ",
        "notes":            "By the way, my old place was at "
                             "999 Elm St, Phoenix AZ — please don't "
                             "route there.",
        "service_interest": "Pool",
    }
    out = extract_contact_fields(payload)
    # Structured field wins — the notes-embedded address never
    # overrides the labeled one.
    assert out["address"] == "123 Main St, Peoria AZ"
    # The notes field is still preserved verbatim under ``message``.
    assert "999 Elm St" in (out["message"] or "")


def test_extractor_alias_priority_direct_over_your_address():
    """When BOTH ``address`` and a lower-precedence alias
    (``your_address``) are present, the earlier alias in the
    table wins — this locks the historical priority order the
    K53.1 alias fix established."""
    payload = {
        "name":         "Jane",
        "address":      "TOP-PRECEDENCE 123 Main St",
        "your_address": "LOW-PRECEDENCE 999 Elm St",
    }
    out = extract_contact_fields(payload)
    assert out["address"] == "TOP-PRECEDENCE 123 Main St"


# ─── Acceptance 4 — service_interest alias coverage ─────────────────────

@pytest.mark.parametrize("alias_key", [
    "service_interest", "requested_service", "service", "interest",
    "service_type",
])
def test_service_interest_alias_coverage(alias_key):
    """Every canonical alias for the interest field must resolve —
    the frontend hidden input emits ``service_interest`` but any
    tenant-authored form on the same intake helper should also
    work."""
    payload = {alias_key: "Pool + Landscape"}
    out = extract_contact_fields(payload)
    assert out["service_interest"] == "Pool + Landscape", (
        f"alias {alias_key!r} did not resolve"
    )


def test_empty_address_returns_none_not_placeholder():
    """Guards against the extractor emitting a whitespace-only or
    empty ``address`` — those values should be treated as missing
    so the downstream ``address`` column stays clean."""
    payload = {"name": "Jane", "address": "   "}
    out = extract_contact_fields(payload)
    assert out["address"] is None
