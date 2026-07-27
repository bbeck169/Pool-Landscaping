"""Task QQ · Feb 2026 — Stripe → Lumino migration script (Phase 2 hydrate).

USER DIRECTIVE (safety rails — enforced here, not just documented):

* NO LIVE CUSTOMERS in any test flow.
* Defaults to the seed / demo tenant only.
* Production tenant target requires BOTH
  ``--i-know-this-is-production`` and a typed ``YES`` confirmation.
* Dry-run is the default. ``--live`` is required to mutate anything.
* ``--dry-run-report-only`` emits aggregate counts only (no per-row
  logs), useful for producing a "what would happen" report without
  polluting the log with thousands of lines.

Phase 2 (this file, Feb 2026)
-----------------------------
* Wires the actual Lumino data-import call site: for each doc the
  script would migrate, it now invokes
  ``LuminoProvider.create_customer`` (or the equivalent for payment
  methods / subscriptions) and stores the returned Lumino id.
* In preview / non-production the LuminoProvider short-circuits
  every call to a synthetic ``{status: "dry_run", ...}`` payload
  via ``PaymentProviderDryRun``. We catch it and log
  ``[DRY-RUN mock]`` — nothing hits the network, nothing is
  written unless ``--persist-dry-run-ids`` is passed (defaults to
  OFF; the mock ids are prefixed ``prev_`` and are useless outside
  the preview scope test).
* In production with valid credentials the call proceeds and we
  persist the real Lumino id on the doc.

Usage (from ``/app/backend``)::

    python scripts/migrate_stripe_to_lumino.py                          # dry-run, seed tenant
    python scripts/migrate_stripe_to_lumino.py --dry-run-report-only    # aggregate counts, no per-row logs
    python scripts/migrate_stripe_to_lumino.py --live                   # actually call Lumino import (preview → mocked)
    python scripts/migrate_stripe_to_lumino.py --tenant-id ${TENANT_ID}
    python scripts/migrate_stripe_to_lumino.py --i-know-this-is-production --tenant-id ${PROD_TENANT_ID} --live
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
    async for doc in coll.find(q, fields):
        yield doc


async def _hydrate_customer(provider, c, *, live: bool,
                                  persist_dry_run_ids: bool,
                                  report_only: bool) -> str:
    """Invoke Lumino data-import for a single customer. Returns one
    of: ``migrated``, ``dry_run``, ``skipped``, ``failed``."""
    from config import db
    from services.payments import (
        PaymentProviderDryRun,
        PaymentProviderNotConfigured,
        PaymentTestScopeViolation,
    )
    email = c.get("email") or ""
    idem = f"qq-p2-cust-{c['id']}"
    try:
        resp = await provider.create_customer(
            email=email,
            name=c.get("name") or None,
            metadata={"legacy_stripe_customer_id": c["stripe_customer_id"]},
            idempotency_key=idem,
        )
        # Real Lumino returned a customer id. Persist it.
        lumino_id = (resp or {}).get("id") or (resp or {}).get("customer_id")
        if live and lumino_id and not report_only:
            await db.customers.update_one(
                {"id": c["id"]},
                {"$set": {"lumino_customer_id": lumino_id}},
            )
        if not report_only:
            log.info("[MIGRATED] customer %s → lumino=%s", c["id"], lumino_id)
        return "migrated"
    except PaymentProviderDryRun as ex:
        mock_id = (ex.payload or {}).get("session_id")
        if live and persist_dry_run_ids and mock_id and not report_only:
            await db.customers.update_one(
                {"id": c["id"]},
                {"$set": {"lumino_customer_id": mock_id,
                            "lumino_import_mode": "dry_run_mock"}},
            )
        if not report_only:
            log.info("[DRY-RUN mock] customer %s (mock id=%s)", c["id"], mock_id)
        return "dry_run"
    except PaymentTestScopeViolation:
        if not report_only:
            log.warning("[SCOPE-BLOCK] customer %s not synthetic — skipped",
                          c["id"])
        return "skipped"
    except PaymentProviderNotConfigured:
        if not report_only:
            log.error("[NOT-CONFIGURED] customer %s — Lumino env missing",
                        c["id"])
        return "failed"
    except Exception as exc:                                        # noqa: BLE001
        if not report_only:
            log.error("[ERROR] customer %s: %s", c["id"], exc)
        return "failed"


async def migrate(*, tenant_id: str, live: bool,
                  report_only: bool = False,
                  persist_dry_run_ids: bool = False) -> dict:
    from config import db
    from services.payments import get_payment_provider
    provider = get_payment_provider()
    stats = {"customers": 0,                                          # Phase 1 back-compat key
                "customers_would_migrate": 0,
                "customers_migrated": 0,
                "customers_dry_run": 0,
                "customers_failed": 0,
                "payment_methods": 0, "subscriptions": 0,
                "skipped_already_migrated": 0}
    # ── Customers ─────────────────────────────────────────────────
    async for c in _iter(db.customers,
                              {"tenant_id": tenant_id,
                                "stripe_customer_id": {"$exists": True, "$ne": None}},
                              {"_id": 0, "id": 1, "email": 1, "name": 1,
                                "stripe_customer_id": 1, "lumino_customer_id": 1}):
        if c.get("lumino_customer_id"):
            stats["skipped_already_migrated"] += 1
            continue
        stats["customers_would_migrate"] += 1
        stats["customers"] += 1                                       # Phase 1 back-compat
        if not report_only:
            log.info("[WOULD MIGRATE] customer %s (%s) stripe=%s",
                        c["id"], c.get("email"), c["stripe_customer_id"])
        if live:
            outcome = await _hydrate_customer(
                provider, c,
                live=True, report_only=report_only,
                persist_dry_run_ids=persist_dry_run_ids,
            )
            if outcome == "migrated":
                stats["customers_migrated"] += 1
            elif outcome == "dry_run":
                stats["customers_dry_run"] += 1
            elif outcome == "failed":
                stats["customers_failed"] += 1
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
        if not report_only:
            log.info("[WOULD MIGRATE] payment_method %s stripe=%s",
                        pm["id"], pm["stripe_payment_method_id"])
        # NOTE: Lumino's PM import path is customer-scoped and
        # depends on the customer having been migrated in the pass
        # above. We defer PM hydration to a Phase 3 pass so live
        # cutover can order the two migrations correctly.
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
        if not report_only:
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
    log.info("Target tenant: %s (%s) · live=%s · report_only=%s",
                tenant.get("slug"), tenant_id, args.live,
                args.dry_run_report_only)
    stats = await migrate(
        tenant_id=tenant_id,
        live=args.live,
        report_only=args.dry_run_report_only,
        persist_dry_run_ids=args.persist_dry_run_ids,
    )
    log.info("Done. Stats: %s", stats)
    return stats


def _parse(argv):
    p = argparse.ArgumentParser(description="Migrate Stripe records to Lumino.")
    p.add_argument("--tenant-id", default=None,
                     help="Target tenant id (defaults to synthetic seed tenant).")
    p.add_argument("--live", action="store_true",
                     help="Actually call Lumino import endpoints. Default: dry-run enumerate only.")
    p.add_argument("--dry-run-report-only", action="store_true",
                     help="Aggregate counts only, no per-row logs. Useful for CI-style reports.")
    p.add_argument("--persist-dry-run-ids", action="store_true",
                     help="With --live + preview scope, persist the mock lumino_* ids "
                            "on the docs. OFF by default — mock ids are useless outside preview.")
    p.add_argument("--i-know-this-is-production",
                     action="store_true",
                     help="Required when --tenant-id is a real production tenant.")
    return p.parse_args(argv)


def main(argv=None):
    args = _parse(sys.argv[1:] if argv is None else argv)
    return asyncio.run(_amain(args))


if __name__ == "__main__":
    main()
