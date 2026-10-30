"""Feb-2026 · P2 #6 property pivot — Dashboard property counts.

Four tenant-scoped count helpers consumed by ``GET /api/dashboard``
to drive the new Active Accounts + Pool / Landscaping / Both
property tiles rendered BELOW the existing customer-count tiles
(``cb8cd1a6a`` + ``70f4afc44``, intentionally preserved).

TD-80 · Feb-2026 — the "active property" + "active customer"
predicates are now sourced from
``services/properties_active_predicate`` so this module and
``routers/properties.list_properties`` share a single source of
truth.  See the audit at
``/app/memory/td80_active_accounts_audit.md`` for the full
root-cause explanation.

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
from typing import Any, Dict, List, Optional

from services.properties_active_predicate import (
    active_customer_ids,
    active_property_match_base,
)


logger = logging.getLogger(__name__)


_PERF_WARN_MS = 100


# Ticket V · Feb-2026 — Property-category inclusive-match rule.
# Mirrors the regex ladder ``compute_property_counts`` emits so the
# aggregator and the new ``/api/customers?property_service_category=X``
# list filter are provably identical in their inclusive-rule
# semantics (case-insensitive, union on Pool / Landscaping, exact
# on Both). Centralised here so both call-sites stay in lockstep.
_PROPERTY_CATEGORY_REGEX = {
    "pool":        r"^(pool|both)$",
    "landscaping": r"^(landscaping|both)$",
    "both":        r"^both$",
}


def _category_match(category: str) -> Optional[Dict[str, Any]]:
    """Return the Mongo ``service_category`` match clause for
    ``category`` (``pool`` / ``landscaping`` / ``both``), or
    ``None`` for an unknown value.  Case-insensitive input + output.
    """
    key = (category or "").strip().lower()
    pattern = _PROPERTY_CATEGORY_REGEX.get(key)
    if not pattern:
        return None
    return {"$regex": pattern, "$options": "i"}


async def active_customer_ids_with_category(
    *, db, tenant_id: str, category: str,
) -> List[str]:
    """Ticket V · Feb-2026 — distinct customer_ids who own at
    least one active property whose ``service_category`` matches
    the inclusive rule for ``category``.

    Shared single source of truth between the Dashboard property-
    count tiles (``compute_property_counts``) and the new
    ``/api/customers?property_service_category=X&is_active=true``
    list filter.  Both call-sites consume this helper so the
    aggregator's contributing-customer set and the list filter's
    matched-customer set are provably identical (verified by the
    ``test_customers_property_service_category_filter`` cross-
    check case).

    Returns an empty list when:
      * ``category`` is not one of ``pool`` / ``landscaping`` /
        ``both`` (case-insensitive);
      * no active customers exist for the tenant;
      * no properties match the active + category gate.

    Preserves the active-property gate (``active != False`` + no
    soft-delete) + the active-parent-customer gate baked into
    :func:`active_customer_ids` so divergence vs the aggregator
    is impossible by construction.
    """
    key = (category or "").strip().lower()
    if key not in _PROPERTY_CATEGORY_REGEX:
        return []
    active_cust_ids = await active_customer_ids(
        db=db, tenant_id=tenant_id,
    )
    if not active_cust_ids:
        return []
    sets = await _category_customer_sets(
        db=db, tenant_id=tenant_id, active_cust_ids=active_cust_ids,
    )
    return sorted(sets[key])


async def _category_customer_sets(
    *, db, tenant_id: str, active_cust_ids: List[str],
) -> Dict[str, set]:
    """T296674 - customer ids per category tile.

    The customer profile selector writes ``customers.service_category``
    while the tiles used to read only ``properties.service_category``,
    so most customers never counted.  A customer now counts toward a
    category when EITHER their own ``service_category`` OR any of
    their active properties matches the inclusive rule
    (pool|both / landscaping|both).  ``both`` = customers present in
    both the pool and landscaping sets (so a customer with a pool
    property and a landscaping profile is a Both customer).
    """
    active = set(active_cust_ids)
    base = active_property_match_base(tenant_id)
    base["customer_id"] = {"$in": active_cust_ids}
    out: Dict[str, set] = {}
    for key in ("pool", "landscaping"):
        match = _category_match(key)
        from_props = set(await db.properties.distinct(
            "customer_id", {**base, "service_category": match},
        ))
        from_custs = set(await db.customers.distinct(
            "id",
            {"tenant_id": tenant_id, "id": {"$in": active_cust_ids},
             "service_category": match},
        ))
        out[key] = {c for c in (from_props | from_custs) if c in active}
    out["both"] = out["pool"] & out["landscaping"]
    return out


_PERF_WARN_MS = _PERF_WARN_MS  # (preserve the pre-existing export)



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
    active_cust_ids = await active_customer_ids(
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

    base = active_property_match_base(tenant_id)
    base["customer_id"] = {"$in": active_cust_ids}

    active_accounts = await db.properties.count_documents(base)

    sets = await _category_customer_sets(
        db=db, tenant_id=tenant_id, active_cust_ids=active_cust_ids,
    )
    pool_count = len(sets["pool"])
    landscape_count = len(sets["landscaping"])
    both_count = len(sets["both"])

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
