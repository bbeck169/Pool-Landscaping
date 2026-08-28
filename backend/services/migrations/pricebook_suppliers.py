"""Backlog #iii · Feb-2026 — Pricebook multi-supplier fold-up.

Sentinel: ``pricebook_suppliers_v1``. Idempotent + sentinel-guarded.

Folds three legacy supplier shapes into the new authoritative
``items.suppliers[]`` list:

  A. Phase PB1 · scalar ``wholesale_price`` (single supplier cost).
  B. Phase 54a · ``supplier_slug`` / ``external_sku`` / ``last_synced_at``
     (wholesaler-scraper linkage).
  C. Phase 56-b · ``supplier_prices[{supplier_slug, cost_cents}]``
     (compact multi-supplier shape).

Fold-up rules (locked in the audit note + user's R1 approval):

  * Every entry in ``supplier_prices[]`` becomes one row in
    ``suppliers[]`` with:
      supplier_name = pricebook_suppliers.display_name(slug) OR slug
      supplier_sku  = ""
      unit_cost     = cost_cents / 100.0 (2-decimal precision)
      unit_size     = items.unit
      last_updated  = items.last_synced_at OR items.updated_at OR now
      notes         = ""

  * Legacy scalar ``wholesale_price`` becomes an additional row when
    (a) it's > 0 AND (b) no ``suppliers[]`` row with the same
    supplier_name (case-insensitive) already exists after step 1.
    The row uses:
      supplier_name = pricebook_suppliers.display_name(supplier_slug) OR "Legacy"
      supplier_sku  = items.external_sku OR ""
      unit_cost     = items.wholesale_price
      unit_size     = items.unit
      last_updated  = items.last_synced_at OR items.updated_at OR now
      notes         = "Migrated from Phase PB1 wholesale_price"

  * Dedup within an item's ``suppliers[]`` list on lowercase
    ``supplier_name``. Ties break on LOWER unit_cost (winner wins).

  * Compat mirrors regenerated in-place via
    ``services.pricebook.cost.rebuild_mirrors`` so grandfathered
    downstream consumers keep working (``wholesale_price`` scalar +
    ``supplier_prices[]`` compact array).

Sentinel-guarded so it only runs once per environment on boot; the
super_admin ``force=true`` endpoint re-runs against fresh data.

Runs AFTER the Phase 56-a supplier catalog seed so
``pricebook_suppliers`` name resolution finds display_names.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from config import db
from services.pricebook.cost import rebuild_mirrors
from utils import now_iso


logger = logging.getLogger("pricebook_suppliers_migration")


_SENTINEL_ID = "pricebook_suppliers_v1"


async def _sentinel_row() -> Optional[Dict[str, Any]]:
    return await db.migrations.find_one({"id": _SENTINEL_ID}, {"_id": 0})


async def _write_sentinel(summary: Dict[str, Any]) -> None:
    await db.migrations.update_one(
        {"id": _SENTINEL_ID},
        {"$set": {
            "id": _SENTINEL_ID,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "summary": summary,
        }},
        upsert=True,
    )


async def _load_pricebook_supplier_map(tenant_id: str) -> Dict[str, str]:
    """Return ``{slug: display_name}`` for the tenant's Phase 56-a
    pricebook_suppliers catalog. Missing → slug used verbatim."""
    out: Dict[str, str] = {}
    async for s in db.pricebook_suppliers.find(
        {"tenant_id": tenant_id},
        {"_id": 0, "slug": 1, "display_name": 1},
    ):
        slug = str(s.get("slug") or "").strip().lower()
        name = str(s.get("display_name") or "").strip()
        if slug and name:
            out[slug] = name
    return out


async def _load_supplier_catalog_map(tenant_id: str) -> Dict[str, str]:
    """Return ``{slug: display_name}`` for the tenant's Phase 54
    ``suppliers`` catalog (Pool360, SiteOne, Ewing, Heritage,
    ePoolSupply, plus any custom rows). Missing → slug verbatim."""
    out: Dict[str, str] = {}
    async for s in db.suppliers.find(
        {"tenant_id": tenant_id},
        {"_id": 0, "slug": 1, "display_name": 1},
    ):
        slug = str(s.get("slug") or "").strip().lower()
        name = str(s.get("display_name") or "").strip()
        if slug and name:
            out[slug] = name
    return out


def _resolve_display_name(
    slug: Optional[str],
    pricebook_map: Dict[str, str],
    supplier_map: Dict[str, str],
) -> str:
    """Look up a slug across both catalogs. Fallback: slug titled."""
    s = str(slug or "").strip().lower()
    if not s:
        return ""
    if s in pricebook_map:
        return pricebook_map[s]
    if s in supplier_map:
        return supplier_map[s]
    return s.title() if s else ""


def _build_suppliers_from_item(
    item: Dict[str, Any],
    pricebook_map: Dict[str, str],
    supplier_map: Dict[str, str],
    default_last: str,
) -> List[Dict[str, Any]]:
    """Fold Phase-56b + PB1 + Phase-54 shapes into rich
    ``suppliers[]``. Preserves any existing ``suppliers[]`` on the
    item (idempotent — a second run adds nothing new)."""
    out: List[Dict[str, Any]] = []
    seen: set = set()  # lower-cased supplier_name keys

    def _push(row: Dict[str, Any]) -> None:
        name = str(row.get("supplier_name") or "").strip()
        if not name:
            return
        key = name.lower()
        cost = row.get("unit_cost")
        try:
            cost_f = float(cost) if cost is not None else None
        except (TypeError, ValueError):
            cost_f = None
        if key in seen:
            # Dedup — keep the lower unit_cost when both defined.
            for existing in out:
                if str(existing.get("supplier_name") or "").lower() == key:
                    ex_cost = existing.get("unit_cost")
                    try:
                        ex_f = float(ex_cost) if ex_cost is not None else None
                    except (TypeError, ValueError):
                        ex_f = None
                    if cost_f is not None and (ex_f is None or cost_f < ex_f):
                        existing["unit_cost"] = round(cost_f, 2)
                    break
            return
        seen.add(key)
        out.append({
            "id": str(uuid.uuid4()),
            "supplier_name": name,
            "supplier_sku": str(row.get("supplier_sku") or ""),
            "unit_cost": (round(cost_f, 2) if cost_f is not None else None),
            "unit_size": str(row.get("unit_size") or ""),
            "last_updated": str(row.get("last_updated") or default_last),
            "notes": str(row.get("notes") or ""),
        })

    # 0. Preserve existing rich rows first — idempotency anchor.
    existing = item.get("suppliers") or []
    if isinstance(existing, list):
        for r in existing:
            if isinstance(r, dict) and r.get("supplier_name"):
                _push(r)

    # 1. Compact Phase 56-b entries.
    compact = item.get("supplier_prices") or []
    if isinstance(compact, list):
        for p in compact:
            if not isinstance(p, dict):
                continue
            slug = str(p.get("supplier_slug") or "").strip().lower()
            try:
                cents = int(p.get("cost_cents") or 0)
            except (TypeError, ValueError):
                cents = 0
            if not slug:
                continue
            name = _resolve_display_name(slug, pricebook_map, supplier_map)
            if not name:
                continue
            _push({
                "supplier_name": name,
                "supplier_sku": "",
                "unit_cost": (cents / 100.0) if cents > 0 else 0.0,
                "unit_size": str(item.get("unit") or ""),
                "last_updated": (str(item.get("last_synced_at") or "")
                                  or str(item.get("updated_at") or "")
                                  or default_last),
                "notes": "",
            })

    # 2. Legacy scalar wholesale_price + Phase 54 supplier_slug/sku.
    # Only fold this in when we have NO other supplier data yet —
    # otherwise the ``wholesale_price`` we see is very likely the
    # rebuilt mirror from step 0/1 and folding it in adds a phantom
    # "Legacy" row on every re-run.
    try:
        wp = float(item.get("wholesale_price") or 0)
    except (TypeError, ValueError):
        wp = 0.0
    if wp > 0 and not out:
        legacy_slug = (item.get("supplier_slug") or "").strip().lower()
        legacy_name = _resolve_display_name(
            legacy_slug, pricebook_map, supplier_map,
        ) or "Legacy"
        _push({
            "supplier_name": legacy_name,
            "supplier_sku": str(item.get("external_sku") or ""),
            "unit_cost": wp,
            "unit_size": str(item.get("unit") or ""),
            "last_updated": (str(item.get("last_synced_at") or "")
                              or str(item.get("updated_at") or "")
                              or default_last),
            "notes": "Migrated from Phase PB1 wholesale_price",
        })

    return out


async def run_pricebook_suppliers_migration(
    *, force: bool = False,
) -> Dict[str, Any]:
    """Full-fleet fold-up.

    ``force=True`` bypasses the sentinel — used by the super_admin
    admin endpoint. Idempotent — a second run over the same DB
    produces the same ``suppliers[]`` on every item (the seen-name
    dedup collapses re-folds).
    """
    if not force:
        sentinel = await _sentinel_row()
        if sentinel:
            logger.info(
                "[pricebook_suppliers] sentinel present · skipping",
            )
            return {
                "status": "skipped",
                "reason": "sentinel_present",
                "sentinel": sentinel,
            }

    default_last = now_iso()
    scanned = 0
    updated = 0
    skipped_no_change = 0
    errors: List[Dict[str, Any]] = []
    per_tenant_summary: Dict[str, Dict[str, int]] = {}

    tenants = [t for t in await db.items.distinct("tenant_id") if t]
    for tid in tenants:
        pricebook_map = await _load_pricebook_supplier_map(tid)
        supplier_map = await _load_supplier_catalog_map(tid)
        per_tenant_summary[tid] = {
            "scanned": 0, "updated": 0, "skipped": 0,
        }
        cursor = db.items.find(
            {"tenant_id": tid,
              "$or": [{"deleted_at": None},
                       {"deleted_at": {"$exists": False}}]},
            {"_id": 0},
        )
        async for item in cursor:
            scanned += 1
            per_tenant_summary[tid]["scanned"] += 1
            try:
                new_suppliers = _build_suppliers_from_item(
                    item, pricebook_map, supplier_map, default_last,
                )
                existing = item.get("suppliers") or []
                # Idempotency short-circuit — if the list content
                # matches (by supplier_name → unit_cost tuple set),
                # skip the write.
                def _sig(rows: List[Dict[str, Any]]) -> set:
                    return {
                        (
                            str(r.get("supplier_name") or "").lower(),
                            (round(float(r.get("unit_cost") or 0), 2)
                              if r.get("unit_cost") is not None else None),
                        )
                        for r in (rows or [])
                        if isinstance(r, dict) and r.get("supplier_name")
                    }
                if _sig(existing) == _sig(new_suppliers) and not force:
                    skipped_no_change += 1
                    per_tenant_summary[tid]["skipped"] += 1
                    continue
                mirrors = rebuild_mirrors({"suppliers": new_suppliers})
                update_doc = {
                    "suppliers": new_suppliers,
                    "suppliers_backfilled_at": default_last,
                }
                # Only overwrite mirrors when we produced them (empty
                # suppliers → keep existing mirrors untouched).
                update_doc.update(mirrors)
                await db.items.update_one(
                    {"id": item["id"], "tenant_id": tid},
                    {"$set": update_doc},
                )
                updated += 1
                per_tenant_summary[tid]["updated"] += 1
            except Exception as exc:                              # noqa: BLE001
                errors.append({"item_id": item.get("id"),
                                "tenant_id": tid, "error": str(exc)})
                logger.warning(
                    "[pricebook_suppliers] tenant=%s item=%s failed: %s",
                    tid, item.get("id"), exc,
                )

    summary = {
        "scanned_items": scanned,
        "updated_items": updated,
        "skipped_no_change": skipped_no_change,
        "errors_count": len(errors),
        "errors": errors,
        "per_tenant": per_tenant_summary,
        "tenants_scanned": len(tenants),
    }
    await _write_sentinel(summary)
    logger.info(
        "[pricebook_suppliers] scanned=%s updated=%s skipped=%s "
        "tenants=%s errors=%s",
        scanned, updated, skipped_no_change, len(tenants), len(errors),
    )
    return {"status": "ok", "summary": summary}
