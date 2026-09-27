"""Task H · Phase H.1 · Feb-2026 — PDF-to-QuoteIn mapper.

Converts an ``ExtractedDocument`` from the vision extractor into
a ``QuoteIn`` payload the Phase H.2 commit path can replay
against ``POST /quotes``. Also handles fuzzy customer resolution
(rapidfuzz ≥ 87) and defers payment receipts to the future
Phase H.4 handler.

Task H0 reuse — ``resolve_date_override`` is the sole authority
on ``created_at`` validation.  Its 400 on future / ancient dates
becomes a soft ``MapperReport.errors`` entry here (framework-
agnostic reuse per Task H0 § 8).
"""
from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, time, timezone
from typing import Any, Dict, List, Optional

from fastapi import HTTPException
from rapidfuzz import fuzz, process
from rapidfuzz.utils import default_process

from services.quotes.date_override import resolve_date_override

from .extraction_schema import ExtractedDocument, MapperReport


logger = logging.getLogger("imports.pdf_mapper")

# Task H.1 spec §Fuzzy-match threshold — Sub-phase A halt-report
# locked 87.  Feb-2026 · PDF Importer Sub-phase B · R3 ruling —
# relaxed to 80 (rapidfuzz 0-100 scale) after Aquaterra fixture
# review showed 87 was rejecting legitimate near-misses (typo
# families, transposed characters).  Below the threshold the
# mapper writes a pending_import_customers row instead of silently
# binding to a near-miss customer.
_FUZZY_THRESHOLD = 80

# Task H.1 spec §Response payload cap — 25 line items per doc.
_LINE_ITEM_CAP = 25


async def _fuzzy_match_customer(
    db, *, tenant_id: str, extracted_name: str,
) -> Optional[Dict[str, Any]]:
    """Return the best matching customer dict + score OR None.

    Uses ``rapidfuzz.token_sort_ratio`` (via ``default_process``
    for lower-case + punctuation strip) which handles the
    ``"Dianne LIoyd"`` (I-as-l typo) near-miss family cleanly.
    """
    cursor = db.customers.find(
        {"tenant_id": tenant_id, "is_active": {"$ne": False}},
        {"_id": 0, "id": 1, "name": 1, "email": 1, "phone": 1, "address": 1},
    )
    rows = await cursor.to_list(length=None)
    if not rows:
        return None

    choices = {r["id"]: (r.get("name") or "") for r in rows}
    best = process.extractOne(
        extracted_name, choices,
        scorer=fuzz.token_sort_ratio,
        processor=default_process,
    )
    if best is None:
        return None
    matched_name, score, matched_id = best
    if score < _FUZZY_THRESHOLD:
        return {"customer": None, "score": score, "candidate_id": matched_id,
                "candidate_name": matched_name}
    row = next((r for r in rows if r["id"] == matched_id), None)
    return {"customer": row, "score": score,
            "candidate_id": matched_id, "candidate_name": matched_name}


