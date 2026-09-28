"""FIN-PARITY-C · Feb-2026 — recompute ``amount_paid`` /
``payment_status`` / ``status`` / ``paid_at`` for every invoice
from its linked ``db.payments`` rows.

Delegates the actual write path to
``services.imports.payment_reconciler.reconcile_invoice_after_payment``
so this migration and the FIN-PARITY-A commit-time path stay
byte-identical.  Dry-run pre-computes what the reconciler would
write using ``_compute_payment_status`` + the same tolerance
constant — no logic reimplementation, just read-only preview.

Pathological data-integrity guard
─────────────────────────────────
The reconciler treats "0 linked payments" as a valid reconcile
input and flips ``payment_status=paid → unpaid`` on those rows.
For a migration sweep that is DANGEROUS: an invoice that a
pre-FIN-PARITY code path marked ``paid`` (perhaps via a manual
mongo write, an old ``record_payment`` variant, or a customer-
portal path that predates ``db.payments``) has NO payment rows
to sum from, so the reconciler would silently unpay it.  This
migration pre-checks the ``paid`` + ``0 payments`` case, writes a
``paid_flag_without_payments`` audit row for operator review, and
SKIPS the reconciler for that invoice.  The operator resolves the
data integrity issue manually.

Idempotent — the reconciler's own ``if transitions: update`` guard
means a re-run against an already-reconciled row issues zero
writes.  Guarded again at the migration level: rows with no
planned transitions never call into the reconciler.
Tenant-scoped — one tenant per invocation via ``--tenant``.
Resume-safe — ``--resume-from <invoice_id>`` skips rows with
``id <= <value>``.
Dry-run default — ``--apply`` opts in to actual writes.

Usage
    # Dry-run:
    python /app/backend/migrations/recompute_amount_paid_v1.py \
        --tenant tenant_abc

    # Apply:
    python /app/backend/migrations/recompute_amount_paid_v1.py \
        --tenant tenant_abc --apply

    # Resume:
    python /app/backend/migrations/recompute_amount_paid_v1.py \
        --tenant tenant_abc --apply --resume-from inv_id_last
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# Allow ``python migrations/recompute_amount_paid_v1.py`` invocation.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import dotenv_values  # noqa: E402
from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

from services.imports.payment_reconciler import (  # noqa: E402
    FULLY_PAID_TOLERANCE,
    PAYMENT_STATUS_PAID,
    _compute_payment_status,
    reconcile_invoice_after_payment,
)

logger = logging.getLogger("migrations.recompute_amount_paid_v1")

AUDIT_SOURCE = "recompute_amount_paid_v1"

# Data-integrity audit code — invoice was marked paid without any
# ``db.payments`` rows to back the claim.  Migration skips these
# rows (see module docstring) and logs the audit for operator
# resolution.
DATA_INTEGRITY_CODE_PAID_WITHOUT_PAYMENTS = "paid_flag_without_payments"


def _make_db_from_env():
    """Instantiate a motor client the same way the app does."""
    be_env = dotenv_values(
        Path(__file__).resolve().parents[1] / ".env"
    )
    mongo_url = be_env.get("MONGO_URL") or os.environ.get("MONGO_URL")
    db_name = be_env.get("DB_NAME") or os.environ.get("DB_NAME")
    if not mongo_url or not db_name:
        raise RuntimeError(
            "MONGO_URL / DB_NAME not set — cannot run backfill."
        )
    client = AsyncIOMotorClient(mongo_url)
    return client[db_name]


# ══════════════════════════════════════════════════════════════════
# Read-only preview — mirrors the reconciler's write plan without
# issuing any writes. Used by ``--dry-run`` reporting AND the
# apply path (so we can suppress the reconciler call entirely on
# no-op rows — belt-and-braces on top of the reconciler's own
# ``if transitions:`` guard).
# ══════════════════════════════════════════════════════════════════
async def _sum_payments(
    db, *, tenant_id: str, invoice_id: str,
) -> tuple[float, int]:
    """Return ``(total_paid_rounded_2dp, payments_count)`` for the
    invoice.  Uses the same soft-delete filter shape the
    reconciler uses (see ``reconcile_invoice_after_payment``)."""
    cursor = db.payments.find(
        {
            "tenant_id": tenant_id,
            "invoice_id": invoice_id,
            "$or": [
                {"deleted_at": None},
                {"deleted_at": {"$exists": False}},
            ],
        },
        {"_id": 0, "amount": 1},
    )
    total = 0.0
    count = 0
    async for p in cursor:
        total += float(p.get("amount") or 0.0)
        count += 1
    return round(total, 2), count


def _plan_from_state(
    *,
    invoice: Dict[str, Any],
    total_paid: float,
) -> Dict[str, Any]:
    """Given the current invoice row + summed payments, return the
    planned reconciled state (matches what the reconciler would
    write).  ``transitions`` is empty when the row is already
    in-sync — mirroring the reconciler's ``if transitions:`` guard.

    Uses the reconciler's exposed helpers so the two paths cannot
    drift: change the rule in ``_compute_payment_status`` and both
    reconciler + migration follow.
    """
    prior_amount_paid = float(invoice.get("amount_paid") or 0.0)
    prior_payment_status = invoice.get("payment_status") or "unpaid"
    prior_status = invoice.get("status") or "sent"
    total = float(invoice.get("total") or 0.0)

    new_payment_status = _compute_payment_status(total_paid, total)
    persisted_amount_paid = min(total_paid, total)

    is_new_full_pay = (
        new_payment_status == PAYMENT_STATUS_PAID
        and prior_status != "accepted"
    )
    new_status = "accepted" if is_new_full_pay else prior_status

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

    return {
        "invoice_id": invoice["id"],
        "prior_amount_paid": prior_amount_paid,
        "new_amount_paid": persisted_amount_paid,
        "prior_payment_status": prior_payment_status,
        "new_payment_status": new_payment_status,
        "prior_status": prior_status,
        "new_status": new_status,
        "transitions": transitions,
        "is_new_full_pay": is_new_full_pay,
    }


async def _iter_invoices(
    db, *, tenant_id: str, resume_from: Optional[str],
):
    """Yield ``db.quotes`` invoice docs for one tenant, sorted by
    ``id`` ASC, skipping soft-deleted rows and honoring resume."""
    query: Dict[str, Any] = {
        "tenant_id": tenant_id,
        "doc_type": "invoice",
        "$or": [
            {"deleted_at": None},
            {"deleted_at": {"$exists": False}},
        ],
    }
    if resume_from:
        query["id"] = {"$gt": resume_from}
    cursor = db.quotes.find(
        query,
        {
            "_id": 0, "id": 1, "tenant_id": 1,
            "total": 1, "amount_paid": 1,
            "payment_status": 1, "status": 1, "paid_at": 1,
        },
    ).sort([("id", 1)])
    async for inv in cursor:
        yield inv


async def _write_data_integrity_audit(
    db,
    *,
    tenant_id: str,
    invoice: Dict[str, Any],
    now_iso: str,
) -> str:
    """Emit one ``paid_flag_without_payments`` audit row.  Returns
    the audit row id."""
    audit_id = str(uuid.uuid4())
    await db.import_audit.insert_one({
        "id": audit_id,
        "tenant_id": tenant_id,
        "action": "recompute_amount_paid_v1_skip",
        "invoice_id": invoice["id"],
        "audit_source": AUDIT_SOURCE,
        "operator_user_id": None,
        "code": DATA_INTEGRITY_CODE_PAID_WITHOUT_PAYMENTS,
        "prior_amount_paid": float(invoice.get("amount_paid") or 0.0),
        "prior_payment_status": invoice.get("payment_status"),
        "prior_status": invoice.get("status"),
        "total": float(invoice.get("total") or 0.0),
        "at": now_iso,
    })
    return audit_id


async def run_recompute(
    db,
    *,
    tenant_id: str,
    apply: bool = False,
    resume_from: Optional[str] = None,
) -> Dict[str, Any]:
    """Run the recompute for one tenant.  Returns a summary dict
    (invoices scanned / touched / flagged / fields written / audit
    ids / last invoice id).
    """
    scanned = 0
    touched = 0
    flagged = 0
    reconcile_audit_ids: List[str] = []
    integrity_audit_ids: List[str] = []
    last_invoice_id: Optional[str] = None

    now_iso = datetime.now(timezone.utc).isoformat()

    async for invoice in _iter_invoices(
        db, tenant_id=tenant_id, resume_from=resume_from,
    ):
        scanned += 1
        last_invoice_id = invoice.get("id") or last_invoice_id

        total_paid, payments_count = await _sum_payments(
            db, tenant_id=tenant_id, invoice_id=invoice["id"],
        )

        # ── Data-integrity pre-check ────────────────────────
        # Invoice claims paid but has no db.payments rows — do
        # NOT call the reconciler (it would flip paid → unpaid).
        prior_ps = invoice.get("payment_status") or "unpaid"
        if payments_count == 0 and prior_ps == PAYMENT_STATUS_PAID:
            flagged += 1
            logger.warning(
                "[recompute_amount_paid_v1] invoice=%s tenant=%s "
                "code=%s prior_amount_paid=%.2f total=%.2f — "
                "SKIPPING reconciler, requires operator review",
                invoice["id"], tenant_id,
                DATA_INTEGRITY_CODE_PAID_WITHOUT_PAYMENTS,
                float(invoice.get("amount_paid") or 0.0),
                float(invoice.get("total") or 0.0),
            )
            if apply:
                audit_id = await _write_data_integrity_audit(
                    db, tenant_id=tenant_id, invoice=invoice,
                    now_iso=now_iso,
                )
                integrity_audit_ids.append(audit_id)
            continue

        # ── Preview the reconciled state ─────────────────────
        plan = _plan_from_state(
            invoice=invoice, total_paid=total_paid,
        )
        if not plan["transitions"]:
            # Already in sync — reconciler would issue no writes.
            continue

        touched += 1
        logger.info(
            "[recompute_amount_paid_v1] invoice=%s tenant=%s "
            "payments=%d transitions=%s",
            invoice["id"], tenant_id, payments_count,
            plan["transitions"],
        )
        for t in plan["transitions"]:
            logger.info("  · %s", t)

        if not apply:
            continue

        # ── Delegate to the reconciler for the actual write.
        # The reconciler writes ``amount_paid`` / ``payment_status``
        # / ``status`` / ``paid_at`` and inserts one
        # ``db.import_audit`` row with ``action="invoice_reconciled"``
        # and ``audit_source=recompute_amount_paid_v1`` (below).
        result = await reconcile_invoice_after_payment(
            db,
            tenant_id=tenant_id,
            invoice_id=invoice["id"],
            audit_source=AUDIT_SOURCE,
            audit_actor="migration",
        )
        if result.audit_id:
            reconcile_audit_ids.append(result.audit_id)

    summary = {
        "tenant_id": tenant_id,
        "scanned": scanned,
        "touched": touched,
        "flagged": flagged,
        "reconcile_audit_ids": reconcile_audit_ids,
        "integrity_audit_ids": integrity_audit_ids,
        "last_invoice_id": last_invoice_id,
        "apply": apply,
    }
    logger.info("[recompute_amount_paid_v1] summary=%s", summary)
    return summary


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="FIN-PARITY-C · recompute invoice amount_paid "
                    "from linked db.payments rows.",
    )
    parser.add_argument(
        "--tenant", required=True,
        help="Tenant id to process (one tenant per run).",
    )
    parser.add_argument(
        "--apply", action="store_true",
        help="Actually write changes.  Default is dry-run.",
    )
    parser.add_argument(
        "--resume-from", default=None,
        help="Skip every invoice whose id sorts <= this value.",
    )
    return parser.parse_args()


async def _main() -> int:
    args = _parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    db = _make_db_from_env()
    summary = await run_recompute(
        db,
        tenant_id=args.tenant,
        apply=args.apply,
        resume_from=args.resume_from,
    )
    print("--- summary ---")
    for k, v in summary.items():
        print(f"{k}: {v}")
    print(f"tolerance: {FULLY_PAID_TOLERANCE}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
