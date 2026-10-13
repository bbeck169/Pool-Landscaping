"""Feb-2026 · PDF Import Hub — auto-create customer from PDF
extraction when no match found (coverage for the auto-create UX
ticket).

Covers the preview-classification side (``classify_pending_for_preview``)
PLUS the auto-create helper side (``auto_create_pending_customers``):

  1. Preview emits ``auto_create_candidate`` with name / email /
     phone / mailing_address / service_category + fields_extracted
     / fields_missing + dedup_group_id for pendings with signal.
  2. Preview emits ``summary.will_auto_create_count`` = number of
     distinct dedup groups so the FE banner matches commit truth.
  3. Two pendings sharing the same normalized (name, address) land
     under the SAME ``dedup_group_id`` and the summary count
     collapses to 1.
  4. Low-confidence rows (Bug 3 demoted ``customer_extraction_confidence``
     ``=="low"``) are routed to ``will_require_manual_review`` with
     reason ``"customer_extraction_confidence_low"`` — NEVER to
     ``will_auto_create``.
  5. Auto-create helper short-circuits low-conf pendings into
     ``manual_review_needed`` with the same reason.
  6. ``_insert_auto_customer`` stamps ``service_category="both"`` +
     ``created_by="pdf_import"`` + ``source="pdf_import"`` +
     ``created_from_import_batch_id`` on the new customer doc.
  7. ``UnresolvedCustomersError`` carries the
     ``customer_requires_manual_resolution`` error_code the router
     now surfaces as 422.
  8. ``collect_unresolved_customers`` tags low-conf pendings with
     ``reason="customer_extraction_confidence_low"`` so the 422
     body distinguishes manual-resolution UX from zero-signal
     UX.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.imports.customer_autocreate import (  # noqa: E402
    auto_create_pending_customers,
    collect_low_confidence_pending_ids,
    compute_dedup_group_id,
)
from services.imports.pdf_commit import (  # noqa: E402
    UnresolvedCustomer,
    UnresolvedCustomersError,
    classify_pending_for_preview,
    collect_unresolved_customers,
)


# ═════════════════════════════════════════════════════════════
# Fake async Mongo — just enough shape for the helpers to run
# without a live DB connection.
# ═════════════════════════════════════════════════════════════
class _FakeCollection:
    def __init__(self, rows=None):
        self.rows = list(rows or [])
        self.inserted: list = []
        self.updated: list = []

    def find(self, query, projection=None):
        rows = list(self.rows)
        id_filter = (query or {}).get("id")
        if isinstance(id_filter, dict) and "$in" in id_filter:
            allowed = set(id_filter["$in"])
            rows = [r for r in rows if r.get("id") in allowed]
        tenant_id = (query or {}).get("tenant_id")
        if tenant_id is not None:
            rows = [r for r in rows if r.get("tenant_id") == tenant_id]

        class _Cursor:
            def __aiter__(self_cur):
                return self_cur

            async def __anext__(self_cur):
                if not rows:
                    raise StopAsyncIteration
                return rows.pop(0)

        return _Cursor()

    async def insert_one(self, doc):
        self.inserted.append(doc)

    async def update_one(self, filt, update):
        self.updated.append((filt, update))


class _FakeDB:
    def __init__(self, *, pending_rows=None, existing_customers=None):
        self.pending_import_customers = _FakeCollection(pending_rows)
        self.customers = _FakeCollection(existing_customers)
        self.audit_logs = _FakeCollection()


# ═════════════════════════════════════════════════════════════
# Test 1 — Preview emits auto_create_candidate with all fields
# ═════════════════════════════════════════════════════════════
def test_classify_emits_auto_create_candidate_with_all_fields():
    pending_rows = [{
        "id": "pid-full", "tenant_id": "t1", "batch_id": "b1",
        "extracted_customer_name": "Joe Kail",
        "extracted_email": "joe@example.com",
        "extracted_address": "123 Pine Dr",
        "extracted_phone": "555-1234",
    }]
    db = _FakeDB(pending_rows=pending_rows)
    previews = [{
        "source_doc_index": 3, "mapped_target": "quote_in",
        "quote_in": {"customer_id": "PENDING::pid-full"},
    }]
    result = asyncio.run(classify_pending_for_preview(
        previews=previews, tenant_id="t1", db=db,
    ))
    assert len(result["will_auto_create"]) == 1
    row = result["will_auto_create"][0]
    candidate = row["auto_create_candidate"]
    assert candidate["name"] == "Joe Kail"
    assert candidate["email"] == "joe@example.com"
    assert candidate["phone"] == "555-1234"
    assert candidate["mailing_address"] == {
        "street": "123 Pine Dr",
        "city": None, "state": None, "zip": None,
    }
    assert candidate["service_category"] == "both"
    assert set(row["fields_extracted"]) == {
        "name", "email", "phone", "mailing_address",
    }
    assert row["fields_missing"] == []
    assert row["dedup_group_id"]
    assert result["summary"]["will_auto_create_count"] == 1


# ═════════════════════════════════════════════════════════════
# Test 2 — Fields missing surface on fields_missing array
# ═════════════════════════════════════════════════════════════
def test_classify_partial_extraction_populates_fields_missing():
    pending_rows = [{
        "id": "pid-partial", "tenant_id": "t1", "batch_id": "b1",
        "extracted_customer_name": "Partial Inc",
        "extracted_phone": "555-9999",
        "extracted_address": "",
        "extracted_email": "",
    }]
    db = _FakeDB(pending_rows=pending_rows)
    previews = [{
        "source_doc_index": 0, "mapped_target": "quote_in",
        "quote_in": {"customer_id": "PENDING::pid-partial"},
    }]
    result = asyncio.run(classify_pending_for_preview(
        previews=previews, tenant_id="t1", db=db,
    ))
    row = result["will_auto_create"][0]
    assert row["fields_extracted"] == ["name", "phone"]
    assert sorted(row["fields_missing"]) == ["email", "mailing_address"]
    assert row["auto_create_candidate"]["email"] is None
    assert row["auto_create_candidate"]["mailing_address"] is None


# ═════════════════════════════════════════════════════════════
# Test 3 — Shared dedup_group_id for identical name+address
# ═════════════════════════════════════════════════════════════
def test_classify_two_pendings_same_name_address_share_dedup_group():
    pending_rows = [
        {"id": "pid-a", "tenant_id": "t1", "batch_id": "b1",
          "extracted_customer_name": "Acme Pools",
          "extracted_address": "123 Pine",
          "extracted_phone": "555-1111"},
        {"id": "pid-b", "tenant_id": "t1", "batch_id": "b1",
          "extracted_customer_name": "ACME POOLS",  # case-variant
          "extracted_address": "  123 Pine  ",       # whitespace-variant
          "extracted_phone": "555-9999"},
    ]
    db = _FakeDB(pending_rows=pending_rows)
    previews = [
        {"source_doc_index": 0, "mapped_target": "quote_in",
          "quote_in": {"customer_id": "PENDING::pid-a"}},
        {"source_doc_index": 1, "mapped_target": "quote_in",
          "quote_in": {"customer_id": "PENDING::pid-b"}},
    ]
    result = asyncio.run(classify_pending_for_preview(
        previews=previews, tenant_id="t1", db=db,
    ))
    assert len(result["will_auto_create"]) == 2
    group_ids = {r["dedup_group_id"] for r in result["will_auto_create"]}
    assert len(group_ids) == 1, (
        f"expected both rows to share one dedup group, got {group_ids!r}"
    )
    # Banner count must equal distinct groups — one new customer
    # will be created on commit.
    assert result["summary"]["will_auto_create_count"] == 1


# ═════════════════════════════════════════════════════════════
# Test 4 — Low-confidence row NEVER lands in will_auto_create
# ═════════════════════════════════════════════════════════════
def test_classify_low_confidence_lands_in_manual_review():
    pending_rows = [{
        "id": "pid-lowconf", "tenant_id": "t1", "batch_id": "b1",
        "extracted_customer_name": "346",
        "extracted_address": "",
        "extracted_phone": "",
    }]
    db = _FakeDB(pending_rows=pending_rows)
    previews = [{
        "source_doc_index": 5, "mapped_target": "quote_in",
        "quote_in": {
            "customer_id": "PENDING::pid-lowconf",
            # Bug 3 post-processor runs AFTER mapper and demotes
            # the suspect name; the preview still carries the
            # PENDING sentinel so the classifier can see it.
            "customer_extraction_confidence": "low",
        },
    }]
    result = asyncio.run(classify_pending_for_preview(
        previews=previews, tenant_id="t1", db=db,
    ))
    assert result["will_auto_create"] == []
    assert len(result["will_require_manual_review"]) == 1
    row = result["will_require_manual_review"][0]
    assert row["reason"] == "customer_extraction_confidence_low"
    assert result["summary"]["will_auto_create_count"] == 0
    assert result["summary"]["manual_review_count"] == 1


# ═════════════════════════════════════════════════════════════
# Test 5 — Auto-create helper skips low-confidence pendings
# ═════════════════════════════════════════════════════════════
def test_auto_create_helper_routes_low_conf_to_manual_review():
    pending_rows = [{
        "id": "pid-lowconf", "tenant_id": "t1", "batch_id": "b1",
        "extracted_customer_name": "346",
        "extracted_address": "",
        "extracted_phone": "",
    }]
    previews = [{
        "source_doc_index": 1, "mapped_target": "quote_in",
        "quote_in": {
            "customer_id": "PENDING::pid-lowconf",
            "customer_extraction_confidence": "low",
        },
    }]
    db = _FakeDB(pending_rows=pending_rows)
    result = asyncio.run(auto_create_pending_customers(
        previews=previews,
        batch={"id": "b1"},
        tenant_id="t1",
        operator={"id": "admin-1"},
        db=db,
    ))
    # Zero new customers minted.
    assert db.customers.inserted == []
    # Manual-review surface populated with the right reason.
    assert len(result.manual_review_needed) == 1
    assert (
        result.manual_review_needed[0].reason
        == "customer_extraction_confidence_low"
    )


# ═════════════════════════════════════════════════════════════
# Test 6 — _insert_auto_customer stamps service_category + created_by
# ═════════════════════════════════════════════════════════════
def test_auto_create_helper_stamps_service_category_and_created_by():
    pending_rows = [{
        "id": "pid-new", "tenant_id": "t1", "batch_id": "b1",
        "extracted_customer_name": "Fresh Customer",
        "extracted_email": "fresh@example.com",
        "extracted_address": "456 Oak",
        "extracted_phone": "555-2222",
    }]
    previews = [{
        "source_doc_index": 0, "mapped_target": "quote_in",
        "quote_in": {"customer_id": "PENDING::pid-new"},
    }]
    db = _FakeDB(pending_rows=pending_rows)
    result = asyncio.run(auto_create_pending_customers(
        previews=previews,
        batch={"id": "b1"},
        tenant_id="t1",
        operator={"id": "admin-1"},
        db=db,
    ))
    assert len(db.customers.inserted) == 1
    new_cust = db.customers.inserted[0]
    assert new_cust["name"] == "Fresh Customer"
    assert new_cust["email"] == "fresh@example.com"
    assert new_cust["service_category"] == "both"
    assert new_cust["created_by"] == "pdf_import"
    assert new_cust["source"] == "pdf_import"
    assert new_cust["created_via"] == "pdf_import_auto"
    assert new_cust["created_from_import_batch_id"] == "b1"
    assert new_cust["tenant_id"] == "t1"
    assert len(result.auto_created) == 1
    assert result.auto_created[0].action == "created"


# ═════════════════════════════════════════════════════════════
# Test 7 — In-batch dedup: 2 rows → 1 customer
# ═════════════════════════════════════════════════════════════
def test_auto_create_helper_dedups_two_rows_to_one_customer():
    pending_rows = [
        {"id": "pid-a", "tenant_id": "t1", "batch_id": "b1",
          "extracted_customer_name": "Shared Customer",
          "extracted_address": "789 Elm",
          "extracted_phone": "555-3333"},
        {"id": "pid-b", "tenant_id": "t1", "batch_id": "b1",
          "extracted_customer_name": "SHARED Customer",  # case variant
          "extracted_address": "789 ELM",                 # case variant
          "extracted_phone": "555-9999"},
    ]
    previews = [
        {"source_doc_index": 0, "mapped_target": "quote_in",
          "quote_in": {"customer_id": "PENDING::pid-a"}},
        {"source_doc_index": 1, "mapped_target": "quote_in",
          "quote_in": {"customer_id": "PENDING::pid-b"}},
    ]
    db = _FakeDB(pending_rows=pending_rows)
    result = asyncio.run(auto_create_pending_customers(
        previews=previews,
        batch={"id": "b1"},
        tenant_id="t1",
        operator={"id": "admin-1"},
        db=db,
    ))
    # Exactly ONE insert in db.customers.
    assert len(db.customers.inserted) == 1
    # Both pendings resolved to the SAME customer_id.
    actions = [c.action for c in result.auto_created]
    assert "created" in actions
    assert "deduped_batch" in actions
    resolved_ids = {c.resolved_customer_id for c in result.auto_created}
    assert len(resolved_ids) == 1
    # Both previews rewritten to the new customer_id.
    assert previews[0]["quote_in"]["customer_id"] == previews[1][
        "quote_in"
    ]["customer_id"]


# ═════════════════════════════════════════════════════════════
# Test 8 — UnresolvedCustomersError carries new error_code
# ═════════════════════════════════════════════════════════════
def test_unresolved_customers_error_default_error_code():
    exc = UnresolvedCustomersError([
        UnresolvedCustomer(
            source_doc_index=0,
            extracted_customer_name="X",
            pending_customer_id="p",
        ),
    ])
    assert exc.error_code == "customer_requires_manual_resolution"


def test_unresolved_customers_error_custom_error_code_override():
    exc = UnresolvedCustomersError(
        [], error_code="some_other_code",
    )
    assert exc.error_code == "some_other_code"


# ═════════════════════════════════════════════════════════════
# Test 9 — collect_unresolved_customers tags low-conf rows
# ═════════════════════════════════════════════════════════════
def test_collect_unresolved_customers_tags_low_confidence_reason():
    previews = [
        {"source_doc_index": 0, "mapped_target": "quote_in",
          "quote_in": {"customer_id": "PENDING::pid-lowconf",
                        "customer_extraction_confidence": "low",
                        "customer_name": None}},
        {"source_doc_index": 1, "mapped_target": "quote_in",
          "quote_in": {"customer_id": "PENDING::pid-blank",
                        "customer_name": None}},
    ]
    out = collect_unresolved_customers(previews)
    assert len(out) == 2
    by_pid = {u.pending_customer_id: u for u in out}
    assert (
        by_pid["pid-lowconf"].reason
        == "customer_extraction_confidence_low"
    )
    assert by_pid["pid-blank"].reason is None


# ═════════════════════════════════════════════════════════════
# Test 10 — collect_low_confidence_pending_ids walks previews
# ═════════════════════════════════════════════════════════════
def test_collect_low_confidence_pending_ids_walks_both_fields():
    previews = [
        {"source_doc_index": 0, "mapped_target": "quote_in",
          "quote_in": {"customer_id": "PENDING::pid-q",
                        "customer_extraction_confidence": "low"}},
        {"source_doc_index": 1, "mapped_target": "payment_in",
          "payment_in": {"customer_id": "PENDING::pid-p",
                          "customer_extraction_confidence": "low"}},
        {"source_doc_index": 2, "mapped_target": "quote_in",
          "quote_in": {"customer_id": "PENDING::pid-ok"}},
    ]
    out = collect_low_confidence_pending_ids(previews)
    assert out == {"pid-q", "pid-p"}


# ═════════════════════════════════════════════════════════════
# Test 11 — compute_dedup_group_id stable + case-insensitive
# ═════════════════════════════════════════════════════════════
def test_compute_dedup_group_id_stable_across_case_whitespace():
    a = compute_dedup_group_id(
        name="Joe Kail", address="123 Pine", phone="555-1234",
    )
    b = compute_dedup_group_id(
        name="  joe  kail ", address="123 PINE", phone="999",
    )
    assert a == b
    # Different name → different group id.
    c = compute_dedup_group_id(
        name="Someone Else", address="123 Pine", phone="555-1234",
    )
    assert a != c
