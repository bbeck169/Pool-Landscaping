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
    # Feb-2026 · PDF Importer Sub-phase A — short-label distinct
    # from ``description``.  The extractor prompt gains the field
    # in Sub-phase B; until then this defaults to ``None`` on every
    # extraction result and the mapper's copy-through is a no-op.
    # Nullable + Optional so existing extraction fixtures without
    # the field parse cleanly.
    item_name: Optional[str] = None
    # PDF-MIRROR · Feb-2026 — verbatim SKU / part number when the
    # PDF prints one in its own column (distinct from the short
    # ``item_name``). Nullable so pre-MIRROR extraction fixtures
    # continue to parse.
    sku: Optional[str] = None
    cost_rate: Optional[float] = None
    qty: Optional[float] = None
    tax_pct: Optional[float] = None
    # PDF-MIRROR · Feb-2026 — verbatim per-line TAX AMOUNT
    # (dollars) when the PDF prints a per-line tax column.
    # Distinct from ``tax_pct`` (rate) — some vendors show both,
    # some show only the amount. Nullable so pre-MIRROR fixtures
    # continue to parse.
    tax_line: Optional[float] = None
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
    # PDF-FIX-C · Feb-2026 — verbatim tax RATE captured from the
    # source PDF when the invoice prints one (e.g., "6.25%" in a
    # dedicated tax row). Stored as a percentage float — 6.25
    # means 6.25%, NOT 0.0625.  Kept as a sibling of
    # ``tax_total`` (the dollar amount).  Null when the PDF
    # shows only a tax amount without a rate.
    tax_rate: Optional[float] = None
    amount_paid: Optional[float] = None
    total_due: Optional[float] = None
    # PDFI-PAID-A · Feb-2026 — derived paid-status boolean. True when
    # STRICT ruling holds: ``amount_paid > 0`` AND ``total_due <= 0.01``
    # (floating-point tolerance for a nominal zero). Set by the
    # extractor (fast-path and vision path both compute it) so the
    # mapper + commit path downstream can promote an invoice to a
    # "paid" status without re-deriving the rule.  None when neither
    # input is present (operator still edits at preview).
    is_paid: Optional[bool] = None
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
    # Feb-2026 · PDF Importer Sub-phase B — additive structured
    # warnings alongside the legacy ``warnings: List[str]`` list.
    # Each entry is a dict with at minimum ``code`` (short machine
    # tag, e.g. ``"doc_date_missing"``), ``message`` (the same
    # human-readable string that also lands in ``warnings``), and
    # ``doc_position`` (1-indexed source_doc_index the warning
    # belongs to — used by Sub-phase E's per-row yellow-border
    # banner treatment per R8 · C ruling).  New entries land in
    # BOTH lists so consumers that still read ``warnings`` (Mongo
    # persistence, legacy router responses) keep working while
    # frontend banner code migrates to the structured list.
    structured_warnings: List[Dict[str, Any]] = []
    # PDF Importer Sub-phase D · Feb-2026 — additive tile-summary
    # block populated by :mod:`services.imports.pdf_tiled_extractor`
    # when the source PDF crosses the ``TILE_PAGE_THRESHOLD`` gate
    # (>36 pages). ``None`` for single-shot extractions to keep the
    # small-PDF happy path byte-identical and the response payload
    # slim. Shape::
    #
    #     {
    #         "total_pages": int,
    #         "tiles_used": int,
    #         "docs_pre_merge": int,
    #         "docs_post_merge": int,
    #         "cross_tile_merges": int,
    #         "warnings": [ {code, tile_index, message}, ... ],
    #     }
    tile_summary: Optional[Dict[str, Any]] = None
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
    # PDF Importer Sub-phase C · Feb-2026 — bumped from a two-
    # value enum ({"quote_in", "deferred_to_h4"}) to a three-value
    # one so payment receipts get their own commit lane instead of
    # a permanent H.4 deferral. When ``doc_kind == "payment_receipt"``
    # the mapper now populates ``payment_in`` and sets
    # ``mapped_target == "payment_in"``. ``deferred_to_h4`` remains
    # as a last-resort fallback for payment receipts whose data was
    # too malformed to build a payment doc from (e.g. no
    # ``amount_paid``, no customer resolution possible at all).
    mapped_target: Literal["quote_in", "payment_in", "deferred_to_h4"]

    # QuoteIn preview (None when doc_kind=payment_receipt).
    # Stored as a dict rather than a QuoteIn to keep the response
    # JSON-friendly + avoid a circular import from models.py at
    # schema-load time.
    quote_in: Optional[Dict[str, Any]] = None

    # PDF-C · Feb-2026 — Payment preview (None when
    # ``mapped_target != "payment_in"``). Dict shape mirrors the
    # ``db.payments`` document expected by commit_batch's
    # payment-write path — see :func:`services.imports.pdf_mapper.
    # _build_payment_in` for the canonical builder.
    payment_in: Optional[Dict[str, Any]] = None

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
