"""Phase 13 · Feb-2026 — W2 · Session-collections index ensure.

Idempotent one-shot compound-index creator for the 15 Phase 1-11
collections that were flagged by the Phase 12 audit as missing a
(tenant_id, timestamp_desc) compound index.

Usage:
    python -m scripts.create_session_indexes            # real
    python -m scripts.create_session_indexes --dry-run  # inspect
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import OperationFailure


# (collection, primary_ts_field, fallback_ts_fields[])
SPECS: List[Tuple[str, str, Tuple[str, ...]]] = [
    ("route_optimize_events",   "executed_at",   ("created_at",)),
    ("aeo_visibility_probes",   "ran_at",        ("created_at", "probed_at")),
    ("brand_mentions",          "discovered_at", ("created_at", "seen_at")),
    ("brand_mention_runs",      "ran_at",        ("created_at", "started_at")),
    ("aeo_fixes",               "generated_at",  ("created_at",)),
    ("mention_response_drafts", "drafted_at",    ("created_at",)),
    ("response_draft_templates","created_at",    ()),
    ("scorecard_digests",       "generated_at",  ("created_at", "period_start")),
    ("aeo_digest_runs",         "generated_at",  ("created_at", "run_at")),
    ("aeo_digest_pdfs",         "generated_at",  ("created_at",)),
    ("llmstxt_publish_configs", "updated_at",    ("created_at",)),
    ("llmstxt_publish_history", "requested_at",  ("created_at", "completed_at")),
    ("invoice_reconciliation_log", "logged_at",  ("created_at",)),
    ("quotes",                  "created_at",    ()),
    ("aeo_probe_runs",          "ran_at",        ("created_at", "started_at")),
]


def _index_name(field: str) -> str:
    return f"tenant_{field}_desc"


async def _pick_field(db, coll: str, primary: str, fallbacks: Tuple[str, ...]) -> str:
    """Return the first ts field that exists on at least one sample doc.
    Never crashes — returns the primary if the sample is empty."""
    sample = await db[coll].find_one({}, sort=[("_id", -1)])
    if not sample:
        return primary
    if primary in sample:
        return primary
    for f in fallbacks:
        if f in sample:
            return f
    return primary  # nothing matched — try the primary anyway; create_index
                    # will still succeed even if no docs have the field.


async def _existing_names(db, coll: str) -> List[str]:
    try:
        return [i["name"] async for i in db[coll].list_indexes()]
    except OperationFailure:
        return []


async def run(*, dry_run: bool) -> Dict[str, int]:
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]
    names = set(await db.list_collection_names())
    stats = {"created": 0, "already_exists": 0,
              "skipped_missing_field": 0, "skipped_empty_collection": 0,
              "substituted_field": 0}

    for coll, primary_field, fallbacks in SPECS:
        if coll not in names:
            stats["skipped_empty_collection"] += 1
            print(f"  · SKIP {coll:32s} — collection does not exist yet")
            continue

        ts_field = await _pick_field(db, coll, primary_field, fallbacks)
        if ts_field != primary_field:
            stats["substituted_field"] += 1
            print(f"  · NOTE {coll:32s} — using {ts_field!r} "
                  f"(primary {primary_field!r} not present on sample)")

        idx_name = _index_name(ts_field)
        existing = await _existing_names(db, coll)
        if idx_name in existing:
            stats["already_exists"] += 1
            print(f"  · OK   {coll:32s} — {idx_name} already present")
            continue

        if dry_run:
            print(f"  · DRY  {coll:32s} — would create {idx_name} on "
                  f"[('tenant_id',1), ('{ts_field}',-1)]")
        else:
            try:
                await db[coll].create_index(
                    [("tenant_id", 1), (ts_field, -1)], name=idx_name)
                stats["created"] += 1
                print(f"  · NEW  {coll:32s} — created {idx_name}")
            except OperationFailure as e:
                # Race with another boot hook — treat as already_exists.
                if "already exists" in str(e).lower() or "IndexOptionsConflict" in str(e):
                    stats["already_exists"] += 1
                    print(f"  · OK   {coll:32s} — {idx_name} (concurrent create)")
                else:
                    raise

    print()
    print("=" * 60)
    print(f"{'DRY-RUN' if dry_run else 'REAL RUN'} SUMMARY")
    print("=" * 60)
    for k, v in stats.items():
        print(f"  {k}: {v}")
    return stats


async def ensure_on_boot() -> None:
    """Boot hook — silent-except-on-error, never blocks startup."""
    import logging
    log = logging.getLogger("pool_crm")
    try:
        stats = await run(dry_run=False)
        n = stats["created"]; m = stats["already_exists"] + stats["skipped_empty_collection"]
        log.info(f"[indexes] {n} indexes ensured, {m} skipped/present")
    except Exception as e:  # noqa: BLE001
        log.warning(f"[indexes] boot-hook failed (non-fatal): {e}")

    # Phase 14b · Feb-2026 — bulk_charge_runs unique + query indexes.
    try:
        from routers.invoices_bulk_charge import ensure_indexes as _p14b_idx
        await _p14b_idx()
    except Exception as e:  # noqa: BLE001
        log.warning(f"[indexes] phase-14b hook failed (non-fatal): {e}")

    # Phase 17 · Feb-2026 — QBO mirror collection indexes.
    try:
        from routers.qbo_router import ensure_indexes as _p17_idx
        await _p17_idx()
    except Exception as e:  # noqa: BLE001
        log.warning(f"[indexes] phase-17 hook failed (non-fatal): {e}")

    # Phase 19 · Feb-2026 — ai_rewrite_usage composite-unique index.
    try:
        from routers.checkin_rewrite import ensure_indexes as _p19_idx
        await _p19_idx()
    except Exception as e:  # noqa: BLE001
        log.warning(f"[indexes] phase-19 hook failed (non-fatal): {e}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    asyncio.run(run(dry_run=bool(args.dry_run)))


if __name__ == "__main__":
    main()
