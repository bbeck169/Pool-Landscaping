"""TD-93 · Feb-2026 — ``quotes.due_date`` compound index.

The TD-93 ship adds a ``date_field=due_date`` branch to
``GET /quotes?doc_type=invoice`` so operators can scope the Invoices
list to invoices falling due in a specific window.  Without a
compound index the Mongo range scan degenerates into a full-tenant
scan on large tenants (the existing compound indexes cover
``tenant_id + doc_type + {payment_status | customer_id | created_at}``
but not ``due_date``).

This migration seeds the ``tenant_id + doc_type + due_date``
compound so the range-on-due-date predicate runs in O(log n) under
the same TD-93 branch.  ``created_at`` is already covered by the
TD-K21 ``k21_quotes_tenant_customer_doctype_created`` + sibling
compounds — no new index needed on that field.

Partial filter ``{"doc_type": "invoice"}`` keeps the index slim —
quote docs never consume the ``date_field=due_date`` branch (no FE
surface sends that param for quotes).

Idempotent — ``create_index`` on an existing identical spec is a
safe Mongo no-op; the sentinel row in ``_migrations`` tracks the
rollout date per deployment.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict

from config import db


_SENTINEL_ID = "quotes_due_date_index_v1"
_INDEX_NAME = "tenant_doctype_due_date"
logger = logging.getLogger(_SENTINEL_ID)


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _already_ran() -> bool:
    row = await db["_migrations"].find_one({"id": _SENTINEL_ID})
    return bool(row and row.get("completed_at"))


async def _mark_complete(stats: Dict[str, Any]) -> None:
    await db["_migrations"].update_one(
        {"id": _SENTINEL_ID},
        {"$set": {
            "id": _SENTINEL_ID,
            "completed_at": _iso_now(),
            "stats": stats,
        }},
        upsert=True,
    )


async def run(*, force: bool = False) -> Dict[str, Any]:
    """Create the compound index on
    ``quotes.(tenant_id, doc_type, due_date)`` and stamp the
    ``_migrations`` sentinel.

    * ``force=True`` re-stamps the sentinel but does NOT drop +
      recreate the index — ``create_index`` on an already-identical
      spec is a safe no-op in Mongo so re-running is cheap.
    * Return shape: ``{"created": True|False, "sentinel":
      "stamped"|"present", "name": <index name>}``.
    """
    if not force and await _already_ran():
        return {"created": False, "sentinel": "present",
                "name": _INDEX_NAME}

    try:
        await db.quotes.create_index(
            [("tenant_id", 1), ("doc_type", 1), ("due_date", 1)],
            name=_INDEX_NAME,
            partialFilterExpression={"doc_type": "invoice"},
        )
        created = True
    except Exception as exc:
        logger.warning(
            "[migration] %s create_index failed (likely spec mismatch "
            "on existing name): %s", _SENTINEL_ID, exc,
        )
        created = False

    await _mark_complete({"index_name": _INDEX_NAME, "created": created})
    return {"created": created, "sentinel": "stamped", "name": _INDEX_NAME}
