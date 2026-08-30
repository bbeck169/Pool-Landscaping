"""Phase B4 follow-up · Feb-2026 — Backfill price enrichment on
existing ``stripe_subscriptions`` rows.

Sentinel: ``stripe_subscriptions_price_enrichment_v1``.

For each row missing ``price_product_name`` (created before the
enrichment shipped, or ingested via the pre-B4 backfill import),
resolve the Stripe Price by id (with product expanded) and stamp
the 5 enriched fields on the mirror. Rate-limited to ~5 requests
per second to avoid hammering Stripe.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict

from config import db


logger = logging.getLogger("stripe_subscriptions_price_enrichment_migration")


_SENTINEL_ID = "stripe_subscriptions_price_enrichment_v1"
_RATE_LIMIT_SLEEP_SEC = 0.2  # ~5 req/s


async def _sentinel_row() -> Dict[str, Any] | None:
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


async def run_stripe_subscriptions_price_enrichment(*, force: bool = False) -> Dict[str, Any]:
    if not force:
        if await _sentinel_row():
            return {"status": "skipped", "reason": "sentinel_present"}

    # Lazy import so the tests that stub the Stripe SDK still work.
    from services.payments.stripe_subscription import _enrich_price_from_id

    summary: Dict[str, Any] = {
        "scanned": 0,
        "enriched": 0,
        "already_enriched": 0,
        "no_price_id": 0,
        "errors": [],
    }

    cursor = db.stripe_subscriptions.find(
        {"$or": [
            {"price_product_name": {"$exists": False}},
            {"price_product_name": None},
        ]},
        {"_id": 0, "stripe_subscription_id": 1, "price_id": 1, "tenant_id": 1},
    )
    async for row in cursor:
        summary["scanned"] += 1
        pid = row.get("price_id")
        if not pid:
            summary["no_price_id"] += 1
            continue
        try:
            enriched = await _enrich_price_from_id(pid)
        except Exception as exc:  # noqa: BLE001
            summary["errors"].append(
                {"sub": row.get("stripe_subscription_id"), "error": str(exc)[:400]},
            )
            continue
        if not enriched or not enriched.get("price_product_name"):
            # Price no longer resolvable (archived / deleted). Skip.
            summary["errors"].append(
                {"sub": row.get("stripe_subscription_id"), "error": "unresolvable"},
            )
            continue
        await db.stripe_subscriptions.update_one(
            {"stripe_subscription_id": row["stripe_subscription_id"]},
            {"$set": enriched},
        )
        summary["enriched"] += 1
        # Rate-limit so a huge backfill doesn't hammer Stripe.
        await asyncio.sleep(_RATE_LIMIT_SLEEP_SEC)

    await _write_sentinel(summary)
    logger.info(
        "[stripe_subscriptions_price_enrichment] scanned=%s enriched=%s errors=%s",
        summary["scanned"], summary["enriched"], len(summary["errors"]),
    )
    return {"status": "ok", "summary": summary}
