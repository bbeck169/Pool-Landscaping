"""PDF-MIRROR · Feb-2026 — zero-total recovery + needs_review.

Coverage:
  1. PDF with only subtotal + tax + no grand total → line-item
     recompute yields non-zero, ``total_source ==
     'reconstructed_from_lines'``.
  2. PDF with "Balance Due" (aliased in extractor prompt) →
     extractor captures it as ``grand_total`` → verbatim path.
  3. Truly zero-total PDF (no grand_total, no line items with
     values) → ``total_source == 'zero_total_unrecoverable'``.
  4. PDF-FIX-D verbatim path (valid non-zero) → unchanged,
     ``total_source == 'verbatim'``.
"""
from __future__ import annotations

import pytest

from services.imports.pdf_commit import _apply_totals


# ══════════════════════════════════════════════════════════════
# 1. Verbatim path — extractor's non-zero total → total_source: verbatim
# ══════════════════════════════════════════════════════════════
def test_verbatim_non_zero_total_stamps_verbatim():
    doc = {
        "imported_totals_verbatim": True,
        "subtotal": 400.0, "tax": 25.0, "total": 425.0,
        "tax_rate": 6.25,
        "line_items": [
            {"description": "x", "quantity": 1, "unit_price": 400.0,
             "line_total": 400.0},
        ],
    }
    _apply_totals(doc)
    assert doc["total"] == 425.0
    assert doc["total_source"] == "verbatim"


def test_verbatim_zero_total_falls_through_to_recompute():
    """PDF-FIX-D sentinel: ``total == 0.0`` while
    ``imported_totals_verbatim = True`` means "no PDF totals
    available" → recompute from lines."""
    doc = {
        "imported_totals_verbatim": True,
        "subtotal": 0.0, "tax": 0.0, "total": 0.0,
        "tax_rate": 0.0,
        "line_items": [
            {"description": "x", "quantity": 2, "unit_price": 50.0,
             "line_total": 100.0},
        ],
    }
    _apply_totals(doc)
    # Recompute picks up ``line_total`` first.
    assert doc["subtotal"] == 100.0
    assert doc["total"] == 100.0
    assert doc["total_source"] == "reconstructed_from_lines"


# ══════════════════════════════════════════════════════════════
# 2. Reconstruction from line items — total_source: reconstructed_from_lines
# ══════════════════════════════════════════════════════════════
def test_reconstruction_from_line_totals():
    """PDF with only subtotal + tax + no grand-total line — the
    extractor sees no grand_total, the mapper writes total=0.0,
    line-item recompute derives the total from ``line_total``
    fields."""
    doc = {
        "imported_totals_verbatim": True,
        "subtotal": 0.0, "tax": 0.0, "total": 0.0,
        "tax_rate": 0.0,
        "line_items": [
            {"description": "a", "quantity": 1, "unit_price": 30.0,
             "line_total": 30.0},
            {"description": "b", "quantity": 2, "unit_price": 20.0,
             "line_total": 40.0},
            {"description": "c", "quantity": 1, "unit_price": 15.0,
             "line_total": 15.0},
        ],
    }
    _apply_totals(doc)
    assert doc["subtotal"] == 85.0
    assert doc["total"] == 85.0
    assert doc["total_source"] == "reconstructed_from_lines"


def test_reconstruction_from_qty_times_price_when_line_total_missing():
    """When the extractor DIDN'T capture ``line_total`` (i.e.
    ``line_total = None``), fall back to ``qty × unit_price``."""
    doc = {
        "imported_totals_verbatim": True,
        "subtotal": 0.0, "tax": 0.0, "total": 0.0,
        "tax_rate": 0.0,
        "line_items": [
            {"description": "no line total", "quantity": 3,
             "unit_price": 25.0, "line_total": None},
        ],
    }
    _apply_totals(doc)
    assert doc["subtotal"] == 75.0
    assert doc["total"] == 75.0
    assert doc["total_source"] == "reconstructed_from_lines"


