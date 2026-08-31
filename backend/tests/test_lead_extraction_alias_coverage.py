"""Phase F5 · Feb-2026 — alias-coverage regression.

Locks in every expanded alias set from the audit.  If a future
refactor drops one of these aliases, this test fires.
"""
from __future__ import annotations

from services import lead_extraction as le


def _fields(vals):
    return le.extract_contact_fields(vals)


# ── Direct name aliases ────────────────────────────────────────
def test_direct_name_aliases_all_supported():
    assert _fields({"name": "Alice"})["name"] == "Alice"
    assert _fields({"full_name": "Bob"})["name"] == "Bob"
    assert _fields({"fullname": "Carol"})["name"] == "Carol"


# ── first + last composition ──────────────────────────────────
def test_first_plus_last_composes_when_no_direct_name():
    assert _fields({"first_name": "Alice", "last_name": "Baker"})["name"] == "Alice Baker"
    assert _fields({"fname": "Alice", "lname": "Baker"})["name"] == "Alice Baker"
    assert _fields({"given_name": "Alice", "surname": "Baker"})["name"] == "Alice Baker"
    assert _fields({"first_name": "Alice", "family_name": "Baker"})["name"] == "Alice Baker"


def test_direct_name_takes_priority_over_first_last():
    r = _fields({"name": "Explicit", "first_name": "Ignored", "last_name": "Also"})
    assert r["name"] == "Explicit"
    # But first_name and last_name still populate the denorm fields.
    assert r["first_name"] == "Ignored"
    assert r["last_name"] == "Also"


def test_only_first_or_only_last_still_composes():
    assert _fields({"first_name": "Alice"})["name"] == "Alice"
    assert _fields({"last_name": "Baker"})["name"] == "Baker"


def test_no_name_falls_through_to_none():
    assert _fields({"email": "a@b.com"})["name"] is None
    # And ``lead_row_from_form_values`` then applies the sentinel.
    row = le.lead_row_from_form_values(
        tid="t1", vals={"email": "a@b.com"}, source_label="Web Form")
    assert row["name"] == le.WEBSITE_VISITOR_FALLBACK


# ── phone aliases (the P1 driver) ─────────────────────────────
def test_all_phone_aliases_covered():
    for k in ("phone", "phone_number", "tel", "mobile",
              "cell_phone", "home_phone", "work_phone", "mobile_phone"):
        assert _fields({k: "555-1212"})["phone"] == "555-1212", k


# ── notes aliases (description was the missing one) ───────────
def test_all_notes_aliases_covered():
    for k in ("message", "notes", "details", "comments",
              "description", "description_of_service_needed", "service_needed"):
        assert _fields({k: "Need help"})["message"] == "Need help", k


# ── address parts ─────────────────────────────────────────────
def test_city_state_zip_company_all_extract():
    r = _fields({
        "city": "Peoria", "state": "AZ", "zip": "85383",
        "company_name": "Acme LLC",
    })
    assert r["city"] == "Peoria"
    assert r["state"] == "AZ"
    assert r["zip"] == "85383"
    assert r["company_name"] == "Acme LLC"


def test_zip_and_state_alias_synonyms():
    assert _fields({"zipcode": "85383"})["zip"] == "85383"
    assert _fields({"zip_code": "85383"})["zip"] == "85383"
    assert _fields({"postal_code": "85383"})["zip"] == "85383"
    assert _fields({"postcode": "85383"})["zip"] == "85383"
    assert _fields({"province": "ON"})["state"] == "ON"
    assert _fields({"region": "CA"})["state"] == "CA"
    assert _fields({"town": "Peoria"})["city"] == "Peoria"


def test_company_alias_synonyms():
    for k in ("company", "company_name", "business", "business_name", "organization"):
        assert _fields({k: "Acme"})["company_name"] == "Acme", k


# ── whitespace-only guard ─────────────────────────────────────
def test_whitespace_only_is_treated_as_empty():
    assert le.first_str({"name": "   "}, ["name"]) is None
    # And a whitespace-first alias falls through to the next.
    assert le.first_str({"name": "   ", "full_name": "Alice"},
                          ["name", "full_name"]) == "Alice"


def test_whitespace_only_first_name_does_not_compose_junk_name():
    r = _fields({"first_name": "   ", "last_name": "Baker"})
    assert r["name"] == "Baker"


# ── non-string coercion ───────────────────────────────────────
def test_numeric_zip_still_extracts():
    """Some HTML number inputs POST as int rather than str."""
    r = _fields({"zip": 85383})
    assert r["zip"] == "85383"


# ── none-input safety ─────────────────────────────────────────
def test_none_input_returns_none_dict_shape():
    r = _fields(None)
    assert set(r.keys()) == {
        "name", "first_name", "last_name", "email", "phone",
        "message", "address", "city", "state", "zip",
        "company_name", "service_interest",
    }
    for v in r.values():
        assert v is None
