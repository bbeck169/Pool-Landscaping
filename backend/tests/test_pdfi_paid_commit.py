"""PDFI-PAID-B · Feb-2026 — Mapper + commit flow for paid invoices.

Locks the contracts shipped with PDFI-PAID-B:

  (a) Commit an invoice preview with ``is_paid=True`` + explicit
      ``paid_at`` + positive ``amount_paid`` → 200, invoice doc
      has ``payment_status="paid"`` + ``status="accepted"``
      (reconciler-driven terminal state), exactly 1 ``db.payments``
      row with canonical shape (amount, method, paid_at, source,
      invoice_id, customer_id, tenant_id, import_batch_id).
  (b) Same but ``is_paid=False`` → invoice doc has default
      status (``"sent"``), zero ``db.payments`` rows.
  (c) ``is_paid=True`` + ``paid_at=None`` → 422 ``paid_without_date``.
      Zero quotes created, zero payments created. Batch rolls back
      to ``preview_complete`` so operator can patch + retry.
  (d) ``is_paid=True`` + ``amount_paid=0`` → 422
      ``paid_without_amount``.  Same no-partial-write posture.
  (e) PATCH /preview with ``{is_paid:true, amount_paid, paid_at}``
      → whitelist accepts, persists, follow-up commit writes the
      payment row with the patched values.
  (f) Multi-doc batch (1 paid + 1 unpaid) → 2 quotes created, 1
      payment row (paid one only), tenant-scoped.
  (g) Payment row ``tenant_id`` matches the invoice's tenant_id.
      Cross-tenant leak impossible.

All tests seed ``import_batches`` directly in Mongo and drive
the HTTP endpoints — same end-to-end harness as
``test_task_h2_pdf_commit.py``.
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


# ─────────────────────────────────────────────────────────────
# Fixtures (mirror test_task_h2_pdf_commit.py)
# ─────────────────────────────────────────────────────────────
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


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────
def _preview_paid_invoice(*, source_doc_index: int, customer_id: str,
                          doc_number: str,
                          amount_paid: float = 140.0,
                          paid_at: str | None = "2026-08-28",
                          is_paid: bool = True) -> dict:
    """Build a mapper preview whose quote_in carries the three
    PDFI-PAID-B fields.  Also stamps ``payment_in`` when
    is_paid=True (the mapper does this; we mirror the shape
    directly so tests don't have to run the mapper live)."""
    qi = {
        "customer_id": customer_id,
        "customer_name": "Paid Test Customer",
        "title": f"Import #{doc_number}",
        "doc_type": "invoice",
        "doc_number": doc_number,
        "doc_date": "2026-08-28",
        "line_items": [
            {"description": "Service", "quantity": 1,
              "unit_price": 140.0, "line_total": 140.0}
        ],
        "tax_rate": 0.0,
        "grand_total": 140.0,
        "amount_paid": amount_paid,
        "total_due": 0.0 if is_paid else 140.0,
        "is_paid": is_paid,
        "paid_at": paid_at,
    }
    preview = {
        "source_doc_index": source_doc_index,
        "doc_kind": "invoice",
        "mapped_target": "quote_in",
        "customer_resolution": "matched",
        "matched_customer_id": customer_id,
        "match_score": 100.0,
        "quote_in": qi,
        "pending_payment_actions": [],
        "errors": [],
        "warnings": [],
        "truncated": False,
    }
    if is_paid:
        # Mirror pdf_mapper._build_payment_in output shape.
        preview["payment_in"] = {
            "customer_id": customer_id,
            "customer_name": qi["customer_name"],
            "doc_number": doc_number,
            "paid_at": paid_at,
            "amount_paid": amount_paid,
            "payment_method": "other",
            "payment_reference": None,
            "notes": None,
            "import_batch_id": None,  # commit stamps this
        }
    return preview


def _seed_batch(dbc, *, tenant_id: str, previews: list,
                status: str = "preview_complete",
                source_filename: str = "test.pdf") -> str:
    batch_id = str(uuid.uuid4())
    now_iso = datetime.now(timezone.utc).isoformat()
    dbc.import_batches.insert_one({
        "id": batch_id, "tenant_id": tenant_id, "status": status,
        "source_filename": source_filename, "created_at": now_iso,
        "mapper_previews": previews,
    })
    return batch_id


def _cleanup(dbc, tenant_id: str, batch_id: str):
    dbc.quotes.delete_many({"tenant_id": tenant_id,
                             "import_batch_id": batch_id})
    dbc.payments.delete_many({"tenant_id": tenant_id,
                                "import_batch_id": batch_id})
    dbc.import_batches.delete_one({"id": batch_id})
    dbc.import_audit.delete_many({"batch_id": batch_id})


# ═════════════════════════════════════════════════════════════
# (a) Fully paid invoice → payment_status=paid + status=accepted
#     (reconciler-driven) + 1 payment row
# ═════════════════════════════════════════════════════════════
def test_a_paid_invoice_commits_status_paid_and_writes_payment_row(
    dbc, aquaterra_id, admin_h, customer_id,
):
    doc_number = f"PAID-A-{uuid.uuid4().hex[:6]}"
    preview = _preview_paid_invoice(
        source_doc_index=0, customer_id=customer_id,
        doc_number=doc_number, amount_paid=140.0, paid_at="2026-08-28",
    )
    batch_id = _seed_batch(dbc, tenant_id=aquaterra_id, previews=[preview])
    try:
        r = requests.post(
            f"{API}/imports/pdf-invoice/{batch_id}/commit",
            headers=admin_h, json={"on_duplicate": "skip"}, timeout=20,
        )
        assert r.status_code == 200, f"expected 200, got {r.status_code}: {r.text}"
        body = r.json()
        assert body.get("quotes_created") == 1
        # PDFI-PAID-B · Feb-2026 — commit response nests payment
        # counts under committed.payments. Authoritative check is
        # the db.payments.find_one below; this top-level assertion
        # guards the HTTP envelope shape.
        committed = body.get("committed") or {}
        assert (committed.get("payments") or {}).get("created") == 1
        qid = body["quote_ids"][0]
        inv = dbc.quotes.find_one({"id": qid}, {"_id": 0})
        # Terminal paid state (FIN-PARITY-A reconciler-driven):
        # ``payment_status="paid"`` is the authoritative paid signal;
        # ``status="accepted"`` is the invoice-lifecycle terminal
        # the reconciler flips to on fully-paid landing
        # (sent → accepted, locked by test_pdf_commit_with_invoice_
        # link_reconciles). The CRM ``status`` enum does NOT include
        # "paid".
        assert inv.get("payment_status") == "paid", (
            f"expected payment_status=paid, got "
            f"{inv.get('payment_status')!r}"
        )
        assert inv["status"] == "accepted", (
            f"expected status=accepted (reconciler-driven), "
            f"got {inv.get('status')!r}"
        )
        pay = dbc.payments.find_one(
            {"tenant_id": aquaterra_id, "import_batch_id": batch_id},
            {"_id": 0},
        )
        assert pay is not None, "payment row not written"
        # Canonical field assertions (shape existing code already uses).
        assert pay["tenant_id"] == aquaterra_id
        assert pay["customer_id"] == customer_id
        assert pay["invoice_id"] == qid, (
            f"invoice_link_by_doc_number failed — expected {qid}, "
            f"got {pay.get('invoice_id')}"
        )
        assert pay["amount"] == 140.0
        assert pay["method"] == "other"
        assert str(pay["paid_at"]).startswith("2026-08-28")
        assert pay["source"] == "pdf_import"
        assert pay["import_batch_id"] == batch_id
    finally:
        _cleanup(dbc, aquaterra_id, batch_id)


# ═════════════════════════════════════════════════════════════
# (b) Unpaid invoice → default status, zero payment rows
# ═════════════════════════════════════════════════════════════
def test_b_unpaid_invoice_commits_with_no_payment_row(
    dbc, aquaterra_id, admin_h, customer_id,
):
    doc_number = f"PAID-B-{uuid.uuid4().hex[:6]}"
    preview = _preview_paid_invoice(
        source_doc_index=0, customer_id=customer_id,
        doc_number=doc_number, is_paid=False, paid_at=None,
    )
    # Explicitly strip payment_in to mirror a true unpaid preview.
    preview.pop("payment_in", None)
    batch_id = _seed_batch(dbc, tenant_id=aquaterra_id, previews=[preview])
    try:
        r = requests.post(
            f"{API}/imports/pdf-invoice/{batch_id}/commit",
            headers=admin_h, json={"on_duplicate": "skip"}, timeout=20,
        )
        assert r.status_code == 200
        body = r.json()
        assert body.get("quotes_created") == 1
        committed = body.get("committed") or {}
        assert (committed.get("payments") or {}).get("created") == 0
        qid = body["quote_ids"][0]
        inv = dbc.quotes.find_one({"id": qid}, {"_id": 0, "status": 1})
        assert inv["status"] == "sent", (
            f"expected default status=sent, got {inv.get('status')!r}"
        )
        n_pay = dbc.payments.count_documents(
            {"tenant_id": aquaterra_id, "import_batch_id": batch_id},
        )
        assert n_pay == 0
    finally:
        _cleanup(dbc, aquaterra_id, batch_id)


# ═════════════════════════════════════════════════════════════
# (c) is_paid=True + paid_at=None → 422 paid_without_date
# ═════════════════════════════════════════════════════════════
def test_c_paid_without_date_returns_422_and_no_writes(
    dbc, aquaterra_id, admin_h, customer_id,
):
    doc_number = f"PAID-C-{uuid.uuid4().hex[:6]}"
    preview = _preview_paid_invoice(
        source_doc_index=0, customer_id=customer_id,
        doc_number=doc_number, is_paid=True, paid_at=None,
    )
    batch_id = _seed_batch(dbc, tenant_id=aquaterra_id, previews=[preview])
    try:
        r = requests.post(
            f"{API}/imports/pdf-invoice/{batch_id}/commit",
            headers=admin_h, json={"on_duplicate": "skip"}, timeout=20,
        )
        assert r.status_code == 422, f"expected 422, got {r.status_code}: {r.text}"
        err = r.json().get("detail", {})
        assert err.get("error") == "paid_without_date"
        assert err.get("batch_id") == batch_id
        assert err.get("doc_indices") == [0]
        # Verify no writes.
        assert dbc.quotes.count_documents(
            {"tenant_id": aquaterra_id, "import_batch_id": batch_id},
        ) == 0
        assert dbc.payments.count_documents(
            {"tenant_id": aquaterra_id, "import_batch_id": batch_id},
        ) == 0
        # Verify batch rolled back to preview_complete.
        row = dbc.import_batches.find_one({"id": batch_id}, {"status": 1})
        assert row["status"] == "preview_complete"
    finally:
        _cleanup(dbc, aquaterra_id, batch_id)


# ═════════════════════════════════════════════════════════════
# (d) is_paid=True + amount_paid=0 → 422 paid_without_amount
# ═════════════════════════════════════════════════════════════
def test_d_paid_without_amount_returns_422_and_no_writes(
    dbc, aquaterra_id, admin_h, customer_id,
):
    doc_number = f"PAID-D-{uuid.uuid4().hex[:6]}"
    preview = _preview_paid_invoice(
        source_doc_index=0, customer_id=customer_id,
        doc_number=doc_number, is_paid=True, paid_at="2026-08-28",
        amount_paid=0.0,
    )
    batch_id = _seed_batch(dbc, tenant_id=aquaterra_id, previews=[preview])
    try:
        r = requests.post(
            f"{API}/imports/pdf-invoice/{batch_id}/commit",
            headers=admin_h, json={"on_duplicate": "skip"}, timeout=20,
        )
        assert r.status_code == 422
        err = r.json().get("detail", {})
        assert err.get("error") == "paid_without_amount"
        assert err.get("doc_indices") == [0]
        assert dbc.quotes.count_documents(
            {"tenant_id": aquaterra_id, "import_batch_id": batch_id},
        ) == 0
        assert dbc.payments.count_documents(
            {"tenant_id": aquaterra_id, "import_batch_id": batch_id},
        ) == 0
    finally:
        _cleanup(dbc, aquaterra_id, batch_id)


# ═════════════════════════════════════════════════════════════
# (e) PATCH /preview with the 3 paid-status fields → commit works
# ═════════════════════════════════════════════════════════════
def test_e_patch_preview_whitelist_accepts_paid_status_fields(
    dbc, aquaterra_id, admin_h, customer_id,
):
    doc_number = f"PAID-E-{uuid.uuid4().hex[:6]}"
    # Seed with is_paid=False, operator patches to True+date+amount.
    preview = _preview_paid_invoice(
        source_doc_index=0, customer_id=customer_id,
        doc_number=doc_number, is_paid=False, paid_at=None,
    )
    preview.pop("payment_in", None)
    batch_id = _seed_batch(dbc, tenant_id=aquaterra_id, previews=[preview])
    try:
        pr = requests.patch(
            f"{API}/imports/pdf-invoice/{batch_id}/preview",
            headers=admin_h,
            json={"doc_idx": 0, "patch": {
                "is_paid": True,
                "amount_paid": 150.0,
                "paid_at": "2026-09-01",
            }},
            timeout=20,
        )
        assert pr.status_code == 200, (
            f"PATCH expected 200, got {pr.status_code}: {pr.text}"
        )
        # Confirm persisted.
        row = dbc.import_batches.find_one({"id": batch_id})
        patched_qi = row["mapper_previews"][0]["quote_in"]
        assert patched_qi["is_paid"] is True
        assert patched_qi["amount_paid"] == 150.0
        assert patched_qi["paid_at"] == "2026-09-01"
        # Also stamp payment_in so commit lane fires (mapper would
        # normally do this on the next re-map; test harness patches
        # the shape directly to mirror the mapper's output).
        dbc.import_batches.update_one(
            {"id": batch_id},
            {"$set": {"mapper_previews.0.payment_in": {
                "customer_id": customer_id,
                "customer_name": patched_qi.get("customer_name"),
                "doc_number": doc_number,
                "paid_at": "2026-09-01",
                "amount_paid": 150.0,
                "payment_method": "other",
                "payment_reference": None,
                "notes": None,
                "import_batch_id": None,
            }}},
        )
        # Follow-up commit.
        r = requests.post(
            f"{API}/imports/pdf-invoice/{batch_id}/commit",
            headers=admin_h, json={"on_duplicate": "skip"}, timeout=20,
        )
        assert r.status_code == 200, f"commit expected 200, got {r.status_code}: {r.text}"
        pay = dbc.payments.find_one(
            {"tenant_id": aquaterra_id, "import_batch_id": batch_id},
            {"_id": 0},
        )
        assert pay is not None
        assert pay["amount"] == 150.0
        assert str(pay["paid_at"]).startswith("2026-09-01")
    finally:
        _cleanup(dbc, aquaterra_id, batch_id)


# ═════════════════════════════════════════════════════════════
# (f) Multi-doc batch — 1 paid + 1 unpaid → 2 quotes, 1 payment
# ═════════════════════════════════════════════════════════════
def test_f_multi_doc_batch_only_paid_gets_payment_row(
    dbc, aquaterra_id, admin_h, customer_id,
):
    doc_paid = f"PAID-F-P-{uuid.uuid4().hex[:6]}"
    doc_open = f"PAID-F-O-{uuid.uuid4().hex[:6]}"
    prev_paid = _preview_paid_invoice(
        source_doc_index=0, customer_id=customer_id,
        doc_number=doc_paid, is_paid=True,
        paid_at="2026-08-28", amount_paid=140.0,
    )
    prev_open = _preview_paid_invoice(
        source_doc_index=1, customer_id=customer_id,
        doc_number=doc_open, is_paid=False, paid_at=None,
    )
    prev_open.pop("payment_in", None)
    batch_id = _seed_batch(
        dbc, tenant_id=aquaterra_id, previews=[prev_paid, prev_open],
    )
    try:
        r = requests.post(
            f"{API}/imports/pdf-invoice/{batch_id}/commit",
            headers=admin_h, json={"on_duplicate": "skip"}, timeout=20,
        )
        assert r.status_code == 200, f"expected 200, got {r.status_code}: {r.text}"
        body = r.json()
        assert body.get("quotes_created") == 2
        committed = body.get("committed") or {}
        assert (committed.get("payments") or {}).get("created") == 1
        # Payment linked to the paid doc only.
        pay = dbc.payments.find_one(
            {"tenant_id": aquaterra_id, "import_batch_id": batch_id},
            {"_id": 0},
        )
        assert pay is not None
        assert pay["invoice_number"] == doc_paid
    finally:
        _cleanup(dbc, aquaterra_id, batch_id)


# ═════════════════════════════════════════════════════════════
# (g) Payment row carries the invoice's tenant_id — cross-tenant
#     leak impossible.  Also verifies the invoice_link lookup is
#     tenant-scoped (same doc_number under another tenant does not
#     link).
# ═════════════════════════════════════════════════════════════
def test_g_payment_row_tenant_isolation(
    dbc, aquaterra_id, admin_h, customer_id,
):
    doc_number = f"PAID-G-{uuid.uuid4().hex[:6]}"
    # Plant a decoy invoice with the SAME doc_number under a different
    # tenant to prove the invoice_link lookup is tenant-scoped.
    decoy_tid = f"TEST-G-DECOY-{uuid.uuid4().hex[:8]}"
    decoy_cid = f"TEST-G-CUST-{uuid.uuid4().hex[:8]}"
    dbc.quotes.insert_one({
        "id": f"TEST-G-QUOTE-{uuid.uuid4().hex[:8]}",
        "tenant_id": decoy_tid,
        "customer_id": decoy_cid,
        "doc_type": "invoice",
        "invoice_number": doc_number,
        "status": "sent",
    })
    preview = _preview_paid_invoice(
        source_doc_index=0, customer_id=customer_id,
        doc_number=doc_number, is_paid=True,
        paid_at="2026-08-28", amount_paid=140.0,
    )
    batch_id = _seed_batch(dbc, tenant_id=aquaterra_id, previews=[preview])
    try:
        r = requests.post(
            f"{API}/imports/pdf-invoice/{batch_id}/commit",
            headers=admin_h, json={"on_duplicate": "skip"}, timeout=20,
        )
        assert r.status_code == 200
        pay = dbc.payments.find_one(
            {"tenant_id": aquaterra_id, "import_batch_id": batch_id},
            {"_id": 0},
        )
        assert pay is not None
        assert pay["tenant_id"] == aquaterra_id, (
            f"payment tenant_id leaked — expected {aquaterra_id}, "
            f"got {pay.get('tenant_id')}"
        )
        # The payment MUST link to the invoice under the SAME tenant,
        # not the decoy.
        linked_inv = dbc.quotes.find_one({"id": pay["invoice_id"]},
                                           {"_id": 0, "tenant_id": 1})
        assert linked_inv["tenant_id"] == aquaterra_id, (
            "payment linked to a cross-tenant invoice!"
        )
    finally:
        _cleanup(dbc, aquaterra_id, batch_id)
        dbc.quotes.delete_many({"tenant_id": decoy_tid})
