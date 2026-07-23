"""Phase 10 · Feb 2026 — Auto-apply credits to invoices.

Two exported functions that operate on plain dicts — persistence is
the caller's responsibility (so an invoice-creation flow can commit
the customer + invoice + ledger in a single request cycle).

Contract:
  * ``apply_credits_to_invoice(invoice, customer)``
      → returns ``{credits_applied_cents, updated_invoice, updated_customer,
                    ledger_entry?}``. Never mutates inputs (returns fresh copies).
      No-op when balance == 0 OR ``invoice.credits_applied_cents`` is
      already set (idempotency guard). Caller writes both the customer
      and invoice atomically.

  * ``revert_credits_from_invoice(invoice, customer)``
      → same shape, but the ledger entry is a positive delta with
      ``source="revert"`` + ``reverted_from_entry_id`` pointing at the
      original ``ledger_entry.id``. Only fires when the invoice has
      ``credits_applied_cents > 0`` AND status in ``{"draft", "sent"}``.

Line-item shape for the invoice PDF/HTML:
    {"description": "Referral credit applied", "quantity": 1,
     "unit_price": -<amount_dollars>, "credit_line": true,
     "promo_code_id": None}
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional


def _invoice_total_cents(invoice: Dict[str, Any]) -> int:
    """Prefer explicit ``total_cents``; fall back to ``total`` (float dollars)."""
    if invoice.get("total_cents") is not None:
        try:
            return int(invoice["total_cents"])
        except (TypeError, ValueError):
            pass
    try:
        return int(round(float(invoice.get("total") or 0) * 100))
    except (TypeError, ValueError):
        return 0


def _customer_balance_cents(customer: Dict[str, Any]) -> int:
    try:
        return int(customer.get("credits_balance_cents") or 0)
    except (TypeError, ValueError):
        return 0


def _new_id() -> str:
    from utils import new_id
    return new_id()


def _now_iso() -> str:
    from utils import now_iso
    return now_iso()


def apply_credits_to_invoice(
    invoice: Dict[str, Any], customer: Dict[str, Any],
) -> Dict[str, Any]:
    """Auto-apply available credit to a fresh (or re-issued) invoice.

    Idempotent: an invoice with ``credits_applied_cents > 0`` is a
    no-op. Caller is responsible for persisting the returned invoice +
    customer atomically.
    """
    already_applied = int(invoice.get("credits_applied_cents") or 0)
    if already_applied > 0:
        return {
            "credits_applied_cents": 0,
            "updated_invoice": dict(invoice),
            "updated_customer": dict(customer),
            "ledger_entry": None,
            "reason": "already_applied",
        }
    balance = _customer_balance_cents(customer)
    total = _invoice_total_cents(invoice)
    if balance <= 0 or total <= 0:
        return {
            "credits_applied_cents": 0,
            "updated_invoice": dict(invoice),
            "updated_customer": dict(customer),
            "ledger_entry": None,
            "reason": "zero_balance_or_total",
        }
    apply_cents = min(balance, total)

    # ─── Compose updated invoice.
    new_invoice = dict(invoice)
    new_invoice["credits_applied_cents"] = apply_cents
    new_total_cents = max(0, total - apply_cents)
    new_invoice["total_cents"] = new_total_cents
    new_invoice["total"] = round(new_total_cents / 100.0, 2)
    line_items = list(new_invoice.get("line_items") or [])
    line_items.append({
        "description": "Referral credit applied",
        "quantity": 1,
        "unit_price": -round(apply_cents / 100.0, 2),
        "credit_line": True,
    })
    new_invoice["line_items"] = line_items

    # ─── Compose updated customer.
    new_customer = dict(customer)
    new_customer["credits_balance_cents"] = max(0, balance - apply_cents)

    # ─── Compose ledger entry.
    entry = {
        "id": _new_id(),
        "delta_cents": -apply_cents,
        "source": "redeemed",
        "invoice_id": invoice.get("id"),
        "note": f"Auto-applied to invoice {invoice.get('id') or ''}".strip(),
        "created_at": _now_iso(),
    }
    return {
        "credits_applied_cents": apply_cents,
        "updated_invoice": new_invoice,
        "updated_customer": new_customer,
        "ledger_entry": entry,
        "reason": "applied",
    }


def revert_credits_from_invoice(
    invoice: Dict[str, Any], customer: Dict[str, Any],
) -> Dict[str, Any]:
    """Restore credit if an invoice is deleted/voided while still in
    ``draft`` or ``sent``. Never touches paid invoices."""
    applied = int(invoice.get("credits_applied_cents") or 0)
    if applied <= 0:
        return {
            "credits_applied_cents": 0,
            "updated_invoice": dict(invoice),
            "updated_customer": dict(customer),
            "ledger_entry": None,
            "reason": "nothing_to_revert",
        }
    status = (invoice.get("status") or "").lower()
    if status not in ("draft", "sent"):
        return {
            "credits_applied_cents": 0,
            "updated_invoice": dict(invoice),
            "updated_customer": dict(customer),
            "ledger_entry": None,
            "reason": "invoice_not_reversible",
        }

    balance = _customer_balance_cents(customer)
    new_customer = dict(customer)
    new_customer["credits_balance_cents"] = balance + applied

    new_invoice = dict(invoice)
    new_invoice["credits_applied_cents"] = 0
    line_items = [
        li for li in (new_invoice.get("line_items") or [])
        if not li.get("credit_line")
    ]
    new_invoice["line_items"] = line_items
    total = _invoice_total_cents(new_invoice) + applied
    new_invoice["total_cents"] = total
    new_invoice["total"] = round(total / 100.0, 2)

    # Find the originating ledger entry id (if present) for traceability.
    reverted_from: Optional[str] = None
    for e in (customer.get("credits_ledger") or []):
        if e.get("invoice_id") == invoice.get("id") and e.get("source") == "redeemed":
            reverted_from = e.get("id")
            break

    entry = {
        "id": _new_id(),
        "delta_cents": applied,
        "source": "revert",
        "invoice_id": invoice.get("id"),
        "reverted_from_entry_id": reverted_from,
        "note": f"Reverted from voided invoice {invoice.get('id') or ''}".strip(),
        "created_at": _now_iso(),
    }
    return {
        "credits_applied_cents": applied,
        "updated_invoice": new_invoice,
        "updated_customer": new_customer,
        "ledger_entry": entry,
        "reason": "reverted",
    }


# ─── Callsite convenience: apply + persist in one call ───────────────
async def apply_and_persist(db, tenant_id: str, invoice: dict) -> dict:
    """Callable from invoice-creation flows. Reads the customer once,
    applies credits, and commits both writes + a ledger push in the
    same request cycle. Returns the mutated invoice dict."""
    if not invoice.get("customer_id"):
        return invoice
    cust = await db.customers.find_one(
        {"id": invoice["customer_id"], "tenant_id": tenant_id}, {"_id": 0},
    )
    if not cust:
        return invoice
    res = apply_credits_to_invoice(invoice, cust)
    if res["credits_applied_cents"] <= 0:
        return res["updated_invoice"]
    # Atomic-ish updates.
    await db.customers.update_one(
        {"id": cust["id"], "tenant_id": tenant_id},
        {
            "$set": {"credits_balance_cents":
                       res["updated_customer"]["credits_balance_cents"]},
            "$push": {"credits_ledger": res["ledger_entry"]},
        },
    )
    return res["updated_invoice"]
