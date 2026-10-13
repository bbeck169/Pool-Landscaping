"""Feb-2026 · Deploy-time one-shot backfill for the credit auto-apply
feature. Iterates every customer with ``credit_balance_cents > 0``
and funnels each through
``services.credit_apply.apply_credit_to_customer_open_invoices``.

Usage::

    cd /app/backend
    # Preview — list what WOULD apply, no writes.
    python -m scripts.backfill_credit_apply --dry-run

    # Commit — writes payments, decrements credits, writes
    # ``audit_logs.credit_apply.backfill_summary`` row, sends admin
    # summary email to ``FOUNDER_SUPER_ADMIN_EMAIL``.
    python -m scripts.backfill_credit_apply --commit

    # Single-tenant scope.
    python -m scripts.backfill_credit_apply --commit --tenant-id=T123

The service's 24-hour idempotency guard means repeated ``--commit``
invocations within the same day will not double-apply.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

logger = logging.getLogger("backfill_credit_apply")


_AUDIT_ACTION = "credit_apply.backfill_summary"
_EMAIL_SUBJECT_FMT = "Credit auto-apply backfill summary · {run_id}"
_EMAIL_BODY_FMT = (
    "Credit auto-apply backfill completed.\n\n"
    "Customers touched: {customers_touched}\n"
    "Invoices updated:  {invoices_updated}\n"
    "Total applied:     ${total_amount_applied}\n"
    "Run id:            {run_id}\n"
    "Started at:        {started_at}\n"
    "Completed at:      {completed_at}\n"
)


def _new_id() -> str:
    from utils import new_id
    return new_id()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _candidate_customers(
    db, *, tenant_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Return every ``(tenant_id, customer_id)`` with a positive
    ``balance_cents`` in ``db.customer_credits_balance``. Scoped to a
    single tenant when ``tenant_id`` is set."""
    _filter: Dict[str, Any] = {"balance_cents": {"$gt": 0}}
    if tenant_id:
        _filter["tenant_id"] = tenant_id
    rows: List[Dict[str, Any]] = []
    async for r in db.customer_credits_balance.find(
        _filter,
        {"_id": 0, "tenant_id": 1, "customer_id": 1, "balance_cents": 1},
    ):
        rows.append(r)
    return rows


async def run_backfill(
    db,
    *,
    dry_run: bool,
    tenant_id: Optional[str] = None,
    send_email: bool = True,
) -> Dict[str, Any]:
    """Main backfill entry point. Returns an aggregated report dict.

    * ``dry_run=True`` — walks candidates, computes what WOULD apply
      (reads only), does NOT call the service.
    * ``dry_run=False`` — calls
      ``apply_credit_to_customer_open_invoices`` per customer,
      aggregates totals, writes the ``audit_logs`` row + sends the
      admin summary email (when ``send_email=True`` and
      ``FOUNDER_SUPER_ADMIN_EMAIL`` is set).
    """
    from services.credit_apply import (
        apply_credit_to_customer_open_invoices,
        _fetch_eligible_open_invoices,
        _read_credit_balance_cents,
    )

    run_id = _new_id()
    started_at = _now_iso()
    customers_touched = 0
    invoices_updated = 0
    total_cents = 0
    per_customer: List[Dict[str, Any]] = []

    candidates = await _candidate_customers(db, tenant_id=tenant_id)
    for row in candidates:
        tid = row.get("tenant_id")
        cid = row.get("customer_id")
        if not tid or not cid:
            continue
        if dry_run:
            # Read-only projection — how many open invoices would
            # be affected and what the net apply would be.
            credit = await _read_credit_balance_cents(db, tid, cid)
            if credit <= 0:
                continue
            opens = await _fetch_eligible_open_invoices(
                db, tid, cid, exclude_invoice_ids=[],
            )
            would_apply_cents = 0
            would_touch: List[str] = []
            remaining = credit
            for inv in opens:
                if remaining <= 0:
                    break
                total_dollars = float(inv.get("total") or 0.0)
                paid_dollars = float(inv.get("amount_paid") or 0.0)
                bal_dollars = round(total_dollars - paid_dollars, 2)
                if bal_dollars <= 1e-9:
                    continue
                bal_cents = int(round(bal_dollars * 100))
                apply_cents = min(remaining, bal_cents)
                if apply_cents <= 0:
                    continue
                would_apply_cents += apply_cents
                would_touch.append(inv.get("id"))
                remaining -= apply_cents
            if would_apply_cents > 0:
                customers_touched += 1
                invoices_updated += len(would_touch)
                total_cents += would_apply_cents
                per_customer.append({
                    "tenant_id": tid,
                    "customer_id": cid,
                    "would_apply_cents": would_apply_cents,
                    "would_touch_invoice_ids": would_touch,
                })
        else:
            result = await apply_credit_to_customer_open_invoices(
                db, tid, cid, actor=None, source="auto",
            )
            if result.applied_cents > 0:
                customers_touched += 1
                invoices_updated += len(result.invoices_touched)
                total_cents += result.applied_cents
                per_customer.append({
                    "tenant_id": tid,
                    "customer_id": cid,
                    "applied_cents": result.applied_cents,
                    "invoices_touched": result.invoices_touched,
                    "invoices_fully_paid": result.invoices_fully_paid,
                    "skipped_duplicates": result.skipped_duplicates,
                    "inconsistencies": result.inconsistencies,
                })

    completed_at = _now_iso()
    total_amount_applied = round(total_cents / 100.0, 2)
    report = {
        "run_id": run_id,
        "started_at": started_at,
        "completed_at": completed_at,
        "dry_run": dry_run,
        "tenant_scope": tenant_id or "ALL",
        "customers_touched": customers_touched,
        "invoices_updated": invoices_updated,
        "total_amount_applied_cents": int(total_cents),
        "total_amount_applied": total_amount_applied,
        "per_customer": per_customer,
    }

    if not dry_run:
        # Audit row — one per committed run.
        try:
            await db.audit_logs.insert_one({
                "id": _new_id(),
                "tenant_id": tenant_id,
                "action": _AUDIT_ACTION,
                "actor_user_id": None,
                "payload": {
                    "run_id": run_id,
                    "started_at": started_at,
                    "completed_at": completed_at,
                    "tenant_scope": tenant_id or "ALL",
                    "customers_touched": customers_touched,
                    "invoices_updated": invoices_updated,
                    "total_amount_applied_cents": int(total_cents),
                },
                "created_at": completed_at,
            })
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "credit_apply.backfill_summary.audit_write_failed "
                "run_id=%s error=%r", run_id, exc,
            )

        # Admin summary email — best-effort.
        if send_email:
            await _send_admin_summary(
                run_id=run_id,
                customers_touched=customers_touched,
                invoices_updated=invoices_updated,
                total_amount_applied=total_amount_applied,
                started_at=started_at,
                completed_at=completed_at,
            )

    return report


