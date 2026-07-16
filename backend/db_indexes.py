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
    ]
    for coll, keys, opts in plans:
        try:
            await db[coll].create_index(keys, **opts)
        except Exception as e:
            logger.warning(f"index ensure failed on {coll}: {type(e).__name__}: {e}")
