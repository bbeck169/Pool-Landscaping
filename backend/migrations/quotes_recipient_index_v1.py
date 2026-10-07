"""LEAD-CREATE-QUOTE · Feb-2026 — quotes ``recipient_type`` index.

Phase-2 Quote-to-Lead Recipient (Feb-2026) shipped a polymorphic
``(recipient_type, recipient_id)`` pair on ``db.quotes`` so quotes
can be addressed to a Lead OR a Customer without materialising a
customer row.  Phase B of LEAD-CREATE-QUOTE adds:

  * A per-lead quote-count badge on the Lead Detail "Create Quote"
    button — ``GET /leads/{lid}`` runs
    ``db.quotes.count_documents({tenant_id, recipient_type:"lead",
    recipient_id:<lid>})`` once per detail page load.
  * A close-won reparent that calls
    ``db.quotes.update_many({tenant_id, recipient_type:"lead",
    recipient_id:<lid>}, …)`` to flip every lead-recipient quote
    (and invoice — ``db.quotes`` holds both doc_types) onto the new
    customer.

Both are hot paths once the feature ships.  This migration seeds the
compound ``(tenant_id, recipient_type, recipient_id)`` index so they
run in O(log n) instead of a full-collection scan.

Partial filter ``{"recipient_id": {"$exists": True}}`` grandfather-
excludes the oldest legacy quotes written before Phase-2 (those
rows carry only the pre-polymorphic ``customer_id``; the Phase-2
backfill script ``scripts/backfill_quote_recipient_type.py`` seeds
them with ``recipient_type="customer"`` + ``recipient_id=customer_id``
in a separate pass).  Partial indexes keep the catalogue slim on
multi-tenant deployments and make the index usable immediately
even if a tenant hasn't yet been through the Phase-2 backfill.

Idempotent — ``create_index`` on an existing identical spec is a
safe Mongo no-op; the sentinel row in ``_migrations`` tracks the
rollout date per deployment so a future audit can confirm the
feature's ship window without re-running the (cheap) index touch.

Running a second time:
  * ``already_ran`` → ``{"created": False, "sentinel": "present"}``
  * ``force=True`` → re-stamps the sentinel but still only touches
                     the index catalogue (which is a no-op on an
                     already-identical spec).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict

from config import db


_SENTINEL_ID = "quotes_recipient_index_v1"
_INDEX_NAME = "tenant_recipient"
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
    ``quotes.(tenant_id, recipient_type, recipient_id)`` and stamp
    the ``_migrations`` sentinel.

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
            [("tenant_id", 1), ("recipient_type", 1),
             ("recipient_id", 1)],
            name=_INDEX_NAME,
            partialFilterExpression={"recipient_id": {"$exists": True}},
        )
        created = True
    except Exception as exc:
        # An index with the same NAME but a different spec/filter
        # already exists — surface a warning but let the sentinel
        # stamp so operators have a single place to track the ship
        # date.  Rebuild path (drop + recreate) stays an admin
        # operation, not a migration-time surprise.
        logger.warning(
            "[migration] %s create_index failed (likely spec mismatch "
            "on existing name): %s", _SENTINEL_ID, exc,
        )
        created = False

    stats = {"created": created, "name": _INDEX_NAME}
    await _mark_complete(stats)
    logger.info("[migration] %s %s", _SENTINEL_ID, stats)
    return {"created": created, "sentinel": "stamped",
            "name": _INDEX_NAME}
