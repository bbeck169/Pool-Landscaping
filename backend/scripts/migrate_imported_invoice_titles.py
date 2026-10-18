"""TD-72 · Feb-2026 — One-shot migration · rewrite stored title for
imported invoices whose ``title`` field still carries the ugly
``Import #<n>`` placeholder.

Companion to TD-71 (display-time resolver at
``frontend/src/lib/portalInvoiceTitle.js``) — TD-71 fixed the
customer-facing portal LIST, THIS migration rewrites the STORED
title field so every downstream consumer (admin invoice list,
PDF renderer, admin exports, legacy clients, email templates)
also sees the human-friendly label.

Usage::

    cd /app/backend
    # Preview — report counts, no writes. DEFAULT.
    python -m scripts.migrate_imported_invoice_titles

    # Commit — rewrite the matching invoice titles.
    python -m scripts.migrate_imported_invoice_titles --apply

    # Single-tenant scope.
    python -m scripts.migrate_imported_invoice_titles --tenant T123 --apply

The resolver chain mirrors TD-71 EXACTLY (operator-ruled parity
between display + storage):

  1. ``line_items[0].description || line_items[0].title`` — first
     line item.
  2. ``notes.strip()`` truncated to 120 chars + U+2026 ellipsis
     when longer (storage limit is 120, not 80 — stored titles
     have more display headroom than list-row titles).
  3. ``Service — MM/DD/YYYY`` fallback using the same
     ``created_at`` (or ``invoice_date`` fallback) field TD-71
     surfaces as "Created".

Idempotent — re-running the script after the first ``--apply``
scans the same rows but finds zero titles matching the ugly
pattern (because they've all been rewritten) and reports zero
updates. Multi-tenant safe — never cross-writes. Title-only
writes — amounts, status, line items, notes, dates, flags all
untouched. Writes a run summary to
``/app/memory/migration_imported_invoice_titles.md``.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

logger = logging.getLogger("migrate_imported_invoice_titles")


# ═════════════════════════════════════════════════════════════════
# Resolver — pure function, mirrors TD-71 FE helper contract.
# ═════════════════════════════════════════════════════════════════

# Matches ``Import #259`` + whitespace variants + case-insensitive
# — identical regex to the FE ``_IMPORT_TITLE_RE`` so the two
# surfaces classify consistently.
_IMPORT_TITLE_RE = re.compile(r"^\s*Import\s*#\s*\d+\s*$", re.IGNORECASE)


def is_imported_placeholder_title(invoice: Dict[str, Any]) -> bool:
    """True when ``invoice.title`` matches the TD-71 ugly pattern."""
    title = invoice.get("title") or ""
    return bool(_IMPORT_TITLE_RE.match(str(title)))


def _format_service_fallback_date(invoice: Dict[str, Any]) -> str:
    """Return ``MM/DD/YYYY`` from ``created_at`` / ``invoice_date``.

    The TD-71 FE helper uses the browser's local timezone — but
    the migration runs server-side so we use UTC consistently. If
    tenant-level timezone handling becomes a requirement, this is
    the single swap-point (operator Q3=UTC for now).
    """
    raw = invoice.get("created_at") or invoice.get("invoice_date")
    if raw is None:
        return ""
    try:
        if isinstance(raw, datetime):
            dt = raw
        else:
            s = str(raw).replace("Z", "+00:00")
            dt = datetime.fromisoformat(s)
    except (TypeError, ValueError):
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return f"{dt.month:02d}/{dt.day:02d}/{dt.year:04d}"


def resolve_imported_title(
    invoice: Dict[str, Any],
) -> Tuple[str, str]:
    """Resolve the replacement title + the branch label.

    Returns a ``(new_title, branch)`` tuple. ``branch`` is one of
    ``"line_item"`` / ``"notes"`` / ``"fallback"`` so the run-
    summary report can bucket counts per branch.
    """
    # 1. line_items[0].description || .title
    items = invoice.get("line_items")
    if isinstance(items, list) and items:
        first = items[0] if isinstance(items[0], dict) else {}
        label = (first.get("description") or first.get("title") or "")
        label = str(label).strip()
        if label:
            return (label, "line_item")

    # 2. notes trimmed + truncated to 120 chars with ellipsis.
    notes = str(invoice.get("notes") or "").strip()
    if notes:
        if len(notes) <= 120:
            return (notes, "notes")
        return (notes[:120].rstrip() + "\u2026", "notes")

    # 3. ``Service — MM/DD/YYYY`` fallback.
    date_part = _format_service_fallback_date(invoice)
    if date_part:
        return (f"Service — {date_part}", "fallback")
    # Edge case: no usable date either — operator-ruled "NOT the
    # import number" so use the neutral literal.
    return ("Service", "fallback")


# ═════════════════════════════════════════════════════════════════
# Migration driver.
# ═════════════════════════════════════════════════════════════════

_MEMORY_SUMMARY_PATH = Path("/app/memory/migration_imported_invoice_titles.md")


async def _iter_imported_invoices(db, tenant: Optional[str] = None):
    """Yield ``quotes`` docs where ``doc_type == 'invoice'`` AND
    the title matches the ugly ``Import #<n>`` pattern AND the doc
    is flagged as imported.

    Flag discriminator (any truthy value counts):
      * ``source == 'import'``
      * ``import_batch_id`` present + non-null
      * ``import_number``   present + non-null

    Title regex is enforced server-side via Mongo ``$regex`` so
    the collection scan is bounded (hits the title index when
    present).
    """
    query = {
        "doc_type": "invoice",
        "title": {"$regex": r"^\s*Import\s*#\s*\d+\s*$", "$options": "i"},
        "$or": [
            {"source": "import"},
            {"import_batch_id": {"$exists": True, "$ne": None}},
            {"import_number":   {"$exists": True, "$ne": None}},
        ],
    }
    if tenant:
        query["tenant_id"] = tenant
    async for inv in db.quotes.find(query):
        yield inv


async def migrate(db, apply: bool, tenant: Optional[str] = None) -> Dict[str, Any]:
    """Run the migration. Returns a report dict.

    The function body is directly testable — ``apply=False`` is a
    pure read-only scan + classify, ``apply=True`` performs the
    atomic ``{$set: {title: <new>}}`` write per doc.
    """
    scanned = 0
    matched = 0
    updated = 0
    skipped_already_fine = 0
    failed: List[Dict[str, str]] = []
    by_branch: Dict[str, int] = {"line_item": 0, "notes": 0, "fallback": 0}

    async for inv in _iter_imported_invoices(db, tenant=tenant):
        scanned += 1
        inv_id = inv.get("id") or str(inv.get("_id"))
        try:
            # Idempotency guard — if title doesn't match the ugly
            # pattern we skip even though the mongo filter should
            # have excluded it. Belt + suspenders.
            if not is_imported_placeholder_title(inv):
                skipped_already_fine += 1
                continue
            matched += 1
            new_title, branch = resolve_imported_title(inv)
            if apply:
                res = await db.quotes.update_one(
                    {"_id": inv["_id"], "title": inv["title"]},
                    {"$set": {"title": new_title}},
                )
                if res.modified_count == 1:
                    updated += 1
                    by_branch[branch] = by_branch.get(branch, 0) + 1
                else:
                    failed.append({"id": inv_id, "reason": "update_matched_no_rows"})
            else:
                # Dry-run — still bucket by branch so the preview
                # report accurately projects the apply-run.
                by_branch[branch] = by_branch.get(branch, 0) + 1
        except Exception as exc:  # pragma: no cover — defensive
            failed.append({"id": inv_id, "reason": f"{type(exc).__name__}: {exc}"})

    # Non-imported title count (regression lock — the apply branch
    # MUST NOT touch any non-imported invoice. We don't modify
    # non-imported docs so this is a count-equality assertion
    # between pre- and post- apply runs; emit the count here so
    # the operator can diff it externally.)
    non_imported_count = await db.quotes.count_documents({
        "doc_type": "invoice",
        "title": {"$not": {"$regex": r"^\s*Import\s*#\s*\d+\s*$", "$options": "i"}},
    })

    return {
        "mode": "apply" if apply else "dry-run",
        "tenant": tenant or "all",
        "scanned": scanned,
        "matched": matched,
        "updated": updated,
        "skipped_already_fine": skipped_already_fine,
        "failed_count": len(failed),
        "failed": failed,
        "updated_by_branch": by_branch,
        "non_imported_count": non_imported_count,
    }


# ═════════════════════════════════════════════════════════════════
# Memory-doc summary writer.
# ═════════════════════════════════════════════════════════════════

def _format_summary(report: Dict[str, Any]) -> str:
    now = datetime.now(timezone.utc).isoformat()
    lines = [
        f"### TD-72 · migrate_imported_invoice_titles · {now}",
        f"",
        f"- mode: `{report['mode']}`",
        f"- tenant scope: `{report['tenant']}`",
        f"- scanned: **{report['scanned']}**",
        f"- matched (title regex + imported flag): **{report['matched']}**",
        f"- updated: **{report['updated']}**",
        f"- skipped (already fine): **{report['skipped_already_fine']}**",
        f"- failed: **{report['failed_count']}**",
        f"- non-imported invoice count (regression lock): **{report['non_imported_count']}**",
        f"- updated-by-branch:",
    ]
    for branch, n in report["updated_by_branch"].items():
        lines.append(f"  * `{branch}`: **{n}**")
    if report["failed"]:
        lines.append("- failed ids:")
        for f in report["failed"]:
            lines.append(f"  * `{f['id']}` — {f['reason']}")
    lines.append("")
    return "\n".join(lines)


def _append_summary(report: Dict[str, Any]) -> None:
    """Append the report to the memory doc. Creates the file +
    header if it doesn't exist yet."""
    _MEMORY_SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    header = (
        "# TD-72 · migrate_imported_invoice_titles · run history\n\n"
        "Companion to TD-71 (display-time resolver). This file\n"
        "accumulates one entry per invocation of\n"
        "`scripts/migrate_imported_invoice_titles.py` on either\n"
        "preview or (operator-driven) prod.\n\n"
    )
    exists = _MEMORY_SUMMARY_PATH.exists()
    with _MEMORY_SUMMARY_PATH.open("a", encoding="utf-8") as f:
        if not exists:
            f.write(header)
        f.write(_format_summary(report))


