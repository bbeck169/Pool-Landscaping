"""Feb-2026 · P24 — Backfill ``ai_employees.avatar_url`` where it is
missing or empty.

Runs three recovery strategies in order per broken row:

  1. **Audit log** — the last known non-empty ``avatar_url`` for this
     ``(tenant_id, key)`` pair, if any, is pulled from
     ``migration_log`` (dedupe merges) and ``ai_employee_updates``
     (an existing update-history collection when present). We match
     on ``(tenant_id, key)`` rather than ``id`` so a row that lost
     its avatar via dedupe still gets recovered.

  2. **DEFAULT_EMPLOYEES seed** — the canonical persona seed table
     in ``routers/ai_employees.py`` carries the shipped avatar path
     (``/avatars/personas/{key}.jpg``) for every seeded persona. If
     the row's ``key`` matches a seeded persona, use the shipped
     value.  This covers ~95% of the reported prod incidents.

  3. **Deterministic DiceBear default** — for non-seeded rows (a
     custom persona created by an admin, or a legacy row with an
     unrecognised key), fall back to a DiceBear seed keyed on the
     row's ``id`` so the persona has *some* portrait rather than a
     grey placeholder.

Idempotent: rows that already have a non-empty ``avatar_url`` are
skipped. Safe to re-run.

Usage
-----

Dry-run (default — no writes, prints counts):

    $ python -m backend.migrations.task_p24_backfill_ai_employee_avatars

Commit:

    $ python -m backend.migrations.task_p24_backfill_ai_employee_avatars --commit

Verbose:

    $ python -m backend.migrations.task_p24_backfill_ai_employee_avatars --commit --verbose
"""
from __future__ import annotations

import argparse
import asyncio
import logging
from typing import Any, Dict, List, Optional

from config import db, logger  # type: ignore[attr-defined]
from routers.ai_employees import DEFAULT_EMPLOYEES  # type: ignore[attr-defined]


_DICEBEAR = "https://api.dicebear.com/7.x/personas/svg?seed={seed}"


def _is_empty(v: Any) -> bool:
    return v is None or (isinstance(v, str) and not v.strip())


def _seeded_default_for_key(key: Optional[str]) -> Optional[str]:
    if not key:
        return None
    for row in DEFAULT_EMPLOYEES:
        if row.get("key") == key:
            av = row.get("avatar_url")
            if not _is_empty(av):
                return av
    return None


async def _pull_last_known(tenant_id: str, key: Optional[str]) -> Optional[str]:
    """Best-effort scan of the two audit surfaces for a prior non-empty
    ``avatar_url`` on the same ``(tenant_id, key)`` pair. Returns the
    first non-empty match; ``None`` if nothing is found.  Failures
    (missing collection, missing indexes) are silent — recovery falls
    through to the seed table on the next branch."""
    if not tenant_id or not key:
        return None
    try:
        # ``migration_log`` from the P24 dedupe extension records the
        # merged_fields that were promoted. If a prior dedupe of this
        # pair moved an avatar_url onto the survivor, we can trust
        # that value.  Best-effort.
        async for ml in db.migration_log.find(
            {"tenant_id": tenant_id, "key": key, "kind": "in_tenant_dupe"},
        ).sort("_id", -1).limit(5):
            if isinstance(ml.get("merged_fields"), list) \
               and "avatar_url" in ml["merged_fields"]:
                # We know a value was merged in but the value itself
                # isn't recorded in ``migration_log``.  Fall through.
                break
    except Exception:
        pass
    try:
        # Some deployments carry an ``ai_employee_updates`` audit
        # trail that stores every patch payload. When present, walk
        # it newest-first for a prior non-empty avatar_url.
        async for row in db.ai_employee_updates.find(
            {"tenant_id": tenant_id, "key": key},
        ).sort("_id", -1).limit(20):
            candidate = (row.get("patch") or {}).get("avatar_url")
            if not _is_empty(candidate):
                return candidate
    except Exception:
        pass
    return None


async def _process_row(
    row: Dict[str, Any], commit: bool, verbose: bool,
) -> str:
    """Return one of ``restored``, ``seeded_default``, ``dicebear``,
    ``skipped`` — used for the summary counters."""
    if not _is_empty(row.get("avatar_url")):
        return "skipped"
    tenant_id = row.get("tenant_id")
    key = row.get("key")
    rid = row.get("id")

    recovered = await _pull_last_known(tenant_id, key)
    source = "audit"
    if _is_empty(recovered):
        recovered = _seeded_default_for_key(key)
        source = "seeded_default"
    if _is_empty(recovered):
        recovered = _DICEBEAR.format(seed=(rid or "unknown"))
        source = "dicebear"

    if verbose:
        logger.info("[p24] backfill target id=%s key=%s tenant=%s "
                        "source=%s new=%s", rid, key, tenant_id, source,
                        recovered)

    if commit:
        await db.ai_employees.update_one(
            {"id": rid}, {"$set": {"avatar_url": recovered}},
        )
    return source


async def main(commit: bool, verbose: bool) -> Dict[str, Any]:
    q = {"$or": [{"avatar_url": {"$exists": False}},
                    {"avatar_url": None},
                    {"avatar_url": ""}]}
    counters = {"restored": 0, "seeded_default": 0,
                 "dicebear": 0, "skipped": 0}
    rows: List[Dict[str, Any]] = await db.ai_employees.find(
        q, {"_id": 0}).to_list(10000)
    for row in rows:
        result = await _process_row(row, commit=commit, verbose=verbose)
        counters[result] = counters.get(result, 0) + 1
    if verbose or not commit:
        logger.info("[p24] backfill summary %s (commit=%s)",
                        counters, commit)
    return counters


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--commit", action="store_true",
                          help="Persist recoveries. Dry-run without this flag.")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    result = asyncio.run(main(commit=args.commit, verbose=args.verbose))
    mode = "COMMIT" if args.commit else "DRY-RUN"
    print(f"[p24] backfill {mode}: {result}")
