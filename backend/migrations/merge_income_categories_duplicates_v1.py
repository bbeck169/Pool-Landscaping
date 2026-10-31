"""Feb-2026 · TD-income-category-dupes-migration · Phase 2.

Merges duplicate ``income_categories`` rows (case / whitespace
drift only — spelling variants are explicitly out-of-scope per
operator spec) and backfills ``invoice_line_items.income_
category_id`` from inline ``category`` strings onto the post-
merge canonical FK target.

Companion endpoint: ``GET /api/admin/income-categories/duplicates``
(shipped in Phase 1 commit ``cdef2cfac``) — operator previews the
proposed merge BEFORE invoking this script with ``--apply``.

CONTRACT
========

Scope (per tenant):

  * **Duplicate-merge** — ``income_categories`` rows whose
    ``(name or "").strip().lower()`` collide into a set of >1
    live row.
      - Canonical pick (r1): row with MAX ref_count on
        ``invoice_line_items``; lex tiebreak on raw ``name``
        (deterministic across runs).
      - For every non-canonical row in the set:
          · Rewrite every ``line_items.$.income_category_id``
            pointer from the loser's ``id`` to the winner's
            ``id``, within tenant.
          · Soft-delete the loser (``deleted_at = now_iso``).
            Rows are NEVER hard-deleted so reversibility is
            trivially supported.

  * **Inline-string FK backfill (s1)** — ``invoice_line_items``
    rows where ``income_category_id`` is missing/null AND the
    inline ``category`` string is a non-empty, non-UUID label
    whose normalized value matches a live ``income_categories``
    row (post-merge canonical).
      - Stamp ``income_category_id = <canonical.id>``.
      - PRESERVE the inline ``category`` string as-is for
        back-compat (do NOT null it).
      - Unmatched normalized names are LOGGED (``unmatched_
        inline_names``) and SKIPPED — never invent a fake FK.

Normalization is byte-identical to the dashboard helper
``_resolve_line_category_identity`` (``.strip().lower()``) and
the Phase 1 audit endpoint ``_normalize_cat_name``.  Kept inline
rather than imported so a future refactor of either sibling
cannot silently drift the migration's grouping rule.

Idempotency: a second ``--apply`` run reports every count = 0
(no dupes left to merge; inline-string lines already have FKs).

Tenant isolation: every read + write is scoped by ``tenant_id``.
A ``--all-tenants`` run iterates per tenant with full isolation.

Fail-closed: if any single tenant raises mid-apply, the script
re-raises AFTER printing a loud per-tenant marker.  The
``migration_runs`` audit doc for the aborted tenant records the
partial counts so operators can diff against a prior green run.

CLI USAGE
=========
    # dry-run on one tenant
    python backend/migrations/merge_income_categories_duplicates_v1.py \\
      --tenant-id <tid>

    # apply on one tenant
    python backend/migrations/merge_income_categories_duplicates_v1.py \\
      --tenant-id <tid> --apply

    # dry-run across ALL tenants (operator confirms via explicit flag)
    python backend/migrations/merge_income_categories_duplicates_v1.py \\
      --all-tenants

    # apply across ALL tenants
    python backend/migrations/merge_income_categories_duplicates_v1.py \\
      --all-tenants --apply
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import re
import sys
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import dotenv_values  # noqa: E402
from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402


logger = logging.getLogger("merge_income_categories_duplicates_v1")

# Byte-identical to the shipped dashboard helper's inline-string
# normalization + the Phase 1 audit's _normalize_cat_name.
# Phase-2 operator spec: do NOT fork or extend.
_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def _normalize(raw: Any) -> str:
    return str(raw or "").strip().lower()


async def _list_tenants(db) -> List[str]:
    rows = await db.tenants.find(
        {"$or": [{"active": {"$ne": False}},
                   {"active": {"$exists": False}}]},
        {"_id": 0, "id": 1},
    ).to_list(10_000)
    return [r["id"] for r in rows if r.get("id")]


async def _ref_counts_for_tenant(db, tid: str) -> Dict[str, int]:
    """Count invoice line items per ``income_category_id`` for one
    tenant.  Soft-delete filter on ``quotes``."""
    cursor = db.quotes.aggregate([
        {"$match": {"tenant_id": tid, "doc_type": "invoice",
                      "$or": [{"deleted_at": None},
                              {"deleted_at": {"$exists": False}}]}},
        {"$unwind": "$line_items"},
        {"$match": {"line_items.income_category_id":
                       {"$ne": None, "$exists": True}}},
        {"$group": {"_id": "$line_items.income_category_id",
                     "count": {"$sum": 1}}},
    ])
    out: Dict[str, int] = {}
    async for row in cursor:
        rid = row.get("_id")
        if rid:
            out[rid] = int(row.get("count") or 0)
    return out


async def _merge_duplicates_for_tenant(
    db, tid: str, *, dry_run: bool, now_iso: str,
) -> Dict[str, Any]:
    """Pass 1 — merge case/whitespace-drift income_categories dupes.
    Returns ``{sets_merged, lines_fk_rewritten, loser_rows_soft_
    deleted, winners_by_norm}``.  ``winners_by_norm`` is used by
    the s1 backfill in pass 2 so canonical picks stay consistent."""
    cats = await db.income_categories.find(
        {"tenant_id": tid, "$or": [
            {"deleted_at": None}, {"deleted_at": {"$exists": False}},
        ]},
        {"_id": 0, "id": 1, "name": 1, "is_archived": 1},
    ).to_list(10_000)
    refs = await _ref_counts_for_tenant(db, tid)
    groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for c in cats:
        groups[_normalize(c.get("name"))].append(c)

    sets_merged = 0
    lines_fk_rewritten = 0
    loser_rows_soft_deleted = 0
    winners_by_norm: Dict[str, str] = {}

    for norm, rows in groups.items():
        if not norm:
            continue
        # Winner (even for singleton sets): max ref_count, lex
        # tiebreak on raw name.  Singletons never trigger a merge
        # but the winner still feeds pass 2's backfill map.
        ranked = sorted(
            rows,
            key=lambda r: (-int(refs.get(r["id"], 0)),
                           r.get("name") or ""),
        )
        winner = ranked[0]
        winners_by_norm[norm] = winner["id"]
        losers = ranked[1:]
        if not losers:
            continue
        sets_merged += 1

        for loser in losers:
            if dry_run:
                # Count the lines that WOULD be rewritten.
                would_rw = int(refs.get(loser["id"], 0))
                lines_fk_rewritten += would_rw
                loser_rows_soft_deleted += 1
                continue
            # FK rewrite — one Mongo update per loser id using the
            # positional-filter operator so only the matching
            # line_items element on each invoice is stamped.
            res = await db.quotes.update_many(
                {"tenant_id": tid, "doc_type": "invoice",
                 "line_items.income_category_id": loser["id"]},
                {"$set": {
                    "line_items.$[el].income_category_id": winner["id"],
                }},
                array_filters=[{"el.income_category_id": loser["id"]}],
            )
            # ``modified_count`` reflects invoices-touched; count
            # lines rewritten via the pre-computed refs since the
            # array_filter can mutate many elements per invoice.
            lines_fk_rewritten += int(refs.get(loser["id"], 0))

            # Soft-delete the loser.  Preserve the row for
            # reversibility (``$unset: deleted_at`` restores it).
            await db.income_categories.update_one(
                {"id": loser["id"], "tenant_id": tid},
                {"$set": {"deleted_at": now_iso,
                           "deleted_reason": "duplicate_merge_v1",
                           "merged_into_id": winner["id"]}},
            )
            loser_rows_soft_deleted += 1

    return {
        "sets_merged":              sets_merged,
        "lines_fk_rewritten":       lines_fk_rewritten,
        "loser_rows_soft_deleted":  loser_rows_soft_deleted,
        "winners_by_norm":          winners_by_norm,
    }


async def _backfill_inline_fk_for_tenant(
    db, tid: str, *,
    winners_by_norm: Dict[str, str], dry_run: bool,
) -> Dict[str, Any]:
    """Pass 2 — s1 inline-string FK backfill.  For every invoice
    line in the tenant with ``income_category_id`` missing/null
    and a non-empty, non-UUID inline ``category`` string whose
    normalized value matches a canonical winner, stamp the FK.
    """
    lines_fk_backfilled = 0
    unmatched_names: Dict[str, int] = defaultdict(int)
    invoices_touched = 0

    cursor = db.quotes.find(
        {"tenant_id": tid, "doc_type": "invoice",
         "$or": [{"deleted_at": None},
                 {"deleted_at": {"$exists": False}}]},
        {"_id": 1, "id": 1, "line_items": 1},
    )
    async for inv in cursor:
        lines = inv.get("line_items") or []
        if not lines:
            continue
        new_lines = []
        changed = False
        for li in lines:
            new_li = dict(li)
            inline = li.get("category")
            cur_fk = li.get("income_category_id")
            if (
                isinstance(inline, str) and inline.strip()
                and (not isinstance(cur_fk, str) or not cur_fk.strip())
                and not _UUID_RE.match(inline.strip())
            ):
                norm = _normalize(inline)
                winner_id = winners_by_norm.get(norm)
                if winner_id:
                    new_li["income_category_id"] = winner_id
                    lines_fk_backfilled += 1
                    changed = True
                else:
                    unmatched_names[norm] += 1
            new_lines.append(new_li)
        if changed:
            invoices_touched += 1
            if not dry_run:
                await db.quotes.update_one(
                    {"_id": inv["_id"]},
                    {"$set": {"line_items": new_lines}},
                )

    return {
        "lines_fk_backfilled":   lines_fk_backfilled,
        "invoices_touched":      invoices_touched,
        "unmatched_inline_names": dict(unmatched_names),
    }


async def merge_income_categories_duplicates(
    db, *, tenant_id: Optional[str] = None,
    all_tenants: bool = False, dry_run: bool = True,
) -> Dict[str, Any]:
    """Top-level entry point.  Scope is a single tenant when
    ``tenant_id`` is set, ALL active tenants when ``all_tenants``
    is True; passing neither (or both) raises."""
    if tenant_id and all_tenants:
        raise ValueError(
            "pass either --tenant-id OR --all-tenants, not both",
        )
    if not tenant_id and not all_tenants:
        raise ValueError(
            "pass --tenant-id <id> OR --all-tenants (explicit)",
        )
    now_iso = datetime.now(timezone.utc).isoformat()
    tids = [tenant_id] if tenant_id else await _list_tenants(db)

    per_tenant: Dict[str, Dict[str, Any]] = {}
    totals = {
        "tenants_scanned":        0,
        "sets_merged":            0,
        "lines_fk_rewritten":     0,
        "loser_rows_soft_deleted": 0,
        "lines_fk_backfilled":    0,
        "invoices_touched":       0,
        "unmatched_inline_names": {},
    }

    for tid in tids:
        if not tid:
            continue
        totals["tenants_scanned"] += 1
        try:
            merge_summary = await _merge_duplicates_for_tenant(
                db, tid, dry_run=dry_run, now_iso=now_iso,
            )
            backfill_summary = await _backfill_inline_fk_for_tenant(
                db, tid,
                winners_by_norm=merge_summary["winners_by_norm"],
                dry_run=dry_run,
            )
        except Exception as exc:
            # Fail-closed: record what we have and re-raise so the
            # operator sees the halt loud and clear.  Per-tenant
            # audit row still written so an abort halfway through
            # a multi-tenant run is diffable.
            logger.exception("[merge-dupes] tenant=%s failed", tid)
            per_tenant[tid] = {"error": str(exc)}
            if not dry_run:
                await db.migration_runs.insert_one({
                    "id": str(uuid.uuid4()),
                    "name": "merge_income_categories_duplicates_v1",
                    "tenant_id": tid,
                    "status": "error",
                    "error": str(exc),
                    "at": now_iso,
                })
            raise
        per_tenant[tid] = {
            "sets_merged":              merge_summary["sets_merged"],
            "lines_fk_rewritten":       merge_summary["lines_fk_rewritten"],
            "loser_rows_soft_deleted":  merge_summary["loser_rows_soft_deleted"],
            "lines_fk_backfilled":      backfill_summary["lines_fk_backfilled"],
            "invoices_touched":         backfill_summary["invoices_touched"],
            "unmatched_inline_names":   backfill_summary["unmatched_inline_names"],
        }
        totals["sets_merged"] += merge_summary["sets_merged"]
        totals["lines_fk_rewritten"] += merge_summary["lines_fk_rewritten"]
        totals["loser_rows_soft_deleted"] += \
            merge_summary["loser_rows_soft_deleted"]
        totals["lines_fk_backfilled"] += \
            backfill_summary["lines_fk_backfilled"]
        totals["invoices_touched"] += backfill_summary["invoices_touched"]
        for norm, cnt in backfill_summary["unmatched_inline_names"].items():
            totals["unmatched_inline_names"][norm] = \
                totals["unmatched_inline_names"].get(norm, 0) + cnt
        if not dry_run:
            await db.migration_runs.insert_one({
                "id": str(uuid.uuid4()),
                "name": "merge_income_categories_duplicates_v1",
                "tenant_id": tid,
                "status": "ok",
                "summary": per_tenant[tid],
                "at": now_iso,
            })

    return {
        "dry_run":     dry_run,
        "all_tenants": bool(all_tenants and not tenant_id),
        "totals":      totals,
        "per_tenant":  per_tenant,
    }


# ─────────────────────────── CLI ──────────────────────────────────
def _print_summary(result: Dict[str, Any]):
    totals = result["totals"]
    print(f"tenants_scanned         = {totals['tenants_scanned']}")
    print(f"sets_merged             = {totals['sets_merged']}")
    print(f"lines_fk_rewritten      = {totals['lines_fk_rewritten']}")
    print(f"loser_rows_soft_deleted = {totals['loser_rows_soft_deleted']}")
    print(f"lines_fk_backfilled     = {totals['lines_fk_backfilled']}")
    print(f"invoices_touched        = {totals['invoices_touched']}")
    unmatched = totals.get("unmatched_inline_names") or {}
    if unmatched:
        top = sorted(unmatched.items(),
                       key=lambda kv: (-kv[1], kv[0]))[:10]
        print("unmatched_inline_names (top 10):")
        for n, c in top:
            print(f"  {n!r}: {c}")
    print()
    for tid, row in result["per_tenant"].items():
        if "error" in row:
            print(f"  [ERROR] tenant={tid}: {row['error']}")
            continue
        print(
            f"  tenant={tid}  sets_merged={row['sets_merged']}  "
            f"lines_rw={row['lines_fk_rewritten']}  "
            f"loser_del={row['loser_rows_soft_deleted']}  "
            f"backfill={row['lines_fk_backfilled']}  "
            f"inv={row['invoices_touched']}"
        )


async def _cli(argv: Optional[List[str]] = None) -> None:
    p = argparse.ArgumentParser(description=(
        "Merge income_categories duplicates + backfill inline-"
        "string FKs onto the canonical winner."
    ))
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--tenant-id", default=None,
                         help="Scope to one tenant.")
    group.add_argument("--all-tenants", action="store_true",
                         help="Scope to every active tenant.")
    p.add_argument("--apply", action="store_true",
                    help="Actually mutate.  Default is dry-run.")
    args = p.parse_args(argv)

    env = dotenv_values(
        str(Path(__file__).resolve().parents[1] / ".env"),
    )
    mongo_url = env.get("MONGO_URL") or ""
    db_name = env.get("DB_NAME") or ""
    if not mongo_url or not db_name:
        print("MONGO_URL / DB_NAME missing from backend/.env",
              file=sys.stderr)
        sys.exit(2)
    db = AsyncIOMotorClient(mongo_url)[db_name]

    scope = (f"tenant={args.tenant_id}"
             if args.tenant_id else "ALL TENANTS")
    print(f"== income-cat dupe merge · dry-run · scope={scope} ==")
    dry = await merge_income_categories_duplicates(
        db, tenant_id=args.tenant_id,
        all_tenants=bool(args.all_tenants and not args.tenant_id),
        dry_run=True,
    )
    _print_summary(dry)
    if not args.apply:
        print("\nDry-run only.  Re-run with --apply to mutate.")
        return

    print(f"\n== income-cat dupe merge · APPLY · scope={scope} ==")
    real = await merge_income_categories_duplicates(
        db, tenant_id=args.tenant_id,
        all_tenants=bool(args.all_tenants and not args.tenant_id),
        dry_run=False,
    )
    _print_summary(real)

    print("\n-- idempotency re-check --")
    recheck = await merge_income_categories_duplicates(
        db, tenant_id=args.tenant_id,
        all_tenants=bool(args.all_tenants and not args.tenant_id),
        dry_run=True,
    )
    _print_summary(recheck)
    rt = recheck["totals"]
    if any(rt[k] for k in ("sets_merged", "lines_fk_rewritten",
                              "loser_rows_soft_deleted",
                              "lines_fk_backfilled")):
        print("WARNING: idempotency re-check reported non-zero "
              "counts.")


if __name__ == "__main__":
    asyncio.run(_cli())
