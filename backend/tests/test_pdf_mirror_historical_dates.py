"""PDF-MIRROR · Feb-2026 — historical date preservation.

Coverage:
  1. Each of the 6 date formats parses correctly.
  2. Absent ``doc_date`` → fallback with
     ``doc_date_source: 'commit_time_fallback'``.
  3. Present ``doc_date`` → landed verbatim with
     ``doc_date_source: 'extracted'``.
  4. ``due_date`` gets the same treatment.
  5. Ambiguous ``02/03/2025`` → parsed per tenant locale when
     configured, else US-first + WARN log.
"""
from __future__ import annotations

import logging
from datetime import date

import pytest

from services.imports.pdf_invoice_extractor import _coerce_date
from services.imports.pdf_commit import _build_quote_doc_from_preview


# ══════════════════════════════════════════════════════════════
# 1. Each of the 6 date formats parses correctly
# ══════════════════════════════════════════════════════════════
_UNAMBIGUOUS_FORMATS = [
    # Format,             Expected date
    ("2025-03-15",        date(2025, 3, 15)),        # ISO
    ("March 15, 2025",    date(2025, 3, 15)),        # Full month name
    ("15 March 2025",     date(2025, 3, 15)),        # Day-first natural
    ("Mar 15 2025",       date(2025, 3, 15)),        # Abbreviated month
    ("03/15/2025",        date(2025, 3, 15)),        # US slash (day > 12 → unambiguous)
    ("2025/03/15",        date(2025, 3, 15)),        # ISO-like slash
]


@pytest.mark.parametrize("raw,expected", _UNAMBIGUOUS_FORMATS)
def test_common_date_formats_parse(raw, expected):
    assert _coerce_date(raw) == expected


def test_none_input_returns_none():
    assert _coerce_date(None) is None
    assert _coerce_date("") is None


def test_garbled_input_returns_none_with_warn(caplog):
    caplog.set_level(logging.WARNING, logger="")
    assert _coerce_date("not a date") is None
    warns = [r for r in caplog.records
              if "pdf_extract.date" in r.getMessage()]
    assert warns, "unparseable input should log a WARN"


# ══════════════════════════════════════════════════════════════
# 2. Ambiguous NN/NN/YYYY WARNs and parses per dayfirst kwarg
# ══════════════════════════════════════════════════════════════
def test_ambiguous_date_defaults_us_and_warns(caplog):
    caplog.set_level(logging.WARNING, logger="")
    # ``02/03/2025`` — could be Feb 3 (US) or March 2 (EU).
    parsed = _coerce_date("02/03/2025")
    assert parsed == date(2025, 2, 3)  # default US
    warns = [r for r in caplog.records
              if "ambiguous" in r.getMessage()]
    assert warns, "ambiguous NN/NN/YYYY should log an ambiguity WARN"


def test_ambiguous_date_dayfirst_locale():
    """A tenant with EU locale (dayfirst=True) parses the same
    ``02/03/2025`` as March 2, not Feb 3."""
    parsed = _coerce_date("02/03/2025", dayfirst=True)
    assert parsed == date(2025, 3, 2)


def test_unambiguous_date_does_not_log_ambiguity(caplog):
    """``03/15/2025`` — day > 12 → unambiguous. No ambiguity WARN."""
    caplog.set_level(logging.WARNING, logger="")
    parsed = _coerce_date("03/15/2025")
    assert parsed == date(2025, 3, 15)
    warns = [r for r in caplog.records
              if "ambiguous" in r.getMessage()]
    assert not warns


# ══════════════════════════════════════════════════════════════
# 3. commit-side doc_date_source sentinel
# ══════════════════════════════════════════════════════════════
def _build_preview(*, quote_in: dict) -> dict:
    return {"quote_in": quote_in, "source_doc_index": 0}


