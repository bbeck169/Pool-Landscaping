"""Feb-2026 · Backlog #1 Tightening T1 — invoice line-items with a
UUID-shaped ``category`` string.

The Revenue-by-Category tile was rendering a raw UUID as a legend
label because a legacy write path persisted an id (not a name) into
``line_items[].category``. The tile handler now hardens against this
at render time (id→name resolution + Uncategorized coercion), but
historical data can still surface the UUID on other tiles / reports
that don't share the same guard.

This migration walks every invoice's ``line_items[]`` array. For each
entry whose ``category`` matches ``^[0-9a-f]{8}-...{12}$`` (UUID
shape) we try to resolve the id against the tenant's
``income_categories`` collection:

  * Resolved → rewrite ``category`` to the human name AND stamp
    ``income_category_id`` on the line item (if not already set).
  * Unresolved → clear ``category`` to ``""`` (empty; the tile's
    fallback logic collapses it into the Uncategorized bucket).

Idempotent + sentinel-guarded. Sentinel:
``revenue_line_items_uuid_category_v1``.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from config import db
from utils import now_iso


logger = logging.getLogger("revenue_line_items_uuid_category_migration")


_SENTINEL_ID = "revenue_line_items_uuid_category_v1"


_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


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


async def _load_income_cat_map(tid: str) -> Dict[str, str]:
    """Return ``{income_category.id: name}`` for one tenant."""
    out: Dict[str, str] = {}
    async for row in db.income_categories.find(
        {"tenant_id": tid},
        {"_id": 0, "id": 1, "name": 1},
    ):
        rid = row.get("id")
        nm = (row.get("name") or "").strip()
        if rid and nm:
            out[rid] = nm
    return out


async def run_revenue_line_items_uuid_category_migration(
    *, force: bool = False,
) -> Dict[str, Any]:
    """Full-fleet backfill.

    ``force=True`` bypasses the sentinel — used by the super_admin
    admin endpoint for on-demand re-runs. Runs after the
    ``service_category_chemicals`` boot migration so the income
    categories collection is fully seeded before we resolve.
    """
    if not force:
        sentinel = await _sentinel_row()
        if sentinel:
            logger.info(
                "[revenue_line_items_uuid_category] sentinel present · skipping",
            )
            return {
                "status": "skipped",
                "reason": "sentinel_present",
                "sentinel": sentinel,
            }

    scanned = 0
    rewritten_to_name = 0
    cleared_orphan = 0
    skipped = 0
    errors: List[Dict[str, Any]] = []
    now = now_iso()

    # Cache tenant-scoped id→name maps.
    cat_map_cache: Dict[str, Dict[str, str]] = {}

    async def _map_for(tid: str) -> Dict[str, str]:
        if tid not in cat_map_cache:
            cat_map_cache[tid] = await _load_income_cat_map(tid)
        return cat_map_cache[tid]

    # Only touch invoices — quotes/estimates aren't a Revenue-tile
    # source. We do NOT filter by ``payment_status`` because the tile
    # renders paid invoices only, but historical unpaid rows would
    # still leak UUIDs on other reports.
    cursor = db.quotes.find(
        {"doc_type": "invoice",
          "line_items": {"$elemMatch": {"category": {"$regex": _UUID_RE.pattern,
                                                        "$options": "i"}}}},
        {"_id": 0, "id": 1, "tenant_id": 1, "line_items": 1},
    )
    async for inv in cursor:
        scanned += 1
        try:
            tid = inv.get("tenant_id") or ""
            cat_map = await _map_for(tid)
            new_lines = []
            touched = False
            for li in (inv.get("line_items") or []):
                if not isinstance(li, dict):
                    new_lines.append(li)
                    continue
                cat = (li.get("category") or "").strip()
                if cat and _UUID_RE.match(cat):
                    resolved = cat_map.get(cat)
                    new_li = dict(li)
                    if resolved:
                        new_li["category"] = resolved
                        if not new_li.get("income_category_id"):
                            new_li["income_category_id"] = cat
                        rewritten_to_name += 1
                    else:
                        new_li["category"] = ""
                        cleared_orphan += 1
                    new_li["category_backfilled_at"] = now
                    new_lines.append(new_li)
                    touched = True
                else:
                    new_lines.append(li)
            if touched:
                await db.quotes.update_one(
                    {"id": inv["id"]},
                    {"$set": {
                        "line_items": new_lines,
                        "line_items_category_backfilled_at": now,
                    }},
                )
            else:
                skipped += 1
        except Exception as exc:                                # noqa: BLE001
            errors.append({"invoice_id": inv.get("id"), "error": str(exc)})
            logger.warning(
                f"[revenue_line_items_uuid_category] "
                f"{inv.get('id')} failed: {exc}",
            )

    summary = {
        "scanned": scanned,
        "rewritten_to_name": rewritten_to_name,
        "cleared_orphan": cleared_orphan,
        "skipped": skipped,
        "errors_count": len(errors),
        "errors": errors,
    }
    await _write_sentinel(summary)
    logger.info(
        f"[revenue_line_items_uuid_category] scanned={scanned} "
        f"rewritten_to_name={rewritten_to_name} "
        f"cleared_orphan={cleared_orphan} skipped={skipped} "
        f"errors={len(errors)}",
    )
    return {"status": "ok", "summary": summary}
