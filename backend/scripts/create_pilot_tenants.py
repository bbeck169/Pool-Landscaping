"""Phase T1.1 · Feb-2026 — idempotent pilot-tenant creator.

Creates two pilot tenants ``pool.tenant`` and ``landscaping.tenant``
alongside the current data-owning tenants.  Existing tenants
(especially Aquaterra / Pool & Landscaping of Vistancia) are
completely untouched — the pilots start empty save for their default
service + income categories.

Usage
-----
::

    python -m scripts.create_pilot_tenants
    python -m scripts.create_pilot_tenants --dry-run

Idempotent — rerunning simply reports "already exists" per row.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import uuid
from datetime import datetime, timezone

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from dotenv import load_dotenv                                # noqa: E402
from motor.motor_asyncio import AsyncIOMotorClient            # noqa: E402

load_dotenv(os.path.join(_ROOT, ".env"))


PILOTS = [
    {
        "id": "pool.tenant",  # Fixed IDs so the row is trivial to
                                 # reference from admin flows / tests.
        "slug": "pool",
        "name": "Pool Services Pilot",
        "default_industry": "pool",
    },
    {
        "id": "landscaping.tenant",
        "slug": "landscaping",
        "name": "Landscaping Services Pilot",
        "default_industry": "landscape",
    },
]


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _create_pilot(db, spec: dict, dry_run: bool) -> str:
    existing = await db.tenants.find_one({"id": spec["id"]}, {"_id": 0, "id": 1})
    if existing:
        return "already_exists"
    if dry_run:
        return "would_create"
    doc = {
        "id":       spec["id"],
        "slug":     spec["slug"],
        "name":     spec["name"],
        "active":   True,
        "created_at": _now(),
        "settings": {
            # Phase L1.2 handshake — the new tenant-aware industry
            # derivation consults ``tenants.settings.default_industry``
            # first. Pinning it here means every job created in the
            # pilot naturally lands on the correct industry checklist
            # even before any per-job override is stored.
            "default_industry": spec["default_industry"],
        },
    }
    await db.tenants.insert_one(doc)
    # Explicitly seed the two category axes so the tenant looks
    # complete on inspection (both routers seed lazily on GET, but
    # the explicit invocation avoids the "half-seeded" appearance
    # user asked us to avoid).
    try:
        from routers.service_categories import ensure_defaults_for_tenant \
            as _seed_service_categories
        await _seed_service_categories(spec["id"])
    except Exception as exc:                                    # noqa: BLE001
        print(f"  [warn] service_categories seed failed: {exc}")
    try:
        from routers.income_categories import ensure_defaults_for_tenant \
            as _seed_income_categories
        await _seed_income_categories(spec["id"])
    except Exception as exc:                                    # noqa: BLE001
        print(f"  [warn] income_categories seed failed: {exc}")
    return "created"


async def _run(args: argparse.Namespace) -> None:
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]

    print(f"[pilot-create] dry_run={args.dry_run}")
    for spec in PILOTS:
        status = await _create_pilot(db, spec, args.dry_run)
        print(f"[pilot-create] id={spec['id']} slug={spec['slug']} "
              f"status={status}")
    print("[pilot-create] done.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                          help="Report only — no writes.")
    asyncio.run(_run(parser.parse_args()))


if __name__ == "__main__":
    main()
