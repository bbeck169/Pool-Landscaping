"""TD-stripe-webhook-mark-invoice-paid · Feb-2026
================================================

Backfill invoices that received a successful payment-flip from
``services/payments/stripe_charge._mark_invoice_paid`` BEFORE Fix A
landed — those rows carry ``payment_status="paid"`` +
``amount_paid=total`` + ``paid_at`` but their lifecycle ``status``
field was never flipped to ``"paid"`` (stuck on ``"draft"`` /
``"issued"`` / ``"sent"`` / ``"past_due"`` depending on when the
payment arrived).

Why we care: the ``routers/payments_summary.py`` Outstanding filter
double-gates on ``status in _LIVE_STATUSES`` AND
``balance > 0``.  A sub-penny ``amount_paid`` drift (the fully-paid
gate uses ``new_paid + 0.01 >= total``) leaks ``balance > 0``
true → the paid row spuriously stays in Outstanding.  Fix A closes
the write path going forward; this CLI heals the historical rows.
Fix B's ``payment_status != "paid"`` guard on the Outstanding
filter is a parallel belt-and-braces, but we want ``status`` to be
coherent for every downstream filter / report that uses it as a
live/paid proxy — hence the backfill.

Scope
-----
``db.quotes`` rows matching ALL of::

    doc_type        == "invoice"
    payment_status  == "paid"
    status          NOT IN ("paid", "void", "refunded",
                             "partially_refunded")

The NOT-IN list intentionally excludes refund states — a refunded
invoice should preserve ``status`` as the refund flow left it
(see follow-up ``TD-stripe-refund-restore-prepaid-status``). Also
excludes rows that are already ``"paid"`` so a re-run is a no-op.

For each matched row::

    * $set status="paid"
    * $set previous_status_before_paid = <current status>
    * $set paid_status_backfill_v1 = {at, from_status}
      (idempotency breadcrumb)

Partial-payment rows are NEVER touched — the scope filter
requires ``payment_status="paid"`` exactly, so a row at
``"partial"`` falls through.

Flags
-----
``--dry-run``   (default)  — no writes, no sentinel. Prints the
                             counts the real run would apply.
``--report-only``          — Per-tenant / per-row summary table.
                             No writes.
``--apply``                — Perform the writes + record a
                             sentinel in ``db._migrations``.
                             Idempotent.
``--tenant <id>``          — Restrict to one tenant.
``--force``                — Bypass the sentinel short-circuit on
                             re-apply.

Boot wiring
-----------
Deliberately NOT boot-wired. Operator-triggered per the
TD-stripe-webhook-mark-invoice-paid brief. Mirrors the Ticket L
``convert_to_invoice_status_backfill_v1`` ladder exactly so
operator muscle memory applies.

Usage
-----
::

    cd /app/backend
    # 1. Dry-run — print aggregate counts.
    python -m migrations.paid_invoice_status_backfill_v1 --dry-run

    # 2. Report-only — per-tenant summary table.
    python -m migrations.paid_invoice_status_backfill_v1 --report-only

    # 3. Scoped apply — single tenant.
    python -m migrations.paid_invoice_status_backfill_v1 \\
        --apply --tenant <tenant_id>

    # 4. Full apply — every tenant.
    python -m migrations.paid_invoice_status_backfill_v1 --apply

Revert
------
To revert a bad apply (not usually needed — idempotent + scoped)::

    db._migrations.deleteOne({"key": "paid_invoice_status_backfill_v1"})
    # Then per-row revert: set status back to the value stored in
    # ``previous_status_before_paid`` using
    # ``paid_status_backfill_v1`` as the scope filter.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

from config import db, logger  # noqa: E402

_SENTINEL_KEY = "paid_invoice_status_backfill_v1"
_SENTINEL_COLLECTION = "_migrations"

# Scope filter — rows that already carry a terminal / refund status
# are left untouched.
_LEAVE_ALONE_STATUSES = ["paid", "void", "refunded", "partially_refunded"]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _load_tenant_ids(scoped: Optional[str]) -> List[str]:
    if scoped:
        return [scoped]
    out: List[str] = []
    async for t in db.tenants.find({}, {"_id": 0, "id": 1}):
        if t.get("id"):
            out.append(t["id"])
    return out


async def _scan_tenant(tenant_id: str) -> Dict[str, Any]:
    """Enumerate every paid-but-status-not-paid invoice in this tenant."""
    report: Dict[str, Any] = {
        "tenant_id": tenant_id,
        "candidates": 0,
        "candidate_rows": [],
    }
    cursor = db.quotes.find(
        {
            "tenant_id": tenant_id,
            "doc_type": "invoice",
            "payment_status": "paid",
            "status": {"$nin": _LEAVE_ALONE_STATUSES},
        },
        {
            "_id": 0, "id": 1, "invoice_number": 1, "status": 1,
            "payment_status": 1, "amount_paid": 1, "total": 1,
            "paid_at": 1, "customer_id": 1,
        },
    )
    async for inv in cursor:
        report["candidates"] += 1
        report["candidate_rows"].append({
            "id": inv.get("id"),
            "invoice_number": inv.get("invoice_number"),
            "status": inv.get("status"),
            "amount_paid": inv.get("amount_paid"),
            "total": inv.get("total"),
            "paid_at": inv.get("paid_at"),
        })
    return report


async def _apply_tenant(report: Dict[str, Any]) -> int:
    """Flip ``status="paid"`` + stamp ``previous_status_before_paid``
    on every candidate. Belt-and-braces match re-asserts the
    scope filter so a concurrent writer that already moved the row
    into a refund state can't be re-stomped."""
    tenant_id = report["tenant_id"]
    at = _now_iso()
    moved = 0
    for row in report["candidate_rows"]:
        inv_id = row["id"]
        if not inv_id:
            continue
        prev_status = row.get("status") or ""
        res = await db.quotes.update_one(
            {
                "tenant_id": tenant_id,
                "doc_type": "invoice",
                "id": inv_id,
                "payment_status": "paid",
                "status": {"$nin": _LEAVE_ALONE_STATUSES},
            },
            {"$set": {
                "status": "paid",
                "previous_status_before_paid": prev_status,
                "paid_status_backfill_v1": {
                    "at": at,
                    "from_status": prev_status,
                },
            }},
        )
        if int(getattr(res, "modified_count", 0) or 0):
            moved += 1
    return moved


