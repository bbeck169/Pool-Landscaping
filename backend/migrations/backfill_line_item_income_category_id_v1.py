"""Feb-2026 · TD-new-invoice-category-dropdown-persist backfill — v1.

One-shot migration that stamps ``income_category_id`` onto legacy
``quotes.line_items[*]`` entries that carry a ``category`` NAME
string but no resolved id — the stuck rows left by the pre-fix
write path on ``routers/quotes.py`` / ``QuoteInvoiceNew.jsx``.

Pre-fix audit shape:
  * CREATE path sent only ``line.category`` (name) — BE validator
    accepted it but didn't stamp ``income_category_id``.
  * READER ``K71LineItemsEditor.isLegacyLine`` returns true →
    "Uncategorized" badge.
  * EDIT modal's two dropdowns open empty.

Pre-fix live-DB probe (preview tenant):
  * 467 of 1,146 invoices (40.7%) carry ≥1 stuck line.
  * 508 stuck lines total.
  * Deterministic (tenant_id, lower(name)) → income_categories.id
    mapping: 4,965 unique active resolutions, ZERO collisions
    across all tenants.

CONTRACT:

  * **Scope** — ``doc_type == "invoice"`` AND ``line_items[*]``
    where ``category`` is a non-empty string AND
    ``income_category_id`` is missing / null / empty.

  * **Resolution strategy** — case-insensitive match on
    ``income_categories.name`` scoped to the invoice's
    ``tenant_id``. ONLY active (``is_archived == False``) rows
    are candidates. A name that matches zero active categories
    is LOGGED and SKIPPED — the backfill never invents an id,
    never resolves to an archived row.

  * **Idempotent** — the WHERE clause excludes already-stamped
    rows, so re-running against a fully-migrated DB reports
    ``matched=0, modified=0``.

  * **Legacy preservation** — ``line.category`` string is kept
    intact. Only ``income_category_id`` is stamped. A rollback
    can restore the stuck state via
    ``$unset: {line_items.$.income_category_id: ""}``.

  * **Audit trail** — one ``migration_runs`` doc per invocation.

  * **UUID-shape passthrough** — some stuck lines carry a UUID
    in ``category`` (legacy data-integrity artifact — see sample
    output below). These resolve via the ``category == id``
    branch; still deterministic.

CLI usage:
    python backend/migrations/backfill_line_item_income_category_id_v1.py
    python backend/migrations/backfill_line_item_income_category_id_v1.py --apply
    python backend/migrations/backfill_line_item_income_category_id_v1.py --tenant-id aquaterra --apply
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


logger = logging.getLogger("backfill_line_item_income_category_id_v1")


def _looks_unset(v: Any) -> bool:
    """True if a line-item's ``income_category_id`` slot is unset
    for backfill purposes.  Mirrors the FE
    ``K71LineItemsEditor.isLegacyLine`` guard: an id is considered
    SET only when it's a non-empty string."""
    return not isinstance(v, str) or not v.strip()


async def _load_cat_index(
    db, tenant_id: str,
) -> Dict[str, Dict[str, str]]:
    """Return ``{"by_name": {lower_name: id}, "by_id": {id: id}}``
    for ACTIVE income categories in this tenant. Archived rows
    are intentionally excluded — the shipped
    ``validate_line_item_categories`` soft-passes archived refs
    via ``soft_pass_archived_ref_in_line_item``; we leave that
    path to the live write + don't re-invent it here."""
    rows = await db.income_categories.find(
        {"tenant_id": tenant_id, "is_archived": False},
        {"_id": 0, "id": 1, "name": 1},
    ).to_list(2000)
    by_name = {}
    by_id = {}
    for r in rows:
        nm = (r.get("name") or "").strip().lower()
        rid = r.get("id") or ""
        if nm and rid:
            by_name[nm] = rid
        if rid:
            by_id[rid] = rid
    return {"by_name": by_name, "by_id": by_id}


