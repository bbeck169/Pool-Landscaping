"""PDF-FIX-A · Feb-2026 — mapper ``grand_total`` field on quote_in.

Locks the contract that the PDF-invoice mapper now surfaces
``grand_total`` on its ``quote_in`` preview so the FE Preview
table can render the source PDF's stated total (the "Total" /
"Total Due" line) instead of falling back to ``total_due`` —
which is $0.00 on fully-paid invoices and produced the
"$0.00 for a paid $400 invoice" display regression.

Priority chain the mapper implements
────────────────────────────────────
1. ``extracted.grand_total`` when present — including a verbatim
   ``0.0`` for legitimately-waived invoices (rulings §1: a
   $0.00 extraction is a valid value, NOT a fallback trigger —
   ``!= None`` check, not truthiness).
2. Fall back to ``extracted.total_due`` when ``grand_total`` is
   ``None``.
3. ``None`` when both are absent — the FE format helper renders
   this via its own ``0``-terminated ``??`` chain (see
   ``pdfImportTotalColumn.test.jsx``).

Also asserts the pre-A ``quote_in`` shape stays a strict
superset — no siblings dropped, no field renamed. Backwards
compat matters because ``import_batch_id`` + ``total_due`` +
``line_items`` are already consumed by Phase H.2 commit and the
duplicate pre-flight query in ``pdf-invoice-import-preview.test.jsx``.

The mapper's fuzzy-match customer path is exercised via the
``adb`` + ``h1_customer`` fixtures reused from
``test_task_h1_pdf_import.py`` — we skip the vision-extractor
call by building ``ExtractedDocument`` values directly. This
isolates the mapper's ``quote_in`` shape from the
``pdf_invoice_extractor`` mock plumbing.
"""
from __future__ import annotations

import os
import uuid
from datetime import date, datetime, timezone

import pytest
from dotenv import dotenv_values
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient

from pathlib import Path


# ── Bootstrap DB config (mirrors test_task_h1_pdf_import.py) ──
_TEST_DIR = Path(__file__).resolve().parent
_BE = dotenv_values(_TEST_DIR.parent / ".env")
MONGO_URL = _BE.get("MONGO_URL") or os.environ.get("MONGO_URL")
DB_NAME = _BE.get("DB_NAME") or os.environ.get("DB_NAME")


@pytest.fixture(scope="module")
def dbc():
    return MongoClient(MONGO_URL)[DB_NAME]


@pytest.fixture()
def adb():
    return AsyncIOMotorClient(MONGO_URL)[DB_NAME]


@pytest.fixture(scope="module")
def aquaterra_id(dbc):
    return dbc.tenants.find_one({"slug": "aquaterra"}, {"id": 1})["id"]


@pytest.fixture(scope="module")
def h1_customer(dbc, aquaterra_id):
    """Seeded customer for fuzzy-match path — mirrors the
    ``h1_customer`` fixture in the H.1 regression file, kept
    module-local so this test file can run in isolation via
    ``pytest backend/tests/test_pdf_mapper_grand_total.py``."""
    cid = f"cust-pdf-fix-a-{uuid.uuid4().hex[:12]}"
    dbc.customers.insert_one({
        "id": cid,
        "tenant_id": aquaterra_id,
        "name": "PDF-FIX-A Test Customer",
        "email": "pdffixa@example.com",
        "phone": "555-0199",
        "address": "1 PDF Fix Ln, Testville AZ 00001",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "is_active": True,
    })
    yield cid
    dbc.customers.delete_one({"id": cid})


def _make_doc(
    *,
    grand_total: float | None,
    total_due: float | None,
    customer_name: str = "PDF-FIX-A Test Customer",
    line_total: float = 400.00,
):
    """Build a minimal ``ExtractedDocument`` for the invoice branch.

    One line item so the empty-line-items guard doesn't short-
    circuit; ``customer_name`` matches the seeded fixture so the
    fuzzy-match branch takes the ``matched`` path and no pending
    row is written to Mongo (keeps test hermetic).
    """
    from services.imports.extraction_schema import (
        ExtractedDocument, ExtractedLineItem,
    )
    return ExtractedDocument(
        doc_kind="invoice",
        source_page_range=[1, 1],
        customer_name=customer_name,
        doc_number=f"INV-PFA-{uuid.uuid4().hex[:8]}",
        doc_date=date(2026, 2, 1),
        line_items=[
            ExtractedLineItem(
                description="Pool service — monthly",
                item_name="POOL-MO",
                qty=1.0,
                cost_rate=line_total,
                line_total=line_total,
            ),
        ],
        subtotal=line_total,
        tax_total=0.0,
        grand_total=grand_total,
        total_due=total_due,
    )


