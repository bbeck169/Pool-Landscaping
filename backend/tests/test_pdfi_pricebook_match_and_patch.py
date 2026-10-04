"""PDFI-II · Feb-2026 — mapper line-catalogue auto-match + preview edit route.

Locks the following contracts shipped with PDFI-II:

  (a) Exact-name catalogue match attaches ``pricebook_item_id``.
  (b) Fuzzy name match (score >= 80 under rapidfuzz
      token_set_ratio) attaches the id too.
  (c) No close catalogue hit leaves the line free-form (no
      ``pricebook_item_id`` key, or value absent/None).
  (d) Tenant isolation — an item on tenant B must NEVER match a
      line on tenant A's batch regardless of name similarity.
  (e) PATCH preview with a valid doc_idx + customer_name patch
      returns 200, bumps the applied counter, and the mutation
      is visible on the Mongo row.
  (f) PATCH on a ``committed`` batch returns 409 and leaves the
      row untouched.
  (g) PATCH with doc_idx outside ``[0, len)`` returns 422.
  (h) PATCH with ``{line_items: {0: {unit_price: 150.0}}}``
      updates ONLY index-0 unit_price; every other field and
      other lines stay verbatim.

PATCH tests rebind ``routers.imports.db`` to the pytest loop-
bound Motor client via ``monkeypatch`` so the handler reads
collections on the same loop pytest is running on (sibling PDF
tests use direct-call pattern; the router-level handler's module-
level ``db`` is bound to the FastAPI startup loop which pytest
cannot share).
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
    row = dbc.tenants.find_one({"slug": "aquaterra"}, {"id": 1})
    assert row, "aquaterra tenant missing from seed"
    return row["id"]


@pytest.fixture(scope="module")
def other_tenant_id(dbc):
    tid = f"tenant-pdfi-ii-isolate-{uuid.uuid4().hex[:10]}"
    dbc.tenants.insert_one({
        "id": tid,
        "slug": tid,
        "name": "PDFI-II Isolation Tenant",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    yield tid
    dbc.tenants.delete_one({"id": tid})


@pytest.fixture()
def seed_catalogue(dbc, aquaterra_id, other_tenant_id):
    suffix = uuid.uuid4().hex[:10]
    pb_exact = f"pb-pdfi-ii-exact-{suffix}"
    pb_fuzzy = f"pb-pdfi-ii-fuzzy-{suffix}"
    pb_other = f"pb-pdfi-ii-other-{suffix}"
    dbc.items.insert_many([
        {
            "id": pb_exact,
            "tenant_id": aquaterra_id,
            "name": "Full Weekly Pool Service",
            "description": "weekly chem + clean",
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
        {
            "id": pb_fuzzy,
            "tenant_id": aquaterra_id,
            "name": "Weekly Pool Service",
            "description": "chem + skim",
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
        {
            "id": pb_other,
            "tenant_id": other_tenant_id,
            "name": "Full Weekly Pool Service",
            "description": "sibling-tenant row",
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
    ])
    yield {"exact": pb_exact, "fuzzy": pb_fuzzy, "other": pb_other}
    dbc.items.delete_many({"id": {"$in": [pb_exact, pb_fuzzy, pb_other]}})


@pytest.fixture()
def seed_customer(dbc, aquaterra_id):
    cid = f"cust-pdfi-ii-{uuid.uuid4().hex[:10]}"
    dbc.customers.insert_one({
        "id": cid,
        "tenant_id": aquaterra_id,
        "name": "PDFI-II Test Customer",
        "email": "pdfi-ii@example.com",
        "phone": "555-0177",
        "address": "22 Lane",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "is_active": True,
    })
    yield cid
    dbc.customers.delete_one({"id": cid})


# ══════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════

def _make_doc(*, item_name: str, customer_name: str = "PDFI-II Test Customer"):
    from services.imports.extraction_schema import (
        ExtractedDocument, ExtractedLineItem,
    )
    return ExtractedDocument(
        doc_kind="invoice",
        source_page_range=[1, 1],
        customer_name=customer_name,
        doc_number=f"INV-PDFI-II-{uuid.uuid4().hex[:8]}",
        doc_date=date(2026, 2, 10),
        line_items=[
            ExtractedLineItem(
                description="Multi-line description here",
                item_name=item_name,
                qty=1.0,
                cost_rate=140.00,
                line_total=140.00,
            ),
        ],
        subtotal=140.00,
        tax_total=0.0,
        grand_total=140.00,
        total_due=0.0,
    )


async def _run_mapper(doc, *, adb, tenant_id):
    from services.imports.pdf_mapper import map_extracted_to_quote_in
    batch_id = f"bat-pdfi-ii-{uuid.uuid4().hex[:10]}"
    return await map_extracted_to_quote_in(
        doc,
        db=adb,
        tenant_id=tenant_id,
        batch_id=batch_id,
        operator_user={"id": "admin-pdfi-ii", "role": "admin"},
        source_doc_index=0,
    )


# ══════════════════════════════════════════════════════════════════
# (a-d) Catalogue match assertions on the mapper
# ══════════════════════════════════════════════════════════════════

@pytest.mark.anyio
async def test_a_exact_name_attaches_catalogue_id(
    adb, aquaterra_id, seed_customer, seed_catalogue,
):
    doc = _make_doc(item_name="Full Weekly Pool Service")
    report = await _run_mapper(doc, adb=adb, tenant_id=aquaterra_id)
    assert report.quote_in is not None, report.errors
    lines = report.quote_in["line_items"]
    assert len(lines) == 1
    assert lines[0].get("pricebook_item_id") == seed_catalogue["exact"], (
        f"expected exact-name hit; got {lines[0].get('pricebook_item_id')!r}"
    )


@pytest.mark.anyio
async def test_b_fuzzy_name_attaches_catalogue_id(
    adb, aquaterra_id, seed_customer, seed_catalogue,
):
    doc = _make_doc(item_name="Service - Weekly Pool")
    report = await _run_mapper(doc, adb=adb, tenant_id=aquaterra_id)
    assert report.quote_in is not None
    lines = report.quote_in["line_items"]
    attached = lines[0].get("pricebook_item_id")
    assert attached in {seed_catalogue["fuzzy"], seed_catalogue["exact"]}, (
        f"expected fuzzy hit on a seeded aquaterra row; got {attached!r}"
    )


@pytest.mark.anyio
async def test_c_no_close_match_leaves_line_free_form(
    adb, aquaterra_id, seed_customer, seed_catalogue,
):
    doc = _make_doc(item_name="Fountain Repair")
    report = await _run_mapper(doc, adb=adb, tenant_id=aquaterra_id)
    assert report.quote_in is not None
    lines = report.quote_in["line_items"]
    assert not lines[0].get("pricebook_item_id"), (
        f"below-threshold match leaked onto line: "
        f"{lines[0].get('pricebook_item_id')!r}"
    )
    assert lines[0]["item_name"] == "Fountain Repair"


@pytest.mark.anyio
async def test_d_tenant_isolation_cross_tenant_row_cannot_win(
    adb, aquaterra_id, other_tenant_id, seed_customer, seed_catalogue,
):
    # Drop the two aquaterra rows for the duration of this test so
    # the ONLY candidate across tenants is the cross-tenant row. If
    # the filter were tenant-leaky, the line would attach other_id.
    mc = MongoClient(MONGO_URL)[DB_NAME]
    mc.items.delete_many({
        "id": {"$in": [seed_catalogue["exact"], seed_catalogue["fuzzy"]]},
    })
    try:
        doc = _make_doc(item_name="Full Weekly Pool Service")
        report = await _run_mapper(doc, adb=adb, tenant_id=aquaterra_id)
        assert report.quote_in is not None
        lines = report.quote_in["line_items"]
        assert not lines[0].get("pricebook_item_id"), (
            f"cross-tenant row leaked: {lines[0].get('pricebook_item_id')!r}"
        )
    finally:
        mc.items.insert_many([
            {
                "id": seed_catalogue["exact"],
                "tenant_id": aquaterra_id,
                "name": "Full Weekly Pool Service",
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
            {
                "id": seed_catalogue["fuzzy"],
                "tenant_id": aquaterra_id,
                "name": "Weekly Pool Service",
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        ])


# ══════════════════════════════════════════════════════════════════
# (e-h) PATCH preview-edit endpoint assertions
# ══════════════════════════════════════════════════════════════════

def _seed_preview_batch(dbc, *, tenant_id, status="preview_complete"):
    bid = f"bat-pdfi-ii-patch-{uuid.uuid4().hex[:10]}"
    dbc.import_batches.insert_one({
        "id": bid,
        "tenant_id": tenant_id,
        "status": status,
        "mapper_previews": [{
            "source_doc_index": 0,
            "doc_kind": "invoice",
            "mapped_target": "quote_in",
            "customer_resolution": "matched",
            "matched_customer_id": "cust-seed",
            "quote_in": {
                "customer_id": "cust-seed",
                "customer_name": "Diane Lloyd",
                "doc_type": "invoice",
                "doc_number": "10774",
                "doc_date": "2026-08-28",
                "grand_total": 140.0,
                "total_due": 0.0,
                "line_items": [
                    {
                        "item_name": "Full Weekly Pool Service",
                        "description": "weekly service",
                        "quantity": 1.0,
                        "unit_price": 140.0,
                        "line_total": 140.0,
                        "sku": None,
                        "tax_pct": None,
                        "tax_line": None,
                    },
                    {
                        "item_name": "Chlorine",
                        "description": "chem add-on",
                        "quantity": 2.0,
                        "unit_price": 25.0,
                        "line_total": 50.0,
                    },
                ],
            },
        }],
    })
    return bid


@pytest.fixture()
def rebind_router_db(adb, monkeypatch):
    """Rebind ``routers.imports.db`` + ``config.db`` to the loop-
    bound Motor client the pytest-anyio event loop owns. Without
    this, the handler's ``await db.import_batches.find_one(...)``
    hits a Future attached to a different loop and raises
    ``RuntimeError``.
    """
    import importlib
    r_imports = importlib.import_module("routers.imports")
    cfg = importlib.import_module("config")
    monkeypatch.setattr(r_imports, "db", adb, raising=True)
    monkeypatch.setattr(cfg, "db", adb, raising=True)
    yield


async def _call_patch(*, batch_id, body, tenant_id, user_id="admin-pdfi-ii"):
    from routers.imports import patch_pdf_invoice_preview, _PreviewPatchIn
    return await patch_pdf_invoice_preview(
        batch_id=batch_id,
        body=_PreviewPatchIn(**body),
        user={"id": user_id, "role": "admin"},
        tenant={"id": tenant_id},
    )


@pytest.mark.anyio
async def test_e_patch_customer_name_persists(
    dbc, aquaterra_id, rebind_router_db,
):
    bid = _seed_preview_batch(dbc, tenant_id=aquaterra_id)
    try:
        res = await _call_patch(
            batch_id=bid,
            body={"doc_idx": 0, "patch": {"customer_name": "Diane A. Lloyd"}},
            tenant_id=aquaterra_id,
        )
        assert res["batch_id"] == bid
        assert "customer_name" in res["patched_keys"]
        assert res["preview_patches_applied"] == 1
        row = dbc.import_batches.find_one({"id": bid})
        assert row["mapper_previews"][0]["quote_in"]["customer_name"] == "Diane A. Lloyd"
        assert row.get("preview_patches_applied") == 1
        assert len(row.get("preview_patch_log", [])) == 1
    finally:
        dbc.import_batches.delete_one({"id": bid})


@pytest.mark.anyio
async def test_f_patch_on_committed_batch_is_409(
    dbc, aquaterra_id, rebind_router_db,
):
    from fastapi import HTTPException
    bid = _seed_preview_batch(dbc, tenant_id=aquaterra_id, status="committed")
    try:
        with pytest.raises(HTTPException) as exc:
            await _call_patch(
                batch_id=bid,
                body={"doc_idx": 0, "patch": {"customer_name": "Mutated"}},
                tenant_id=aquaterra_id,
            )
        assert exc.value.status_code == 409
        assert exc.value.detail.get("error") == "batch_wrong_status"
        row = dbc.import_batches.find_one({"id": bid})
        assert row["mapper_previews"][0]["quote_in"]["customer_name"] == "Diane Lloyd"
        assert row.get("preview_patches_applied") in (None, 0)
        assert row.get("preview_patch_log") in (None, [])
    finally:
        dbc.import_batches.delete_one({"id": bid})


@pytest.mark.anyio
async def test_g_patch_doc_idx_out_of_range_is_422(
    dbc, aquaterra_id, rebind_router_db,
):
    from fastapi import HTTPException
    bid = _seed_preview_batch(dbc, tenant_id=aquaterra_id)
    try:
        with pytest.raises(HTTPException) as exc:
            await _call_patch(
                batch_id=bid,
                body={"doc_idx": 7, "patch": {"customer_name": "X"}},
                tenant_id=aquaterra_id,
            )
        assert exc.value.status_code == 422
        assert exc.value.detail.get("error") == "doc_idx_out_of_range"
    finally:
        dbc.import_batches.delete_one({"id": bid})


@pytest.mark.anyio
async def test_h_patch_line_items_partial_surgical_update(
    dbc, aquaterra_id, rebind_router_db,
):
    bid = _seed_preview_batch(dbc, tenant_id=aquaterra_id)
    try:
        res = await _call_patch(
            batch_id=bid,
            body={
                "doc_idx": 0,
                "patch": {"line_items": {0: {"unit_price": 150.0}}},
            },
            tenant_id=aquaterra_id,
        )
        assert "line_items" in res["patched_keys"]
        row = dbc.import_batches.find_one({"id": bid})
        lines = row["mapper_previews"][0]["quote_in"]["line_items"]
        assert lines[0]["unit_price"] == 150.0
        assert lines[0]["item_name"] == "Full Weekly Pool Service"
        assert lines[0]["description"] == "weekly service"
        assert lines[0]["quantity"] == 1.0
        assert lines[0]["line_total"] == 140.0
        assert lines[1]["item_name"] == "Chlorine"
        assert lines[1]["unit_price"] == 25.0
        assert lines[1]["line_total"] == 50.0
    finally:
        dbc.import_batches.delete_one({"id": bid})
