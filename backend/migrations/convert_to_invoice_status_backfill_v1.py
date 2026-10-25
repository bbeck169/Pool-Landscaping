"""TD-estimate-to-invoice-conversion-doctype-and-balance · Feb-2026
=================================================================

Backfill converted invoices that were inserted BEFORE Fix B landed
(``services/invoice_builder.py:154`` previously stamped
``status="draft"``) so operator-visible Outstanding tiles pick them
up. Optionally repair placeholder ``title`` strings on the same rows
(Fix A — ``title="Estimate"`` etc. displayed under the InvoicesList
"Invoice" column).

Scope
-----
``db.quotes`` rows matching ALL of::

    doc_type   == "invoice"
    source     in ("convert_from_quote", "convert_from_estimate")
    status     == "draft"

For each matched row::

    * $set status="issued"
    * $set issued_at = <existing converted_at> OR <now_iso()>
    * $set convert_status_backfill_v1 = {at, from_status, chain}
      (idempotency breadcrumb so a re-run visibly reports as a no-op)

When ``--skip-title-repair`` is NOT passed, a parallel pass against
the SAME scope rewrites placeholder titles to "Invoice". Match set
mirrors ``_PLACEHOLDER_SOURCE_TITLES`` in ``services/invoice_builder.py``.
Custom titles (e.g. "Pool Repair — Main pump") are preserved verbatim.

Flags
-----
``--dry-run``           (default) — no writes, no sentinel. Prints
                        the counts the real run would apply.
``--report-only``       Like ``--dry-run`` but emits a per-tenant
                        summary table on stdout. No writes.
``--apply``             Perform the writes + record a sentinel in
                        ``db._migrations``. Idempotent.
``--tenant <id>``       Restrict scan + apply to one tenant.
``--force``             Bypass the sentinel short-circuit on re-apply.
``--skip-title-repair`` Skip the title placeholder repair pass.
                        Status flip + ``issued_at`` stamp still run.

Boot wiring
-----------
Deliberately NOT boot-wired. Operator-triggered per the
TD-estimate-to-invoice-conversion-doctype-and-balance brief.
Changes AR-tile values — operator must dry-run first.

Usage
-----
::

    cd /app/backend
    # 1. Dry-run — print aggregate counts.
    python -m migrations.convert_to_invoice_status_backfill_v1 --dry-run

    # 2. Report-only — per-tenant summary table.
    python -m migrations.convert_to_invoice_status_backfill_v1 --report-only

    # 3. Scoped apply — single tenant.
    python -m migrations.convert_to_invoice_status_backfill_v1 \\
        --apply --tenant <tenant_id>

    # 4. Full apply — every tenant.
    python -m migrations.convert_to_invoice_status_backfill_v1 --apply

    # 5. Status-only apply (skip title repair).
    python -m migrations.convert_to_invoice_status_backfill_v1 \\
        --apply --skip-title-repair

Revert
------
To revert a bad apply (not usually needed — idempotent + scoped)::

    db._migrations.deleteOne({"key": "convert_to_invoice_status_backfill_v1"})
    # Then manually revert the ``status`` + ``title`` fields on the
    # affected rows using the ``convert_status_backfill_v1`` breadcrumb
    # as a scope filter.
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

_SENTINEL_KEY = "convert_to_invoice_status_backfill_v1"
_SENTINEL_COLLECTION = "_migrations"

# Mirror of the catalogue in ``services/invoice_builder.py``. Kept
# duplicated (not imported) so the CLI has no cross-module coupling
# that could complicate a future module rename.
_PLACEHOLDER_SOURCE_TITLES: frozenset[str] = frozenset({
    "",
    "estimate",
    "new estimate",
    "quote",
    "new quote",
    "proposal",
    "untitled",
})

_CONVERT_SOURCES = ["convert_from_quote", "convert_from_estimate"]


# ═════════════════════════════════════════════════════════════
# Helpers
# ═════════════════════════════════════════════════════════════
def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_placeholder_title(title: Any) -> bool:
    """Case-insensitive trimmed match against the placeholder set."""
    if title is None:
        return True
    return str(title).strip().lower() in _PLACEHOLDER_SOURCE_TITLES


async def _load_tenant_ids(scoped: Optional[str]) -> List[str]:
    if scoped:
        return [scoped]
    out: List[str] = []
    async for t in db.tenants.find({}, {"_id": 0, "id": 1}):
        if t.get("id"):
            out.append(t["id"])
    return out


# ═════════════════════════════════════════════════════════════
# Core scan
# ═════════════════════════════════════════════════════════════
async def _scan_tenant(
    tenant_id: str, *, skip_title_repair: bool,
) -> Dict[str, Any]:
    """Enumerate every convert-sourced ``status=draft`` invoice in
    this tenant. Build a per-tenant report with status + title
    repair counts.
    """
    report: Dict[str, Any] = {
        "tenant_id": tenant_id,
        "candidates": 0,
        "status_flips": 0,
        "title_repairs": 0,
        "custom_titles_preserved": 0,
        "candidate_rows": [],   # [{id, invoice_number, title, source, converted_at}]
    }
    cursor = db.quotes.find(
        {
            "tenant_id": tenant_id,
            "doc_type": "invoice",
            "source": {"$in": _CONVERT_SOURCES},
            "status": "draft",
        },
        {
            "_id": 0, "id": 1, "invoice_number": 1, "title": 1,
            "source": 1, "converted_at": 1, "customer_id": 1,
        },
    )
    async for inv in cursor:
        report["candidates"] += 1
        report["status_flips"] += 1    # every candidate flips status
        title = inv.get("title")
        if _is_placeholder_title(title) and not skip_title_repair:
            report["title_repairs"] += 1
        else:
            report["custom_titles_preserved"] += 1
        report["candidate_rows"].append({
            "id": inv.get("id"),
            "invoice_number": inv.get("invoice_number"),
            "title": title,
            "source": inv.get("source"),
            "converted_at": inv.get("converted_at"),
        })
    return report


async def _apply_tenant(
    report: Dict[str, Any], *, skip_title_repair: bool,
) -> Dict[str, int]:
    """Flip ``status="draft" → "issued"`` + stamp ``issued_at`` on every
    candidate. Belt-and-braces filter re-matches ``status="draft"`` so
    a double-run moves zero rows. Title repair is a per-row update_one
    (needs the id-specific placeholder gate) to avoid clobbering any
    row whose title was manually edited between scan + apply.
    """
    tenant_id = report["tenant_id"]
    at = _now_iso()
    status_moved = 0
    title_moved = 0

    for row in report["candidate_rows"]:
        inv_id = row["id"]
        if not inv_id:
            continue
        # Prefer the stored ``converted_at`` for ``issued_at`` when
        # present — the conversion really happened then, not now.
        # Fall back to current wall-clock only when the row lacks the
        # audit stamp (shouldn't happen for convert-sourced rows but
        # defend anyway).
        issued_at = row.get("converted_at") or at

        set_fields: Dict[str, Any] = {
            "status": "issued",
            "convert_status_backfill_v1": {
                "at": at,
                "from_status": "draft",
                "issued_at_source": (
                    "converted_at" if row.get("converted_at")
                    else "now"
                ),
            },
        }
        # Only stamp ``issued_at`` when the row doesn't already carry
        # one — matches auto_invoice.py's semantic (``issued_at`` is
        # the issuance anchor, not a repair timestamp).
        res = await db.quotes.update_one(
            {
                "tenant_id": tenant_id,
                "doc_type": "invoice",
                "id": inv_id,
                "status": "draft",      # belt-and-braces re-check
            },
            [
                {"$set": {
                    **set_fields,
                    "issued_at": {
                        "$cond": [
                            {"$in": [
                                {"$ifNull": ["$issued_at", None]},
                                [None, ""],
                            ]},
                            issued_at,
                            "$issued_at",
                        ],
                    },
                }},
            ],
        )
        if int(getattr(res, "modified_count", 0) or 0):
            status_moved += 1

        # Title repair pass — scoped to placeholder-titled rows,
        # skipped when the operator passed ``--skip-title-repair``.
        if not skip_title_repair and _is_placeholder_title(row.get("title")):
            # Re-check the title on write so a concurrent manual
            # rename doesn't get clobbered.
            t_res = await db.quotes.update_one(
                {
                    "tenant_id": tenant_id,
                    "doc_type": "invoice",
                    "id": inv_id,
                },
                [
                    {"$set": {
                        "title": {
                            "$cond": [
                                {"$in": [
                                    {"$toLower": {
                                        "$trim": {
                                            "input": {
                                                "$ifNull": ["$title", ""],
                                            },
                                        },
                                    }},
                                    list(_PLACEHOLDER_SOURCE_TITLES),
                                ]},
                                "Invoice",
                                "$title",
                            ],
                        },
                        "convert_title_backfill_v1": {
                            "at": at,
                            "from_title": row.get("title"),
                        },
                    }},
                ],
            )
            if int(getattr(t_res, "modified_count", 0) or 0):
                title_moved += 1

    return {"status_moved": status_moved, "title_moved": title_moved}


# ═════════════════════════════════════════════════════════════
# Sentinel
# ═════════════════════════════════════════════════════════════
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
        "phase": "TD-estimate-to-invoice-conversion-doctype-and-balance",
        "mode": mode,
        "completed_at": _now_iso(),
        "stats": stats,
    }
    await db[_SENTINEL_COLLECTION].update_one(
        {"key": _SENTINEL_KEY},
        {"$set": doc},
        upsert=True,
    )


# ═════════════════════════════════════════════════════════════
# Public entry
# ═════════════════════════════════════════════════════════════
async def run(
    *,
    apply: bool = False,
    report_only: bool = False,
    tenant_id: Optional[str] = None,
    force: bool = False,
    skip_title_repair: bool = False,
) -> Dict[str, Any]:
    """Run the backfill. Semantics mirror
    ``invoice_customer_id_repoint_merged_v1.run`` so operator muscle-
    memory from the earlier CLI applies verbatim here.
    """
    # Loop-rebind for test fixtures that run each test on a fresh
    # event loop (same shim as the sibling migration — Motor's
    # ``_io_loop`` guard trips otherwise).
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
    total_status_moved = 0
    total_title_moved = 0
    for tid in tenant_ids:
        rep = await _scan_tenant(tid, skip_title_repair=skip_title_repair)
        all_reports.append(rep)
        total_candidates += rep["candidates"]
        if apply and rep["candidates"]:
            moved = await _apply_tenant(
                rep, skip_title_repair=skip_title_repair,
            )
            rep["status_moved"] = moved["status_moved"]
            rep["title_moved"] = moved["title_moved"]
            total_status_moved += moved["status_moved"]
            total_title_moved += moved["title_moved"]
        else:
            rep["status_moved"] = 0
            rep["title_moved"] = 0

    stats: Dict[str, Any] = {
        "tenants": len(tenant_ids),
        "candidates": total_candidates,
        "status_moved": total_status_moved,
        "title_moved": total_title_moved,
        "skip_title_repair": skip_title_repair,
    }

    logger.info(
        "[convert_status_backfill] apply=%s report_only=%s "
        "tenants=%s candidates=%s status_moved=%s title_moved=%s "
        "skip_title=%s",
        apply, report_only, stats["tenants"], total_candidates,
        total_status_moved, total_title_moved, skip_title_repair,
    )

    if apply:
        # Post-apply rescan to confirm zero candidates remain.
        remaining = 0
        for tid in tenant_ids:
            rp = await _scan_tenant(
                tid, skip_title_repair=skip_title_repair,
            )
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


# ═════════════════════════════════════════════════════════════
# Report-only pretty printer
# ═════════════════════════════════════════════════════════════
def _format_report_table(out: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append("=" * 78)
    lines.append(
        "TD-estimate-to-invoice-conversion-doctype-and-balance · report-only")
    lines.append("=" * 78)
    stats = out["stats"]
    lines.append(f"tenants scanned:            {stats['tenants']}")
    lines.append(f"candidate invoices total:   {stats['candidates']}")
    lines.append(f"skip_title_repair:          {stats['skip_title_repair']}")
    lines.append("-" * 78)
    for rep in out["reports"]:
        if not rep["candidates"]:
            continue
        lines.append(
            f"[tenant={rep['tenant_id']}]  "
            f"candidates={rep['candidates']}  "
            f"status_flips={rep['status_flips']}  "
            f"title_repairs={rep['title_repairs']}  "
            f"custom_titles_preserved={rep['custom_titles_preserved']}")
        for row in rep["candidate_rows"][:10]:
            lines.append(
                f"  invoice_number={row['invoice_number'] or '<none>'}  "
                f"id={row['id']}  title={row['title']!r}  "
                f"source={row['source']}")
        if len(rep["candidate_rows"]) > 10:
            lines.append(
                f"  … +{len(rep['candidate_rows']) - 10} more rows")
    lines.append("=" * 78)
    return "\n".join(lines)


# ═════════════════════════════════════════════════════════════
# CLI
# ═════════════════════════════════════════════════════════════
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=(
            "Backfill status=draft → issued on convert-sourced "
            "invoices (TD-estimate-to-invoice-conversion-doctype-"
            "and-balance). Optional parallel pass repairs "
            "placeholder titles under the InvoicesList Invoice column."
        ),
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--apply", action="store_true",
                        help="Perform writes (default: dry-run)")
    group.add_argument("--dry-run", action="store_true",
                        help="Explicit dry-run (default behaviour)")
    group.add_argument("--report-only", action="store_true",
                        help=("Print per-tenant summary table; "
                              "no writes."))
    parser.add_argument("--tenant", default=None,
                        help="Restrict to a single tenant id")
    parser.add_argument("--force", action="store_true",
                        help=("Bypass the sentinel short-circuit "
                              "on --apply"))
    parser.add_argument("--skip-title-repair", action="store_true",
                        help=("Skip the placeholder-title repair "
                              "pass. Status flip + issued_at stamp "
                              "still run."))
    ns = parser.parse_args()
    out = asyncio.run(run(
        apply=ns.apply,
        report_only=ns.report_only,
        tenant_id=ns.tenant,
        force=ns.force,
        skip_title_repair=ns.skip_title_repair,
    ))
    if ns.report_only:
        print(_format_report_table(out))
    else:
        print(json.dumps(out, indent=2, default=str))
