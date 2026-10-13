"""Feb-2026 · Automation eligibility gate — single source of truth
for whether an invoice should fire a specific automation.

Two rules enforced here:

1. ``automations_suppressed=True`` on the invoice → skip for ALL
   automation kinds.  Stamped at write time by the PDF importer
   (see ``services/imports/pdf_commit._build_quote_doc_from_preview``);
   native invoice write sites stamp ``False`` explicitly so legacy
   invoices (field absent) still fire.

2. For ``automation_kind in {"payment_reminder", "dunning"}``:
   fire ONLY when ``payment_status == "unpaid"`` AND
   ``status`` is not in ``{"draft", "void", "cancelled"}``.

Reason strings are stable — audit log consumers / log greps rely
on exact tokens:

    pdf_import_suppressed
    soft_deleted
    payment_status_<status>
    invoice_status_<status>

The helper also exports :func:`log_batch_skipped` — called by
cron sweeps that batch-skip N invoices in a run so operators
have per-tenant visibility into why reminders / dunning didn't
fire.  See ``services/marketing/phase1_sweeps._sweep_invoice_overdue``,
``services/marketing/drip_events._sweep_past_due``, and
``routers/dunning._scan_tenant`` for call sites.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple

from config import db
from utils import new_id, now_iso


logger = logging.getLogger(__name__)


# Automation kinds that gate on payment status + invoice status.
_PAYMENT_STATUS_GATED_KINDS = frozenset({"payment_reminder", "dunning"})

# Invoice ``status`` values that NEVER get reminder / dunning
# traffic — mirror of the user's dispatch spec.
_INVALID_INVOICE_STATUSES = frozenset({"draft", "void", "cancelled"})


def is_invoice_eligible_for_automation(
    invoice: Dict[str, Any],
    *,
    automation_kind: str,
) -> Tuple[bool, Optional[str]]:
    """Return ``(eligible, skip_reason)``.

    Legacy invoices without the ``automations_suppressed`` field
    default to NOT suppressed — live traffic that pre-dates this
    gate is unaffected.
    """
    if invoice.get("automations_suppressed") is True:
        return (False, "pdf_import_suppressed")
    if invoice.get("deleted_at"):
        return (False, "soft_deleted")

    if automation_kind in _PAYMENT_STATUS_GATED_KINDS:
        pstat = invoice.get("payment_status") or "unpaid"
        if pstat != "unpaid":
            return (False, f"payment_status_{pstat}")
        istat = (invoice.get("status") or "").lower()
        if istat in _INVALID_INVOICE_STATUSES:
            return (False, f"invoice_status_{istat}")

    return (True, None)


async def log_batch_skipped(
    *,
    tenant_id: Optional[str],
    automation_kind: str,
    run_id: str,
    reason_breakdown: Dict[str, int],
    total_skipped: int,
) -> None:
    """Write a single ``automation.batch_skipped`` row to
    ``db.audit_logs`` after a cron run that skipped at least one
    invoice.  Non-fatal — never raises; failure logs a WARNING
    and the caller continues.

    Shape (greppable for operators)::

        {"action": "automation.batch_skipped",
         "tenant_id": "...",
         "automation_kind": "dunning",
         "run_id": "...",
         "total_skipped": 42,
         "reason_breakdown": {"pdf_import_suppressed": 10,
                               "payment_status_paid": 32}}

    Operators can grep for ``action: automation.batch_skipped``
    across the audit log collection or filter by
    ``tenant_id`` + ``automation_kind`` to see per-tenant per-kind
    skip volumes.
    """
    if total_skipped <= 0:
        return
    try:
        await db.audit_logs.insert_one({
            "id": new_id(),
            "action": "automation.batch_skipped",
            "tenant_id": tenant_id,
            "automation_kind": automation_kind,
            "run_id": run_id,
            "total_skipped": int(total_skipped),
            "reason_breakdown": dict(reason_breakdown or {}),
            "created_at": now_iso(),
        })
    except Exception as exc:  # noqa: BLE001 — defensive
        logger.warning(
            "[automations.eligibility] batch_skipped audit insert "
            "failed tenant=%s kind=%s err=%s",
            (tenant_id or "")[:8], automation_kind, exc,
        )
