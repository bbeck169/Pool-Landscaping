"""Feb-2026 · P2 #6 property pivot — Dashboard property counts.

Four tenant-scoped count helpers consumed by ``GET /api/dashboard``
to drive the new Active Accounts + Pool / Landscaping / Both
property tiles rendered BELOW the existing customer-count tiles
(``cb8cd1a6a`` + ``70f4afc44``, intentionally preserved).

"Active property" definition (ruling #3 from the Feb-2026
dispatch, locked):

    * ``property.active != False`` — matches True + missing + null,
      preserving the "active by default" semantics the P33
      customer_properties helper already uses.
    * ``property.deleted_at`` not set.
    * Parent ``customer.is_active != False`` — a deactivated
      customer disqualifies all their properties.
    * Parent ``customer.deleted_at`` not set.

A ``customer.is_muted == True`` row does NOT disqualify its
properties — mute is a comms-suppression signal, NOT an
account-deactivation signal.

Union semantics mirror the P2 #6 customer-level counts:

    * Pool properties → ``service_category in {"pool", "both"}``
    * Landscaping properties → ``service_category in
      {"landscaping", "both"}``
    * Both-services properties → exact ``service_category == "both"``

A property with ``service_category == "both"`` is counted on BOTH
Pool and Landscaping tiles, matching the P2 #6 customer behaviour
+ the ``?service_category=pool`` filter on ``/api/properties``.
Properties with no ``service_category`` set (null/missing) count
toward Active Accounts but NOT toward any category tile.

Perf
----
Four ``count_documents`` calls per dashboard request. On tenants
with up to ~5000 properties this is <100ms total. If a tenant
scan exceeds the perf budget, the dashboard router logs
``kind=perf.dashboard_slow`` with the duration — operator signal
to add a covering index. No caching layered on top (dashboard
response is already cached upstream when enabled).
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List


logger = logging.getLogger(__name__)


_PERF_WARN_MS = 100


def _active_property_match_base(tenant_id: str) -> Dict[str, Any]:
    """Property-level active filter — the half of the gate that
    doesn't depend on the parent customer. ``active != False`` +
    ``deleted_at`` not set.
    """
    return {
        "tenant_id": tenant_id,
        "$and": [
            {"$or": [
                {"active": True},
                {"active": None},
                {"active": {"$exists": False}},
            ]},
            {"$or": [
                {"deleted_at": {"$exists": False}},
                {"deleted_at": None},
            ]},
        ],
    }


async def _active_customer_ids(*, db, tenant_id: str) -> List[str]:
    """Return the list of ``customer.id`` values whose row is still
    active per ruling #3 (``is_active != False`` + no soft-delete).

    Used as a ``$in`` filter on properties so the four counts share
    the same parent-customer gate.
    """
    cursor = db.customers.find(
        {
            "tenant_id": tenant_id,
            "$and": [
                {"$or": [{"is_active": True},
                          {"is_active": None},
                          {"is_active": {"$exists": False}}]},
                {"$or": [{"deleted_at": {"$exists": False}},
                          {"deleted_at": None}]},
            ],
        },
        {"_id": 0, "id": 1},
    )
    return [c["id"] async for c in cursor if c.get("id")]


async def compute_property_counts(
    *, db, tenant_id: str,
) -> Dict[str, int]:
    """Return the 4-field count payload consumed by
    ``GET /api/dashboard``::

        {
            "active_accounts_count": N,
            "pool_properties_count": N,
            "landscaping_properties_count": N,
            "both_properties_count": N,
        }

    All four share the ruling #3 "active property" gate. Each
    category count applies union semantics on top.
    """
    t0 = time.perf_counter()

    # Parent-customer gate — resolve once per request.
    active_cust_ids = await _active_customer_ids(
        db=db, tenant_id=tenant_id,
    )
    if not active_cust_ids:
        # Short-circuit: no active customers → zero active
        # properties by definition. Avoids an $in: [] which Mongo
        # treats as "match none" (correct) but silences a
        # potentially confusing debug trace.
        return {
            "active_accounts_count": 0,
            "pool_properties_count": 0,
            "landscaping_properties_count": 0,
            "both_properties_count": 0,
        }

    base = _active_property_match_base(tenant_id)
    base["customer_id"] = {"$in": active_cust_ids}

    active_accounts = await db.properties.count_documents(base)

    pool_q = {
        **base,
        "service_category": {
            "$regex": r"^(pool|both)$", "$options": "i",
        },
    }
    pool_count = await db.properties.count_documents(pool_q)

    landscape_q = {
        **base,
        "service_category": {
            "$regex": r"^(landscaping|both)$", "$options": "i",
        },
    }
    landscape_count = await db.properties.count_documents(landscape_q)

    both_q = {
        **base,
        "service_category": {"$regex": r"^both$", "$options": "i"},
    }
    both_count = await db.properties.count_documents(both_q)

    duration_ms = int((time.perf_counter() - t0) * 1000)
    if duration_ms > _PERF_WARN_MS:
        logger.warning(
            "kind=perf.dashboard_slow component=property_counts "
            "tenant=%s duration_ms=%d active_accounts=%d",
            tenant_id, duration_ms, active_accounts,
        )

    return {
        "active_accounts_count": active_accounts,
        "pool_properties_count": pool_count,
        "landscaping_properties_count": landscape_count,
        "both_properties_count": both_count,
    }
