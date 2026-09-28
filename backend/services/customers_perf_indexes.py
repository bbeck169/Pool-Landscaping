"""SEARCH-SPEED · Feb-2026 — Customers-list soft-delete-aware compound
indexes.

Motivation
──────────
The pre-existing ``perf_customers_v2_*`` catalogue ships compounds
keyed by ``(tenant_id, <sort_field>, _id)`` — great for the sort
axis, but the customers-list handler ALSO filters every query by
``deleted_at: null`` (HD-A soft-delete rail).  Because
``deleted_at`` isn't in any existing index prefix, Mongo's planner
falls back to either:

  * an in-memory ``SORT`` stage after a tenant partition scan
    (``indexName=None`` in ``executionStats``); or
  * a compound that carries ``deleted_at`` in a NON-prefix
    position (``customers_dashboard_active_inactive_idx``) — which
    it can't use for equality unless the earlier keys were also
    equalized in the query.

Both cases waste work at 2k+ customers per tenant.  This module
adds five compound indexes that put ``deleted_at`` at position 2,
right after ``tenant_id``, so the equality on ``deleted_at``
scopes the range scan BEFORE the sort key kicks in:

    (tenant_id, deleted_at, created_at DESC, _id DESC)
        default ``created_desc`` sort + pagination tiebreaker.

    (tenant_id, deleted_at, updated_at DESC)
        for ``sort=updated_desc`` (future-proofing per SEARCH-SPEED
        brief; the handler doesn't currently expose this sort but
        several ops probes filter-then-sort by updated_at so the
        index is cheap insurance).

    (tenant_id, deleted_at, name)
        ``name_asc`` / ``name_desc`` (walk in either direction).

    (tenant_id, deleted_at, email)   → exact-match email lookups.
    (tenant_id, deleted_at, phone)   → exact-match phone lookups.

Contract
────────
Idempotent — ``create_indexes`` no-ops when the same name + key
spec already exists.  All five carry ``background=True`` so an
online build against a hot production collection never blocks
writes.  Errors are swallowed with a WARN log — a bad index
should NEVER wedge boot.

Public
──────
``ensure_customers_perf_indexes(db)`` — call once at startup.
``INDEX_NAMES`` — greppable list for rollback / audit.

Rollback::

    for name in ensure_customers_perf_indexes.INDEX_NAMES:
        db.customers.drop_index(name)
"""
from __future__ import annotations

import logging
from typing import Any, List

from pymongo import ASCENDING, DESCENDING, IndexModel


logger = logging.getLogger("services.customers_perf_indexes")


# Greppable catalogue — each entry is (name, key_spec).
_INDEXES: List[tuple[str, list]] = [
    (
        "customers_tenant_deleted_created_desc_bg",
        [("tenant_id", ASCENDING), ("deleted_at", ASCENDING),
         ("created_at", DESCENDING), ("_id", DESCENDING)],
    ),
    (
        "customers_tenant_deleted_updated_desc_bg",
        [("tenant_id", ASCENDING), ("deleted_at", ASCENDING),
         ("updated_at", DESCENDING)],
    ),
    (
        "customers_tenant_deleted_name_bg",
        [("tenant_id", ASCENDING), ("deleted_at", ASCENDING),
         ("name", ASCENDING), ("_id", ASCENDING)],
    ),
    (
        "customers_tenant_deleted_email_bg",
        [("tenant_id", ASCENDING), ("deleted_at", ASCENDING),
         ("email", ASCENDING)],
    ),
    (
        "customers_tenant_deleted_phone_bg",
        [("tenant_id", ASCENDING), ("deleted_at", ASCENDING),
         ("phone", ASCENDING)],
    ),
]


INDEX_NAMES: tuple[str, ...] = tuple(name for name, _ in _INDEXES)


async def ensure_customers_perf_indexes(db: Any) -> dict:
    """Create the five compound indexes if missing.  Idempotent.

    Returns a summary dict for observability::

        {"created": [name, ...], "already": [name, ...],
         "errors": [{"index": name, "error": str}, ...]}
    """
    summary: dict[str, list] = {
        "created": [], "already": [], "errors": [],
    }
    existing: set[str] = set()
    try:
        async for idx in db.customers.list_indexes():
            existing.add(idx.get("name") or "")
    except Exception as exc:                                     # noqa: BLE001
        logger.warning(
            "[customers_perf_indexes] list_indexes failed: %s", exc,
        )

    to_create: list[IndexModel] = []
    to_create_names: list[str] = []
    for name, keys in _INDEXES:
        if name in existing:
            summary["already"].append(name)
            continue
        to_create.append(IndexModel(keys, name=name, background=True))
        to_create_names.append(name)

    if to_create:
        try:
            await db.customers.create_indexes(to_create)
            summary["created"].extend(to_create_names)
            logger.info(
                "[customers_perf_indexes] created=%s already=%s",
                summary["created"], summary["already"],
            )
        except Exception as exc:                                 # noqa: BLE001
            # Batch failed — fall back to one-by-one so a single
            # bad index doesn't block the others.
            logger.warning(
                "[customers_perf_indexes] batch create failed (%s) "
                "— falling back to per-index create",
                exc,
            )
            for name, keys in _INDEXES:
                if name in existing:
                    continue
                try:
                    await db.customers.create_index(
                        keys, name=name, background=True,
                    )
                    summary["created"].append(name)
                except Exception as sub:                         # noqa: BLE001
                    summary["errors"].append(
                        {"index": name, "error": str(sub)},
                    )
                    logger.warning(
                        "[customers_perf_indexes] %s failed: %s",
                        name, sub,
                    )
    else:
        logger.info(
            "[customers_perf_indexes] all indexes already present: %s",
            summary["already"],
        )
    return summary
