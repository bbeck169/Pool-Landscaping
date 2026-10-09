#!/usr/bin/env python3
"""Phase 17 · Feb-2026 — stamp ``field_id`` onto every checklist
item in ``industry_checklist_templates`` + ``tenant_checklist_
overrides``.

Idempotent — safe to re-run. Reports a summary dict to stdout.

Runbook (preview)
-----------------
    python backend/scripts/stamp_checklist_field_ids.py

Runbook (production — single-tenant scope)
------------------------------------------
    python backend/scripts/stamp_checklist_field_ids.py \
        --tenant <tenant_id>

Scope narrowing: ``--tenant`` skips ``industry_checklist_templates``
(platform-level defaults are tenant-agnostic) and only processes
``tenant_checklist_overrides`` whose ``tenant_id`` matches.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Make ``services.*`` importable when running from /app.
_BACKEND_DIR = str(Path(__file__).resolve().parents[1])
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from dotenv import dotenv_values                                 # noqa: E402
from pymongo import MongoClient                                   # noqa: E402

from services.checklist_field_id import (                         # noqa: E402
    stamp_field_ids, stamped_counts,
)


def _db():
    env = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
    return MongoClient(env["MONGO_URL"])[env["DB_NAME"]]


def _migrate_collection(col, filter_q, dry_run=False, sample=None):
    """Return a ``{processed, updated, items_stamped, items_skipped}``
    summary. ``sample`` is a list to collect before/after diffs
    (first 5 items)."""
    processed = 0
    updated = 0
    items_stamped = 0
    items_skipped = 0
    for doc in col.find(filter_q, {"_id": 0, "id": 1,
                                     "items": 1, "tenant_id": 1,
                                     "industry": 1}):
        processed += 1
        before = doc.get("items") or []
        after = stamp_field_ids(before)
        counts = stamped_counts(before, after)
        items_stamped += counts["stamped"]
        items_skipped += counts["skipped"]
        if counts["stamped"] == 0:
            continue
        if sample is not None and len(sample) < 5:
            for b, a in zip(before, after):
                if (isinstance(b, dict) and isinstance(a, dict)
                        and not b.get("field_id") and a.get("field_id")):
                    sample.append({
                        "collection": col.name,
                        "doc_id": doc.get("id"),
                        "tenant_id": doc.get("tenant_id"),
                        "industry": doc.get("industry"),
                        "before": b,
                        "after": a,
                    })
                    if len(sample) >= 5:
                        break
        if dry_run:
            updated += 1
            continue
        col.update_one(
            {"id": doc["id"]},
            {"$set": {"items": after}},
        )
        updated += 1
    return {
        "collection": col.name,
        "processed": processed,
        "updated": updated,
        "items_stamped": items_stamped,
        "items_skipped": items_skipped,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenant", default=None,
                     help="Scope to a single tenant_id (production "
                           "runbook). Omit for a full-DB preview run.")
    ap.add_argument("--dry-run", action="store_true",
                     help="Report what would change without writing.")
    args = ap.parse_args()

    db = _db()
    sample = []
    results = []
    if args.tenant:
        # Production narrow scope — only tenant_checklist_overrides.
        results.append(_migrate_collection(
            db.tenant_checklist_overrides,
            {"tenant_id": args.tenant},
            dry_run=args.dry_run, sample=sample,
        ))
    else:
        # Preview / default — both collections.
        results.append(_migrate_collection(
            db.industry_checklist_templates, {},
            dry_run=args.dry_run, sample=sample,
        ))
        results.append(_migrate_collection(
            db.tenant_checklist_overrides, {},
            dry_run=args.dry_run, sample=sample,
        ))
    out = {
        "dry_run": args.dry_run,
        "tenant_scope": args.tenant,
        "collections": results,
        "sample_before_after": sample,
    }
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
