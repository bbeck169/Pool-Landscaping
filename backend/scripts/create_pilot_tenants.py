"""Phase T1.1 · Feb-2026 — idempotent pilot-tenant creator.

Creates two pilot tenants (slugs ``pool`` and ``landscaping``)
alongside the current data-owning tenants.  Existing tenants
(especially Aquaterra / Pool & Landscaping of Vistancia) are
completely untouched — the pilots start empty save for their default
service + income categories.

Contract (Feb-2026 T1 hotfix)
-----------------------------
*   Tenant ``id`` is a real UUID4 (matches the rest of the ``tenants``
    collection; the original string literals ``pool.tenant`` /
    ``landscaping.tenant`` are only accepted for backward-compatible
    idempotency — the row is auto-renamed to a UUID on first sight so
    downstream admin tooling never sees a mixed-shape tenants
    collection).
*   Slugs are stable (``pool`` and ``landscaping``) — the script keys
    off ``slug`` for idempotency, so re-running against a fresh DB
    always converges on exactly one row per pilot regardless of any
    prior legacy state.
*   Any pre-existing user membership row pointing at the legacy string
    id is auto-rewritten to reference the new UUID so no user ends up
    with a stale membership.
*   Sibling helper :func:`resolve_pilot_id` lets test / curl scripts
    look up the current UUID by slug without hard-coding it.

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
from typing import Optional

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from dotenv import load_dotenv                                # noqa: E402
from motor.motor_asyncio import AsyncIOMotorClient            # noqa: E402

load_dotenv(os.path.join(_ROOT, ".env"))


PILOTS = [
    {
        # Legacy id — the older create runs used this string as the
        # ``id`` field. New runs pick a fresh UUID and migrate any
        # legacy row/membership over to it. Keeping the string here
        # lets us recognise & retire the old shape safely.
        "legacy_id": "pool.tenant",
        "slug": "pool",
        "name": "Pool Services Pilot",
        "default_industry": "pool",
    },
    {
        "legacy_id": "landscaping.tenant",
        "slug": "landscaping",
        "name": "Landscaping Services Pilot",
        "default_industry": "landscape",
    },
]


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def resolve_pilot_id(db, slug: str) -> Optional[str]:
    """Return the current tenant id for the pilot with the given slug,
    or ``None`` when the row doesn't exist yet.  Test / curl helpers
    consume this so they never need to hard-code either the legacy
    literal or the freshly-minted UUID.
    """
    doc = await db.tenants.find_one({"slug": slug}, {"_id": 0, "id": 1})
    return doc["id"] if doc else None


async def _migrate_legacy_membership_refs(
    db, *, old_id: str, new_id: str,
) -> int:
    """Rewrite every user membership pointing at ``old_id`` to point at
    ``new_id``. Also fix ``users.tenant_id`` and ``users.active_tenant_id``
    for the rare case a user was created directly against the legacy
    string id.  Returns the number of updates performed (sum across
    both fields, for diagnostics only).
    """
    if not old_id or old_id == new_id:
        return 0
    updated = 0
    # Rewrite membership entries.
    r1 = await db.users.update_many(
        {"tenant_memberships.tenant_id": old_id},
        {"$set": {"tenant_memberships.$[m].tenant_id": new_id}},
        array_filters=[{"m.tenant_id": old_id}],
    )
    updated += (r1.modified_count or 0)
    # Rewrite user.tenant_id + active_tenant_id.
    r2 = await db.users.update_many(
        {"tenant_id": old_id},
        {"$set": {"tenant_id": new_id}})
    updated += (r2.modified_count or 0)
    r3 = await db.users.update_many(
        {"active_tenant_id": old_id},
        {"$set": {"active_tenant_id": new_id}})
    updated += (r3.modified_count or 0)
    return updated


async def _seed_categories(tenant_id: str) -> None:
    """Explicit best-effort default-category seed (both routers seed
    lazily on GET, but the explicit call keeps ``inspection = complete``
    right after create)."""
    try:
        from routers.service_categories import ensure_defaults_for_tenant \
            as _seed_service_categories
        await _seed_service_categories(tenant_id)
    except Exception as exc:                                    # noqa: BLE001
        print(f"  [warn] service_categories seed failed: {exc}")
    try:
        from routers.income_categories import ensure_defaults_for_tenant \
            as _seed_income_categories
        await _seed_income_categories(tenant_id)
    except Exception as exc:                                    # noqa: BLE001
        print(f"  [warn] income_categories seed failed: {exc}")


async def _create_pilot(db, spec: dict, dry_run: bool) -> dict:
    """Return ``{status, id, slug, migrated_memberships}``.

    ``status`` is one of ``created``, ``already_exists``,
    ``renamed_from_legacy``, ``would_create``.
    """
    # 1. Slug lookup — this is the authoritative primary key from
    #    the script's perspective.
    by_slug = await db.tenants.find_one(
        {"slug": spec["slug"]}, {"_id": 0, "id": 1, "slug": 1})
    legacy = await db.tenants.find_one(
        {"id": spec["legacy_id"]}, {"_id": 0, "id": 1, "slug": 1})

    if by_slug:
        # Two possibilities:
        #   a) already migrated → id is already a UUID → nothing to do.
        #   b) still on legacy id (id == legacy_id) → rename in place.
        current_id = by_slug["id"]
        if current_id == spec["legacy_id"]:
            new_id = str(uuid.uuid4())
            if dry_run:
                return {"status": "would_rename",
                        "id": new_id, "slug": spec["slug"],
                        "migrated_memberships": 0}
            # Insert-then-delete pattern so we never have zero rows.
            new_doc = {
                "id":         new_id,
                "slug":       spec["slug"],
                "name":       spec["name"],
                "active":     True,
                "created_at": _now(),
                "settings":   {"default_industry": spec["default_industry"]},
            }
            await db.tenants.insert_one(new_doc)
            await db.tenants.delete_one({"id": spec["legacy_id"]})
            n_mig = await _migrate_legacy_membership_refs(
                db, old_id=spec["legacy_id"], new_id=new_id)
            # Rewrite tenant-scoped category rows so the seed stays with
            # the pilot rather than being orphaned.
            for coll in ("service_categories", "income_categories"):
                await db[coll].update_many(
                    {"tenant_id": spec["legacy_id"]},
                    {"$set": {"tenant_id": new_id}})
            await _seed_categories(new_id)
            return {"status": "renamed_from_legacy",
                    "id": new_id, "slug": spec["slug"],
                    "migrated_memberships": n_mig}
        return {"status": "already_exists",
                "id": current_id, "slug": spec["slug"],
                "migrated_memberships": 0}

    # 2. Slug missing → create a fresh UUID row. Handle the legacy-
    #    only edge case where id=="pool.tenant" but slug column is
    #    absent.
    if legacy:
        new_id = str(uuid.uuid4())
        if dry_run:
            return {"status": "would_rename",
                    "id": new_id, "slug": spec["slug"],
                    "migrated_memberships": 0}
        new_doc = {
            "id":         new_id,
            "slug":       spec["slug"],
            "name":       spec["name"],
            "active":     True,
            "created_at": _now(),
            "settings":   {"default_industry": spec["default_industry"]},
        }
        await db.tenants.insert_one(new_doc)
        await db.tenants.delete_one({"id": spec["legacy_id"]})
        n_mig = await _migrate_legacy_membership_refs(
            db, old_id=spec["legacy_id"], new_id=new_id)
        for coll in ("service_categories", "income_categories"):
            await db[coll].update_many(
                {"tenant_id": spec["legacy_id"]},
                {"$set": {"tenant_id": new_id}})
        await _seed_categories(new_id)
        return {"status": "renamed_from_legacy",
                "id": new_id, "slug": spec["slug"],
                "migrated_memberships": n_mig}

    # 3. Clean create.
    if dry_run:
        return {"status": "would_create",
                "id": None, "slug": spec["slug"],
                "migrated_memberships": 0}
    new_id = str(uuid.uuid4())
    new_doc = {
        "id":         new_id,
        "slug":       spec["slug"],
        "name":       spec["name"],
        "active":     True,
        "created_at": _now(),
        "settings":   {"default_industry": spec["default_industry"]},
    }
    await db.tenants.insert_one(new_doc)
    await _seed_categories(new_id)
    return {"status": "created", "id": new_id, "slug": spec["slug"],
            "migrated_memberships": 0}


async def _run(args: argparse.Namespace) -> None:
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]

    print(f"[pilot-create] dry_run={args.dry_run}")
    for spec in PILOTS:
        r = await _create_pilot(db, spec, args.dry_run)
        print(f"[pilot-create] slug={spec['slug']} status={r['status']} "
              f"id={r['id']} migrated_memberships={r['migrated_memberships']}")
    print("[pilot-create] done.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                          help="Report only — no writes.")
    asyncio.run(_run(parser.parse_args()))


if __name__ == "__main__":
    main()
