"""Phase L2 · Feb-2026 — label-aware extractor unit tests."""
from services.lead_extraction import (
    extract_contact_fields,
    extract_contact_fields_with_schema,
)


_SVC_ADDR = "789 Elm St, Peoria, AZ"
_DESC = "Need weekly pool cleaning; two dogs on-site."


# ─── 1. Auto-generated ids resolve via label — Service Address ─────
def test_l2_field_id_auto_generated_resolves_service_address_via_label():
    schema = [
        {"id": "field_Service Address_5", "name": "field_Service Address_5",
          "label": "Service Address", "type": "text"},
    ]
    vals = {"field_Service Address_5": _SVC_ADDR}
    out = extract_contact_fields_with_schema(vals, schema)
    assert out["address"] == _SVC_ADDR


# ─── 2. Auto-generated ids resolve via label — Description ─────────
def test_l2_field_id_9_resolves_description_via_label():
    schema = [
        {"id": "field_9", "name": "field_9",
          "label": "Description of Services Needed", "type": "textarea"},
    ]
    vals = {"field_9": _DESC}
    out = extract_contact_fields_with_schema(vals, schema)
    # Extraction target for "notes" family fields is ``message`` — the
    # lead-writer twins it to ``notes`` too.
    assert out["message"] == _DESC


# ─── 3. Precedence — matching KEY wins even when label also matches
def test_l2_key_match_wins_over_label_match():
    schema = [
        {"id": "service_address", "name": "service_address",
          "label": "Service Address", "type": "text"},
        {"id": "field_99", "name": "field_99",
          "label": "Service Address", "type": "text"},
    ]
    vals = {
        "service_address": "123 KEY WINS Blvd",
        "field_99": "456 LABEL LOSES Ave",
    }
    out = extract_contact_fields_with_schema(vals, schema)
    assert out["address"] == "123 KEY WINS Blvd"


# ─── 4. Case-insensitive label match ──────────────────────────────
def test_l2_label_match_case_insensitive():
    for label in ("SERVICE ADDRESS", "service address", "Service Address"):
        schema = [{"id": "f1", "name": "f1", "label": label, "type": "text"}]
        vals = {"f1": _SVC_ADDR}
        out = extract_contact_fields_with_schema(vals, schema)
        assert out["address"] == _SVC_ADDR, f"failed on label={label!r}"


# ─── 5. Fuzzy match — "Where is the service?" → address ────────────
def test_l2_fuzzy_match_where_is_the_service():
    schema = [
        {"id": "f_where", "name": "f_where",
          "label": "Where is the service?", "type": "text"},
    ]
    vals = {"f_where": _SVC_ADDR}
    out = extract_contact_fields_with_schema(vals, schema)
    assert out["address"] == _SVC_ADDR


# ─── 6. Anti-match — "Phone Address Book" MUST NOT hijack address ──
def test_l2_anti_match_prevents_cross_field_hijack():
    schema = [
        {"id": "f_bad", "name": "f_bad",
          "label": "Phone Address Book", "type": "text"},
    ]
    vals = {"f_bad": "Unrelated data"}
    out = extract_contact_fields_with_schema(vals, schema)
    assert out["address"] is None


# ─── 7. Pre-L2 alias path still works when schema is None ──────────
def test_l2_no_schema_falls_through_to_key_aliases():
    vals = {"service_address": "42 Legacy Rd"}
    out = extract_contact_fields_with_schema(vals, None)
    # Legacy behaviour is unchanged.
    assert out["address"] == "42 Legacy Rd"
    # And matches the pre-L2 helper byte-for-byte.
    legacy = extract_contact_fields(vals)
    assert out["address"] == legacy["address"]


# ─── 8. Empty-string values are skipped so a later label wins ──────
def test_l2_empty_value_on_matching_field_doesnt_block_other_fields():
    schema = [
        {"id": "field_1", "name": "field_1",
          "label": "Service Address", "type": "text"},
        {"id": "field_2", "name": "field_2",
          "label": "Property Address", "type": "text"},
    ]
    vals = {"field_1": "   ", "field_2": _SVC_ADDR}
    out = extract_contact_fields_with_schema(vals, schema)
    assert out["address"] == _SVC_ADDR


# ─── 9. Additional coverage — phone / email / company / name ──────
def test_l2_additional_canonical_fields_resolve_via_label():
    schema = [
        {"id": "f_a", "label": "Cell Phone Number"},
        {"id": "f_b", "label": "Your Email"},
        {"id": "f_c", "label": "Company Name"},
        {"id": "f_d", "label": "Full Name"},
    ]
    vals = {"f_a": "555-123-4567",
             "f_b": "buyer@example.com",
             "f_c": "Acme Widgets LLC",
             "f_d": "Jane Buyer"}
    out = extract_contact_fields_with_schema(vals, schema)
    assert out["phone"] == "555-123-4567"
    assert out["email"] == "buyer@example.com"
    assert out["company_name"] == "Acme Widgets LLC"
    assert out["name"] == "Jane Buyer"
