"""QuickBooks cleanup · Feb 2026.

QuickBooks integration was fully retired in favor of Stripe as the
sole payment processor. This module ships:

* An idempotent boot-time migration that ``$unset``s any lingering
  ``qb_*`` fields from ``tenants``, ``customers``, ``quotes``
  (invoices), and ``payments``. Safe to run every boot — logs the
  number of docs it actually touched.
* An admin-only, ``ALLOW_TEST_HOOKS=1``-gated endpoint
  ``POST /api/dev/quickbooks-purge`` that drops the ``quickbooks_*``
  auxiliary collections on demand.

Grep-clean by design — this file is the sole place the string
"quickbooks" appears in the backend after cleanup.
"""
from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException

from config import db, logger
from utils import require_admin

router = APIRouter()

# ────── Field / collection catalogues for the cleanup
_QB_FIELDS = {
    "tenants": [
        "qb_customer_id", "qb_invoice_id", "qb_payment_id",
        "qb_last_sync_at", "qb_realm_id", "qb_access_token",
        "qb_refresh_token", "quickbooks_enabled",
        "quickbooks_connected_at",
    ],
    "customers": ["qb_customer_id", "qb_last_sync_at"],
    "quotes": ["qb_invoice_id", "qb_last_sync_at"],
    "payments": ["qb_payment_id", "qb_last_sync_at"],
}
_QB_COLLECTIONS = [
    "quickbooks_sync_log", "quickbooks_webhook_events",
    "quickbooks_tokens", "quickbooks_oauth_state",
]


async def run_migration() -> dict:
    """Boot-time idempotent ``$unset`` sweep. Returns a per-collection
    modified-count dict — usually all zeros after the first run."""
    summary: dict = {}
    for coll, fields in _QB_FIELDS.items():
        unset = {f: "" for f in fields}
        # Match docs where at least one of the target fields exists.
        or_clauses = [{f: {"$exists": True}} for f in fields]
        try:
            res = await db[coll].update_many(
                {"$or": or_clauses}, {"$unset": unset},
            )
            summary[coll] = res.modified_count
        except Exception as exc:
            logger.warning(f"[qb-cleanup] {coll} unset skipped: {exc}")
            summary[coll] = -1
    total = sum(v for v in summary.values() if v > 0)
    if total > 0:
        logger.info(f"[qb-cleanup] boot migration cleaned qb_* fields: {summary}")
    return summary


if os.getenv("ALLOW_TEST_HOOKS") == "1":

    @router.post("/dev/quickbooks-purge")
    async def purge_quickbooks_collections(user: dict = Depends(require_admin)):
        """Drop the auxiliary QuickBooks collections on demand. Only
        reachable when ``ALLOW_TEST_HOOKS=1`` so production tenants
        can't accidentally wipe historical audit trails."""
        dropped: dict = {}
        for coll in _QB_COLLECTIONS:
            try:
                await db[coll].drop()
                dropped[coll] = "dropped"
            except Exception as exc:
                dropped[coll] = f"skipped: {exc}"
        return {"ok": True, "dropped": dropped}
