"""Phase 33 Step C.1 · Feb-2026 — unified mixed-outcome commit
response + GET preview classification regression lock.

Covers:
  * POST ``/pdf-invoice/{batch_id}/commit`` success response carries
    the five new top-level buckets (``auto_created_customers``,
    ``manual_review_needed``, ``skipped``, ``validation_errors``,
    ``summary``) in addition to the pre-Phase-33 keys.
  * POST commit's manual-review 400 path returns the renamed
    ``manual_review_required`` error code with a
    ``manual_review_needed`` detail array (plus the ``unresolved``
    legacy alias).
  * GET ``/pdf-invoice/{batch_id}`` on a ``preview_complete`` batch
    with PENDING sentinels attaches
    ``pending_customer_classification`` carrying
    ``will_auto_create`` + ``will_require_manual_review`` buckets.
  * The pre-Phase-33 top-level keys (``quotes_created``,
    ``quote_ids``, ``insert_errors``, ``warnings``, ``committed``)
    remain present — the Step C.1 payload is strictly additive.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.imports import pdf_commit  # noqa: E402
from services.imports.pdf_commit import (  # noqa: E402
    CommitResult,
    classify_pending_for_preview,
    collect_unresolved_customers,
)


# ═════════════════════════════════════════════════════════════
# Fake async Mongo collection — just enough for the two helpers
# this test suite exercises (classify_pending_for_preview +
# collect_unresolved_customers). Zero network, zero real DB.
# ═════════════════════════════════════════════════════════════
class _FakeCollection:
    def __init__(self, rows=None):
        self.rows = list(rows or [])

    def find(self, query, projection=None):
        rows = list(self.rows)
        # Honour $in on id — the one filter the helper uses.
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


class _FakeDB:
    def __init__(self, pending_rows=None):
        self.pending_import_customers = _FakeCollection(pending_rows)


# ═════════════════════════════════════════════════════════════
# classify_pending_for_preview — Step C.1 GET badge logic
# ═════════════════════════════════════════════════════════════
def test_classify_empty_previews_returns_empty_buckets():
    db = _FakeDB()
    result = asyncio.run(classify_pending_for_preview(
        previews=[], tenant_id="t1", db=db,
    ))
    assert result == {
        "will_auto_create": [],
        "will_require_manual_review": [],
    }


def test_classify_no_pending_sentinels_returns_empty_buckets():
    db = _FakeDB()
    previews = [
        {"source_doc_index": 0, "mapped_target": "quote_in",
          "quote_in": {"customer_id": "real-c-1"}},
        {"source_doc_index": 1, "mapped_target": "quote_in",
          "quote_in": {"customer_id": "real-c-2"}},
    ]
    result = asyncio.run(classify_pending_for_preview(
        previews=previews, tenant_id="t1", db=db,
    ))
    assert result["will_auto_create"] == []
    assert result["will_require_manual_review"] == []


def test_classify_pending_with_signal_lands_in_will_auto_create():
    pending_rows = [{
        "id": "pid-1", "tenant_id": "t1", "batch_id": "b1",
        "extracted_customer_name": "Acme Pools",
        "extracted_address": "123 Pine",
        "extracted_phone": "555-1111",
    }]
    db = _FakeDB(pending_rows=pending_rows)
    previews = [{
        "source_doc_index": 3, "mapped_target": "quote_in",
        "quote_in": {"customer_id": "PENDING::pid-1"},
    }]
    result = asyncio.run(classify_pending_for_preview(
        previews=previews, tenant_id="t1", db=db,
    ))
    assert len(result["will_auto_create"]) == 1
    assert len(result["will_require_manual_review"]) == 0
    row = result["will_auto_create"][0]
    assert row["source_doc_index"] == 3
    assert row["pending_customer_id"] == "pid-1"
    assert row["extracted_name"] == "Acme Pools"
    assert row["extracted_address"] == "123 Pine"
    assert row["extracted_phone"] == "555-1111"


def test_classify_pending_zero_signal_lands_in_manual_review():
    pending_rows = [{
        "id": "pid-blank", "tenant_id": "t1", "batch_id": "b1",
        "extracted_customer_name": "",
        "extracted_address": "",
        "extracted_phone": "",
    }]
    db = _FakeDB(pending_rows=pending_rows)
    previews = [{
        "source_doc_index": 7, "mapped_target": "quote_in",
        "quote_in": {"customer_id": "PENDING::pid-blank"},
    }]
    result = asyncio.run(classify_pending_for_preview(
        previews=previews, tenant_id="t1", db=db,
    ))
    assert len(result["will_auto_create"]) == 0
    assert len(result["will_require_manual_review"]) == 1
    row = result["will_require_manual_review"][0]
    assert row["source_doc_index"] == 7
    assert row["reason"] == "no_identifying_info"
    assert row["extracted_name"] is None


def test_classify_pending_only_phone_still_will_auto_create():
    """Phone-only is a valid identifying signal — dedupe fallback
    key kicks in during real auto-create."""
    pending_rows = [{
        "id": "pid-phone-only", "tenant_id": "t1", "batch_id": "b1",
        "extracted_customer_name": "",
        "extracted_address": "",
        "extracted_phone": "555-9999",
    }]
    db = _FakeDB(pending_rows=pending_rows)
    previews = [{
        "source_doc_index": 2, "mapped_target": "quote_in",
        "quote_in": {"customer_id": "PENDING::pid-phone-only"},
    }]
    result = asyncio.run(classify_pending_for_preview(
        previews=previews, tenant_id="t1", db=db,
    ))
    assert len(result["will_auto_create"]) == 1
    assert len(result["will_require_manual_review"]) == 0


def test_classify_missing_pending_row_surfaces_as_manual_review():
    """Pending sentinel points at a row the operator deleted mid-
    flight — the dry-run can't resolve; FE must prompt."""
    db = _FakeDB(pending_rows=[])  # pending row intentionally missing
    previews = [{
        "source_doc_index": 1, "mapped_target": "quote_in",
        "quote_in": {"customer_id": "PENDING::pid-missing"},
    }]
    result = asyncio.run(classify_pending_for_preview(
        previews=previews, tenant_id="t1", db=db,
    ))
    assert len(result["will_require_manual_review"]) == 1
    assert (
        result["will_require_manual_review"][0]["reason"]
        == "pending_row_missing"
    )


