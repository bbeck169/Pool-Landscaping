"""Feb-2026 · FIN-PAID-STATUS-PARITY backfill — v1.

One-shot migration that reconciles legacy ``quotes`` rows where
``payment_status == "paid"`` AND ``status != "paid"``. These are the
rows left stuck by the write-path asymmetry fixed in Commits 1a + 1b:

  * Before Commit 1a: ``record_payment`` / ``pay_quote`` / the
    import reconciler all set ``status = "accepted"`` on fully-paid
    transitions. Downstream filters that key off ``status`` as the
    paid-proxy (``payments_summary._LIVE_STATUSES``, ``reports``
    paid-filter, ``referral_watcher``) kept these rows visible on
    the wrong surfaces.
  * Before Commit 1b: the Phase-47 Checkout Session webhook consumer
    ``_mark_invoice_paid_from_session`` had the same bug.

Commits 1a + 1b fix the WRITE paths for NEW payments. This migration
fixes the LEGACY STUCK rows by flipping ``status → "paid"`` and
stamping the ``previous_status_before_paid`` audit crumb with the
prior value so a future refund-restore flow
(``TD-stripe-refund-restore-prepaid-status``) can roll back cleanly.

CONTRACT:

  * **Scope** — ``doc_type == "invoice"`` AND
    ``payment_status == "paid"`` AND ``status not in ("paid",
    "void", "cancelled", "refunded")``.  The exclude-list protects
    terminal-non-paid states from being accidentally re-labelled
    (a voided invoice that was partially refunded might carry
    ``payment_status="paid"`` from the pre-refund state; we leave
    those alone — the refund flow owns that lifecycle).

  * **Idempotent** — the WHERE clause excludes already-fixed rows,
    so re-running against a fully-migrated DB reports
    ``matched=0, modified=0``.

  * **Audit crumb preservation** — ``previous_status_before_paid``
    is ONLY written when the row doesn't already carry one. If
    a row somehow got the crumb from a half-run previous attempt,
    this migration leaves the crumb alone and only flips ``status``.
    Guarantees: a future refund-restore flow can always trust the
    crumb to carry the ORIGINAL pre-paid status.

  * **Audit trail** — a single ``migration_runs`` doc is written
    per invocation with the counts + a ``dry_run`` flag. Multi-
    tenant runs produce multiple audit rows (one per tenant).

  * **Tenant scoping** — the function accepts ``tenant_id``; passing
    ``None`` targets ALL tenants (super_admin-only path). The admin
    endpoint always passes an explicit tenant from the caller's
    scope.

CLI usage:
    python /app/backend/migrations/backfill_paid_invoice_status_v1.py
    python /app/backend/migrations/backfill_paid_invoice_status_v1.py --apply
    python /app/backend/migrations/backfill_paid_invoice_status_v1.py --tenant-id aquaterra --apply
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402
from dotenv import dotenv_values  # noqa: E402


logger = logging.getLogger("backfill_paid_invoice_status_v1")

# Terminal-non-paid states that we MUST NOT re-label to "paid".
# A voided / cancelled / refunded invoice whose ``payment_status``
# still reads "paid" from the pre-refund state is NOT a candidate —
# the refund flow owns that lifecycle (see TD-stripe-refund-restore-
# prepaid-status). The exclude-list is defensive: if any of these
# were missed by the refund flow and left in a bad state, this
# backfill will NOT compound the problem by over-labelling.
_TERMINAL_NON_PAID = ("paid", "void", "cancelled", "refunded")


def _build_query(tenant_id: Optional[str]) -> Dict[str, Any]:
    q: Dict[str, Any] = {
        "doc_type": "invoice",
        "payment_status": "paid",
        "status": {"$nin": list(_TERMINAL_NON_PAID)},
    }
    if tenant_id:
        q["tenant_id"] = tenant_id
    return q


async def backfill_paid_invoice_status(
    db,
    *,
    tenant_id: Optional[str] = None,
    dry_run: bool = True,
) -> Dict[str, Any]:
    """Flip ``status`` to ``"paid"`` on legacy stuck rows.

    Returns ``{"matched": N, "modified": M, "crumbs_written": C,
    "dry_run": bool, "tenant_id": str|None}``.

    Writes one ``migration_runs`` audit doc on a non-dry-run call.
    """
    query = _build_query(tenant_id)
    matched = 0
    modified = 0
    crumbs_written = 0
    now_iso = datetime.now(timezone.utc).isoformat()

    # One-at-a-time so the ``previous_status_before_paid`` crumb
    # carries the ROW-SPECIFIC prior ``status`` (a bulk ``$set``
    # with a single value would collapse all crumbs to the same
    # literal and lose the audit trail). The N is small (preview
    # snapshot shows ~tens of rows per tenant), so a loop is fine.
    #
    # Target by ``_id`` not ``id`` so duplicate ``id`` rows across
    # tenants (a known legacy data-integrity artifact — see the
    # analytics-ip-salt backfill) each get their own write.
    cursor = db.quotes.find(
        query, {"_id": 1, "id": 1, "status": 1, "tenant_id": 1,
                 "previous_status_before_paid": 1},
    )
    async for row in cursor:
        matched += 1
        if dry_run:
            continue

        set_fields: Dict[str, Any] = {
            "status": "paid",
            "backfilled_at": now_iso,
            "backfilled_by": "backfill_paid_invoice_status_v1",
        }
        # Audit crumb preservation — only write the crumb if the
        # row doesn't already carry one. A half-run previous
        # attempt or a Fix-A-era write may already have set it;
        # NEVER clobber it with the terminal ``"paid"`` literal.
        if row.get("previous_status_before_paid") is None:
            set_fields["previous_status_before_paid"] = row.get("status")
            crumbs_written += 1

        res = await db.quotes.update_one(
            {"_id": row["_id"]},
            {"$set": set_fields},
        )
        modified += int(res.modified_count or 0)

    result = {
        "matched": matched,
        "modified": modified,
        "crumbs_written": crumbs_written,
        "dry_run": dry_run,
        "tenant_id": tenant_id,
    }

    if not dry_run:
        # Audit row — one per invocation.  The ``migration_runs``
        # collection is the shipped audit stream for one-shot
        # migrations (see sibling scripts
        # ``scripts/k79_customer_group_display_migration.py``,
        # ``scripts/i15d_theme_migration.py``).
        audit_doc = {
            "id": str(uuid.uuid4()),
            "migration": "backfill_paid_invoice_status_v1",
            "ran_at": now_iso,
            "tenant_id": tenant_id,
            "matched": matched,
            "modified": modified,
            "crumbs_written": crumbs_written,
        }
        try:
            await db.migration_runs.insert_one(audit_doc)
        except Exception as exc:  # pragma: no cover — best-effort
            logger.warning(
                "[backfill_paid_invoice_status_v1] audit insert "
                "failed: %s", exc,
            )

    return result


async def _cli(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Backfill status='paid' on legacy stuck invoices "
            "(payment_status='paid' AND status not in terminal set)."
        ),
    )
    parser.add_argument(
        "--tenant-id",
        default=None,
        help="Restrict to a single tenant_id. Omit for ALL tenants.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help=(
            "Actually write. Default is dry-run (prints the match "
            "count without flipping anything)."
        ),
    )
    args = parser.parse_args(argv)

    env = dotenv_values(
        str(Path(__file__).resolve().parents[1] / ".env"),
    )
    mongo_url = env.get("MONGO_URL") or ""
    db_name = env.get("DB_NAME") or ""
    if not mongo_url or not db_name:
        print(
            "MONGO_URL / DB_NAME missing from backend/.env",
            file=sys.stderr,
        )
        sys.exit(2)
    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]

    scope = f"tenant={args.tenant_id}" if args.tenant_id else "ALL TENANTS"
    print(f"== paid-status backfill · dry-run · scope={scope} ==")
    dry = await backfill_paid_invoice_status(
        db, tenant_id=args.tenant_id, dry_run=True,
    )
    print(f"stuck rows: matched={dry['matched']}")
    if dry["matched"] == 0:
        print("Nothing to migrate — already idempotent.")
        return
    if not args.apply:
        print("Dry-run only. Re-run with --apply to write.")
        return

    print(f"== paid-status backfill · real-run · scope={scope} ==")
    real = await backfill_paid_invoice_status(
        db, tenant_id=args.tenant_id, dry_run=False,
    )
    print(
        f"matched={real['matched']} modified={real['modified']} "
        f"crumbs_written={real['crumbs_written']}"
    )
    print("Re-running dry to confirm idempotence...")
    dry2 = await backfill_paid_invoice_status(
        db, tenant_id=args.tenant_id, dry_run=True,
    )
    assert dry2["matched"] == 0, (
        f"post-run dry showed matched={dry2['matched']} — "
        "not idempotent!"
    )
    print("Idempotent OK ✓")


if __name__ == "__main__":
    asyncio.run(_cli())