# ═════════════════════════════════════════════════════════════════
# CLI entry.
# ═════════════════════════════════════════════════════════════════

async def _amain(args: argparse.Namespace) -> int:
    # Load env + build Mongo client here (avoids import-time env
    # requirements for the pytest).
    from pathlib import Path as _P
    from dotenv import load_dotenv
    load_dotenv(_P(__file__).resolve().parents[1] / ".env")
    from motor.motor_asyncio import AsyncIOMotorClient
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]

    report = await migrate(db, apply=args.apply, tenant=args.tenant)
    _append_summary(report)
    # Print a one-line human summary.
    logger.info(
        "[TD-72] mode=%s tenant=%s scanned=%d matched=%d updated=%d "
        "skipped_already_fine=%d failed=%d by_branch=%s non_imported=%d",
        report["mode"], report["tenant"],
        report["scanned"], report["matched"], report["updated"],
        report["skipped_already_fine"], report["failed_count"],
        report["updated_by_branch"], report["non_imported_count"],
    )
    print(_format_summary(report))
    return 0 if report["failed_count"] == 0 else 1


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--apply",
        action="store_true",
        help="Commit writes to Mongo. Omit for dry-run (default).",
    )
    p.add_argument(
        "--tenant",
        type=str,
        default=None,
        help="Scope the run to a single tenant_id. Default: all tenants.",
    )
    args = p.parse_args()
    return asyncio.run(_amain(args))


if __name__ == "__main__":
    sys.exit(main())