# ══════════════════════════════════════════════════════════════
# 3. Truly unrecoverable — total_source: zero_total_unrecoverable
# ══════════════════════════════════════════════════════════════
def test_zero_total_unrecoverable_when_everything_is_blank():
    """PDF where the extractor captured neither a grand_total NOR
    per-line totals — recompute yields $0.00. The doc is flagged
    for operator review and the commit path REFUSES to insert."""
    doc = {
        "imported_totals_verbatim": True,
        "subtotal": 0.0, "tax": 0.0, "total": 0.0,
        "tax_rate": 0.0,
        "line_items": [
            {"description": "blank price row", "quantity": 1,
             "unit_price": 0.0, "line_total": None},
        ],
    }
    _apply_totals(doc)
    assert doc["total"] == 0.0
    assert doc["total_source"] == "zero_total_unrecoverable"


def test_zero_total_unrecoverable_empty_line_items():
    doc = {
        "imported_totals_verbatim": True,
        "subtotal": 0.0, "tax": 0.0, "total": 0.0,
        "tax_rate": 0.0,
        "line_items": [],
    }
    _apply_totals(doc)
    assert doc["total_source"] == "zero_total_unrecoverable"


# ══════════════════════════════════════════════════════════════
# 4. Tax-rate percentage recompute when only subtotal is verbatim
# ══════════════════════════════════════════════════════════════
def test_tax_recompute_applies_tax_rate_correctly():
    doc = {
        "imported_totals_verbatim": False,
        "subtotal": 0.0, "tax": 0.0, "total": 0.0,
        "tax_rate": 6.25,
        "line_items": [
            {"description": "x", "quantity": 2, "unit_price": 50.0,
             "line_total": 100.0},
        ],
    }
    _apply_totals(doc)
    assert doc["subtotal"] == 100.0
    assert doc["tax"] == 6.25
    assert doc["total"] == 106.25
    assert doc["total_source"] == "reconstructed_from_lines"


# ══════════════════════════════════════════════════════════════
# 5. Balance Due alias — verify extractor prompt captures it
# ══════════════════════════════════════════════════════════════
def test_extractor_prompt_lists_balance_due_alias():
    """The PDF-MIRROR extractor prompt update lists ``Balance
    Due`` / ``Amount Due`` / ``Grand Total`` / ``Invoice Total``
    as ``grand_total`` aliases so the extractor no longer misses
    PDFs that use those labels."""
    from services.imports.pdf_invoice_extractor import _EXTRACTION_USER_TMPL
    lower = _EXTRACTION_USER_TMPL.lower()
    assert "balance due" in lower, (
        "extractor prompt must list 'Balance Due' as a grand_total alias"
    )
    assert "amount due" in lower
    assert "grand total" in lower
    assert "invoice total" in lower


# ══════════════════════════════════════════════════════════════
# 6. Commit-loop skips zero_total_unrecoverable docs (via commit_batch)
# ══════════════════════════════════════════════════════════════
def test_zero_total_never_committed_semantic():
    """The commit-loop refuses to insert docs flagged
    ``zero_total_unrecoverable``. This unit-tests the sentinel
    on the doc; the full commit_batch integration is covered
    in the existing PDF-FIX-D commit-preserve-totals suite +
    the FE test which asserts the ``Needs Review`` badge +
    commit-button gate."""
    doc = {
        "imported_totals_verbatim": True,
        "subtotal": 0.0, "tax": 0.0, "total": 0.0,
        "tax_rate": 0.0,
        "line_items": [],
    }
    _apply_totals(doc)
    # The doc carries the reject sentinel — commit_batch reads
    # this and pushes the preview into ``warnings`` with
    # ``code: 'needs_review', reason: 'zero_total_unrecoverable'``
    # rather than into ``to_insert``.
    assert doc["total_source"] == "zero_total_unrecoverable"
