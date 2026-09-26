"""CUS-perf · Feb-2026 — Customers-list sort-path compound indexes.

Adds three compound indexes on the ``customers`` collection so the
Customers-list page's paginated list endpoint (``GET /api/customers``)
serves its sort surface via IXSCAN instead of an in-memory ``$sort``
stage:

    * ``(tenant_id, created_at, _id)`` — default sort (``created_desc``)
      and the mirrored ``created_asc`` variant. All-ASC so MongoDB
      walks the compound B-tree in either direction.
    * ``(tenant_id, last_name, first_name, _id)`` — mirrors the
      ``last_name_asc`` sort's key tuple. The frontend routes that
      sort through the ``_k49_lastname_pipeline`` aggregation (for
      nulls-last + last-space fallback), so the win here is on the
      aggregation planner's ``$sort`` stage where applicable.
    * ``(tenant_id, name, _id)`` — ``name_asc`` and ``name_desc``.

Sentinel key: ``perf_customers_v2``. Distinct from
``perf_customers_v1`` — v1 ships COMPOUND indexes on the tenant-
scoped foreign collections (``jobs`` / ``invoices`` / ``payments`` /
``customer_notes`` / ``properties``) keyed by ``(tenant_id,
customer_id, created_at)`` for the customer-detail tabs. v2 lives
on the ``customers`` collection itself and services the LIST page's
sort surface. Sentinels + index-name catalogues are fully
independent so a rollback of one has zero effect on the other.

Ruled ``must_succeed=False`` at boot (see server.py) — perf polish,
not correctness. A background index-build hiccup records ERROR on
``/api/health.init.structural_migrations.perf_customers_v2`` but
never 503s ``/health/ready`` and never crashes boot.

Rollback::

    for name in ("perf_customers_v2_tenant_created",
                 "perf_customers_v2_tenant_lastname_firstname",
                 "perf_customers_v2_tenant_name"):
        db.customers.drop_index(name)

Idempotent — a second run reports 0 created via the sentinel gate.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Tuple

logger = logging.getLogger("services.migrations.perf_customers_indexes_v2")

MIGRATION_KEY = "perf_customers_v2"

# (collection, [(key, direction), ...], explicit_index_name)
#
# Explicit names (not composed via a suffix like v1) because all three
# indexes live on the ``customers`` collection — auto-composing would
# produce awkward doubled names (``perf_customers_customers_...``).
# Names are versioned + greppable so a future v3 refactor can drop
# them by exact match.
_INDEXES: List[Tuple[str, List[Tuple[str, int]], str]] = [
    ("customers",
     [("tenant_id", 1), ("created_at", 1), ("_id", 1)],
     "perf_customers_v2_tenant_created"),
    ("customers",
     [("tenant_id", 1), ("last_name", 1), ("first_name", 1), ("_id", 1)],
     "perf_customers_v2_tenant_lastname_firstname"),
    ("customers",
     [("tenant_id", 1), ("name", 1), ("_id", 1)],
     "perf_customers_v2_tenant_name"),
]


async def _has_index_matching_first_two_keys(
    coll: Any, first: str, second: str,
) -> bool:
    """True when the collection already has an index whose FIRST two
    key names are ``(first, second)`` in that order (any direction).

    Safety net for reruns / manual index provisioning — if an
    operator has already dropped in a compatible compound (e.g. an
    older ``customers_tenant_created_bg`` from a hand-run script),
    we do NOT double-create. Mirrors v1's helper verbatim.
    """
    async for idx in coll.list_indexes():
        keys = list((idx.get("key") or {}).items())
        if len(keys) >= 2 and keys[0][0] == first and keys[1][0] == second:
            return True
    return False


async def run(db: Any) -> Dict[str, Any]:
    """Ensure the CUS-perf v2 compound indexes exist. Sentinel-gated.

    Returns a summary dict with the same shape as
    ``perf_customers_indexes.run`` (v1) so the wrapper /
    /api/health surface can consume both without special-casing::

        {
            "ok": bool,
            "skipped": bool,
            "reason": str | absent,
            "created": int,
            "already": int,
            "collections": List[str],     # collections actually written to
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
            "collections": [],
        }

    created: List[str] = []
    already: List[str] = []
    errors: List[Dict[str, str]] = []
    for coll_name, keys, idx_name in _INDEXES:
        coll = db[coll_name]
        try:
            if await _has_index_matching_first_two_keys(
                coll, keys[0][0], keys[1][0],
            ):
                already.append(idx_name)
                continue
            await coll.create_index(keys, name=idx_name, background=True)
            created.append(idx_name)
            logger.info(
                "[perf_customers_v2] created index %s on %s",
                idx_name, coll_name,
            )
        except Exception as e:  # noqa: BLE001
            errors.append({"index": idx_name, "error": str(e)})
            logger.warning(
                "[perf_customers_v2] index create failed on %s: %s",
                idx_name, e,
            )

    from datetime import datetime, timezone
    await db.migration_status.update_one(
        {"key": MIGRATION_KEY},
        {"$set": {"key": MIGRATION_KEY,
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                    "created": created, "already": already,
                    "errors": errors}},
        upsert=True,
    )
    return {
        "ok": True, "skipped": False,
        "created": len(created), "already": len(already),
        "collections": created,
        "errors": errors,
    }
