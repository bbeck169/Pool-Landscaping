"""PDF-FIX-D · Feb-2026 — mapper verbatim preservation + commit
verbatim persistence + hardcoded ``tax_rate=0.0`` fix +
``line_total`` pass-through.

Locks the write-path contract shipped with PDF-FIX-D:

  1. Mapper's ``quote_in`` now surfaces ``tax_rate``,
     ``subtotal``, ``tax_total``, and
     ``imported_totals_verbatim=True`` in addition to the
     ``grand_total`` field PDF-FIX-A already added.
  2. Hardcoded ``tax_rate = 0.0`` on ``quote_in`` REPLACED
     with ``doc.tax_rate`` verbatim (falling back to 0.0
     only when the PDF didn't print a rate).
  3. ``_line_item_to_quote_shape()`` copies ``line_total``
     from the extractor into ``quote_in.line_items[i]`` —
     the mapper no longer drops the PDF's printed per-line
     total.  FE + commit paths read verbatim.
  4. Commit path (`_build_quote_doc_from_preview`) reads
     ``subtotal`` / ``tax_total`` / ``grand_total`` from
     ``quote_in`` verbatim rather than seeding ``0.0`` and
     letting ``_apply_totals`` recompute.  Sets
     ``imported_totals_verbatim=True`` on the persisted doc.
  5. ``_apply_totals`` GATED — when
     ``imported_totals_verbatim=True`` and the persisted
     ``total`` is non-zero, the recompute is SKIPPED.  Legacy
     paths (verbatim flag absent OR total == 0 sentinel for
     "no PDF totals available") still fall through to
     ``qty × unit_price`` recompute (matches every
     pre-PDF-FIX-D test).
  6. **No tenant tax-rate service** is called on the PDF path
     — the grep at recon confirmed no such service exists in
     this codebase, so the check is verified by absence
     rather than by mock spy.

All tests are unit-level against ``pdf_mapper`` +
``pdf_commit._build_quote_doc_from_preview`` +
``pdf_commit._apply_totals``.  End-to-end regression via
``test_pdf_import_multi_doc.py`` + ``test_task_h1_pdf_import.py``
(both re-run at PDF-FIX-D finalisation).
"""
from __future__ import annotations

import os
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import pytest
from dotenv import dotenv_values
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient


# ── Bootstrap DB config (mirrors test_pdf_mapper_grand_total) ──
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
def pdf_fix_d_customer(dbc, aquaterra_id):
    cid = f"cust-pdf-fix-d-{uuid.uuid4().hex[:12]}"
    dbc.customers.insert_one({
        "id": cid,
        "tenant_id": aquaterra_id,
        "name": "PDF-FIX-D Test Customer",
        "email": "pdffixd@example.com",
        "phone": "555-0201",
        "address": "1 PDF Fix D Ln, Testville AZ 00001",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "is_active": True,
    })
    yield cid
    dbc.customers.delete_one({"id": cid})


def _make_doc(
    *,
    subtotal: float | None = 400.00,
    tax_total: float | None = 24.50,
    tax_rate: float | None = 6.13,
    grand_total: float | None = 424.50,
    line_total: float | None = 400.00,
    customer_name: str = "PDF-FIX-D Test Customer",
):
    """Build an ``ExtractedDocument`` covering all the PDF-FIX-D
    fields the mapper must now preserve."""
    from services.imports.extraction_schema import (
        ExtractedDocument, ExtractedLineItem,
    )
    return ExtractedDocument(
        doc_kind="invoice",
        source_page_range=[1, 1],
        customer_name=customer_name,
        doc_number=f"INV-PFD-{uuid.uuid4().hex[:8]}",
        doc_date=date(2026, 2, 1),
        line_items=[
            ExtractedLineItem(
                description="Pool service — monthly",
                item_name="POOL-MO",
                qty=1.0,
                cost_rate=400.00,
                line_total=line_total,
            ),
        ],
        subtotal=subtotal,
        tax_total=tax_total,
        tax_rate=tax_rate,
        grand_total=grand_total,
        total_due=grand_total,
    )


