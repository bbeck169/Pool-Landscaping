"""Startup-time idempotent index creation.

Motor's ``create_index`` / ``create_indexes`` is idempotent — calling it
with the same spec on an existing index is a fast no-op. That means we
can safely re-run this on every boot.

Naming policy: give every index an explicit ``name`` so migrations are
observable (`db.<coll>.getIndexes()` shows a semantic name instead of
Mongo's auto-derived one).

Deployment audit (Phase 58.a follow-up) surfaced these missing indexes:

  * ``stripe_events.event_id`` — unique. Backstops the idempotency
    guard on the Stripe webhook (find-then-insert had a race window).
  * ``notifications.(tenant_id, user_id, created_at DESC)`` — read
    optimization for the bell dropdown poll. NOT unique.
  * ``budgets.(tenant_id, year)`` — unique. Prevents duplicate
    per-tenant budget rows.
"""
from __future__ import annotations

from pymongo import ASCENDING, DESCENDING

from config import db, logger


async def ensure_deployment_indexes() -> None:
    """Idempotent — safe to call on every boot."""
    plans = [
        ("stripe_events",
         [("event_id", ASCENDING)],
         {"unique": True, "name": "uniq_event_id", "background": True}),
        ("notifications",
         [("tenant_id", ASCENDING), ("user_id", ASCENDING), ("created_at", DESCENDING)],
         {"name": "tenant_user_created_desc", "background": True}),
        ("budgets",
         [("tenant_id", ASCENDING), ("year", ASCENDING)],
         {"unique": True, "name": "uniq_tenant_year", "background": True}),
        # Marketing M1 · Feb 2026 — subscribers, lists, segments, memberships.
        ("subscribers",
         [("tenant_id", ASCENDING), ("email", ASCENDING)],
         {"name": "sub_tenant_email", "background": True,
          "sparse": True}),
        ("subscribers",
         [("tenant_id", ASCENDING), ("phone", ASCENDING)],
         {"name": "sub_tenant_phone", "background": True,
          "sparse": True}),
        ("subscribers",
         [("tenant_id", ASCENDING), ("status", ASCENDING),
          ("created_at", DESCENDING)],
         {"name": "sub_tenant_status_created", "background": True}),
        ("marketing_lists",
         [("tenant_id", ASCENDING), ("slug", ASCENDING)],
         {"unique": True, "name": "uniq_tenant_list_slug", "background": True}),
        ("marketing_segments",
         [("tenant_id", ASCENDING), ("slug", ASCENDING)],
         {"unique": True, "name": "uniq_tenant_segment_slug", "background": True}),
        ("marketing_list_memberships",
         [("tenant_id", ASCENDING), ("list_id", ASCENDING),
          ("subscriber_id", ASCENDING)],
         {"unique": True, "name": "uniq_tenant_list_sub", "background": True}),
        # QuoteIQ Phase Q1 · Feb 2026
        ("ai_credit_transactions",
         [("tenant_id", ASCENDING), ("created_at", DESCENDING)],
         {"name": "ai_credit_tenant_created", "background": True}),
        ("chemical_usage_events",
         [("tenant_id", ASCENDING), ("customer_id", ASCENDING),
          ("occurred_at", DESCENDING)],
         {"name": "chem_usage_tenant_customer_time", "background": True}),
        ("chemical_usage_events",
         [("tenant_id", ASCENDING), ("service_report_id", ASCENDING)],
         {"name": "chem_usage_tenant_report", "background": True}),
        ("deal_pipelines",
         [("tenant_id", ASCENDING), ("slug", ASCENDING)],
         {"unique": True, "name": "uniq_tenant_pipeline_slug", "background": True}),
        ("deals",
         [("tenant_id", ASCENDING), ("pipeline_id", ASCENDING),
          ("status", ASCENDING), ("updated_at", DESCENDING)],
         {"name": "deals_tenant_pipeline_status_updated", "background": True}),
        ("deal_events",
         [("tenant_id", ASCENDING), ("deal_id", ASCENDING),
          ("created_at", DESCENDING)],
         {"name": "deal_events_tenant_deal_created", "background": True}),
        # Phase 4B · Feb 2026 — Stripe webhook idempotency ledger.
        # Unique on ``event_id`` prevents concurrent-replay double-processing.
        # TTL 30 days on ``processed_at`` (ISO string) — Mongo TTL requires
        # a BSON Date field, so we index it as a plain sparse index and
        # rely on the 30-day TTL enforced by a second Date field written
        # by the webhook handler (``expires_at``).
        ("stripe_events_processed",
         [("event_id", ASCENDING)],
         {"unique": True, "name": "uniq_stripe_event_id", "background": True}),
        # Phase 10c · Feb 2026 — promo redemption idempotency guard.
        # Unique on (tenant_id, payment_intent_id, kind) so a repeated
        # webhook can never double-redeem or double-revert.
        ("promo_redemptions_live",
         [("tenant_id", ASCENDING), ("payment_intent_id", ASCENDING),
          ("kind", ASCENDING)],
         {"unique": True, "name": "uniq_promo_redemption_pi_kind",
          "background": True}),
        # Phase 22 · Feb 2026 — Service Record Images public portal.
        # Unique lookup key for ``GET /api/public/service/{uuid}`` and
        # the SERVICE_RECORD_IMAGES merge tag. Sparse because legacy
        # rows may not carry a ``public_uuid`` field.
        ("service_reports",
         [("public_uuid", ASCENDING)],
         {"unique": True, "sparse": True, "name": "uniq_service_report_public_uuid",
          "background": True}),
    ]
    for coll, keys, opts in plans:
        try:
            await db[coll].create_index(keys, **opts)
        except Exception as e:
            logger.warning(f"index ensure failed on {coll}: {type(e).__name__}: {e}")

    # Phase 4B · Stripe webhook 30-day TTL. The TTL requires a BSON Date
    # field, so we maintain ``expires_at`` alongside the ISO ``processed_at``.
    try:
        await db.stripe_events_processed.create_index(
            [("expires_at", ASCENDING)],
            name="ttl_stripe_event_expires_at",
            expireAfterSeconds=0,
            background=True,
        )
    except Exception as e:
        logger.warning(f"stripe_events_processed TTL ensure failed: {e}")
