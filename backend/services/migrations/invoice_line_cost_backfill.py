"""Feb 2026 · Invoice/Quote line cost-snapshot backfill.

One-time cleanup for existing ``db.quotes`` docs (invoices +
estimates unified) whose ``line_items`` were written before the
pricebook `_stamp_line_snapshots` gained tenant-scoped lookups and
before the 0-vs-None cost re-hydration rule.

Sentinel: ``feb2026_invoice_line_cost_backfill_v1``. Idempotent.

Rule (matches the live ``_stamp_line_snapshots`` contract):
  * ``retail_price_snapshot`` — write once from ``unit_price``. If
    missing, hydrate; never overwrite.
  * ``wholesale_price_snapshot`` — if None OR 0 on the line AND the
    linked pricebook item has a non-zero ``wholesale_price``,
    hydrate. Never overwrite non-zero snapshots.
  * ``labor_cost_snapshot`` — same as wholesale but from the
    pricebook's ``labor_cost_default``.
  * Lines missing ``item_id`` are matched by name against pricebook
    entries in the same tenant (exact, case-insensitive). When a
    match is found, ``item_id`` is backfilled + snapshots follow.

Only mutates docs that actually change — safe to re-run.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List

from config import db


logger = logging.getLogger("invoice_line_cost_backfill")


_SENTINEL_ID = "feb2026_invoice_line_cost_backfill_v1"


def _to_float(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


async def _load_tenant_pricebook_by_name(tenant_id: str) -> Dict[str, Dict[str, Any]]:
    """Case-insensitive name-lookup for a tenant's pricebook."""
    out: Dict[str, Dict[str, Any]] = {}
    cur = db.items.find(
        {"tenant_id": tenant_id},
        {"_id": 0, "id": 1, "name": 1, "wholesale_price": 1,
          "labor_cost_default": 1, "unit_price": 1},
    )
    async for row in cur:
        nm = (row.get("name") or "").strip().lower()
        if nm and nm not in out:
            out[nm] = row
    return out


async def _load_tenant_pricebook_by_id(tenant_id: str,
                                          ids: List[str]) -> Dict[str, Dict[str, Any]]:
    if not ids:
        return {}
    rows = await db.items.find(
        {"tenant_id": tenant_id, "id": {"$in": list(ids)}},
        {"_id": 0, "id": 1, "name": 1, "wholesale_price": 1,
          "labor_cost_default": 1, "unit_price": 1},
    ).to_list(len(ids) + 5)
    return {r["id"]: r for r in rows}


async def _backfill_tenant(tenant_id: str) -> Dict[str, int]:
    stats = {"docs_scanned": 0, "docs_updated": 0,
             "lines_hydrated_ws": 0, "lines_hydrated_lc": 0,
             "lines_hydrated_retail": 0, "lines_linked_by_name": 0}
    by_name = await _load_tenant_pricebook_by_name(tenant_id)
    cur = db.quotes.find(
        {"tenant_id": tenant_id},
        {"_id": 0, "id": 1, "line_items": 1},
    )
    async for doc in cur:
        stats["docs_scanned"] += 1
        items = doc.get("line_items") or []
        if not items:
            continue
        ids_needed = [li.get("item_id") for li in items if li.get("item_id")]
        by_id = await _load_tenant_pricebook_by_id(tenant_id, list(set(ids_needed)))
        changed = False
        for li in items:
            master = by_id.get(li.get("item_id") or "") or {}
            if not master:
                nm = (li.get("description") or li.get("name") or "").strip().lower()
                master = by_name.get(nm) or {}
                if master and master.get("id"):
                    li["item_id"] = master["id"]
                    changed = True
                    stats["lines_linked_by_name"] += 1

            # retail — write once from unit_price.
            if li.get("retail_price_snapshot") is None:
                li["retail_price_snapshot"] = _to_float(li.get("unit_price"))
                changed = True
                stats["lines_hydrated_retail"] += 1

            # wholesale — hydrate when 0/None AND pricebook has value.
            ws_cur = li.get("wholesale_price_snapshot")
            ws_zero_or_null = (ws_cur is None or _to_float(ws_cur) == 0.0)
            if ws_zero_or_null:
                pb_ws = _to_float(master.get("wholesale_price"))
                if pb_ws > 0 or ws_cur is None:
                    li["wholesale_price_snapshot"] = pb_ws
                    changed = True
                    if pb_ws > 0:
                        stats["lines_hydrated_ws"] += 1

            # labor — hydrate when 0/None AND pricebook has value.
            lc_cur = li.get("labor_cost_snapshot")
            lc_zero_or_null = (lc_cur is None or _to_float(lc_cur) == 0.0)
            if lc_zero_or_null:
                pb_lc = _to_float(master.get("labor_cost_default"))
                if pb_lc > 0 or lc_cur is None:
                    li["labor_cost_snapshot"] = pb_lc
                    changed = True
                    if pb_lc > 0:
                        stats["lines_hydrated_lc"] += 1

        if changed:
            await db.quotes.update_one(
                {"id": doc["id"], "tenant_id": tenant_id},
                {"$set": {"line_items": items}},
            )
            stats["docs_updated"] += 1
    return stats


async def run_invoice_line_cost_backfill(*, force: bool = False) -> Dict[str, Any]:
    """Idempotent one-shot backfill. Returns per-tenant rollup."""
    sent = await db.migrations.find_one({"id": _SENTINEL_ID})
    if sent and not force:
        return {"already_ran": True,
                 "ran_at": sent.get("ran_at"),
                 "summary": sent.get("summary") or {}}

    rollup = {"tenants_scanned": 0,
                "docs_scanned": 0, "docs_updated": 0,
                "lines_hydrated_ws": 0, "lines_hydrated_lc": 0,
                "lines_hydrated_retail": 0, "lines_linked_by_name": 0,
                "errors": []}

    tenants = await db.tenants.find(
        {"$or": [{"active": {"$ne": False}},
                   {"active": {"$exists": False}}]},
        {"_id": 0, "id": 1},
    ).to_list(2000)

    for t in tenants:
        tid = t.get("id")
        if not tid:
            continue
        rollup["tenants_scanned"] += 1
        try:
            per = await _backfill_tenant(tid)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[invoice-cost-backfill] tenant %s crashed: %s",
                             tid, exc)
            rollup["errors"].append({"tenant_id": tid, "error": str(exc)})
            continue
        for k in ("docs_scanned", "docs_updated",
                    "lines_hydrated_ws", "lines_hydrated_lc",
                    "lines_hydrated_retail", "lines_linked_by_name"):
            rollup[k] += per[k]

    now = datetime.now(timezone.utc).isoformat()
    doc = {"id": _SENTINEL_ID, "ran_at": now, "summary": rollup}
    if sent and force:
        await db.migrations.update_one({"id": _SENTINEL_ID},
                                          {"$set": {"last_forced_run_at": now,
                                                     "last_forced_summary": rollup}})
    else:
        await db.migrations.insert_one(doc)

    logger.info(
        "[invoice-cost-backfill] scanned %d tenants · docs scanned=%d · "
        "updated=%d · WS hydrated=%d · LC hydrated=%d · retail hydrated=%d · "
        "linked-by-name=%d · errors=%d",
        rollup["tenants_scanned"], rollup["docs_scanned"], rollup["docs_updated"],
        rollup["lines_hydrated_ws"], rollup["lines_hydrated_lc"],
        rollup["lines_hydrated_retail"], rollup["lines_linked_by_name"],
        len(rollup["errors"]),
    )
    return {"already_ran": False, "ran_at": now, "summary": rollup}
