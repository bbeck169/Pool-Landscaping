"""PDF-MIRROR · Feb-2026 — line-item verbatim preservation.

Locks the contract that ``pdf_mapper._line_item_to_quote_shape``
passes EVERY extractor field through to the ``quote_in`` line-
item entry without truncation, silent drop, or re-derivation:

  * ``description`` — verbatim including embedded ``\\n`` newlines.
  * ``quantity`` — verbatim.
  * ``unit_price`` — verbatim, back-calc'd from ``line_total``
    only when the extractor didn't capture a rate.
  * ``line_total`` — verbatim from the PDF (may reflect PDF-side
    discounts / rounding invisible to naive qty × price math).
  * ``sku`` — verbatim when the PDF prints a dedicated column.
  * ``tax_pct`` — per-line tax rate verbatim.
  * ``tax_line`` — per-line tax dollar amount verbatim.

Plus the ``line_items_preserved_verbatim: true`` sentinel on
``quote_in`` so downstream (commit, reports, admin edits) can
opt out of re-deriving line-item math.
"""
from __future__ import annotations

import os
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from dotenv import dotenv_values
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient


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
def mirror_customer(dbc, aquaterra_id):
    cid = f"cust-mirror-{uuid.uuid4().hex[:12]}"
    dbc.customers.insert_one({
        "id": cid,
        "tenant_id": aquaterra_id,
        "name": "PDF-MIRROR Test Customer",
        "email": "mirror@example.com",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "is_active": True,
    })
    yield cid
    dbc.customers.delete_one({"id": cid})


def _make_doc(*, line_items):
    from services.imports.extraction_schema import ExtractedDocument
    return ExtractedDocument(
        doc_kind="invoice",
        source_page_range=[1, 1],
        customer_name="PDF-MIRROR Test Customer",
        doc_number=f"INV-MIR-{uuid.uuid4().hex[:8]}",
        doc_date=date(2026, 2, 5),
        line_items=line_items,
        subtotal=100.0, tax_total=6.25, grand_total=106.25,
    )


async def _run_mapper(doc, *, adb, aquaterra_id):
    from services.imports.pdf_mapper import map_extracted_to_quote_in
    batch_id = f"bat-mirror-{uuid.uuid4().hex[:12]}"
    return await map_extracted_to_quote_in(
        doc, db=adb, tenant_id=aquaterra_id, batch_id=batch_id,
        operator_user={"id": "admin-mirror", "role": "admin"},
        source_doc_index=0,
    )


# ══════════════════════════════════════════════════════════════
# 1. Multi-line description preserved verbatim (with \n)
# ══════════════════════════════════════════════════════════════
@pytest.mark.anyio
async def test_multi_line_description_preserves_newlines(
    adb, aquaterra_id, mirror_customer,
):
    from services.imports.extraction_schema import ExtractedLineItem
    multi_line = (
        "Chlorine 4-lb tablets\n"
        "  delivered on 3/12 during weekly service\n"
        "  charged at 2 cases"
    )
    doc = _make_doc(line_items=[
        ExtractedLineItem(
            description=multi_line, item_name="CL-4LB",
            qty=2.0, cost_rate=50.0, line_total=100.0,
        ),
    ])
    report = await _run_mapper(doc, adb=adb, aquaterra_id=aquaterra_id)
    assert report.quote_in is not None
    items = report.quote_in["line_items"]
    assert len(items) == 1
    assert items[0]["description"] == multi_line
    # \n round-trips.
    assert "\n" in items[0]["description"]
    assert items[0]["description"].count("\n") == 2


# ══════════════════════════════════════════════════════════════
# 2. Long description (>200 chars) NOT truncated
# ══════════════════════════════════════════════════════════════
@pytest.mark.anyio
async def test_long_description_not_truncated(
    adb, aquaterra_id, mirror_customer,
):
    from services.imports.extraction_schema import ExtractedLineItem
    long_desc = "A" * 512 + " — sentinel"  # 523 chars total
    doc = _make_doc(line_items=[
        ExtractedLineItem(
            description=long_desc, item_name="LONG-1",
            qty=1.0, cost_rate=100.0, line_total=100.0,
        ),
    ])
    report = await _run_mapper(doc, adb=adb, aquaterra_id=aquaterra_id)
    items = report.quote_in["line_items"]
    # Byte-identical round-trip — no truncation, no ellipsis.
    assert items[0]["description"] == long_desc
    assert len(items[0]["description"]) == 523
    assert items[0]["description"].endswith(" — sentinel")


# ══════════════════════════════════════════════════════════════
# 3. sku field preserved
# ══════════════════════════════════════════════════════════════
@pytest.mark.anyio
async def test_sku_field_preserved(
    adb, aquaterra_id, mirror_customer,
):
    from services.imports.extraction_schema import ExtractedLineItem
    doc = _make_doc(line_items=[
        ExtractedLineItem(
            description="Pool skimmer replacement",
            item_name="Skimmer", sku="PN-8842-XL",
            qty=1.0, cost_rate=100.0, line_total=100.0,
        ),
    ])
    report = await _run_mapper(doc, adb=adb, aquaterra_id=aquaterra_id)
    items = report.quote_in["line_items"]
    assert items[0]["sku"] == "PN-8842-XL"
    # item_name distinct from sku — both preserved.
    assert items[0]["item_name"] == "Skimmer"


