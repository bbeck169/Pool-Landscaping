"""Task H · Phase H.2 · Feb-2026 — PDF importer commit + rollback
end-to-end tests.

Locks the following contracts:

* ``POST /api/imports/pdf-invoice/{batch_id}/commit`` — 200 happy
  path, 400 on ``PENDING::`` sentinels, 400 on wrong status, 409
  on duplicates when ``on_duplicate="fail"``.
* ``POST /api/imports/pdf-invoice/{batch_id}/rollback`` — 200
  happy path, collision snapshot preservation when quotes were
  edited after commit, 400 on wrong status.
* ``GET /api/imports/pdf-invoice/{batch_id}/duplicates`` —
  read-only pre-flight duplicate scan.
* Cross-tenant isolation — 404 on every endpoint when the batch
  belongs to another tenant.
* Idempotency — a re-run of commit after a mid-flight failure
  skips already-inserted (batch_id, source_doc_index) pairs.
* Hook suppression — the four customer-facing hooks
  (Zapier / automation / drip / event dispatcher) are NOT
  fired for imported historicals.
* Field preservation — ``doc_number`` becomes ``invoice_number``,
  ``status`` defaults to ``"sent"``, ``paid_at`` preserved from
  ``pending_payment_actions``.
* Audit row shape — every commit + rollback writes exactly one
  ``import_audit`` row with the expected keys.
"""
from __future__ import annotations

import io
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
# Fixtures
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
    """Grab any real customer id on the aquaterra tenant."""
    doc = dbc.customers.find_one(
        {"tenant_id": aquaterra_id}, {"id": 1},
    )
    assert doc is not None, "no customers seeded for aquaterra"
    return doc["id"]


def _seed_batch(dbc, *, tenant_id: str, status: str,
                previews: list, source_filename: str = "test.pdf",
                extra: dict | None = None) -> str:
    """Insert a synthetic import_batches row.  Returns the batch id.
    Every test that touches an in-progress commit uses this helper
    so we can exercise the endpoints without needing to run the
    full extraction pipeline again."""
    batch_id = str(uuid.uuid4())
    now_iso = datetime.now(timezone.utc).isoformat()
    doc = {
        "id": batch_id,
        "tenant_id": tenant_id,
        "status": status,
        "source_filename": source_filename,
        "created_at": now_iso,
        "mapper_previews": previews,
    }
    if extra:
        doc.update(extra)
    dbc.import_batches.insert_one(doc)
    return batch_id


