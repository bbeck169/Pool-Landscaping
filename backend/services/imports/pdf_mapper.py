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

    # ── Payment receipts skip QuoteIn generation ────────────
    if doc.doc_kind == "payment_receipt":
        report.mapped_target = "deferred_to_h4"
        if doc.amount_paid is not None:
            report.pending_payment_actions.append({
                "kind": "record_payment",
                "amount": doc.amount_paid,
                "paid_at": doc.paid_at.isoformat() if doc.paid_at else None,
                "payment_method": doc.payment_method,
                "payment_reference": doc.payment_reference,
                "resolved_by": "phase_h4_receipt_handler",
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
    quote_in: Dict[str, Any] = {
        "customer_id": customer_id_field,
        "customer_name": doc.customer_name,
        "title": doc.doc_number and f"Import #{doc.doc_number}" or "Imported document",
        "doc_type": doc_type,
        "doc_number": doc.doc_number,
        "doc_date": doc.doc_date.isoformat() if doc.doc_date else None,
        "line_items": wire_items,
        "tax_rate": 0.0,  # H.1 does NOT try to reverse-engineer the
                            # rate; the extractor's ``tax_total`` is
                            # captured in warnings for H.2 audit.
        "total_due": doc.total_due,
        "amount_paid": doc.amount_paid,
        "payment_method": doc.payment_method,
        "notes": doc.notes,
        "import_batch_id": batch_id,
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

    # Extractor warnings that surface tax / discrepancy audit
    # notes for H.2.
    if doc.tax_total is not None and doc.tax_total > 0:
        report.warnings.append(
            f"tax_total={doc.tax_total} present but tax_rate=0 on the "
            f"QuoteIn preview — Phase H.2 must reconcile before commit."
        )

    report.quote_in = quote_in
    return report
