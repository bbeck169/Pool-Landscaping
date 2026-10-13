"""Feb-2026 · Auto-apply customer credit balance to OPEN invoices.

Model B (coexist with ``services/credits_apply.py``):
  * ``services/credits_apply.py`` (shipped) — line-item model.
    Reduces the invoice's own ``total_cents`` + appends a negative
    ``line_item`` for credits applied **at invoice creation time**
    on the invoice being created.
  * This module (new)              — payment-row model.
    Writes a ``db.payments`` row with ``method="credit_balance"``
    for OTHER open invoices + credit-issue triggers + a one-shot
    deploy-time backfill. Invoice balance is recomputed via the
    existing ``services/imports/payment_reconciler.py``.

The two paths never touch the same invoice in the same request —
invoice-create callsites pass ``exclude_invoice_ids`` containing
the freshly-created invoice's id so the sweep only runs against
the customer's OTHER open invoices.

Credit mutation goes through the ``services.customer_balance.mutate_credit``
choke point (gated by ``services/credit_write_guard.py``). This
module never writes ``customers.credit_balance_cents`` /
``db.customer_credits`` / ``db.customer_credits_balance`` directly.

Invoice-balance recompute goes through
``services/imports/payment_reconciler.py::reconcile_invoice_after_payment``
— the SAME helper that heals invoices after PDF-import payment
commits. No bespoke ``$inc amount_paid`` here.

Partial-failure semantics:
  * Payment insert succeeds → reconcile OR mutate_credit fails
    → soft-delete the payment row (``deleted_at`` + ``deleted_reason``)
    and emit ``credit_apply.inconsistency_detected`` with full
    context so operators can clean up manually.

Blocked statuses (eligibility):
  * ``payment_status IN ("unpaid", "partial")`` AND
  * ``deleted_at`` null/missing AND
  * ``status NOT IN ("draft", "void", "cancelled")``.

Ordering:
  * ``due_date`` ASC (nulls last) → ``created_at`` ASC.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional

logger = logging.getLogger("services.credit_apply")

# Payment-feed description template — rendered verbatim into
# ``db.payments.description`` so the portal payment-feed line shows
# ``Credit applied: $12.34``.
_PAYMENT_DESCRIPTION_FMT = "Credit applied: ${amount:.2f}"

# Idempotency window — a prior ``credit_balance`` payment on the
# same (tenant, customer, invoice) within this many hours short-
# circuits a retry.
_IDEMPOTENCY_WINDOW_HOURS = 24

# Eligibility rails — matches ``services/imports/payment_reconciler.py``.
_ELIGIBLE_PAYMENT_STATUSES = ("unpaid", "partial")
_BLOCKED_INVOICE_STATUSES = ("draft", "void", "cancelled", "voided")


@dataclass
class ApplyResult:
    """Return shape from ``apply_credit_to_customer_open_invoices``."""
    customer_id: str
    tenant_id: str
    applied_cents: int = 0
    invoices_touched: List[str] = field(default_factory=list)
    invoices_fully_paid: List[str] = field(default_factory=list)
    skipped_duplicates: List[str] = field(default_factory=list)
    inconsistencies: List[Dict[str, Any]] = field(default_factory=list)
    starting_credit_cents: int = 0
    ending_credit_cents: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "customer_id": self.customer_id,
            "tenant_id": self.tenant_id,
            "applied_cents": int(self.applied_cents),
            "applied_dollars": round(self.applied_cents / 100.0, 2),
            "invoices_touched": list(self.invoices_touched),
            "invoices_fully_paid": list(self.invoices_fully_paid),
            "skipped_duplicates": list(self.skipped_duplicates),
            "inconsistencies": list(self.inconsistencies),
            "starting_credit_cents": int(self.starting_credit_cents),
            "ending_credit_cents": int(self.ending_credit_cents),
        }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    from utils import new_id
    return new_id()


async def _read_credit_balance_cents(
    db, tenant_id: str, customer_id: str,
) -> int:
    """Read the authoritative credit balance from the Phase-10
    aggregate collection. Falls back to the legacy dollar field."""
    row = await db.customer_credits_balance.find_one(
        {"tenant_id": tenant_id, "customer_id": customer_id},
        {"_id": 0, "balance_cents": 1, "balance": 1},
    ) or {}
    cents = row.get("balance_cents")
    if cents is None:
        try:
            cents = int(round(float(row.get("balance") or 0) * 100))
        except (TypeError, ValueError):
            cents = 0
    try:
        return int(cents)
    except (TypeError, ValueError):
        return 0


async def _fetch_eligible_open_invoices(
    db, tenant_id: str, customer_id: str,
    exclude_invoice_ids: Iterable[str],
) -> List[Dict[str, Any]]:
    """Return eligible open invoices for the customer ordered by
    oldest ``due_date`` first (``null`` last), then oldest
    ``created_at`` first. Excludes any ids in ``exclude_invoice_ids``."""
    excludes = [i for i in (exclude_invoice_ids or []) if i]
    _filter: Dict[str, Any] = {
        "tenant_id": tenant_id,
        "customer_id": customer_id,
        "doc_type": "invoice",
        "payment_status": {"$in": list(_ELIGIBLE_PAYMENT_STATUSES)},
        "status": {"$nin": list(_BLOCKED_INVOICE_STATUSES)},
        "$or": [
            {"deleted_at": None},
            {"deleted_at": {"$exists": False}},
        ],
    }
    if excludes:
        _filter["id"] = {"$nin": excludes}
    rows: List[Dict[str, Any]] = []
    async for inv in db.quotes.find(
        _filter,
        {"_id": 0, "id": 1, "customer_id": 1, "customer_name": 1,
          "tenant_id": 1, "total": 1, "amount_paid": 1,
          "payment_status": 1, "status": 1, "due_date": 1,
          "created_at": 1, "invoice_number": 1},
    ):
        rows.append(inv)
    # Python-side sort — ``None`` due_dates sort last.
    rows.sort(key=lambda r: (
        r.get("due_date") is None,
        r.get("due_date") or "",
        r.get("created_at") or "",
    ))
    return rows


async def _recent_duplicate_payment(
    db, tenant_id: str, customer_id: str, invoice_id: str,
    amount_dollars: float, window_hours: int = _IDEMPOTENCY_WINDOW_HOURS,
) -> Optional[Dict[str, Any]]:
    """Idempotency guard — look for an existing non-deleted
    ``credit_balance`` payment on the same (tenant, customer,
    invoice) within the last N hours at the same amount."""
    since = (
        datetime.now(timezone.utc) - timedelta(hours=window_hours)
    ).isoformat()
    row = await db.payments.find_one(
        {
            "tenant_id": tenant_id,
            "customer_id": customer_id,
            "invoice_id": invoice_id,
            "method": "credit_balance",
            "created_at": {"$gte": since},
            "$or": [
                {"deleted_at": None},
                {"deleted_at": {"$exists": False}},
            ],
        },
        {"_id": 0, "id": 1, "amount": 1, "created_at": 1},
    )
    if not row:
        return None
    # Dollar comparison with 1-cent tolerance.
    if abs(float(row.get("amount") or 0) - amount_dollars) < 0.01:
        return row
    return None


async def _soft_delete_payment(
    db, tenant_id: str, payment_id: str, reason: str,
) -> None:
    try:
        await db.payments.update_one(
            {"tenant_id": tenant_id, "id": payment_id},
            {"$set": {
                "deleted_at": _now_iso(),
                "deleted_reason": reason,
            }},
        )
    except Exception:  # noqa: BLE001
        logger.exception(
            "[credit_apply.rollback] soft-delete payment failed "
            "tenant=%s payment=%s reason=%s",
            tenant_id, payment_id, reason,
        )


async def apply_credit_to_customer_open_invoices(
    db,
    tenant_id: str,
    customer_id: str,
    *,
    actor: Optional[Dict[str, Any]] = None,
    source: str = "auto",
    exclude_invoice_ids: Optional[Iterable[str]] = None,
) -> ApplyResult:
    """Apply the customer's credit balance to their open invoices,
    oldest ``due_date`` first.

    See module docstring for eligibility + idempotency + rollback
    semantics. Returns an :class:`ApplyResult` summarising the run.
    """
    result = ApplyResult(customer_id=customer_id, tenant_id=tenant_id)
    starting_credit = await _read_credit_balance_cents(
        db, tenant_id, customer_id,
    )
    result.starting_credit_cents = starting_credit
    result.ending_credit_cents = starting_credit
    if starting_credit <= 0:
        return result

    invoices = await _fetch_eligible_open_invoices(
        db, tenant_id, customer_id, exclude_invoice_ids or [],
    )
    remaining_credit = starting_credit

    # Payment reconciler + mutate_credit imported lazily so this
    # module is importable in test harnesses that monkey-patch the
    # choke point before the first call.
    from services.imports.payment_reconciler import (
        reconcile_invoice_after_payment,
        InvoiceNotFoundError,
    )
    from services.customer_balance import mutate_credit

    for inv in invoices:
        if remaining_credit <= 0:
            break
        invoice_id = inv.get("id")
        if not invoice_id:
            continue
        total_dollars = float(inv.get("total") or 0.0)
        paid_dollars = float(inv.get("amount_paid") or 0.0)
        balance_due_dollars = round(total_dollars - paid_dollars, 2)
        if balance_due_dollars <= 1e-9:
            continue
        balance_due_cents = int(round(balance_due_dollars * 100))
        apply_cents = min(remaining_credit, balance_due_cents)
        if apply_cents <= 0:
            continue
        apply_dollars = round(apply_cents / 100.0, 2)

        # ─── Idempotency guard ──────────────────────────────────
        dup = await _recent_duplicate_payment(
            db, tenant_id, customer_id, invoice_id, apply_dollars,
        )
        if dup:
            logger.info(
                "credit_apply.skipped_duplicate "
                "tenant=%s customer=%s invoice=%s amount=%.2f "
                "existing_payment=%s",
                tenant_id, customer_id, invoice_id, apply_dollars,
                dup.get("id"),
            )
            result.skipped_duplicates.append(invoice_id)
            continue

        # ─── Payment row insert ────────────────────────────────
        payment_id = _new_id()
        now_iso = _now_iso()
        payment_doc = {
            "id": payment_id,
            "tenant_id": tenant_id,
            "customer_id": customer_id,
            "customer_name": inv.get("customer_name") or "",
            "amount": apply_dollars,
            "method": "credit_balance",
            "status": "succeeded",
            "invoice_id": invoice_id,
            "invoice_number": inv.get("invoice_number"),
            "description": _PAYMENT_DESCRIPTION_FMT.format(
                amount=apply_dollars,
            ),
            "paid_at": now_iso,
            "created_at": now_iso,
            "updated_at": now_iso,
            "source": source,
            "written_by_system": True,
            "actor_user_id": (actor or {}).get("id"),
            "actor_email":   (actor or {}).get("email"),
        }
        try:
            await db.payments.insert_one(payment_doc)
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "credit_apply.payment_insert_failed "
                "tenant=%s customer=%s invoice=%s error=%r",
                tenant_id, customer_id, invoice_id, exc,
            )
            # Nothing to roll back — payment never landed.
            continue

        # ─── Invoice reconcile (recompute amount_paid/status) ──
        try:
            recon = await reconcile_invoice_after_payment(
                db, tenant_id, invoice_id,
                audit_source="credit_apply",
                audit_actor=(actor or {}).get("id"),
            )
        except InvoiceNotFoundError as exc:
            # Rolled back: soft-delete payment, record inconsistency.
            await _soft_delete_payment(
                db, tenant_id, payment_id,
                reason="credit_apply.rollback.invoice_not_found",
            )
            logger.error(
                "credit_apply.inconsistency_detected "
                "tenant=%s customer=%s invoice=%s payment=%s "
                "stage=reconcile reason=invoice_not_found error=%r",
                tenant_id, customer_id, invoice_id, payment_id, exc,
            )
            result.inconsistencies.append({
                "stage": "reconcile",
                "reason": "invoice_not_found",
                "invoice_id": invoice_id,
                "payment_id": payment_id,
            })
            continue
        except Exception as exc:  # noqa: BLE001
            await _soft_delete_payment(
                db, tenant_id, payment_id,
                reason="credit_apply.rollback.reconcile_failed",
            )
            logger.error(
                "credit_apply.inconsistency_detected "
                "tenant=%s customer=%s invoice=%s payment=%s "
                "stage=reconcile error=%r",
                tenant_id, customer_id, invoice_id, payment_id, exc,
            )
            result.inconsistencies.append({
                "stage": "reconcile",
                "invoice_id": invoice_id,
                "payment_id": payment_id,
                "error": repr(exc)[:400],
            })
            continue

        # ─── Credit decrement via choke point ──────────────────
        # Idempotency key narrows to invoice + amount + day so
        # same-day retries converge; distinct-day re-runs can
        # legitimately re-apply (shouldn't happen because of the
        # eligibility filter + the 24h payment-dup guard, but
        # defense in depth).
        today = datetime.now(timezone.utc).date().isoformat()
        idem_key = f"credit_apply:{invoice_id}:{apply_cents}:{today}"
        try:
            mut = await mutate_credit(
                db, tenant_id, customer_id,
                delta_cents=-apply_cents,
                source="auto_applied_to_invoice",
                actor=actor,
                reason=f"Auto-applied to invoice {invoice_id}",
                idempotency_key=idem_key,
                extra_ledger_fields={
                    "invoice_id": invoice_id,
                    "payment_id": payment_id,
                },
            )
        except Exception as exc:  # noqa: BLE001
            # Rolled back: soft-delete payment, record inconsistency.
            # Invoice has already been reconciled with the payment
            # row — the reconcile is a pure recompute of linked
            # payments, so after the soft-delete we re-run the
            # reconciler to converge the invoice state back.
            await _soft_delete_payment(
                db, tenant_id, payment_id,
                reason="credit_apply.rollback.mutate_credit_failed",
            )
            try:
                await reconcile_invoice_after_payment(
                    db, tenant_id, invoice_id,
                    audit_source="credit_apply.rollback",
                    audit_actor=(actor or {}).get("id"),
                )
            except Exception:  # noqa: BLE001
                logger.exception(
                    "credit_apply.rollback.reconcile_also_failed "
                    "tenant=%s customer=%s invoice=%s",
                    tenant_id, customer_id, invoice_id,
                )
            logger.error(
                "credit_apply.inconsistency_detected "
                "tenant=%s customer=%s invoice=%s payment=%s "
                "stage=mutate_credit error=%r",
                tenant_id, customer_id, invoice_id, payment_id, exc,
            )
            result.inconsistencies.append({
                "stage": "mutate_credit",
                "invoice_id": invoice_id,
                "payment_id": payment_id,
                "error": repr(exc)[:400],
            })
            continue

        # ─── Success bookkeeping ───────────────────────────────
        result.applied_cents += apply_cents
        result.invoices_touched.append(invoice_id)
        if (recon.new_payment_status or "").lower() == "paid":
            result.invoices_fully_paid.append(invoice_id)
        # Trust mutate_credit's return for the ending balance; if
        # it's a duplicate short-circuit, re-fetch (should not happen
        # here because the idempotency_key is deterministic per
        # invoice+amount+day and the dup guard upstream would have
        # already short-circuited).
        new_balance = int(mut.get("balance_cents") or 0)
        remaining_credit = max(0, new_balance)
        result.ending_credit_cents = remaining_credit

        logger.info(
            "credit_apply.applied "
            "tenant=%s customer=%s invoice=%s payment=%s "
            "amount=%.2f new_credit_balance_cents=%d "
            "new_payment_status=%s",
            tenant_id, customer_id, invoice_id, payment_id,
            apply_dollars, remaining_credit, recon.new_payment_status,
        )

    return result


__all__ = [
    "ApplyResult",
    "apply_credit_to_customer_open_invoices",
]