async def _send_admin_summary(
    *,
    run_id: str,
    customers_touched: int,
    invoices_updated: int,
    total_amount_applied: float,
    started_at: str,
    completed_at: str,
) -> None:
    """Best-effort admin summary send. No-op when
    ``FOUNDER_SUPER_ADMIN_EMAIL`` is unset."""
    admin_email = (
        os.environ.get("FOUNDER_SUPER_ADMIN_EMAIL") or ""
    ).strip()
    if not admin_email:
        logger.info(
            "credit_apply.backfill_summary.email_skipped "
            "reason=no_admin_email run_id=%s", run_id,
        )
        return
    subject = _EMAIL_SUBJECT_FMT.format(run_id=run_id)
    body = _EMAIL_BODY_FMT.format(
        customers_touched=customers_touched,
        invoices_updated=invoices_updated,
        total_amount_applied=f"{total_amount_applied:.2f}",
        run_id=run_id,
        started_at=started_at,
        completed_at=completed_at,
    )
    try:
        from services.email.resend_adapter import send as _resend_send
        from services.comms_env_guard import CommsContext
        await _resend_send(
            to=admin_email,
            subject=subject,
            html=f"<pre>{body}</pre>",
            context=CommsContext.SYSTEM,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "credit_apply.backfill_summary.email_failed "
            "run_id=%s error=%r", run_id, exc,
        )


def _parse_args(argv: List[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--dry-run", action="store_true",
        help="Preview mode — reads only, writes nothing. Default.",
    )
    p.add_argument(
        "--commit", action="store_true",
        help="Commit mode — writes payments, decrements credits, "
             "writes audit row + sends admin summary email.",
    )
    p.add_argument(
        "--tenant-id", default=None,
        help="Scope the backfill to a single tenant_id. Default: all.",
    )
    p.add_argument(
        "--no-email", action="store_true",
        help="Suppress the admin summary email on commit.",
    )
    args = p.parse_args(argv)
    if not (args.dry_run or args.commit):
        args.dry_run = True
    if args.dry_run and args.commit:
        p.error("--dry-run and --commit are mutually exclusive")
    return args


async def _amain(argv: List[str]) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    args = _parse_args(argv)
    from config import db
    report = await run_backfill(
        db,
        dry_run=args.dry_run,
        tenant_id=args.tenant_id,
        send_email=not args.no_email,
    )
    logger.info(
        "credit_apply.backfill done dry_run=%s tenant_scope=%s "
        "customers_touched=%d invoices_updated=%d total_applied=$%.2f "
        "run_id=%s",
        args.dry_run, report["tenant_scope"],
        report["customers_touched"], report["invoices_updated"],
        report["total_amount_applied"], report["run_id"],
    )
    print(report)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_amain(sys.argv[1:])))
