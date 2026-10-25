"""TD-customers-indexes-and-counts-400 · Feb-2026 — v3 compound indexes.

Adds three compound indexes on the ``customers`` and ``properties``
collections to cover filter paths that the pre-v3 catalogue
leaves on a tenant-partition scan:

    customers:  (tenant_id, service_category)
        — ``?service_category=`` filter on the customers-list hot
          path. The ``service_category`` field is a low-cardinality
          enum (``pool``/``landscaping``/``both``/unset) but the
          predicate scans the entire tenant partition without this
          compound.

    customers:  (tenant_id, created_at DESC, _id DESC)
        — default-sort pagination tiebreaker. Both legs are
          intentionally DESC (not ASC) even though the operator's
          phrasing only specified ``created_at`` direction. The
          DESC-both choice mirrors the pre-existing
          ``customers_tenant_deleted_created_desc_bg`` precedent so
          Mongo's planner picks a forward IXSCAN for the default
          ``sort=created_desc`` walk instead of a reverse-scan on
          an all-ASC compound. For a future reviewer wondering why
          the ``_id`` tiebreaker is also DESC: when two rows share
          the same ``created_at`` (bulk-seeded demo rows, backfill
          imports), tiebreaking by ``_id`` in the same direction as
          the primary sort keeps the walk strictly monotonic — a
          mixed DESC/ASC tiebreaker would force an in-memory sort
          stage on the tie group.

    properties:  (tenant_id, customer_id, active)
        — nested property lookups filter by ``active=True`` after
          joining on ``customer_id``. The v1 compound
          ``perf_customers_properties_tenant_customer`` covers
          ``(tenant_id, customer_id)`` but leaves ``active`` on an
          in-memory filter stage. Extending the compound keeps the
          predicate index-covered end-to-end.

Verify-only (no new index, flagged in result for observability):

    jobs:       (tenant_id, customer_id)      — perf_customers_v1
    invoices:   (tenant_id, customer_id)      — perf_customers_v1

Sentinel key: ``perf_customers_v3``. Lives in ``db.migration_status``
alongside v1 / v2 (repo convention — NOT ``db._migrations``).

Ruled ``must_succeed=False`` at boot — perf polish, not correctness.
Mirrors v2's ruling R1 so a background index-build hiccup records
ERROR on
``/api/health.init.structural_migrations.perf_customers_v3``
without 503'ing ``/health/ready``.

Rollback::

    for name in (
        "perf_customers_v3_tenant_service_category",
        "perf_customers_v3_tenant_created_desc_id",
    ):
        db.customers.drop_index(name)
    db.properties.drop_index(
        "perf_customers_v3_properties_tenant_customer_active"
    )

Idempotent — a second run short-circuits via the sentinel gate; even
if the sentinel is manually cleared, the per-index name check keeps
the create_index calls no-op.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

logger = logging.getLogger("services.migrations.perf_customers_indexes_v3")

MIGRATION_KEY = "perf_customers_v3"


# (collection, [(key, direction), ...], explicit_index_name)
_INDEXES_TO_CREATE: List[Tuple[str, List[Tuple[str, int]], str]] = [
    ("customers",
     [("tenant_id", 1), ("service_category", 1)],
     "perf_customers_v3_tenant_service_category"),
    ("customers",
     [("tenant_id", 1), ("created_at", -1), ("_id", -1)],
     "perf_customers_v3_tenant_created_desc_id"),
    ("properties",
     [("tenant_id", 1), ("customer_id", 1), ("active", 1)],
     "perf_customers_v3_properties_tenant_customer_active"),
]


# (collection, first_key, second_key) — covered by ``perf_customers_v1``.
# Report-only; no index created. Lets ops see v3's coverage audit on
# the migration result dict without accidental duplicate indexes.
_INDEXES_VERIFY_ONLY: List[Tuple[str, str, str]] = [
    ("jobs", "tenant_id", "customer_id"),
    ("invoices", "tenant_id", "customer_id"),
]


async def _has_index_named(coll: Any, name: str) -> bool:
    """True when the collection already has an index with this exact
    name. Idempotency gate for the create-side.
    """
    async for idx in coll.list_indexes():
        if (idx.get("name") or "") == name:
            return True
    return False


async def _has_index_with_prefix(
    coll: Any, first: str, second: str,
) -> bool:
    """True when any index on the collection has the first two keys
    equal to ``(first, second)`` in that order (any direction). Used
    for the verify-only pass against the v1 compounds — if a
    compatible compound exists the collection is marked as covered
    without a second index being written.
    """
    async for idx in coll.list_indexes():
        keys = list((idx.get("key") or {}).items())
        if (len(keys) >= 2
                and keys[0][0] == first
                and keys[1][0] == second):
            return True
    return False


async def run(db: Any) -> Dict[str, Any]:
    """Ensure the v3 compound indexes exist. Sentinel-gated.

    Returns a summary dict mirroring v2's shape, extended with a
    ``verified`` list so the health surface can show which
    collections are already covered by a prior migration::

        {
            "ok": bool,
            "skipped": bool,
            "reason": str | absent,
            "created": int,
            "already": int,
            "verified": List[str],   # jobs/invoices already covered
            "collections": List[str],  # collections actually written to
            "errors": List[Dict[str, str]],
        }
    """
    sentinel = await db.migration_status.find_one(
        {"key": MIGRATION_KEY}, {"_id": 0},
    )
    if sentinel and sentinel.get("completed_at"):
        return {
            "ok": True, "skipped": True,
            "reason": "already_ran",
            "created": 0, "already": 0,
            "verified": [], "collections": [],
        }

    created: List[str] = []
    already: List[str] = []
    verified: List[str] = []
    errors: List[Dict[str, str]] = []

    # ─── Create pass ──────────────────────────────────────────────
    for coll_name, keys, idx_name in _INDEXES_TO_CREATE:
        coll = db[coll_name]
        try:
            if await _has_index_named(coll, idx_name):
                already.append(idx_name)
                continue
            await coll.create_index(keys, name=idx_name, background=True)
            created.append(idx_name)
            logger.info(
                "[perf_customers_v3] created index %s on %s",
                idx_name, coll_name,
            )
        except Exception as e:  # noqa: BLE001
            errors.append({"index": idx_name, "error": str(e)})
            logger.warning(
                "[perf_customers_v3] index create failed on %s: %s",
                idx_name, e,
            )

    # ─── Verify-only pass (jobs / invoices covered by v1) ────────
    for coll_name, first_key, second_key in _INDEXES_VERIFY_ONLY:
        coll = db[coll_name]
        try:
            if await _has_index_with_prefix(coll, first_key, second_key):
                verified.append(coll_name)
                logger.info(
                    "[perf_customers_v3] verified existing "
                    "(%s, %s) prefix on %s",
                    first_key, second_key, coll_name,
                )
            else:
                # Should never happen in a healthy repo (v1 ships
                # these) — surface it so the health probe shows the
                # gap. We deliberately do NOT create the index here
                # (that's v1's job) to keep v3's write surface
                # tightly scoped.
                errors.append({
                    "collection": coll_name,
                    "error": (
                        f"expected ({first_key}, {second_key}) "
                        f"compound missing — run perf_customers_v1"
                    ),
                })
        except Exception as e:  # noqa: BLE001
            errors.append({"collection": coll_name, "error": str(e)})

    await db.migration_status.update_one(
        {"key": MIGRATION_KEY},
        {"$set": {
            "key": MIGRATION_KEY,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "created": created,
            "already": already,
            "verified": verified,
            "errors": errors,
        }},
        upsert=True,
    )

    return {
        "ok": True, "skipped": False,
        "created": len(created),
        "already": len(already),
        "verified": verified,
        "collections": created,
        "errors": errors,
    }
