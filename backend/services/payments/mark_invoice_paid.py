"""Feb-2026 · P0 fix — Canonical ``mark_invoice_paid`` helper.

Root cause the helper closes: three write paths were flipping
``payment_status = "paid"`` on invoice docs without recording a
matching ``payment_record`` (Stripe PaymentIntent id, ACH transfer
id, cash/check receipt id, service credit, etc.). Result: a customer
opens the SMS invoice link and sees the invoice already marked paid
even though they never entered a card — the Hector Guerrero bug.

Every future ``payment_status = "paid"`` transition MUST route
through this helper. The helper refuses to flip an invoice paid
without a caller-supplied ``payment_record`` and writes an audit
row for every flip so operators can reconcile.

Accepted ``payment_record.kind`` values (extend as needed):
  * ``stripe_checkout``      — Stripe hosted-checkout session.
  * ``stripe_card_on_file``  — auto-charged card on file.
  * ``stripe_pi``            — generic Stripe PaymentIntent.
  * ``manual_cash``          — admin marked paid, cash tendered.
  * ``manual_check``         — admin marked paid, check received.
  * ``manual_ach``           — admin marked paid, ACH transfer.
  * ``service_credit``       — fully covered by service credits.
  * ``import``               — one-off historical import (Homeworks
    Stripe sync, etc.). ``payment_record.txn_id`` must carry the
    upstream provider's id for auditability.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from config import db


logger = logging.getLogger("mark_invoice_paid")


_VALID_RECORD_KINDS = frozenset({
    "stripe_checkout", "stripe_card_on_file", "stripe_pi",
    "manual_cash", "manual_check", "manual_ach",
    "service_credit", "import",
})


class InvoicePaymentRecordError(ValueError):
    """Raised when ``mark_invoice_paid`` is called without a valid
    ``payment_record``. Never silently swallowed — the caller must
    fix the flow before it hits the database."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _validate_payment_record(pr: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(pr, dict) or not pr:
        raise InvoicePaymentRecordError(
            "mark_invoice_paid requires a non-empty payment_record dict",
        )
    kind = (pr.get("kind") or "").strip().lower()
    if kind not in _VALID_RECORD_KINDS:
        raise InvoicePaymentRecordError(
            f"mark_invoice_paid: payment_record.kind={kind!r} is not in "
            f"the accepted set {_VALID_RECORD_KINDS!r}"
        )
    # ``txn_id`` is required for anything backed by an external
    # provider. ``service_credit`` + manual kinds can carry an
    # internal id (audit row uses it) but a completely empty txn_id
    # is a smell — reject it.
    txn_id = (pr.get("txn_id") or "").strip()
    if not txn_id:
        raise InvoicePaymentRecordError(
            "mark_invoice_paid: payment_record.txn_id is required "
            "(pass the Stripe PI id, ACH transfer id, receipt no., "
            "or ``service_credit:{invoice_id}`` for internal kinds).",
        )
    return {
        "kind": kind,
        "txn_id": txn_id,
        "amount_cents": int(pr.get("amount_cents") or 0),
        "currency": (pr.get("currency") or "usd").lower(),
        "actor_user_id": pr.get("actor_user_id"),
        "note": (pr.get("note") or "").strip() or None,
        "created_at": pr.get("created_at") or _now_iso(),
    }


async def mark_invoice_paid(
    *,
    invoice_id: str,
    tenant_id: str,
    payment_record: Dict[str, Any],
    actor_user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Canonical invoice-paid transition.

    * Refuses to flip an invoice paid without a valid ``payment_record``.
    * Idempotent — flipping a doc that is already paid short-circuits
      to a ``noop`` response.
    * Writes to ``db.invoice_status_audit`` on every state change so
      operators can reconcile.
    * Never mutates the invoice's ``created_at`` — only status +
      ``paid_at`` + ``amount_paid`` + ``payment_records[]`` (appended).
    """
    validated = _validate_payment_record(payment_record)
    inv = await db.quotes.find_one(
        {"id": invoice_id, "tenant_id": tenant_id, "doc_type": "invoice"},
        {"_id": 0, "id": 1, "total": 1, "amount_paid": 1,
          "payment_status": 1, "payment_records": 1},
    )
    if not inv:
        raise InvoicePaymentRecordError(
            f"mark_invoice_paid: invoice {invoice_id} not found in "
            f"tenant {tenant_id}.",
        )
    if (inv.get("payment_status") or "").lower() == "paid":
        # Idempotent — the caller may still want to record the
        # payment_record for audit though, so append it.
        await db.quotes.update_one(
            {"id": invoice_id, "tenant_id": tenant_id},
            {"$addToSet": {"payment_records": validated}},
        )
        return {
            "status": "noop",
            "reason": "already_paid",
            "invoice_id": invoice_id,
        }

    total = float(inv.get("total") or 0)
    amount_paid_prev = float(inv.get("amount_paid") or 0)
    amount_paid_new = amount_paid_prev + (validated["amount_cents"] / 100.0)
    if validated["amount_cents"] == 0:
        # Zero-amount ``service_credit`` and ``import`` records carry
        # the invoice total implicitly.
        amount_paid_new = total
    amount_paid_new = round(amount_paid_new, 2)
    now = _now_iso()

    await db.quotes.update_one(
        {"id": invoice_id, "tenant_id": tenant_id},
        {
            "$set": {
                "amount_paid": amount_paid_new,
                "payment_status": "paid",
                "status": "accepted",
                "paid_at": now,
                "paid_method": validated["kind"],
            },
            "$addToSet": {"payment_records": validated},
        },
    )

    # Audit row — separate collection, purpose-built for reconciliation.
    audit_id = str(uuid.uuid4())
    await db.invoice_status_audit.insert_one({
        "id": audit_id,
        "tenant_id": tenant_id,
        "invoice_id": invoice_id,
        "previous_status": inv.get("payment_status") or "unpaid",
        "corrected_status": "paid",
        "reason": "mark_invoice_paid",
        "payment_record": validated,
        "actor_user_id": actor_user_id,
        "corrected_at": now,
    })
    logger.info(
        "[mark_invoice_paid] flipped invoice=%s tenant=%s kind=%s txn=%s "
        "amount_paid=%.2f",
        invoice_id, tenant_id, validated["kind"], validated["txn_id"],
        amount_paid_new,
    )
    return {
        "status": "ok",
        "invoice_id": invoice_id,
        "amount_paid": amount_paid_new,
        "audit_id": audit_id,
    }