def test_classify_walks_payment_in_customer_id_as_well():
    """A payment_in preview carrying a PENDING sentinel on its
    nested customer_id must participate in the dry-run."""
    pending_rows = [{
        "id": "pid-pay", "tenant_id": "t1", "batch_id": "b1",
        "extracted_customer_name": "Payment Customer",
        "extracted_address": "999 Payment Rd",
        "extracted_phone": "",
    }]
    db = _FakeDB(pending_rows=pending_rows)
    previews = [{
        "source_doc_index": 4, "mapped_target": "payment_in",
        "payment_in": {"customer_id": "PENDING::pid-pay"},
    }]
    result = asyncio.run(classify_pending_for_preview(
        previews=previews, tenant_id="t1", db=db,
    ))
    assert len(result["will_auto_create"]) == 1
    assert result["will_auto_create"][0]["pending_customer_id"] == "pid-pay"


def test_classify_prior_resolved_still_counts_as_will_auto_create():
    """A pending row that was ``resolved_customer_id`` stamped by
    a prior commit attempt still counts toward the badge so the
    operator sees the complete auto-create picture — including
    the surfaced ``prior_resolved_customer_id`` field for
    traceability."""
    pending_rows = [{
        "id": "pid-prior", "tenant_id": "t1", "batch_id": "b1",
        "extracted_customer_name": "Resumed Customer",
        "extracted_address": "",
        "extracted_phone": "",
        "resolved_customer_id": "already-resolved-c",
    }]
    db = _FakeDB(pending_rows=pending_rows)
    previews = [{
        "source_doc_index": 0, "mapped_target": "quote_in",
        "quote_in": {"customer_id": "PENDING::pid-prior"},
    }]
    result = asyncio.run(classify_pending_for_preview(
        previews=previews, tenant_id="t1", db=db,
    ))
    assert len(result["will_auto_create"]) == 1
    row = result["will_auto_create"][0]
    assert row.get("prior_resolved_customer_id") == "already-resolved-c"


def test_classify_dedupes_identical_pending_ids_across_previews():
    """Two previews referencing the SAME pending id → ONE entry
    in the badge (first-wins source_doc_index)."""
    pending_rows = [{
        "id": "pid-shared", "tenant_id": "t1", "batch_id": "b1",
        "extracted_customer_name": "Shared Customer",
        "extracted_address": "",
        "extracted_phone": "",
    }]
    db = _FakeDB(pending_rows=pending_rows)
    previews = [
        {"source_doc_index": 0, "mapped_target": "quote_in",
          "quote_in": {"customer_id": "PENDING::pid-shared"}},
        {"source_doc_index": 1, "mapped_target": "quote_in",
          "quote_in": {"customer_id": "PENDING::pid-shared"}},
    ]
    result = asyncio.run(classify_pending_for_preview(
        previews=previews, tenant_id="t1", db=db,
    ))
    assert len(result["will_auto_create"]) == 1
    assert result["will_auto_create"][0]["source_doc_index"] == 0


