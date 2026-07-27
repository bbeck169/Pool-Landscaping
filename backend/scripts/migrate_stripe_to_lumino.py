"""Task QQ · Feb 2026 — Stripe → Lumino migration script skeleton.

USER DIRECTIVE (safety rail — enforced here, not just documented):

* NO LIVE CUSTOMERS in any test flow.
* Defaults to the seed / demo tenant only.
* Production tenant target requires BOTH ``--i-know-this-is-production``
  and a typed ``YES`` confirmation prompt.
* Dry-run is the default. ``--live`` is required to mutate anything.

Phase 1: this script is a **skeleton** — the Lumino data-import API is
not wired yet (Phase 2). What Phase 1 delivers:

  * enumeration query over ``customers``, ``payment_methods``,
    ``subscriptions`` filtered by tenant.
  * per-record dry-run log line ``[WOULD MIGRATE] <collection> <id>``.
  * idempotency short-circuit: any doc already carrying a
    ``lumino_customer_id`` / ``lumino_payment_method_id`` /
    ``lumino_subscription_id`` is skipped.
  * safety confirmation gate.

Usage (from ``/app/backend``)::

    python scripts/migrate_stripe_to_lumino.py            # dry-run, seed tenant
    python scripts/migrate_stripe_to_lumino.py --live     # still dry-run in Phase 1 — no live wiring
    python scripts/migrate_stripe_to_lumino.py --tenant-id ${TENANT_ID}
    python scripts/migrate_stripe_to_lumino.py --i-know-this-is-production --tenant-id ${PROD_TENANT_ID}
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("migrate_stripe_to_lumino")

# Synthetic tenant slugs that are OK to touch without the
# --i-know-this-is-production flag.
_SYNTHETIC_TENANT_SLUGS = ("aquaterra", "plofv-dev", "plofv-demo")


async def _resolve_default_tenant(db) -> str:
    """Return the seed/demo tenant id. Prefers Aquaterra."""
    for slug in _SYNTHETIC_TENANT_SLUGS:
        t = await db.tenants.find_one({"slug": slug}, {"_id": 0, "id": 1})
        if t:
            return t["id"]
    raise SystemExit("No synthetic tenant found — refusing to guess.")


async def _iter(coll, q, fields):
    """Async generator across a Mongo cursor with a projection."""
    async for doc in coll.find(q, fields):
        yield doc


async def migrate(*, tenant_id: str, live: bool) -> dict:
    from config import db
    stats = {"customers": 0, "payment_methods": 0, "subscriptions": 0,
                "skipped_already_migrated": 0}
    # ── Customers ─────────────────────────────────────────────────
    async for c in _iter(db.customers,
                              {"tenant_id": tenant_id,
                                "stripe_customer_id": {"$exists": True, "$ne": None}},
                              {"_id": 0, "id": 1, "email": 1,
                                "stripe_customer_id": 1, "lumino_customer_id": 1}):
        if c.get("lumino_customer_id"):
            stats["skipped_already_migrated"] += 1
            continue
        stats["customers"] += 1
        log.info("[WOULD MIGRATE] customer %s (%s) stripe=%s",
                    c["id"], c.get("email"), c["stripe_customer_id"])
        if live:
            # TODO(phase2): POST to Lumino data-import endpoint and
            # store the returned lumino_customer_id on the doc.
            pass
    # ── Payment methods ───────────────────────────────────────────
    async for pm in _iter(db.payment_methods,
                                {"tenant_id": tenant_id,
                                  "stripe_payment_method_id": {"$exists": True, "$ne": None}},
                                {"_id": 0, "id": 1, "stripe_payment_method_id": 1,
                                  "lumino_payment_method_id": 1}):
        if pm.get("lumino_payment_method_id"):
            stats["skipped_already_migrated"] += 1
            continue
        stats["payment_methods"] += 1
        log.info("[WOULD MIGRATE] payment_method %s stripe=%s",
                    pm["id"], pm["stripe_payment_method_id"])
    # ── Subscriptions (Autobilling) ──────────────────────────────
    async for sub in _iter(db.subscriptions,
                                {"tenant_id": tenant_id,
                                  "stripe_subscription_id": {"$exists": True, "$ne": None}},
                                {"_id": 0, "id": 1, "stripe_subscription_id": 1,
                                  "lumino_subscription_id": 1}):
        if sub.get("lumino_subscription_id"):
            stats["skipped_already_migrated"] += 1
            continue
        stats["subscriptions"] += 1
        log.info("[WOULD MIGRATE] subscription %s stripe=%s",
                    sub["id"], sub["stripe_subscription_id"])
    return stats


async def _amain(args):
    from config import db
    tenant_id = args.tenant_id or await _resolve_default_tenant(db)
    tenant = await db.tenants.find_one({"id": tenant_id},
                                              {"_id": 0, "slug": 1, "name": 1})
    if not tenant:
        raise SystemExit(f"Tenant not found: {tenant_id}")
    is_synthetic = tenant.get("slug") in _SYNTHETIC_TENANT_SLUGS
    if not is_synthetic and not args.i_know_this_is_production:
        raise SystemExit(
            f"Refusing to run against non-synthetic tenant "
            f"{tenant.get('slug')!r}. Re-run with "
            f"--i-know-this-is-production if intended."
        )
    if not is_synthetic and args.i_know_this_is_production:
        print(f"\n⚠️  About to migrate PRODUCTION tenant "
                 f"{tenant.get('slug')!r} ({tenant.get('name')}).")
        print("Type YES to continue: ", end="", flush=True)
        confirm = sys.stdin.readline().strip()
        if confirm != "YES":
            raise SystemExit("Aborted — no YES confirmation.")
    log.info("Target tenant: %s (%s) · live=%s",
                tenant.get("slug"), tenant_id, args.live)
    stats = await migrate(tenant_id=tenant_id, live=args.live)
    log.info("Done. Stats: %s", stats)
    return stats


def _parse(argv):
    p = argparse.ArgumentParser(description="Migrate Stripe records to Lumino.")
    p.add_argument("--tenant-id", default=None,
                     help="Target tenant id (defaults to synthetic seed tenant).")
    p.add_argument("--live", action="store_true",
                     help="Actually mutate. Default: dry-run.")
    p.add_argument("--i-know-this-is-production",
                     action="store_true",
                     help="Required when --tenant-id is a real production tenant.")
    return p.parse_args(argv)


def main(argv=None):
    args = _parse(sys.argv[1:] if argv is None else argv)
    return asyncio.run(_amain(args))


if __name__ == "__main__":
    main()
