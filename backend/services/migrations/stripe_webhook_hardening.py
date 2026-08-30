"""Phase B3 · Feb-2026 — Stripe webhook hardening index migration.

Sentinel: ``stripe_webhook_hardening_v1``. Idempotent + sentinel-
guarded. Bootstraps indexes for the new dedup ledger + dead-letter
tables PLUS backfills the missing compound indexes on the existing
``payment_methods`` and ``stripe_charges`` mirror collections
(surfaced in the B3 audit).

Runs on every boot; the sentinel keeps the cost at a single
``migrations.find_one`` lookup after the first successful run.

Indexes created:

    stripe_webhook_events
      • event_id UNIQUE
      • (status, received_at desc) — dead-letter dashboards

    stripe_webhook_dead_letter
      • event_id UNIQUE
      • (resolved, first_failed_at desc) — operator dashboards

    payment_methods
      • (tenant_id, customer_id, is_default)
      • (tenant_id, provider_payment_method_id) UNIQUE

    stripe_charges
      • (tenant_id, customer_id, created_at desc)
      • (tenant_id, invoice_id, status)
      • stripe_payment_intent_id UNIQUE sparse
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from config import db


logger = logging.getLogger("stripe_webhook_hardening_migration")


_SENTINEL_ID = "stripe_webhook_hardening_v1"


async def _sentinel_row() -> Optional[Dict[str, Any]]:
    return await db.migrations.find_one({"id": _SENTINEL_ID}, {"_id": 0})


async def _write_sentinel(summary: Dict[str, Any]) -> None:
    await db.migrations.update_one(
        {"id": _SENTINEL_ID},
        {"$set": {
            "id": _SENTINEL_ID,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "summary": summary,
        }},
        upsert=True,
    )


async def _has_index(coll, name: str) -> bool:
    async for idx in coll.list_indexes():
        if (idx.get("name") or "") == name:
            return True
    return False


async def _create_index_safe(coll, keys, *, name: str, unique: bool = False, sparse: bool = False, summary: Dict[str, Any]) -> None:
    """Create an index if missing. Records +1 in summary on create,
    +1 in ``already_present`` on skip, and +1 error on failure so a
    single failing spec doesn't stop the whole migration."""
    try:
        if await _has_index(coll, name):
            summary["already_present"] += 1
            return
        kwargs: Dict[str, Any] = {"name": name}
        if unique:
            kwargs["unique"] = True
        if sparse:
            kwargs["sparse"] = True
        await coll.create_index(keys, **kwargs)
        summary["indexes_created"] += 1
    except Exception as exc:  # noqa: BLE001
        summary["errors"].append({"index": name, "error": str(exc)[:400]})
        logger.warning("[stripe_webhook_hardening] index %s failed: %s", name, exc)


async def run_stripe_webhook_hardening_migration(*, force: bool = False) -> Dict[str, Any]:
    if not force:
        sentinel = await _sentinel_row()
        if sentinel:
            return {"status": "skipped",
                    "reason": "sentinel_present",
                    "sentinel": sentinel}

    summary: Dict[str, Any] = {
        "collections_touched": [
            "stripe_webhook_events",
            "stripe_webhook_dead_letter",
            "payment_methods",
            "stripe_charges",
        ],
        "indexes_created": 0,
        "already_present": 0,
        "errors": [],
    }

    # 1) stripe_webhook_events — dedup ledger.
    await _create_index_safe(
        db.stripe_webhook_events, [("event_id", 1)],
        name="stripe_webhook_events_event_id_unique", unique=True,
        summary=summary,
    )
    await _create_index_safe(
        db.stripe_webhook_events, [("status", 1), ("received_at", -1)],
        name="stripe_webhook_events_status_idx",
        summary=summary,
    )

    # 2) stripe_webhook_dead_letter — operator retry surface.
    await _create_index_safe(
        db.stripe_webhook_dead_letter, [("event_id", 1)],
        name="stripe_webhook_dead_letter_event_id_unique", unique=True,
        summary=summary,
    )
    await _create_index_safe(
        db.stripe_webhook_dead_letter, [("resolved", 1), ("first_failed_at", -1)],
        name="stripe_webhook_dead_letter_resolved_idx",
        summary=summary,
    )

    # 3) payment_methods — list-per-customer + upsert-by-Stripe-id.
    await _create_index_safe(
        db.payment_methods,
        [("tenant_id", 1), ("customer_id", 1), ("is_default", 1)],
        name="payment_methods_tenant_customer_default_idx",
        summary=summary,
    )
    await _create_index_safe(
        db.payment_methods,
        [("tenant_id", 1), ("provider_payment_method_id", 1)],
        name="payment_methods_tenant_pm_unique", unique=True,
        summary=summary,
    )

    # 4) stripe_charges — charge history + invoice lookups.
    await _create_index_safe(
        db.stripe_charges,
        [("tenant_id", 1), ("customer_id", 1), ("created_at", -1)],
        name="stripe_charges_tenant_customer_created_idx",
        summary=summary,
    )
    await _create_index_safe(
        db.stripe_charges,
        [("tenant_id", 1), ("invoice_id", 1), ("status", 1)],
        name="stripe_charges_tenant_invoice_status_idx",
        summary=summary,
    )
    await _create_index_safe(
        db.stripe_charges, [("stripe_payment_intent_id", 1)],
        name="stripe_charges_pi_unique", unique=True, sparse=True,
        summary=summary,
    )

    await _write_sentinel(summary)
    logger.info(
        "[stripe_webhook_hardening] indexes_created=%s already_present=%s errors=%s",
        summary["indexes_created"], summary["already_present"], len(summary["errors"]),
    )
    return {"status": "ok", "summary": summary}