async def _run_mapper(doc, *, adb, aquaterra_id):
    """Invoke ``map_extracted_to_quote_in`` with a fresh batch_id
    + minimal admin user context."""
    from services.imports.pdf_mapper import map_extracted_to_quote_in
    batch_id = f"bat-pdf-fix-a-{uuid.uuid4().hex[:12]}"
    return await map_extracted_to_quote_in(
        doc,
        db=adb,
        tenant_id=aquaterra_id,
        batch_id=batch_id,
        operator_user={"id": "admin-pdf-fix-a", "role": "admin"},
        source_doc_index=0,
    )


# ══════════════════════════════════════════════════════════════
# Acceptance cases (5) — from PDF-FIX-A dispatch brief.
# ══════════════════════════════════════════════════════════════

@pytest.mark.anyio
async def test_grand_total_present_wins_over_total_due(
    adb, aquaterra_id, h1_customer,
):
    """Case (a) — extractor emits ``grand_total = 400.00`` +
    ``total_due = 0.00`` (fully-paid invoice).  ``quote_in``
    should surface ``grand_total = 400.00``; ``total_due`` stays
    as a sibling for downstream commit compatibility.
    """
    doc = _make_doc(grand_total=400.00, total_due=0.00)
    report = await _run_mapper(doc, adb=adb, aquaterra_id=aquaterra_id)
    assert report.customer_resolution == "matched"
    assert report.quote_in is not None
    assert report.quote_in["grand_total"] == 400.00, (
        "grand_total must win over total_due when present"
    )
    # Sibling preserved for backwards compat.
    assert report.quote_in["total_due"] == 0.00


@pytest.mark.anyio
async def test_grand_total_zero_preserved_verbatim(
    adb, aquaterra_id, h1_customer,
):
    """Case (b) — a legitimately-waived invoice
    (``grand_total = 0.0``) must be preserved verbatim on
    ``quote_in``, NOT trigger a fallback to ``total_due``.
    ``!= None`` check locked; rulings §1.
    """
    doc = _make_doc(grand_total=0.0, total_due=250.00, line_total=0.0)
    report = await _run_mapper(doc, adb=adb, aquaterra_id=aquaterra_id)
    assert report.quote_in is not None
    # If the mapper used truthiness (falsy 0.0 → fallback),
    # this would be 250.00 — that would silently
    # mis-report waived invoices as $250.00.  The contract
    # is: 0 is a real number, not "missing".
    assert report.quote_in["grand_total"] == 0.0, (
        "grand_total = 0.0 must be preserved verbatim, not "
        "trigger the total_due fallback"
    )
    assert report.quote_in["total_due"] == 250.00


@pytest.mark.anyio
async def test_grand_total_missing_falls_back_to_total_due(
    adb, aquaterra_id, h1_customer,
):
    """Case (c) — extractor ``grand_total = None`` +
    ``total_due = 250.00`` → ``quote_in.grand_total`` falls
    back to ``total_due`` so the FE still has a value to
    render. Fallback chain locked.
    """
    doc = _make_doc(grand_total=None, total_due=250.00)
    report = await _run_mapper(doc, adb=adb, aquaterra_id=aquaterra_id)
    assert report.quote_in is not None
    assert report.quote_in["grand_total"] == 250.00, (
        "grand_total should fall back to total_due when the "
        "extractor didn't emit a grand_total value"
    )


@pytest.mark.anyio
async def test_grand_total_and_total_due_both_missing(
    adb, aquaterra_id, h1_customer,
):
    """Case (d) — both extractor fields absent → mapper writes
    ``grand_total = None`` on ``quote_in``.  The FE renders this
    via its own ``??`` chain (falls through to ``$0.00``); the
    mapper contract is: never crash, never fabricate a value.
    """
    doc = _make_doc(grand_total=None, total_due=None)
    report = await _run_mapper(doc, adb=adb, aquaterra_id=aquaterra_id)
    assert report.quote_in is not None
    assert report.quote_in["grand_total"] is None
    assert report.quote_in["total_due"] is None


@pytest.mark.anyio
async def test_backwards_compat_quote_in_shape_preserved(
    adb, aquaterra_id, h1_customer,
):
    """Case (e) — every pre-PDF-FIX-A ``quote_in`` field is
    still present after the field-add.  Guards Phase H.2 commit
    readers + the duplicate pre-flight query + the FE preview
    columns (doc_number, doc_date, customer_name, line_items,
    total_due, amount_paid, payment_method) from silent
    breakage.
    """
    doc = _make_doc(grand_total=400.00, total_due=100.00)
    report = await _run_mapper(doc, adb=adb, aquaterra_id=aquaterra_id)
    assert report.quote_in is not None
    q = report.quote_in
    # Pre-A siblings — MUST all remain present.
    for field in (
        "customer_id", "customer_name", "title", "doc_type",
        "doc_number", "doc_date", "line_items", "tax_rate",
        "total_due", "amount_paid", "payment_method", "notes",
        "import_batch_id",
    ):
        assert field in q, f"{field} dropped from quote_in — regression"
    # New field.
    assert "grand_total" in q
    # doc_type stays as "invoice" for invoice doc_kind.
    assert q["doc_type"] == "invoice"
