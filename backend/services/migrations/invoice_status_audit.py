"""Feb-2026 · P0 fix — Orphan-paid invoice audit.

Root case: real customer received an invoice link, opened it, and
saw ``Status: paid · Amount Paid: $197.00 · Total Due: $0.00`` —
but had never entered a card. Cause was a code path silently
flipping ``payment_status = "paid"`` without recording a matching
payment_record.

This migration scans every tenant for invoice docs whose
``payment_status == "paid"`` state is not backed by any evidence:

  * No ``payment_records`` array (or empty).
  * No ``stripe_payment_intent_id``.
  * No ``stripe_checkout_session_id``.
  * No ``paid_method`` in the whitelist (service_credit, manual_cash,
    manual_check, manual_ach, import — all of which stamp the field
    when they run today).

Those rows get flipped to ``pending_reconciliation`` (NOT ``unpaid``
— we don't want to imply the customer never paid; we're saying "we
can't prove they paid; please reconcile"). Every flip writes to
``db.invoice_status_audit`` for a full trail.

Idempotent + sentinel-guarded
(``feb2026_orphan_paid_audit_v1``). Two entry points:

  * ``run_orphan_paid_audit()`` — boot-time; respects the sentinel
    by default so a re-boot doesn't re-scan.
  * ``run_orphan_paid_audit(force=True, dry_run=True/False)`` —
    super_admin admin endpoint; ``dry_run=True`` returns the diff
    without writing.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from config import db


logger = logging.getLogger("invoice_orphan_paid_audit")


_SENTINEL_ID = "feb2026_orphan_paid_audit_v1"


# ``paid_method`` values that carry their OWN evidence trail (either
# an internal proof — like ``service_credit`` implying a credits
# ledger row — or an explicit operator action). Rows with one of
# these values are considered evidence-backed and NOT flipped.
_PROVEN_METHODS = {
    "stripe_checkout", "stripe_card_on_file", "stripe", "stripe_pi",
    "manual_cash", "manual_check", "manual_ach",
    "service_credit", "import",
    # Legacy method names still on disk from earlier phases.
    "cash", "check", "ach", "wire",
}


def _orphan_filter() -> Dict[str, Any]:
    """Query fragment matching orphan-paid docs."""
    return {
        "doc_type": "invoice",
        "payment_status": "paid",
        "$and": [
            {"$or": [
                {"payment_records": {"$exists": False}},
                {"payment_records": {"$size": 0}},
                {"payment_records": None},
            ]},
            {"$or": [
                {"stripe_payment_intent_id": {"$exists": False}},
                {"stripe_payment_intent_id": None},
                {"stripe_payment_intent_id": ""},
            ]},
            {"$or": [
                {"stripe_checkout_session_id": {"$exists": False}},
                {"stripe_checkout_session_id": None},
                {"stripe_checkout_session_id": ""},
            ]},
            {"$or": [
                {"paid_method": {"$exists": False}},
                {"paid_method": None},
                {"paid_method": ""},
                {"paid_method": {"$nin": list(_PROVEN_METHODS)}},
            ]},
            # Never touch soft-deleted invoices.
            {"$or": [
                {"deleted_at": None},
                {"deleted_at": {"$exists": False}},
            ]},
        ],
    }


async def _sentinel_row() -> Optional[Dict[str, Any]]:
    return await db.migrations.find_one({"id": _SENTINEL_ID}, {"_id": 0})


async def _write_sentinel(summary: Dict[str, Any]) -> None:
    await db.migrations.update_one(
        {"id": _SENTINEL_ID},
        {"$set": {
            "id": _SENTINEL_ID,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "summary": summary,
        }},
        upsert=True,
    )


async def run_orphan_paid_audit(
    *, force: bool = False, dry_run: bool = False,
) -> Dict[str, Any]:
    """Full-fleet audit.

    ``force=False`` (default): respects the sentinel — a second run
    on the same DB reports ``status: 'skipped'``.

    ``dry_run=True``: match + report the diff, don't write. Used by
    the admin endpoint's default gate before a real flip.
    """
    if not force:
        sentinel = await _sentinel_row()
        if sentinel:
            logger.info(
                "[orphan-paid-audit] sentinel present — skipping "
                "(completed_at=%s)",
                sentinel.get("completed_at"),
            )
            return {
                "status": "skipped",
                "reason": "sentinel_present",
                "sentinel": sentinel,
            }

    scanned = 0
    corrected = 0
    errors: List[Dict[str, Any]] = []
    per_tenant: Dict[str, int] = {}
    now = datetime.now(timezone.utc).isoformat()

    cursor = db.quotes.find(
        _orphan_filter(),
        {"_id": 0, "id": 1, "tenant_id": 1, "customer_id": 1,
          "customer_name": 1, "total": 1, "amount_paid": 1,
          "title": 1, "paid_at": 1, "invoice_number": 1,
          "payment_status": 1},
    ).sort([("tenant_id", 1), ("paid_at", 1)])
    async for doc in cursor:
        scanned += 1
        tid = doc.get("tenant_id")
        iid = doc.get("id")
        if not (tid and iid):
            errors.append({"id": iid, "reason": "missing_tenant_or_id"})
            continue
        if dry_run:
            per_tenant[tid] = per_tenant.get(tid, 0) + 1
            corrected += 1
            continue
        try:
            audit_id = str(uuid.uuid4())
            await db.invoice_status_audit.insert_one({
                "id": audit_id,
                "tenant_id": tid,
                "invoice_id": iid,
                "previous_status": "paid",
                "corrected_status": "pending_reconciliation",
                "reason": "orphan_paid_no_payment_record",
                "actor_user_id": None,
                "snapshot": {
                    "customer_name": doc.get("customer_name"),
                    "invoice_number": doc.get("invoice_number"),
                    "title": doc.get("title"),
                    "total": doc.get("total"),
                    "amount_paid": doc.get("amount_paid"),
                    "paid_at": doc.get("paid_at"),
                },
                "corrected_at": now,
            })
            await db.quotes.update_one(
                {"id": iid, "tenant_id": tid},
                {"$set": {
                    "payment_status": "pending_reconciliation",
                    # Preserve ``paid_at`` on the doc so downstream
                    # ledger queries can still see when the flip
                    # first happened, but flag the reconcile state.
                    "reconciliation_required": True,
                    "reconciliation_flagged_at": now,
                }},
            )
            corrected += 1
            per_tenant[tid] = per_tenant.get(tid, 0) + 1
            logger.info(
                "[orphan-paid-audit] flipped invoice=%s tenant=%s "
                "customer=%s title=%r → pending_reconciliation",
                iid, tid, doc.get("customer_name"),
                (doc.get("title") or "")[:60],
            )
        except Exception as _exc:                                # noqa: BLE001
            errors.append({
                "id": iid,
                "reason": f"flip_failed: {_exc}",
            })

    summary = {
        "scanned": scanned,
        "corrected": corrected,
        "errors_count": len(errors),
        "per_tenant": per_tenant,
        "dry_run": dry_run,
    }
    # Only stamp the sentinel on a REAL (non-dry) full run so a
    # dry-run doesn't lock out the follow-up write pass.
    if not force and not dry_run:
        await _write_sentinel(summary)

    logger.info(
        "[orphan-paid-audit] complete · scanned=%d corrected=%d "
        "errors=%d dry_run=%s",
        scanned, corrected, len(errors), dry_run,
    )
    return {
        "status": "ok",
        "summary": summary,
        "errors": errors[:50],
    }
