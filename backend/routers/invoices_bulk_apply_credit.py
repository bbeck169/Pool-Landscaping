"""Feb-2026 · Bulk Apply Credit — invoices-list bulk action.

New endpoint: ``POST /api/invoices/bulk-apply-credit``.

Admin selects one or more invoices on the Invoices list and clicks
"Apply Credit". For every selected invoice the backend consults the
customer's credit balance and, if credit is available, applies up to
``invoice.balance_due`` dollars via
``services.credit_apply.apply_credit_to_specific_invoice`` — the
same guard + idempotency + rollback path that the invoice-create
sweep uses.

Non-goals / explicit non-regressions:
  * Does NOT reinvent credit mutation / payment-row writes /
    idempotency. The shipped ``services/credit_apply.py`` is the
    only writer.
  * Does NOT touch the sibling bulk-charge endpoints
    (``invoices/bulk-charge-card-on-file`` / ``…-ach-on-file``)
    or their ``db.bulk_charge_runs`` collection.

Response shape — see ``_bulk_apply_credit_summary`` for the exact
contract. Partial failures surface per-invoice; the endpoint never
500s the whole request on a single-invoice error.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from config import db
from routers.tenants import get_current_tenant
from services.credit_apply import apply_credit_to_specific_invoice
from utils import get_current_user, new_id, now_iso


logger = logging.getLogger("invoices_bulk_apply_credit")
router = APIRouter()


_ADMIN_ROLES = ("admin", "manager", "super_admin")
_MAX_BULK_INVOICES = 500   # DOS guard — per Phase 1 spec Feb-2026.


class BulkApplyCreditBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    invoice_ids: List[str] = Field(min_length=1)


def _require_admin(user: dict) -> None:
    """Match the sibling bulk-charge endpoints' auth gate."""
    if (user.get("role") or "") not in _ADMIN_ROLES:
        raise HTTPException(403, "Admin/manager only")


_STATUS_CREDITED = "credited"
_STATUS_NO_CREDIT = "skipped_no_credit"
_STATUS_ALREADY_PAID = "skipped_already_paid"
_STATUS_BLOCKED = "skipped_blocked_status"
_STATUS_NOT_FOUND = "skipped_not_found"
_STATUS_ERROR = "error"


# Mirrors ``services/credit_apply._BLOCKED_INVOICE_STATUSES`` —
# duplicated here (narrow scope) so the eligibility probe does not
# accidentally drift. If the shipped set changes we'll propagate
# via a shared constant in a follow-up.
_BLOCKED_INVOICE_STATUSES = ("draft", "void", "cancelled", "voided")
_PAID_PAYMENT_STATUSES    = ("paid",)


def _balance_due_dollars(inv: Dict[str, Any]) -> float:
    try:
        total = float(inv.get("total") or 0.0)
        paid  = float(inv.get("amount_paid") or 0.0)
    except (TypeError, ValueError):
        return 0.0
    return round(max(total - paid, 0.0), 2)


def _derive_payment_status_after(inv: Dict[str, Any]) -> str:
    """Re-read the invoice after apply_credit so the response shows
    the fresh payment_status (``paid`` / ``partial`` / ``unpaid``)."""
    return (inv.get("payment_status") or "unpaid")


