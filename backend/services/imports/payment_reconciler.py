"""FIN-PARITY-A · Feb-2026 — Invoice reconciliation after payment landing.

Closes the gap between the native ``routers.quotes.record_payment``
path (which updates the invoice's ``amount_paid`` / ``payment_status``
/ ``status`` fields inline) and the PDF payment commit path (which
inserts rows into ``db.payments`` but historically didn't touch the
linked invoice at all).

**Reconciliation rules — verbatim from ``record_payment``:**
    * ``fully_paid = paid >= total - 0.01``   (tolerance = 1¢)
    * ``amount_paid = min(paid, total)``      (caps at total on
                                                  overpay)
    * ``payment_status = "paid" if fully_paid else "partial"``
      (``"unpaid"`` added by this reconciler for the zero-payments
      case — ``record_payment`` never reaches that branch because
      it 400s on ``body.amount <= 0``)
    * On fully_paid transition (current status != "accepted"):
      ``status = "accepted"`` + ``paid_at = <first paid_at from
      linked payments, or now() as fallback>``.

**What this helper is NOT:**
    * NOT called by ``record_payment`` itself — that path stays
      as-is per FIN-PARITY-A scope. A source-inspect parity test
      (``test_fin_parity_a_record_payment_parity.py``) locks the
      two paths to identical outputs for the same payment set.
    * NOT a full audit stamper — it writes ONE
      ``db.import_audit`` row per reconciliation via the shared
      audit lane. Marketing / automation event emission is
      deferred to the caller (PDF commit does not fire
      ``invoice.paid`` events; that's a FIN-PARITY-B decision).

**FIN-PARITY-B guardrail — DO NOT fire ``invoice.paid`` events
from this helper.** Imported historicals routinely represent
invoices that were paid years ago; wiring an
``automation_engine.emit("invoice.paid")`` here would trigger a
present-day "thanks for paying!" drip against 2023 invoices,
generate outbound SMS / email storms against customers who have
long since moved on, and pollute marketing analytics with
back-dated conversions. This restriction is architectural, not
temporary — even if a future track lands a "historical
suppression" flag on the automation engine, the reconciler stays
event-silent so the guardrail can never be bypassed by a
misconfigured tenant.  Downstream state (invoice card, reports
aggregators) reads from ``db.quotes`` directly and picks up the
reconciled ``payment_status`` / ``amount_paid`` on the next
render — no event bus needed.

**Idempotency:** the reconciler is a full-recompute from
``db.payments.find({tenant_id, invoice_id})`` — calling it twice
with the same payment set produces identical results (modulo the
``reconciled_at`` timestamp). Locked by a dedicated test.

**Tenant isolation:** every query is scoped to ``tenant_id``.
An invoice from another tenant will never surface here, and
payments for another tenant's invoice cannot contaminate the sum.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("fin_parity_reconciler")


# Tolerance for "fully paid" — matches ``record_payment`` at
# ``backend/routers/quotes.py:1768``. Locked by parity test.
FULLY_PAID_TOLERANCE = 0.01

# ``db.quotes.payment_status`` enum values used by the reconciler.
# ``record_payment`` writes "paid" / "partial"; the ``"unpaid"``
# state is the initial value on invoice creation and the target
# of this reconciler when the summed payments == 0.
PAYMENT_STATUS_UNPAID = "unpaid"
PAYMENT_STATUS_PARTIAL = "partial"
PAYMENT_STATUS_PAID = "paid"


@dataclass
class ReconcileResult:
    """Return shape from ``reconcile_invoice_after_payment``.

    Every field is JSON-serialisable so the commit response can
    include it verbatim in ``reconciled_invoices``.
    """
    invoice_id: str
    prior_amount_paid: float
    new_amount_paid: float
    prior_payment_status: str
    new_payment_status: str
    prior_status: str
    new_status: str
    transitions: List[str] = field(default_factory=list)
    reconciled_at: str = ""
    audit_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "invoice_id": self.invoice_id,
            "prior_amount_paid": self.prior_amount_paid,
            "new_amount_paid": self.new_amount_paid,
            "prior_payment_status": self.prior_payment_status,
            "new_payment_status": self.new_payment_status,
            "prior_status": self.prior_status,
            "new_status": self.new_status,
            "transitions": list(self.transitions),
            "reconciled_at": self.reconciled_at,
            "audit_id": self.audit_id,
        }


class InvoiceNotFoundError(Exception):
    """Raised when the invoice_id doesn't resolve within the
    tenant. The PDF commit path catches this + logs; other
    callers may want a hard fail."""


def _compute_payment_status(paid: float, total: float) -> str:
    """The 3-way rule matching ``record_payment`` + the extra
    ``unpaid`` case the reconciler owns.

    Kept private so both the reconciler AND the parity test
    can call it directly. If ``record_payment`` ever changes
    its 3-way rule, the parity test will catch the drift here.
    """
    if paid <= 0:
        return PAYMENT_STATUS_UNPAID
    if paid >= total - FULLY_PAID_TOLERANCE:
        return PAYMENT_STATUS_PAID
    return PAYMENT_STATUS_PARTIAL


async def reconcile_invoice_after_payment(
    db,
    tenant_id: str,
    invoice_id: str,
    *,
    audit_source: str = "pdf_import",
    audit_actor: Optional[str] = None,
) -> ReconcileResult:
    """Recompute ``amount_paid`` / ``payment_status`` / ``status``
    for one invoice from the current sum of linked payments.

    See module docstring for the reconciliation rules.

    Raises ``InvoiceNotFoundError`` when the ``invoice_id`` does
    not exist within the tenant.  Callers can catch + continue
    (batch commit) or let it bubble (single-shot API).
    """
    # ── Load invoice (tenant-scoped) ─────────────────────────
    invoice = await db.quotes.find_one(
        {"id": invoice_id, "tenant_id": tenant_id},
        {
            "_id": 0, "id": 1, "tenant_id": 1,
            "total": 1, "amount_paid": 1,
            "payment_status": 1, "status": 1, "paid_at": 1,
            "customer_id": 1,
        },
    )
    if invoice is None:
        raise InvoiceNotFoundError(
            f"invoice_id={invoice_id!r} not found in tenant "
            f"{tenant_id!r}"
        )

    prior_amount_paid = float(invoice.get("amount_paid") or 0.0)
    prior_payment_status = invoice.get("payment_status") or PAYMENT_STATUS_UNPAID
    prior_status = invoice.get("status") or "sent"
    total = float(invoice.get("total") or 0.0)

    # ── Sum linked payments (tenant-scoped, non-deleted) ────
    # HD-A soft-delete filter: payments with ``deleted_at``
    # set (non-null) are excluded. Matches the ``not_deleted``
    # posture the rest of the codebase uses.
    payments_cursor = db.payments.find(
        {
            "tenant_id": tenant_id,
            "invoice_id": invoice_id,
            "$or": [
                {"deleted_at": None},
                {"deleted_at": {"$exists": False}},
            ],
        },
        {"_id": 0, "amount": 1, "paid_at": 1},
    )
    total_paid = 0.0
    earliest_paid_at: Optional[str] = None
    async for p in payments_cursor:
        total_paid += float(p.get("amount") or 0.0)
        p_at = p.get("paid_at")
        if p_at and (earliest_paid_at is None or p_at < earliest_paid_at):
            earliest_paid_at = p_at
    # Round to 2 decimal places — mirrors ``record_payment``'s
    # ``round(..., 2)`` on the running sum.
    total_paid = round(total_paid, 2)

    # ── Apply the 3-way status rule ──────────────────────────
    new_payment_status = _compute_payment_status(total_paid, total)
    # ``record_payment`` caps at total on overpay; mirror that
    # so the persisted ``amount_paid`` never exceeds ``total``.
    # The full unrounded sum is still available on the
    # ReconcileResult (``new_amount_paid``) for audit / UI.
    persisted_amount_paid = min(total_paid, total)

    # Status transition — only upgrade to "paid" on the
    # fully-paid boundary crossing. Never downgrade (partial
    # refund scenarios are out of scope).
    #
    # Feb-2026 · FIN-PAID-STATUS-PARITY — flipped the terminal
    # value from "accepted" to "paid" to match the Stripe-webhook
    # ``_mark_invoice_paid`` Fix A at ``stripe_charge.py:1969``.
    # The guard accepts BOTH legacy ``"accepted"`` and the new
    # ``"paid"`` as terminal so pre-backfill + post-backfill
    # rows both no-op on repeat calls.
    new_status = prior_status
    is_new_full_pay = (
        new_payment_status == PAYMENT_STATUS_PAID
        and prior_status not in ("paid", "accepted")
    )
    if is_new_full_pay:
        new_status = "paid"

    # ── Build the transitions log ───────────────────────────
    transitions: List[str] = []
    if abs(persisted_amount_paid - prior_amount_paid) > 1e-9:
        transitions.append(
            f"amount_paid: {prior_amount_paid:.2f} → "
            f"{persisted_amount_paid:.2f}"
        )
    if new_payment_status != prior_payment_status:
        transitions.append(
            f"payment_status: {prior_payment_status} → "
            f"{new_payment_status}"
        )
    if new_status != prior_status:
        transitions.append(f"status: {prior_status} → {new_status}")

    reconciled_at = datetime.now(timezone.utc).isoformat()

    # ── Persist ──────────────────────────────────────────────
    update_fields: Dict[str, Any] = {
        "amount_paid": persisted_amount_paid,
        "payment_status": new_payment_status,
    }
    if is_new_full_pay:
        update_fields["status"] = "paid"
        # Feb-2026 · FIN-PAID-STATUS-PARITY — audit crumb for a
        # future refund-restore flow (TD-stripe-refund-restore-
        # prepaid-status). Only stamped on the real transition
        # because ``is_new_full_pay`` already excludes legacy
        # terminal rows via the ``not in ("paid", "accepted")``
        # guard above.
        update_fields["previous_status_before_paid"] = prior_status
        # Prefer the earliest payment's paid_at; fall back to
        # now(). ``record_payment`` uses a date-override resolver
        # here — the reconciler stays out of that lane (PDF
        # imports don't accept a user override).
        if not invoice.get("paid_at"):
            update_fields["paid_at"] = (
                earliest_paid_at or reconciled_at
            )
        update_fields["payment_method"] = (
            invoice.get("payment_method") or "pdf_import"
        )
        update_fields["charge_failed"] = False
        update_fields["charge_error"] = ""

    # Only issue the update when something actually changed —
    # avoids a no-op Mongo write on repeat calls with an
    # already-reconciled invoice.
    audit_id: Optional[str] = None
    if transitions:
        await db.quotes.update_one(
            {"id": invoice_id, "tenant_id": tenant_id},
            {"$set": update_fields},
        )

        # Best-effort audit row. Never blocks the reconciliation
        # if the audit collection is unavailable — a missing
        # audit is diagnosed at the ops / dashboard level.
        try:
            audit_id = str(uuid.uuid4())
            await db.import_audit.insert_one({
                "id": audit_id,
                "tenant_id": tenant_id,
                "action": "invoice_reconciled",
                "invoice_id": invoice_id,
                "audit_source": audit_source,
                "operator_user_id": audit_actor,
                "prior_amount_paid": prior_amount_paid,
                "new_amount_paid": persisted_amount_paid,
                "prior_payment_status": prior_payment_status,
                "new_payment_status": new_payment_status,
                "prior_status": prior_status,
                "new_status": new_status,
                "transitions": transitions,
                "at": reconciled_at,
            })
        except Exception:  # noqa: BLE001
            logger.exception(
                "[fin-parity] audit insert failed for invoice=%s "
                "tenant=%s (non-blocking)", invoice_id, tenant_id,
            )
            audit_id = None

    return ReconcileResult(
        invoice_id=invoice_id,
        prior_amount_paid=prior_amount_paid,
        new_amount_paid=persisted_amount_paid,
        prior_payment_status=prior_payment_status,
        new_payment_status=new_payment_status,
        prior_status=prior_status,
        new_status=new_status,
        transitions=transitions,
        reconciled_at=reconciled_at,
        audit_id=audit_id,
    )


__all__ = [
    "FULLY_PAID_TOLERANCE",
    "PAYMENT_STATUS_UNPAID",
    "PAYMENT_STATUS_PARTIAL",
    "PAYMENT_STATUS_PAID",
    "ReconcileResult",
    "InvoiceNotFoundError",
    "reconcile_invoice_after_payment",
    "_compute_payment_status",
]