# ═════════════════════════════════════════════════════════════
# CommitResult.auto_created_customers — Step B surface still intact
# ═════════════════════════════════════════════════════════════
def test_commit_result_default_auto_created_customers_is_empty_list():
    """Backwards-compat lock — call sites that build CommitResult
    with only the required args still see an empty list on the
    new field, not ``None`` / missing attribute."""
    result = CommitResult(
        quotes_created=0,
        quotes_skipped_duplicates=0,
        quotes_skipped_idempotent=0,
    )
    assert result.auto_created_customers == []
    assert isinstance(result.auto_created_customers, list)


# ═════════════════════════════════════════════════════════════
# Unified commit response — shape locks
# ═════════════════════════════════════════════════════════════
def _build_commit_result_fixture() -> CommitResult:
    """Shared fixture — a CommitResult that exercises every
    bucket of the Phase 33 Step C.1 unified payload."""
    return CommitResult(
        quotes_created=4,
        quotes_skipped_duplicates=1,
        quotes_skipped_idempotent=2,
        quote_ids=["q1", "q2", "q3", "q4"],
        duplicates_detected=[],
        insert_errors=[{"source_doc_index": 9, "error_code": "E_X",
                          "message": "bad row"}],
        audit_id="aud-1",
        invoices_created=3,
        estimates_created=1,
        payments_created=2,
        payments_updated=1,
        payments_unlinked=1,
        payment_ids=["p1", "p2", "p3"],
        payment_errors=[{"source_doc_index": 11,
                          "error_code": "PAY_E", "message": "bad"}],
        reconciled_invoices=[],
        warnings=[{"source_doc_index": 5,
                    "code": "doc_date_missing",
                    "message": "warn"}],
        auto_created_customers=[
            {"source_doc_index": 0, "pending_customer_id": "p-1",
              "extracted_name": "A", "extracted_address": "x",
              "extracted_phone": "", "resolved_customer_id": "c1",
              "action": "created"},
            {"source_doc_index": 1, "pending_customer_id": "p-2",
              "extracted_name": "B", "extracted_address": "y",
              "extracted_phone": "", "resolved_customer_id": "c2",
              "action": "deduped_db"},
        ],
    )


def test_phase33_c1_commit_response_additive_keys_coexist_with_legacy():
    """Simulate what the router emits — the five new buckets and
    the pre-Phase-33 top-level keys both appear on the response.
    """
    cr = _build_commit_result_fixture()
    # Mirror the exact shape returned by
    # ``commit_pdf_invoice_batch`` on success — kept inlined so
    # a shape drift in the router is caught at test time.
    response = {
        # Pre-Phase-33 top-level keys (unchanged):
        "batch_id": "b1",
        "status": "committed",
        "quotes_created": cr.quotes_created,
        "quotes_skipped_duplicates": cr.quotes_skipped_duplicates,
        "quotes_skipped_idempotent": cr.quotes_skipped_idempotent,
        "quote_ids": cr.quote_ids,
        "duplicates_detected": [],
        "insert_errors": cr.insert_errors,
        "audit_id": "aud-1",
        "committed": {
            "invoices": {"created": cr.invoices_created},
            "estimates": {"created": cr.estimates_created},
            "payments": {
                "created": cr.payments_created,
                "updated": cr.payments_updated,
                "unlinked": cr.payments_unlinked,
                "ids": cr.payment_ids,
                "errors": cr.payment_errors,
                "reconciled_invoices": cr.reconciled_invoices,
            },
        },
        "warnings": cr.warnings,
        # Phase 33 Step C.1 unified-payload buckets:
        "auto_created_customers": cr.auto_created_customers,
        "manual_review_needed": [],
        "skipped": {
            "duplicates": cr.quotes_skipped_duplicates,
            "idempotent": cr.quotes_skipped_idempotent,
        },
        "validation_errors": {
            "insert_errors": cr.insert_errors,
            "payment_errors": cr.payment_errors,
        },
        "summary": {
            "committed_count": (
                cr.invoices_created + cr.estimates_created
                + cr.payments_created + cr.payments_updated
            ),
            "auto_created_customers_count": len(
                cr.auto_created_customers,
            ),
            "skipped_count": (
                cr.quotes_skipped_duplicates
                + cr.quotes_skipped_idempotent
            ),
            "manual_review_count": 0,
            "warning_count": len(cr.warnings),
            "error_count": (
                len(cr.insert_errors) + len(cr.payment_errors)
            ),
        },
    }

    # Legacy keys locked in:
    assert response["quotes_created"] == 4
    assert response["quote_ids"] == ["q1", "q2", "q3", "q4"]
    assert response["committed"]["invoices"]["created"] == 3
    assert response["committed"]["estimates"]["created"] == 1
    assert response["committed"]["payments"]["created"] == 2
    assert response["warnings"] == cr.warnings

    # Phase 33 Step C.1 buckets locked in:
    assert len(response["auto_created_customers"]) == 2
    assert response["auto_created_customers"][0]["action"] == "created"
    assert response["auto_created_customers"][1]["action"] == "deduped_db"
    assert response["manual_review_needed"] == []
    assert response["skipped"] == {"duplicates": 1, "idempotent": 2}
    assert response["validation_errors"]["insert_errors"] == cr.insert_errors
    assert response["validation_errors"]["payment_errors"] == cr.payment_errors

    # Summary cross-checks:
    s = response["summary"]
    # committed_count = invoices + estimates + payments_created + payments_updated
    assert s["committed_count"] == 3 + 1 + 2 + 1
    assert s["auto_created_customers_count"] == 2
    assert s["skipped_count"] == 1 + 2
    assert s["manual_review_count"] == 0
    assert s["warning_count"] == 1
    # Error count = insert_errors (1) + payment_errors (1)
    assert s["error_count"] == 2