def test_commit_stamps_doc_date_source_extracted_when_present():
    preview = _build_preview(quote_in={
        "customer_id": "cust-1", "customer_name": "A",
        "doc_type": "invoice", "doc_number": "INV-1",
        "doc_date": "2023-06-15",
        "due_date": "2023-07-15",
        "line_items": [{"description": "x", "quantity": 1,
                         "unit_price": 10.0, "line_total": 10.0}],
        "grand_total": 10.0, "total_due": 10.0, "amount_paid": 0.0,
        "imported_totals_verbatim": True,
        "line_items_preserved_verbatim": True,
    })
    doc = _build_quote_doc_from_preview(
        preview=preview,
        batch={"id": "batch-1"},
        tenant_id="tenant-1", operator={"id": "u-admin"},
        commit_at="2026-02-20T10:00:00+00:00",
    )
    assert doc["doc_date"] == "2023-06-15"
    assert doc["doc_date_source"] == "extracted"
    assert doc["due_date"] == "2023-07-15"
    assert doc["due_date_source"] == "extracted"


def test_commit_stamps_doc_date_source_fallback_when_absent():
    preview = _build_preview(quote_in={
        "customer_id": "cust-1", "customer_name": "A",
        "doc_type": "invoice", "doc_number": "INV-2",
        # No doc_date, no due_date.
        "line_items": [{"description": "x", "quantity": 1,
                         "unit_price": 10.0, "line_total": 10.0}],
        "grand_total": 10.0, "total_due": 10.0, "amount_paid": 0.0,
        "imported_totals_verbatim": True,
        "line_items_preserved_verbatim": True,
    })
    doc = _build_quote_doc_from_preview(
        preview=preview,
        batch={"id": "batch-1"},
        tenant_id="tenant-1", operator={"id": "u-admin"},
        commit_at="2026-02-20T10:00:00+00:00",
    )
    assert doc["doc_date"] is None
    assert doc["doc_date_source"] == "commit_time_fallback"
    assert doc["due_date"] is None
    assert doc["due_date_source"] == "commit_time_fallback"


def test_commit_time_fallback_is_never_silent_default():
    """PDF-MIRROR non-negotiable: absent doc_date must NEVER
    silently default to today. The sentinel makes it discoverable."""
    preview = _build_preview(quote_in={
        "customer_id": "cust-1", "customer_name": "A",
        "doc_type": "invoice", "doc_number": "INV-3",
        "line_items": [{"description": "x", "quantity": 1,
                         "unit_price": 10.0, "line_total": 10.0}],
        "grand_total": 10.0, "amount_paid": 0.0,
        "imported_totals_verbatim": True,
    })
    doc = _build_quote_doc_from_preview(
        preview=preview,
        batch={"id": "batch-1"},
        tenant_id="tenant-1", operator={"id": "u-admin"},
        commit_at="2026-02-20T10:00:00+00:00",
    )
    # Sentinel is either "extracted" or "commit_time_fallback" —
    # never silently absent.
    assert doc["doc_date_source"] in ("extracted", "commit_time_fallback")


# ══════════════════════════════════════════════════════════════
# 4. Historical doc_date lands on Mongo doc verbatim
# ══════════════════════════════════════════════════════════════
def test_historical_doc_date_lands_verbatim():
    """A 2015 invoice imported today should carry doc_date=2015-*
    on the Mongo doc, NOT commit-time (2026)."""
    preview = _build_preview(quote_in={
        "customer_id": "cust-1", "customer_name": "A",
        "doc_type": "invoice", "doc_number": "INV-2015",
        "doc_date": "2015-06-15",
        "line_items": [{"description": "x", "quantity": 1,
                         "unit_price": 10.0, "line_total": 10.0}],
        "grand_total": 10.0, "total_due": 10.0, "amount_paid": 0.0,
        "imported_totals_verbatim": True,
        "line_items_preserved_verbatim": True,
    })
    doc = _build_quote_doc_from_preview(
        preview=preview,
        batch={"id": "batch-1"},
        tenant_id="tenant-1", operator={"id": "u-admin"},
        commit_at="2026-02-20T10:00:00+00:00",
    )
    assert doc["doc_date"] == "2015-06-15"
    # Not today.
    assert not doc["doc_date"].startswith("2026")
