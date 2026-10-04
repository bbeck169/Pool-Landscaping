"""PDFI-III · Feb-2026 — PyMuPDF native-text fast path with vision fallback.

Locks the contracts shipped with PDFI-III:

  (a) ``_try_text_fast_path`` accepts a native-text PDF carrying
      all four required fields and returns an
      ``ExtractedDocument`` with matching values.
  (b) Rejects an empty-text-layer PDF (synthetic scan-equivalent)
      and logs the decision as ``rejected`` with
      ``blank_page_text_layer`` in ``missing_fields``.
  (c) Rejects when customer_name cannot be parsed (no ``Bill To``
      or ``Customer`` block).
  (d) Rejects when grand_total cannot be parsed (no labelled
      total AND no bare currency figure).
  (e) ``extract()`` on a scan-equivalent PDF falls through to
      the vision stub (``_call_vision_model`` IS called).
  (f) ``extract()`` on a valid native-text PDF does NOT call the
      vision stub (``_call_vision_model`` call_count == 0).

All PDFs are synthesised in-test with PyMuPDF ``insert_text`` —
no binary fixtures shipped.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import fitz
import pytest


# ══════════════════════════════════════════════════════════════════
# Helpers — build native-text PDFs via PyMuPDF insert_text
# ══════════════════════════════════════════════════════════════════

def _pdf_from_lines(lines: List[str]) -> bytes:
    """Render ``lines`` as a one-page PDF with each line vertically
    offset. ``fitz.insert_text`` lays out at the given point so we
    manually step the y coordinate."""
    doc = fitz.open()
    page = doc.new_page()
    y = 72
    for line in lines:
        page.insert_text((50, y), line)
        y += 16
    out = doc.tobytes()
    doc.close()
    return out


def _empty_page_pdf() -> bytes:
    """Zero-text-layer page — simulates a scanned image PDF for the
    fast-path's ``any(page_text.strip() == "")`` guard."""
    doc = fitz.open()
    doc.new_page()
    out = doc.tobytes()
    doc.close()
    return out


_HAPPY_PATH_LINES = [
    "Pool & Landscaping of Vistancia LLC",
    "22 Vendor Way",
    "Peoria AZ 85383",
    "",
    "Bill To:",
    "Diane Lloyd",
    "123 Lake View Drive",
    "Peoria AZ 85383",
    "",
    "Invoice #10774",
    "Date: Aug 28, 2026",
    "",
    "Description                               Qty    Rate      Amount",
    "Full Weekly Pool Service                   1   $140.00   $140.00",
    "",
    "Subtotal:    $140.00",
    "Amount Paid: $140.00",
    "Total:       $140.00",
]


# ══════════════════════════════════════════════════════════════════
# (a-d) Fast-path acceptance + rejection assertions
# ══════════════════════════════════════════════════════════════════

def test_a_native_text_accepted_returns_extracted_document():
    from services.imports.pdf_invoice_extractor import _try_text_fast_path
    pdf = _pdf_from_lines(_HAPPY_PATH_LINES)
    doc = _try_text_fast_path(
        pdf, batch_id="bat-fast-a", doc_idx=0,
    )
    assert doc is not None, "fast-path should accept a happy-path native PDF"
    assert doc.customer_name == "Diane Lloyd"
    assert doc.doc_date is not None
    assert doc.doc_date.year == 2026
    assert doc.doc_date.month == 8
    assert doc.doc_date.day == 28
    assert doc.grand_total == 140.0
    assert doc.doc_number == "10774"
    assert len(doc.line_items) == 1
    li = doc.line_items[0]
    assert li.item_name == "Full Weekly Pool Service"
    assert li.cost_rate == 140.0
    assert li.line_total == 140.0


def test_b_empty_text_layer_rejected_and_logs_decision(caplog):
    from services.imports.pdf_invoice_extractor import _try_text_fast_path
    with caplog.at_level(logging.INFO, logger="imports.pdf_invoice_extractor"):
        out = _try_text_fast_path(
            _empty_page_pdf(), batch_id="bat-fast-b", doc_idx=0,
        )
    assert out is None, "fast-path must bail on empty text layer"
    # Decision log emitted with ``rejected`` + missing_fields marker.
    rejections = [
        r for r in caplog.records
        if r.message == "pdfi_fast_path_decision"
        and getattr(r, "decision", None) == "rejected"
    ]
    assert rejections, "no rejection decision log emitted"
    assert "blank_page_text_layer" in getattr(
        rejections[-1], "missing_fields", [],
    )


