"""Feb-2026 · Phase — Customer geocoding on save + one-time backfill.

Admin-only endpoint that scans tenant customers missing ``latitude``
/ ``longitude`` (or the legacy ``service_lat`` / ``service_lng``
pair), resolves their address via ``resolve_customer_address``, and
calls ``geocode_and_persist_customer`` per row with a 200 ms delay
between calls so the batch stays well under Google's 50 QPS
default limit.

Threshold rule
--------------
Scans ≤ 20 unlocated customers → run inline; return the counts
synchronously so the admin sees the result immediately.
Scans > 20 unlocated customers → hand off to a background task
and return ``{enqueued: true, estimated_seconds: N}``. Estimate
assumes 200 ms per row + a ~400 ms Google round-trip = 600 ms per
row. See ``memory/FEATURE_CUSTOMER_AUTO_GEOCODE_AND_BACKFILL.md``.

Idempotency
-----------
``geocode_and_persist_customer`` already 30-day-caches on the
customer's ``geocoded_at`` timestamp, AND the create/update
paths now stamp a ``geocode_address_hash`` off the resolved
address so a re-geocode of an unchanged address short-circuits.
Running the backfill twice on the same data → 0 fresh updates,
just re-scans.
"""
from __future__ import annotations

import asyncio
import hashlib
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from config import db, logger
from utils import get_current_user, now_iso
from routers.tenants import get_current_tenant

router = APIRouter()

_RATE_LIMIT_DELAY_S = 0.2
_INLINE_THRESHOLD = 20
_PER_ROW_ESTIMATE_S = 0.6


def address_hash(addr: str) -> str:
    """Stable content hash off a resolved address string. Used as
    the idempotency key for auto-geocode-on-save — a customer
    update that mutates only, say, notes doesn't re-geocode.

    Normalisation: lowercase + whitespace collapse. Anything more
    aggressive (strip punctuation, expand ``st``→``street``, etc.)
    risks masking real changes (``"1 Main St"`` vs.
    ``"1 Main St #2"`` MUST hash differently).
    """
    if not addr:
        return ""
    norm = " ".join(str(addr).strip().lower().split())
    return hashlib.sha1(norm.encode("utf-8")).hexdigest()


async def _unlocated_customers_query(tenant_id: str) -> List[Dict[str, Any]]:
    """Return every customer in the tenant that has no coord pair
    (neither the canonical ``latitude/longitude`` nor the legacy
    ``service_lat/service_lng``) AND resolves to a non-empty
    address via the fallback chain. Deleted customers are
    filtered out.
    """
    from services.google_maps.geocoding import resolve_customer_address

    q = {
        "tenant_id": tenant_id,
        "is_deleted": {"$ne": True},
        "$and": [
            {"$or": [{"latitude": None},
                        {"latitude": {"$exists": False}}]},
            {"$or": [{"service_lat": None},
                        {"service_lat": {"$exists": False}}]},
        ],
    }
    proj = {"_id": 0, "id": 1,
              "service_address": 1, "address": 1,
              "street_address": 1, "mailing_address": 1,
              "service_street": 1, "street": 1,
              "service_city": 1, "city": 1,
              "service_state": 1, "state": 1,
              "service_zip": 1, "zip": 1,
              "property": 1}
    rows: List[Dict[str, Any]] = []
    async for c in db.customers.find(q, proj):
        if resolve_customer_address(c).strip():
            rows.append(c)
    return rows


async def _run_backfill(tenant_id: str,
                          rows: List[Dict[str, Any]],
                          actor_user_id: Optional[str]) -> Dict[str, int]:
    """The actual loop — called inline OR from a background task.
    Delegates each row to ``geocode_and_persist_customer`` (which
    also stamps ``geocoded_at`` + persists ``latitude/longitude``
    + ``service_location`` GeoJSON). Sleeps 200 ms between rows.
    """
    from services.google_maps.geocoding import geocode_and_persist_customer

    counters = {"scanned": 0, "updated": 0, "failed": 0,
                  "skipped_no_address": 0}
    for i, c in enumerate(rows):
        counters["scanned"] += 1
        try:
            ok = await geocode_and_persist_customer(c["id"], tenant_id)
            if ok:
                counters["updated"] += 1
            else:
                # The helper returns False for missing-address AND
                # for API failure — distinguishable via the current
                # doc post-write. Fast path: treat as failure since
                # ``_unlocated_customers_query`` already filtered
                # out no-address rows.
                counters["failed"] += 1
        except Exception as exc:                                # noqa: BLE001
            logger.warning("[backfill-geocoding] cid=%s err=%s",
                            c.get("id"), exc)
            counters["failed"] += 1
        # 200 ms drip between calls — keeps us well under the
        # default 50 QPS Google quota and gives their rate limiter
        # breathing room.
        if i < len(rows) - 1:
            await asyncio.sleep(_RATE_LIMIT_DELAY_S)

    # Best-effort audit log — never blocks the response.
    try:
        await db.audit_logs.insert_one({
            "tenant_id": tenant_id,
            "action": "customer_geocode_backfill",
            "actor_user_id": actor_user_id,
            "at": now_iso(),
            "payload": counters,
        })
    except Exception as _exc:                                   # noqa: BLE001
        logger.warning("[backfill-geocoding] audit log failed: %s", _exc)
    return counters


@router.post("/admin/customers/backfill-geocoding")
async def backfill_customer_geocoding(
    background_tasks: BackgroundTasks,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    """Admin+/super_admin-only. Scan customers missing coords, run
    ``geocode_and_persist_customer`` on each with a 200 ms drip.

    Sync/inline when the queue is ≤ 20 rows; background-task when
    > 20. Response shape mirrors the spec:

    ::

        Inline    → {scanned, updated, failed, skipped_no_address,
                     enqueued: false}
        Background→ {enqueued: true, estimated_seconds,
                     queue_size, message}
    """
    role = (user or {}).get("role") or ""
    if role not in ("admin", "super_admin"):
        raise HTTPException(403, "Admin access required")

    tenant_id = tenant["id"]
    actor = (user or {}).get("id")

    rows = await _unlocated_customers_query(tenant_id)

    # skipped_no_address is the DIFFERENCE between everyone
    # missing coords and those with a resolvable address.
    from services.google_maps.geocoding import resolve_customer_address
    q_all = {
        "tenant_id": tenant_id,
        "is_deleted": {"$ne": True},
        "$and": [
            {"$or": [{"latitude": None},
                        {"latitude": {"$exists": False}}]},
            {"$or": [{"service_lat": None},
                        {"service_lat": {"$exists": False}}]},
        ],
    }
    total_missing = await db.customers.count_documents(q_all)
    skipped_no_address = max(0, total_missing - len(rows))

    if len(rows) == 0:
        return {"scanned": 0, "updated": 0, "failed": 0,
                 "skipped_no_address": skipped_no_address,
                 "enqueued": False}

    if len(rows) <= _INLINE_THRESHOLD:
        counters = await _run_backfill(tenant_id, rows, actor)
        counters["skipped_no_address"] = skipped_no_address
        counters["enqueued"] = False
        return counters

    # Background path — hand off to FastAPI's BackgroundTasks so the
    # response fires immediately.
    background_tasks.add_task(
        _run_backfill, tenant_id, rows, actor,
    )
    return {
        "enqueued": True,
        "queue_size": len(rows),
        "estimated_seconds": int(round(len(rows) * _PER_ROW_ESTIMATE_S)),
        "skipped_no_address": skipped_no_address,
        "message": ("Backfill running in background — refresh in a "
                     f"few minutes to see updates ({len(rows)} rows)"),
    }
