"""CUSTOMER-RETENTION-ACCOUNT-CORRECTION · Feb-2026 — sentinel-only migration.

The ``customers.account_correction`` field is sparse-safe: both missing
and ``false`` rows pass the exclusion predicate
``{account_correction: {$ne: true}}``.  Therefore we do NOT touch any
existing customer rows — a backfill would be a no-op write that burns
I/O for zero behavioral change.  The migration exists solely to:

  1. Stamp a sentinel row in ``_migrations`` so a future audit can
     confirm the feature's rollout date per tenant pool.
  2. Document (via this docstring) that the field default is implicit
     missing-value → ``false``, and future tooling MUST NOT assume
     the key is present on every doc.

Idempotent — second run returns ``sentinel: "present"``.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict

from config import db


_SENTINEL_ID = "customer_account_correction_v1"
logger = logging.getLogger("customer_account_correction_v1")


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _already_ran() -> bool:
    row = await db["_migrations"].find_one({"id": _SENTINEL_ID})
    return bool(row and row.get("completed_at"))


async def run(*, force: bool = False) -> Dict[str, Any]:
    """Register the sentinel.  No row writes.

    * ``force=True`` re-stamps the ``completed_at`` timestamp (useful
      if an admin wants to pin a re-ship date), but still never
      touches ``customers`` rows.
    * Return shape: ``{"sentinel": "present"|"stamped", "customers": N}``
      where N is the live customers count (observational only, so an
      operator running the script can sanity-check the tenant size
      without a second query).
    """
    if not force and await _already_ran():
        n = await db.customers.estimated_document_count()
        return {"sentinel": "present", "customers": int(n)}
    n = await db.customers.estimated_document_count()
    await db["_migrations"].update_one(
        {"id": _SENTINEL_ID},
        {"$set": {
            "id": _SENTINEL_ID,
            "completed_at": _iso_now(),
            "stats": {"customers_at_rollout": int(n),
                      "backfill": "sentinel-only (sparse-safe field)"},
        }},
        upsert=True,
    )
    logger.info(
        "[migration] customer_account_correction_v1 stamped sentinel; "
        "no customer rows touched (sparse-safe field)",
    )
    return {"sentinel": "stamped", "customers": int(n)}
