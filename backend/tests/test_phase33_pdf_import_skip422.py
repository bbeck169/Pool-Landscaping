"""Phase 33 Step A · Feb-2026 — Skip-422 regression lock.

Repro scenario the user reported: a batch contains a preview that
is BOTH a duplicate of an already-committed invoice AND carries
``quote_in.is_paid=True`` with ``amount_paid=0/None`` (the extractor
failed to parse the paid amount on the receipt). Operator selects
``on_duplicate=skip``.

**Before Phase 33 Step A** — ``commit_batch`` ran paid-status
validation BEFORE the duplicate scan, so the invalid-paid-data row
tripped the 422 ``paid_without_amount`` gate even though
``on_duplicate=skip`` would have skipped it anyway. The whole batch
was rolled back to ``preview_complete`` with an opaque
``Upload failed (422)`` toast.

**After Phase 33 Step A** — ``commit_batch`` runs ``check_duplicates``
first, then filters previews destined to be skipped out of the
paid-status validation input. HTTP 200 is returned, the duplicate
row is skipped, non-duplicate rows commit normally.

This file is the minimum regression lock for the Skip-422 fix.
Full auto-create + response-shape coverage lives in
``test_phase33_pdf_import_full_flow.py`` (Step B+C).
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient


_TEST_DIR = Path(__file__).resolve().parent
_FE = dotenv_values(_TEST_DIR.parent.parent / "frontend" / ".env")
_BE = dotenv_values(_TEST_DIR.parent / ".env")
BASE = (_FE.get("EXPO_PUBLIC_BACKEND_URL")
        or os.environ.get("EXPO_PUBLIC_BACKEND_URL")
        or "http://localhost:8001").rstrip("/")
API = f"{BASE}/api"
MONGO_URL = _BE.get("MONGO_URL") or os.environ.get("MONGO_URL")
DB_NAME = _BE.get("DB_NAME") or os.environ.get("DB_NAME")


@pytest.fixture(scope="module")
def dbc():
    return MongoClient(MONGO_URL)[DB_NAME]


@pytest.fixture(scope="module")
def aquaterra_id(dbc):
    return dbc.tenants.find_one({"slug": "aquaterra"}, {"id": 1})["id"]


@pytest.fixture(scope="module")
def admin_h():
    r = requests.post(
        f"{API}/auth/login",
        json={"email": "admin@aquaterra.com", "password": "password123"},
        timeout=20,
    )
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture()
def customer_id(dbc, aquaterra_id):
    doc = dbc.customers.find_one({"tenant_id": aquaterra_id}, {"id": 1})
    assert doc is not None, "no customers seeded for aquaterra"
    return doc["id"]


def _preview_invoice(*, source_doc_index: int, customer_id: str,
                     doc_number: str, is_paid: bool, amount_paid):
    qi = {
        "customer_id": customer_id,
        "customer_name": "Skip422 Customer",
        "title": f"Import #{doc_number}",
        "doc_type": "invoice",
        "doc_number": doc_number,
        "doc_date": "2026-08-28",
        "line_items": [{"description": "Service", "quantity": 1,
                        "unit_price": 140.0, "line_total": 140.0}],
        "tax_rate": 0.0,
        "grand_total": 140.0,
        "amount_paid": amount_paid,
        "total_due": 0.0 if is_paid else 140.0,
        "is_paid": is_paid,
        "paid_at": "2026-08-28" if is_paid else None,
    }
    return {
        "source_doc_index": source_doc_index,
        "doc_kind": "invoice",
        "mapped_target": "quote_in",
        "customer_resolution": "matched",
        "matched_customer_id": customer_id,
        "match_score": 100.0,
        "quote_in": qi, "pending_payment_actions": [],
        "errors": [], "warnings": [], "truncated": False,
    }


def _seed_batch(dbc, *, tenant_id, previews, source_filename="skip422.pdf"):
    batch_id = str(uuid.uuid4())
    dbc.import_batches.insert_one({
        "id": batch_id, "tenant_id": tenant_id,
        "status": "preview_complete",
        "source_filename": source_filename,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "mapper_previews": previews,
    })
    return batch_id


def _cleanup(dbc, tenant_id, batch_id):
    dbc.quotes.delete_many({"tenant_id": tenant_id,
                            "import_batch_id": batch_id})
    dbc.payments.delete_many({"tenant_id": tenant_id,
                              "import_batch_id": batch_id})
    dbc.import_batches.delete_one({"id": batch_id})
    dbc.import_audit.delete_many({"batch_id": batch_id})


def test_skip422_duplicate_with_invalid_paid_data_does_not_422(
    dbc, aquaterra_id, admin_h, customer_id,
):
    """The specific user-reported repro.

    Row 0: a VALID, non-duplicate invoice that should commit.
    Row 1: a DUPLICATE of an already-committed invoice, flagged
            ``is_paid=True`` with ``amount_paid=None`` — exactly
            the data shape that previously tripped 422.

    With ``on_duplicate=skip``, the valid row commits, the
    duplicate row lands in ``quotes_skipped_duplicates`` count,
    and HTTP 200 is returned with NO ``paid_without_amount`` 422.
    """
    valid_doc = f"VAL-{uuid.uuid4().hex[:6]}"
    dup_doc = f"DUP-{uuid.uuid4().hex[:6]}"

    # Seed the "already-committed" quote so dup_doc shows up as a
    # duplicate on the duplicate scan. The dedupe query (see
    # ``check_duplicates`` in pdf_commit.py:186) matches on
    # ``(tenant_id, customer_id, doc_type, import_source_doc_number)``
    # — note the ``import_source_doc_number`` field, NOT doc_number.
    dbc.quotes.insert_one({
        "id": str(uuid.uuid4()),
        "tenant_id": aquaterra_id,
        "customer_id": customer_id,
        "doc_type": "invoice",
        "doc_number": dup_doc,
        "import_source_doc_number": dup_doc,
        "status": "sent",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })

    # Build the batch: 1 valid preview + 1 duplicate preview with
    # invalid paid data.
    previews = [
        _preview_invoice(source_doc_index=0, customer_id=customer_id,
                         doc_number=valid_doc,
                         is_paid=False, amount_paid=None),
        _preview_invoice(source_doc_index=1, customer_id=customer_id,
                         doc_number=dup_doc,
                         is_paid=True, amount_paid=None),  # the 422 trigger
    ]
    batch_id = _seed_batch(dbc, tenant_id=aquaterra_id, previews=previews)

    try:
        r = requests.post(
            f"{API}/imports/pdf-invoice/{batch_id}/commit",
            headers=admin_h, json={"on_duplicate": "skip"}, timeout=20,
        )
        assert r.status_code == 200, (
            f"Expected HTTP 200 (duplicate row with invalid paid data "
            f"should be skipped before 422 fires), got "
            f"{r.status_code}: {r.text}"
        )
        body = r.json()
        # Valid non-duplicate row committed.
        assert body.get("quotes_created") == 1, (
            f"Expected 1 quote created from the valid non-duplicate "
            f"preview, got {body.get('quotes_created')}: {body}"
        )
        # Duplicate row landed in the skipped-duplicates count.
        assert body.get("quotes_skipped_duplicates") == 1, (
            f"Expected 1 duplicate skipped, got "
            f"{body.get('quotes_skipped_duplicates')}: {body}"
        )
        # The 422 error-code string must NOT appear anywhere in the
        # response body.
        assert "paid_without_amount" not in r.text, (
            f"Response leaked paid_without_amount error after the "
            f"duplicate skip: {r.text}"
        )
    finally:
        dbc.quotes.delete_many({"tenant_id": aquaterra_id,
                                "doc_number": {"$in": [valid_doc, dup_doc]}})
        _cleanup(dbc, aquaterra_id, batch_id)


def test_skip422_non_skipped_invalid_paid_now_autoheals(
    dbc, aquaterra_id, admin_h, customer_id,
):
    """PDFI-PAID-C · Feb-2026 — the paid-status validator now has
    an auto-heal preamble that backfills ``amount_paid`` from
    ``grand_total`` (and ``paid_at`` from ``doc_date``) for rows
    with ``is_paid=True``. A non-skipped, non-duplicate preview
    with missing ``amount_paid`` but a valid ``grand_total`` is
    now a 200 (commit succeeds, provenance recorded) — not a 422.

    See ``test_pdf_import_phase_c_autoheal_and_fidelity.py::
    test_s5_unhealable_row_returns_structured_422`` for the
    negative control that locks the 422 path once auto-heal
    exhausts its fallbacks.
    """
    bad_doc = f"BAD-{uuid.uuid4().hex[:6]}"
    previews = [
        _preview_invoice(source_doc_index=0, customer_id=customer_id,
                         doc_number=bad_doc,
                         is_paid=True, amount_paid=None),
    ]
    batch_id = _seed_batch(dbc, tenant_id=aquaterra_id, previews=previews)
    try:
        r = requests.post(
            f"{API}/imports/pdf-invoice/{batch_id}/commit",
            headers=admin_h, json={"on_duplicate": "skip"}, timeout=20,
        )
        assert r.status_code == 200, (
            f"Expected 200 after PDFI-PAID-C auto-heal, got "
            f"{r.status_code}: {r.text}"
        )
        body = r.json()
        assert body.get("quotes_created") == 1
        qid = body["quote_ids"][0]
        inv = dbc.quotes.find_one({"id": qid}, {"_id": 0})
        meta = inv.get("_import_metadata") or {}
        assert "amount_paid" in (meta.get("auto_healed_fields") or [])
    finally:
        dbc.quotes.delete_many({"tenant_id": aquaterra_id,
                                "doc_number": bad_doc})
        _cleanup(dbc, aquaterra_id, batch_id)
