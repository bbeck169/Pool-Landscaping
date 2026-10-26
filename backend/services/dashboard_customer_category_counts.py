"""Feb-2026 - Dashboard Pool + Landscaping customer counts.

Two tenant-scoped count helpers consumed by ``GET /api/dashboard``
to drive the new Pool / Landscaping customer tiles.  Both counts
apply the same guardrails the Active Customers tile already uses:

  * ``is_active != False`` - matches True, missing, and null so
    legacy rows that never had ``is_active`` stamped still count.
    Mirrors ``routers/dashboard.py:active_customers_count`` +
    ``models.py:96`` ("Missing/legacy docs read back as True").
  * Soft-deleted rows (``deleted_at`` set) excluded.
  * Case-insensitive match on ``service_category`` so legacy
    documents with ``"Pool"`` / ``"POOL"`` / ``"pool"`` all land in
    the same bucket.

Union semantics (approved in P2 #6, commit ``615339ab5``):
a customer with ``service_category == "both"`` is counted on
BOTH tiles. Mirrors the P2 #6 list filter at
``routers/customers.py`` (``?service_category=pool`` -> union
``{"pool", "both"}``) so the tile count and the deep-linked list
count agree exactly.

The P2 #6 ``dashboard_service_category.py`` endpoint also
publishes per-bucket counts but intentionally does NOT filter by
``is_active`` + ``deleted_at`` (operator-visibility signal, not
an "active roster" count).  These helpers are the authoritative
source for the Active-only Pool / Landscaping customer tiles.
"""
from __future__ import annotations

from typing import Any, Dict


def _active_customer_query(tenant_id: str) -> Dict[str, Any]:
    """Base filter shared with ``routers/dashboard.py``'s
    ``active_customers_count`` scan: tenant-scoped,
    ``is_active != False`` (True + missing + null), not
    soft-deleted. Factored here so the two scans stay in
    lockstep with the Active Customers tile.
    """
    return {
        "tenant_id": tenant_id,
        "$and": [
            {"$or": [
                {"is_active": True},
                {"is_active": None},
                {"is_active": {"$exists": False}},
            ]},
            {"$or": [
                {"deleted_at": {"$exists": False}},
                {"deleted_at": None},
                {"deleted_at": ""},
                {"deleted_at": False},
            ]},
        ],
    }


async def count_pool_customers(*, db, tenant_id: str) -> int:
    """Active, non-deleted customers whose ``service_category`` is
    ``pool`` or ``both`` (case-insensitive match).

    Union semantics — ``both`` customers increment this count AND
    :func:`count_landscaping_customers` so the two tile totals
    overlap on the ``both`` cohort, matching the P2 #6
    ``?service_category=pool`` list filter.
    """
    q = _active_customer_query(tenant_id)
    q["service_category"] = {
        "$regex": r"^(pool|both)$",
        "$options": "i",
    }
    return await db.customers.count_documents(q)


async def count_landscaping_customers(*, db, tenant_id: str) -> int:
    """Active, non-deleted customers whose ``service_category`` is
    ``landscaping`` or ``both`` (case-insensitive match).

    Union semantics — see :func:`count_pool_customers`.
    """
    q = _active_customer_query(tenant_id)
    q["service_category"] = {
        "$regex": r"^(landscaping|both)$",
        "$options": "i",
    }
    return await db.customers.count_documents(q)


async def count_both_customers(*, db, tenant_id: str) -> int:
    """Active, non-deleted customers whose ``service_category`` is
    EXACTLY ``both`` (case-insensitive match).

    Ticket U · Feb-2026 — wired for the "Both Service Customers"
    dashboard tile.  No union semantics on this one: a ``both``
    customer counts here AND on both :func:`count_pool_customers`
    and :func:`count_landscaping_customers`, mirroring the P2 #6
    customer-list filter ``?service_category=both`` which also
    returns ONLY the ``both`` cohort.
    """
    q = _active_customer_query(tenant_id)
    q["service_category"] = {
        "$regex": r"^both$",
        "$options": "i",
    }
    return await db.customers.count_documents(q)
