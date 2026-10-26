"""Ticket AA · Feb-2026 — Tag → customers.service_category backfill.

The P2 #6 ``seed_property_service_category_from_customer`` migration
inherits ``customer.service_category`` → ``property.service_category``.
On this DB it ran once and inherited ZERO because every customer
row has ``service_category=null`` — the P2 #6 PATCH endpoint was
only ever used by a handful of operators.

Operator classifications historically landed in ``customers.tags``
instead (``Pool``, ``Landscaping``, ``Pool & Landscaping``, etc.).
This migration lifts those tags into ``service_category`` so the
downstream P2 #6 property-inheritance migration can cascade them
to the ``properties`` collection, and the Ticket V dashboard tile
aggregator starts returning non-zero counts.

Mapping (permissive canonical; case-insensitive):

    Pool, Pool Client, pool, POOL      → "pool"
    Landscaping, Landscaping Client    → "landscaping"
    Pool & Landscaping, Pool and
      Landscaping, Pool+Landscaping    → "both"

"Two singles = both" promotion: when a customer has BOTH a
Pool-mapped tag AND a Landscaping-mapped tag (as distinct tags,
not a combined one) → promoted to ``"both"``.

Unknown tags are ignored — customer stays null, surfaced in the
return summary as ``unmapped_tag_counts`` for operator review.

Idempotent via ``db.migrations`` sentinel
``aa_tag_to_service_category_backfill_v1``.  Second run = no-op.
``force=True`` bypasses the sentinel for admin re-run.

Only touches customers whose current ``service_category`` is
null/missing/empty — preserves ANY manual PATCH write (admin
override intent).
"""
from __future__ import annotations

import logging
import time
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Optional

from config import db
from utils import new_id


logger = logging.getLogger("aa_tag_to_service_category_backfill")

_SENTINEL_ID = "aa_tag_to_service_category_backfill_v1"

# Normalized tag → category.  Case-insensitive keys.
_TAG_TO_CATEGORY = {
    "pool": "pool",
    "pool client": "pool",
    "landscaping": "landscaping",
    "landscaping client": "landscaping",
    "pool & landscaping": "both",
    "pool and landscaping": "both",
    "pool+landscaping": "both",
    "pool + landscaping": "both",
}

_VALID_CATEGORIES = frozenset({"pool", "landscaping", "both"})


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _resolve_category(tags: Optional[Iterable[Any]]) -> Optional[str]:
    """Map a customer's ``tags`` list to a canonical service_category.

    Returns ``None`` when no tag matches.  Promotes two singles
    (Pool + Landscaping) to ``"both"``.
    """
    if not tags:
        return None
    hits: set[str] = set()
    for t in tags:
        if not isinstance(t, str):
            continue
        norm = t.strip().lower()
        mapped = _TAG_TO_CATEGORY.get(norm)
        if mapped:
            hits.add(mapped)
    if not hits:
        return None
    if "both" in hits:
        return "both"
    if "pool" in hits and "landscaping" in hits:
        return "both"
    if "pool" in hits:
        return "pool"
    if "landscaping" in hits:
        return "landscaping"
    return None


async def run_tag_to_service_category_backfill(
    *, force: bool = False, dry_run: bool = False,
) -> Dict[str, Any]:
    """Idempotent one-shot migration.

    Returns a summary dict:

        {
          "already_ran": bool,
          "ran_at": iso-ts,
          "run_id": uuid,
          "summary": {
             "processed": int,
             "mapped_pool": int,
             "mapped_landscaping": int,
             "mapped_both": int,
             "left_unset": int,
             "unmapped_tag_counts": {tag: count, ...},
             "per_tenant": {tenant_id: {pool, landscaping, both}, ...},
             "duration_ms": int,
             "dry_run": bool,
          },
        }
    """
    sentinel = await db.migrations.find_one({"id": _SENTINEL_ID})
    if sentinel and not force:
        return {
            "already_ran": True,
            "ran_at": sentinel.get("ran_at"),
            "summary": sentinel.get("summary") or {},
        }

    t0 = time.perf_counter()
    run_id = new_id()
    stats = {
        "processed": 0,
        "mapped_pool": 0,
        "mapped_landscaping": 0,
        "mapped_both": 0,
        "left_unset": 0,
    }
    unmapped_tags: Counter = Counter()
    per_tenant: Dict[str, Dict[str, int]] = {}

    # Scan every customer that has NO ``service_category`` set yet.
    cursor = db.customers.find(
        {"$or": [
            {"service_category": {"$exists": False}},
            {"service_category": None},
            {"service_category": ""},
        ]},
        {"_id": 0, "id": 1, "tenant_id": 1, "tags": 1},
    )
    async for cust in cursor:
        stats["processed"] += 1
        cid = cust.get("id")
        tid = cust.get("tenant_id")
        tags = cust.get("tags") or []
        if not (cid and tid):
            stats["left_unset"] += 1
            continue
        resolved = _resolve_category(tags)
        if not resolved:
            stats["left_unset"] += 1
            # Record unmapped tags for operator review.
            for t in tags:
                if not isinstance(t, str):
                    continue
                norm = t.strip().lower()
                if norm and norm not in _TAG_TO_CATEGORY:
                    unmapped_tags[t.strip()] += 1
            continue
        if not dry_run:
            await db.customers.update_one(
                {"id": cid, "tenant_id": tid,
                 # Idempotency belt-and-braces — re-check null guard
                 # at the write site so a concurrent PATCH between
                 # the scan and the write can't be clobbered.
                 "$or": [
                     {"service_category": {"$exists": False}},
                     {"service_category": None},
                     {"service_category": ""},
                 ]},
                {"$set": {
                    "service_category": resolved,
                    "service_category_source": "aa_tag_backfill",
                    "service_category_set_at": _now_iso(),
                }},
            )
        stats[f"mapped_{resolved}"] += 1
        tenant_bucket = per_tenant.setdefault(
            tid, {"pool": 0, "landscaping": 0, "both": 0},
        )
        tenant_bucket[resolved] += 1

    duration_ms = int((time.perf_counter() - t0) * 1000)
    summary = {
        **stats,
        "unmapped_tag_counts": dict(unmapped_tags),
        "per_tenant": per_tenant,
        "run_id": run_id,
        "duration_ms": duration_ms,
        "dry_run": dry_run,
    }

    if not dry_run:
        if sentinel and force:
            await db.migrations.update_one(
                {"id": _SENTINEL_ID},
                {"$set": {"last_forced_run_at": _now_iso(),
                           "last_forced_summary": summary}},
            )
        else:
            await db.migrations.insert_one({
                "id": _SENTINEL_ID,
                "ran_at": _now_iso(),
                "summary": summary,
            })

    logger.info(
        "[migration.aa_tag_to_service_category] run_id=%s "
        "processed=%d pool=%d landscaping=%d both=%d left_unset=%d "
        "duration_ms=%d dry_run=%s",
        run_id, stats["processed"], stats["mapped_pool"],
        stats["mapped_landscaping"], stats["mapped_both"],
        stats["left_unset"], duration_ms, dry_run,
    )
    return {
        "already_ran": False,
        "ran_at": _now_iso(),
        "summary": summary,
    }
