"""Feb-2026 · Technicians · user_id backfill.

Backfills ``technicians.user_id`` for seeded real technician rows
(e.g. Mike Rivera / Carlos Rivera / Luis Marquez) whose tenant seed
wrote the tech row without linking it to a ``db.users`` account.
Without ``user_id`` the mobile ColorPicker's Apply flow short-
circuits with ``"No linked user account for this technician."``
because it PATCHes ``/api/users/{t.user_id}``.

Matching strategy (per tenant, most specific first):
  1. **email** — case-insensitive equality against ``db.users.email``.
     Same tenant only.
  2. **name** — normalised lower-cased ``db.users.name`` fallback.
     Same tenant only.

When no user match is found the row is SKIPPED (not created) — an
audit line ``technician_unlinked_no_user_match`` is written so ops
can decide whether to create a login credential manually. Creating
a bare user row here would give it no password / no invited-at
flag / no sensible defaults, and we don't want silent ghost logins.

Idempotency: rows that already have ``user_id`` are ignored on
every run. A second execution touches zero rows.

Audit collection: ``color_migration_audit`` is reused — same tenant
+ event shape — so ops has ONE table to inspect for all
data-fixups. Events written here:
  * ``technician_user_linked``            — success
  * ``technician_unlinked_no_user_match`` — skipped

Usage:
    python -m services.migrations.technicians_user_id_backfill --dry-run
    python -m services.migrations.technicians_user_id_backfill
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from motor.motor_asyncio import AsyncIOMotorClient


log = logging.getLogger("migrations.technicians_user_id_backfill")


def _norm_email(v: Any) -> str:
    if not isinstance(v, str):
        return ""
    return v.strip().lower()


def _norm_name(v: Any) -> str:
    if not isinstance(v, str):
        return ""
    return v.strip().lower()


async def _find_matching_user(
    db, *, tenant_id: str, email: str, name: str,
) -> Optional[Dict[str, Any]]:
    """Case-insensitive email match, then name fallback. Same tenant."""
    if email:
        u = await db.users.find_one(
            {"tenant_id": tenant_id,
              "email": {"$regex": f"^{email}$", "$options": "i"}},
            {"_id": 0, "id": 1, "email": 1, "name": 1},
        )
        if u:
            return u
    if name:
        u = await db.users.find_one(
            {"tenant_id": tenant_id,
              "name": {"$regex": f"^{name}$", "$options": "i"}},
            {"_id": 0, "id": 1, "email": 1, "name": 1},
        )
        if u:
            return u
    return None


async def backfill(
    db, *, dry_run: bool = False, tenant_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Scan every ``db.technicians`` row with a missing / null
    ``user_id`` and try to link it to a same-tenant user.

    When ``tenant_id`` is provided, the scan is scoped to that
    tenant (useful for ops running the migration on one tenant at
    a time, and for tests isolating from the shared dev DB).

    Returns ``{"scanned", "already_linked", "linked", "skipped",
    "mapping", "dry_run"}``. ``mapping`` is a list of per-row
    outcomes for the dry-run report.
    """
    _tenant_filter: Dict[str, Any] = (
        {"tenant_id": tenant_id} if tenant_id else {}
    )
    scanned = await db.technicians.count_documents(_tenant_filter)
    already_linked = await db.technicians.count_documents({
        **_tenant_filter,
        "user_id": {"$exists": True, "$nin": [None, ""]},
    })

    unlinked_query: Dict[str, Any] = {
        **_tenant_filter,
        "$or": [{"user_id": None},
                  {"user_id": {"$exists": False}},
                  {"user_id": ""}],
    }
    unlinked_rows = await db.technicians.find(
        unlinked_query,
        {"_id": 0, "id": 1, "tenant_id": 1, "name": 1, "email": 1},
    ).to_list(10000)

    linked_count = 0
    skipped_count = 0
    mapping: List[Dict[str, Any]] = []
    now_iso = datetime.now(timezone.utc).isoformat()

    for row in unlinked_rows:
        tid = row.get("tenant_id") or ""
        email = _norm_email(row.get("email"))
        name = _norm_name(row.get("name"))
        matched = await _find_matching_user(
            db, tenant_id=tid, email=email, name=name,
        )
        if matched:
            entry = {
                "tech_id": row["id"], "tenant_id": tid,
                "matched_by": "email" if email else "name",
                "tech_name": row.get("name"),
                "user_id": matched["id"],
                "user_email": matched.get("email"),
            }
            if not dry_run:
                res = await db.technicians.update_one(
                    {"id": row["id"], "tenant_id": tid,
                      "$or": [{"user_id": None},
                                {"user_id": {"$exists": False}},
                                {"user_id": ""}]},
                    {"$set": {"user_id": matched["id"]}},
                )
                if res.modified_count > 0:
                    linked_count += 1
                    await db.color_migration_audit.insert_one({
                        "event": "technician_user_linked",
                        "tech_id": row["id"],
                        "tenant_id": tid,
                        "user_id": matched["id"],
                        "matched_by": entry["matched_by"],
                        "user_email": matched.get("email"),
                        "ts": now_iso,
                    })
            else:
                linked_count += 1  # projected count for dry-run summary
            mapping.append(entry)
        else:
            entry = {
                "tech_id": row["id"], "tenant_id": tid,
                "tech_name": row.get("name"),
                "tech_email": row.get("email"),
                "skipped": True,
                "reason": "no_user_match",
            }
            if not dry_run:
                skipped_count += 1
                await db.color_migration_audit.insert_one({
                    "event": "technician_unlinked_no_user_match",
                    "tech_id": row["id"],
                    "tenant_id": tid,
                    "tech_email": row.get("email"),
                    "tech_name": row.get("name"),
                    "ts": now_iso,
                })
            else:
                skipped_count += 1
            mapping.append(entry)

    log.info(
        "[technicians_user_id.backfill] scanned=%d already_linked=%d "
        "linked=%d skipped=%d dry_run=%s",
        scanned, already_linked, linked_count, skipped_count, dry_run,
    )
    return {
        "scanned": scanned,
        "already_linked": already_linked,
        "linked": linked_count,
        "skipped": skipped_count,
        "mapping": mapping,
        "dry_run": dry_run,
    }


