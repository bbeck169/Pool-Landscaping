"""Phase 54b · Feb-2026 — Supplier sync service (dedupe + soft-delete).

Called from a FastAPI background task by
``POST /api/suppliers/{slug}/sync``. Owns the job-row lifecycle
(running → success/error), matches on ``(tenant_id, supplier_id,
external_sku)`` to insert new / update existing / soft-delete
missing pricebook items.

Soft-delete = sets ``deleted_at``, never physically drops rows.
Quotes / invoices already referencing an item's snapshot fields
continue to work — the row just stops appearing in the pricebook UI.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from config import db, logger


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def start_sync_job(tenant_id: str, supplier: Dict[str, Any]) -> Dict[str, Any]:
    """Insert a ``running`` job row and return it."""
    doc = {
        "id": str(uuid.uuid4()),
        "tenant_id": tenant_id,
        "supplier_id": supplier["id"],
        "supplier_slug": supplier["slug"],
        "started_at": _now_iso(),
        "finished_at": None,
        "status": "running",
        "items_added": 0,
        "items_updated": 0,
        "items_removed": 0,
        "error_message": "",
    }
    await db.supplier_sync_jobs.insert_one(dict(doc))
    return doc


async def finalize_sync_job(
    job_id: str, *, status: str,
    items_added: int = 0, items_updated: int = 0, items_removed: int = 0,
    error_message: str = "",
) -> None:
    await db.supplier_sync_jobs.update_one(
        {"id": job_id},
        {"$set": {
            "finished_at": _now_iso(),
            "status": status,
            "items_added": items_added,
            "items_updated": items_updated,
            "items_removed": items_removed,
            "error_message": error_message or "",
        }},
    )


async def apply_products_to_pricebook(
    tenant_id: str, supplier: Dict[str, Any],
    products: List[Dict[str, Any]],
) -> Dict[str, int]:
    """Reconcile the incoming product list against ``db.items``.

    Returns ``{added, updated, removed}`` counters. Matching key is
    ``(tenant_id, supplier_id, external_sku)``. Items missing from
    the incoming list get a ``deleted_at`` stamp (soft-delete)."""
    now = _now_iso()
    added = updated = removed = 0
    incoming_skus = {p["sku"] for p in products if p.get("sku")}

    # Layout-change guard: an empty product list must NOT wipe every
    # supplier item. The caller is expected to raise before reaching
    # here, but defense-in-depth: refuse the reconcile.
    if not products:
        logger.warning(
            f"[suppliers] sync produced zero products for tenant={tenant_id[:8]} "
            f"slug={supplier['slug']} — refusing to soft-delete existing rows.")
        return {"added": 0, "updated": 0, "removed": 0}

    for p in products:
        sku = (p.get("sku") or "").strip()
        if not sku:
            continue
        existing = await db.items.find_one(
            {"tenant_id": tenant_id, "supplier_id": supplier["id"],
              "external_sku": sku},
            {"_id": 0, "id": 1, "name": 1, "unit_price": 1,
              "wholesale_price": 1, "category": 1, "unit": 1, "description": 1},
        )
        payload = {
            "tenant_id": tenant_id,
            "supplier_id": supplier["id"],
            "external_sku": sku,
            "last_synced_at": now,
            "name": p.get("name") or sku,
            "wholesale_price": p.get("cost"),
            "unit_price": p.get("msrp"),
            "category": p.get("category") or "Parts",
            "unit": p.get("uom") or "each",
            "description": p.get("description") or "",
            "sku": sku,
            "deleted_at": None,
            "active": True,
        }
        if existing:
            payload["id"] = existing["id"]
            await db.items.update_one({"id": existing["id"]}, {"$set": payload})
            updated += 1
        else:
            payload["id"] = str(uuid.uuid4())
            payload["created_at"] = now
            await db.items.insert_one(dict(payload))
            added += 1

    # Soft-delete items that belonged to this supplier but are absent
    # from the current sync.
    stale = db.items.find(
        {"tenant_id": tenant_id, "supplier_id": supplier["id"],
          "deleted_at": None},
        {"_id": 0, "id": 1, "external_sku": 1},
    )
    async for row in stale:
        if row.get("external_sku") not in incoming_skus:
            await db.items.update_one(
                {"id": row["id"]},
                {"$set": {"deleted_at": now, "active": False,
                            "last_synced_at": now}},
            )
            removed += 1

    return {"added": added, "updated": updated, "removed": removed}


async def run_supplier_sync(
    tenant_id: str, supplier: Dict[str, Any],
    credentials: Dict[str, Any], job_id: str,
    connector,
) -> None:
    """Generic supplier sync runner. Used by ``run_poolcorp_sync`` and
    ``run_siteone_sync`` (Phase 54c) — each variant is a thin wrapper
    that just instantiates the right connector and delegates here.

    ``connector`` is a live instance with ``authenticate`` and
    ``list_products`` coroutines. Any ``LoginFailedError`` /
    ``LayoutChangedError`` raised from either coroutine is captured
    onto the job row as an ``error`` status. All other exceptions
    are captured with their class name for triage.
    """
    from services.suppliers.poolcorp import (
        LoginFailedError, LayoutChangedError,
    )
    try:
        session = await connector.authenticate(credentials)
        products: List[Dict[str, Any]] = []
        async for ep in connector.list_products(session):
            products.append({
                "sku": ep.sku, "name": ep.name, "cost": ep.cost,
                "msrp": ep.msrp, "category": ep.category, "uom": ep.uom,
                "description": ep.description,
            })
        counts = await apply_products_to_pricebook(tenant_id, supplier, products)
        await finalize_sync_job(
            job_id, status="success",
            items_added=counts["added"],
            items_updated=counts["updated"],
            items_removed=counts["removed"],
        )
        # Warn on suspicious drop (>50% fewer items than last sync).
        prior = await db.supplier_sync_jobs.find_one(
            {"tenant_id": tenant_id, "supplier_id": supplier["id"],
              "status": "success", "id": {"$ne": job_id}},
            {"_id": 0, "items_added": 1, "items_updated": 1},
            sort=[("started_at", -1)],
        )
        if prior:
            prior_total = int(prior.get("items_added", 0)) + int(prior.get("items_updated", 0))
            now_total = counts["added"] + counts["updated"]
            if prior_total > 20 and now_total < prior_total * 0.5:
                logger.warning(
                    f"[suppliers] SYNC ANOMALY tenant={tenant_id[:8]} "
                    f"slug={supplier['slug']}: {now_total} items vs prior "
                    f"{prior_total} — likely layout change or credential expiry.")
    except LoginFailedError as e:
        await finalize_sync_job(job_id, status="error", error_message=str(e))
    except LayoutChangedError as e:
        await finalize_sync_job(job_id, status="error", error_message=str(e))
    except Exception as e:
        await finalize_sync_job(
            job_id, status="error",
            error_message=f"{type(e).__name__}: {e}",
        )


async def run_poolcorp_sync(
    tenant_id: str, supplier: Dict[str, Any],
    credentials: Dict[str, Any], job_id: str,
) -> None:
    """Pool360 sync entry-point — kept as a stable name for Phase 54b
    callers + tests. Instantiates the Pool360 connector then delegates
    to ``run_supplier_sync``."""
    from services.suppliers.poolcorp import PoolCorpConnector
    connector = PoolCorpConnector()
    await run_supplier_sync(tenant_id, supplier, credentials, job_id, connector)


async def run_siteone_sync(
    tenant_id: str, supplier: Dict[str, Any],
    credentials: Dict[str, Any], job_id: str,
) -> None:
    """SiteOne sync entry-point (Phase 54c). Thin wrapper on
    ``run_supplier_sync`` with the wired ``SiteOneConnector``."""
    from services.suppliers.siteone import SiteOneConnector
    connector = SiteOneConnector()
    await run_supplier_sync(tenant_id, supplier, credentials, job_id, connector)


async def run_ewing_sync(
    tenant_id: str, supplier: Dict[str, Any],
    credentials: Dict[str, Any], job_id: str,
) -> None:
    """Ewing Irrigation sync entry-point (Phase 54d). Thin wrapper on
    ``run_supplier_sync`` with the wired ``EwingConnector``."""
    from services.suppliers.ewing import EwingConnector
    connector = EwingConnector()
    await run_supplier_sync(tenant_id, supplier, credentials, job_id, connector)
