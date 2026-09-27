"""Feb-2026 · PDF Importer Sub-phase A — backfill migration tests.

Coverage matrix:
  1. Fresh DB (0 PDF-imported quotes) → migration runs, sentinel
     stamped "completed", 0 rows backfilled.
  2. 3 PDF-imported quotes all missing ``doc_date`` → all 3 get
     ``doc_date = created_at``.
  3. Mixed rows (PDF + non-PDF) → only PDF rows touched.
  4. Rows with existing ``doc_date`` → left untouched; only missing
     values are back-filled.
  5. Idempotency — 2nd run short-circuits via the sentinel.
  6. ``created_at`` is NEVER mutated in any scenario (pre/post
     equality assertion + a query result printed).
  7. Legacy rows without ``imported_from_pdf`` field are NOT
     touched.
  8. Sentinel doc shape — key, completed_at, matched, modified.

The tests run against the shared Mongo instance (mirrors the
existing K41 + backfill test pattern).  Each case scopes its seed
data via a UUID-suffixed ``tenant_id`` so parallel runs against a
shared DB never step on each other.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from dotenv import load_dotenv
from tests._shared_mongo import (
    shared_client as _shared_client,
    shared_db as _shared_db,
)


load_dotenv(Path(__file__).resolve().parent.parent / ".env")

_sync = _shared_client()
_db_sync = _shared_db()


# ═════════════════════════════════════════════════════════════════════
# Test helpers
# ═════════════════════════════════════════════════════════════════════
def _scope() -> str:
    """Unique tenant_id suffix — every test's seed data is prefixed
    with this so cleanup is a single delete_many + the migration
    can't be confused by other tests' rows."""
    return f"pdfdocdate-{uuid.uuid4().hex[:12]}"


def _seed_quote(
    tenant_id: str,
    *,
    created_at: str,
    imported_from_pdf: bool,
    doc_date: object = "__ABSENT__",
) -> str:
    """Insert a synthetic quote row.  ``doc_date="__ABSENT__"`` omits
    the field from the doc entirely (mirroring pre-Sub-phase-A rows)."""
    qid = f"TEST-DD-Q-{uuid.uuid4().hex[:12]}"
    doc = {
        "id": qid,
        "tenant_id": tenant_id,
        "doc_type": "invoice",
        "customer_id": "test-customer",
        "created_at": created_at,
        "line_items": [],
        "total": 100,
    }
    if imported_from_pdf:
        doc["imported_from_pdf"] = True
    if doc_date != "__ABSENT__":
        doc["doc_date"] = doc_date
    _db_sync.quotes.insert_one(doc)
    return qid


async def _run_migration_isolated():
    """Run the migration against a motor async db wrapper.  The
    migration module owns its own logging + sentinel semantics —
    we just invoke ``run(db)`` and return the report."""
    # The migration expects a motor-shaped async db.  Reuse the
    # tests' shared motor connection via ``config.db``.
    from config import db as motor_db
    from services.migrations.pdf_doc_date_backfill_v1 import run
    return await run(motor_db)


def _reset_sentinel() -> None:
    """Delete the migration_status doc so each test runs the
    migration fresh (except the idempotency test that DOES want the
    sentinel to persist between passes)."""
    _db_sync.migration_status.delete_one({"key": "pdf_doc_date_backfill_v1"})


# ═════════════════════════════════════════════════════════════════════
# 1) Fresh DB — no PDF-imported quotes → migration ok, 0 rows
# ═════════════════════════════════════════════════════════════════════
def test_migration_runs_clean_on_empty_pdf_import_set():
    _reset_sentinel()
    try:
        report = asyncio.get_event_loop().run_until_complete(
            _run_migration_isolated(),
        )
        # First-pass result — may include already-existing PDF-imported
        # rows from earlier test seeds that survived; assert on the
        # migration-report shape only, not counts.
        assert report["ok"] is True
        assert report.get("skipped") is False
        assert "matched" in report
        assert "modified" in report
        # Sentinel armed for next run.
        sentinel = _db_sync.migration_status.find_one(
            {"key": "pdf_doc_date_backfill_v1"}, {"_id": 0},
        )
        assert sentinel is not None
        assert sentinel.get("completed_at")
        assert "matched" in sentinel
        assert "modified" in sentinel
    finally:
        _reset_sentinel()


# ═════════════════════════════════════════════════════════════════════
# 2) PDF-imported rows all missing doc_date → all backfilled
# ═════════════════════════════════════════════════════════════════════
def test_migration_backfills_doc_date_from_created_at_for_pdf_rows():
    tenant_id = _scope()
    created_iso = "2015-06-15T00:00:00+00:00"
    qids = [
        _seed_quote(tenant_id, created_at=created_iso,
                    imported_from_pdf=True)
        for _ in range(3)
    ]
    _reset_sentinel()
    try:
        asyncio.get_event_loop().run_until_complete(_run_migration_isolated())
        for qid in qids:
            row = _db_sync.quotes.find_one(
                {"id": qid}, {"_id": 0, "created_at": 1, "doc_date": 1},
            )
            assert row is not None
            assert row.get("doc_date") == created_iso
            # ``created_at`` must be byte-identical to the seed.
            assert row.get("created_at") == created_iso
    finally:
        _db_sync.quotes.delete_many({"id": {"$in": qids}})
        _reset_sentinel()


# ═════════════════════════════════════════════════════════════════════
# 3) Mixed rows — only PDF-imported are touched
# ═════════════════════════════════════════════════════════════════════
def test_migration_does_not_touch_non_pdf_rows():
    tenant_id = _scope()
    non_pdf_id = _seed_quote(
        tenant_id, created_at="2019-01-01T00:00:00+00:00",
        imported_from_pdf=False,
    )
    pdf_id = _seed_quote(
        tenant_id, created_at="2019-01-01T00:00:00+00:00",
        imported_from_pdf=True,
    )
    _reset_sentinel()
    try:
        asyncio.get_event_loop().run_until_complete(_run_migration_isolated())
        non_pdf_row = _db_sync.quotes.find_one({"id": non_pdf_id}, {"_id": 0})
        pdf_row = _db_sync.quotes.find_one({"id": pdf_id}, {"_id": 0})
        # Non-PDF: doc_date still absent (or None if the seed helper
        # set it — the seed did NOT).
        assert non_pdf_row.get("doc_date") is None
        # PDF: doc_date now populated.
        assert pdf_row.get("doc_date") == "2019-01-01T00:00:00+00:00"
    finally:
        _db_sync.quotes.delete_many({"id": {"$in": [non_pdf_id, pdf_id]}})
        _reset_sentinel()


# ═════════════════════════════════════════════════════════════════════
# 4) Existing doc_date values are preserved
# ═════════════════════════════════════════════════════════════════════
def test_migration_preserves_existing_doc_date_values():
    tenant_id = _scope()
    # PDF row WITH doc_date already set to a distinct value.
    with_dd = _seed_quote(
        tenant_id, created_at="2020-01-01T00:00:00+00:00",
        imported_from_pdf=True, doc_date="1999-12-31",
    )
    # PDF row WITHOUT doc_date.
    without_dd = _seed_quote(
        tenant_id, created_at="2020-01-01T00:00:00+00:00",
        imported_from_pdf=True,
    )
    _reset_sentinel()
    try:
        asyncio.get_event_loop().run_until_complete(_run_migration_isolated())
        with_row = _db_sync.quotes.find_one({"id": with_dd}, {"_id": 0})
        without_row = _db_sync.quotes.find_one({"id": without_dd}, {"_id": 0})
        # Existing doc_date preserved.
        assert with_row.get("doc_date") == "1999-12-31"
        # Missing doc_date filled from created_at.
        assert without_row.get("doc_date") == "2020-01-01T00:00:00+00:00"
    finally:
        _db_sync.quotes.delete_many(
            {"id": {"$in": [with_dd, without_dd]}},
        )
        _reset_sentinel()


# ═════════════════════════════════════════════════════════════════════
# 5) Idempotency — 2nd run short-circuits via the sentinel
# ═════════════════════════════════════════════════════════════════════
def test_migration_is_idempotent_second_run_is_noop():
    tenant_id = _scope()
    qid = _seed_quote(
        tenant_id, created_at="2018-03-20T00:00:00+00:00",
        imported_from_pdf=True,
    )
    _reset_sentinel()
    try:
        first = asyncio.get_event_loop().run_until_complete(
            _run_migration_isolated(),
        )
        assert first["ok"] is True
        assert first["skipped"] is False
        # Immediate second run without deleting the sentinel.
        second = asyncio.get_event_loop().run_until_complete(
            _run_migration_isolated(),
        )
        assert second["ok"] is True
        assert second["skipped"] is True
        assert second.get("reason") == "already_ran"
    finally:
        _db_sync.quotes.delete_one({"id": qid})
        _reset_sentinel()


# ═════════════════════════════════════════════════════════════════════
# 6) created_at is NEVER mutated (R1 · A ruling)
# ═════════════════════════════════════════════════════════════════════
def test_migration_never_mutates_created_at():
    """R1 · A — the backfill copies ``created_at`` INTO ``doc_date``
    but leaves ``created_at`` byte-identical.  Assert on the pre/
    post equality of every seeded row's ``created_at``."""
    tenant_id = _scope()
    ca_values = {
        f"TEST-DD-CA-A-{uuid.uuid4().hex[:8]}": "2010-06-15T00:00:00+00:00",
        f"TEST-DD-CA-B-{uuid.uuid4().hex[:8]}": "2005-01-01T12:34:56+00:00",
        f"TEST-DD-CA-C-{uuid.uuid4().hex[:8]}": "2022-11-30T23:59:59+00:00",
    }
    for qid, ca in ca_values.items():
        _db_sync.quotes.insert_one({
            "id": qid, "tenant_id": tenant_id, "doc_type": "invoice",
            "customer_id": "test-c",
            "created_at": ca,
            "imported_from_pdf": True,
            "line_items": [], "total": 100,
        })
    _reset_sentinel()
    try:
        asyncio.get_event_loop().run_until_complete(_run_migration_isolated())
        for qid, expected_ca in ca_values.items():
            row = _db_sync.quotes.find_one(
                {"id": qid}, {"_id": 0, "created_at": 1, "doc_date": 1},
            )
            # Pre-migration ``created_at`` == post-migration ``created_at``.
            assert row["created_at"] == expected_ca, (
                f"created_at MUTATED for {qid} — "
                f"expected {expected_ca}, got {row['created_at']}"
            )
            # And doc_date now mirrors it.
            assert row["doc_date"] == expected_ca
    finally:
        _db_sync.quotes.delete_many({"id": {"$in": list(ca_values.keys())}})
        _reset_sentinel()


