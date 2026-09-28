"""FIN-PARITY-C · Feb-2026 — invoice amount_paid recompute
migration test suite.

Locks:

  * Invoice with 1 payment summing to full total →
    ``payment_status=paid``, ``status=accepted``, ``paid_at`` set.
  * Invoice with 2 payments summing to partial → ``partial``,
    status unchanged.
  * Invoice with 0 linked payments (and not already-paid) →
    no-op / no write.
  * Invoice with ``payment_status="paid"`` + 0 payments — NOT
    reconciled (would flip back to unpaid); flagged with a
    ``paid_flag_without_payments`` audit row instead (apply only).
  * Dry-run reports plan; writes nothing to ``db.quotes`` and
    ``db.import_audit``.
  * Apply writes correct fields via the reconciler.
  * Idempotency — second apply run issues zero writes.
  * Tenant isolation.
  * ``--resume-from`` honoured.
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

PFX = "TESTfpCr_"


def _run(coro):
    asyncio.set_event_loop(_LOOP)
    return _LOOP.run_until_complete(coro)


async def _wipe():
    await _DB.quotes.delete_many({"id": {"$regex": f"^{PFX}"}})
    await _DB.payments.delete_many({"id": {"$regex": f"^{PFX}"}})
    await _DB.import_audit.delete_many({
        "$or": [
            {"invoice_id": {"$regex": f"^{PFX}"}},
            {"audit_source": "recompute_amount_paid_v1"},
        ],
    })


@pytest.fixture(autouse=True)
def _clean():
    _run(_wipe())
    yield
    _run(_wipe())


TENANT = f"{PFX}tenant_A"
TENANT_B = f"{PFX}tenant_B"


async def _seed_invoice(
    *,
    invoice_id: Optional[str] = None,
    tenant_id: str = TENANT,
    total: float,
    amount_paid: float = 0.0,
    payment_status: str = "unpaid",
    status: str = "sent",
    paid_at: Optional[str] = None,
) -> str:
    inv_id = invoice_id or f"{PFX}inv_{uuid.uuid4().hex[:10]}"
    doc: Dict[str, Any] = {
        "id": inv_id,
        "tenant_id": tenant_id,
        "doc_type": "invoice",
        "total": total,
        "amount_paid": amount_paid,
        "payment_status": payment_status,
        "status": status,
        "customer_id": f"{PFX}cust_x",
        "customer_name": "Test Customer",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    if paid_at:
        doc["paid_at"] = paid_at
    await _DB.quotes.insert_one(doc)
    return inv_id


async def _seed_payment(
    *,
    tenant_id: str = TENANT,
    invoice_id: str,
    amount: float,
    paid_at: Optional[str] = None,
    deleted_at: Optional[str] = None,
) -> str:
    pay_id = f"{PFX}pay_{uuid.uuid4().hex[:10]}"
    doc: Dict[str, Any] = {
        "id": pay_id,
        "tenant_id": tenant_id,
        "invoice_id": invoice_id,
        "amount": amount,
        "status": "succeeded",
        "paid_at": paid_at or datetime.now(timezone.utc).isoformat(),
    }
    if deleted_at:
        doc["deleted_at"] = deleted_at
    await _DB.payments.insert_one(doc)
    return pay_id


async def _fetch_invoice(inv_id: str) -> Dict[str, Any]:
    return await _DB.quotes.find_one({"id": inv_id}, {"_id": 0})


# ═══════════════════════════════════════════════════════════════════
# §1 · Full-pay: 1 payment == total → paid + accepted + paid_at
# ═══════════════════════════════════════════════════════════════════
def test_apply_full_pay_transitions_paid_accepted_paid_at():
    from migrations.recompute_amount_paid_v1 import run_recompute

    inv_id = _run(_seed_invoice(total=250.0))
    _run(_seed_payment(
        invoice_id=inv_id, amount=250.0,
        paid_at="2026-01-15T10:00:00Z",
    ))

    summary = _run(run_recompute(_DB, tenant_id=TENANT, apply=True))
    assert summary["scanned"] == 1
    assert summary["touched"] == 1
    assert summary["flagged"] == 0
    assert len(summary["reconcile_audit_ids"]) == 1

    fresh = _run(_fetch_invoice(inv_id))
    assert fresh["amount_paid"] == 250.0
    assert fresh["payment_status"] == "paid"
    assert fresh["status"] == "accepted"
    assert fresh["paid_at"] == "2026-01-15T10:00:00Z"


# ═══════════════════════════════════════════════════════════════════
# §2 · Partial: 2 payments summing to partial → partial, status stays
# ═══════════════════════════════════════════════════════════════════
def test_apply_partial_pay_keeps_status_but_flips_payment_status():
    from migrations.recompute_amount_paid_v1 import run_recompute

    inv_id = _run(_seed_invoice(total=500.0, status="sent"))
    _run(_seed_payment(invoice_id=inv_id, amount=100.0))
    _run(_seed_payment(invoice_id=inv_id, amount=150.0))

    _run(run_recompute(_DB, tenant_id=TENANT, apply=True))
    fresh = _run(_fetch_invoice(inv_id))
    assert fresh["amount_paid"] == 250.0
    assert fresh["payment_status"] == "partial"
    # Status stays as-is (not accepted) — the reconciler only
    # promotes on the paid-boundary crossing.
    assert fresh["status"] == "sent"


# ═══════════════════════════════════════════════════════════════════
# §3 · No payments AND not paid — no-op (dry-run reports no change)
# ═══════════════════════════════════════════════════════════════════
def test_zero_payments_unpaid_invoice_is_a_noop():
    from migrations.recompute_amount_paid_v1 import run_recompute

    inv_id = _run(_seed_invoice(
        total=300.0, amount_paid=0.0, payment_status="unpaid",
    ))
    # No payments seeded.
    summary_dry = _run(run_recompute(_DB, tenant_id=TENANT, apply=False))
    assert summary_dry["scanned"] == 1
    assert summary_dry["touched"] == 0
    assert summary_dry["flagged"] == 0

    summary = _run(run_recompute(_DB, tenant_id=TENANT, apply=True))
    assert summary["touched"] == 0
    assert summary["reconcile_audit_ids"] == []
    # Invoice unchanged.
    fresh = _run(_fetch_invoice(inv_id))
    assert fresh["amount_paid"] == 0.0
    assert fresh["payment_status"] == "unpaid"


# ═══════════════════════════════════════════════════════════════════
# §4 · Pathological — paid without payments → NOT flipped, flagged
# ═══════════════════════════════════════════════════════════════════
def test_paid_without_payments_is_flagged_not_flipped():
    from migrations.recompute_amount_paid_v1 import (
        DATA_INTEGRITY_CODE_PAID_WITHOUT_PAYMENTS,
        run_recompute,
    )

    inv_id = _run(_seed_invoice(
        total=400.0,
        amount_paid=0.0,             # <-- inconsistent
        payment_status="paid",       # <-- inconsistent
        status="accepted",
    ))
    # NO payments seeded — the invoice was marked paid without
    # matching db.payments rows (pre-FIN-PARITY-A data).

    summary = _run(run_recompute(_DB, tenant_id=TENANT, apply=True))
    assert summary["scanned"] == 1
    assert summary["touched"] == 0
    assert summary["flagged"] == 1
    assert len(summary["integrity_audit_ids"]) == 1
    assert summary["reconcile_audit_ids"] == []

    # Invoice UNCHANGED — payment_status stays "paid" for operator
    # to review (reconciler would have silently flipped to unpaid).
    fresh = _run(_fetch_invoice(inv_id))
    assert fresh["payment_status"] == "paid"
    assert fresh["amount_paid"] == 0.0
    assert fresh["status"] == "accepted"

    audit_rows = _run(_DB.import_audit.find(
        {"invoice_id": inv_id}
    ).to_list(None))
    assert len(audit_rows) == 1
    assert audit_rows[0]["code"] == DATA_INTEGRITY_CODE_PAID_WITHOUT_PAYMENTS
    assert audit_rows[0]["action"] == "recompute_amount_paid_v1_skip"
    assert audit_rows[0]["audit_source"] == "recompute_amount_paid_v1"


def test_paid_without_payments_dry_run_flags_without_writing_audit():
    """Dry-run counts flagged rows but does NOT emit audit."""
    from migrations.recompute_amount_paid_v1 import run_recompute

    inv_id = _run(_seed_invoice(
        total=400.0, amount_paid=0.0,
        payment_status="paid", status="accepted",
    ))
    summary = _run(run_recompute(_DB, tenant_id=TENANT, apply=False))
    assert summary["flagged"] == 1
    assert summary["integrity_audit_ids"] == []
    audit_rows = _run(_DB.import_audit.find(
        {"invoice_id": inv_id}
    ).to_list(None))
    assert audit_rows == []


# ═══════════════════════════════════════════════════════════════════
# §5 · Dry-run — no db.quotes writes and no audit writes
# ═══════════════════════════════════════════════════════════════════
def test_dry_run_never_writes_to_quotes_or_audit():
    from migrations.recompute_amount_paid_v1 import run_recompute

    inv_id = _run(_seed_invoice(total=250.0))
    _run(_seed_payment(invoice_id=inv_id, amount=250.0))

    summary = _run(run_recompute(_DB, tenant_id=TENANT, apply=False))
    assert summary["touched"] == 1
    assert summary["reconcile_audit_ids"] == []
    assert summary["integrity_audit_ids"] == []

    fresh = _run(_fetch_invoice(inv_id))
    assert fresh["amount_paid"] == 0.0
    assert fresh["payment_status"] == "unpaid"

    audit_rows = _run(_DB.import_audit.find(
        {"invoice_id": inv_id}
    ).to_list(None))
    assert audit_rows == []


# ═══════════════════════════════════════════════════════════════════
# §6 · Idempotency — second apply run issues zero writes
# ═══════════════════════════════════════════════════════════════════
def test_second_apply_run_is_a_noop():
    from migrations.recompute_amount_paid_v1 import run_recompute

    inv_id = _run(_seed_invoice(total=250.0))
    _run(_seed_payment(invoice_id=inv_id, amount=250.0))

    first = _run(run_recompute(_DB, tenant_id=TENANT, apply=True))
    assert first["touched"] == 1
    assert len(first["reconcile_audit_ids"]) == 1

    second = _run(run_recompute(_DB, tenant_id=TENANT, apply=True))
    assert second["touched"] == 0
    assert second["reconcile_audit_ids"] == []

    # Total audit rows for THIS invoice — exactly 1 across both runs.
    audit_rows = _run(_DB.import_audit.find(
        {"invoice_id": inv_id}
    ).to_list(None))
    assert len(audit_rows) == 1


# ═══════════════════════════════════════════════════════════════════
# §7 · Tenant isolation
# ═══════════════════════════════════════════════════════════════════
def test_tenant_isolation_other_tenant_untouched():
    from migrations.recompute_amount_paid_v1 import run_recompute

    inv_a = _run(_seed_invoice(tenant_id=TENANT, total=100.0))
    _run(_seed_payment(tenant_id=TENANT, invoice_id=inv_a, amount=100.0))
    inv_b = _run(_seed_invoice(tenant_id=TENANT_B, total=200.0))
    _run(_seed_payment(tenant_id=TENANT_B, invoice_id=inv_b, amount=200.0))

    summary = _run(run_recompute(_DB, tenant_id=TENANT, apply=True))
    assert summary["scanned"] == 1
    assert summary["touched"] == 1

    fresh_a = _run(_fetch_invoice(inv_a))
    fresh_b = _run(_fetch_invoice(inv_b))
    assert fresh_a["payment_status"] == "paid"
    # Tenant B untouched.
    assert fresh_b["payment_status"] == "unpaid"
    assert fresh_b["amount_paid"] == 0.0


# ═══════════════════════════════════════════════════════════════════
# §8 · Resume-from-last skips lexicographically earlier invoices
# ═══════════════════════════════════════════════════════════════════
def test_resume_from_skips_earlier_invoices():
    from migrations.recompute_amount_paid_v1 import run_recompute

    inv_1 = _run(_seed_invoice(
        invoice_id=f"{PFX}inv_001", total=100.0,
    ))
    inv_2 = _run(_seed_invoice(
        invoice_id=f"{PFX}inv_002", total=200.0,
    ))
    inv_3 = _run(_seed_invoice(
        invoice_id=f"{PFX}inv_003", total=300.0,
    ))
    _run(_seed_payment(invoice_id=inv_1, amount=100.0))
    _run(_seed_payment(invoice_id=inv_2, amount=200.0))
    _run(_seed_payment(invoice_id=inv_3, amount=300.0))

    # Resume from inv_1 — should skip inv_1, process inv_2 + inv_3.
    summary = _run(run_recompute(
        _DB, tenant_id=TENANT, apply=True, resume_from=inv_1,
    ))
    assert summary["scanned"] == 2
    assert summary["touched"] == 2

    # inv_1 unchanged.
    fresh_1 = _run(_fetch_invoice(inv_1))
    assert fresh_1["payment_status"] == "unpaid"
    # inv_2 + inv_3 reconciled.
    for iid in (inv_2, inv_3):
        fresh = _run(_fetch_invoice(iid))
        assert fresh["payment_status"] == "paid"


# ═══════════════════════════════════════════════════════════════════
# §9 · Reconciler audit_source correctly stamped
# ═══════════════════════════════════════════════════════════════════
def test_reconcile_audit_row_stamped_with_migration_source():
    """The reconciler-written audit row must carry
    ``audit_source="recompute_amount_paid_v1"`` so ops can filter
    all rows this migration produced."""
    from migrations.recompute_amount_paid_v1 import (
        AUDIT_SOURCE, run_recompute,
    )

    inv_id = _run(_seed_invoice(total=250.0))
    _run(_seed_payment(invoice_id=inv_id, amount=250.0))
    _run(run_recompute(_DB, tenant_id=TENANT, apply=True))

    audit_rows = _run(_DB.import_audit.find(
        {"invoice_id": inv_id, "action": "invoice_reconciled"}
    ).to_list(None))
    assert len(audit_rows) == 1
    assert audit_rows[0]["audit_source"] == AUDIT_SOURCE
    assert AUDIT_SOURCE == "recompute_amount_paid_v1"


# ═══════════════════════════════════════════════════════════════════
# §10 · Soft-deleted payments excluded from sum
# ═══════════════════════════════════════════════════════════════════
def test_soft_deleted_payments_do_not_count_toward_amount_paid():
    from migrations.recompute_amount_paid_v1 import run_recompute

    inv_id = _run(_seed_invoice(total=300.0))
    _run(_seed_payment(invoice_id=inv_id, amount=100.0))
    _run(_seed_payment(
        invoice_id=inv_id, amount=200.0,
        deleted_at=datetime.now(timezone.utc).isoformat(),
    ))

    _run(run_recompute(_DB, tenant_id=TENANT, apply=True))
    fresh = _run(_fetch_invoice(inv_id))
    # Only the non-deleted $100 counted.
    assert fresh["amount_paid"] == 100.0
    assert fresh["payment_status"] == "partial"


# ═══════════════════════════════════════════════════════════════════
# §11 · Soft-deleted invoices skipped
# ═══════════════════════════════════════════════════════════════════
def test_soft_deleted_invoices_skipped():
    from migrations.recompute_amount_paid_v1 import run_recompute

    inv_id = f"{PFX}inv_{uuid.uuid4().hex[:10]}"
    await_coro = _DB.quotes.insert_one({
        "id": inv_id,
        "tenant_id": TENANT,
        "doc_type": "invoice",
        "total": 100.0,
        "amount_paid": 0.0,
        "payment_status": "unpaid",
        "status": "sent",
        "deleted_at": datetime.now(timezone.utc).isoformat(),
    })
    _run(await_coro)

    summary = _run(run_recompute(_DB, tenant_id=TENANT, apply=True))
    assert summary["scanned"] == 0
    assert summary["touched"] == 0


# ═══════════════════════════════════════════════════════════════════
# §12 · Quotes (non-invoice doc_type) never processed
# ═══════════════════════════════════════════════════════════════════
def test_non_invoice_doc_types_skipped():
    from migrations.recompute_amount_paid_v1 import run_recompute

    quote_id = f"{PFX}q_{uuid.uuid4().hex[:10]}"
    _run(_DB.quotes.insert_one({
        "id": quote_id,
        "tenant_id": TENANT,
        "doc_type": "quote",     # <-- not an invoice
        "total": 500.0,
        "amount_paid": 0.0,
        "payment_status": "unpaid",
        "status": "sent",
    }))

    summary = _run(run_recompute(_DB, tenant_id=TENANT, apply=True))
    assert summary["scanned"] == 0
