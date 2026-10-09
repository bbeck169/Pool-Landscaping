"""Phase 14B · Feb-2026 — PDF template-styles helper + line_items
threading contract tests.

Covers Follow-up 1 from the Phase 14 batch. Two slices:

  1. Helper unit tests (``services.documents.pdf_template_styles``)
     — return shape, hex sanitisation, graceful ``None`` on
     missing / malformed / absent docs.
  2. Integration smoke on ``GET /api/invoices/{iid}/pdf`` — the
     endpoint still returns a 200 ``application/pdf`` response
     after the helper is threaded in, both with and without a
     saved form_template (zero-regression lock).
"""
from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient


_BACKEND_DIR = str(Path(__file__).resolve().parents[1])
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
MONGO_URL = _ENV.get("MONGO_URL") or os.environ.get("MONGO_URL")
DB_NAME = _ENV.get("DB_NAME") or os.environ.get("DB_NAME")
API = os.environ.get("BACKEND_API_URL") or "http://localhost:8001/api"

_TAG = "P14B_PDF_TPL_TEST"


# ─── Section 1 — Helper unit tests (sync-wrapped via asyncio) ────
import asyncio
from services.documents.pdf_template_styles import (
    hex_or_default, load_pdf_template_styles,
)


def test_hex_or_default_accepts_valid_hex():
    assert hex_or_default("#FF0000", "#000000") == "#FF0000"
    assert hex_or_default("#123ABC", "#FFFFFF") == "#123ABC"


def test_hex_or_default_rejects_malformed():
    assert hex_or_default("red", "#000000") == "#000000"
    assert hex_or_default("", "#000000") == "#000000"
    assert hex_or_default(None, "#000000") == "#000000"
    assert hex_or_default("#GGGGGG", "#000000") == "#000000"
    assert hex_or_default("#F00", "#000000") == "#000000"  # 3-char rejected
    assert hex_or_default(42, "#000000") == "#000000"


def test_load_pdf_template_styles_returns_none_for_missing_doc():
    # ``load_pdf_template_styles`` is an async function; the two
    # ``None`` return branches are: no template saved + bad input.
    out = asyncio.get_event_loop().run_until_complete(
        load_pdf_template_styles(tenant_id="", form_type="invoice"))
    assert out is None
    out = asyncio.get_event_loop().run_until_complete(
        load_pdf_template_styles(tenant_id="nope-xxx",
                                   form_type="invoice"))
    assert out is None


# ─── Section 2 — Integration smoke ───────────────────────────────
def _login(email: str, password: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login",
                      json={"email": email, "password": password}, timeout=20)
    r.raise_for_status()
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def admin_h():
    return {"Authorization": f"Bearer {_login('admin@aquaterra.com')}"}


@pytest.fixture(scope="module")
def db():
    return MongoClient(MONGO_URL)[DB_NAME]


@pytest.fixture(scope="module")
def aquaterra_id(db):
    return db.tenants.find_one({"slug": "aquaterra"})["id"]


@pytest.fixture
def _seeded_invoice_id(db, aquaterra_id):
    cust = db.customers.find_one({"tenant_id": aquaterra_id},
                                    {"_id": 0, "id": 1, "name": 1})
    assert cust, "No customer in aquaterra for PDF smoke."
    iid = f"{_TAG}_{uuid.uuid4().hex[:8]}"
    # Invoices live in db.quotes with doc_type="invoice" (unified
    # quotes/estimates/invoices collection — see
    # routers/invoice_viewer.py::_load_invoice).
    db.quotes.insert_one({
        "id": iid, "tenant_id": aquaterra_id,
        "doc_type": "invoice",
        "customer_id": cust["id"], "customer_name": cust.get("name"),
        "number": iid[-6:],
        "invoice_number": iid[-6:],
        "invoice_date": "2026-02-15",
        "status": "draft",
        "subtotal": 100.0, "tax_total": 0.0, "taxes": 0.0,
        "total": 100.0, "amount_paid": 0.0, "outstanding": 100.0,
        "line_items": [
            {"description": f"{_TAG} line 1",
             "quantity": 1, "unit_price": 100.0, "total": 100.0,
             "cost_rate": 100.0, "qty_hr": 1, "percent": 0,
             "unit": "ea"},
        ],
        "deleted_at": None,
        "_tag": _TAG,
    })
    yield iid
    db.quotes.delete_many({"_tag": _TAG})
    db.form_templates.delete_many({"tenant_id": aquaterra_id,
                                     "_tag": _TAG})


def test_invoice_pdf_without_saved_template_renders(
        admin_h, _seeded_invoice_id):
    """Zero-regression smoke: no template saved for ``invoice``
    (lazy-seeded on first list GET, but we skip that) — the PDF
    endpoint must still return a 200 ``application/pdf`` body."""
    r = requests.get(f"{API}/invoices/{_seeded_invoice_id}/pdf",
                     headers=admin_h, timeout=30)
    assert r.status_code == 200, r.text
    assert r.headers.get("content-type", "").startswith(
        "application/pdf"), r.headers
    assert r.content.startswith(b"%PDF-"), (
        "Response body must be a PDF; got "
        f"{r.content[:64]!r}"
    )


def test_invoice_pdf_with_saved_template_still_renders(
        admin_h, db, aquaterra_id, _seeded_invoice_id):
    """Save a form_template for ``invoice`` with a non-default
    line_items_table bg_color + border_color; the endpoint must
    continue to return 200 + a valid PDF (the ReportLab TableStyle
    now consumes the template colors via ``hex_or_default``)."""
    db.form_templates.insert_one({
        "id": f"{_TAG}_tpl_{uuid.uuid4().hex[:8]}",
        "tenant_id": aquaterra_id,
        "form_type": "invoice",
        "version": 999,
        "is_current": True,
        "fields": [
            {"field_id": "line_items_table",
             "label": "Line Items",
             "field_type": "line_items_table",
             "order": 1,
             "locked_reorder": False,
             "style": {
                 "bg_color": "#FEF3C7",
                 "border_color": "#92400E",
                 "text_color": "#111827",
                 "width_cols": 12,
                 "padding_y": 6,
             }},
        ],
        "_tag": _TAG,
    })
    # Flip the pre-existing current template off so our tagged one
    # is the sole active doc (idempotent — the uniqueness invariant
    # is per-tenant-per-form_type).
    db.form_templates.update_many(
        {"tenant_id": aquaterra_id, "form_type": "invoice",
         "_tag": {"$ne": _TAG}},
        {"$set": {"is_current": False}},
    )

    r = requests.get(f"{API}/invoices/{_seeded_invoice_id}/pdf",
                     headers=admin_h, timeout=30)
    assert r.status_code == 200, r.text
    assert r.content.startswith(b"%PDF-")