@router.post("/invoices/bulk-apply-credit")
async def bulk_apply_credit(
    body: BulkApplyCreditBody,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    """Bulk-apply customer credit to the selected invoices.

    See module docstring for behavior + non-regression rails.
    """
    _require_admin(user)

    if len(body.invoice_ids) > _MAX_BULK_INVOICES:
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "too_many_invoice_ids",
                "message": (
                    f"At most {_MAX_BULK_INVOICES} invoice_ids may "
                    "be processed per request."
                ),
                "max": _MAX_BULK_INVOICES,
                "received": len(body.invoice_ids),
            },
        )

    tid = tenant["id"]
    request_id = new_id()

    # ─── 1 · Resolve invoice_ids → invoice rows (tenant-scoped) ──
    # Preserve input order on the way out so operators can read the
    # results table against their selection. ``results_by_id`` maps
    # invoice_id → the response row; populated as we discover each.
    results_by_id: Dict[str, Dict[str, Any]] = {}

    # Bulk fetch to minimize round-trips; soft-deleted explicitly
    # EXCLUDED from the fetch (soft-deleted invoices are reported
    # as ``skipped_not_found`` to avoid leaking existence).
    rows: Dict[str, Dict[str, Any]] = {}
    async for inv in db.quotes.find(
        {
            "id": {"$in": list(body.invoice_ids)},
            "tenant_id": tid,
            "doc_type": "invoice",
            "$or": [
                {"deleted_at": None},
                {"deleted_at": {"$exists": False}},
            ],
        },
        {"_id": 0, "id": 1, "customer_id": 1, "customer_name": 1,
          "invoice_number": 1, "payment_status": 1, "status": 1,
          "total": 1, "amount_paid": 1, "due_date": 1,
          "created_at": 1},
    ):
        rows[inv["id"]] = inv

    # ─── 2 · First-pass classification (not_found / already_paid /
    #        blocked_status). Groups the eligible rows by
    #        customer_id for the second pass. ───────────────────
    by_customer: Dict[str, List[str]] = defaultdict(list)
    for inv_id in body.invoice_ids:
        inv = rows.get(inv_id)
        if not inv:
            results_by_id[inv_id] = {
                "invoice_id": inv_id,
                "invoice_number": None,
                "customer_id": None,
                "customer_name": None,
                "status": _STATUS_NOT_FOUND,
                "amount_applied": 0,
                "balance_remaining": 0,
                "payment_status_after": None,
            }
            continue
        pstatus = (inv.get("payment_status") or "unpaid").lower()
        istatus = (inv.get("status") or "").lower()
        balance = _balance_due_dollars(inv)
        if pstatus in _PAID_PAYMENT_STATUSES or balance <= 0.009:
            results_by_id[inv_id] = {
                "invoice_id": inv_id,
                "invoice_number": inv.get("invoice_number"),
                "customer_id": inv.get("customer_id"),
                "customer_name": inv.get("customer_name"),
                "status": _STATUS_ALREADY_PAID,
                "amount_applied": 0,
                "balance_remaining": balance,
                "payment_status_after": pstatus,
            }
            continue
        if istatus in _BLOCKED_INVOICE_STATUSES:
            results_by_id[inv_id] = {
                "invoice_id": inv_id,
                "invoice_number": inv.get("invoice_number"),
                "customer_id": inv.get("customer_id"),
                "customer_name": inv.get("customer_name"),
                "status": _STATUS_BLOCKED,
                "amount_applied": 0,
                "balance_remaining": balance,
                "payment_status_after": pstatus,
            }
            continue
        # Eligible — group for second pass.
        by_customer[inv.get("customer_id") or ""].append(inv_id)

    # ─── 3 · Per-customer apply · due_date ASC, created_at ASC ──
    # Mirrors the sweep's ordering so an operator who runs this
    # endpoint right after an auto-sweep sees deterministic results.
    for customer_id, inv_ids in by_customer.items():
        if not customer_id:
            # Headless invoice (no customer linkage) — can't apply.
            for inv_id in inv_ids:
                inv = rows[inv_id]
                results_by_id[inv_id] = {
                    "invoice_id": inv_id,
                    "invoice_number": inv.get("invoice_number"),
                    "customer_id": None,
                    "customer_name": inv.get("customer_name"),
                    "status": _STATUS_NO_CREDIT,
                    "amount_applied": 0,
                    "balance_remaining": _balance_due_dollars(inv),
                    "payment_status_after": (
                        inv.get("payment_status") or "unpaid"),
                }
            continue

        # Sort by (due_date asc, created_at asc) with None-last.
        inv_ids.sort(key=lambda iid: (
            rows[iid].get("due_date") is None,
            rows[iid].get("due_date") or "",
            rows[iid].get("created_at") or "",
        ))

        for inv_id in inv_ids:
            inv = rows[inv_id]
            try:
                res = await apply_credit_to_specific_invoice(
                    db, tid, customer_id, inv_id,
                    actor={"id": (user or {}).get("id"),
                            "email": (user or {}).get("email")},
                    source="bulk_apply_credit",
                )
            except Exception as exc:  # noqa: BLE001
                logger.exception(
                    "[bulk-apply-credit] inner exception "
                    "tenant=%s customer=%s invoice=%s error=%r",
                    tid, customer_id, inv_id, exc,
                )
                results_by_id[inv_id] = {
                    "invoice_id": inv_id,
                    "invoice_number": inv.get("invoice_number"),
                    "customer_id": customer_id,
                    "customer_name": inv.get("customer_name"),
                    "status": _STATUS_ERROR,
                    "error_code": "apply_failed",
                    "amount_applied": 0,
                    "balance_remaining": _balance_due_dollars(inv),
                    "payment_status_after": (
                        inv.get("payment_status") or "unpaid"),
                }
                continue
            applied_dollars = round(res.applied_cents / 100.0, 2)
            # Re-read the (now reconciled) invoice for the fresh
            # balance + payment_status.
            fresh = await db.quotes.find_one(
                {"id": inv_id, "tenant_id": tid},
                {"_id": 0, "payment_status": 1, "total": 1,
                  "amount_paid": 1},
            ) or {}
            fresh_balance = _balance_due_dollars(fresh or inv)
            fresh_status  = _derive_payment_status_after(fresh or inv)
            if applied_dollars > 0:
                status_label = _STATUS_CREDITED
            elif res.starting_credit_cents <= 0:
                status_label = _STATUS_NO_CREDIT
            elif inv_id in (res.skipped_duplicates or []):
                status_label = _STATUS_CREDITED
                # 24h-window duplicate — the service guards against
                # double-apply. Treat as credited (idempotent) with
                # amount_applied=0 so the UX reflects reality.
                applied_dollars = 0.0
            elif res.inconsistencies:
                status_label = _STATUS_ERROR
            else:
                # Credit > 0 but nothing applied — the invoice became
                # ineligible between the pre-filter and the service
                # call (racy, extremely rare). Treat as blocked.
                status_label = _STATUS_BLOCKED
            row = {
                "invoice_id": inv_id,
                "invoice_number": inv.get("invoice_number"),
                "customer_id": customer_id,
                "customer_name": inv.get("customer_name"),
                "status": status_label,
                "amount_applied": applied_dollars,
                "balance_remaining": fresh_balance,
                "payment_status_after": fresh_status,
            }
            if res.inconsistencies and status_label == _STATUS_ERROR:
                row["error_code"] = "inconsistency_detected"
            results_by_id[inv_id] = row

    # ─── 4 · Preserve input order on the way out ────────────────
    results = [results_by_id[iid] for iid in body.invoice_ids]

    # ─── 5 · Summary roll-up ────────────────────────────────────
    summary = {
        "total_selected": len(body.invoice_ids),
        "credited": sum(
            1 for r in results if r["status"] == _STATUS_CREDITED),
        "skipped_no_credit": sum(
            1 for r in results if r["status"] == _STATUS_NO_CREDIT),
        "skipped_already_paid": sum(
            1 for r in results if r["status"] == _STATUS_ALREADY_PAID),
        "skipped_blocked_status": sum(
            1 for r in results if r["status"] == _STATUS_BLOCKED),
        "skipped_not_found": sum(
            1 for r in results if r["status"] == _STATUS_NOT_FOUND),
        "errors": sum(
            1 for r in results if r["status"] == _STATUS_ERROR),
        "total_amount_applied": round(sum(
            float(r.get("amount_applied") or 0) for r in results
        ), 2),
    }

    # ─── 6 · Audit log — single row per request ─────────────────
    try:
        await db.audit_logs.insert_one({
            "id": new_id(),
            "tenant_id": tid,
            "event":  "invoices.bulk_apply_credit",
            "action": "invoices.bulk_apply_credit",
            "actor_id":    (user or {}).get("id"),
            "actor_email": (user or {}).get("email"),
            "request_id": request_id,
            "total_selected": summary["total_selected"],
            "credited":       summary["credited"],
            "total_amount_applied": summary["total_amount_applied"],
            "invoice_ids_sample": list(body.invoice_ids[:10]),
            "created_at": now_iso(),
        })
    except Exception:  # noqa: BLE001
        logger.exception(
            "[bulk-apply-credit] audit insert failed tenant=%s "
            "request_id=%s", tid, request_id,
        )

    return {
        "request_id": request_id,
        "summary": summary,
        "results": results,
    }
