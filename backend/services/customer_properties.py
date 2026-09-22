"""Phase P33 · Feb-2026 — Shared customer-property validator.

Two-function surface, tenant-scoped, no side-effects. Both are
``async`` because ``db.customers`` and ``db.properties`` are
Motor collections.

.. note::
   ``routers/jobs.py`` currently ships an INLINE
   :func:`~routers.jobs._resolve_property_for_job` helper that
   emits HTTP 422 with codes ``property_tenant_mismatch`` /
   ``property_customer_mismatch``. That contract predates P33 and
   is consumed by existing frontend surfaces + tests; forcibly
   flipping it to the P33 shape (400 + ``property_not_on_customer``
   / ``customer_has_no_properties``) would regress those callers.
   The P33 helpers below are used by ``routers/recurring_jobs.py``
   in isolation. Unifying the two contracts is deferred — a
   coordinated FE + test update is required first.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import HTTPException

from config import db


logger = logging.getLogger("customer_properties")


async def validate_property_belongs_to_customer(
    tenant_id: str,
    customer_id: str,
    property_id: str,
) -> Dict[str, Any]:
    """Fail closed if ``property_id`` isn't owned by ``customer_id``
    under ``tenant_id``.

    Raises
    ------
    HTTPException(404)
        The ``property_id`` doesn't exist in ``tenant_id`` (unknown
        id OR belongs to another tenant — treated identically so a
        caller can't enumerate cross-tenant property ids).
    HTTPException(400)
        The property exists in this tenant but belongs to a
        DIFFERENT customer — detail carries ``code:
        "property_not_on_customer"`` for the FE to key on.

    Returns
    -------
    dict
        The tenant-scoped property doc (minus ``_id``) on success —
        callers that need the property record for downstream stamp
        (e.g. denorm the label) get it in the same round trip.
    """
    if not (tenant_id and customer_id and property_id):
        # Guard-rail: any of the three missing is a caller bug.
        raise HTTPException(
            400,
            {"code": "invalid_property_lookup",
              "message": ("tenant_id, customer_id, and property_id "
                          "are all required")},
        )
    prop = await db.properties.find_one(
        {"id": property_id, "tenant_id": tenant_id},
        {"_id": 0},
    )
    if not prop:
        raise HTTPException(
            404,
            {"code": "property_not_found",
              "message": "property_id does not resolve"},
        )
    if prop.get("customer_id") != customer_id:
        raise HTTPException(
            400,
            {"code": "property_not_on_customer",
              "message": "property_id belongs to a different customer"},
        )
    return prop


async def get_active_properties_for_customer(
    tenant_id: str,
    customer_id: str,
) -> List[Dict[str, Any]]:
    """Return the tenant-scoped active property list for a customer,
    sorted by ``sort_order`` (nulls last).

    "Active" means ``active`` field is not explicitly ``False`` and
    the doc isn't soft-deleted (``deleted_at`` unset). Matches the
    filter the ``GET /customers/{cid}/properties`` endpoint applies.
    """
    if not (tenant_id and customer_id):
        return []
    cursor = db.properties.find(
        {"customer_id": customer_id, "tenant_id": tenant_id,
          "active": {"$ne": False},
          "$or": [
              {"deleted_at": {"$exists": False}},
              {"deleted_at": None},
          ]},
        {"_id": 0},
    )
    rows: List[Dict[str, Any]] = []
    async for r in cursor:
        rows.append(r)
    # Stable sort — primary rows (sort_order=0) first, then by
    # created_at asc as a tiebreaker.
    rows.sort(key=lambda r: (
        r.get("sort_order") if r.get("sort_order") is not None else 999,
        r.get("created_at") or "",
    ))
    return rows


async def resolve_recurring_property_payload(
    tenant_id: str,
    customer_id: str,
    property_id: Optional[str],
    *,
    context: str = "recurring_job",
) -> Optional[str]:
    """P33 · Feb-2026 — Server-side normalization of the (customer,
    property) pair for the recurring-jobs router.

    Applies the P33 defense-in-depth ladder:

    * ``property_id`` supplied → validate against
      ``validate_property_belongs_to_customer`` and return the
      original id on success.
    * ``property_id`` empty AND customer has EXACTLY ONE active
      property → auto-fill with that property's id (log INFO with
      the ``context`` tag so ops can trace stale-FE calls).
    * ``property_id`` empty AND customer has 2+ properties →
      HTTP 400 ``property_required``.
    * ``property_id`` supplied AND customer has 0 properties →
      HTTP 400 ``customer_has_no_properties``.

    Returns the effective ``property_id`` (possibly auto-filled)
    or ``None`` when the customer has zero properties AND no
    ``property_id`` was supplied (legacy path — recurring templates
    predating properties can still exist).
    """
    props = await get_active_properties_for_customer(tenant_id, customer_id)
    if not property_id:
        if len(props) == 1:
            auto = props[0]["id"]
            logger.info(
                "[p33] auto-filled property_id=%s for customer=%s "
                "(context=%s) — FE may be stale",
                auto, customer_id, context,
            )
            return auto
        if len(props) >= 2:
            raise HTTPException(
                400,
                {"code": "property_required",
                  "message": ("This customer has multiple "
                              "properties — pick one before "
                              "saving.")},
            )
        # Zero properties AND no property_id → legacy allow-through.
        return None

    # property_id supplied.
    if not props:
        raise HTTPException(
            400,
            {"code": "customer_has_no_properties",
              "message": ("This customer has no addresses on file. "
                          "Add an address before scheduling.")},
        )
    # Validate ownership. Raises 404 / 400 per the helper.
    await validate_property_belongs_to_customer(
        tenant_id, customer_id, property_id,
    )
    return property_id
