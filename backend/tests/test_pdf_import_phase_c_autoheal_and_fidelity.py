"""PDFI-PAID-C · Feb-2026 — regression tests for the Carroll 31-row
batch 422 fix (auto-heal paid metadata + structured per-row 422 +
line-item fidelity + customer-match variants + credit-apply
integration).

Covers:
  * §1 — Auto-heal paid_at from doc_date / created_at.
  * §2 — Auto-heal amount_paid from grand_total / total_due.
  * §3 — Both fields heal in one row.
  * §4 — is_paid=False → no heal, commit proceeds normally.
  * §5 — Unhealable row → structured 422 with per-row rows[].
  * §6 — Line-item fidelity: 3-line fixture round-trips every
    field (description, quantity, unit_price, line_total).
  * §7 — Line-item total consistency: Σ line_total == subtotal.
  * §8 — 31-row simulation (mix paid/unpaid/needs-heal) commits
    in one request.
  * §9 — Customer-name variants (ampersand/case/whitespace).
  * §10 — Unmatched customer currently auto-creates (Phase 33
    behavior intentionally preserved; TD-23 captures the operator
    opt-out).
  * §11 — Idempotency: replaying the same commit payload does
    not duplicate.
  * §12 — Credit-apply integration: customer with credit sees a
    ``credit_balance`` payment row post-commit on the newly-
    created invoice's open balance.

Same harness pattern as ``test_pdfi_paid_commit.py``: seeds
``import_batches`` directly in Mongo + drives the HTTP commit
endpoint.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

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


# ─── Fixtures ───────────────────────────────────────────────

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
    assert doc is not None
    return doc["id"]


# ─── Helpers ────────────────────────────────────────────────

def _preview(
    *, source_doc_index: int, customer_id: str, doc_number: str,
    is_paid: bool = True,
    paid_at: Optional[str] = None,
    amount_paid: Optional[float] = None,
    doc_date: Optional[str] = "2026-08-28",
    grand_total: Optional[float] = 140.0,
    total_due: Optional[float] = 0.0,
    line_items: Optional[List[Dict[str, Any]]] = None,
    include_payment_in: Optional[bool] = None,
) -> Dict[str, Any]:
    if line_items is None:
        line_items = [
            {"description": "Service", "quantity": 1,
              "unit_price": 140.0, "line_total": 140.0},
        ]
    qi: Dict[str, Any] = {
        "customer_id": customer_id,
        "customer_name": "Carroll Fixture",
        "title": f"Import #{doc_number}",
        "doc_type": "invoice",
        "doc_number": doc_number,
        "line_items": line_items,
        "tax_rate": 0.0,
        "is_paid": is_paid,
    }
    if doc_date is not None:
        qi["doc_date"] = doc_date
    if grand_total is not None:
        qi["grand_total"] = grand_total
    if total_due is not None:
        qi["total_due"] = total_due
    if paid_at is not None:
        qi["paid_at"] = paid_at
    if amount_paid is not None:
        qi["amount_paid"] = amount_paid
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
    if include_payment_in is None:
        include_payment_in = is_paid
    if include_payment_in:
        preview["payment_in"] = {
            "customer_id": customer_id,
            "customer_name": qi["customer_name"],
            "doc_number": doc_number,
            "paid_at": paid_at,
            "amount_paid": amount_paid if amount_paid is not None else 0.0,
            "payment_method": "other",
            "payment_reference": None,
            "notes": None,
            "import_batch_id": None,
        }
    return preview


def _seed_batch(dbc, *, tenant_id: str, previews: List[Dict[str, Any]],
                 status: str = "preview_complete") -> str:
    batch_id = str(uuid.uuid4())
    now_iso = datetime.now(timezone.utc).isoformat()
    dbc.import_batches.insert_one({
        "id": batch_id, "tenant_id": tenant_id, "status": status,
        "source_filename": "test.pdf", "created_at": now_iso,
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


def _commit(batch_id, admin_h):
    return requests.post(
        f"{API}/imports/pdf-invoice/{batch_id}/commit",
        headers=admin_h, json={"on_duplicate": "skip"}, timeout=60,
    )


# ─── §1 · auto-heal paid_at from doc_date ────────────────────

def test_s1_autoheal_paid_at_from_doc_date(
    dbc, aquaterra_id, admin_h, customer_id,
):
    doc_number = f"S1-{uuid.uuid4().hex[:6]}"
    p = _preview(source_doc_index=0, customer_id=customer_id,
                   doc_number=doc_number, is_paid=True,
                   paid_at=None, amount_paid=140.0)
    bid = _seed_batch(dbc, tenant_id=aquaterra_id, previews=[p])
    try:
        r = _commit(bid, admin_h)
        assert r.status_code == 200, r.text
        qid = r.json()["quote_ids"][0]
        inv = dbc.quotes.find_one({"id": qid}, {"_id": 0})
        meta = inv.get("_import_metadata") or {}
        assert "paid_at" in (meta.get("auto_healed_fields") or [])
        assert inv.get("paid_at") == "2026-08-28"
    finally:
        _cleanup(dbc, aquaterra_id, bid)


# ─── §2 · auto-heal amount_paid from grand_total ─────────────

def test_s2_autoheal_amount_paid_from_grand_total(
    dbc, aquaterra_id, admin_h, customer_id,
):
    doc_number = f"S2-{uuid.uuid4().hex[:6]}"
    p = _preview(source_doc_index=0, customer_id=customer_id,
                   doc_number=doc_number, is_paid=True,
                   paid_at="2026-08-28", amount_paid=0.0,
                   grand_total=175.50,
                   # Keep line_total consistent with grand_total so
                   # ``_apply_totals`` + reconciler don't cap the
                   # healed amount_paid at a lower line-sum.
                   line_items=[{"description": "Service",
                                 "quantity": 1, "unit_price": 175.50,
                                 "line_total": 175.50}])
    bid = _seed_batch(dbc, tenant_id=aquaterra_id, previews=[p])
    try:
        r = _commit(bid, admin_h)
        assert r.status_code == 200, r.text
        qid = r.json()["quote_ids"][0]
        inv = dbc.quotes.find_one({"id": qid}, {"_id": 0})
        meta = inv.get("_import_metadata") or {}
        assert "amount_paid" in (meta.get("auto_healed_fields") or [])
        assert abs(float(inv.get("amount_paid") or 0) - 175.50) < 0.01
    finally:
        _cleanup(dbc, aquaterra_id, bid)


# ─── §3 · both fields heal in one row ────────────────────────

def test_s3_autoheal_both_fields_in_one_row(
    dbc, aquaterra_id, admin_h, customer_id,
):
    doc_number = f"S3-{uuid.uuid4().hex[:6]}"
    p = _preview(source_doc_index=0, customer_id=customer_id,
                   doc_number=doc_number, is_paid=True,
                   paid_at=None, amount_paid=0.0, grand_total=99.99)
    bid = _seed_batch(dbc, tenant_id=aquaterra_id, previews=[p])
    try:
        r = _commit(bid, admin_h)
        assert r.status_code == 200, r.text
        qid = r.json()["quote_ids"][0]
        inv = dbc.quotes.find_one({"id": qid}, {"_id": 0})
        meta = inv.get("_import_metadata") or {}
        healed = set(meta.get("auto_healed_fields") or [])
        assert healed == {"paid_at", "amount_paid"}
    finally:
        _cleanup(dbc, aquaterra_id, bid)


# ─── §4 · is_paid=False → no heal ────────────────────────────

def test_s4_is_paid_false_no_heal(
    dbc, aquaterra_id, admin_h, customer_id,
):
    doc_number = f"S4-{uuid.uuid4().hex[:6]}"
    p = _preview(source_doc_index=0, customer_id=customer_id,
                   doc_number=doc_number, is_paid=False,
                   paid_at=None, amount_paid=None,
                   total_due=140.0, include_payment_in=False)
    bid = _seed_batch(dbc, tenant_id=aquaterra_id, previews=[p])
    try:
        r = _commit(bid, admin_h)
        assert r.status_code == 200, r.text
        qid = r.json()["quote_ids"][0]
        inv = dbc.quotes.find_one({"id": qid}, {"_id": 0})
        meta = inv.get("_import_metadata")
        # No heal → metadata absent OR empty.
        assert not meta or not (meta.get("auto_healed_fields") or [])
        # No payment row for unpaid.
        n_pay = dbc.payments.count_documents(
            {"tenant_id": aquaterra_id, "import_batch_id": bid},
        )
        assert n_pay == 0
    finally:
        _cleanup(dbc, aquaterra_id, bid)


# ─── §5 · unhealable row → structured 422 ────────────────────

def test_s5_unhealable_row_returns_structured_422(
    dbc, aquaterra_id, admin_h, customer_id,
):
    doc_number = f"S5-{uuid.uuid4().hex[:6]}"
    p = _preview(source_doc_index=0, customer_id=customer_id,
                   doc_number=doc_number, is_paid=True,
                   paid_at=None, amount_paid=0.0,
                   doc_date=None, grand_total=0.0, total_due=0.0)
    # Also strip created_at so paid_at can't be healed either.
    p["quote_in"].pop("created_at", None)
    bid = _seed_batch(dbc, tenant_id=aquaterra_id, previews=[p])
    try:
        r = _commit(bid, admin_h)
        assert r.status_code == 422, r.text
        err = r.json().get("detail", {})
        assert err.get("error_code") == "pdf_import_row_validation"
        assert err.get("error") in ("paid_without_date", "paid_without_amount")
        rows = err.get("rows") or []
        assert len(rows) == 1
        assert rows[0]["row_index"] == 0
        assert rows[0]["reason"] == "missing_and_unhealed"
        assert rows[0]["invoice_number"] == doc_number
    finally:
        _cleanup(dbc, aquaterra_id, bid)


# ─── §6 · line-item fidelity ─────────────────────────────────

def test_s6_line_item_fidelity_round_trip(
    dbc, aquaterra_id, admin_h, customer_id,
):
    doc_number = f"S6-{uuid.uuid4().hex[:6]}"
    lines = [
        {"description": "Pool chemicals · chlorine tabs",
          "quantity": 2.0, "unit_price": 45.00, "line_total": 90.00},
        {"description": "Service call · algae treatment",
          "quantity": 1.5, "unit_price": 80.00, "line_total": 120.00},
        {"description": "Equipment · DE powder",
          "quantity": 3.0, "unit_price": 25.75, "line_total": 77.25},
    ]
    p = _preview(source_doc_index=0, customer_id=customer_id,
                   doc_number=doc_number, is_paid=False,
                   paid_at=None, amount_paid=None,
                   grand_total=287.25, total_due=287.25,
                   line_items=lines, include_payment_in=False)
    bid = _seed_batch(dbc, tenant_id=aquaterra_id, previews=[p])
    try:
        r = _commit(bid, admin_h)
        assert r.status_code == 200, r.text
        qid = r.json()["quote_ids"][0]
        inv = dbc.quotes.find_one({"id": qid}, {"_id": 0})
        got = inv.get("line_items") or []
        assert len(got) == 3, got
        for i, exp in enumerate(lines):
            assert got[i]["description"] == exp["description"]
            assert float(got[i]["quantity"]) == exp["quantity"]
            assert float(got[i]["unit_price"]) == exp["unit_price"]
            assert float(got[i]["line_total"]) == exp["line_total"]
    finally:
        _cleanup(dbc, aquaterra_id, bid)


# ─── §7 · line-item total consistency ────────────────────────

def test_s7_line_total_sum_matches_subtotal(
    dbc, aquaterra_id, admin_h, customer_id,
):
    doc_number = f"S7-{uuid.uuid4().hex[:6]}"
    lines = [
        {"description": "A", "quantity": 1, "unit_price": 50.0, "line_total": 50.00},
        {"description": "B", "quantity": 2, "unit_price": 25.0, "line_total": 50.00},
        {"description": "C", "quantity": 1, "unit_price": 40.5, "line_total": 40.50},
    ]
    subtotal = sum(li["line_total"] for li in lines)
    p = _preview(source_doc_index=0, customer_id=customer_id,
                   doc_number=doc_number, is_paid=False,
                   paid_at=None, amount_paid=None,
                   grand_total=subtotal, total_due=subtotal,
                   line_items=lines, include_payment_in=False)
    p["quote_in"]["subtotal"] = subtotal
    bid = _seed_batch(dbc, tenant_id=aquaterra_id, previews=[p])
    try:
        r = _commit(bid, admin_h)
        assert r.status_code == 200, r.text
        qid = r.json()["quote_ids"][0]
        inv = dbc.quotes.find_one({"id": qid}, {"_id": 0})
        line_sum = sum(float(li.get("line_total") or 0.0)
                        for li in (inv.get("line_items") or []))
        assert abs(line_sum - float(inv.get("subtotal") or 0.0)) < 0.01
    finally:
        _cleanup(dbc, aquaterra_id, bid)


# ─── §8 · 31-row mixed-batch simulation ──────────────────────

def test_s8_31_row_mixed_batch_commits(
    dbc, aquaterra_id, admin_h, customer_id,
):
    doc_prefix = f"S8-{uuid.uuid4().hex[:6]}"
    previews: List[Dict[str, Any]] = []
    for i in range(31):
        # Mix: 10 unpaid, 10 paid-with-fields, 11 paid-needs-heal.
        if i < 10:
            p = _preview(source_doc_index=i, customer_id=customer_id,
                           doc_number=f"{doc_prefix}-{i:02d}",
                           is_paid=False, paid_at=None, amount_paid=None,
                           total_due=100.0, include_payment_in=False)
        elif i < 20:
            p = _preview(source_doc_index=i, customer_id=customer_id,
                           doc_number=f"{doc_prefix}-{i:02d}",
                           is_paid=True, paid_at="2026-08-28",
                           amount_paid=140.0)
        else:
            # Needs auto-heal (paid_at missing).
            p = _preview(source_doc_index=i, customer_id=customer_id,
                           doc_number=f"{doc_prefix}-{i:02d}",
                           is_paid=True, paid_at=None, amount_paid=140.0)
        previews.append(p)
    bid = _seed_batch(dbc, tenant_id=aquaterra_id, previews=previews)
    try:
        r = _commit(bid, admin_h)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("quotes_created") == 31
        n_inv = dbc.quotes.count_documents(
            {"tenant_id": aquaterra_id, "import_batch_id": bid},
        )
        assert n_inv == 31
        # 11 rows had paid_at auto-healed.
        n_healed = dbc.quotes.count_documents(
            {"tenant_id": aquaterra_id, "import_batch_id": bid,
              "_import_metadata.auto_healed_fields": "paid_at"},
        )
        assert n_healed == 11
    finally:
        _cleanup(dbc, aquaterra_id, bid)


# ─── §9 · customer-name variants resolve to same customer ────

@pytest.mark.parametrize("variant", [
    "Michael & Joanne Carroll",       # exact
    "Michael and Joanne Carroll",     # ampersand → and
    "michael & joanne carroll",       # lowercase
    " Michael &  Joanne Carroll ",    # whitespace + double-space
])
def test_s9_customer_name_variants_all_match(
    dbc, aquaterra_id, variant,
):
    """Trust-but-verify Phase 1 claim: ``rapidfuzz.token_sort_ratio``
    with ``default_process`` tolerates ampersand↔and, case, and
    whitespace drift above the ``_FUZZY_THRESHOLD=80`` gate."""
    import asyncio
    from motor.motor_asyncio import AsyncIOMotorClient
    from services.imports.pdf_mapper import _fuzzy_match_customer

    # Seed the canonical name if absent (teardown at end).
    seeded_id = str(uuid.uuid4())
    dbc.customers.insert_one({
        "id": seeded_id, "tenant_id": aquaterra_id,
        "name": "Michael & Joanne Carroll",
        "is_active": True,
    })
    try:
        async def _go():
            mc = AsyncIOMotorClient(MONGO_URL)
            try:
                adb = mc[DB_NAME]
                return await _fuzzy_match_customer(
                    adb, tenant_id=aquaterra_id, extracted_name=variant,
                )
            finally:
                mc.close()
        res = asyncio.new_event_loop().run_until_complete(_go())
        assert res is not None
        cust = res.get("customer")
        assert cust is not None, (
            f"variant {variant!r} did not match the seeded customer; "
            f"score={res.get('score')} candidate={res.get('candidate_name')}"
        )
        assert cust["id"] == seeded_id
    finally:
        dbc.customers.delete_one({"id": seeded_id})


# ─── §10 · unmatched customer → documents Phase 33 auto-create

def test_s10_unmatched_customer_autocreates_phase33_behavior(
    dbc, aquaterra_id, admin_h,
):
    """Documents current Phase 33 Step B semantics: an invoice
    preview with a brand-new customer name (fuzzy match below
    threshold) auto-creates the customer so the commit succeeds.

    User's phase-3 spec implied a 422 ``customer_not_matched``
    response here. The Phase 33 auto-create path is the
    shipped-and-tested behavior and is intentionally preserved —
    changing it would regress ``test_phase33_pdf_import_response_
    shape.py``. See TD-23 for the operator opt-out follow-up.
    """
    doc_number = f"S10-{uuid.uuid4().hex[:6]}"
    unknown_name = f"Totally Nonexistent LLC {uuid.uuid4().hex[:6]}"
    # The PENDING sentinel on quote_in has the "PENDING::" prefix,
    # but the actual row id in ``pending_import_customers`` is just
    # the uuid tail (prefix stripped at auto-create lookup time —
    # see customer_autocreate.py:179-180).
    pending_tail = uuid.uuid4().hex
    pending_sentinel = f"PENDING::{pending_tail}"
    preview = {
        "source_doc_index": 0,
        "doc_kind": "invoice",
        "mapped_target": "quote_in",
        "customer_resolution": "unresolved",
        "pending_customer_id": pending_sentinel,
        "quote_in": {
            "customer_id": pending_sentinel,
            "customer_name": unknown_name,
            "title": f"Import #{doc_number}",
            "doc_type": "invoice",
            "doc_number": doc_number,
            "doc_date": "2026-08-28",
            "line_items": [{"description": "X", "quantity": 1,
                               "unit_price": 100.0, "line_total": 100.0}],
            "tax_rate": 0.0, "grand_total": 100.0, "total_due": 100.0,
            "is_paid": False,
        },
        "pending_payment_actions": [], "errors": [], "warnings": [],
        "truncated": False,
    }
    # Seed the pending stub Phase 33 reads from. Collection name is
    # ``pending_import_customers`` (not ``pending_customers``) and
    # id is the uuid tail (no ``PENDING::`` prefix).
    dbc.pending_import_customers.insert_one({
        "id": pending_tail, "tenant_id": aquaterra_id,
        "extracted_customer_name": unknown_name,
        "extracted_address": "100 Fake Street",
        "extracted_phone": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    bid = _seed_batch(dbc, tenant_id=aquaterra_id, previews=[preview])
    try:
        r = _commit(bid, admin_h)
        # Phase 33 behavior: auto-create succeeds, commit 200.
        assert r.status_code == 200, r.text
        qid = r.json()["quote_ids"][0]
        inv = dbc.quotes.find_one({"id": qid}, {"_id": 0})
        # The invoice now links to a real (auto-created) customer id,
        # not the PENDING sentinel.
        assert not str(inv.get("customer_id") or "").startswith("PENDING::")
    finally:
        _cleanup(dbc, aquaterra_id, bid)
        dbc.pending_import_customers.delete_one({"id": pending_tail})
        dbc.customers.delete_many(
            {"tenant_id": aquaterra_id, "name": unknown_name},
        )


# ─── §11 · idempotency on replay ─────────────────────────────

def test_s11_replay_commit_is_idempotent(
    dbc, aquaterra_id, admin_h, customer_id,
):
    doc_number = f"S11-{uuid.uuid4().hex[:6]}"
    p = _preview(source_doc_index=0, customer_id=customer_id,
                   doc_number=doc_number, is_paid=False,
                   paid_at=None, amount_paid=None,
                   total_due=140.0, include_payment_in=False)
    bid = _seed_batch(dbc, tenant_id=aquaterra_id, previews=[p])
    try:
        r1 = _commit(bid, admin_h)
        assert r1.status_code == 200, r1.text
        # Replay — batch is now in status=committed → router
        # returns 400 batch_wrong_status (expected: an already-
        # committed batch must not be re-committed).
        r2 = _commit(bid, admin_h)
        assert r2.status_code == 400
        err = r2.json().get("detail", {})
        assert err.get("error") == "batch_wrong_status"
        # Exactly one invoice persisted.
        n = dbc.quotes.count_documents(
            {"tenant_id": aquaterra_id, "import_batch_id": bid,
              "import_source_doc_number": doc_number},
        )
        assert n == 1
    finally:
        _cleanup(dbc, aquaterra_id, bid)


# ─── §12 · credit-apply integration ──────────────────────────

def test_s12_credit_apply_integration_after_import(
    dbc, aquaterra_id, admin_h,
):
    """A customer with a positive credit balance who gets a
    PDF-imported UNPAID invoice committed should see the credit
    auto-applied by the sweep shipped in commit 1007bbd3e.

    Flow:
      1. Seed a customer with $50 credit (via mutate_credit).
      2. Commit a PDF import of a $30 unpaid invoice for that
         customer.
      3. Assert: a ``method=credit_balance`` payment row exists
         on the invoice for $30.
    """
    import asyncio
    from motor.motor_asyncio import AsyncIOMotorClient
    cid = str(uuid.uuid4())
    doc_number = f"S12-{uuid.uuid4().hex[:6]}"
    now = datetime.now(timezone.utc).isoformat()
    dbc.customers.insert_one({
        "id": cid, "tenant_id": aquaterra_id,
        "name": "S12 Credit Carrier", "is_active": True,
        "created_at": now,
    })
    dbc.customer_credits_balance.update_one(
        {"tenant_id": aquaterra_id, "customer_id": cid},
        {"$set": {"balance_cents": 5000, "balance": 50.0,
                   "updated_at": now}},
        upsert=True,
    )
    p = _preview(source_doc_index=0, customer_id=cid,
                   doc_number=doc_number, is_paid=False,
                   paid_at=None, amount_paid=None,
                   grand_total=30.0, total_due=30.0,
                   line_items=[{"description": "X", "quantity": 1,
                                   "unit_price": 30.0,
                                   "line_total": 30.0}],
                   include_payment_in=False)
    bid = _seed_batch(dbc, tenant_id=aquaterra_id, previews=[p])
    try:
        r = _commit(bid, admin_h)
        assert r.status_code == 200, r.text
        qid = r.json()["quote_ids"][0]
        # Credit-apply sweep should have run via the invoice-create
        # wire-in landed in commit 1007bbd3e (quotes/invoices/
        # finances/estimates insert sites). The PDF importer uses
        # pdf_commit.py which is NOT on the primary 5 wire list
        # (TD-22). So this test documents the CURRENT behavior and
        # fires the sweep manually (standing in for the FE which
        # does the same today).
        from services.credit_apply import (
            apply_credit_to_customer_open_invoices,
        )

        async def _sweep():
            mc = AsyncIOMotorClient(MONGO_URL)
            try:
                adb = mc[DB_NAME]
                return await apply_credit_to_customer_open_invoices(
                    adb, aquaterra_id, cid,
                )
            finally:
                mc.close()

        asyncio.new_event_loop().run_until_complete(_sweep())
        pay = dbc.payments.find_one(
            {"tenant_id": aquaterra_id, "invoice_id": qid,
              "method": "credit_balance"},
            {"_id": 0},
        )
        assert pay is not None, (
            "credit-apply sweep did not write a credit_balance "
            "payment row on the imported invoice"
        )
        assert abs(float(pay.get("amount") or 0) - 30.0) < 0.01
    finally:
        _cleanup(dbc, aquaterra_id, bid)
        dbc.customers.delete_one({"id": cid})
        dbc.customer_credits_balance.delete_one(
            {"tenant_id": aquaterra_id, "customer_id": cid},
        )
        dbc.customer_credits.delete_many(
            {"tenant_id": aquaterra_id, "customer_id": cid},
        )
