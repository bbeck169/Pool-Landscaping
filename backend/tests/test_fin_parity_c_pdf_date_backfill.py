"""FIN-PARITY-C · Feb-2026 — backfill migration test suite.

Locks:

  * Dry-run reports planned changes; issues zero writes.
  * Apply writes the missing date fields onto the correct target
    (``quote_in`` or ``payment_in``) using ``derive_pdf_dates``.
  * Already-populated rows are no-ops (idempotent).
  * ``payment_in`` receipts backfill ``paid_at`` from
    ``doc_date`` when the extractor didn't capture ``paid_at``.
  * Tenant isolation — a run scoped to tenant A does not touch
    tenant B's batches even when the tenants have same-shape
    rows.
  * ``--resume-from`` honours the checkpoint (skips every batch
    id <= the value passed).
  * Audit — one ``db.import_audit`` row per batch touched, only
    written under ``--apply``.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest
from dotenv import dotenv_values
from motor.motor_asyncio import AsyncIOMotorClient

_TEST_DIR = Path(__file__).resolve().parent
_BE = dotenv_values(_TEST_DIR.parent / ".env")
MONGO_URL = _BE.get("MONGO_URL") or os.environ.get("MONGO_URL")
DB_NAME = _BE.get("DB_NAME") or os.environ.get("DB_NAME")

_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)
_MC = AsyncIOMotorClient(MONGO_URL, io_loop=_LOOP)
_DB = _MC[DB_NAME]

PFX = "TESTfpC_"


def _run(coro):
    asyncio.set_event_loop(_LOOP)
    return _LOOP.run_until_complete(coro)


async def _wipe():
    await _DB.import_batches.delete_many({"id": {"$regex": f"^{PFX}"}})
    await _DB.import_audit.delete_many({"batch_id": {"$regex": f"^{PFX}"}})


@pytest.fixture(autouse=True)
def _clean():
    _run(_wipe())
    yield
    _run(_wipe())


TENANT = f"{PFX}tenant_A"
TENANT_B = f"{PFX}tenant_B"


def _make_extracted(
    *,
    doc_kind: str = "invoice",
    source_doc_index: int = 0,
    doc_date: Optional[str] = None,
    due_date: Optional[str] = None,
    paid_at: Optional[str] = None,
    total: float = 100.0,
) -> Dict[str, Any]:
    """Minimal ExtractedDocument-shaped dict (JSON-mode)."""
    return {
        "doc_kind": doc_kind,
        "source_doc_index": source_doc_index,
        "doc_date": doc_date,
        "due_date": due_date,
        "paid_at": paid_at,
        "customer_name": "Test Customer",
        "doc_number": f"DOC-{source_doc_index}",
        "grand_total": total,
        "total_due": total,
        "amount_paid": 0.0,
        "line_items": [],
    }


def _make_preview(
    *,
    mapped_target: str = "quote_in",
    source_doc_index: int = 0,
    doc_date: Optional[str] = None,
    due_date: Optional[str] = None,
    paid_at: Optional[str] = None,
    total: float = 100.0,
) -> Dict[str, Any]:
    """Minimal MapperReport-shaped dict."""
    dk = (
        "payment_receipt" if mapped_target == "payment_in" else "invoice"
    )
    report = {
        "source_doc_index": source_doc_index,
        "doc_kind": dk,
        "mapped_target": mapped_target,
        "customer_resolution": "matched",
        "quote_in": None,
        "payment_in": None,
        "pending_payment_actions": [],
        "warnings": [],
        "errors": [],
    }
    if mapped_target == "quote_in":
        qi: Dict[str, Any] = {
            "customer_id": "cust-x",
            "doc_type": "invoice",
            "doc_number": f"DOC-{source_doc_index}",
            "total_due": total,
            "grand_total": total,
        }
        if doc_date is not None:
            qi["doc_date"] = doc_date
        if due_date is not None:
            qi["due_date"] = due_date
        if paid_at is not None:
            qi["paid_at"] = paid_at
        report["quote_in"] = qi
    elif mapped_target == "payment_in":
        pi: Dict[str, Any] = {
            "customer_id": "cust-x",
            "doc_number": f"DOC-{source_doc_index}",
            "amount_paid": total,
        }
        if paid_at is not None:
            pi["paid_at"] = paid_at
        if doc_date is not None:
            pi["doc_date"] = doc_date
        report["payment_in"] = pi
    return report


async def _seed_batch(
    *,
    batch_id: str,
    tenant_id: str = TENANT,
    extracted: Optional[List[Dict[str, Any]]] = None,
    previews: Optional[List[Dict[str, Any]]] = None,
) -> str:
    await _DB.import_batches.insert_one({
        "id": batch_id,
        "tenant_id": tenant_id,
        "status": "preview_complete",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "extracted_documents_full": extracted or [],
        "mapper_previews": previews or [],
    })
    return batch_id


async def _fetch_batch(batch_id: str) -> Dict[str, Any]:
    return await _DB.import_batches.find_one(
        {"id": batch_id}, {"_id": 0},
    )


# ═══════════════════════════════════════════════════════════════════
# §1 · Dry-run reports planned changes, issues zero writes
# ═══════════════════════════════════════════════════════════════════
def test_dry_run_reports_change_and_writes_nothing():
    from migrations.backfill_pdf_dates_v1 import run_backfill

    bid = f"{PFX}b_{uuid.uuid4().hex[:8]}"
    _run(_seed_batch(
        batch_id=bid,
        extracted=[_make_extracted(
            doc_date="2026-01-15", due_date="2026-02-15",
        )],
        previews=[_make_preview(mapped_target="quote_in")],
    ))

    summary = _run(run_backfill(_DB, tenant_id=TENANT, apply=False))
    assert summary["scanned"] == 1
    assert summary["touched"] == 1
    assert summary["fields_written"] == 2  # doc_date + due_date
    assert summary["audit_ids"] == []

    # Nothing actually written.
    fresh = _run(_fetch_batch(bid))
    qi = fresh["mapper_previews"][0]["quote_in"]
    assert qi.get("doc_date") is None
    assert qi.get("due_date") is None
    audit_rows = _run(_DB.import_audit.find(
        {"batch_id": bid}
    ).to_list(None))
    assert audit_rows == []


# ═══════════════════════════════════════════════════════════════════
# §2 · Apply writes to quote_in + one audit row per batch
# ═══════════════════════════════════════════════════════════════════
def test_apply_writes_dates_onto_quote_in_and_audit_row():
    from migrations.backfill_pdf_dates_v1 import run_backfill

    bid = f"{PFX}b_{uuid.uuid4().hex[:8]}"
    _run(_seed_batch(
        batch_id=bid,
        extracted=[_make_extracted(
            doc_kind="invoice",
            doc_date="2026-01-15", due_date="2026-02-15",
            paid_at="2026-01-20",
        )],
        previews=[_make_preview(mapped_target="quote_in")],
    ))

    summary = _run(run_backfill(_DB, tenant_id=TENANT, apply=True))
    assert summary["touched"] == 1
    assert summary["fields_written"] == 3  # doc_date + due_date + paid_at
    assert len(summary["audit_ids"]) == 1

    fresh = _run(_fetch_batch(bid))
    qi = fresh["mapper_previews"][0]["quote_in"]
    assert qi["doc_date"] == "2026-01-15"
    assert qi["due_date"] == "2026-02-15"
    assert qi["paid_at"] == "2026-01-20"
    assert fresh.get("backfill_pdf_dates_v1_applied_at") is not None

    audit_rows = _run(_DB.import_audit.find(
        {"batch_id": bid}
    ).to_list(None))
    assert len(audit_rows) == 1
    assert audit_rows[0]["action"] == "backfill_pdf_dates_v1"
    assert audit_rows[0]["field_count"] == 3


# ═══════════════════════════════════════════════════════════════════
# §3 · Row with only total, no dates — gets doc_date populated
# ═══════════════════════════════════════════════════════════════════
def test_row_with_only_total_and_no_dates_gets_doc_date_populated():
    from migrations.backfill_pdf_dates_v1 import run_backfill

    bid = f"{PFX}b_{uuid.uuid4().hex[:8]}"
    _run(_seed_batch(
        batch_id=bid,
        # Extractor captured doc_date but no due_date / paid_at.
        extracted=[_make_extracted(
            doc_date="2026-03-01", due_date=None, paid_at=None,
        )],
        previews=[_make_preview(mapped_target="quote_in")],
    ))

    _run(run_backfill(_DB, tenant_id=TENANT, apply=True))
    fresh = _run(_fetch_batch(bid))
    qi = fresh["mapper_previews"][0]["quote_in"]
    assert qi["doc_date"] == "2026-03-01"
    # due_date + paid_at stayed unset (extractor didn't have them).
    assert qi.get("due_date") is None
    assert qi.get("paid_at") is None


# ═══════════════════════════════════════════════════════════════════
# §4 · Already fully-populated → no-op (dry-run + apply)
# ═══════════════════════════════════════════════════════════════════
def test_already_populated_row_is_a_noop_on_dry_run_and_apply():
    from migrations.backfill_pdf_dates_v1 import run_backfill

    bid = f"{PFX}b_{uuid.uuid4().hex[:8]}"
    _run(_seed_batch(
        batch_id=bid,
        extracted=[_make_extracted(
            doc_date="2026-01-15", due_date="2026-02-15",
        )],
        previews=[_make_preview(
            mapped_target="quote_in",
            doc_date="2026-01-15", due_date="2026-02-15",
        )],
    ))

    # Dry-run
    dry = _run(run_backfill(_DB, tenant_id=TENANT, apply=False))
    assert dry["touched"] == 0
    assert dry["fields_written"] == 0

    # Apply
    ap = _run(run_backfill(_DB, tenant_id=TENANT, apply=True))
    assert ap["touched"] == 0
    assert ap["audit_ids"] == []
    fresh = _run(_fetch_batch(bid))
    assert fresh.get("backfill_pdf_dates_v1_applied_at") is None


# ═══════════════════════════════════════════════════════════════════
# §5 · Payment receipt — paid_at derived from doc_date fallback
# ═══════════════════════════════════════════════════════════════════
def test_payment_receipt_missing_paid_at_falls_back_to_doc_date():
    from migrations.backfill_pdf_dates_v1 import run_backfill

    bid = f"{PFX}b_{uuid.uuid4().hex[:8]}"
    _run(_seed_batch(
        batch_id=bid,
        extracted=[_make_extracted(
            doc_kind="payment_receipt",
            doc_date="2026-04-10",
            # Extractor didn't capture paid_at — expect the
            # backfill to derive it from doc_date, matching
            # ``_build_payment_in``.
            paid_at=None,
        )],
        previews=[_make_preview(mapped_target="payment_in")],
    ))

    _run(run_backfill(_DB, tenant_id=TENANT, apply=True))
    fresh = _run(_fetch_batch(bid))
    pi = fresh["mapper_previews"][0]["payment_in"]
    assert pi["paid_at"] == "2026-04-10"
    assert pi["doc_date"] == "2026-04-10"
    # payment_in never carries due_date — never introduced.
    assert "due_date" not in pi


def test_payment_receipt_explicit_paid_at_beats_doc_date():
    from migrations.backfill_pdf_dates_v1 import run_backfill

    bid = f"{PFX}b_{uuid.uuid4().hex[:8]}"
    _run(_seed_batch(
        batch_id=bid,
        extracted=[_make_extracted(
            doc_kind="payment_receipt",
            doc_date="2026-04-10",
            paid_at="2026-04-11",  # different day
        )],
        previews=[_make_preview(mapped_target="payment_in")],
    ))

    _run(run_backfill(_DB, tenant_id=TENANT, apply=True))
    fresh = _run(_fetch_batch(bid))
    pi = fresh["mapper_previews"][0]["payment_in"]
    assert pi["paid_at"] == "2026-04-11"  # explicit wins


# ═══════════════════════════════════════════════════════════════════
# §6 · Estimate — paid_at never written even if stray in extractor
# ═══════════════════════════════════════════════════════════════════
def test_estimate_never_gets_paid_at_backfilled():
    from migrations.backfill_pdf_dates_v1 import run_backfill

    bid = f"{PFX}b_{uuid.uuid4().hex[:8]}"
    est_preview = _make_preview(mapped_target="quote_in")
    est_preview["doc_kind"] = "estimate"
    est_preview["quote_in"]["doc_type"] = "quote"

    _run(_seed_batch(
        batch_id=bid,
        extracted=[_make_extracted(
            doc_kind="estimate",
            doc_date="2026-05-01", due_date="2026-06-01",
            # Extractor misclassified — a stray paid_at on an
            # estimate must NOT propagate to quote_in.
            paid_at="2026-05-02",
        )],
        previews=[est_preview],
    ))

    _run(run_backfill(_DB, tenant_id=TENANT, apply=True))
    fresh = _run(_fetch_batch(bid))
    qi = fresh["mapper_previews"][0]["quote_in"]
    assert qi["doc_date"] == "2026-05-01"
    assert qi["due_date"] == "2026-06-01"
    assert qi.get("paid_at") is None


# ═══════════════════════════════════════════════════════════════════
# §7 · Tenant isolation
# ═══════════════════════════════════════════════════════════════════
def test_tenant_isolation_other_tenants_untouched():
    from migrations.backfill_pdf_dates_v1 import run_backfill

    bid_a = f"{PFX}b_A_{uuid.uuid4().hex[:8]}"
    bid_b = f"{PFX}b_B_{uuid.uuid4().hex[:8]}"

    for bid, tid in [(bid_a, TENANT), (bid_b, TENANT_B)]:
        _run(_seed_batch(
            batch_id=bid, tenant_id=tid,
            extracted=[_make_extracted(
                doc_date="2026-01-15", due_date="2026-02-15",
            )],
            previews=[_make_preview(mapped_target="quote_in")],
        ))

    _run(run_backfill(_DB, tenant_id=TENANT, apply=True))

    # Tenant A: backfilled.
    fresh_a = _run(_fetch_batch(bid_a))
    assert fresh_a["mapper_previews"][0]["quote_in"]["doc_date"] == "2026-01-15"
    # Tenant B: untouched.
    fresh_b = _run(_fetch_batch(bid_b))
    qi_b = fresh_b["mapper_previews"][0]["quote_in"]
    assert qi_b.get("doc_date") is None
    # No audit row for B either.
    audit_b = _run(_DB.import_audit.find({"batch_id": bid_b}).to_list(None))
    assert audit_b == []


# ═══════════════════════════════════════════════════════════════════
# §8 · Resume-from checkpoint honoured
# ═══════════════════════════════════════════════════════════════════
def test_resume_from_last_skips_earlier_batches():
    from migrations.backfill_pdf_dates_v1 import run_backfill

    # Use lexicographically ordered ids so we can predict skip.
    bid_1 = f"{PFX}b_001_{uuid.uuid4().hex[:6]}"
    bid_2 = f"{PFX}b_002_{uuid.uuid4().hex[:6]}"
    bid_3 = f"{PFX}b_003_{uuid.uuid4().hex[:6]}"

    for bid in (bid_1, bid_2, bid_3):
        _run(_seed_batch(
            batch_id=bid,
            extracted=[_make_extracted(doc_date="2026-01-15")],
            previews=[_make_preview(mapped_target="quote_in")],
        ))

    # Resume from bid_1 — should process bid_2 + bid_3 only.
    summary = _run(run_backfill(
        _DB, tenant_id=TENANT, apply=True, resume_from=bid_1,
    ))
    assert summary["scanned"] == 2
    assert summary["touched"] == 2

    # bid_1 stayed None (never touched).
    fresh_1 = _run(_fetch_batch(bid_1))
    assert fresh_1["mapper_previews"][0]["quote_in"].get("doc_date") is None
    # bid_2 + bid_3 got the doc_date.
    for bid in (bid_2, bid_3):
        fresh = _run(_fetch_batch(bid))
        assert fresh["mapper_previews"][0]["quote_in"]["doc_date"] == "2026-01-15"


# ═══════════════════════════════════════════════════════════════════
# §9 · Idempotent — second apply is a no-op
# ═══════════════════════════════════════════════════════════════════
def test_second_apply_run_is_a_noop():
    from migrations.backfill_pdf_dates_v1 import run_backfill

    bid = f"{PFX}b_{uuid.uuid4().hex[:8]}"
    _run(_seed_batch(
        batch_id=bid,
        extracted=[_make_extracted(
            doc_date="2026-01-15", due_date="2026-02-15",
        )],
        previews=[_make_preview(mapped_target="quote_in")],
    ))

    first = _run(run_backfill(_DB, tenant_id=TENANT, apply=True))
    assert first["touched"] == 1
    assert len(first["audit_ids"]) == 1

    second = _run(run_backfill(_DB, tenant_id=TENANT, apply=True))
    assert second["touched"] == 0
    assert second["fields_written"] == 0
    assert second["audit_ids"] == []

    # Only ONE audit row across both runs.
    audit_rows = _run(_DB.import_audit.find(
        {"batch_id": bid, "action": "backfill_pdf_dates_v1"}
    ).to_list(None))
    assert len(audit_rows) == 1


# ═══════════════════════════════════════════════════════════════════
# §10 · Zero writes when extractor also missing the field
# ═══════════════════════════════════════════════════════════════════
def test_zero_writes_when_extractor_also_missing_field():
    """If the extractor didn't capture a value either, the field
    stays None on the preview — the backfill can't invent data."""
    from migrations.backfill_pdf_dates_v1 import run_backfill

    bid = f"{PFX}b_{uuid.uuid4().hex[:8]}"
    _run(_seed_batch(
        batch_id=bid,
        # Extractor captured nothing.
        extracted=[_make_extracted(
            doc_date=None, due_date=None, paid_at=None,
        )],
        previews=[_make_preview(mapped_target="quote_in")],
    ))

    summary = _run(run_backfill(_DB, tenant_id=TENANT, apply=True))
    assert summary["touched"] == 0
    assert summary["audit_ids"] == []


