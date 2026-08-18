"""Feb-2026 · Phase 2 · Idempotent supplier_prices backfill.

Wraps ``scripts/hydrate_homeworks_pricebook_prices`` and adds:

* ``--dry-run`` (default) / ``--commit`` toggle per user spec
* multi-tenant fan-out (default: every tenant; ``--tenant-id`` narrows)
* per-item skip reason logging (``unmapped_supplier`` /
  ``no_source_blob`` / ``already_populated`` / ``all_costs_zero``)
* final aggregate report + per-tenant breakdown

Only touches items that meet ALL of:

1. ``supplier_prices`` is empty (``[]`` / missing / None).
2. ``homeworks_costs`` blob has at least one non-zero cost field.
3. A ``pricebook_suppliers`` row with ``slug='homeworks'`` exists for
   the tenant — auto-upserted by the reused hydration entry point,
   so this constraint is always satisfied after step 1 of the run.

Idempotent: rerunning on a hydrated store yields
``hydrated=0, skipped_already_populated=<N>`` and zero DB writes.

Never deletes ``homeworks_costs`` — raw source stays in place per
constraint.

Usage::

    # audit / preview (safe, default)
    python3 -m scripts.backfill_pricebook_supplier_prices

    # commit for every tenant sequentially
    python3 -m scripts.backfill_pricebook_supplier_prices --commit

    # single tenant
    python3 -m scripts.backfill_pricebook_supplier_prices \\
        --commit --tenant-id 3814833a-...
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone

from dotenv import load_dotenv
load_dotenv("/app/backend/.env")

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

from scripts.hydrate_homeworks_pricebook_prices import (  # noqa: E402
    HOMEWORKS_SLUG, _derive_prices, _apply_supplier_price,
    upsert_homeworks_supplier, Counters as _HydrateCounters,
)
from scripts.audit_pricebook_missing_supplier_prices import (  # noqa: E402
    _has_any_signal,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class TenantReport:
    tenant_id: str
    scanned: int = 0
    hydrated: int = 0
    skipped_no_source: int = 0
    skipped_unmapped_supplier: int = 0
    skipped_already_populated: int = 0
    skipped_all_costs_zero: int = 0
    supplier_upserted: bool = False
    skipped_items: list[dict] = field(default_factory=list)


async def _run_tenant(db, tenant_id: str, *, commit: bool) -> TenantReport:
    report = TenantReport(tenant_id=tenant_id)

    # Step 1 — ensure the homeworks supplier row exists so item writes
    # aren't rejected by the multi-supplier validator. Reuses the same
    # helper the real-time importer uses.
    _hydrate_counters = _HydrateCounters()
    try:
        await upsert_homeworks_supplier(
            db, tenant_id,
            dry_run=(not commit),
            counters=_hydrate_counters,
        )
        report.supplier_upserted = (
            _hydrate_counters.supplier_created or _hydrate_counters.supplier_updated
        )
    except RuntimeError:
        # Tenant lacks any income_categories — every item on this
        # tenant will be surfaced under ``skipped_unmapped_supplier``.
        pass

    supplier_row = await db.pricebook_suppliers.find_one(
        {"tenant_id": tenant_id, "slug": HOMEWORKS_SLUG},
        {"_id": 0, "id": 1},
    )
    supplier_ready = supplier_row is not None

    async for item in db.items.find({"tenant_id": tenant_id}, {"_id": 0}):
        report.scanned += 1
        item_id = item.get("id")
        existing = item.get("supplier_prices") or []
        if existing:
            report.skipped_already_populated += 1
            # No entry in ``skipped_items`` — this is the noisy bucket.
            continue
        hw = item.get("homeworks_costs")
        if not hw:
            report.skipped_no_source += 1
            report.skipped_items.append({
                "item_id": item_id, "name": item.get("name"),
                "reason": "no_source_blob",
            })
            continue
        if not _has_any_signal(hw):
            report.skipped_all_costs_zero += 1
            report.skipped_items.append({
                "item_id": item_id, "name": item.get("name"),
                "reason": "all_costs_zero",
            })
            continue
        if not supplier_ready:
            report.skipped_unmapped_supplier += 1
            report.skipped_items.append({
                "item_id": item_id, "name": item.get("name"),
                "reason": f"unmapped_supplier:{HOMEWORKS_SLUG}",
            })
            continue

        cost_cents, retail_cents = _derive_prices(item)
        entry = {
            "supplier_slug": HOMEWORKS_SLUG,
            "cost_cents": cost_cents,
            "retail_cents": retail_cents,
            "currency": "USD",
        }
        next_prices, added, updated = _apply_supplier_price(existing, entry)
        if not (added or updated):
            # Defensive — shouldn't happen because we filtered
            # ``existing`` empty above. Keeps idempotency contract clean.
            report.skipped_already_populated += 1
            continue

        if commit:
            await db.items.update_one(
                {"tenant_id": tenant_id, "id": item_id},
                {"$set": {"supplier_prices": next_prices,
                            "updated_at": _now_iso()}},
            )
        report.hydrated += 1

    return report


def _print_final(reports: list[TenantReport], commit: bool) -> None:
    totals = defaultdict(int)
    for r in reports:
        totals["scanned"] += r.scanned
        totals["hydrated"] += r.hydrated
        totals["skipped_no_source"] += r.skipped_no_source
        totals["skipped_unmapped_supplier"] += r.skipped_unmapped_supplier
        totals["skipped_already_populated"] += r.skipped_already_populated
        totals["skipped_all_costs_zero"] += r.skipped_all_costs_zero
    payload = {
        "mode": "commit" if commit else "dry_run",
        "totals": dict(totals),
        "tenants": [asdict(r) for r in reports],
    }
    print(json.dumps(payload, indent=2, default=str))


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenant-id", default=None,
                     help="Single tenant. Default: every tenant sequentially.")
    ap.add_argument("--commit", action="store_true",
                     help="Actually write the hydrated supplier_prices. "
                          "Without this flag the script only previews.")
    ap.add_argument("--dry-run", action="store_true",
                     help="Preview only (default behavior; kept for "
                          "backwards compatibility with existing scripts).")
    args = ap.parse_args()
    commit = args.commit and not args.dry_run
    from config import db

    if args.tenant_id:
        tenant_ids = [args.tenant_id]
    else:
        tenant_ids = [
            t["id"] async for t in db.tenants.find({}, {"_id": 0, "id": 1})
            if t.get("id")
        ]

    reports: list[TenantReport] = []
    for tid in tenant_ids:
        r = await _run_tenant(db, tid, commit=commit)
        # Skip zero-activity tenants from the report to keep it readable.
        if r.scanned:
            reports.append(r)

    _print_final(reports, commit)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
