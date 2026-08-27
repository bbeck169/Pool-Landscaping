"""Feb 2026 · Persona avatar_url backfill — idempotent boot migration
wrapping ``scripts/backfill_persona_avatar_urls.py``.

Why a wrapper?
--------------
The original script under ``scripts/`` is a CLI entry point that
loads ``.env`` and opens its own Mongo client. This module exposes
the SAME backfill logic as an ``async`` function reusing the
``config.db`` handle so ``server.py`` can call it as one of the
boot-migration steps AND the admin-triggered
``POST /api/admin/migrations/backfill-persona-avatars`` endpoint can
re-run it (with ``force=True``) against production.

Contract:
  * Runs once per environment — guarded by a sentinel doc in
    ``db.migrations`` (``id: 'feb2026_persona_avatar_url_v1'``).
  * ``force=True`` bypasses the sentinel and re-runs unconditionally
    (used by the admin endpoint for prod re-runs after the sentinel
    has already fired).
  * Sets ``avatar_url = "/avatars/personas/{key}.jpg"`` on every
    ``ai_employees`` doc whose ``key`` is one of the 10 canonical
    admin personas AND whose stored value doesn't already match.
    These are STATIC frontend assets shipped with the app under
    ``/app/frontend/public/avatars/personas/``  — the "Pixar
    portraits" the user asked to see — NOT user-uploaded media, so
    no object-storage migration is involved for them.
  * Emits a summary log at INFO with per-outcome counts.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict

from config import db


logger = logging.getLogger("persona_avatar_backfill")


_SENTINEL_ID = "feb2026_persona_avatar_url_v1"

# Canonical persona keys — must match ``routers/ai_employees.py``
# ``DEFAULT_EMPLOYEES`` seed table. Only these 10 admin personas
# ship shipped-with-app portraits under
# ``/app/frontend/public/avatars/personas/{key}.jpg``.
CANONICAL_KEYS = frozenset({
    "casey", "emmie", "buddy", "vizzy", "dexter",
    "soshie", "scouty", "commet", "skedra", "billy",
})


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _expected_url(key: str) -> str:
    return f"/avatars/personas/{key}.jpg"


async def backfill_persona_avatar_urls(*, force: bool = False) -> Dict[str, Any]:
    """Idempotent backfill. ``force=True`` bypasses the sentinel.

    Returns::

        {
          "skipped": bool,     # True if sentinel says already ran
          "reason":  str,      # only when skipped=True
          "ran_at":  str,      # ISO timestamp (any run)
          "total":   int,      # ai_employees docs scanned
          "updated": int,      # docs written
          "skipped_up_to_date": int,
          "unknown_key": int,  # docs with non-canonical persona key
          "errored":  int,
          "forced":  bool,     # True when force=True and sentinel existed
        }
    """
    sentinel = await db.migrations.find_one({"id": _SENTINEL_ID})
    if sentinel and not force:
        return {
            "skipped": True, "reason": "already_ran",
            "ran_at": sentinel.get("ran_at"),
            "total":   sentinel.get("total", 0),
            "updated": sentinel.get("updated", 0),
            "skipped_up_to_date": sentinel.get("skipped_up_to_date", 0),
            "unknown_key": sentinel.get("unknown_key", 0),
            "errored": sentinel.get("errored", 0),
            "forced": False,
        }

    total = 0
    updated = 0
    skipped_up_to_date = 0
    unknown_key = 0
    errored = 0

    cursor = db.ai_employees.find(
        {},
        {"_id": 0, "id": 1, "key": 1, "avatar_url": 1, "tenant_id": 1},
    )
    async for doc in cursor:
        total += 1
        key = (doc.get("key") or "").strip().lower()
        if key not in CANONICAL_KEYS:
            unknown_key += 1
            continue
        want = _expected_url(key)
        have = doc.get("avatar_url")
        if have == want:
            skipped_up_to_date += 1
            continue
        try:
            r = await db.ai_employees.update_one(
                {"id": doc["id"]}, {"$set": {"avatar_url": want}},
            )
            if r.modified_count == 1:
                updated += 1
            else:
                # matched=1, modified=0 → shouldn't happen after the
                # ``have != want`` check, but count defensively.
                skipped_up_to_date += 1
        except Exception as e:  # noqa: BLE001
            errored += 1
            logger.warning(
                "[persona-avatar] update failed tenant=%s key=%s: %s",
                doc.get("tenant_id"), key, e,
            )

    report = {
        "skipped": False,
        "ran_at": _now_iso(),
        "total": total,
        "updated": updated,
        "skipped_up_to_date": skipped_up_to_date,
        "unknown_key": unknown_key,
        "errored": errored,
        "forced": bool(sentinel and force),
    }

    if sentinel and force:
        # Update the existing sentinel with the latest run stats.
        await db.migrations.update_one(
            {"id": _SENTINEL_ID},
            {"$set": {"last_forced_run_at": report["ran_at"],
                       "last_forced_summary": {
                           k: v for k, v in report.items() if k != "skipped"
                       }}},
        )
    else:
        await db.migrations.insert_one({
            "id": _SENTINEL_ID,
            "ran_at": report["ran_at"],
            "total": total,
            "updated": updated,
            "skipped_up_to_date": skipped_up_to_date,
            "unknown_key": unknown_key,
            "errored": errored,
        })

    logger.info(
        "[persona-avatar] backfilled %d ai_employees (skipped_up_to_date=%d, "
        "unknown_key=%d, errored=%d, total=%d, forced=%s)",
        updated, skipped_up_to_date, unknown_key, errored, total,
        report["forced"],
    )
    return report