async def _run_mapper(doc, *, adb, aquaterra_id):
    from services.imports.pdf_mapper import map_extracted_to_quote_in
    batch_id = f"bat-pdf-fix-d-{uuid.uuid4().hex[:12]}"
    return await map_extracted_to_quote_in(
        doc,
        db=adb,
        tenant_id=aquaterra_id,
        batch_id=batch_id,
        operator_user={"id": "admin-pdf-fix-d", "role": "admin"},
        source_doc_index=0,
    )


# ══════════════════════════════════════════════════════════════
# Mapper contract (a) - (f) — quote_in shape
# ══════════════════════════════════════════════════════════════

@pytest.mark.anyio
async def test_a_mapper_preserves_tax_subtotal_tax_rate_verbatim(
    adb, aquaterra_id, pdf_fix_d_customer,
):
    """(a) Extractor emits tax_total=24.50 + subtotal=400.00 +
    tax_rate=6.13 → mapper's quote_in has all three verbatim.
    """
    doc = _make_doc(
        subtotal=400.00, tax_total=24.50, tax_rate=6.13,
        grand_total=424.50,
    )
    report = await _run_mapper(doc, adb=adb, aquaterra_id=aquaterra_id)
    q = report.quote_in
    assert q is not None
    assert q["subtotal"] == 400.00
    assert q["tax_total"] == 24.50
    assert q["tax_rate"] == 6.13
    assert q["grand_total"] == 424.50


@pytest.mark.anyio
async def test_b_mapper_tax_rate_not_clobbered_to_zero(
    adb, aquaterra_id, pdf_fix_d_customer,
):
    """(b) Extractor emits tax_rate=6.25 → NOT clobbered to 0.0
    in quote_in (rulings §hardcoded-fix). The pre-PDF-FIX-D
    hardcoded ``0.0`` silently destroyed the extractor's rate.
    """
    doc = _make_doc(tax_rate=6.25)
    report = await _run_mapper(doc, adb=adb, aquaterra_id=aquaterra_id)
    assert report.quote_in["tax_rate"] == 6.25, (
        "mapper must NOT overwrite the extractor's tax_rate; "
        "the hardcoded 0.0 default is now gated behind a "
        "``doc.tax_rate is None`` check"
    )


@pytest.mark.anyio
async def test_c_mapper_tax_rate_none_falls_back_to_zero(
    adb, aquaterra_id, pdf_fix_d_customer,
):
    """(c) Extractor emits tax_rate=None → quote_in.tax_rate = 0.0
    (existing default for missing; backwards compat with quotes
    router which requires float).
    """
    doc = _make_doc(tax_rate=None)
    report = await _run_mapper(doc, adb=adb, aquaterra_id=aquaterra_id)
    assert report.quote_in["tax_rate"] == 0.0


@pytest.mark.anyio
async def test_d_line_total_pass_through_verbatim(
    adb, aquaterra_id, pdf_fix_d_customer,
):
    """(d) Line item with line_total=100.00 from extractor →
    mapper quote_in.line_items[i].line_total = 100.00 (not
    overwritten by qty × unit_price math).  Guards against
    silent recompute drift on discounted / rounded PDF lines.
    """
    doc = _make_doc(line_total=100.00)
    report = await _run_mapper(doc, adb=adb, aquaterra_id=aquaterra_id)
    li = report.quote_in["line_items"][0]
    assert li["line_total"] == 100.00, (
        "line_total must be preserved verbatim from the "
        "extractor; recomputing as qty × unit_price would "
        "silently lose PDF-printed discount / rounding signal"
    )


@pytest.mark.anyio
async def test_e_line_total_none_stays_none(
    adb, aquaterra_id, pdf_fix_d_customer,
):
    """(e) Line item with line_total=None from extractor →
    mapper writes None (no compute).  FE + commit paths handle
    the None sentinel with their own qty×unit_price fallback.
    """
    doc = _make_doc(line_total=None)
    report = await _run_mapper(doc, adb=adb, aquaterra_id=aquaterra_id)
    li = report.quote_in["line_items"][0]
    assert li["line_total"] is None


@pytest.mark.anyio
async def test_f_imported_totals_verbatim_flag_on_all_pdf_rows(
    adb, aquaterra_id, pdf_fix_d_customer,
):
    """(f) quote_in.imported_totals_verbatim = True on every
    row from the PDF path. Signals downstream to skip
    recompute + reports to trust the persisted totals.
    """
    doc = _make_doc()
    report = await _run_mapper(doc, adb=adb, aquaterra_id=aquaterra_id)
    assert report.quote_in["imported_totals_verbatim"] is True


