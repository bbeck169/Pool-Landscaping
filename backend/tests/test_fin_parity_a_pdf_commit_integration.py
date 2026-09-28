"""FIN-PARITY-A · Feb-2026 — PDF commit + reconciler integration.

Locks the wiring between ``_commit_payment_previews`` and the
reconciler:

  * Payment committed WITH ``invoice_id`` → linked invoice
    reconciled + summary appears on the commit response's
    ``reconciled_invoices`` array.
  * Payment committed WITHOUT ``invoice_id`` → payment lands
    normally; NO reconcile fires; ``reconciled_invoices`` is
    empty for that payment.
  * Reconcile failure on ONE payment must NOT abort the batch —
    the remaining payments still commit + reconcile.
  * Response envelope shape stability: ``committed.payments``
    now carries a ``reconciled_invoices`` field.
  * Schema guard: ``db.payments`` docs must NOT carry an
    ``amount_cents`` field (PDF-HUB fork lock).
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

PFX = "TESTfpi_"
TENANT = f"{PFX}tenant"


def _run(coro):
    asyncio.set_event_loop(_LOOP)
    return _LOOP.run_until_complete(coro)


async def _wipe():
    await _DB.quotes.delete_many({"id": {"$regex": f"^{PFX}"}})
    await _DB.payments.delete_many({"id": {"$regex": f"^{PFX}"}})
    await _DB.import_audit.delete_many(
        {"$or": [
            {"batch_id": {"$regex": f"^{PFX}"}},
            {"invoice_id": {"$regex": f"^{PFX}"}},
        ]},
    )


@pytest.fixture(autouse=True)
def _clean():
    _run(_wipe())
    yield
    _run(_wipe())


async def _seed_invoice(*, total: float, doc_number: str,
                          amount_paid: float = 0.0,
                          payment_status: str = "unpaid",
                          status: str = "sent") -> str:
    inv_id = f"{PFX}inv_{uuid.uuid4().hex[:10]}"
    await _DB.quotes.insert_one({
        "id": inv_id,
        "tenant_id": TENANT,
        "doc_type": "invoice",
        "doc_number": doc_number,
        "invoice_number": doc_number,
        "total": total,
        "amount_paid": amount_paid,
        "payment_status": payment_status,
        "status": status,
        "customer_id": f"{PFX}cust_1",
        "customer_name": "Test Customer",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    return inv_id


def _payment_preview(*, doc_number: str, amount: float,
                       source_doc_index: int = 0) -> Dict[str, Any]:
    """Build a MapperReport-shaped preview dict for a payment_in."""
    return {
        "source_doc_index": source_doc_index,
        "doc_kind": "payment_receipt",
        "mapped_target": "payment_in",
        "customer_resolution": "resolved",
        "payment_in": {
            "doc_number": doc_number,
            "customer_id": f"{PFX}cust_1",
            "customer_name": "Test Customer",
            "amount_paid": amount,
            "payment_method": "check",
            "payment_reference": "TEST-REF",
            "paid_at": "2026-02-15T10:00:00+00:00",
        },
    }


def _batch(batch_id: str) -> Dict[str, Any]:
    return {
        "id": batch_id,
        "tenant_id": TENANT,
        "source_filename": "fin_parity_test.pdf",
    }


# ═══════════════════════════════════════════════════════════════════
# §1 · Linked payment → invoice reconciled
# ═══════════════════════════════════════════════════════════════════
def test_pdf_commit_with_invoice_link_reconciles():
    from services.imports.pdf_commit import _commit_payment_previews

    inv_id = _run(_seed_invoice(total=100.0, doc_number="INV-FIN-A-1"))
    previews = [_payment_preview(
        doc_number="INV-FIN-A-1", amount=100.0, source_doc_index=0,
    )]
    batch_id = f"{PFX}batch_{uuid.uuid4().hex[:8]}"

    stats = _run(_commit_payment_previews(
        previews=previews,
        batch=_batch(batch_id),
        tenant_id=TENANT,
        operator={"id": "admin-1", "email": "admin@test"},
        commit_at=datetime.now(timezone.utc).isoformat(),
        warnings=[],
        db=_DB,
    ))

    # Payment created + reconciled.
    assert stats["created"] == 1
    assert stats["errors"] == []
    assert len(stats["reconciled_invoices"]) == 1

    rec = stats["reconciled_invoices"][0]
    assert rec["invoice_id"] == inv_id
    assert rec["new_amount_paid"] == 100.0
    assert rec["new_payment_status"] == "paid"
    assert rec["new_status"] == "accepted"
    assert "payment_status: unpaid → paid" in rec["transitions"]
    assert "status: sent → accepted" in rec["transitions"]

    # Invoice row was actually mutated.
    row = _run(_DB.quotes.find_one({"id": inv_id}))
    assert row["payment_status"] == "paid"
    assert row["status"] == "accepted"


# ═══════════════════════════════════════════════════════════════════
# §2 · Unlinked payment → no reconcile fires
# ═══════════════════════════════════════════════════════════════════
def test_pdf_commit_without_invoice_link_does_not_reconcile():
    from services.imports.pdf_commit import _commit_payment_previews

    # No invoice seeded — payment.doc_number won't resolve.
    previews = [_payment_preview(
        doc_number="INV-DOES-NOT-EXIST", amount=42.00,
        source_doc_index=0,
    )]
    batch_id = f"{PFX}batch_{uuid.uuid4().hex[:8]}"

    stats = _run(_commit_payment_previews(
        previews=previews,
        batch=_batch(batch_id),
        tenant_id=TENANT,
        operator={"id": "admin-1", "email": "admin@test"},
        commit_at=datetime.now(timezone.utc).isoformat(),
        warnings=[],
        db=_DB,
    ))

    # Payment lands as unlinked.
    assert stats["created"] == 1
    assert stats["unlinked"] == 1
    # No reconciled_invoices — invoice_id was None.
    assert stats["reconciled_invoices"] == []
    # No errors on the reconcile lane.
    assert all(
        e.get("error_code") != "reconcile_failed"
        for e in stats["errors"]
    )


# ═══════════════════════════════════════════════════════════════════
# §3 · Reconcile failure on one payment doesn't kill the batch
# ═══════════════════════════════════════════════════════════════════
def test_pdf_commit_reconcile_failure_does_not_abort_batch(monkeypatch):
    """Two payments in the batch: the first reconciles fine; the
    second's invoice_id is dropped BETWEEN the doc_number match
    and the reconciler call (simulate via monkeypatched
    reconciler that raises on the second call). Batch must
    commit both payments; second failure lands in stats.errors
    with error_code=reconcile_failed."""
    from services.imports import pdf_commit
    from services.imports.payment_reconciler import (
        reconcile_invoice_after_payment as _real,
        InvoiceNotFoundError,
    )

    inv_a = _run(_seed_invoice(total=100.0, doc_number="INV-A"))
    inv_b = _run(_seed_invoice(total=50.0, doc_number="INV-B"))

    call_count = {"n": 0}

    async def _flaky_reconcile(db, tenant_id, invoice_id, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 2:
            raise RuntimeError("simulated reconcile blow-up")
        return await _real(db, tenant_id, invoice_id, **kwargs)

    # Patch WHERE the import happens — the local import inside
    # _commit_payment_previews imports the symbol fresh each call,
    # so we patch the module-level attr.
    from services.imports import payment_reconciler as _pr_mod
    monkeypatch.setattr(
        _pr_mod, "reconcile_invoice_after_payment", _flaky_reconcile,
    )

    previews = [
        _payment_preview(
            doc_number="INV-A", amount=100.0, source_doc_index=0,
        ),
        _payment_preview(
            doc_number="INV-B", amount=50.0, source_doc_index=1,
        ),
    ]
    batch_id = f"{PFX}batch_{uuid.uuid4().hex[:8]}"

    stats = _run(pdf_commit._commit_payment_previews(
        previews=previews,
        batch=_batch(batch_id),
        tenant_id=TENANT,
        operator={"id": "admin-1", "email": "admin@test"},
        commit_at=datetime.now(timezone.utc).isoformat(),
        warnings=[],
        db=_DB,
    ))

    # Both payments landed.
    assert stats["created"] == 2
    # First reconcile succeeded.
    assert len(stats["reconciled_invoices"]) == 1
    assert stats["reconciled_invoices"][0]["invoice_id"] == inv_a
    # Second reconcile surfaced as a per-row error.
    reconcile_errors = [
        e for e in stats["errors"]
        if e.get("error_code") == "reconcile_failed"
    ]
    assert len(reconcile_errors) == 1
    assert reconcile_errors[0]["source_doc_index"] == 1
    # Invoice B still has its ORIGINAL (unreconciled) state —
    # payment landed but the flip didn't happen. This is the
    # ops-hand-fix-lane per the design spec.
    row_b = _run(_DB.quotes.find_one({"id": inv_b}))
    assert row_b["payment_status"] == "unpaid"  # NOT reconciled
    # Payment row itself is present.
    pay_b = _run(_DB.payments.find_one({"invoice_number": "INV-B"}))
    assert pay_b is not None
    assert pay_b["amount"] == 50.0


# ═══════════════════════════════════════════════════════════════════
# §4 · Response envelope shape
# ═══════════════════════════════════════════════════════════════════
def test_commit_result_carries_reconciled_invoices_field():
    """The ``CommitResult`` dataclass must surface
    ``reconciled_invoices`` so the router response envelope can
    forward it to the FE without hitting Mongo again."""
    from services.imports.pdf_commit import CommitResult

    cr = CommitResult(
        quotes_created=0,
        quotes_skipped_duplicates=0,
        quotes_skipped_idempotent=0,
    )
    assert hasattr(cr, "reconciled_invoices")
    assert cr.reconciled_invoices == []
    # Field is a list of dicts (per ReconcileResult.to_dict).
    cr.reconciled_invoices.append({"invoice_id": "test", "transitions": []})
    assert cr.reconciled_invoices[0]["invoice_id"] == "test"


def test_router_response_includes_reconciled_invoices_key():
    """Source-inspect: the commit response envelope in
    ``routers/imports.py`` must include ``reconciled_invoices``
    inside ``committed.payments``."""
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] / "routers" /
             "imports.py").read_text()
    # Field is forwarded from commit_result into the response.
    assert '"reconciled_invoices": commit_result.reconciled_invoices' in src, (
        "commit response no longer forwards reconciled_invoices "
        "from CommitResult — FE reconcile UI will break"
    )


# ═══════════════════════════════════════════════════════════════════
# §5 · Schema fork guardrail (PDF-HUB lock)
# ═══════════════════════════════════════════════════════════════════
def test_db_payments_docs_do_not_carry_amount_cents():
    """PDF-HUB fork lock: ``db.payments.amount`` stays as a float
    dollars field. If a future phase introduces ``amount_cents``
    (integer cents) on this collection, it must land as a
    schema migration — not as a silent side-effect of PDF-HUB's
    audit or FIN-PARITY-A's wiring."""
    from services.imports.pdf_commit import _commit_payment_previews

    inv_id = _run(_seed_invoice(total=100.0, doc_number="INV-SCHEMA"))
    previews = [_payment_preview(
        doc_number="INV-SCHEMA", amount=19.95, source_doc_index=0,
    )]
    batch_id = f"{PFX}batch_{uuid.uuid4().hex[:8]}"

    _run(_commit_payment_previews(
        previews=previews,
        batch=_batch(batch_id),
        tenant_id=TENANT,
        operator={"id": "admin-1", "email": "admin@test"},
        commit_at=datetime.now(timezone.utc).isoformat(),
        warnings=[],
        db=_DB,
    ))

    pay = _run(_DB.payments.find_one({"invoice_number": "INV-SCHEMA"}))
    assert pay is not None
    # Float dollars field present.
    assert "amount" in pay
    assert isinstance(pay["amount"], float)
    assert pay["amount"] == 19.95
    # NO amount_cents field — PDF-HUB fork lock.
    assert "amount_cents" not in pay, (
        "db.payments.amount_cents field appeared — "
        "schema migration must be a separate phase, not a "
        "side-effect of FIN-PARITY-A"
    )
