"""Phase F5 · Feb-2026 — the new lead schema fields (first_name,
last_name, city, state, zip, company_name) are persisted on insert.

Covers ``lead_row_from_form_values`` (public-form path) so a fresh
submission carrying the full F5 field set lands correctly.
"""
from __future__ import annotations

from services import lead_extraction as le


def test_full_form_submission_populates_all_new_fields():
    vals = {
        "company_name": "Acme LLC",
        "first_name": "Alice",
        "last_name": "Baker",
        "cell_phone": "555-0001",
        "email": "alice@example.com",
        "address": "123 Main St",
        "city": "Peoria",
        "state": "AZ",
        "zip": "85383",
        "description_of_service_needed": "Weekly pool cleaning",
    }
    row = le.lead_row_from_form_values(
        tid="t-1", vals=vals, source_label="Lead")
    assert row["name"] == "Alice Baker"
    assert row["first_name"] == "Alice"
    assert row["last_name"] == "Baker"
    assert row["email"] == "alice@example.com"
    assert row["phone"] == "555-0001"
    assert row["address"] == "123 Main St"
    assert row["service_address"] == "123 Main St"
    assert row["city"] == "Peoria"
    assert row["state"] == "AZ"
    assert row["zip"] == "85383"
    assert row["company_name"] == "Acme LLC"
    assert row["message"] == "Weekly pool cleaning"
    assert row["notes"] == "Weekly pool cleaning"
    assert row["source"] == "Lead"
    assert row["tenant_id"] == "t-1"
    assert row["status"] == "new"
    assert "created_at" in row
    assert "id" in row


def test_partial_submission_leaves_new_fields_as_empty_strings():
    """Every F5 field is set to ``""`` (not missing) so filter
    queries on Mongo don't have to check for absent keys."""
    row = le.lead_row_from_form_values(
        tid="t-1", vals={"email": "alice@example.com"},
        source_label="Web Form")
    assert row["first_name"] == ""
    assert row["last_name"] == ""
    assert row["city"] == ""
    assert row["state"] == ""
    assert row["zip"] == ""
    assert row["company_name"] == ""
    # And the sentinel name fires because no name-composition inputs.
    assert row["name"] == le.WEBSITE_VISITOR_FALLBACK


def test_service_interest_still_flows_through():
    """Regression against earlier F5 iterations dropping the pre-
    existing service_interest capture."""
    row = le.lead_row_from_form_values(
        tid="t-1",
        vals={"email": "alice@example.com",
              "service_interest": "landscape_design"},
        source_label="Web Form",
    )
    assert row["service_interest"] == "landscape_design"