# ══════════════════════════════════════════════════════════════
# Commit contract (g) — _build_quote_doc_from_preview
# ══════════════════════════════════════════════════════════════

def test_g_commit_persists_verbatim_totals_from_quote_in():
    """(g) Commit's _build_quote_doc_from_preview reads the
    extractor's authoritative totals from quote_in verbatim.
    No math on the write path.
    """
    from services.imports.pdf_commit import _build_quote_doc_from_preview
    preview = {
        "source_doc_index": 0,
        "quote_in": {
            "customer_id": "cust-x",
            "customer_name": "Verbatim Test",
            "title": "Import #INV-VERBATIM-001",
            "doc_type": "invoice",
            "doc_number": "INV-VERBATIM-001",
            "line_items": [
                {"item_name": "SKU", "description": "widget",
                 "quantity": 4, "unit_price": 25.0,
                 "line_total": 89.99},  # <- deliberate mismatch:
                                         # qty × price = 100.00 but
                                         # PDF printed 89.99 (discount).
            ],
            "tax_rate": 6.25,
            "subtotal": 89.99,
            "tax_total": 5.62,
            "grand_total": 95.61,
            "total_due": 95.61,
            "imported_totals_verbatim": True,
        },
    }
    doc = _build_quote_doc_from_preview(
        preview=preview,
        batch={"id": "b1"},
        tenant_id="t1",
        operator={"id": "u1", "role": "admin"},
        commit_at=datetime.now(timezone.utc).isoformat(),
    )
    assert doc["subtotal"] == 89.99
    assert doc["tax"] == 5.62
    assert doc["total"] == 95.61
    assert doc["tax_rate"] == 6.25
    assert doc["imported_totals_verbatim"] is True
    # Verbatim line_total on the persisted line item.
    assert doc["line_items"][0]["line_total"] == 89.99


def test_h_apply_totals_skipped_when_verbatim_flag_set():
    """(h) _apply_totals is a no-op when
    imported_totals_verbatim=True + total != 0.0.  Guards
    against the recompute silently rewriting the extractor's
    authoritative values.  Legacy path (flag absent / False,
    OR total == 0 sentinel) still recomputes.
    """
    from services.imports.pdf_commit import _apply_totals

    # (h.1) Verbatim path — recompute skipped.
    doc_verbatim = {
        "subtotal": 89.99,
        "tax": 5.62,
        "total": 95.61,
        "tax_rate": 6.25,
        "imported_totals_verbatim": True,
        "line_items": [
            # Line-item math would give subtotal=100.00; the
            # verbatim gate must prevent that from clobbering
            # the extractor's 89.99.
            {"quantity": 4, "unit_price": 25.0},
        ],
    }
    _apply_totals(doc_verbatim)
    assert doc_verbatim["subtotal"] == 89.99, (
        "_apply_totals must SKIP recompute when "
        "imported_totals_verbatim=True + non-zero total"
    )
    assert doc_verbatim["tax"] == 5.62
    assert doc_verbatim["total"] == 95.61

    # (h.2) Legacy path — no flag, recompute drives totals.
    doc_legacy = {
        "subtotal": 0.0,
        "tax": 0.0,
        "total": 0.0,
        "tax_rate": 10.0,
        "line_items": [
            {"quantity": 2, "unit_price": 50.0},
        ],
    }
    _apply_totals(doc_legacy)
    assert doc_legacy["subtotal"] == 100.0
    assert doc_legacy["tax"] == 10.0
    assert doc_legacy["total"] == 110.0

    # (h.3) Flag set but total is 0 sentinel → fall through
    # to recompute so a "no PDF totals available" case still
    # produces a valid persisted doc.
    doc_sentinel = {
        "subtotal": 0.0,
        "tax": 0.0,
        "total": 0.0,
        "tax_rate": 0.0,
        "imported_totals_verbatim": True,
        "line_items": [
            {"quantity": 1, "unit_price": 42.0},
        ],
    }
    _apply_totals(doc_sentinel)
    assert doc_sentinel["subtotal"] == 42.0, (
        "verbatim flag + total=0.0 sentinel must fall through "
        "to recompute so the doc still gets sensible totals"
    )