async def _insert_pending_customer(
    db, *, tenant_id: str, batch_id: str, extracted: ExtractedDocument,
) -> str:
    """Write a ``pending_import_customers`` row and return its id.
    Phase H.2's commit path validates no ``PENDING::`` prefix
    remains on any QuoteIn before committing to ``quotes``."""
    pending_id = str(uuid.uuid4())
    await db.pending_import_customers.insert_one({
        "id": pending_id,
        "tenant_id": tenant_id,
        "batch_id": batch_id,
        "extracted_customer_name": extracted.customer_name,
        "extracted_email": extracted.customer_email,
        "extracted_phone": extracted.customer_phone,
        "extracted_address": extracted.customer_address,
        "resolved_customer_id": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    return pending_id


def _line_item_to_quote_shape(li) -> Dict[str, Any]:
    """Map an ``ExtractedLineItem`` to the ``LineItem`` shape
    ``QuoteIn`` expects.  ``LineItem`` schema (models.py:335) has
    fields ``description``, ``quantity``, ``unit_price``, +
    optional taxonomy — we populate the numeric fields from the
    extractor with sensible fallbacks.

    Feb-2026 · PDF Importer Sub-phase B — copy through
    ``item_name`` from the extractor when populated so the
    preview-table + downstream commit path can render the short
    SKU alongside the long description.  Defaults to ``None`` for
    grandfather compat with fixtures that pre-date Sub-phase A's
    ``ExtractedLineItem.item_name`` field.

    PDF-FIX-D · Feb-2026 — ``line_total`` now passes through
    verbatim so the commit path can preserve the PDF's printed
    per-line total instead of recomputing ``qty × unit_price``.
    A PDF's printed line_total may reflect discounts / rounding
    the extractor cannot see; recomputing silently loses that
    signal.  ``None`` when the extractor didn't capture one —
    downstream consumers (FE display, commit path) fall back to
    ``qty × unit_price``.
    """
    qty = li.qty if li.qty is not None else 1.0
    unit_price = li.cost_rate
    if unit_price is None and li.line_total is not None and qty:
        # Best-effort back-calc from the line total when the
        # rate wasn't visible on the invoice.
        unit_price = li.line_total / qty if qty else li.line_total
    return {
        "item_name": li.item_name,
        "description": li.description,
        "quantity": qty,
        "unit_price": float(unit_price) if unit_price is not None else 0.0,
        # PDF-FIX-D · Feb-2026 — verbatim pass-through from
        # extractor.  Never overwritten by qty × unit_price math.
        "line_total": float(li.line_total) if li.line_total is not None else None,
    }


# ═════════════════════════════════════════════════════════════════════
# PDF Importer Sub-phase C · Feb-2026 — payment-preview builder +
# shared helpers.
# ═════════════════════════════════════════════════════════════════════
async def _resolve_customer_or_pending(
    doc: ExtractedDocument, *, db, tenant_id: str, batch_id: str,
    report: MapperReport,
) -> str:
    """Shared customer-resolution used by the payment_receipt path
    (PDF-C). Returns the resolved customer_id or a ``PENDING::``
    sentinel. Side-effects the ``report``'s customer_resolution /
    matched_customer_id / match_score / pending_customer_id fields
    to mirror what the invoice path writes.

    Kept as a separate helper so the invoice-path customer
    resolution block stays byte-identical for the existing H.1
    regression suite — this new helper only owns the payment lane.
    """
    if doc.customer_name:
        match = await _fuzzy_match_customer(
            db, tenant_id=tenant_id, extracted_name=doc.customer_name,
        )
        if match and match["customer"]:
            report.customer_resolution = "matched"
            report.matched_customer_id = match["customer"]["id"]
            report.match_score = float(match["score"])
            return match["customer"]["id"]
        pending_id = await _insert_pending_customer(
            db, tenant_id=tenant_id, batch_id=batch_id, extracted=doc,
        )
        report.customer_resolution = "pending"
        report.pending_customer_id = pending_id
        if match:
            report.match_score = float(match["score"])
            report.warnings.append(
                f"below-threshold near-match: score={match['score']:.1f} "
                f"candidate={match['candidate_name']!r}"
            )
        return f"PENDING::{pending_id}"
    # No customer_name on the payment receipt — write a pending
    # row so the commit path can require operator resolution.
    pending_id = await _insert_pending_customer(
        db, tenant_id=tenant_id, batch_id=batch_id, extracted=doc,
    )
    report.customer_resolution = "pending"
    report.pending_customer_id = pending_id
    return f"PENDING::{pending_id}"


def _emit_warning(report: MapperReport, *, code: str, message: str) -> None:
    """Push a structured warning into ``MapperReport.warnings``.
    Kept small on purpose — the structured-warnings field lives on
    the ExtractionResult layer (Sub-phase B), the mapper layer just
    accumulates human-readable strings for the H.1 response body."""
    report.warnings.append(f"[{code}] {message}")


def _build_payment_in(
    *, doc: ExtractedDocument, customer_id_field: str, batch_id: str,
) -> Dict[str, Any]:
    """Shape the payment preview dict the commit path consumes.

    Mirrors ``db.payments`` (see stripe_billing_history_sync for
    the canonical schema) plus PDF-import provenance fields.
    ``invoice_id`` is deliberately absent here — the commit path
    does the best-effort ``db.quotes`` lookup by ``doc_number``
    and stamps it if a match exists.
    """
    return {
        "customer_id": customer_id_field,
        "customer_name": doc.customer_name,
        # Payment receipts inherit doc_number from the receipt itself;
        # commit uses it to look up the matching invoice number.
        "doc_number": doc.doc_number,
        # ``paid_at`` preferred; falls back to ``doc_date``; commit
        # falls back to ``now`` when both are absent (last-resort).
        "paid_at": (
            doc.paid_at.isoformat() if doc.paid_at
            else (doc.doc_date.isoformat() if doc.doc_date else None)
        ),
        "amount_paid": doc.amount_paid,
        "payment_method": doc.payment_method,
        "payment_reference": doc.payment_reference,
        "notes": doc.notes,
        "import_batch_id": batch_id,
    }


async def map_extracted_to_quote_in(
    doc: ExtractedDocument,
    *,
    db,
    tenant_id: str,
    batch_id: str,
    operator_user: Dict[str, Any],
    source_doc_index: int,
) -> MapperReport:
    """Task H · Phase H.1 mapper.  See module docstring."""
    report = MapperReport(
        source_doc_index=source_doc_index,
        doc_kind=doc.doc_kind,
        mapped_target="quote_in",
        customer_resolution="unresolved",
    )

    # ── Payment receipts — build a payment_in preview ───────
    # PDF Importer Sub-phase C · Feb-2026 — payment receipts now
    # take their own commit lane (``mapped_target = "payment_in"``)
    # instead of a permanent H.4 deferral. Do the same customer-
    # resolution dance as the invoice path so ``payment_in`` lands
    # with a resolved (or PENDING::) customer_id ready for the
    # commit-side ``db.payments`` write.
    if doc.doc_kind == "payment_receipt":
        customer_id_field = await _resolve_customer_or_pending(
            doc, db=db, tenant_id=tenant_id, batch_id=batch_id,
            report=report,
        )
        # Payment-specific data-quality warnings (per PDF-C
        # ruling #7 — warn, do NOT block the commit).
        if doc.amount_paid is None:
            _emit_warning(
                report, code="amount_paid_missing",
                message=(
                    "amount_paid missing on payment receipt — "
                    "the commit will store a $0 payment placeholder."
                ),
            )
        if doc.paid_at is None and doc.doc_date is None:
            _emit_warning(
                report, code="paid_at_missing",
                message=(
                    "paid_at and doc_date both missing on payment "
                    "receipt — commit will stamp paid_at=now."
                ),
            )
        report.mapped_target = "payment_in"
        report.payment_in = _build_payment_in(
            doc=doc, customer_id_field=customer_id_field,
            batch_id=batch_id,
        )
        # H.2 pending_payment_actions kept for backward compat —
        # older readers (audit trail) still consume this.
        if doc.amount_paid is not None:
            report.pending_payment_actions.append({
                "kind": "record_payment",
                "amount": doc.amount_paid,
                "paid_at": doc.paid_at.isoformat() if doc.paid_at else None,
                "payment_method": doc.payment_method,
                "payment_reference": doc.payment_reference,
                "resolved_by": "pdf_c_payment_commit_path",
            })
        return report

    # ── Reject empty line-item docs ─────────────────────────
    if not doc.line_items:
        report.errors.append(
            "line_items empty — cannot map to QuoteIn"
        )
        return report

    # ── Customer resolution ─────────────────────────────────
    customer_id_field: Optional[str] = None
    if doc.customer_name:
        match = await _fuzzy_match_customer(
            db, tenant_id=tenant_id, extracted_name=doc.customer_name,
        )
        if match and match["customer"]:
            report.customer_resolution = "matched"
            report.matched_customer_id = match["customer"]["id"]
            report.match_score = float(match["score"])
            customer_id_field = match["customer"]["id"]
        else:
            # Below-threshold or empty customers collection →
            # write a pending row.
            pending_id = await _insert_pending_customer(
                db, tenant_id=tenant_id, batch_id=batch_id, extracted=doc,
            )
            report.customer_resolution = "pending"
            report.pending_customer_id = pending_id
            if match:
                report.match_score = float(match["score"])
                report.warnings.append(
                    f"below-threshold near-match: score={match['score']:.1f} "
                    f"candidate={match['candidate_name']!r}"
                )
            customer_id_field = f"PENDING::{pending_id}"
    else:
        # No customer_name on the document — extractor should
        # already have emitted a warning; the mapper produces
        # a pending row regardless so H.2 can require operator
        # resolution before commit.
        pending_id = await _insert_pending_customer(
            db, tenant_id=tenant_id, batch_id=batch_id, extracted=doc,
        )
        report.customer_resolution = "pending"
        report.pending_customer_id = pending_id
        customer_id_field = f"PENDING::{pending_id}"

    # ── Date override via Task H0 helper ───────────────────
    created_at_dt: Optional[datetime] = None
    if doc.doc_date is not None:
        # Task H0's resolve_date_override wants a ``datetime``
        # (not a ``date``); combine at UTC midnight — same
        # convention the H0 curl smoke uses.
        created_at_dt = datetime.combine(
            doc.doc_date, time(hour=0, minute=0),
            tzinfo=timezone.utc,
        )
        try:
            resolve_date_override(
                created_at_dt,
                user=operator_user,
                tenant_id=tenant_id,
                field_name="created_at",
                entity_kind=doc.doc_kind,
                entity_id=f"pending-import::{batch_id}::{source_doc_index}",
                log_level="warn",
            )
        except HTTPException as exc:
            # Task H0 raises 400 on future / ancient dates —
            # record it and drop this doc from the batch.
            detail = exc.detail or {}
            err_code = detail.get("error") if isinstance(detail, dict) else str(detail)
            report.errors.append(
                f"created_at override rejected: {err_code} "
                f"(doc_date={doc.doc_date.isoformat()})"
            )
            return report

    # ── Line items with truncation ─────────────────────────
    all_items = [_line_item_to_quote_shape(li) for li in doc.line_items]
    if len(all_items) > _LINE_ITEM_CAP:
        report.truncated = True
        report.warnings.append(
            f"line_items truncated in response preview "
            f"({len(all_items)} → {_LINE_ITEM_CAP}); full list retained "
            f"server-side for Phase H.2 commit."
        )
        wire_items = all_items[:_LINE_ITEM_CAP]
    else:
        wire_items = all_items

    # ── Doc type mapping ───────────────────────────────────
    doc_type = "invoice" if doc.doc_kind == "invoice" else "quote"

    # ── Assemble QuoteIn dict ──────────────────────────────
    # Feb-2026 · PDF Importer Sub-phase B — the preview-table
    # consumer in PdfInvoiceImportPage.jsx reads five extractor
    # fields directly off the mapper's ``quote_in`` output:
    # doc_number, doc_date, customer_name, total_due, amount_paid,
    # payment_method.  Pre-Sub-phase B those columns rendered "—"
    # because the fields weren't copied through — the extractor
    # captured them but the mapper's ``quote_in`` dict didn't
    # surface them.  Sub-phase E owns the preview-table columns
    # themselves; Sub-phase B ships the strict-superset data
    # payload so E has something to render.
    # PDF-FIX-A · Feb-2026 — surface ``grand_total`` on the quote_in
    # preview so the FE Preview table can render the invoice's stated
    # total (the "Total" or "Total Due" line on the PDF) instead of
    # falling back to ``total_due`` — which is $0.00 on fully-paid
    # invoices and produced the "$0.00 for a paid $400 invoice"
    # display regression.  Priority chain: prefer the extractor's
    # ``grand_total`` when present (including verbatim $0.00 for
    # legitimately-waived invoices), else fall back to
    # ``total_due``.  ``total_due`` is kept as a sibling field
    # because downstream commit + audit logic already reads it.
    # ``!= None`` check (not truthiness) so ``grand_total = 0.0``
    # is preserved verbatim per PDF-FIX rulings §1.
    grand_total_value = (
        doc.grand_total if doc.grand_total is not None else doc.total_due
    )
    quote_in: Dict[str, Any] = {
        "customer_id": customer_id_field,
        "customer_name": doc.customer_name,
        "title": doc.doc_number and f"Import #{doc.doc_number}" or "Imported document",
        "doc_type": doc_type,
        "doc_number": doc.doc_number,
        "doc_date": doc.doc_date.isoformat() if doc.doc_date else None,
        "line_items": wire_items,
        # PDF-FIX-D · Feb-2026 — tax_rate now passes through
        # verbatim from the extractor (was hardcoded 0.0 pre-D).
        # Falls back to 0.0 only when the PDF didn't print a rate.
        # ``tax_rate`` is a PERCENTAGE (6.25 == 6.25%) per PDF-FIX-C
        # schema.
        "tax_rate": (
            float(doc.tax_rate) if doc.tax_rate is not None else 0.0
        ),
        # PDF-FIX-D · Feb-2026 — subtotal + tax_total now surface
        # on quote_in verbatim so commit can persist them without
        # re-derivation.  Both may be None when the PDF didn't
        # print them; commit path falls back to line-item recompute
        # only when the ``imported_totals_verbatim`` flag is False
        # OR the values are None.
        "subtotal": doc.subtotal,
        "tax_total": doc.tax_total,
        "grand_total": grand_total_value,
        "total_due": doc.total_due,
        "amount_paid": doc.amount_paid,
        "payment_method": doc.payment_method,
        "notes": doc.notes,
        "import_batch_id": batch_id,
        # PDF-FIX-D · Feb-2026 — provenance flag. Signals to
        # downstream commit + read paths + reports that these
        # totals were extracted from a PDF and should NOT be
        # re-derived (tax_rate × subtotal math would silently
        # drift the persisted numbers away from the PDF the
        # operator uploaded).
        "imported_totals_verbatim": True,
    }
    if created_at_dt is not None:
        quote_in["created_at"] = created_at_dt.isoformat()
    if doc.due_date is not None:
        quote_in["due_date"] = doc.due_date.isoformat()

    # H.2 pending payment action — set when an invoice arrived
    # pre-paid (rare) or with an explicit paid_at.
    if doc.doc_kind == "invoice" and doc.paid_at is not None:
        report.pending_payment_actions.append({
            "kind": "record_payment",
            "amount": doc.amount_paid if doc.amount_paid is not None else doc.grand_total,
            "paid_at": doc.paid_at.isoformat(),
            "payment_method": doc.payment_method,
            "payment_reference": doc.payment_reference,
            "resolved_by": "phase_h2_commit_path",
        })

    # PDF-FIX-D · Feb-2026 — the old "tax_total present but
    # tax_rate=0" warning is stale.  ``tax_rate`` is now
    # preserved verbatim (see the quote_in construction above),
    # so a mismatch there is no longer a mapper concern — the
    # extractor's ``_check_totals_consistency`` handles the
    # cross-field reconciliation and logs a warning if
    # ``subtotal + tax_total != grand_total``.  We no longer
    # emit a mapper-side warning for the same signal.

    report.quote_in = quote_in
    return report
