#!/usr/bin/env python3
"""Task 4 · Feb-2026 — Backfill supplier_prices for Homeworks-imported
pricebook items.

The Feb-2026 pricebook importer intentionally landed
``supplier_prices: []`` on every item because the multi-supplier
validator requires a ``pricebook_suppliers`` row + matching
``income_category_id``, and both are tenant-configured. Now that
users are ready to surface cost/retail on the pricebook UI, this
script:

  1. Idempotently upserts a ``pricebook_suppliers`` row keyed by
     ``(tenant_id, slug='homeworks')``.
  2. Walks every ``db.items`` row on the tenant with
     ``imported_from == 'homeworks'`` and hydrates the
     ``homeworks`` slug entry in ``supplier_prices`` with cost + retail
     derived from the raw ``homeworks_costs`` blob (kept intact for
     audit).

Design constraints (from user brief):
  * Only touch the ``homeworks`` slug entry — non-Homeworks entries
    are left alone so admins' manual supplier prices survive.
  * Uses the existing default income category (``Pool``, matching
    every other seed supplier on aquaterra) rather than creating a
    new taxonomy row.
  * Idempotent: re-running with unchanged ``homeworks_costs`` yields
    zero DB writes.
  * Skips items whose cost + retail are both zero (produces no
    signal for the multi-supplier planner).

Usage::

    python3 -m scripts.hydrate_homeworks_pricebook_prices \\
        --tenant-id <uuid> --dry-run
    python3 -m scripts.hydrate_homeworks_pricebook_prices \\
        --tenant-id <uuid> --confirm
"""
from __future__ import annotations

import argparse
import asyncio
import json
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime, timezone

from dotenv import load_dotenv
load_dotenv("/app/backend/.env")


HOMEWORKS_SLUG = "homeworks"
HOMEWORKS_DISPLAY_NAME = "Homeworks (imported)"
DEFAULT_INCOME_CATEGORY_NAME = "Pool"


@dataclass
class Counters:
    items_scanned: int = 0
    items_hydrated: int = 0
    items_skipped_missing_costs: int = 0
    items_unchanged: int = 0
    prices_added: int = 0
    prices_updated: int = 0
    supplier_created: bool = False
    supplier_updated: bool = False


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _cents(v) -> int:
    """Convert a decimal-ish value to integer cents. Zero-safe."""
    try:
        f = float(v or 0)
    except (TypeError, ValueError):
        return 0
    return int(round(f * 100))


async def _resolve_income_category(db, tenant_id: str) -> str:
    """Prefer ``Pool`` (matches every existing seed supplier on
    aquaterra); fall back to the tenant's first income category if
    Pool is missing. Never creates one — the user brief was explicit
    about not touching taxonomy."""
    row = await db.income_categories.find_one(
        {"tenant_id": tenant_id, "name": DEFAULT_INCOME_CATEGORY_NAME},
        {"_id": 0, "id": 1},
    )
    if row:
        return row["id"]
    row = await db.income_categories.find_one(
        {"tenant_id": tenant_id}, {"_id": 0, "id": 1},
    )
    if not row:
        raise RuntimeError(
            "tenant_has_no_income_categories: cannot upsert homeworks supplier",
        )
    return row["id"]


async def upsert_homeworks_supplier(db, tenant_id: str, *,
                                        dry_run: bool,
                                        counters: Counters) -> str:
    """Idempotent upsert. Returns the supplier's income_category_id
    (needed by callers that want to align items' income_category_id
    with the supplier's)."""
    income_cat_id = await _resolve_income_category(db, tenant_id)
    existing = await db.pricebook_suppliers.find_one(
        {"tenant_id": tenant_id, "slug": HOMEWORKS_SLUG},
        {"_id": 0},
    )
    if existing:
        # Compare mutable fields — only update if we'd change something.
        changed = (
            existing.get("display_name") != HOMEWORKS_DISPLAY_NAME
            or existing.get("income_category_id") != income_cat_id
            or existing.get("is_active") is not True
        )
        if changed and not dry_run:
            await db.pricebook_suppliers.update_one(
                {"tenant_id": tenant_id, "slug": HOMEWORKS_SLUG},
                {"$set": {
                    "display_name": HOMEWORKS_DISPLAY_NAME,
                    "income_category_id": income_cat_id,
                    "is_active": True,
                    "updated_at": _now_iso(),
                }},
            )
        counters.supplier_updated = bool(changed)
        return income_cat_id

    if not dry_run:
        await db.pricebook_suppliers.insert_one({
            "id": uuid.uuid4().hex,
            "tenant_id": tenant_id,
            "slug": HOMEWORKS_SLUG,
            "display_name": HOMEWORKS_DISPLAY_NAME,
            "income_category_id": income_cat_id,
            "is_active": True,
            "is_seed": False,
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
        })
    counters.supplier_created = True
    return income_cat_id


