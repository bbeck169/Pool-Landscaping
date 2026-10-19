"""TD-80 · Feb-2026 — Shared active-account/active-property predicate.

Single source of truth for "what counts as an active account /
active property" across the two call-sites that drive the admin
dashboard property-count tiles + the Properties list page:

  * ``services/dashboard_property_category_counts.compute_property_counts``
    — produces the dashboard tile counts via ``count_documents``.
  * ``routers/properties.list_properties`` — produces the row list
    behind the dashboard-tile deep-link ``/properties?is_active=true``.

Prior to TD-80 both call-sites had their own copies of the gate
and they drifted apart on the LIST side: ``list_properties`` used
a two-pass ``.to_list(limit*4)`` prelim + Python parent-customer
gate, which silently truncated when the property-level prelim
exceeded the ``limit*4`` cap.  See
``/app/memory/td80_active_accounts_audit.md`` for the full
root-cause analysis.

Ruling (locked, carried over from the P2 #6 dispatch):

    An "active property" is one where ALL of:
      * ``property.active != False`` — matches True + missing + null
        ("active by default" semantics).
      * ``property.deleted_at`` is missing or None.
      * The parent ``customer.is_active != False``.
      * The parent ``customer.deleted_at`` is missing or None.

    A ``customer.is_muted == True`` row does NOT disqualify its
    properties — mute is a comms-suppression signal, NOT an
    account-deactivation signal.

Both call-sites consume this module through the public helpers
below; nothing else in the backend reads these predicates
directly.  If a future consumer joins (e.g., a CSV export, a
customer-success dashboard, a mobile list endpoint), route it
through here so the ruling stays single-sourced.
"""
from __future__ import annotations

from typing import Any, Dict, List


def active_customer_filter(tenant_id: str) -> Dict[str, Any]:
    """Mongo filter dict for customers that count as "still active":

        tenant-scoped + ``is_active != False`` + no soft-delete.

    Preserves the "active by default" semantics (``is_active``
    missing or ``None`` passes the gate) that every pre-TD-80
    call-site already used.
    """
    return {
        "tenant_id": tenant_id,
        "$and": [
            {"$or": [{"is_active": True},
                      {"is_active": None},
                      {"is_active": {"$exists": False}}]},
            {"$or": [{"deleted_at": {"$exists": False}},
                      {"deleted_at": None}]},
        ],
    }


def active_property_match_base(tenant_id: str) -> Dict[str, Any]:
    """Mongo filter dict for properties whose own fields pass the
    active gate (property-level half of the predicate):

        tenant-scoped + ``active != False`` + no soft-delete.

    The parent-customer half must be AND-ed on top via
    ``customer_id: {"$in": active_customer_ids(...)}`` (do the
    customer-id resolution in a single round-trip BEFORE the
    properties query so Mongo evaluates the full gate in one
    pass — see TD-80 audit for why the two-pass Python version
    silently truncated).
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


async def active_customer_ids(*, db: Any, tenant_id: str) -> List[str]:
    """Return the list of ``customer.id`` values whose row still
    passes :func:`active_customer_filter`.

    Used as the ``$in`` source on the properties query so the
    parent-customer gate becomes part of the Mongo filter instead
    of a post-fetch Python filter.  Call once per request; keep
    the resulting list in local scope for all downstream property
    queries that need the same gate.

    Preserves ordering only insofar as Mongo yields it — callers
    treat this as a set.
    """
    cursor = db.customers.find(
        active_customer_filter(tenant_id),
        {"_id": 0, "id": 1},
    )
    return [c["id"] async for c in cursor if c.get("id")]