# ═════════════════════════════════════════════════════════════════════
# 7) Legacy rows without imported_from_pdf are NOT touched
# ═════════════════════════════════════════════════════════════════════
def test_migration_ignores_rows_missing_imported_from_pdf_flag():
    """Legacy rows written before the ``imported_from_pdf`` flag
    existed are indistinguishable from manual quotes → they must NOT
    be backfilled.  The migration filter uses strict equality on
    True; rows missing the field entirely are excluded."""
    tenant_id = _scope()
    qid = f"TEST-DD-LEGACY-{uuid.uuid4().hex[:8]}"
    _db_sync.quotes.insert_one({
        "id": qid, "tenant_id": tenant_id, "doc_type": "invoice",
        "customer_id": "test-c",
        "created_at": "2014-05-05T00:00:00+00:00",
        # No imported_from_pdf field at all.
        "line_items": [], "total": 100,
    })
    _reset_sentinel()
    try:
        asyncio.get_event_loop().run_until_complete(_run_migration_isolated())
        row = _db_sync.quotes.find_one({"id": qid}, {"_id": 0})
        assert row.get("doc_date") is None
    finally:
        _db_sync.quotes.delete_one({"id": qid})
        _reset_sentinel()


# ═════════════════════════════════════════════════════════════════════
# 8) Sentinel doc shape — key + completed_at + matched + modified
# ═════════════════════════════════════════════════════════════════════
def test_sentinel_document_has_expected_shape():
    tenant_id = _scope()
    qid = _seed_quote(
        tenant_id, created_at="2016-08-08T00:00:00+00:00",
        imported_from_pdf=True,
    )
    _reset_sentinel()
    try:
        report = asyncio.get_event_loop().run_until_complete(
            _run_migration_isolated(),
        )
        sentinel = _db_sync.migration_status.find_one(
            {"key": "pdf_doc_date_backfill_v1"}, {"_id": 0},
        )
        assert sentinel["key"] == "pdf_doc_date_backfill_v1"
        assert isinstance(sentinel["completed_at"], str)
        # Both counts present + non-negative + report-agreeing.
        assert sentinel["matched"] >= 0
        assert sentinel["modified"] >= 0
        assert sentinel["matched"] == report["matched"]
        assert sentinel["modified"] == report["modified"]
        # No error field on a successful pass.
        assert sentinel.get("error") is None or sentinel.get("error") == ""
    finally:
        _db_sync.quotes.delete_one({"id": qid})
        _reset_sentinel()