# ═══════════════════════════════════════════════════════════════════
# §11 · Multiple previews in one batch — all backfilled atomically
# ═══════════════════════════════════════════════════════════════════
def test_multiple_previews_in_one_batch_backfilled_one_audit_row():
    from migrations.backfill_pdf_dates_v1 import run_backfill

    bid = f"{PFX}b_{uuid.uuid4().hex[:8]}"
    _run(_seed_batch(
        batch_id=bid,
        extracted=[
            _make_extracted(
                source_doc_index=0,
                doc_date="2026-01-15", due_date="2026-02-15",
            ),
            _make_extracted(
                source_doc_index=1,
                doc_kind="payment_receipt",
                doc_date="2026-01-20",
                paid_at="2026-01-21",
            ),
        ],
        previews=[
            _make_preview(mapped_target="quote_in", source_doc_index=0),
            _make_preview(mapped_target="payment_in", source_doc_index=1),
        ],
    ))

    summary = _run(run_backfill(_DB, tenant_id=TENANT, apply=True))
    assert summary["touched"] == 1
    # quote_in: doc_date + due_date + (paid_at N/A since extractor
    # paid_at is None on invoice). payment_in: paid_at + doc_date.
    assert summary["fields_written"] == 4

    # One audit row per batch — not per preview.
    audit_rows = _run(_DB.import_audit.find(
        {"batch_id": bid}
    ).to_list(None))
    assert len(audit_rows) == 1
    assert audit_rows[0]["field_count"] == 4


# ═══════════════════════════════════════════════════════════════════
# §12 · plan_batch_changes is pure (used by dry-run reporting)
# ═══════════════════════════════════════════════════════════════════
def test_plan_batch_changes_is_pure_no_mutation():
    """The dry-run reporter must not mutate the caller's dict —
    proves the migration is safe to re-invoke without re-fetch."""
    from migrations.backfill_pdf_dates_v1 import plan_batch_changes

    batch = {
        "id": "b1",
        "tenant_id": TENANT,
        "extracted_documents_full": [
            _make_extracted(doc_date="2026-01-15"),
        ],
        "mapper_previews": [
            _make_preview(mapped_target="quote_in"),
        ],
    }
    pre_snapshot = batch["mapper_previews"][0].get("quote_in", {}).copy()

    new_previews, changes = plan_batch_changes(batch)

    # Original untouched.
    assert batch["mapper_previews"][0]["quote_in"] == pre_snapshot
    # New previews contain the update.
    assert new_previews[0]["quote_in"]["doc_date"] == "2026-01-15"
    assert changes[0]["field"] == "doc_date"
    assert changes[0]["new_value"] == "2026-01-15"