def test_c_missing_customer_name_rejected():
    from services.imports.pdf_invoice_extractor import _try_text_fast_path
    pdf = _pdf_from_lines([
        "Pool & Landscaping of Vistancia LLC",
        "22 Vendor Way",
        "",
        # NO "Bill To:" or "Customer:" header — customer unresolvable.
        "Walk-in Service",
        "123 Street",
        "",
        "Invoice #99999",
        "Date: Aug 28, 2026",
        "",
        "Full Weekly Pool Service   1   $140.00   $140.00",
        "Total:  $140.00",
    ])
    out = _try_text_fast_path(pdf, batch_id="bat-fast-c", doc_idx=0)
    assert out is None, "fast-path must reject when customer block absent"


def test_d_missing_grand_total_rejected():
    from services.imports.pdf_invoice_extractor import _try_text_fast_path
    # No currency figures at all — nothing for the fallback regex to
    # salvage either.
    pdf = _pdf_from_lines([
        "Bill To:",
        "Diane Lloyd",
        "123 Lake View Drive",
        "",
        "Invoice #10774",
        "Date: Aug 28, 2026",
        "",
        "Full Weekly Pool Service (quote pending — pricing TBD)",
    ])
    out = _try_text_fast_path(pdf, batch_id="bat-fast-d", doc_idx=0)
    assert out is None, "fast-path must reject when no total parsable"


# ══════════════════════════════════════════════════════════════════
# (e-f) extract() dispatch assertions — fast vs. vision
# ══════════════════════════════════════════════════════════════════

class _VisionCallSpy:
    """Replacement for ``_call_vision_model`` — records invocations
    and returns a graceful-warning stub so ``extract()`` continues
    without exploding on real network / dispatcher plumbing.
    """

    def __init__(self):
        self.calls: List[Dict[str, Any]] = []

    async def __call__(self, *args, **kwargs):
        self.calls.append({"args": args, "kwargs": kwargs})
        # Graceful-warning shape — extract() swallows into a
        # warnings entry and keeps going.
        return {"error": "stubbed_for_pdfi_iii_test", "parsed": {}}


@pytest.fixture()
def vision_spy(monkeypatch):
    from services.imports import pdf_invoice_extractor as mod
    spy = _VisionCallSpy()
    monkeypatch.setattr(mod, "_call_vision_model", spy)
    return spy


@pytest.mark.anyio
async def test_e_scan_equivalent_falls_through_to_vision(vision_spy):
    """Fast-path returns None → vision stub IS called at least once."""
    from services.imports.pdf_invoice_extractor import extract
    out = await extract(
        pdf_bytes=_empty_page_pdf(),
        tenant_id="t-fast-e",
        source_filename="scan.pdf",
        db=None,
    )
    assert out.model_used != "pymupdf-fast-path", (
        f"expected vision fallback, got model_used={out.model_used!r}"
    )
    assert len(vision_spy.calls) >= 1, (
        f"vision stub should have been called at least once, "
        f"got {len(vision_spy.calls)}"
    )


@pytest.mark.anyio
async def test_f_native_text_pdf_bypasses_vision_entirely(vision_spy):
    """Fast-path accepts → vision stub is NOT called at all."""
    from services.imports.pdf_invoice_extractor import extract
    out = await extract(
        pdf_bytes=_pdf_from_lines(_HAPPY_PATH_LINES),
        tenant_id="t-fast-f",
        source_filename="native.pdf",
        db=None,
    )
    assert out.model_used == "pymupdf-fast-path", (
        f"expected model_used='pymupdf-fast-path', "
        f"got {out.model_used!r}"
    )
    assert len(out.documents) == 1
    assert out.documents[0].customer_name == "Diane Lloyd"
    assert len(vision_spy.calls) == 0, (
        f"vision stub must not fire on a fast-path hit, "
        f"got {len(vision_spy.calls)} calls"
    )
