"""Phase O4 · Feb-2026 — idempotency_keys index hardening.

Sentinel: ``idempotency_keys_indexes_v1``. Idempotent + sentinel-
guarded. Creates two indexes on ``db.idempotency_keys``:

  1. Unique compound on ``(tenant_id, key, endpoint)`` — closes the
     race window in ``utils_idempotency.store_response``'s upsert.
     Two concurrent requests with the same header would previously
     both land in the ``find_one → None`` branch and race the
     insert; with this index, the loser gets a DuplicateKey which
     the caller silently swallows.
  2. TTL on ``expires_at`` (``expireAfterSeconds: 0``) — reaps rows
     as soon as the persisted ``datetime`` crosses ``now``. Replaces
     the previous "check on read + delete" cleanup pattern that
     left GC to organic access.

Legacy-row backfill: rows written before Phase O4 stored
``expires_at`` as an ISO string, which the Mongo TTL index cannot
read. The migration bulk-deletes any legacy string-typed
``expires_at`` rows (they're already >24h old and safe to drop).

Runs on every boot; the sentinel guards against re-creation cost.
Force-run via the super-admin ``POST /admin/migrations/
idempotency-keys-indexes`` endpoint.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from config import db


logger = logging.getLogger("idempotency_keys_indexes_migration")

_SENTINEL_ID = "idempotency_keys_indexes_v1"


async def _sentinel_row() -> Optional[Dict[str, Any]]:
    return await db.migrations.find_one({"id": _SENTINEL_ID}, {"_id": 0})


async def _write_sentinel(summary: Dict[str, Any]) -> None:
    await db.migrations.update_one(
        {"id": _SENTINEL_ID},
        {"$set": {
            "id": _SENTINEL_ID,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "summary": summary,
        }},
        upsert=True,
    )


async def run_idempotency_keys_indexes_migration(
    *, force: bool = False,
) -> Dict[str, Any]:
    """Create the unique + TTL indexes if missing. Idempotent.

    Returns::

        {"status": "ok" | "skipped",
         "summary": {
             "indexes_created":       <int>,
             "already_present":       <int>,
             "legacy_strings_purged": <int>,
             "errors":                [...],
         }}
    """
    if not force:
        sentinel = await _sentinel_row()
        if sentinel:
            return {"status": "skipped",
                    "reason": "sentinel_present",
                    "sentinel": sentinel}

    summary: Dict[str, Any] = {
        "indexes_created": 0,
        "already_present": 0,
        "legacy_strings_purged": 0,
        "errors": [],
    }

    # Phase 1 — Purge legacy rows with ``expires_at`` stored as a
    # string. The TTL index refuses to reap them anyway and they're
    # older than the old 24h window by definition (Phase 40 launch
    # was months ago). Doing this BEFORE creating the unique index
    # so we don't blow up on any accidental duplicate legacy rows.
    try:
        res = await db.idempotency_keys.delete_many(
            {"expires_at": {"$type": "string"}},
        )
        summary["legacy_strings_purged"] = int(res.deleted_count or 0)
    except Exception as exc:                                       # noqa: BLE001
        summary["errors"].append({"stage": "legacy_purge",
                                    "error": str(exc)})
        logger.warning(
            "[idempotency_keys] legacy string purge failed: %s", exc,
        )

    # Phase 2 — Unique compound index on (tenant_id, key, endpoint).
    try:
        existing = set()
        async for idx in db.idempotency_keys.list_indexes():
            existing.add(idx.get("name") or "")
        if "idem_key_tenant_endpoint_uniq" in existing:
            summary["already_present"] += 1
        else:
            await db.idempotency_keys.create_index(
                [("tenant_id", 1), ("key", 1), ("endpoint", 1)],
                name="idem_key_tenant_endpoint_uniq",
                unique=True,
            )
            summary["indexes_created"] += 1
    except Exception as exc:                                       # noqa: BLE001
        summary["errors"].append({"stage": "unique_index",
                                    "error": str(exc)})
        logger.warning(
            "[idempotency_keys] unique index failed: %s", exc,
        )

    # Phase 3 — TTL index on ``expires_at``.
    try:
        existing = set()
        async for idx in db.idempotency_keys.list_indexes():
            existing.add(idx.get("name") or "")
        if "idem_key_expires_ttl" in existing:
            summary["already_present"] += 1
        else:
            await db.idempotency_keys.create_index(
                [("expires_at", 1)],
                name="idem_key_expires_ttl",
                expireAfterSeconds=0,
            )
            summary["indexes_created"] += 1
    except Exception as exc:                                       # noqa: BLE001
        summary["errors"].append({"stage": "ttl_index",
                                    "error": str(exc)})
        logger.warning(
            "[idempotency_keys] TTL index failed: %s", exc,
        )

    await _write_sentinel(summary)
    logger.info(
        "[idempotency_keys] indexes_created=%s already_present=%s "
        "legacy_purged=%s errors=%s",
        summary["indexes_created"], summary["already_present"],
        summary["legacy_strings_purged"], len(summary["errors"]),
    )
    return {"status": "ok", "summary": summary}
