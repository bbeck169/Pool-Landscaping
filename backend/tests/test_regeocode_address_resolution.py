"""Feb-2026 · Re-geocode button — address resolution fallback chain.

Reported bug: Rochelle Vanderpool's customer detail page displays
the address correctly but clicking the "Re-geocode" button toasts
"No address on file — add a service address first." Root cause:
the geocode path only read ``service_address`` + the structured
legacy fields, missing customers whose only populated field is
``address`` (the field the display renderer uses).

This test locks the new shared ``resolve_customer_address`` helper
that both call sites (nightly + manual /geocode endpoint) now
consume.
"""
from __future__ import annotations

import pytest

from services.google_maps.geocoding import resolve_customer_address


# ─── Fallback chain — priority order ────────────────────────────

def test_resolves_from_service_address_when_present():
    """Canonical ``service_address`` wins over every other field."""
    doc = {
        "service_address": "1 Canon Way, Peoria, AZ 85383",
        "address":         "2 Loser Ave",  # lower precedence
    }
    assert (resolve_customer_address(doc)
            == "1 Canon Way, Peoria, AZ 85383")


def test_resolves_from_address_when_service_address_missing():
    """This is the reported-bug repro: display renderer reads
    ``address``, so re-geocode MUST fall back to the same field."""
    doc = {"address": "5542 W Big Oak St, Phoenix, AZ 85083"}
    assert (resolve_customer_address(doc)
            == "5542 W Big Oak St, Phoenix, AZ 85083")


def test_resolves_from_street_address_alias():
    doc = {"street_address": "12 Alt Rd, Peoria, AZ"}
    assert resolve_customer_address(doc) == "12 Alt Rd, Peoria, AZ"


def test_resolves_from_mailing_address_last_resort():
    doc = {"mailing_address": "PO Box 999, Peoria, AZ 85345"}
    assert resolve_customer_address(doc) == "PO Box 999, Peoria, AZ 85345"


def test_resolves_composite_from_service_prefixed_fields():
    doc = {
        "service_street": "1 Main St",
        "service_city":   "Peoria",
        "service_state":  "AZ",
        "service_zip":    "85383",
    }
    assert (resolve_customer_address(doc)
            == "1 Main St Peoria AZ 85383")


def test_resolves_composite_from_bare_legacy_fields():
    doc = {"street": "42 Elm St", "city": "Peoria",
             "state": "AZ", "zip": "85383"}
    assert resolve_customer_address(doc) == "42 Elm St Peoria AZ 85383"


def test_service_address_dict_shape_flattens():
    """Legacy dict shape must flatten via ``_flatten_addr`` semantics
    — locked by the P37b tolerant read."""
    doc = {"service_address": {
        "street": "1 Main St", "city": "Peoria",
        "state": "AZ", "postal_code": "85383",
    }}
    assert resolve_customer_address(doc) == "1 Main St Peoria AZ 85383"


# ─── Empty branches ─────────────────────────────────────────────

def test_returns_empty_on_no_customer():
    assert resolve_customer_address(None) == ""
    assert resolve_customer_address({}) == ""


@pytest.mark.parametrize("empty_shape", [
    {"service_address": "   "},
    {"address": ""},
    {"street_address": None},
    {"mailing_address": {}},
])
def test_whitespace_or_null_fields_do_not_short_circuit(empty_shape):
    """Whitespace-only / null shapes fall through so lower-priority
    fields keep a chance to match — critical for the ``address``
    fallback (customer_id 8910bfde… had empty ``service_address``
    but a populated ``address``)."""
    empty_shape["address"] = "9 Real St, Peoria AZ"
    assert resolve_customer_address(empty_shape) == "9 Real St, Peoria AZ"


def test_returns_empty_when_nothing_populated():
    """The one genuine ``no_address`` signal — every field is empty."""
    doc = {
        "service_address": "", "address": None, "street_address": "",
        "mailing_address": None, "service_street": "", "street": None,
        "service_city": "", "city": None,
    }
    assert resolve_customer_address(doc) == ""


# ─── Integration — manual-geocode endpoint no_address branch ────

def test_manual_geocode_endpoint_uses_shared_helper():
    """Guardrail — the diagnostic branch in
    ``routers/customers.py::customer_manual_geocode`` imports and
    uses ``resolve_customer_address``. A regression that copy-
    pastes the old inline fallback back into the endpoint is
    caught here.
    """
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1]
             / "routers" / "customers.py").read_text()
    # The endpoint MUST import the shared helper.
    assert "resolve_customer_address" in src, (
        "customer_manual_geocode should call resolve_customer_address"
    )
    # And it MUST NOT resurrect the old inline ``_flatten_addr`` +
    # bare ``service_address`` + structured-composite chain that
    # missed ``address`` entirely.
    _bad = "_flatten_addr(doc.get(\"service_address\")) or \" \".join"
    assert _bad not in src, "old inline fallback chain must not be re-added"
