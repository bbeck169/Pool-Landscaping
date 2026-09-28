"""FIN-PARITY-A · Feb-2026 — Reconciler unit tests.

Locks the ``reconcile_invoice_after_payment`` contract:

  * Zero payments → payment_status=unpaid, amount_paid=0.
  * Partial payment → payment_status=partial, status unchanged.
  * Full payment → payment_status=paid, status=accepted, paid_at set.
  * Overpay → payment_status=paid, status=accepted, amount_paid
    capped at total (mirrors ``record_payment``).
  * Float tolerance ($99.998 on $100) → paid (within 0.01).
  * Float tolerance ($99.98 on $100) → partial (outside 0.01).
  * Idempotency — second call = same result modulo timestamp.
  * Tenant isolation — other tenant's payments never contaminate.
  * Audit row written on every state-changing reconciliation.
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

# Test prefix so the autouse teardown scopes deletes.
PFX = "TESTfp_"


def _run(coro):
    asyncio.set_event_loop(_LOOP)
    return _LOOP.run_until_complete(coro)


async def _seed_invoice(
    *,
    tenant_id: str,
    total: float,
    amount_paid: float = 0.0,
    payment_status: str = "unpaid",
    status: str = "sent",
    paid_at: Optional[str] = None,
) -> str:
    """Insert a synthetic invoice row and return its id."""
    inv_id = f"{PFX}inv_{uuid.uuid4().hex[:10]}"
    doc: Dict[str, Any] = {
        "id": inv_id,
        "tenant_id": tenant_id,
        "doc_type": "invoice",
        "total": total,
        "amount_paid": amount_paid,
        "payment_status": payment_status,
        "status": status,
        "customer_id": f"{PFX}cust_{uuid.uuid4().hex[:6]}",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    if paid_at:
        doc["paid_at"] = paid_at
    await _DB.quotes.insert_one(doc)
    return inv_id


async def _seed_payment(
    *,
    tenant_id: str,
    invoice_id: Optional[str],
    amount: float,
    paid_at: Optional[str] = None,
    deleted_at: Optional[str] = None,
) -> str:
    pid = f"{PFX}pay_{uuid.uuid4().hex[:10]}"
    doc: Dict[str, Any] = {
        "id": pid,
        "tenant_id": tenant_id,
        "amount": amount,
        "status": "succeeded",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    if invoice_id is not None:
        doc["invoice_id"] = invoice_id
    if paid_at:
        doc["paid_at"] = paid_at
    if deleted_at:
        doc["deleted_at"] = deleted_at
    await _DB.payments.insert_one(doc)
    return pid


async def _wipe():
    await _DB.quotes.delete_many({"id": {"$regex": f"^{PFX}"}})
    await _DB.payments.delete_many({"id": {"$regex": f"^{PFX}"}})
    await _DB.import_audit.delete_many(
        {"invoice_id": {"$regex": f"^{PFX}"}}
    )


@pytest.fixture(autouse=True)
def _clean():
    _run(_wipe())
    yield
    _run(_wipe())


TENANT = f"{PFX}tenant_A"
TENANT_B = f"{PFX}tenant_B"


# ═══════════════════════════════════════════════════════════════════
# §1 · The 3-way status rule
# ═══════════════════════════════════════════════════════════════════
def test_zero_payments_yields_unpaid():
    from services.imports.payment_reconciler import (
        reconcile_invoice_after_payment,
    )
    inv_id = _run(_seed_invoice(tenant_id=TENANT, total=100.0))
    # No payments at all — reconcile must land unpaid + no
    # transitions (invoice already unpaid on seed).
    result = _run(
        reconcile_invoice_after_payment(_DB, TENANT, inv_id)
    )
    assert result.new_amount_paid == 0.0
    assert result.new_payment_status == "unpaid"
    assert result.new_status == "sent"
    assert result.transitions == []


def test_partial_payment_yields_partial_status():
    from services.imports.payment_reconciler import (
        reconcile_invoice_after_payment,
    )
    inv_id = _run(_seed_invoice(tenant_id=TENANT, total=100.0))
    _run(_seed_payment(
        tenant_id=TENANT, invoice_id=inv_id, amount=50.0,
    ))
    result = _run(
        reconcile_invoice_after_payment(_DB, TENANT, inv_id)
    )
    assert result.new_amount_paid == 50.0
    assert result.new_payment_status == "partial"
    assert result.new_status == "sent"  # NOT accepted
    assert "payment_status: unpaid → partial" in result.transitions
    assert "amount_paid: 0.00 → 50.00" in result.transitions


def test_full_payment_yields_paid_accepted_and_paid_at():
    from services.imports.payment_reconciler import (
        reconcile_invoice_after_payment,
    )
    inv_id = _run(_seed_invoice(tenant_id=TENANT, total=100.0))
    _run(_seed_payment(
        tenant_id=TENANT, invoice_id=inv_id, amount=100.0,
        paid_at="2026-02-15T12:00:00+00:00",
    ))
    result = _run(
        reconcile_invoice_after_payment(_DB, TENANT, inv_id)
    )
    assert result.new_amount_paid == 100.0
    assert result.new_payment_status == "paid"
    assert result.new_status == "accepted"
    assert "status: sent → accepted" in result.transitions

    # Verify the invoice row was actually updated.
    row = _run(_DB.quotes.find_one({"id": inv_id}))
    assert row["payment_status"] == "paid"
    assert row["status"] == "accepted"
    assert row["amount_paid"] == 100.0
    # paid_at inherited from the earliest linked payment.
    assert row.get("paid_at") == "2026-02-15T12:00:00+00:00"


def test_overpay_caps_amount_paid_at_total():
    """``record_payment`` caps at total via ``min(paid, total)``.
    The reconciler mirrors that so the persisted ``amount_paid``
    never exceeds ``total``."""
    from services.imports.payment_reconciler import (
        reconcile_invoice_after_payment,
    )
    inv_id = _run(_seed_invoice(tenant_id=TENANT, total=100.0))
    _run(_seed_payment(
        tenant_id=TENANT, invoice_id=inv_id, amount=120.0,
    ))
    result = _run(
        reconcile_invoice_after_payment(_DB, TENANT, inv_id)
    )
    # persisted / new_amount_paid capped at total.
    assert result.new_amount_paid == 100.0
    assert result.new_payment_status == "paid"
    assert result.new_status == "accepted"
    row = _run(_DB.quotes.find_one({"id": inv_id}))
    assert row["amount_paid"] == 100.0


# ═══════════════════════════════════════════════════════════════════
# §2 · Float tolerance (matches record_payment @ 0.01)
# ═══════════════════════════════════════════════════════════════════
def test_within_tolerance_yields_paid():
    """``99.998`` on a $100 invoice is inside the 0.01 tolerance
    band ⇒ fully paid. Matches ``record_payment``'s ``paid >=
    total - 0.01`` rule."""
    from services.imports.payment_reconciler import (
        reconcile_invoice_after_payment,
    )
    inv_id = _run(_seed_invoice(tenant_id=TENANT, total=100.0))
    _run(_seed_payment(
        tenant_id=TENANT, invoice_id=inv_id, amount=99.998,
    ))
    result = _run(
        reconcile_invoice_after_payment(_DB, TENANT, inv_id)
    )
    assert result.new_payment_status == "paid"
    assert result.new_status == "accepted"


def test_outside_tolerance_yields_partial():
    """``99.98`` on a $100 invoice is OUTSIDE 0.01 tolerance ⇒
    partial. Guards the tolerance boundary from silent widening."""
    from services.imports.payment_reconciler import (
        reconcile_invoice_after_payment,
    )
    inv_id = _run(_seed_invoice(tenant_id=TENANT, total=100.0))
    _run(_seed_payment(
        tenant_id=TENANT, invoice_id=inv_id, amount=99.98,
    ))
    result = _run(
        reconcile_invoice_after_payment(_DB, TENANT, inv_id)
    )
    assert result.new_payment_status == "partial"
    assert result.new_status == "sent"


# ═══════════════════════════════════════════════════════════════════
# §3 · Idempotency
# ═══════════════════════════════════════════════════════════════════
def test_idempotent_second_call_matches_modulo_timestamp():
    """Calling the reconciler twice with the same payment set
    must yield byte-identical results EXCEPT for
    ``reconciled_at`` (naturally advances) and ``audit_id``
    (a fresh audit row is written on state-changing reconciles;
    the second call is a no-op so no new audit is expected)."""
    from services.imports.payment_reconciler import (
        reconcile_invoice_after_payment,
    )
    inv_id = _run(_seed_invoice(tenant_id=TENANT, total=100.0))
    _run(_seed_payment(
        tenant_id=TENANT, invoice_id=inv_id, amount=100.0,
    ))
    r1 = _run(reconcile_invoice_after_payment(_DB, TENANT, inv_id))
    r2 = _run(reconcile_invoice_after_payment(_DB, TENANT, inv_id))

    # Same numerics.
    assert r1.new_amount_paid == r2.new_amount_paid
    assert r1.new_payment_status == r2.new_payment_status
    assert r1.new_status == r2.new_status
    # Second call sees the FIRST call's post-state as its prior:
    # by definition the second call sees no state transitions.
    assert r2.transitions == [], (
        f"idempotent second call must have empty transitions, "
        f"got {r2.transitions}"
    )
    # First call landed the changes; second is a no-op ⇒
    # no new audit row.
    assert r2.audit_id is None


# ═══════════════════════════════════════════════════════════════════
# §4 · Tenant isolation
# ═══════════════════════════════════════════════════════════════════
def test_tenant_isolation_other_tenant_payments_do_not_contaminate():
    """A payment for tenant B against tenant B's invoice must
    NEVER affect tenant A's reconciliation of a same-id invoice."""
    from services.imports.payment_reconciler import (
        reconcile_invoice_after_payment,
    )
    # Seed same-total invoice in BOTH tenants using explicit ids
    # so we can pin one lookup.
    inv_a = _run(_seed_invoice(tenant_id=TENANT, total=100.0))
    inv_b = _run(_seed_invoice(tenant_id=TENANT_B, total=100.0))
    # Tenant B receives a $100 payment against tenant B's invoice.
    _run(_seed_payment(
        tenant_id=TENANT_B, invoice_id=inv_b, amount=100.0,
    ))
    # Also seed a rogue payment in tenant B that points at
    # tenant A's invoice_id (cross-tenant contamination attempt).
    _run(_seed_payment(
        tenant_id=TENANT_B, invoice_id=inv_a, amount=100.0,
    ))

    # Reconciling tenant A's invoice must ignore tenant B's rows.
    result = _run(
        reconcile_invoice_after_payment(_DB, TENANT, inv_a)
    )
    assert result.new_amount_paid == 0.0
    assert result.new_payment_status == "unpaid"
    assert result.new_status == "sent"


