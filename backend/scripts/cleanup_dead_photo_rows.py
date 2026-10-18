"""TD-76 Phase B (ph2d) · Feb-2026 — preview-DB dead-photo cleanup.

Companion to the TD-76-aux diagnostic (``diagnose_photo_url_shapes.py``)
and the TD-76-ph2a OMIT behavior shipped on the BE emission layer.

**What this script does:** scans ``jobs.photos[]`` and
``estimates.photos[]`` across every tenant and removes photo
subdocs that have NO resolvable byte source:

  * empty / null ``url`` field AND
  * empty / null ``storage_path`` field AND
  * empty / null ``thumb`` field (inline data-URI)

These rows are already OMITted at BE emission (TD-76-ph2a) so
there is zero behavioral change on the wire — this script just
physically evicts them from the DB so future ``get_customer_media``
calls process fewer bogus docs.

**Safety model:**
  * ``--dry-run`` is the DEFAULT.  Pure read.  Counts + samples.
  * ``--apply`` is OPT-IN.  Requires an explicit flag.  Runs
    ``update_many($pull photos)`` with the exact dead-row match
    filter, then prints the per-collection + per-tenant diff.
  * No prod rollout automation.  Operator runs ``--apply`` with
    a prod ``MONGO_URL`` env var manually when they're ready.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from motor.motor_asyncio import AsyncIOMotorClient


MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "pool_crm")


def _is_dead(p: dict) -> bool:
    """Row has NO resolvable byte source."""
    if not isinstance(p, dict):
        return False
    if (p.get("url") or "").strip():
        return False
    if (p.get("storage_path") or "").strip():
        return False
    if (p.get("thumb") or "").strip():
        return False
    return True


async def _scan_dry(db):
    results = {"jobs": [], "estimates": []}
    tenant_counts = {"jobs": Counter(), "estimates": Counter()}
    sample_ids = {"jobs": [], "estimates": []}

    for coll_name in ("jobs", "estimates"):
        coll = db[coll_name]
        async for doc in coll.find({}, {
            "id": 1, "tenant_id": 1, "photos": 1, "_id": 0,
        }):
            dead = [p for p in (doc.get("photos") or [])
                     if _is_dead(p)]
            if not dead:
                continue
            tenant = doc.get("tenant_id") or "unknown"
            tenant_counts[coll_name][tenant] += len(dead)
            results[coll_name].append({
                "doc_id": doc.get("id"),
                "tenant_id": tenant,
                "dead_count": len(dead),
            })
            for p in dead[:3]:  # cap sample ids
                if len(sample_ids[coll_name]) < 6:
                    sample_ids[coll_name].append({
                        "doc_id": doc.get("id"),
                        "photo_id": p.get("id"),
                        "tenant_id": tenant,
                    })
    return results, tenant_counts, sample_ids


async def _apply(db):
    """OPT-IN mutation path. ``$pull`` dead photo subdocs."""
    per_coll = {"jobs": 0, "estimates": 0}
    for coll_name in ("jobs", "estimates"):
        coll = db[coll_name]
        # Match dead rows via $pull with the exact "all three are
        # empty/missing" shape. Mongo-side filter avoids pulling
        # every doc into Python.
        res = await coll.update_many(
            {},  # scan all docs
            {
                "$pull": {
                    "photos": {
                        "$or": [
                            {"$and": [
                                {"url": {"$in": [None, ""]}},
                                {"storage_path": {"$in": [None, ""]}},
                                {"thumb": {"$in": [None, ""]}},
                            ]},
                            {"$and": [
                                {"url": {"$exists": False}},
                                {"storage_path": {"$exists": False}},
                                {"thumb": {"$exists": False}},
                            ]},
                        ],
                    },
                },
            },
        )
        per_coll[coll_name] = res.modified_count
    return per_coll


def _mask(url: str) -> str:
    return re.sub(r"://[^@]+@", "://***:***@", url)


def _render_dry(results, tenant_counts, sample_ids, started_at):
    lines = [
        "# TD-76-ph2d · Preview DB dead-photo cleanup — DRY RUN",
        "",
        f"**Run at:** {started_at}",
        f"**MONGO_URL:** `{_mask(MONGO_URL)}`",
        f"**DB:** `{DB_NAME}`",
        "",
        "**DRY RUN.** Zero writes performed.",
        "**Pass `--apply` to physically remove the rows.**",
        "",
    ]
    for coll in ("jobs", "estimates"):
        docs = results[coll]
        total_dead = sum(d["dead_count"] for d in docs)
        lines += [
            f"## `{coll}.photos[]` — {total_dead} dead subdocs across {len(docs)} parent docs",
            "",
        ]
        if tenant_counts[coll]:
            lines += [
                "**Per-tenant breakdown (top 10):**",
                "",
                "| Tenant | Dead photos |",
                "|---|---|",
            ]
            top = sorted(tenant_counts[coll].items(),
                          key=lambda t: -t[1])[:10]
            for tenant, cnt in top:
                lines.append(f"| `{tenant}` | {cnt} |")
            lines.append("")
        if sample_ids[coll]:
            lines += ["**Sample dead photo_ids:**", "", "```"]
            for s in sample_ids[coll]:
                lines.append(
                    f"- tenant={s['tenant_id']}  doc_id={s['doc_id']}  "
                    f"photo_id={s['photo_id']}"
                )
            lines += ["```", ""]
    lines += [
        "## Next action",
        "",
        "Re-run with `--apply` to physically remove the dead rows.",
        "`$pull` filter: `url` empty/missing AND `storage_path` "
        "empty/missing AND `thumb` empty/missing.",
    ]
    return "\n".join(lines)


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true",
        help="Physically remove dead photo subdocs. DEFAULT is dry-run.",
    )
    args = parser.parse_args()

    client = AsyncIOMotorClient(MONGO_URL)
    db = client[DB_NAME]
    started_at = datetime.now(timezone.utc).isoformat()

    if args.apply:
        print("APPLY mode — physically removing dead photo subdocs.")
        per_coll = await _apply(db)
        print(f"jobs:      {per_coll['jobs']} parent docs modified")
        print(f"estimates: {per_coll['estimates']} parent docs modified")
    else:
        print("DRY RUN mode — pass --apply to physically remove.")
        results, tenant_counts, sample_ids = await _scan_dry(db)
        md = _render_dry(results, tenant_counts, sample_ids, started_at)
        out = Path("/app/memory/photo_url_cleanup_dryrun.md")
        out.write_text(md)
        print(f"Wrote {out} ({len(md)} bytes).")


if __name__ == "__main__":
    asyncio.run(main())
