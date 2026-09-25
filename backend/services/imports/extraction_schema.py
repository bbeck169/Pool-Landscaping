"""Task H · Phase H.1 · Feb-2026 — PDF Invoice Importer schemas.

Pydantic V2 models for the extraction preview contract used by
``POST /api/imports/pdf-invoice``.  These are deliberately looser
than ``models.QuoteIn`` because the vision extractor produces
best-effort structured data that the mapper (``pdf_mapper.py``)
then converts into strict ``QuoteIn`` shape.

Field-level notes worth reading:

  * ``doc_kind`` — enum, drives mapper branching. Payment
    receipts skip QuoteIn generation entirely (deferred_to_h4).

  * ``paid_at`` — used in TWO places: (1) invoices marked paid
    at issue time (rare), and (2) payment receipts (the receipt
    IS the payment event).  Mapper prepares Phase H.2's post-
    create ``record-payment`` call when set on an invoice.

  * ``payment_method`` — normalized to enum by extractor via
    lower-cased substring match.  See
    ``pdf_invoice_extractor.normalize_payment_method``.

  * ``raw_operator_audit_line`` — verbatim excerpt of any
    ``Added by X`` / ``Processed by X`` line so downstream ops
    can prove the extractor SAW the operator-line but chose
    NOT to promote it to customer_name (the H.1 test suite
    locks this contract).

  * ``extraction_confidence`` — model self-reported 0.0-1.0.
    Callers may raise the fuzzy-match threshold when this is
    low.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class ExtractedLineItem(BaseModel):
    """One line item as returned by gpt-4o vision. All numeric
    fields optional because the model may see a description-only
    row (e.g. "Notes:" section) and we shouldn't 422 on it."""
    description: str
    cost_rate: Optional[float] = None
    qty: Optional[float] = None
    tax_pct: Optional[float] = None
    line_total: Optional[float] = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class ExtractedDocument(BaseModel):
    """One logical document inside a possibly-batched PDF.

    ``source_page_range`` is 1-indexed inclusive on both ends —
    matches the human-readable page count in the source PDF.
    """
    doc_kind: Literal["invoice", "estimate", "payment_receipt"]
    source_page_range: List[int]
    customer_name: Optional[str] = None
    customer_email: Optional[str] = None
    customer_phone: Optional[str] = None
    customer_address: Optional[str] = None
    doc_number: Optional[str] = None
    doc_date: Optional[date] = None
    due_date: Optional[date] = None
    paid_at: Optional[date] = None
    payment_method: Optional[Literal[
        "cash", "check", "card", "ach", "other",
    ]] = None
    payment_reference: Optional[str] = None
    line_items: List[ExtractedLineItem] = []
    subtotal: Optional[float] = None
    tax_total: Optional[float] = None
    grand_total: Optional[float] = None
    amount_paid: Optional[float] = None
    total_due: Optional[float] = None
    notes: Optional[str] = None
    raw_operator_audit_line: Optional[str] = None
    extraction_confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class ExtractedBatch(BaseModel):
    """Envelope returned by ``pdf_invoice_extractor.extract``."""
    batch_id: str
    source_filename: str
    source_sha256: str
    source_byte_count: int
    page_count: int
    tenant_id: str
    documents: List[ExtractedDocument]
    warnings: List[str] = []
    model_used: str
    extraction_started_at: datetime
    extraction_finished_at: datetime


class MapperReport(BaseModel):
    """Preview of what the Phase H.2 commit path would produce
    for one ``ExtractedDocument``.  Phase H.1 returns this in
    the router response body; Phase H.2 replays it against the
    live commit endpoints."""
    source_doc_index: int
    doc_kind: Literal["invoice", "estimate", "payment_receipt"]
    mapped_target: Literal["quote_in", "deferred_to_h4"]

    # QuoteIn preview (None when doc_kind=payment_receipt).
    # Stored as a dict rather than a QuoteIn to keep the response
    # JSON-friendly + avoid a circular import from models.py at
    # schema-load time.
    quote_in: Optional[Dict[str, Any]] = None

    # Customer resolution outcome.
    customer_resolution: Literal["matched", "pending", "unresolved"]
    matched_customer_id: Optional[str] = None
    match_score: Optional[float] = None   # rapidfuzz 0-100
    pending_customer_id: Optional[str] = None

    # H.2 hook — record-payment actions the commit path should
    # replay after inserting the invoice doc.
    pending_payment_actions: List[Dict[str, Any]] = []

    errors: List[str] = []
    warnings: List[str] = []

    # Response-payload cap flag (H.1 spec §Response payload cap).
    # When True, ``quote_in.line_items`` was truncated to 25
    # items for wire-size; the full extracted list is retained
    # server-side for Phase H.2 commit retrieval.
    truncated: bool = False