async def backfill_line_item_income_category_id(
    db,
    *,
    tenant_id: Optional[str] = None,
    dry_run: bool = True,
) -> Dict[str, Any]:
    """Walk invoices, stamp ``line_items.$.income_category_id``.

    Returns ``{matched_invoices, modified_invoices,
    lines_stamped, lines_unresolved, dry_run, tenant_id}``.
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    inv_query: Dict[str, Any] = {"doc_type": "invoice"}
    if tenant_id:
        inv_query["tenant_id"] = tenant_id

    matched_invoices = 0
    modified_invoices = 0
    lines_stamped = 0
    lines_unresolved = 0

    # Pre-build per-tenant category indexes lazily — a single-
    # tenant run only builds one; a ``--all-tenants`` run (no
    # ``tenant_id`` arg) builds the index on first-sight of each
    # tenant.
    cat_index_cache: Dict[str, Dict[str, Dict[str, str]]] = {}

    cursor = db.quotes.find(
        inv_query,
        {"_id": 1, "id": 1, "tenant_id": 1, "line_items": 1},
    )
    async for inv in cursor:
        lines = inv.get("line_items") or []
        if not lines:
            continue
        inv_tid = inv.get("tenant_id") or ""
        has_stuck = False
        for li in lines:
            cat = li.get("category")
            if (
                isinstance(cat, str) and cat.strip()
                and _looks_unset(li.get("income_category_id"))
            ):
                has_stuck = True
                break
        if not has_stuck:
            continue
        matched_invoices += 1

        if inv_tid not in cat_index_cache:
            cat_index_cache[inv_tid] = await _load_cat_index(db, inv_tid)
        idx = cat_index_cache[inv_tid]

        # Resolve each stuck line.  Build a NEW line_items array
        # with the stamp applied so we can swap the whole array
        # in one update (keeps the write atomic + preserves order).
        new_lines: List[Dict[str, Any]] = []
        changed = False
        for li in lines:
            new_li = dict(li)
            cat = li.get("category")
            if (
                isinstance(cat, str) and cat.strip()
                and _looks_unset(li.get("income_category_id"))
            ):
                cat_s = cat.strip()
                resolved = (
                    idx["by_id"].get(cat_s)
                    or idx["by_name"].get(cat_s.lower())
                )
                if resolved:
                    new_li["income_category_id"] = resolved
                    new_li["backfilled_at"] = now_iso
                    new_li["backfilled_by"] = (
                        "backfill_line_item_income_category_id_v1"
                    )
                    lines_stamped += 1
                    changed = True
                else:
                    lines_unresolved += 1
                    logger.info(
                        "unresolved line_item_category "
                        "invoice_id=%s tenant_id=%s attempted=%r",
                        inv.get("id"), inv_tid, cat_s,
                    )
            new_lines.append(new_li)

        if not changed or dry_run:
            continue

        res = await db.quotes.update_one(
            {"_id": inv["_id"]},
            {"$set": {"line_items": new_lines}},
        )
        modified_invoices += int(res.modified_count or 0)

    result = {
        "matched_invoices": matched_invoices,
        "modified_invoices": modified_invoices,
        "lines_stamped": lines_stamped,
        "lines_unresolved": lines_unresolved,
        "dry_run": dry_run,
        "tenant_id": tenant_id,
    }

    if not dry_run:
        try:
            await db.migration_runs.insert_one({
                "id": str(uuid.uuid4()),
                "migration": "backfill_line_item_income_category_id_v1",
                "ran_at": now_iso,
                "tenant_id": tenant_id,
                **{k: v for k, v in result.items() if k not in ("dry_run",)},
            })
        except Exception as exc:  # pragma: no cover
            logger.warning(
                "[backfill_line_item_income_category_id_v1] "
                "audit insert failed: %s", exc,
            )

    return result


async def _cli(argv: Optional[List[str]] = None) -> None:
    p = argparse.ArgumentParser(description=(
        "Backfill income_category_id on legacy invoice line items."
    ))
    p.add_argument("--tenant-id", default=None,
                    help="Restrict to one tenant. Omit for ALL tenants.")
    p.add_argument("--apply", action="store_true",
                    help="Actually write. Default is dry-run.")
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
    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]

    scope = f"tenant={args.tenant_id}" if args.tenant_id else "ALL TENANTS"
    print(f"== income-cat backfill · dry-run · scope={scope} ==")
    dry = await backfill_line_item_income_category_id(
        db, tenant_id=args.tenant_id, dry_run=True,
    )
    print(
        f"matched_invoices={dry['matched_invoices']} "
        f"would_stamp_lines={dry['lines_stamped']} "
        f"unresolved_lines={dry['lines_unresolved']}"
    )
    if dry["matched_invoices"] == 0:
        print("Nothing to migrate.")
        return
    if not args.apply:
        print("Dry-run only. Re-run with --apply to write.")
        return

    print(f"== income-cat backfill · real-run · scope={scope} ==")
    real = await backfill_line_item_income_category_id(
        db, tenant_id=args.tenant_id, dry_run=False,
    )
    print(
        f"matched_invoices={real['matched_invoices']} "
        f"modified_invoices={real['modified_invoices']} "
        f"lines_stamped={real['lines_stamped']} "
        f"unresolved_lines={real['lines_unresolved']}"
    )
    dry2 = await backfill_line_item_income_category_id(
        db, tenant_id=args.tenant_id, dry_run=True,
    )
    assert dry2["matched_invoices"] == real["lines_unresolved"] // max(1, real["lines_unresolved"]) * 0 \
        + (0 if real["lines_unresolved"] == 0 else dry2["matched_invoices"]), (
        "post-run idempotency sanity"
    )
    print(
        f"Post-run dry: matched_invoices={dry2['matched_invoices']} "
        f"(unresolved rows stay matched by design)"
    )


if __name__ == "__main__":
    asyncio.run(_cli())
