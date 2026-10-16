"""Feb-2026 · Phase A.5 — Property geocoding diagnostics + backfill.

Sister module to ``admin_customer_geocode_backfill.py``.

Why this exists
---------------
Phase 4 (multi-property map pins) wire-shipped a ``coord_source`` field
on every job response — ``"job" | "property" | "customer" | null``.
The property rung lives inline in ``routers/jobs.py`` (L1340-1444)
and relies on ``db.properties.latitude/longitude`` being populated by
``services/google_maps/geocoding.py::geocode_and_persist_property``.

An operator-reported bug surfaced two customers with distinct Phoenix
+ Glendale addresses pinning to the same spot on the Schedule map.
A Mongo audit found a 235-property cluster at (33.5806, -112.2374) —
a tenant-centroid write from a legacy bulk geocode where addresses
were under-specified. 96% of properties (6756/7036) have NO coords
at all; only 280 are populated, and 235 of those share the bad spot.

This router ships two endpoints:

  1. ``GET /admin/diagnostics/property-geocoding``
     Admin-only. Returns per-tenant counts (valid / null / zero) plus
     the top-15 duplicate-coord clusters so operators can confirm the
     bug and triage.

  2. ``POST /admin/properties/geocode-backfill``
     Admin-only. Scans properties missing coords (null OR zero) with
     a resolvable address and re-geocodes via the existing
     ``geocode_and_persist_property`` helper. Dry-run by default so
     operators preview the candidate set before writing. Rate-limited
     to 500 rows per invocation + 200 ms drip between calls (matches
     ``admin_customer_geocode_backfill``'s cadence).

Idempotency
-----------
``geocode_and_persist_property`` already caches on ``geocoded_at`` so
a backfill rerun on freshly-geocoded rows is a no-op. The dry-run
mode skips the cache check entirely — it only reports what WOULD
change, not what actually ran.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from config import db, logger
from utils import get_current_user, now_iso
from services.google_maps.geocode_trigger import GeocodeTrigger as _GT
from routers.tenants import get_current_tenant

router = APIRouter()

_RATE_LIMIT_DELAY_S = 0.2
_DEFAULT_BACKFILL_MAX = 500
_DUPLICATE_CLUSTER_LIMIT = 15
_SAMPLE_LIMIT = 50
_CLUSTER_ROUND_DECIMALS = 4  # ~11m resolution


def _require_admin(user: dict) -> None:
    role = (user or {}).get("role") or ""
    if role not in ("admin", "super_admin"):
        raise HTTPException(403, "Admin access required")


def _flatten_property_address(prop: Dict[str, Any]) -> str:
    """Mirror of the formatting used by
    ``geocode_and_persist_property`` so dry-run output matches
    live-run inputs. Returns an empty string when no address field
    is present."""
    addr = prop.get("address") or {}
    if not isinstance(addr, dict):
        return str(addr).strip() if addr else ""
    return " ".join(filter(None, [
        addr.get("address_line1"), addr.get("address_line2"),
        addr.get("city"), addr.get("state"), addr.get("zip"),
    ])).strip()


# ---------------------------------------------------------------------------
# Diagnostic endpoint
# ---------------------------------------------------------------------------


@router.get("/admin/diagnostics/property-geocoding")
async def property_geocoding_diagnostics(
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    """Return per-tenant property-geocoding health counts + duplicate
    coord clusters. Admin / super_admin only.

    Response shape::

        {
          "total_properties": int,
          "with_valid_coords": int,
          "null_coords": int,
          "zero_coords": int,
          "sample_null":  [ {id, label, address_line_1, customer_id} ],
          "sample_zero":  [...],
          "duplicate_coord_clusters": [
            {"lat": float, "lng": float, "property_count": int,
             "property_ids": [str], "property_labels": [str]}
          ]
        }
    """
    _require_admin(user)
    tenant_id = tenant["id"]

    total = await db.properties.count_documents({"tenant_id": tenant_id})
    null_coords = await db.properties.count_documents({
        "tenant_id": tenant_id,
        "$or": [
            {"latitude": None}, {"latitude": {"$exists": False}},
            {"longitude": None}, {"longitude": {"$exists": False}},
        ],
    })
    zero_coords = await db.properties.count_documents({
        "tenant_id": tenant_id,
        "$or": [{"latitude": 0}, {"longitude": 0}],
    })
    with_valid = await db.properties.count_documents({
        "tenant_id": tenant_id,
        "latitude": {"$nin": [None, 0], "$exists": True},
        "longitude": {"$nin": [None, 0], "$exists": True},
    })

    # Sample lists — small projection, capped at _SAMPLE_LIMIT.
    sample_proj = {"_id": 0, "id": 1, "label": 1, "address": 1, "customer_id": 1}

    def _project_sample(p: Dict[str, Any]) -> Dict[str, Any]:
        addr = (p.get("address") or {}) if isinstance(p.get("address"), dict) else {}
        return {
            "id": p.get("id"),
            "label": p.get("label") or None,
            "address_line_1": addr.get("address_line1") or None,
            "customer_id": p.get("customer_id") or None,
        }

    sample_null: List[Dict[str, Any]] = []
    cur = db.properties.find(
        {"tenant_id": tenant_id,
         "$or": [{"latitude": None}, {"latitude": {"$exists": False}}]},
        sample_proj,
    ).limit(_SAMPLE_LIMIT)
    async for p in cur:
        sample_null.append(_project_sample(p))

    sample_zero: List[Dict[str, Any]] = []
    cur = db.properties.find(
        {"tenant_id": tenant_id, "$or": [{"latitude": 0}, {"longitude": 0}]},
        sample_proj,
    ).limit(_SAMPLE_LIMIT)
    async for p in cur:
        sample_zero.append(_project_sample(p))

    # Duplicate-cluster detection: group by rounded coords (4 decimals
    # ≈ 11m resolution). Only clusters >=2 are returned.
    clusters: List[Dict[str, Any]] = []
    pipeline = [
        {"$match": {
            "tenant_id": tenant_id,
            "latitude": {"$nin": [None, 0], "$exists": True},
            "longitude": {"$nin": [None, 0], "$exists": True},
        }},
        {"$group": {
            "_id": {
                "lat": {"$round": ["$latitude", _CLUSTER_ROUND_DECIMALS]},
                "lng": {"$round": ["$longitude", _CLUSTER_ROUND_DECIMALS]},
            },
            "count": {"$sum": 1},
            "property_ids": {"$push": "$id"},
            "property_labels": {"$push": "$label"},
        }},
        {"$match": {"count": {"$gte": 2}}},
        {"$sort": {"count": -1}},
        {"$limit": _DUPLICATE_CLUSTER_LIMIT},
    ]
    async for r in db.properties.aggregate(pipeline):
        clusters.append({
            "lat": r["_id"]["lat"],
            "lng": r["_id"]["lng"],
            "property_count": r["count"],
            # Cap the per-cluster id/label lists at 10 so the response
            # stays small when a cluster has hundreds of members.
            "property_ids": (r.get("property_ids") or [])[:10],
            "property_labels": (r.get("property_labels") or [])[:10],
        })

    return {
        "total_properties": total,
        "with_valid_coords": with_valid,
        "null_coords": null_coords,
        "zero_coords": zero_coords,
        "sample_null": sample_null,
        "sample_zero": sample_zero,
        "duplicate_coord_clusters": clusters,
    }


# ---------------------------------------------------------------------------
# Backfill endpoint
# ---------------------------------------------------------------------------


class _BackfillRequest(BaseModel):
    dry_run: bool = Field(default=True, description=(
        "When True, resolve addresses but do NOT persist. Returns a "
        "preview of what WOULD change. When False, each candidate is "
        "pushed through geocode_and_persist_property and the audit log "
        "is stamped."
    ))
    max_rows: int = Field(default=_DEFAULT_BACKFILL_MAX, ge=1, le=5000)


async def _unlocated_properties(
    tenant_id: str, max_rows: int,
) -> List[Dict[str, Any]]:
    """Fetch properties missing coords (null OR zero on either axis)
    with a non-empty resolvable address. Capped at ``max_rows``.
    """
    q = {
        "tenant_id": tenant_id,
        "$or": [
            {"latitude": None},
            {"latitude": {"$exists": False}},
            {"latitude": 0},
            {"longitude": 0},
        ],
    }
    proj = {"_id": 0, "id": 1, "label": 1, "address": 1,
            "customer_id": 1, "latitude": 1, "longitude": 1}
    rows: List[Dict[str, Any]] = []
    async for p in db.properties.find(q, proj).limit(max_rows):
        if _flatten_property_address(p):
            rows.append(p)
    return rows


@router.post("/admin/properties/geocode-backfill")
async def backfill_property_geocoding(
    body: _BackfillRequest,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    """Admin+/super_admin-only. Scan properties missing coords and
    (optionally) re-geocode via ``geocode_and_persist_property``.

    ``dry_run=True`` (default) returns the candidate set + sample of
    the first 10 addresses that would be geocoded without writing
    anything. ``dry_run=False`` runs the loop with a 200 ms drip,
    writes via the existing helper, and stamps ``db.audit_logs``.
    """
    _require_admin(user)
    tenant_id = tenant["id"]
    actor = (user or {}).get("id")

    rows = await _unlocated_properties(tenant_id, body.max_rows)

    sample_updates = [
        {
            "property_id": p["id"],
            "label": p.get("label"),
            "address": _flatten_property_address(p),
        }
        for p in rows[:10]
    ]

    if body.dry_run or len(rows) == 0:
        return {
            "dry_run": body.dry_run,
            "candidates": len(rows),
            "processed": 0,
            "updated": 0,
            "failed": 0,
            "sample_updates": sample_updates,
            "errors": [],
        }

    # Live run — write path.
    from services.google_maps.geocoding import geocode_and_persist_property

    processed = 0
    updated = 0
    failed = 0
    errors: List[Dict[str, Any]] = []
    for i, p in enumerate(rows):
        processed += 1
        try:
            ok = await geocode_and_persist_property(
                p["id"], tenant_id,
                trigger_reason=_GT.ADMIN_BACKFILL,
            )
            if ok:
                updated += 1
            else:
                failed += 1
                errors.append({
                    "property_id": p["id"],
                    "error": "geocode_failed_or_no_address",
                })
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "[backfill-property-geocoding] pid=%s err=%s",
                p.get("id"), exc,
            )
            failed += 1
            errors.append({"property_id": p["id"], "error": str(exc)})
        if i < len(rows) - 1:
            await asyncio.sleep(_RATE_LIMIT_DELAY_S)

    # Best-effort audit log.
    try:
        await db.audit_logs.insert_one({
            "tenant_id": tenant_id,
            "action": "property.geocode_backfill",
            "actor_user_id": actor,
            "at": now_iso(),
            "payload": {
                "processed": processed,
                "updated": updated,
                "failed": failed,
                "candidates": len(rows),
            },
        })
    except Exception as _exc:  # noqa: BLE001
        logger.warning(
            "[backfill-property-geocoding] audit log failed: %s", _exc,
        )

    # Cap the errors list on the response so a 500-row run doesn't
    # push a 500-item array through the API.
    return {
        "dry_run": False,
        "candidates": len(rows),
        "processed": processed,
        "updated": updated,
        "failed": failed,
        "sample_updates": sample_updates,
        "errors": errors[:50],
    }
