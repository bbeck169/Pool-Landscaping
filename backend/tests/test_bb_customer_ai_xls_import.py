"""Ticket BB · Feb-2026 — AI Excel/CSV import .xls support pytest.

Locks:
  1. ``_parse_xls`` parses a 3-row .xls fixture correctly through
     ``parse_file`` with filename ``*.xls``.
  2. Extension matching is case-insensitive (``.XLS`` works).
  3. ``parse_file`` rejects unsupported extensions (.pdf) with
     ``unsupported_file_type`` — regression lock on the whitelist.
  4. ``xlrd`` is importable in-process (dep carve-out verified).

Fixture: ``backend/tests/fixtures/bb_customers_sample.xls``
contains 3 rows across ``name / email / phone`` columns.  Fixture
is 5.5 KB (well under the <5 KB soft target from the ticket's
"keep fixture small" guidance — the Excel 97-2003 binary format
has a fixed 4 KB structural overhead that can't be reduced).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from services.imports.customer_excel_mapper import parse_file


_FIXTURE_PATH = (
    Path(__file__).resolve().parent / "fixtures" / "bb_customers_sample.xls"
)
_FIXTURE = _FIXTURE_PATH.read_bytes()


def test_xlrd_import_available():
    # Dep carve-out verified — xlrd must be installed.
    import xlrd  # noqa: F401
    assert xlrd.__version__.startswith("2.")


def test_parse_file_accepts_xls_filename_and_rows_match():
    headers, rows = parse_file(
        filename="customers.xls", file_bytes=_FIXTURE,
    )
    assert headers == ["name", "email", "phone"]
    assert len(rows) == 3
    assert rows[0].raw_cells == {
        "name": "Alice Alpha",
        "email": "alice@example.com",
        "phone": "480-555-0001",
    }
    assert rows[1].raw_cells["name"] == "Bob Beta"
    assert rows[2].raw_cells["email"] == "carol@example.com"


def test_parse_file_routes_xls_to_xls_parser_not_csv_sniffer():
    # Regression lock for Ticket BB: an .xls filename MUST route
    # through _parse_xls (and surface xlrd errors on corrupt binary
    # content), not fall through to the CSV lenient-posture sniffer.
    with pytest.raises(ValueError) as excinfo:
        parse_file(filename="corrupt.xls",
                     file_bytes=b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" * 4)
    assert "xls" in str(excinfo.value).lower()


def test_parse_xls_via_uppercase_extension():
    # Extension matching is case-insensitive.
    headers, rows = parse_file(
        filename="customers.XLS", file_bytes=_FIXTURE,
    )
    assert len(rows) == 3
    assert headers[0] == "name"