def _derive_prices(item: dict) -> tuple[int, int]:
    """Return (cost_cents, retail_cents) from the item.

    * retail_cents = item.unit_price (Homeworks ``price``)
    * cost_cents   = homeworks_costs.wholesaleCost (fallback:
                     materialCost, then item.wholesale_price)
    """
    retail_cents = _cents(item.get("unit_price"))
    hw = item.get("homeworks_costs") or {}
    cost = hw.get("wholesaleCost") or 0
    if not cost:
        cost = hw.get("materialCost") or 0
    if not cost:
        cost = item.get("wholesale_price") or 0
    return _cents(cost), retail_cents


def _apply_supplier_price(existing: list, new_entry: dict) -> tuple[list, bool, bool]:
    """Return (next_list, was_added, was_updated). Preserves any
    non-``homeworks`` entries verbatim."""
    others = [e for e in (existing or [])
                if (e or {}).get("supplier_slug") != HOMEWORKS_SLUG]
    prior = next(((e for e in (existing or [])
                     if (e or {}).get("supplier_slug") == HOMEWORKS_SLUG)), None)
    if prior is None:
        return others + [new_entry], True, False
    same = (
        int(prior.get("cost_cents") or 0) == int(new_entry["cost_cents"])
        and int(prior.get("retail_cents") or 0) == int(new_entry["retail_cents"])
        and (prior.get("currency") or "USD") == new_entry["currency"]
    )
    if same:
        return list(existing), False, False
    return others + [new_entry], False, True


async def hydrate_items(db, tenant_id: str, *,
                          dry_run: bool,
                          counters: Counters,
                          sample_snapshots: list) -> None:
    q = {"tenant_id": tenant_id, "imported_from": HOMEWORKS_SLUG}
    async for item in db.items.find(q, {"_id": 0}):
        counters.items_scanned += 1
        cost_cents, retail_cents = _derive_prices(item)
        if cost_cents == 0 and retail_cents == 0:
            counters.items_skipped_missing_costs += 1
            continue
        entry = {
            "supplier_slug": HOMEWORKS_SLUG,
            "cost_cents": cost_cents,
            "retail_cents": retail_cents,
            "currency": "USD",
        }
        next_prices, added, updated = _apply_supplier_price(
            item.get("supplier_prices") or [], entry,
        )
        if not (added or updated):
            counters.items_unchanged += 1
            continue

        # Capture up to 3 before/after samples for the report.
        if len(sample_snapshots) < 3:
            sample_snapshots.append({
                "item_id": item.get("id"),
                "name": item.get("name"),
                "before_supplier_prices": item.get("supplier_prices") or [],
                "after_supplier_prices": next_prices,
                "homeworks_costs_preserved": item.get("homeworks_costs"),
            })

        if not dry_run:
            await db.items.update_one(
                {"tenant_id": tenant_id, "id": item["id"]},
                {"$set": {"supplier_prices": next_prices,
                            "updated_at": _now_iso()}},
            )
        counters.items_hydrated += 1
        if added:
            counters.prices_added += 1
        else:
            counters.prices_updated += 1


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenant-id", required=True)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--confirm", action="store_true",
                     help="Perform the actual writes (mutually exclusive with --dry-run).")
    args = ap.parse_args()
    if not (args.dry_run or args.confirm):
        print("Refusing to run — pass either --dry-run or --confirm.")
        return 2
    if args.dry_run and args.confirm:
        print("--dry-run and --confirm are mutually exclusive.")
        return 2

    from config import db
    counters = Counters()
    sample_snapshots: list = []
    await upsert_homeworks_supplier(
        db, args.tenant_id, dry_run=args.dry_run, counters=counters,
    )
    await hydrate_items(
        db, args.tenant_id,
        dry_run=args.dry_run, counters=counters,
        sample_snapshots=sample_snapshots,
    )
    print(json.dumps({
        "mode": "dry_run" if args.dry_run else "committed",
        "counters": asdict(counters),
        "samples": sample_snapshots,
    }, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
