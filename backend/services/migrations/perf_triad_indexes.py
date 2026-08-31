"""Phase B Perf Triad · Feb-2026 — Missing (tenant_id, 1) indexes.

Idempotent one-shot migration that ensures a ``(tenant_id, 1)``
index exists on every collection carrying a ``tenant_id`` field.
Second-run reports 0 created, N already-existed.

Runs at boot via the ``perf_triad_indexes_v1`` sentinel in
``db.migration_status`` so a healthy pod only pays the cost on
the first cold boot after this ships.

Index naming: ``perf_triad_<coll>_tenant_id`` — the ``perf_triad_``
prefix lets ops sweep them all in a rollback:

    for name in db.<coll>.list_indexes():
        if name.startswith("perf_triad_"):
            db.<coll>.drop_index(name)

Non-goals:
  * Compound indexes for F3 scans — those live in their owning
    routers' ``ensure_indexes`` helpers. This migration ONLY adds
    the missing single-field ``(tenant_id, 1)`` index.
  * Does NOT change existing indexes. Skips a collection if it
    already has a ``tenant_id_1`` or any index whose keys start
    with ``tenant_id: 1``.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Tuple

logger = logging.getLogger("services.migrations.perf_triad_indexes")

MIGRATION_KEY = "perf_triad_indexes_v1"

# Names / substrings that MUST be excluded from the sweep.
_EXCLUDED_COLLECTIONS = {
    "system.indexes", "system.views", "system.profile",
}


async def _has_tenant_id_index(coll: Any) -> bool:
    """True when the collection already carries an index whose FIRST
    key is ``tenant_id`` ascending (single or compound)."""
    async for idx in coll.list_indexes():
        key = idx.get("key") or {}
        # Mongo returns key as SON preserving insertion order.
        keys = list(key.items())
        if keys and keys[0] == ("tenant_id", 1):
            return True
    return False


async def run(db: Any) -> Dict[str, Any]:
    """Ensure ``(tenant_id, 1)`` index on every tenant-scoped
    collection.  Idempotent + sentinel-gated."""
    sentinel = await db.migration_status.find_one(
        {"key": MIGRATION_KEY}, {"_id": 0},
    )
    if sentinel and sentinel.get("completed_at"):
        return {
            "ok": True, "skipped": True,
            "reason": "sentinel present",
            "created": 0, "already": 0,
        }

    created: List[str] = []
    already: List[str] = []
    for name in sorted(await db.list_collection_names()):
        if name in _EXCLUDED_COLLECTIONS:
            continue
        coll = db[name]
        try:
            probe = await coll.find_one(
                {"tenant_id": {"$exists": True}}, {"_id": 1},
            )
        except Exception as exc:                             # noqa: BLE001
            logger.warning("[perf-triad] probe %s failed: %s", name, exc)
            continue
        if probe is None:
            continue
        try:
            if await _has_tenant_id_index(coll):
                already.append(name)
                continue
            index_name = f"perf_triad_{name}_tenant_id"
            await coll.create_index(
                [("tenant_id", 1)], name=index_name, background=True,
            )
            created.append(name)
        except Exception as exc:                             # noqa: BLE001
            logger.warning(
                "[perf-triad] create_index on %s failed: %s", name, exc,
            )
            continue

    from datetime import datetime, timezone
    await db.migration_status.update_one(
        {"key": MIGRATION_KEY},
        {"$set": {
            "key": MIGRATION_KEY,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "summary": {
                "created_count": len(created),
                "already_count": len(already),
                "created": created,
                "already": already,
            },
        }},
        upsert=True,
    )
    logger.info(
        "[perf-triad] indexes: created=%d already=%d",
        len(created), len(already),
    )
    print(
        f"[perf-triad] Created {len(created)} new indexes, "
        f"{len(already)} already existed.",
    )
    return {
        "ok": True, "skipped": False,
        "created": len(created), "already": len(already),
        "created_names": created,
    }
