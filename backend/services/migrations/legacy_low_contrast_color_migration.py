"""Feb-2026 · Preset Palette Contrast Reconciliation · legacy user migration.

Scans ``users.display_color_hex`` for values that FAIL the pin
contrast guard (< 3.0 WCAG ratio vs pure white) and remaps each
blocked hex to the closest darker shade that PASSES the guard.

Idempotent — a second run does zero writes. NOT auto-run at boot;
ops invokes it manually. Supports a ``--dry-run`` flag that prints
the affected-user count + before/after mapping without mutating
any rows.

Usage:
    python -m services.migrations.legacy_low_contrast_color_migration --dry-run
    python -m services.migrations.legacy_low_contrast_color_migration

Audit trail: every successful write appends one document to
``color_migration_audit`` with the shape::

    {
      "user_id": <str>, "tenant_id": <str>,
      "before": "#RRGGBB", "after": "#RRGGBB",
      "event": "legacy_color_migrated",
      "ts": <utc-iso-string>,
    }

The audit collection is deliberately new (not the shared
``audit_logs`` table) so ops can eyeball the whole migration in
one place without a filter on ``event`` in the big table.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List

from motor.motor_asyncio import AsyncIOMotorClient


log = logging.getLogger("migrations.legacy_low_contrast_color")


# ── Mapping table ────────────────────────────────────────────────
# Each blocked hex → darker replacement that clears WCAG 3.0.
# Ratios verified against ``services.color.contrast`` before
# checking in:
#
#   #10B981 (2.537) → #059669 (3.768)   emerald 500 → emerald 600
#   #14B8A6 (2.489) → #0F766E (5.473)   teal 500    → teal 700
#   #F59E0B (2.148) → #B45309 (5.022)   amber 500   → amber 700
#   #84CC16 (1.976) → #4D7C0F (4.993)   lime 500    → lime 700
#   #06B6D4 (2.428) → #0E7490 (5.358)   cyan 500    → cyan 700
#   #F97316 (2.803) → #C2410C (5.178)   orange 500  → orange 700
#
# Orange isn't in the ticket's explicit list of 5 but the same
# validator drops it (ratio 2.803 < 3.0). Adding it here so the
# migration is honest: every blocked preset has a mapped fallback.
LEGACY_COLOR_REMAP: Dict[str, str] = {
    "#10B981": "#059669",
    "#14B8A6": "#0F766E",
    "#F59E0B": "#B45309",
    "#84CC16": "#4D7C0F",
    "#06B6D4": "#0E7490",
    "#F97316": "#C2410C",
}


def _normalize_hex(raw: Any) -> str:
    """Return upper-case ``#RRGGBB`` or empty string on malformed."""
    if not isinstance(raw, str):
        return ""
    s = raw.strip()
    if not s:
        return ""
    if not s.startswith("#"):
        s = f"#{s}"
    if len(s) != 7:
        return ""
    return s.upper()


async def _find_affected(db) -> List[Dict[str, Any]]:
    """Return the list of user docs whose ``display_color_hex`` is
    in the remap table (case-insensitive)."""
    blocked = list(LEGACY_COLOR_REMAP.keys())
    cursor = db.users.find(
        {"display_color_hex": {"$in": blocked
                                 + [h.lower() for h in blocked]}},
        {"_id": 0, "id": 1, "tenant_id": 1, "display_color_hex": 1},
    )
    return [row async for row in cursor]


async def backfill(db, *, dry_run: bool = False) -> Dict[str, Any]:
    """Return ``{"scanned", "affected", "updated", "mapping",
    "dry_run"}`` where ``affected`` is the count of users whose
    current hex would be remapped and ``updated`` is the actual
    write count (0 in dry-run mode)."""
    affected_rows = await _find_affected(db)
    scanned = await db.users.count_documents(
        {"display_color_hex": {"$exists": True, "$ne": None}},
    )

    # Per-user before/after breakdown (useful for the dry-run print).
    breakdown: List[Dict[str, str]] = []
    for row in affected_rows:
        before = _normalize_hex(row.get("display_color_hex"))
        after = LEGACY_COLOR_REMAP.get(before)
        if not after:
            continue
        breakdown.append({
            "user_id": row["id"],
            "tenant_id": row.get("tenant_id") or "",
            "before": before,
            "after": after,
        })

    if dry_run:
        log.info(
            "[legacy_color.dry_run] scanned=%d affected=%d",
            scanned, len(breakdown),
        )
        return {
            "scanned": scanned,
            "affected": len(breakdown),
            "updated": 0,
            "mapping": breakdown,
            "dry_run": True,
        }

    # Real run: per-user update + audit line.
    updated = 0
    now_iso = datetime.now(timezone.utc).isoformat()
    for row in breakdown:
        res = await db.users.update_one(
            {"id": row["user_id"],
              "display_color_hex": {"$in": [row["before"],
                                              row["before"].lower()]}},
            {"$set": {"display_color_hex": row["after"]}},
        )
        if res.modified_count > 0:
            updated += 1
            await db.color_migration_audit.insert_one({
                "user_id": row["user_id"],
                "tenant_id": row["tenant_id"],
                "before": row["before"],
                "after": row["after"],
                "event": "legacy_color_migrated",
                "ts": now_iso,
            })

    log.info(
        "[legacy_color.backfill] scanned=%d affected=%d updated=%d",
        scanned, len(breakdown), updated,
    )
    return {
        "scanned": scanned,
        "affected": len(breakdown),
        "updated": updated,
        "mapping": breakdown,
        "dry_run": False,
    }


async def _main() -> None:  # pragma: no cover — CLI entrypoint
    parser = argparse.ArgumentParser(
        description="Migrate users off low-contrast palette colors.")
    parser.add_argument("--dry-run", action="store_true",
                          help="print affected count without mutating rows")
    args = parser.parse_args()

    # Load ``backend/.env`` when the CLI is invoked outside supervisor.
    try:
        from dotenv import load_dotenv
        load_dotenv("/app/backend/.env")
    except Exception:
        pass  # dev may not have python-dotenv; env vars can also be exported

    url = os.environ["MONGO_URL"]
    name = os.environ["DB_NAME"]
    client = AsyncIOMotorClient(url)
    try:
        result = await backfill(client[name], dry_run=args.dry_run)
        # Human-readable summary.
        print(f"scanned={result['scanned']} affected={result['affected']} "
                f"updated={result['updated']} dry_run={result['dry_run']}")
        if args.dry_run and result["mapping"]:
            print("\nMapping preview (first 20):")
            for row in result["mapping"][:20]:
                print(f"  {row['user_id']}: {row['before']} → {row['after']}")
    finally:
        client.close()


if __name__ == "__main__":  # pragma: no cover
    asyncio.run(_main())