async def _is_sentinel_clean() -> bool:
    doc = await db[_SENTINEL_COLLECTION].find_one({"key": _SENTINEL_KEY})
    if not doc or doc.get("mode") != "apply":
        return False
    stats = doc.get("stats") or {}
    return int(stats.get("candidates_after", 1)) == 0


async def _write_sentinel(stats: Dict[str, Any], mode: str) -> None:
    doc = {
        "id": _SENTINEL_KEY,
        "key": _SENTINEL_KEY,
        "phase": "TD-stripe-webhook-mark-invoice-paid",
        "mode": mode,
        "completed_at": _now_iso(),
        "stats": stats,
    }
    await db[_SENTINEL_COLLECTION].update_one(
        {"key": _SENTINEL_KEY},
        {"$set": doc},
        upsert=True,
    )


async def run(
    *,
    apply: bool = False,
    report_only: bool = False,
    tenant_id: Optional[str] = None,
    force: bool = False,
) -> Dict[str, Any]:
    """Run the backfill. Semantics mirror
    ``convert_to_invoice_status_backfill_v1.run`` from Ticket L."""
    # Loop-rebind shim for Motor's ``_io_loop`` guard.
    try:
        from config import client as _client  # noqa: PLC0415
        _client._io_loop = asyncio.get_running_loop()
    except Exception:  # noqa: BLE001
        pass

    if report_only and apply:
        raise ValueError(
            "--report-only and --apply are mutually exclusive "
            "(report-only forbids writes).")

    if apply and not force and not tenant_id and await _is_sentinel_clean():
        return {"status": "skipped", "reason": "sentinel-clean"}

    tenant_ids = await _load_tenant_ids(tenant_id)
    all_reports: List[Dict[str, Any]] = []
    total_candidates = 0
    total_moved = 0
    for tid in tenant_ids:
        rep = await _scan_tenant(tid)
        all_reports.append(rep)
        total_candidates += rep["candidates"]
        if apply and rep["candidates"]:
            moved = await _apply_tenant(rep)
            rep["moved"] = moved
            total_moved += moved
        else:
            rep["moved"] = 0

    stats: Dict[str, Any] = {
        "tenants": len(tenant_ids),
        "candidates": total_candidates,
        "moved": total_moved,
    }

    logger.info(
        "[paid_status_backfill] apply=%s report_only=%s "
        "tenants=%s candidates=%s moved=%s",
        apply, report_only, stats["tenants"],
        total_candidates, total_moved,
    )

    if apply:
        remaining = 0
        for tid in tenant_ids:
            rp = await _scan_tenant(tid)
            remaining += rp["candidates"]
        stats["candidates_after"] = remaining
        stats["clean"] = remaining == 0
        await _write_sentinel(stats, "apply")

    status = (
        "report-only" if report_only
        else "applied" if apply
        else "dry-run"
    )
    return {
        "status": status,
        "stats": stats,
        "reports": all_reports,
    }


def _format_report_table(out: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append("=" * 78)
    lines.append(
        "TD-stripe-webhook-mark-invoice-paid · report-only")
    lines.append("=" * 78)
    stats = out["stats"]
    lines.append(f"tenants scanned:            {stats['tenants']}")
    lines.append(f"candidate invoices total:   {stats['candidates']}")
    lines.append("-" * 78)
    for rep in out["reports"]:
        if not rep["candidates"]:
            continue
        lines.append(
            f"[tenant={rep['tenant_id']}]  candidates={rep['candidates']}")
        for row in rep["candidate_rows"][:10]:
            lines.append(
                f"  invoice_number={row['invoice_number'] or '<none>'}  "
                f"id={row['id']}  status={row['status']!r}  "
                f"amount_paid={row['amount_paid']}/{row['total']}  "
                f"paid_at={row['paid_at']}")
        if len(rep["candidate_rows"]) > 10:
            lines.append(
                f"  … +{len(rep['candidate_rows']) - 10} more rows")
    lines.append("=" * 78)
    return "\n".join(lines)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=(
            "Backfill status=paid on invoices whose "
            "payment_status is already 'paid' but whose lifecycle "
            "status was never flipped by the pre-fix "
            "_mark_invoice_paid (TD-stripe-webhook-mark-invoice-paid)."
        ),
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--apply", action="store_true",
                        help="Perform writes (default: dry-run)")
    group.add_argument("--dry-run", action="store_true",
                        help="Explicit dry-run (default behaviour)")
    group.add_argument("--report-only", action="store_true",
                        help="Per-tenant summary table; no writes.")
    parser.add_argument("--tenant", default=None,
                        help="Restrict to a single tenant id")
    parser.add_argument("--force", action="store_true",
                        help=("Bypass the sentinel short-circuit "
                              "on --apply"))
    ns = parser.parse_args()
    out = asyncio.run(run(
        apply=ns.apply,
        report_only=ns.report_only,
        tenant_id=ns.tenant,
        force=ns.force,
    ))
    if ns.report_only:
        print(_format_report_table(out))
    else:
        print(json.dumps(out, indent=2, default=str))