def test_invoice_not_found_raises():
    """An invoice_id that doesn't exist in the tenant surfaces
    a typed exception the caller can catch + continue on."""
    from services.imports.payment_reconciler import (
        reconcile_invoice_after_payment,
        InvoiceNotFoundError,
    )
    with pytest.raises(InvoiceNotFoundError):
        _run(
            reconcile_invoice_after_payment(
                _DB, TENANT, f"{PFX}nonexistent",
            )
        )


def test_invoice_from_wrong_tenant_raises_not_found():
    """An invoice that exists but belongs to another tenant
    surfaces as ``InvoiceNotFoundError`` (never as a silent
    success), same posture as the poll endpoint's 404-on-
    cross-tenant."""
    from services.imports.payment_reconciler import (
        reconcile_invoice_after_payment,
        InvoiceNotFoundError,
    )
    inv_b = _run(_seed_invoice(tenant_id=TENANT_B, total=100.0))
    with pytest.raises(InvoiceNotFoundError):
        _run(reconcile_invoice_after_payment(_DB, TENANT, inv_b))


# ═══════════════════════════════════════════════════════════════════
# §5 · Audit row + soft-delete filter
# ═══════════════════════════════════════════════════════════════════
def test_audit_row_written_on_state_change():
    from services.imports.payment_reconciler import (
        reconcile_invoice_after_payment,
    )
    inv_id = _run(_seed_invoice(tenant_id=TENANT, total=100.0))
    _run(_seed_payment(
        tenant_id=TENANT, invoice_id=inv_id, amount=100.0,
    ))
    result = _run(
        reconcile_invoice_after_payment(
            _DB, TENANT, inv_id,
            audit_source="pdf_import",
            audit_actor="admin-42",
        )
    )
    assert result.audit_id is not None
    row = _run(_DB.import_audit.find_one({"id": result.audit_id}))
    assert row is not None
    assert row["action"] == "invoice_reconciled"
    assert row["invoice_id"] == inv_id
    assert row["tenant_id"] == TENANT
    assert row["audit_source"] == "pdf_import"
    assert row["operator_user_id"] == "admin-42"
    assert row["new_payment_status"] == "paid"
    assert row["new_status"] == "accepted"


