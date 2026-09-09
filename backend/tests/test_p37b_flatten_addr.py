"""Feb-2026 · P37b — Regression guard for the ``_flatten_addr`` helper
in ``services.google_maps.geocoding``.

The P37 backfill originally assumed ``customers.service_address`` was
always a string, but 120 of 121 seeded rows persist a structured
dict (``{street, city, state, postal_code}``). ``.strip()`` on the
dict raised ``AttributeError`` and every row got silently swallowed
by the migration's ``try/except``. The fix routes every read of
``service_address`` through ``_flatten_addr`` so callers see a
stripped string regardless of the underlying persisted shape.

These tests pin:
  1. Dict-typed ``service_address`` flattens correctly.
  2. String-typed passes through unchanged (bar trim).
  3. Missing / empty / non-string non-dict values return ``""`` so
     callers can fall through to the per-field builder.
  4. The ``postal_code`` → ``zip`` alias round-trips.
  5. Whitespace-only fields don't leak into the joined output.
"""
from services.google_maps.geocoding import _flatten_addr


class TestFlattenAddr:
    def test_dict_with_postal_code(self):
        raw = {"street": "13333 W Jesse Red Dr",
                "city": "Peoria", "state": "AZ",
                "postal_code": "85383"}
        assert _flatten_addr(raw) == (
            "13333 W Jesse Red Dr Peoria AZ 85383"
        )

    def test_dict_with_zip_alias(self):
        raw = {"street": "1 Test Way", "city": "Phoenix",
                "state": "AZ", "zip": "85001"}
        assert _flatten_addr(raw) == "1 Test Way Phoenix AZ 85001"

    def test_dict_missing_fields_skipped(self):
        raw = {"street": "9 Main St", "city": "", "state": "AZ",
                "postal_code": "85001"}
        # Empty city drops out; joiner does NOT emit double spaces.
        assert _flatten_addr(raw) == "9 Main St AZ 85001"

    def test_dict_all_empty(self):
        raw = {"street": "", "city": "", "state": "", "postal_code": ""}
        assert _flatten_addr(raw) == ""

    def test_dict_whitespace_only_stripped(self):
        raw = {"street": "  ", "city": "Peoria",
                "state": "AZ", "postal_code": "85383"}
        assert _flatten_addr(raw) == "Peoria AZ 85383"

    def test_string_passthrough(self):
        assert _flatten_addr("13333 W Jesse Red Dr, Peoria, AZ, 85383") == (
            "13333 W Jesse Red Dr, Peoria, AZ, 85383"
        )

    def test_string_trimmed(self):
        assert _flatten_addr("   1 Main St  ") == "1 Main St"

    def test_none_falls_through_to_empty(self):
        assert _flatten_addr(None) == ""

    def test_missing_field_falls_through_to_empty(self):
        # ``dict.get("service_address")`` on a doc without the field
        # returns None — same code path as ``test_none_falls_through``.
        cust = {}
        assert _flatten_addr(cust.get("service_address")) == ""

    def test_empty_string_returns_empty(self):
        # Empty string is str-typed but stripped to ``""`` — same as
        # "missing", so callers correctly fall through.
        assert _flatten_addr("") == ""
        assert _flatten_addr("   ") == ""

    def test_unexpected_shapes_return_empty(self):
        """List / int / bool → treat as unusable so callers use the
        per-field builder instead. Documented behavior per the P37b
        scope note ("don't invent handlers for other shapes")."""
        assert _flatten_addr(["1 Main St"]) == ""
        assert _flatten_addr(12345) == ""
        assert _flatten_addr(True) == ""
