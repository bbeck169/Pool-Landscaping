"""PDFI-PAID-A · Feb-2026 — Backend paid-status extraction.

Locks the Option-B scope (user-approved) — reuse existing
``amount_paid`` / ``total_due`` / ``paid_at`` fields and add only
``is_paid`` as a new derived boolean under the STRICT ruling.

Seven assertions, following the ``test_pdfi_fast_path.py`` pattern
of synthesising native-text PDFs via PyMuPDF ``insert_text``:

  (a) Fully-paid native invoice with explicit ``Amount Paid``,
      ``Total Due $0``, and ``Payment Date: Aug 28, 2026`` →
      ``is_paid=True`` + all three value fields populated.
  (b) Partial payment (``Amount Paid $100`` + ``Total Due $40``) →
      ``is_paid=False`` under STRICT ruling even though
      ``amount_paid`` and ``total_due`` are both present.
  (c) No paid markers at all → ``is_paid=False`` + ``amount_paid``
      / ``total_due`` / ``paid_at`` all None.
  (d) ``PAID IN FULL`` stamp + ``Total Due $0`` but NO explicit
      ``Amount Paid`` label → ``is_paid=False`` (STRICT: both
      inputs required).  Guards against a lax ruling that would
      promote on the stamp alone.
  (e) ``Amount Paid $140`` + ``Total Due $0`` but NO payment date
      printed → ``is_paid=True`` + ``paid_at=None`` (operator
      fills the date at preview-confirm per PDFI-PAID-C).
  (f) Vision path (mock ``_call_vision_model`` returning the four
      fields in parsed JSON) → ``ExtractedBatch`` carries all
      four through verbatim.
  (g) PDFI-III regression — the sample Diane Lloyd invoice from
      the PDFI-III fixture set still fast-path-accepts, now with
      ``is_paid=True`` + ``amount_paid=140.0`` + ``total_due=0.0``
      + ``paid_at=date(2026,8,28)``.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any, Dict, List, Optional

import fitz
import pytest


# ══════════════════════════════════════════════════════════════════
# Helpers — build native-text PDFs via PyMuPDF insert_text
# (same shape as test_pdfi_fast_path.py so fixtures stay comparable)
# ══════════════════════════════════════════════════════════════════

def _pdf_from_lines(lines: List[str]) -> bytes:
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
    doc = fitz.open()
    doc.new_page()
    out = doc.tobytes()
    doc.close()
    return out


_HAPPY_LINES_FULLY_PAID_WITH_DATE = [
    "Pool & Landscaping of Vistancia LLC",
    "Bill To:",
    "Diane Lloyd",
    "123 Lake View Drive",
    "Peoria AZ 85383",
    "",
    "Invoice #10774",
    "Date: Aug 28, 2026",
    "Payment Date: Aug 28, 2026",
    "",
    "Description                        Qty    Rate      Amount",
    "Full Weekly Pool Service            1   $140.00   $140.00",
    "",
    "Subtotal:    $140.00",
    "Amount Paid: $140.00",
    "Total Due:   $0.00",
    "Total:       $140.00",
]

_HAPPY_LINES_FULLY_PAID_NO_DATE = [
    "Pool & Landscaping of Vistancia LLC",
    "Bill To:",
    "Diane Lloyd",
    "123 Lake View Drive",
    "",
    "Invoice #10775",
    "Date: Aug 28, 2026",
    "",
    "Description                        Qty    Rate      Amount",
    "Full Weekly Pool Service            1   $140.00   $140.00",
    "",
    "Subtotal:    $140.00",
    "Amount Paid: $140.00",
    "Total Due:   $0.00",
    "Total:       $140.00",
]

_PARTIAL_PAY_LINES = [
    "Pool & Landscaping of Vistancia LLC",
    "Bill To:",
    "Diane Lloyd",
    "123 Lake View Drive",
    "",
    "Invoice #10776",
    "Date: Aug 28, 2026",
    "",
    "Description                        Qty    Rate      Amount",
    "Full Weekly Pool Service            1   $140.00   $140.00",
    "",
    "Subtotal:    $140.00",
    "Amount Paid: $100.00",
    "Total Due:   $40.00",
    "Total:       $140.00",
]

_UNPAID_LINES = [
    "Pool & Landscaping of Vistancia LLC",
    "Bill To:",
    "Diane Lloyd",
    "123 Lake View Drive",
    "",
    "Invoice #10777",
    "Date: Aug 28, 2026",
    "",
    "Description                        Qty    Rate      Amount",
    "Full Weekly Pool Service            1   $140.00   $140.00",
    "",
    "Subtotal:    $140.00",
    "Total:       $140.00",
]

_STAMP_ONLY_LINES = [
    "Pool & Landscaping of Vistancia LLC",
    "Bill To:",
    "Diane Lloyd",
    "123 Lake View Drive",
    "",
    "Invoice #10778",
    "Date: Aug 28, 2026",
    "",
    "PAID IN FULL",
    "",
    "Description                        Qty    Rate      Amount",
    "Full Weekly Pool Service            1   $140.00   $140.00",
    "",
    "Subtotal:    $140.00",
    "Total Due:   $0.00",
    "Total:       $140.00",
]


# ══════════════════════════════════════════════════════════════════
# (a) Fully paid + date → is_paid=True + all 4 fields populated
# ══════════════════════════════════════════════════════════════════
def test_a_fully_paid_with_date_sets_is_paid_true():
    from services.imports.pdf_invoice_extractor import _try_text_fast_path
    pdf = _pdf_from_lines(_HAPPY_LINES_FULLY_PAID_WITH_DATE)
    doc = _try_text_fast_path(pdf, batch_id="bat-paid-a", doc_idx=0)
    assert doc is not None, "fast-path should accept a happy-path paid invoice"
    assert doc.is_paid is True, f"expected is_paid=True, got {doc.is_paid!r}"
    assert doc.amount_paid == 140.0
    assert doc.total_due == 0.0
    assert doc.paid_at == date(2026, 8, 28), (
        f"expected paid_at=2026-08-28, got {doc.paid_at!r}"
    )


# ══════════════════════════════════════════════════════════════════
# (b) Partial payment → is_paid=False under STRICT ruling
# ══════════════════════════════════════════════════════════════════
def test_b_partial_payment_is_not_paid():
    from services.imports.pdf_invoice_extractor import _try_text_fast_path
    pdf = _pdf_from_lines(_PARTIAL_PAY_LINES)
    doc = _try_text_fast_path(pdf, batch_id="bat-paid-b", doc_idx=0)
    assert doc is not None
    assert doc.is_paid is False, (
        f"STRICT ruling: total_due > 0.01 must disqualify, "
        f"got is_paid={doc.is_paid!r}"
    )
    assert doc.amount_paid == 100.0
    assert doc.total_due == 40.0


# ══════════════════════════════════════════════════════════════════
# (c) No paid markers at all → is_paid=False + fields None
# ══════════════════════════════════════════════════════════════════
def test_c_no_paid_markers_at_all():
    from services.imports.pdf_invoice_extractor import _try_text_fast_path
    pdf = _pdf_from_lines(_UNPAID_LINES)
    doc = _try_text_fast_path(pdf, batch_id="bat-paid-c", doc_idx=0)
    assert doc is not None
    assert doc.is_paid is False
    assert doc.amount_paid is None
    assert doc.total_due is None
    assert doc.paid_at is None


# ══════════════════════════════════════════════════════════════════
# (d) PAID IN FULL stamp + Total Due $0 but no Amount Paid line
# ══════════════════════════════════════════════════════════════════
def test_d_paid_stamp_without_explicit_amount_paid_is_not_strict_paid():
    from services.imports.pdf_invoice_extractor import _try_text_fast_path
    pdf = _pdf_from_lines(_STAMP_ONLY_LINES)
    doc = _try_text_fast_path(pdf, batch_id="bat-paid-d", doc_idx=0)
    assert doc is not None, "fast-path still accepts (4 required fields pass)"
    assert doc.is_paid is False, (
        f"STRICT ruling: PAID stamp alone (no amount_paid) must NOT "
        f"promote to is_paid=True, got {doc.is_paid!r}"
    )
    assert doc.amount_paid is None, (
        "no 'Amount Paid' label on the invoice → amount_paid stays None"
    )
    assert doc.total_due == 0.0


# ══════════════════════════════════════════════════════════════════
# (e) Fully paid without date → is_paid=True + paid_at=None
# ══════════════════════════════════════════════════════════════════
def test_e_fully_paid_without_date_still_promotes_but_paid_at_none():
    from services.imports.pdf_invoice_extractor import _try_text_fast_path
    pdf = _pdf_from_lines(_HAPPY_LINES_FULLY_PAID_NO_DATE)
    doc = _try_text_fast_path(pdf, batch_id="bat-paid-e", doc_idx=0)
    assert doc is not None
    assert doc.is_paid is True
    assert doc.amount_paid == 140.0
    assert doc.total_due == 0.0
    assert doc.paid_at is None, (
        f"no Payment Date / Paid on line → paid_at stays None (operator "
        f"fills at preview-confirm), got {doc.paid_at!r}"
    )


# ══════════════════════════════════════════════════════════════════
# (f) Vision path — mocked _call_vision_model returns all 4 fields
# ══════════════════════════════════════════════════════════════════
class _PaidVisionStub:
    """Returns a canned 1-doc payload with is_paid + paid-related fields."""

    def __init__(self):
        self.calls: List[Dict[str, Any]] = []

    async def __call__(self, *args, **kwargs):
        self.calls.append({"kwargs": kwargs})
        return {
            "parsed": {
                "doc_kind": "invoice",
                "source_page_range": [1, 1],
                "customer_name": "Diane Lloyd",
                "customer_address": "123 Lake View Drive",
                "doc_number": "10779",
                "doc_date": "2026-09-15",
                "line_items": [{
                    "item_name": "Full Weekly Pool Service",
                    "description": "weekly chem + clean",
                    "qty": 1,
                    "cost_rate": 200,
                    "line_total": 200,
                }],
                "grand_total": 200,
                "amount_paid": 200,
                "total_due": 0,
                "is_paid": True,
                "paid_at": "2026-09-15",
            },
            "raw": {},
        }


@pytest.fixture()
def paid_vision_stub(monkeypatch):
    from services.imports import pdf_invoice_extractor as mod
    stub = _PaidVisionStub()
    monkeypatch.setattr(mod, "_call_vision_model", stub)
    return stub


@pytest.mark.anyio
async def test_f_vision_path_carries_is_paid_and_paid_at_through(
    paid_vision_stub,
):
    from services.imports.pdf_invoice_extractor import extract
    batch = await extract(
        pdf_bytes=_empty_page_pdf(),  # forces vision fallback
        tenant_id="t-paid-f",
        source_filename="scan.pdf",
        db=None,
    )
    assert batch.model_used != "pymupdf-fast-path", (
        f"expected vision fallback, got model_used={batch.model_used!r}"
    )
    assert len(paid_vision_stub.calls) >= 1
    assert len(batch.documents) == 1
    d = batch.documents[0]
    assert d.is_paid is True
    assert d.amount_paid == 200
    assert d.total_due == 0
    assert d.paid_at == date(2026, 9, 15)


# ══════════════════════════════════════════════════════════════════
# (g) Regression — PDFI-III Diane Lloyd fixture still works end-to-end
#     with the new paid-status fields populated.
# ══════════════════════════════════════════════════════════════════
_PDFI_III_DIANE_LLOYD_LINES = [
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
    "Payment Date: Aug 28, 2026",
    "",
    "Description                               Qty    Rate      Amount",
    "Full Weekly Pool Service                   1   $140.00   $140.00",
    "",
    "Subtotal:    $140.00",
    "Amount Paid: $140.00",
    "Total Due:   $0.00",
    "Total:       $140.00",
]


def test_g_pdfi_iii_fixture_still_fast_path_accepts_with_paid_fields():
    from services.imports.pdf_invoice_extractor import _try_text_fast_path
    pdf = _pdf_from_lines(_PDFI_III_DIANE_LLOYD_LINES)
    doc = _try_text_fast_path(pdf, batch_id="bat-paid-g", doc_idx=0)
    # PDFI-III invariants (locked by test_pdfi_fast_path::test_a)
    assert doc is not None
    assert doc.customer_name == "Diane Lloyd"
    assert doc.doc_date == date(2026, 8, 28)
    assert doc.grand_total == 140.0
    assert doc.doc_number == "10774"
    assert len(doc.line_items) == 1
    assert doc.line_items[0].item_name == "Full Weekly Pool Service"
    # PDFI-PAID-A additions
    assert doc.is_paid is True
    assert doc.amount_paid == 140.0
    assert doc.total_due == 0.0
    assert doc.paid_at == date(2026, 8, 28)