def _preview_matched(*, source_doc_index: int, customer_id: str,
                       doc_number: str, unit_price: float = 100.0,
                       qty: float = 1.0,
                       doc_type: str = "invoice",
                       created_at: str | None = None,
                       paid_at: str | None = None) -> dict:
    """Build a MapperReport-shaped preview with a resolved customer."""
    qi: dict = {
        "customer_id": customer_id,
        "customer_name": "Test Customer",
        "title": f"Import #{doc_number}",
        "doc_type": doc_type,
        "line_items": [
            {"description": "Service", "quantity": qty, "unit_price": unit_price}
        ],
        "tax_rate": 0.0,
        "notes": "auto-imported for h2 tests",
        "doc_number": doc_number,
    }
    if created_at:
        qi["created_at"] = created_at
    preview: dict = {
        "source_doc_index": source_doc_index,
        "doc_kind": doc_type,
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
    if paid_at:
        preview["pending_payment_actions"].append({
            "kind": "record_payment",
            "amount": qty * unit_price,
            "paid_at": paid_at,
            "resolved_by": "phase_h2_commit_path",
        })
    return preview


def _preview_pending(*, source_doc_index: int, pending_uuid: str,
                       doc_number: str = "AUTO-0001") -> dict:
    """Preview with a PENDING:: sentinel."""
    return {
        "source_doc_index": source_doc_index,
        "doc_kind": "invoice",
        "mapped_target": "quote_in",
        "customer_resolution": "pending",
        "pending_customer_id": pending_uuid,
        "quote_in": {
            "customer_id": f"PENDING::{pending_uuid}",
            "customer_name": "Unresolved Customer",
            "title": f"Import #{doc_number}",
            "doc_type": "invoice",
            "line_items": [
                {"description": "Service", "quantity": 1, "unit_price": 50}
            ],
            "tax_rate": 0.0,
            "doc_number": doc_number,
        },
        "errors": [],
        "warnings": [],
    }


def _cleanup_batch(dbc, *, batch_id: str, tenant_id: str) -> None:
    """Idempotent teardown: remove any quotes tagged with this
    batch + the batch row + any audit rows.  Safe to call from
    finally blocks even if the test never wrote anything."""
    dbc.quotes.delete_many(
        {"tenant_id": tenant_id, "import_batch_id": batch_id},
    )
    dbc.import_batches.delete_one({"id": batch_id, "tenant_id": tenant_id})
    dbc.import_audit.delete_many(
        {"tenant_id": tenant_id, "batch_id": batch_id},
    )


# ═════════════════════════════════════════════════════════════
# §1 · Happy path commit
# ═════════════════════════════════════════════════════════════
def test_commit_happy_path(admin_h, aquaterra_id, dbc, customer_id):
    """POST /commit with a preview_complete batch → 200, quotes
    materialised, batch flipped to committed, audit row written."""
    doc_number = f"HP-{uuid.uuid4().hex[:8]}"
    previews = [
        _preview_matched(
            source_doc_index=0, customer_id=customer_id,
            doc_number=doc_number, unit_price=100, qty=2,
        ),
    ]
    batch_id = _seed_batch(
        dbc, tenant_id=aquaterra_id, status="preview_complete",
        previews=previews,
    )
    try:
        r = requests.post(
            f"{API}/imports/pdf-invoice/{batch_id}/commit",
            headers=admin_h, json={}, timeout=15,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "committed"
        assert body["quotes_created"] == 1
        assert body["quotes_skipped_duplicates"] == 0
        assert len(body["quote_ids"]) == 1
        assert body["audit_id"]

        # Persisted quote inspection.
        q = dbc.quotes.find_one(
            {"id": body["quote_ids"][0], "tenant_id": aquaterra_id},
        )
        assert q is not None
        # §A ruling: doc_number → invoice_number, no auto-assign.
        assert q["invoice_number"] == doc_number
        # §A ruling: status defaults to "sent".
        assert q["status"] == "sent"
        # Import provenance stamps.
        assert q["import_batch_id"] == batch_id
        assert q["import_source_doc_index"] == 0
        assert q["import_source_doc_number"] == doc_number
        assert q["imported_from_pdf"] is True
        # Totals recomputed from line items (2 × $100 = $200).
        assert q["subtotal"] == 200.0
        assert q["total"] == 200.0

        # Batch flipped to committed.
        b = dbc.import_batches.find_one({"id": batch_id})
        assert b["status"] == "committed"
        assert b["committed_at"]
        assert b["committed_by_user_id"]

        # Audit row.
        audit = dbc.import_audit.find_one({"id": body["audit_id"]})
        assert audit is not None
        assert audit["action"] == "commit"
        assert audit["tenant_id"] == aquaterra_id
        assert audit["batch_id"] == batch_id
        assert audit["quotes_created"] == 1
    finally:
        _cleanup_batch(dbc, batch_id=batch_id, tenant_id=aquaterra_id)


# ═════════════════════════════════════════════════════════════
# §2 · PENDING sentinel gate
# ═════════════════════════════════════════════════════════════
def test_commit_rejects_pending_sentinels(admin_h, aquaterra_id, dbc,
                                              customer_id):
    """Any preview carrying ``PENDING::<uuid>`` must 400 with
    ``unresolved_customers`` before any DB writes happen."""
    previews = [
        _preview_matched(
            source_doc_index=0, customer_id=customer_id,
            doc_number=f"MIX-{uuid.uuid4().hex[:6]}",
        ),
        _preview_pending(
            source_doc_index=1, pending_uuid=str(uuid.uuid4()),
        ),
    ]
    batch_id = _seed_batch(
        dbc, tenant_id=aquaterra_id, status="preview_complete",
        previews=previews,
    )
    try:
        r = requests.post(
            f"{API}/imports/pdf-invoice/{batch_id}/commit",
            headers=admin_h, json={}, timeout=15,
        )
        assert r.status_code == 422, r.text
        detail = r.json().get("detail") or {}
        # Feb-2026 · auto-create UX ticket — primary error_code is
        # ``customer_requires_manual_resolution``; legacy
        # top-level ``error`` alias ``manual_review_required``
        # is preserved for pre-FE-update consumers.
        assert detail.get("error_code") == (
            "customer_requires_manual_resolution"
        ), detail
        assert detail.get("error") == "manual_review_required", detail
        assert len(detail.get("unresolved") or []) == 1

        # Batch status must be reset to preview_complete so the
        # operator can resolve pendings via H.3 UI and retry.
        b = dbc.import_batches.find_one({"id": batch_id})
        assert b["status"] == "preview_complete"

        # No quotes were inserted.
        n = dbc.quotes.count_documents(
            {"tenant_id": aquaterra_id, "import_batch_id": batch_id},
        )
        assert n == 0
    finally:
        _cleanup_batch(dbc, batch_id=batch_id, tenant_id=aquaterra_id)


# ═════════════════════════════════════════════════════════════
# §3 · Wrong-status guard
# ═════════════════════════════════════════════════════════════
def test_commit_rejects_wrong_status(admin_h, aquaterra_id, dbc,
                                        customer_id):
    """A batch that is not in ``preview_complete`` cannot be
    committed. 400 ``batch_wrong_status``."""
    previews = [_preview_matched(
        source_doc_index=0, customer_id=customer_id,
        doc_number=f"WS-{uuid.uuid4().hex[:6]}",
    )]
    batch_id = _seed_batch(
        dbc, tenant_id=aquaterra_id, status="processing",  # wrong
        previews=previews,
    )
    try:
        r = requests.post(
            f"{API}/imports/pdf-invoice/{batch_id}/commit",
            headers=admin_h, json={}, timeout=15,
        )
        assert r.status_code == 400, r.text
        detail = r.json().get("detail") or {}
        assert detail.get("error") == "batch_wrong_status"
        assert detail.get("current_status") == "processing"
    finally:
        _cleanup_batch(dbc, batch_id=batch_id, tenant_id=aquaterra_id)


# ═════════════════════════════════════════════════════════════
# §4 · Duplicate detection
# ═════════════════════════════════════════════════════════════
def test_commit_skip_duplicates(admin_h, aquaterra_id, dbc, customer_id):
    """When ``on_duplicate=skip`` (default), colliding previews
    are omitted from the insert but the commit succeeds."""
    doc_number = f"DUP-{uuid.uuid4().hex[:6]}"
    # Pre-populate a colliding quote directly.
    pre_id = str(uuid.uuid4())
    dbc.quotes.insert_one({
        "id": pre_id,
        "tenant_id": aquaterra_id,
        "customer_id": customer_id,
        "doc_type": "invoice",
        "import_source_doc_number": doc_number,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    previews = [
        _preview_matched(
            source_doc_index=0, customer_id=customer_id,
            doc_number=doc_number,
        ),
        _preview_matched(
            source_doc_index=1, customer_id=customer_id,
            doc_number=f"UNIQ-{uuid.uuid4().hex[:6]}",
        ),
    ]
    batch_id = _seed_batch(
        dbc, tenant_id=aquaterra_id, status="preview_complete",
        previews=previews,
    )
    try:
        r = requests.post(
            f"{API}/imports/pdf-invoice/{batch_id}/commit",
            headers=admin_h, json={"on_duplicate": "skip"}, timeout=15,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["quotes_created"] == 1
        assert body["quotes_skipped_duplicates"] == 1
        assert len(body["duplicates_detected"]) == 1
        assert body["duplicates_detected"][0]["existing_quote_id"] == pre_id
    finally:
        _cleanup_batch(dbc, batch_id=batch_id, tenant_id=aquaterra_id)
        dbc.quotes.delete_one({"id": pre_id})


def test_commit_fail_on_duplicates(admin_h, aquaterra_id, dbc,
                                       customer_id):
    """``on_duplicate=fail`` must 409 without inserting anything."""
    doc_number = f"FAIL-{uuid.uuid4().hex[:6]}"
    pre_id = str(uuid.uuid4())
    dbc.quotes.insert_one({
        "id": pre_id,
        "tenant_id": aquaterra_id,
        "customer_id": customer_id,
        "doc_type": "invoice",
        "import_source_doc_number": doc_number,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    previews = [
        _preview_matched(
            source_doc_index=0, customer_id=customer_id,
            doc_number=doc_number,
        ),
    ]
    batch_id = _seed_batch(
        dbc, tenant_id=aquaterra_id, status="preview_complete",
        previews=previews,
    )
    try:
        r = requests.post(
            f"{API}/imports/pdf-invoice/{batch_id}/commit",
            headers=admin_h, json={"on_duplicate": "fail"}, timeout=15,
        )
        assert r.status_code == 409, r.text
        detail = r.json().get("detail") or {}
        assert detail.get("error") == "duplicates_detected"
        assert len(detail.get("duplicates") or []) == 1

        # No quotes inserted; batch remains preview_complete.
        b = dbc.import_batches.find_one({"id": batch_id})
        assert b["status"] == "preview_complete"
        n = dbc.quotes.count_documents(
            {"tenant_id": aquaterra_id, "import_batch_id": batch_id},
        )
        assert n == 0
    finally:
        _cleanup_batch(dbc, batch_id=batch_id, tenant_id=aquaterra_id)
        dbc.quotes.delete_one({"id": pre_id})


def test_commit_insert_anyway(admin_h, aquaterra_id, dbc, customer_id):
    """``on_duplicate=insert_anyway`` writes both the colliding
    preview AND the unique one."""
    doc_number = f"FORCE-{uuid.uuid4().hex[:6]}"
    pre_id = str(uuid.uuid4())
    dbc.quotes.insert_one({
        "id": pre_id,
        "tenant_id": aquaterra_id,
        "customer_id": customer_id,
        "doc_type": "invoice",
        "import_source_doc_number": doc_number,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    previews = [
        _preview_matched(
            source_doc_index=0, customer_id=customer_id,
            doc_number=doc_number,
        ),
    ]
    batch_id = _seed_batch(
        dbc, tenant_id=aquaterra_id, status="preview_complete",
        previews=previews,
    )
    try:
        r = requests.post(
            f"{API}/imports/pdf-invoice/{batch_id}/commit",
            headers=admin_h, json={"on_duplicate": "insert_anyway"},
            timeout=15,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["quotes_created"] == 1
        # Duplicates are still recorded even when forced.
        assert len(body["duplicates_detected"]) == 1
    finally:
        _cleanup_batch(dbc, batch_id=batch_id, tenant_id=aquaterra_id)
        dbc.quotes.delete_one({"id": pre_id})


# ═════════════════════════════════════════════════════════════
# §5 · Duplicates pre-flight endpoint
# ═════════════════════════════════════════════════════════════
def test_duplicates_endpoint_readonly(admin_h, aquaterra_id, dbc,
                                          customer_id):
    """GET /duplicates is read-only — status never flips."""
    doc_number = f"PREFLIGHT-{uuid.uuid4().hex[:6]}"
    pre_id = str(uuid.uuid4())
    dbc.quotes.insert_one({
        "id": pre_id,
        "tenant_id": aquaterra_id,
        "customer_id": customer_id,
        "doc_type": "invoice",
        "import_source_doc_number": doc_number,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    previews = [
        _preview_matched(
            source_doc_index=0, customer_id=customer_id,
            doc_number=doc_number,
        ),
    ]
    batch_id = _seed_batch(
        dbc, tenant_id=aquaterra_id, status="preview_complete",
        previews=previews,
    )
    try:
        r = requests.get(
            f"{API}/imports/pdf-invoice/{batch_id}/duplicates",
            headers=admin_h, timeout=10,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["duplicate_count"] == 1
        assert body["duplicates"][0]["doc_number"] == doc_number

        # No state change on the batch.
        b = dbc.import_batches.find_one({"id": batch_id})
        assert b["status"] == "preview_complete"
    finally:
        _cleanup_batch(dbc, batch_id=batch_id, tenant_id=aquaterra_id)
        dbc.quotes.delete_one({"id": pre_id})


# ═════════════════════════════════════════════════════════════
# §6 · Rollback happy path
# ═════════════════════════════════════════════════════════════
def test_rollback_happy_path(admin_h, aquaterra_id, dbc, customer_id):
    """After a successful commit, rollback deletes every quote
    tagged with the batch id and flips status to rolled_back."""
    doc_number = f"RB-{uuid.uuid4().hex[:6]}"
    previews = [_preview_matched(
        source_doc_index=0, customer_id=customer_id,
        doc_number=doc_number, unit_price=42, qty=3,
    )]
    batch_id = _seed_batch(
        dbc, tenant_id=aquaterra_id, status="preview_complete",
        previews=previews,
    )
    try:
        r = requests.post(
            f"{API}/imports/pdf-invoice/{batch_id}/commit",
            headers=admin_h, json={}, timeout=15,
        )
        assert r.status_code == 200
        quote_id = r.json()["quote_ids"][0]
        assert dbc.quotes.find_one({"id": quote_id}) is not None

        rr = requests.post(
            f"{API}/imports/pdf-invoice/{batch_id}/rollback",
            headers=admin_h, timeout=15,
        )
        assert rr.status_code == 200, rr.text
        body = rr.json()
        assert body["status"] == "rolled_back"
        assert body["quotes_deleted"] == 1
        assert body["collision_count"] == 0

        # Doc is gone.
        assert dbc.quotes.find_one({"id": quote_id}) is None
        # Audit row exists.
        audit = dbc.import_audit.find_one({"id": body["audit_id"]})
        assert audit is not None
        assert audit["action"] == "rollback"
        assert audit["quotes_deleted"] == 1
    finally:
        _cleanup_batch(dbc, batch_id=batch_id, tenant_id=aquaterra_id)


# ═════════════════════════════════════════════════════════════
# §7 · Rollback collision snapshotting
# ═════════════════════════════════════════════════════════════
def test_rollback_collision_snapshotting(admin_h, aquaterra_id, dbc,
                                              customer_id):
    """If a quote was edited after commit (updated_at >
    committed_at), the rollback audit row must snapshot the full
    doc for recovery-via-replay."""
    doc_number = f"COL-{uuid.uuid4().hex[:6]}"
    previews = [_preview_matched(
        source_doc_index=0, customer_id=customer_id,
        doc_number=doc_number, unit_price=100, qty=1,
    )]
    batch_id = _seed_batch(
        dbc, tenant_id=aquaterra_id, status="preview_complete",
        previews=previews,
    )
    try:
        r = requests.post(
            f"{API}/imports/pdf-invoice/{batch_id}/commit",
            headers=admin_h, json={}, timeout=15,
        )
        assert r.status_code == 200
        quote_id = r.json()["quote_ids"][0]

        # Simulate a post-commit edit: bump updated_at past the
        # committed_at timestamp on the batch row.
        b = dbc.import_batches.find_one({"id": batch_id})
        # Advance updated_at ~1s past committed_at.
        commit_iso = b["committed_at"]
        commit_dt = datetime.fromisoformat(commit_iso)
        later = (commit_dt.replace(tzinfo=commit_dt.tzinfo) if commit_dt.tzinfo
                 else commit_dt.replace(tzinfo=timezone.utc))
        later_iso = later.isoformat()  # exact same second is not "greater"
        # bump by 60s to ensure strict >.
        from datetime import timedelta
        later_iso = (later + timedelta(seconds=60)).isoformat()
        dbc.quotes.update_one(
            {"id": quote_id},
            {"$set": {"updated_at": later_iso, "customer_edit": "manual bump"}},
        )

        rr = requests.post(
            f"{API}/imports/pdf-invoice/{batch_id}/rollback",
            headers=admin_h, timeout=15,
        )
        assert rr.status_code == 200, rr.text
        body = rr.json()
        assert body["collision_count"] == 1

        audit = dbc.import_audit.find_one({"id": body["audit_id"]})
        assert audit is not None
        collisions = audit.get("collisions") or []
        assert len(collisions) == 1
        # Snapshot must contain enough to reconstruct.
        assert collisions[0]["id"] == quote_id
        assert collisions[0]["customer_edit"] == "manual bump"
    finally:
        _cleanup_batch(dbc, batch_id=batch_id, tenant_id=aquaterra_id)


# ═════════════════════════════════════════════════════════════
# §8 · Cross-tenant isolation
# ═════════════════════════════════════════════════════════════
def test_cross_tenant_commit_404(admin_h, dbc):
    """A batch that exists but belongs to another tenant MUST
    return 404 (not 403) so the endpoint cannot be used as a
    tenant-membership probe."""
    other_tenant = f"h2-cross-tenant-{uuid.uuid4().hex[:8]}"
    batch_id = _seed_batch(
        dbc, tenant_id=other_tenant, status="preview_complete",
        previews=[],
    )
    try:
        r = requests.post(
            f"{API}/imports/pdf-invoice/{batch_id}/commit",
            headers=admin_h, json={}, timeout=10,
        )
        assert r.status_code == 404, r.text
        assert (r.json().get("detail") or {}).get("error") == "batch_not_found"

        rr = requests.post(
            f"{API}/imports/pdf-invoice/{batch_id}/rollback",
            headers=admin_h, timeout=10,
        )
        assert rr.status_code == 404, rr.text
        assert (rr.json().get("detail") or {}).get("error") == "batch_not_found"

        dr = requests.get(
            f"{API}/imports/pdf-invoice/{batch_id}/duplicates",
            headers=admin_h, timeout=10,
        )
        assert dr.status_code == 404, dr.text
    finally:
        dbc.import_batches.delete_one({"id": batch_id})


# ═════════════════════════════════════════════════════════════
# §9 · Idempotency (re-run commit skips already-inserted)
# ═════════════════════════════════════════════════════════════
def test_commit_idempotent_re_run(admin_h, aquaterra_id, dbc,
                                       customer_id):
    """After a successful commit, forcing a re-run (by manually
    resetting the batch back to preview_complete) must skip the
    already-inserted (batch_id, source_doc_index) pair without
    duplicating rows."""
    doc_number = f"IDEMP-{uuid.uuid4().hex[:6]}"
    previews = [_preview_matched(
        source_doc_index=0, customer_id=customer_id,
        doc_number=doc_number,
    )]
    batch_id = _seed_batch(
        dbc, tenant_id=aquaterra_id, status="preview_complete",
        previews=previews,
    )
    try:
        # First commit.
        r1 = requests.post(
            f"{API}/imports/pdf-invoice/{batch_id}/commit",
            headers=admin_h, json={}, timeout=15,
        )
        assert r1.status_code == 200
        first_quote = r1.json()["quote_ids"][0]

        # Simulate a mid-flight retry: reset status but leave the
        # already-inserted quote in place.
        dbc.import_batches.update_one(
            {"id": batch_id},
            {"$set": {"status": "preview_complete"}},
        )

        r2 = requests.post(
            f"{API}/imports/pdf-invoice/{batch_id}/commit",
            headers=admin_h, json={}, timeout=15,
        )
        assert r2.status_code == 200, r2.text
        body = r2.json()
        # The already-present doc index should be skipped.
        assert body["quotes_created"] == 0
        assert body["quotes_skipped_idempotent"] == 1

        # No duplicate row.
        n = dbc.quotes.count_documents(
            {"tenant_id": aquaterra_id, "import_batch_id": batch_id},
        )
        assert n == 1
        # Original doc still intact.
        assert dbc.quotes.find_one({"id": first_quote}) is not None
    finally:
        _cleanup_batch(dbc, batch_id=batch_id, tenant_id=aquaterra_id)


# ═════════════════════════════════════════════════════════════
# §10 · paid_at preservation from pending_payment_actions
# ═════════════════════════════════════════════════════════════
def test_commit_preserves_paid_at(admin_h, aquaterra_id, dbc,
                                       customer_id):
    """When a preview carries a ``record_payment`` action, the
    committed quote must persist the ``paid_at`` ISO string
    verbatim so downstream reports (AR aging, cash flow) see the
    historical timestamp."""
    doc_number = f"PAID-{uuid.uuid4().hex[:6]}"
    historical_paid = "2024-06-15T14:30:00+00:00"
    previews = [_preview_matched(
        source_doc_index=0, customer_id=customer_id,
        doc_number=doc_number, unit_price=250, qty=1,
        paid_at=historical_paid,
    )]
    batch_id = _seed_batch(
        dbc, tenant_id=aquaterra_id, status="preview_complete",
        previews=previews,
    )
    try:
        r = requests.post(
            f"{API}/imports/pdf-invoice/{batch_id}/commit",
            headers=admin_h, json={}, timeout=15,
        )
        assert r.status_code == 200
        q = dbc.quotes.find_one({"id": r.json()["quote_ids"][0]})
        assert q["paid_at"] == historical_paid
    finally:
        _cleanup_batch(dbc, batch_id=batch_id, tenant_id=aquaterra_id)


# ═════════════════════════════════════════════════════════════
# §11 · Customer-hook suppression (regression guard)
# ═════════════════════════════════════════════════════════════
def test_commit_does_not_fire_customer_hooks(admin_h, aquaterra_id,
                                                 dbc, customer_id):
    """§A ruling: imported historicals MUST NOT emit the four
    customer-facing hooks (Zapier / automation / drip / event
    dispatcher).  Since our commit path in
    ``services.imports.pdf_commit`` does NOT import the four
    hook modules at all (we bypassed ``create_quote`` entirely),
    this test is a source-code guard: we AST-parse the module
    and assert none of the four hook modules appear in any
    ``import`` / ``from ... import`` statement.

    Docstrings referencing the hook names by way of *documenting
    what we deliberately do NOT do* are allowed — this guard is
    behavioural, not lexical."""
    import ast
    src = (Path("/app/backend/services/imports/pdf_commit.py")
            .read_text())
    tree = ast.parse(src)
    banned_modules = {
        "services.lumino_zapier_dispatcher",
        "services.automation_engine",
        "services.marketing.drip_events",
        "services.marketing.event_dispatcher",
    }
    imported_modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                imported_modules.add(a.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported_modules.add(node.module)
    hit = imported_modules & banned_modules
    assert not hit, (
        f"pdf_commit.py must not import customer-facing hook modules; "
        f"found: {sorted(hit)}"
    )


# ═════════════════════════════════════════════════════════════
# §12 · Non-admin caller is rejected
# ═════════════════════════════════════════════════════════════
def test_commit_requires_admin(aquaterra_id, dbc, customer_id):
    """Technicians / customers cannot commit or rollback.  403
    (or 401) — require_admin gate."""
    # Log in as a technician.
    r = requests.post(
        f"{API}/auth/login",
        json={"email": "mike@aquaterra.com", "password": "password123"},
        timeout=20,
    )
    r.raise_for_status()
    tech_h = {"Authorization": f"Bearer {r.json()['access_token']}"}

    previews = [_preview_matched(
        source_doc_index=0, customer_id=customer_id,
        doc_number=f"NOADMIN-{uuid.uuid4().hex[:6]}",
    )]
    batch_id = _seed_batch(
        dbc, tenant_id=aquaterra_id, status="preview_complete",
        previews=previews,
    )
    try:
        r = requests.post(
            f"{API}/imports/pdf-invoice/{batch_id}/commit",
            headers=tech_h, json={}, timeout=10,
        )
        assert r.status_code in (401, 403), r.text

        rr = requests.post(
            f"{API}/imports/pdf-invoice/{batch_id}/rollback",
            headers=tech_h, timeout=10,
        )
        assert rr.status_code in (401, 403), rr.text
    finally:
        _cleanup_batch(dbc, batch_id=batch_id, tenant_id=aquaterra_id)


# ═════════════════════════════════════════════════════════════
# §13 · Rollback rejects non-committed batches
# ═════════════════════════════════════════════════════════════
def test_rollback_rejects_wrong_status(admin_h, aquaterra_id, dbc,
                                            customer_id):
    """POST /rollback against a batch in preview_complete → 400
    ``batch_not_committed``."""
    previews = [_preview_matched(
        source_doc_index=0, customer_id=customer_id,
        doc_number=f"NORB-{uuid.uuid4().hex[:6]}",
    )]
    batch_id = _seed_batch(
        dbc, tenant_id=aquaterra_id, status="preview_complete",
        previews=previews,
    )
    try:
        r = requests.post(
            f"{API}/imports/pdf-invoice/{batch_id}/rollback",
            headers=admin_h, timeout=10,
        )
        assert r.status_code == 400, r.text
        assert (r.json().get("detail") or {}).get("error") == "batch_not_committed"
    finally:
        _cleanup_batch(dbc, batch_id=batch_id, tenant_id=aquaterra_id)


# ═════════════════════════════════════════════════════════════
# §14 · Invalid on_duplicate value → 400
# ═════════════════════════════════════════════════════════════
def test_commit_rejects_invalid_on_duplicate(admin_h, aquaterra_id, dbc,
                                                customer_id):
    """A bogus ``on_duplicate`` value must be caught at the router
    with 400 ``invalid_on_duplicate``."""
    previews = [_preview_matched(
        source_doc_index=0, customer_id=customer_id,
        doc_number=f"BOGUS-{uuid.uuid4().hex[:6]}",
    )]
    batch_id = _seed_batch(
        dbc, tenant_id=aquaterra_id, status="preview_complete",
        previews=previews,
    )
    try:
        r = requests.post(
            f"{API}/imports/pdf-invoice/{batch_id}/commit",
            headers=admin_h, json={"on_duplicate": "banana"}, timeout=10,
        )
        assert r.status_code == 400, r.text
        assert (r.json().get("detail") or {}).get("error") == "invalid_on_duplicate"
    finally:
        _cleanup_batch(dbc, batch_id=batch_id, tenant_id=aquaterra_id)


# ═════════════════════════════════════════════════════════════
# §15 · Persisted quote provenance fields
# ═════════════════════════════════════════════════════════════
def test_commit_stamps_all_provenance_fields(admin_h, aquaterra_id,
                                                dbc, customer_id):
    """The persisted quote MUST carry every import-provenance
    field the H.2 spec locked in so future audits / rollbacks /
    dedup queries all resolve deterministically."""
    doc_number = f"PROV-{uuid.uuid4().hex[:6]}"
    previews = [_preview_matched(
        source_doc_index=7, customer_id=customer_id,
        doc_number=doc_number, unit_price=99, qty=1,
    )]
    batch_id = _seed_batch(
        dbc, tenant_id=aquaterra_id, status="preview_complete",
        previews=previews,
    )
    try:
        r = requests.post(
            f"{API}/imports/pdf-invoice/{batch_id}/commit",
            headers=admin_h, json={}, timeout=15,
        )
        assert r.status_code == 200
        q = dbc.quotes.find_one({"id": r.json()["quote_ids"][0]})
        # Provenance stamps.
        assert q["import_batch_id"] == batch_id
        assert q["import_source_doc_index"] == 7
        assert q["import_source_doc_number"] == doc_number
        assert q["imported_from_pdf"] is True
        assert q["imported_at"]
        assert q["imported_by_user_id"]
    finally:
        _cleanup_batch(dbc, batch_id=batch_id, tenant_id=aquaterra_id)