# ══════════════════════════════════════════════════════════════
# 4. Per-line tax (tax_line + tax_pct) preserved
# ══════════════════════════════════════════════════════════════
@pytest.mark.anyio
async def test_per_line_tax_preserved(
    adb, aquaterra_id, mirror_customer,
):
    from services.imports.extraction_schema import ExtractedLineItem
    doc = _make_doc(line_items=[
        ExtractedLineItem(
            description="Taxable chemical",
            item_name="CL-1LB",
            qty=1.0, cost_rate=50.0, line_total=53.13,
            tax_pct=6.25, tax_line=3.13,
        ),
    ])
    report = await _run_mapper(doc, adb=adb, aquaterra_id=aquaterra_id)
    items = report.quote_in["line_items"]
    assert items[0]["tax_pct"] == 6.25
    assert items[0]["tax_line"] == 3.13
    assert items[0]["line_total"] == 53.13


# ══════════════════════════════════════════════════════════════
# 5. line_items_preserved_verbatim sentinel emitted
# ══════════════════════════════════════════════════════════════
@pytest.mark.anyio
async def test_verbatim_sentinel_emitted(
    adb, aquaterra_id, mirror_customer,
):
    from services.imports.extraction_schema import ExtractedLineItem
    doc = _make_doc(line_items=[
        ExtractedLineItem(
            description="X", item_name="Y",
            qty=1.0, cost_rate=1.0, line_total=1.0,
        ),
    ])
    report = await _run_mapper(doc, adb=adb, aquaterra_id=aquaterra_id)
    # Sibling to imported_totals_verbatim from PDF-FIX-D.
    assert report.quote_in["imported_totals_verbatim"] is True
    assert report.quote_in["line_items_preserved_verbatim"] is True


# ══════════════════════════════════════════════════════════════
# 6. Missing line_total but qty × unit_price computes correctly
#    (preserved via the PDF-FIX-D fold)
# ══════════════════════════════════════════════════════════════
@pytest.mark.anyio
async def test_missing_line_total_falls_back_to_math(
    adb, aquaterra_id, mirror_customer,
):
    """PDF-FIX-D fold behaviour: when the extractor did NOT
    capture ``line_total`` (extractor emits null), the mapper
    passes through ``line_total = None`` so the commit +
    FE display fall back to ``qty × unit_price``. This lock
    protects that fallback across PDF-MIRROR."""
    from services.imports.extraction_schema import ExtractedLineItem
    doc = _make_doc(line_items=[
        ExtractedLineItem(
            description="Missing line total",
            item_name="MLT",
            qty=3.0, cost_rate=25.0,
            line_total=None,
        ),
    ])
    report = await _run_mapper(doc, adb=adb, aquaterra_id=aquaterra_id)
    items = report.quote_in["line_items"]
    # line_total passes through as None so downstream falls
    # back to qty × price.
    assert items[0]["line_total"] is None
    assert items[0]["quantity"] == 3.0
    assert items[0]["unit_price"] == 25.0
    # qty × unit_price = 75.0 is what downstream commit +
    # FE display fall back to.


# ══════════════════════════════════════════════════════════════
# 7. SKU-only row (description empty) still commits
#    — protects the PDF-FIX-C SKU-only line survival
# ══════════════════════════════════════════════════════════════
@pytest.mark.anyio
async def test_sku_only_row_survives_extractor_filter(
    adb, aquaterra_id, mirror_customer,
):
    """PDF-FIX-C rule: line items with EITHER item_name OR non-
    empty description are kept. A SKU-only line where the tech
    left the description blank still round-trips into
    ``quote_in.line_items``."""
    from services.imports.extraction_schema import ExtractedLineItem
    doc = _make_doc(line_items=[
        ExtractedLineItem(
            description="", item_name="SKU-ONLY-1",
            sku="PN-99-A",
            qty=1.0, cost_rate=10.0, line_total=10.0,
        ),
    ])
    report = await _run_mapper(doc, adb=adb, aquaterra_id=aquaterra_id)
    items = report.quote_in["line_items"]
    assert len(items) == 1
    assert items[0]["item_name"] == "SKU-ONLY-1"
    assert items[0]["sku"] == "PN-99-A"


# ══════════════════════════════════════════════════════════════
# 8. None sku / None tax_pct / None tax_line are all valid
#    passthroughs (grandfather compat for pre-MIRROR fixtures)
# ══════════════════════════════════════════════════════════════
@pytest.mark.anyio
async def test_null_optional_fields_pass_through(
    adb, aquaterra_id, mirror_customer,
):
    from services.imports.extraction_schema import ExtractedLineItem
    doc = _make_doc(line_items=[
        ExtractedLineItem(
            description="Legacy row", item_name="LEG",
            qty=1.0, cost_rate=1.0, line_total=1.0,
        ),
    ])
    report = await _run_mapper(doc, adb=adb, aquaterra_id=aquaterra_id)
    items = report.quote_in["line_items"]
    assert items[0]["sku"] is None
    assert items[0]["tax_pct"] is None
    assert items[0]["tax_line"] is None