async def _main() -> None:  # pragma: no cover — CLI entrypoint
    parser = argparse.ArgumentParser(
        description="Backfill technicians.user_id from db.users matches.")
    parser.add_argument("--dry-run", action="store_true",
                          help="print affected rows without mutating")
    parser.add_argument("--tenant-id", default=None,
                          help="restrict the scan to one tenant id")
    args = parser.parse_args()

    try:
        from dotenv import load_dotenv
        load_dotenv("/app/backend/.env")
    except Exception:
        pass

    url = os.environ["MONGO_URL"]
    name = os.environ["DB_NAME"]
    client = AsyncIOMotorClient(url)
    try:
        result = await backfill(client[name], dry_run=args.dry_run,
                                     tenant_id=args.tenant_id)
        print(f"scanned={result['scanned']} "
                f"already_linked={result['already_linked']} "
                f"linked={result['linked']} "
                f"skipped={result['skipped']} "
                f"dry_run={result['dry_run']}")
        if args.dry_run and result["mapping"]:
            print("\nPer-row plan (first 30):")
            for row in result["mapping"][:30]:
                if row.get("skipped"):
                    print(f"  SKIP  tech={row['tech_id'][:8]}.. "
                            f"name={row.get('tech_name')!r} "
                            f"reason={row['reason']}")
                else:
                    print(f"  LINK  tech={row['tech_id'][:8]}.. "
                            f"name={row.get('tech_name')!r} "
                            f"→ user={row['user_id'][:8]}.. "
                            f"({row['matched_by']}: {row['user_email']!r})")
    finally:
        client.close()


if __name__ == "__main__":  # pragma: no cover
    asyncio.run(_main())