def test_soft_deleted_payments_excluded_from_sum():
    """A payment with ``deleted_at`` set (HD-A soft-delete) must
    NOT contribute to the reconciler's ``amount_paid`` sum."""
    from services.imports.payment_reconciler import (
        reconcile_invoice_after_payment,
    )
    inv_id = _run(_seed_invoice(tenant_id=TENANT, total=100.0))
    _run(_seed_payment(
        tenant_id=TENANT, invoice_id=inv_id, amount=60.0,
    ))
    _run(_seed_payment(
        tenant_id=TENANT, invoice_id=inv_id, amount=40.0,
        deleted_at=datetime.now(timezone.utc).isoformat(),
    ))
    result = _run(
        reconcile_invoice_after_payment(_DB, TENANT, inv_id)
    )
    # Only the $60 live payment counts.
    assert result.new_amount_paid == 60.0
    assert result.new_payment_status == "partial"


def test_multiple_partial_payments_sum_correctly():
    """Three partial payments summing to full total flip the
    invoice to paid + accepted."""
    from services.imports.payment_reconciler import (
        reconcile_invoice_after_payment,
    )
    inv_id = _run(_seed_invoice(tenant_id=TENANT, total=100.0))
    _run(_seed_payment(tenant_id=TENANT, invoice_id=inv_id, amount=40.0))
    _run(_seed_payment(tenant_id=TENANT, invoice_id=inv_id, amount=35.0))
    _run(_seed_payment(tenant_id=TENANT, invoice_id=inv_id, amount=25.0))
    result = _run(
        reconcile_invoice_after_payment(_DB, TENANT, inv_id)
    )
    assert result.new_amount_paid == 100.0
    assert result.new_payment_status == "paid"
    assert result.new_status == "accepted"


def test_no_update_when_reconcile_is_noop():
    """Calling the reconciler on an already-reconciled invoice
    must NOT issue a Mongo write (no transitions ⇒ no update)."""
    from services.imports.payment_reconciler import (
        reconcile_invoice_after_payment,
    )
    # Seed a fully-reconciled invoice: total=100, amount_paid=100,
    # payment_status=paid, status=accepted, PLUS a matching
    # payment row so the reconciler recomputes the same values.
    inv_id = _run(_seed_invoice(
        tenant_id=TENANT, total=100.0, amount_paid=100.0,
        payment_status="paid", status="accepted",
        paid_at="2026-02-01T00:00:00+00:00",
    ))
    _run(_seed_payment(
        tenant_id=TENANT, invoice_id=inv_id, amount=100.0,
    ))
    # Reset paid_at so we can detect a no-op via unchanged ts.
    result = _run(
        reconcile_invoice_after_payment(_DB, TENANT, inv_id)
    )
    assert result.transitions == []
    assert result.audit_id is None
    row = _run(_DB.quotes.find_one({"id": inv_id}))
    # ``paid_at`` untouched (would be overwritten if a write fired).
    assert row.get("paid_at") == "2026-02-01T00:00:00+00:00"
