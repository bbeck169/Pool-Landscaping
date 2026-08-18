"""Feb-2026 · Phase 2 · Read-only audit of empty ``supplier_prices``.

Categorises every pricebook item into:

* **hydratable** — ``supplier_prices`` is empty AND ``homeworks_costs``
  has at least one non-zero cost field. Backfill can populate.
* **unmapped_supplier** — hydratable in shape, but the tenant lacks a
  ``pricebook_suppliers`` row with ``slug='homeworks'``. Backfill will
  auto-upsert one (existing hydration code does this), so this is a
  transient bucket — surfaced separately for visibility only.
* **unresolved** — ``supplier_prices`` is empty AND either no
  ``homeworks_costs`` blob OR every cost field is zero. Backfill will
  skip these; they need supplier-team follow-up.
* **already_populated** — ``supplier_prices`` is non-empty. Backfill
  leaves untouched.

Scoped per tenant to satisfy the multi-tenant safety constraint.

Saves the summary to ``/app/memory/pricebook_backfill_audit.md``.

Usage::

    python3 -m scripts.audit_pricebook_missing_supplier_prices \\
        [--tenant-id <uuid>]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
load_dotenv("/app/backend/.env")

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

from scripts.hydrate_homeworks_pricebook_prices import (  # noqa: E402
    HOMEWORKS_SLUG, _derive_prices,
)


AUDIT_MD_PATH = Path("/app/memory/pricebook_backfill_audit.md")


def _has_any_signal(homeworks_costs: dict | None) -> bool:
    """A hydratable ``homeworks_costs`` blob has at least one non-zero
    cost field. Mirrors the check inside ``_derive_prices`` — an
    item where cost_cents AND retail_cents both resolve to 0 produces
    no useful supplier_price entry."""
    if not homeworks_costs:
        return False
    for k in ("wholesaleCost", "materialCost", "equipmentCost",
                "subcontractCost"):
        try:
            if float(homeworks_costs.get(k) or 0) > 0:
                return True
        except (TypeError, ValueError):
            continue
    return False


async def _audit_tenant(db, tenant_id: str) -> dict:
    total = await db.items.count_documents({"tenant_id": tenant_id})
    empty_prices_q = {
        "tenant_id": tenant_id,
        "$or": [
            {"supplier_prices": {"$exists": False}},
            {"supplier_prices": None},
            {"supplier_prices": []},
        ],
    }
    empty_prices = await db.items.count_documents(empty_prices_q)

    hydratable = 0
    unresolved: list[dict] = []
    # For "unmapped_supplier" reporting — count items whose tenant
    # currently has no pricebook_suppliers row with slug=homeworks.
    supplier_row = await db.pricebook_suppliers.find_one(
        {"tenant_id": tenant_id, "slug": HOMEWORKS_SLUG},
        {"_id": 0, "id": 1},
    )
    tenant_has_homeworks_supplier = supplier_row is not None
    unmapped_supplier_ids: list[str] = []

    unresolved_reason_counts: dict[str, int] = defaultdict(int)

    async for item in db.items.find(empty_prices_q, {"_id": 0}):
        hw = item.get("homeworks_costs")
        if _has_any_signal(hw):
            hydratable += 1
            if not tenant_has_homeworks_supplier:
                unmapped_supplier_ids.append(item.get("id"))
            continue
        # Track WHY the row can't be hydrated so the supplier team has
        # a concrete list to work off.
        if hw is None or hw == {}:
            reason = "no_homeworks_costs_blob"
        else:
            reason = "all_cost_fields_zero"
        unresolved_reason_counts[reason] += 1
        unresolved.append({"item_id": item.get("id"),
                             "name": item.get("name"),
                             "reason": reason})

    return {
        "tenant_id": tenant_id,
        "total_items": total,
        "empty_supplier_prices": empty_prices,
        "hydratable": hydratable,
        "unmapped_supplier": len(unmapped_supplier_ids),
        "unresolved_total": len(unresolved),
        "unresolved_by_reason": dict(unresolved_reason_counts),
        "tenant_has_homeworks_supplier_row": tenant_has_homeworks_supplier,
        "unresolved_items": unresolved,
        "unmapped_supplier_item_ids": unmapped_supplier_ids,
    }


def _render_markdown(reports: list[dict]) -> str:
    ts = datetime.now(timezone.utc).isoformat()
    lines: list[str] = [
        "# Pricebook `supplier_prices` backfill audit",
        "",
        f"*Generated: {ts}*",
        "",
        "## Summary across all tenants",
        "",
    ]
    totals = defaultdict(int)
    for r in reports:
        totals["total_items"] += r["total_items"]
        totals["empty_supplier_prices"] += r["empty_supplier_prices"]
        totals["hydratable"] += r["hydratable"]
        totals["unresolved_total"] += r["unresolved_total"]
    lines += [
        f"* Tenants scanned: **{len(reports)}**",
        f"* Total pricebook items: **{totals['total_items']}**",
        f"* Empty `supplier_prices`: **{totals['empty_supplier_prices']}**",
        f"  * Hydratable (has non-zero `homeworks_costs`): **{totals['hydratable']}**",
        f"  * Unresolved (no source data or all zeros): **{totals['unresolved_total']}**",
        "",
        "## Per-tenant breakdown",
        "",
        "| tenant_id | total | empty | hydratable | unresolved | unmapped_supplier | has_homeworks_row |",
        "|-----------|------:|------:|-----------:|-----------:|------------------:|:-----------------:|",
    ]
    for r in reports:
        lines.append(
            f"| `{r['tenant_id'][:12]}…` "
            f"| {r['total_items']} "
            f"| {r['empty_supplier_prices']} "
            f"| {r['hydratable']} "
            f"| {r['unresolved_total']} "
            f"| {r['unmapped_supplier']} "
            f"| {'yes' if r['tenant_has_homeworks_supplier_row'] else 'no'} |"
        )
    lines += ["", "## Unresolved items (need supplier-team follow-up)", ""]
    for r in reports:
        if not r["unresolved_items"]:
            continue
        lines.append(f"### Tenant `{r['tenant_id']}` — {len(r['unresolved_items'])} row(s)")
        lines.append("")
        lines.append("| item_id | name | reason |")
        lines.append("|---------|------|--------|")
        for u in r["unresolved_items"][:200]:  # cap so the file stays readable
            name = (u.get("name") or "").replace("|", "/")
            lines.append(f"| `{u['item_id']}` | {name} | `{u['reason']}` |")
        if len(r["unresolved_items"]) > 200:
            lines.append(f"| … | +{len(r['unresolved_items']) - 200} more | … |")
        lines.append("")
    return "\n".join(lines)


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenant-id", default=None,
                     help="Scope the audit to a single tenant. Default: every tenant.")
    ap.add_argument("--json", action="store_true",
                     help="Emit JSON instead of the markdown summary.")
    args = ap.parse_args()

    from config import db
    if args.tenant_id:
        tenant_ids = [args.tenant_id]
    else:
        tenant_ids = [
            t["id"] async for t in db.tenants.find({}, {"_id": 0, "id": 1})
            if t.get("id")
        ]

    reports = [await _audit_tenant(db, tid) for tid in tenant_ids]
    # Only render tenants that have at least one item — cuts noise
    # from empty seed tenants (573 tenants exist but most have zero
    # pricebook rows).
    nonempty_reports = [r for r in reports if r["total_items"] > 0]

    md = _render_markdown(nonempty_reports)
    AUDIT_MD_PATH.parent.mkdir(parents=True, exist_ok=True)
    AUDIT_MD_PATH.write_text(md)

    if args.json:
        print(json.dumps({"reports": nonempty_reports}, indent=2))
    else:
        print(md)
    print(f"\n[audit_pricebook_missing_supplier_prices] wrote {AUDIT_MD_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
