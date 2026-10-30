"""Feb-2026 · FIN-PAID-STATUS-PARITY · Commit 1c pytest coverage.

Operator spec:
  (1) Backfill on fixture with 3 stuck rows → all flip to ``paid``,
      ``previous_status_before_paid`` carries old.
  (2) Re-run migration → zero updates (idempotent).
  (3) Void/cancelled/refunded rows → untouched.

Plus one guard case for crumb preservation on a row that already
carries ``previous_status_before_paid`` from a prior half-run.

Live-DB integration pattern (``pymongo`` sync) matches the shipped
style of ``test_invoice_edit_metadata_bypass_beta.py`` and the §3
cases added to the FIN-PARITY suite in Commit 1a.
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest
from dotenv import load_dotenv
from pymongo import MongoClient


load_dotenv(Path(__file__).resolve().parent.parent / ".env")

MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]

_PFX = "TESTbfp_"
_TENANT_A = f"{_PFX}tenant_a"
_TENANT_B = f"{_PFX}tenant_b"


_sync_client = MongoClient(MONGO_URL)
_sync_db = _sync_client[DB_NAME]


def _wipe() -> None:
    _sync_db.quotes.delete_many({"id": {"$regex": f"^{_PFX}"}})
    _sync_db.migration_runs.delete_many(
        {"migration": "backfill_paid_invoice_status_v1",
         "tenant_id": {"$regex": f"^{_PFX}"}},
    )


@pytest.fixture(autouse=True)
def _clean():
    _wipe()
    yield
    _wipe()


def _seed_stuck(tenant_id: str, prior_status: str,
                 crumb: str | None = None) -> str:
    """Seed a row in the stuck state — payment_status='paid' but
    status != 'paid'. Optional ``crumb`` writes a pre-existing
    ``previous_status_before_paid`` to exercise the half-run guard."""
    inv_id = f"{_PFX}inv_{uuid.uuid4().hex[:10]}"
    doc = {
        "id": inv_id,
        "tenant_id": tenant_id,
        "doc_type": "invoice",
        "total": 100.0,
        "amount_paid": 100.0,
        "payment_status": "paid",
        "status": prior_status,
    }
    if crumb is not None:
        doc["previous_status_before_paid"] = crumb
    _sync_db.quotes.insert_one(doc)
    return inv_id


def _run_backfill(
    *, tenant_id: str | None = None, dry_run: bool = True,
):
    import asyncio
    from motor.motor_asyncio import AsyncIOMotorClient
    from migrations.backfill_paid_invoice_status_v1 import (
        backfill_paid_invoice_status,
    )
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        mc = AsyncIOMotorClient(MONGO_URL, io_loop=loop)
        mdb = mc[DB_NAME]
        return loop.run_until_complete(
            backfill_paid_invoice_status(
                mdb,
                tenant_id=tenant_id,
                dry_run=dry_run,
            ),
        )
    finally:
        loop.close()


# ═══════════════════════════════════════════════════════════════════
# §1 · Operator-spec case (1) — three stuck rows all flip + crumbs
# ═══════════════════════════════════════════════════════════════════
def test_backfill_flips_three_stuck_rows_and_writes_crumbs():
    """3 stuck rows with distinct prior statuses — each flips to
    ``paid`` and gets a crumb carrying its OWN prior status.
    Count of rows written matches, and the audit row lands in
    ``migration_runs`` with the right counts."""
    id_sent = _seed_stuck(_TENANT_A, "sent")
    id_accepted = _seed_stuck(_TENANT_A, "accepted")
    id_issued = _seed_stuck(_TENANT_A, "issued")

    # Dry-run first — should show matched=3, modified=0.
    dry = _run_backfill(tenant_id=_TENANT_A, dry_run=True)
    assert dry == {
        "matched": 3,
        "modified": 0,
        "crumbs_written": 0,
        "dry_run": True,
        "tenant_id": _TENANT_A,
    }
    # No DB mutation on dry-run.
    assert _sync_db.quotes.find_one({"id": id_sent})["status"] == "sent"

    # Real run.
    real = _run_backfill(tenant_id=_TENANT_A, dry_run=False)
    assert real["matched"] == 3
    assert real["modified"] == 3
    assert real["crumbs_written"] == 3
    assert real["dry_run"] is False
    assert real["tenant_id"] == _TENANT_A

    # Row-by-row verification — each carries ITS OWN prior status.
    for inv_id, prior in [
        (id_sent, "sent"),
        (id_accepted, "accepted"),
        (id_issued, "issued"),
    ]:
        row = _sync_db.quotes.find_one({"id": inv_id})
        assert row["status"] == "paid", (
            f"{inv_id} did not flip: {row['status']!r}"
        )
        assert row["previous_status_before_paid"] == prior, (
            f"{inv_id} crumb drift: "
            f"{row['previous_status_before_paid']!r} vs {prior!r}"
        )
        assert "backfilled_at" in row
        assert row["backfilled_by"] == "backfill_paid_invoice_status_v1"
        # payment_status is untouched.
        assert row["payment_status"] == "paid"

    # Audit trail.
    audit = _sync_db.migration_runs.find_one({
        "migration": "backfill_paid_invoice_status_v1",
        "tenant_id": _TENANT_A,
    })
    assert audit is not None
    assert audit["matched"] == 3
    assert audit["modified"] == 3
    assert audit["crumbs_written"] == 3
    assert "ran_at" in audit


# ═══════════════════════════════════════════════════════════════════
# §2 · Operator-spec case (2) — re-run is idempotent
# ═══════════════════════════════════════════════════════════════════
def test_backfill_rerun_is_idempotent():
    """After a successful run, a second invocation must report
    ``matched=0, modified=0``."""
    _seed_stuck(_TENANT_A, "sent")
    _seed_stuck(_TENANT_A, "accepted")

    first = _run_backfill(tenant_id=_TENANT_A, dry_run=False)
    assert first["matched"] == 2
    assert first["modified"] == 2

    second = _run_backfill(tenant_id=_TENANT_A, dry_run=False)
    assert second["matched"] == 0, (
        f"second run should be no-op: {second!r}"
    )
    assert second["modified"] == 0
    assert second["crumbs_written"] == 0
    # Both runs wrote one audit row each.
    audits = list(_sync_db.migration_runs.find({
        "migration": "backfill_paid_invoice_status_v1",
        "tenant_id": _TENANT_A,
    }))
    assert len(audits) == 2


# ═══════════════════════════════════════════════════════════════════
# §3 · Operator-spec case (3) — terminal-non-paid rows untouched
# ═══════════════════════════════════════════════════════════════════
def test_backfill_leaves_terminal_non_paid_rows_untouched():
    """Rows with status in (void, cancelled, refunded) MUST stay
    put even if their payment_status reads 'paid' from the
    pre-refund state. The refund flow owns that lifecycle; this
    backfill must never compound a bad state."""
    id_void = _seed_stuck(_TENANT_A, "void")
    id_cancelled = _seed_stuck(_TENANT_A, "cancelled")
    id_refunded = _seed_stuck(_TENANT_A, "refunded")
    # Plus one legitimate stuck row to prove the backfill IS
    # running (not silently skipping everything).
    id_sent = _seed_stuck(_TENANT_A, "sent")

    real = _run_backfill(tenant_id=_TENANT_A, dry_run=False)
    assert real["matched"] == 1, (
        f"terminal rows leaked into match set: {real!r}"
    )
    assert real["modified"] == 1

    # The three terminal rows are untouched.
    for inv_id, expected_status in [
        (id_void, "void"),
        (id_cancelled, "cancelled"),
        (id_refunded, "refunded"),
    ]:
        row = _sync_db.quotes.find_one({"id": inv_id})
        assert row["status"] == expected_status
        assert "previous_status_before_paid" not in row
        assert "backfilled_at" not in row

    # The legitimate stuck row flipped.
    row = _sync_db.quotes.find_one({"id": id_sent})
    assert row["status"] == "paid"
    assert row["previous_status_before_paid"] == "sent"


# ═══════════════════════════════════════════════════════════════════
# §4 · Half-run crumb preservation guard
# ═══════════════════════════════════════════════════════════════════
def test_backfill_preserves_existing_crumb_on_resume():
    """If a row already carries ``previous_status_before_paid``
    from a prior half-run (e.g., a partial backfill that got
    interrupted after the crumb write but before the status
    flip), the backfill must flip ``status`` to ``"paid"`` BUT
    must NOT clobber the existing crumb. A future refund-restore
    flow needs the ORIGINAL pre-paid status, not an intermediate
    value."""
    # Row carries a pre-existing crumb — the half-run scenario.
    inv_id = _seed_stuck(_TENANT_A, "accepted", crumb="sent")

    real = _run_backfill(tenant_id=_TENANT_A, dry_run=False)
    assert real["matched"] == 1
    assert real["modified"] == 1
    # crumb was NOT re-written since one already existed.
    assert real["crumbs_written"] == 0

    row = _sync_db.quotes.find_one({"id": inv_id})
    assert row["status"] == "paid"
    # Original crumb preserved — NOT clobbered to "accepted".
    assert row["previous_status_before_paid"] == "sent"


# ═══════════════════════════════════════════════════════════════════
# §5 · Tenant scoping — tenant_id filter honoured
# ═══════════════════════════════════════════════════════════════════
def test_backfill_tenant_scoping_isolates_tenants():
    """Passing ``tenant_id=A`` must leave tenant B's stuck rows
    alone. Cross-tenant leak would be a P0 regression."""
    id_a = _seed_stuck(_TENANT_A, "sent")
    id_b = _seed_stuck(_TENANT_B, "sent")

    real = _run_backfill(tenant_id=_TENANT_A, dry_run=False)
    assert real["matched"] == 1
    assert real["modified"] == 1

    # A flipped, B untouched.
    assert _sync_db.quotes.find_one({"id": id_a})["status"] == "paid"
    assert _sync_db.quotes.find_one({"id": id_b})["status"] == "sent"
    assert "previous_status_before_paid" not in _sync_db.quotes.find_one(
        {"id": id_b},
    )