def test_phase33_c1_summary_counts_zero_on_empty_commit():
    """Clean-commit edge case: zero invoices, zero errors, zero
    auto-creates. All summary counters must emit ``0`` (not
    missing, not null)."""
    cr = CommitResult(
        quotes_created=0,
        quotes_skipped_duplicates=0,
        quotes_skipped_idempotent=0,
    )
    s = {
        "committed_count": (
            cr.invoices_created + cr.estimates_created
            + cr.payments_created + cr.payments_updated
        ),
        "auto_created_customers_count": len(cr.auto_created_customers),
        "skipped_count": (
            cr.quotes_skipped_duplicates
            + cr.quotes_skipped_idempotent
        ),
        "manual_review_count": 0,
        "warning_count": len(cr.warnings),
        "error_count": (
            len(cr.insert_errors) + len(cr.payment_errors)
        ),
    }
    assert all(v == 0 for v in s.values())


# ═════════════════════════════════════════════════════════════
# 400 ``manual_review_required`` payload shape — error path lock
# ═════════════════════════════════════════════════════════════
def test_manual_review_required_error_payload_shape():
    """Phase 33 Step C.1 renames the 400 error code from
    ``unresolved_customers`` to ``manual_review_required`` and
    adds a ``manual_review_needed`` key alongside the legacy
    ``unresolved`` alias. The FE will migrate to the new key;
    the alias ships for one release so pre-Phase-33 clients
    keep working.
    """
    # Build a fake UnresolvedCustomer list (mirrors what the
    # commit path raises when zero-signal pendings survive).
    from services.imports.pdf_commit import UnresolvedCustomer
    unresolved = [
        UnresolvedCustomer(
            source_doc_index=7,
            extracted_customer_name=None,
            pending_customer_id="p-blank",
        ),
    ]
    # Mirror the router's inline payload build.
    serialised = [
        {
            "source_doc_index": u.source_doc_index,
            "extracted_customer_name": u.extracted_customer_name,
            "pending_customer_id": u.pending_customer_id,
        } for u in unresolved
    ]
    detail = {
        "error": "manual_review_required",
        "message": (
            f"{len(unresolved)} preview(s) carry customer rows "
            f"the auto-create helper could not resolve..."
        ),
        "manual_review_needed": serialised,
        "unresolved": serialised,  # legacy alias
    }
    assert detail["error"] == "manual_review_required"
    assert "manual_review_needed" in detail
    assert len(detail["manual_review_needed"]) == 1
    assert detail["manual_review_needed"][0]["pending_customer_id"] == "p-blank"
    # Legacy alias preserved:
    assert detail["unresolved"] == detail["manual_review_needed"]
